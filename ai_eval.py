#!/usr/bin/env python3
# =============================================================================
# 智能諸葛亮 v12 — AI 覆核離線回溯評分
# -----------------------------------------------------------------------------
# 問題：`BACKTEST.md` 裡每一個數字都是 AI 覆核「關掉」時跑出來的
#       （backtest.py 第 140 行 AI_REVIEW_ENABLED=0），所以這道關卡對獲利因子
#       是正貢獻還是負貢獻，從來沒有被量測過。
#
# 這支腳本回答：**AI 覆核攔掉的那些單，實際結算是賺還是賠？**
#
# 做法：把 ai_training/sft_dataset.jsonl 裡已經有實際損益的歷史訊號，
#       重新丟給 AI 評分，再跟已知的 outcome 對帳。
#
# 設計原則（跟 backtest.py 一致）：**直接呼叫 main.py 的 review()**，
#   不在這裡重寫 prompt 組裝與回應解析。量到的就是實盤在跑的那一套。
#
# ⚠️ 防止 look-ahead bias：main.py 的 few-shot 是「最近 3 筆虧損教訓」。
#   評分第 N 筆訊號時，只會用到「在第 N 筆進場之前就已經平倉」的虧損，
#   否則就是拿未來資訊評估過去，結果會虛假地好看。見 build_few_shot()。
#
# 用法：
#   # 先驗管線，不打 API、不花錢（隨機基準線）
#   python3 ai_eval.py sft_dataset.jsonl --provider random
#
#   # 量現行的 Gemini
#   python3 ai_eval.py sft_dataset.jsonl --provider gemini --rules trading_rules.txt
#
#   # 量 Claude（第一方 API）
#   ANTHROPIC_API_KEY=... python3 ai_eval.py sft_dataset.jsonl --provider claude
#
#   # 量 Claude（Vertex AI，沿用 gcloud ADC）
#   python3 ai_eval.py sft_dataset.jsonl --provider claude --vertex \
#       --gcp-project my-project --region global
#
# 資料取得：
#   gsutil cp gs://zhuge-risk-manager-bucket/ai_training/sft_dataset.jsonl .
#   gsutil cp gs://zhuge-risk-manager-bucket/ai_training/trading_rules.txt .
# =============================================================================
import argparse
import contextlib
import io
import json
import os
import sys
from datetime import datetime, timezone

from backtest import install_stubs

RULES_MAX_CHARS = 4000        # 對齊 main.py get_trading_rules()
FEW_SHOT_LIMIT = 3            # 對齊 main.py get_dynamic_few_shot(limit=3)
FEW_SHOT_SCAN = 300           # 對齊 main.py 只掃最後 300 筆
ENTRY_TOLERANCE_SEC = 120     # 對齊 main.py pair_trade_result() 的 +120 秒寬容


# =============================================================================
# 1. 載入 main.py（沿用 backtest.py 的 stub），並解開 AI 覆核
# =============================================================================
def load_main(quiet=True):
    """import main.py，但把 AI 覆核打開——backtest.py 是關著的，我們要量它。"""
    install_stubs()
    os.environ["AI_REVIEW_ENABLED"] = "1"
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer if quiet else sys.stdout):
        import main as m

    # install_stubs() 讓 genai.Client 變成假的，所以 m.ai_review_session.client
    # 是個沒有 .models 的空殼。下面 attach_reviewer() 會換成真的轉接器。
    m.AI_REVIEW_ENABLED = True
    m.AI_FAIL_OPEN = False        # 評分時 API 失敗一律記為錯誤，不混進判別力統計
    return m


def attach_reviewer(m, backend, rules_text, few_shot_getter):
    """把 main.ai_review_session 的 client 換成我們的轉接器，並攔截兩個會打 GCS
    的 pipeline 函式。這樣 review() 走的還是 main.py 原本的 prompt 與解析路徑。"""
    m.ai_review_session.client = backend
    m.sft_pipeline_session.get_trading_rules = lambda: rules_text
    m.sft_pipeline_session.get_dynamic_few_shot = lambda limit=FEW_SHOT_LIMIT: few_shot_getter()


# =============================================================================
# 1b. 搶救真的 google 套件
#     install_stubs() 會把 google.* 換成假模組——main.py import 時需要這些假貨，
#     但真的要打 Vertex（gemini 後端、或 Claude --vertex 的 ADC 認證）時需要真貨。
#     main.py 只在 import 當下讀 sys.modules，import 完就持有自己的綁定，
#     所以這裡先把真的載進來快照，load_main() 之後再還原回去。
# =============================================================================
def preimport_google(provider, vertex):
    """回傳快照；provider 不需要真 google 時回傳 None。"""
    wanted = []
    if provider == "gemini":
        wanted += ["google.genai", "google.genai.types", "google.auth"]
    elif provider == "claude" and vertex:
        wanted += ["google.auth"]          # AnthropicVertex 走 ADC
    if not wanted:
        return None

    import importlib
    loaded = False
    for name in wanted:
        try:
            importlib.import_module(name)
            loaded = True
        except ImportError:
            pass
    if not loaded:
        return None
    google = sys.modules.get("google")
    return ({k: v for k, v in sys.modules.items() if k == "google" or k.startswith("google.")},
            dict(vars(google)) if google else None)


def restore_google(snapshot):
    """把 install_stubs() 蓋掉的 google.* 換回真貨。"""
    if not snapshot:
        return
    real_modules, google_vars = snapshot
    for key in [k for k in sys.modules if k == "google" or k.startswith("google.")]:
        if key not in real_modules:
            del sys.modules[key]
    sys.modules.update(real_modules)
    if google_vars is not None and "google" in sys.modules:
        namespace = vars(sys.modules["google"])
        namespace.clear()
        namespace.update(google_vars)       # 含 __path__，少了它 google.auth 會找不到


# =============================================================================
# 2. 讀 SFT 資料集
# =============================================================================
def parse_utc(text):
    """main.py 的 fmt_utc() 產出 'YYYY-MM-DD HH:MM:SS'（UTC）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def load_rows(path):
    """讀 sft_dataset.jsonl，只留下 meta 與 outcome 都完整的列。

    回傳依「進場時間」排序的 [{meta, profit, label, ticket, entry_ts, closed_ts}]。
    進場時間排序很重要：look-ahead 防護是以進場先後為準，而檔案本身是依
    「平倉先後」append 的（pair_trade_result 在平倉時才寫入）。"""
    rows, skipped = [], 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            meta, outcome = row.get("meta"), row.get("outcome")
            if not isinstance(meta, dict) or not isinstance(outcome, dict):
                skipped += 1           # 舊格式（沒有 meta）一律跳過，對齊 main.py 的做法
                continue
            profit = outcome.get("profit")
            if not isinstance(profit, (int, float)):
                skipped += 1
                continue
            entry_ts = parse_utc(meta.get("time_utc"))
            closed_ts = parse_utc(outcome.get("closed_utc"))
            if entry_ts is None:
                skipped += 1           # 沒有進場時間就無法做 look-ahead 防護
                continue
            rows.append({
                "meta": meta,
                "profit": float(profit),
                "label": outcome.get("label"),
                "ticket": str(outcome.get("ticket") or ""),
                "entry_ts": entry_ts,
                "closed_ts": closed_ts if closed_ts is not None else entry_ts,
            })
    rows.sort(key=lambda r: r["entry_ts"])
    return rows, skipped


def load_rules(path):
    """對齊 main.py get_trading_rules() 的組裝方式（含 4000 字元上限）。"""
    body = "目前無額外規則。"
    if path:
        text = open(path, encoding="utf-8").read().strip()
        if text:
            body = text[:RULES_MAX_CHARS]
    return "【自我反思與進化規則庫】\n" + body


# =============================================================================
# 2b. 資料集體檢：「0 筆可評分」有好幾種原因，這裡精確指出是哪一種
# =============================================================================
def inspect_dataset(path):
    """逐層拆解資料集，指出卡在哪一關。不需要任何雲端權限。"""
    stats = {"lines": 0, "blank": 0, "bad_json": 0, "not_dict": 0,
             "has_meta": 0, "has_outcome": 0, "numeric_profit": 0,
             "has_time_utc": 0, "parsed_time": 0}
    key_counter, bad_times, sample = {}, [], None

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stats["lines"] += 1
            line = line.strip()
            if not line:
                stats["blank"] += 1
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                stats["bad_json"] += 1
                continue
            if not isinstance(row, dict):
                stats["not_dict"] += 1
                continue
            for key in row:
                key_counter[key] = key_counter.get(key, 0) + 1
            if sample is None:
                sample = row

            meta, outcome = row.get("meta"), row.get("outcome")
            if not isinstance(meta, dict):
                continue
            stats["has_meta"] += 1
            if not isinstance(outcome, dict):
                continue
            stats["has_outcome"] += 1
            if isinstance(outcome.get("profit"), (int, float)):
                stats["numeric_profit"] += 1
            raw_time = meta.get("time_utc")
            if raw_time:
                stats["has_time_utc"] += 1
                if parse_utc(raw_time) is not None:
                    stats["parsed_time"] += 1
                elif len(bad_times) < 5:
                    bad_times.append(repr(raw_time))

    print("\n" + "=" * 70)
    print("🔬 資料集體檢")
    print("=" * 70)
    print(f"檔案：{path}")
    print(f"\n總行數 {stats['lines']}｜空行 {stats['blank']}｜非 JSON {stats['bad_json']}｜非物件 {stats['not_dict']}")
    print("\n逐層過濾（每一層都是前一層的子集）：")
    for label, key in [("有 meta 欄位", "has_meta"), ("＋有 outcome 欄位", "has_outcome"),
                       ("＋profit 是數字", "numeric_profit"), ("＋meta.time_utc 存在", "has_time_utc"),
                       ("＋time_utc 可解析", "parsed_time")]:
        print(f"  {label:<22} {stats[key]:>6}")

    if key_counter:
        print("\n實際出現的頂層欄位：")
        for key, count in sorted(key_counter.items(), key=lambda kv: -kv[1]):
            print(f"  {key:<20} {count:>6} 列")

    # --- 定位 ---------------------------------------------------------------
    print("\n【診斷】")
    if stats["lines"] == 0:
        print("  ❌ 檔案是空的。")
        print("     代表 pair_trade_result() 從來沒有成功配對過任何一筆交易。")
    elif stats["has_meta"] == 0:
        print("  ❌ 沒有任何一列帶 meta 欄位——全是舊格式。")
        print("     main.py:1100 也會忽略這些列，所以連實盤的 few-shot 都是空的。")
        print("     代表這些列是舊版程式寫的，之後就沒有新資料進來過。")
    elif stats["has_outcome"] == 0:
        print("  ❌ 有 meta 但沒有 outcome——配對流程寫到一半。")
    elif stats["numeric_profit"] == 0:
        print("  ❌ outcome.profit 不是數字。")
    elif stats["parsed_time"] == 0:
        print("  ❌ meta.time_utc 無法解析。實際值範例：")
        for text in bad_times:
            print(f"       {text}")
        print("     這個可以修——告訴我格式，我調整 parse_utc()。")
    else:
        print(f"  ✅ 有 {stats['parsed_time']} 列可評分。")

    if sample:
        print("\n第一列樣本（截斷）：")
        print("  " + json.dumps(sample, ensure_ascii=False)[:400])
    print("=" * 70)
    return stats


# =============================================================================
# 3. Look-ahead 防護：只用「當時已經知道」的虧損教訓
# =============================================================================
def build_few_shot(m, rows, index):
    """重建第 index 筆訊號進場當下，main.py 會拿到的 few-shot。

    規則：一筆虧損要能成為教訓，必須在本筆訊號**進場之前就已經平倉**
    （closed_ts <= entry_ts）。main.py 取的是「最近 append 的 3 筆 REJECT」，
    而 append 發生在平倉時，所以這裡依 closed_ts 由新到舊取前 3 筆。

    少了這個過濾，評估第 50 筆時會用到第 500 筆的教訓——整份評估就作廢了。"""
    cutoff = rows[index]["entry_ts"]
    known = [r for i, r in enumerate(rows) if i != index and r["closed_ts"] <= cutoff]
    known.sort(key=lambda r: r["closed_ts"])

    # main.py 是 reversed(rows[-300:]) 再挑前 3 筆 REJECT：300 的窗套用在
    # 「所有列」上，不是只套在虧損列上。順序錯了會多撈到更舊的教訓。
    lessons = []
    for r in reversed(known[-FEW_SHOT_SCAN:]):
        if r["label"] != "REJECT":
            continue
        lessons.append(f"- {m.format_signal_meta(r['meta'])} → 實盤結算 {r['profit']:+.2f}")
        if len(lessons) >= FEW_SHOT_LIMIT:
            break
    return ("【歷史虧損教訓 (Dynamic Few-Shot)】\n" + "\n".join(lessons)) if lessons else ""


# =============================================================================
# 3b. 自我驗證：證明 look-ahead 防護真的有效
#     整份評估的可信度全押在 build_few_shot() 上，所以它必須是可驗證的，
#     而不是靠註解宣稱。任何人都能用 --self-test 重跑這個證明。
# =============================================================================
def self_test(m, rows):
    """逐筆檢查 few-shot 裡沒有任何一筆是「當時還沒平倉」的交易。"""
    by_text = {m.format_signal_meta(r["meta"]): r for r in rows}
    leaks, used, empty = [], 0, 0

    for index, row in enumerate(rows):
        few_shot = build_few_shot(m, rows, index)
        if not few_shot:
            empty += 1
            continue
        for line in few_shot.splitlines():
            if not line.startswith("- "):
                continue
            used += 1
            signal_text = line[2:].split(" → 實盤結算 ")[0]
            source = by_text.get(signal_text)
            if source is None:
                continue
            if source["closed_ts"] > row["entry_ts"]:
                leaks.append((index, source["closed_ts"] - row["entry_ts"]))
            if source["label"] != "REJECT":
                leaks.append((index, "非虧損單混入教訓"))

    print("\n" + "=" * 70)
    print("🛡️  Look-ahead 防護自我驗證")
    print("=" * 70)
    print(f"檢查 {len(rows)} 筆訊號，共引用 {used} 條教訓（其中 {empty} 筆無可用教訓）")
    if leaks:
        print(f"❌ 發現 {len(leaks)} 條洩漏：")
        for index, detail in leaks[:10]:
            print(f"   第 {index} 筆：{detail}")
        print("   評估結果不可信，請勿採用。")
        return False
    print("✅ 沒有任何教訓來自「該訊號進場後才平倉」的交易。")

    # 對照組：故意關掉時間過濾，確認這個測試抓得到問題（不然測試本身沒意義）
    naive_leaks = 0
    for index, row in enumerate(rows):
        recent = [r for i, r in enumerate(rows) if i < index and r["label"] == "REJECT"]
        naive_leaks += sum(1 for r in recent[-FEW_SHOT_LIMIT:] if r["closed_ts"] > row["entry_ts"])
    print(f"✅ 對照：改用「檔案順序前 N 筆」的天真做法會產生 {naive_leaks} 條洩漏"
          f"{'（測試有鑑別力）' if naive_leaks else '（此資料集看不出差異，換一份重疊更多的樣本再驗）'}")
    print("=" * 70)
    return True


# =============================================================================
# 4. 三種評分後端
#    每個後端都長得像 genai 的 client：.models.generate_content(...) → .text
#    這樣 main.py 的 review() 完全不用改就能驅動。
# =============================================================================
class _Reply:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, fn):
        self.generate_content = fn


class RandomBackend:
    """隨機基準線：不打 API、不花錢。

    這不只是管線測試——它是一個有意義的對照組：如果真實模型的表現跟
    「隨機拒絕同樣比例的單」沒有差別，那這道關卡就沒有判別力。"""

    def __init__(self, approve_rate=0.7, seed=20260918):
        self.approve_rate, self.seed = approve_rate, seed
        self.models = _Models(self._generate)

    def _generate(self, model=None, contents=None, config=None):
        import hashlib
        digest = hashlib.sha256(f"{self.seed}|{contents}".encode()).digest()
        score = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
        verdict = "APPROVE" if score < self.approve_rate else "REJECT"
        return _Reply(f"{verdict} | 隨機基準線 score={score:.3f}")


class GeminiBackend:
    """現行的 Vertex AI Gemini。設定對齊 main.py _config()。"""

    def __init__(self, model, location, thinking_budget=0):
        from google import genai
        from google.genai import types
        self._types = types
        self.model, self.thinking_budget = model, thinking_budget
        self.client = genai.Client(vertexai=True, location=location)
        self.models = _Models(self._generate)

    def _generate(self, model=None, contents=None, config=None):
        # 忽略 main.py 傳進來的 config（它是 install_stubs 造出來的假物件），
        # 用同樣的參數自己組一份真的。
        kwargs = {"temperature": 0.0, "max_output_tokens": 256}
        try:
            kwargs["thinking_config"] = self._types.ThinkingConfig(thinking_budget=self.thinking_budget)
        except Exception:
            pass
        reply = self.client.models.generate_content(
            model=self.model, contents=contents,
            config=self._types.GenerateContentConfig(**kwargs))
        return _Reply(reply.text or "")


class ClaudeBackend:
    """Claude，走第一方 API 或 Vertex AI。

    跟 Gemini 的三個差異（見遷移討論）：
      1. temperature 在 Claude 4.6 以後已移除，送出去會 400 → 不送。
      2. 沒有 thinking_budget；用 output_config.effort 控制思考深度。
      3. 思考是預設開啟的，max_tokens 若只給 256 可能全被 thinking 吃掉，
         所以放寬到 2048，再從 content 裡只取 text block。
    """

    def __init__(self, model, effort="low", max_tokens=2048,
                 vertex=False, gcp_project=None, region="global"):
        import anthropic
        if vertex:
            self.client = anthropic.AnthropicVertex(project_id=gcp_project, region=region)
        else:
            self.client = anthropic.Anthropic()
        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        self.models = _Models(self._generate)

    def _generate(self, model=None, contents=None, config=None):
        reply = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": contents}],
        )
        if reply.stop_reason == "refusal":
            raise RuntimeError(f"模型拒答：{getattr(reply.stop_details, 'category', None)}")
        text = "".join(b.text for b in reply.content if b.type == "text")
        return _Reply(text.strip())


def build_backend(args):
    if args.provider == "random":
        return RandomBackend(approve_rate=args.random_approve_rate)
    if args.provider == "gemini":
        return GeminiBackend(args.model or "gemini-2.5-flash", args.region_gemini,
                             thinking_budget=args.thinking_budget)
    return ClaudeBackend(args.model or "claude-opus-5", effort=args.effort,
                         vertex=args.vertex, gcp_project=args.gcp_project, region=args.region)


# =============================================================================
# 5. 評分主迴圈（可中斷續跑）
# =============================================================================
def load_cache(path):
    """已經評過的列不重打 API——中途掛掉不會白花錢。"""
    cache = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("key"):
                    cache[row["key"]] = row
    return cache


def row_key(row, index):
    return row["ticket"] or f"idx-{index}-{int(row['entry_ts'])}"


def score_rows(m, rows, backend, rules_text, cache, out_path, score_from=0, verbose=False):
    """rows 一律傳「完整」資料集，score_from 之後的才評分。

    --limit 只縮評分範圍、不縮 few-shot 歷史池：否則被限制掉的早期訊號
    會連帶讓 few-shot 變空，prompt 就跟實盤長得不一樣了。"""
    results, pending = [], {"few_shot": ""}
    attach_reviewer(m, backend, rules_text, lambda: pending["few_shot"])
    handle = open(out_path, "a", encoding="utf-8") if out_path else None
    targets = list(enumerate(rows))[score_from:]

    try:
        for index, row in targets:
            key = row_key(row, index)
            if key in cache:
                results.append({**row, **cache[key]})
                continue

            pending["few_shot"] = build_few_shot(m, rows, index)
            try:
                # review() 內部固定印「🔍 [Vertex AI 原始回應]」，換供應商後會誤導，
                # 而且逐筆洗版；--verbose 會用我們自己的格式重印。
                noise = io.StringIO()
                with contextlib.redirect_stdout(noise):
                    approved, reason = m.ai_review_session.review(row["meta"])
                error = None
            except Exception as exc:                       # 後端自己拋的例外（如拒答）
                approved, reason, error = None, f"{type(exc).__name__}: {exc}"[:200], True

            # main.py 的 _fallback 會在 API 出錯時回傳 AI_FAIL_OPEN(=False)。
            # 那是「錯誤」不是「判斷」，不能混進判別力統計——用理由字串認出來。
            if error is None and not approved and "→ 依 AI_FAIL_OPEN" in reason:
                error = True

            verdict = {"key": key, "approved": approved, "reason": reason, "error": bool(error)}
            results.append({**row, **verdict})
            if handle:
                handle.write(json.dumps(verdict, ensure_ascii=False) + "\n")
                handle.flush()

            if verbose:
                mark = "⚠️" if error else ("✅" if approved else "❌")
                print(f"  {mark} [{index + 1}/{len(rows)}] {m.format_signal_meta(row['meta'])[:60]} "
                      f"→ 實際 {row['profit']:+.2f} | {reason[:60]}", flush=True)
            elif (index - score_from + 1) % 25 == 0:
                print(f"  …已評分 {index - score_from + 1}/{len(targets)}", flush=True)
    finally:
        if handle:
            handle.close()
    return results


# =============================================================================
# 6. 指標
# =============================================================================
def profit_factor(profits):
    gross_profit = sum(p for p in profits if p > 0)
    gross_loss = -sum(p for p in profits if p < 0)
    if gross_loss <= 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def fmt_pf(value):
    return "∞" if value == float("inf") else f"{value:.2f}"


def report(results, args):
    scored = [r for r in results if not r["error"] and r["approved"] is not None]
    errors = [r for r in results if r["error"]]

    print("\n" + "=" * 70)
    print("📊 AI 覆核判別力報告")
    print("=" * 70)
    print(f"樣本：{len(results)} 筆已配對訊號｜成功評分 {len(scored)}｜API 錯誤 {len(errors)}")
    if not scored:
        print("⚠️ 沒有任何成功評分，無法產出指標。")
        return

    approved = [r for r in scored if r["approved"]]
    rejected = [r for r in scored if not r["approved"]]

    # --- 混淆矩陣 ---------------------------------------------------------
    def bucket(rows_, win):
        return [r for r in rows_ if (r["profit"] > 0) == win]

    hit = bucket(rejected, False)        # AI 拒 × 實際虧 → 正確攔截
    miss_kill = bucket(rejected, True)   # AI 拒 × 實際賺 → 誤殺（最貴）
    pass_win = bucket(approved, True)    # AI 准 × 實際賺 → 正確放行
    pass_loss = bucket(approved, False)  # AI 准 × 實際虧 → 漏放

    print(f"\n【混淆矩陣】  拒絕率 {len(rejected) / len(scored) * 100:.1f}%")
    print(f"  ✅ 正確攔截（拒×虧）  {len(hit):4d} 筆   避開虧損 {-sum(r['profit'] for r in hit):10.2f}")
    print(f"  ❌ 誤殺（拒×賺）      {len(miss_kill):4d} 筆   放棄獲利 {sum(r['profit'] for r in miss_kill):10.2f}")
    print(f"  ⬜ 正確放行（准×賺）  {len(pass_win):4d} 筆")
    print(f"  ⬜ 漏放（准×虧）      {len(pass_loss):4d} 筆")

    # --- 頭號指標：攔掉的單總共是賺是賠 -----------------------------------
    rejected_pnl = sum(r["profit"] for r in rejected)
    print(f"\n【頭號指標】AI 攔掉的 {len(rejected)} 筆，實際結算合計 {rejected_pnl:+.2f}")
    if rejected_pnl > 0:
        print("  🔴 這些單原本是賺錢的 → AI 覆核正在虧你的錢。")
    elif rejected_pnl < 0:
        print("  🟢 這些單原本是虧錢的 → AI 覆核有正貢獻。")
    else:
        print("  ⚪ 淨效果為零。")

    # --- 獲利因子對比 -----------------------------------------------------
    pf_all = profit_factor([r["profit"] for r in scored])
    pf_approved = profit_factor([r["profit"] for r in approved])
    delta = "—"
    if pf_all not in (0.0, float("inf")) and pf_approved != float("inf"):
        delta = f"{(pf_approved - pf_all) / pf_all * 100:+.1f}%"
    print(f"\n【獲利因子】全體 {fmt_pf(pf_all)} → AI 放行後 {fmt_pf(pf_approved)}  ({delta})")

    # --- 誤殺佔毛利比重：對照 PF 1.15 的 13% 生死線 -----------------------
    gross_profit = sum(r["profit"] for r in scored if r["profit"] > 0)
    killed = sum(r["profit"] for r in miss_kill)
    if gross_profit > 0:
        share = killed / gross_profit * 100
        # PF 1.15 代表毛利/毛損=115/100，淨利 15；砍掉 15/115≈13% 的毛利就歸零。
        breakeven = (1 - 1 / pf_all) * 100 if pf_all > 1 else 0.0
        print(f"\n【誤殺佔毛利】{killed:.2f} / {gross_profit:.2f} = {share:.1f}%")
        print(f"  以全體 PF {fmt_pf(pf_all)} 計算，砍掉 {breakeven:.1f}% 的毛利就會讓 PF 掉到 1.00。")
        if pf_all > 1 and share >= breakeven:
            print("  🔴 誤殺已經超過生死線——這道關卡正在吃掉整個優勢。")

    print(f"\n樣本期間：{datetime.fromtimestamp(scored[0]['entry_ts'], timezone.utc):%Y-%m-%d} → "
          f"{datetime.fromtimestamp(scored[-1]['entry_ts'], timezone.utc):%Y-%m-%d}")
    if args.provider == "random":
        print("\n⚠️ 這是隨機基準線，不是真實模型。真實模型必須明顯優於這組數字才算有判別力。")
    print("=" * 70)


# =============================================================================
# 7. CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="AI 覆核離線回溯評分：量測這道關卡對獲利因子的實際貢獻。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", help="sft_dataset.jsonl 的路徑")
    parser.add_argument("--rules", help="trading_rules.txt 的路徑（不給則用「目前無額外規則。」）")
    parser.add_argument("--provider", choices=["random", "gemini", "claude"], default="random",
                        help="random＝不打 API 的對照組（預設）")
    parser.add_argument("--model", help="模型 ID（gemini 預設 gemini-2.5-flash；claude 預設 claude-opus-5）")
    parser.add_argument("--limit", type=int, help="只評分最近 N 筆")
    parser.add_argument("--out", help="verdict 快取檔（可中斷續跑，避免重複付費）")
    parser.add_argument("--verbose", action="store_true", help="逐筆列印")
    parser.add_argument("--self-test", action="store_true",
                        help="只驗證 look-ahead 防護，不評分、不打 API")
    parser.add_argument("--inspect", action="store_true",
                        help="資料集體檢：指出「0 筆可評分」卡在哪一關，不打 API")
    parser.add_argument("--yes", action="store_true", help="跳過花費確認")
    # Claude
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"],
                        help="Claude 思考深度（預設 low：對應現行 thinking_budget=0）")
    parser.add_argument("--vertex", action="store_true", help="Claude 走 Vertex AI（用 gcloud ADC）")
    parser.add_argument("--gcp-project", help="--vertex 時的 GCP 專案 ID")
    parser.add_argument("--region", default="global", help="--vertex 時的區域（預設 global）")
    # Gemini
    parser.add_argument("--region-gemini", default="us-central1", help="Gemini 的 Vertex 區域")
    parser.add_argument("--thinking-budget", type=int, default=0, help="Gemini thinking budget")
    parser.add_argument("--random-approve-rate", type=float, default=0.7,
                        help="random 後端的放行率（預設 0.7）")
    args = parser.parse_args()

    if args.inspect:
        inspect_dataset(args.dataset)
        return 0

    rows, skipped = load_rows(args.dataset)
    if not rows:
        print("❌ 資料集裡沒有任何「meta + outcome + 進場時間」齊全的列。", file=sys.stderr)
        print("   用 --inspect 可以看出卡在哪一關：", file=sys.stderr)
        print(f"     python3 ai_eval.py {args.dataset} --inspect", file=sys.stderr)
        return 1
    score_from = max(0, len(rows) - args.limit) if args.limit else 0

    print(f"📂 載入 {len(rows)} 筆可評分訊號（略過 {skipped} 筆格式不符）")
    if score_from:
        print(f"   --limit {args.limit}：評分最後 {len(rows) - score_from} 筆，"
              f"前面 {score_from} 筆保留作為 few-shot 歷史池")
    print(f"   期間 {datetime.fromtimestamp(rows[0]['entry_ts'], timezone.utc):%Y-%m-%d} → "
          f"{datetime.fromtimestamp(rows[-1]['entry_ts'], timezone.utc):%Y-%m-%d}")

    cache = load_cache(args.out)
    scoring = list(enumerate(rows))[score_from:]
    todo = sum(1 for i, r in scoring if row_key(r, i) not in cache)
    if cache:
        print(f"♻️  快取命中 {len(scoring) - todo} 筆，本次需呼叫 {todo} 次")

    if args.provider != "random" and todo and not args.yes and not args.self_test:
        print(f"\n💰 將對 {args.provider} 發出 {todo} 次 API 呼叫（每次約 2.5–3.5K input tokens）。")
        if input("   繼續？[y/N] ").strip().lower() != "y":
            print("已取消。")
            return 0

    snapshot = preimport_google(args.provider, args.vertex)
    m = load_main()
    restore_google(snapshot)

    if args.self_test:
        return 0 if self_test(m, rows) else 1

    rules_text = load_rules(args.rules)
    print(f"📋 規則庫 {len(rules_text)} 字元｜🛡️ look-ahead 防護：few-shot 只取進場前已平倉的虧損")

    backend = build_backend(args)
    print(f"🤖 後端：{args.provider}"
          + (f"（{backend.model}）" if hasattr(backend, "model") else "") + "\n")

    results = score_rows(m, rows, backend, rules_text, cache, args.out,
                         score_from=score_from, verbose=args.verbose)
    report(results, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
