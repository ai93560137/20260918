#!/usr/bin/env python3
"""[R204] 🐉 龍飛陣覆盤：讀 GCS longfei/<產品>/latest.json（成交）同 decisions/<日>.json（決策），出 Markdown 報告。

用途：每日覆盤，搵出邊類單賺、邊類單蝕，提出「教學簿」（hsi_ai_trader/LESSONS.md）候選改動，
由使用者批准先寫入。只讀，唔落單、唔改任何設定。

    python3 scripts/longfei_review.py --fetch                 # 經 gcp_agent.py 讀 GCS，印報告
    python3 scripts/longfei_review.py --dir 某資料夾           # 離線：<產品>.json＋<產品>_decisions_*.json
    python3 scripts/longfei_review.py --fetch --days 7 --out 報告.md

原則（防過度擬合）：任何分組少過 MIN_N 筆唔出結論；候選教學要寫明樣本數；新教學生效後要同舊版本分開計。
"""
import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HKT = timezone(timedelta(hours=8))
PRODUCTS = ["HSI", "SPY", "QQQ", "DIA", "TLT", "HYG", "GLD", "USO", "IWM", "EWJ", "FXI", "EWT", "INDA", "EZU", "EWU", "EWZ", "EWC",
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
MIN_N = 10            # 分組最少筆數先下結論
ROOT = Path(__file__).resolve().parent.parent


# ---------------- 讀數據 ----------------
def _gcs_cat(obj):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gcp_agent.py"), "cat", "--object", obj],
                       capture_output=True, text=True, timeout=90)
    text = r.stdout
    i = min([k for k in (text.find("{"), text.find("[")) if k >= 0] or [-1])   # 跳過開頭嘅提示行
    if r.returncode != 0 or i < 0:
        return None
    try:
        return json.loads(text[i:])
    except ValueError:
        return None


def fetch(days, base="longfei"):
    """base：模擬倉 longfei、真倉 longfei/real（R209）。"""
    out = {}
    today = datetime.now(HKT).date()
    for p in PRODUCTS:
        doc = _gcs_cat(f"{base}/{p}/latest.json")
        if not isinstance(doc, dict):
            continue
        decs = []
        for k in range(days):
            arr = _gcs_cat(f"{base}/{p}/decisions/{(today - timedelta(days=k)).isoformat()}.json")
            if isinstance(arr, list):
                decs += arr
        out[p] = {"status": doc.get("status") or {}, "trades": doc.get("trades") or [],
                  "decisions": _merge_decs(decs, doc.get("decisions") or [])}
    return out


def _merge_decs(archived, recent):
    """存檔（R204 部署後先有）＋ latest.json 最近 30 個決策，按 ts 去重。"""
    seen, out = set(), []
    for x in list(archived) + list(recent):
        if isinstance(x, dict) and x.get("ts") not in seen:
            seen.add(x.get("ts"))
            out.append(x)
    return sorted(out, key=lambda x: str(x.get("ts") or ""))


def load_dir(d):
    out = {}
    for p in PRODUCTS:
        f = Path(d) / f"{p}.json"
        if not f.exists():
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        decs = []
        for g in sorted(Path(d).glob(f"{p}_decisions_*.json")):
            decs += json.loads(g.read_text(encoding="utf-8"))
        out[p] = {"status": doc.get("status") or {}, "trades": doc.get("trades") or [],
                  "decisions": _merge_decs(decs, doc.get("decisions") or [])}
    return out


# ---------------- 計數 ----------------
def stats(rows, key="pnl_hkd_gross"):
    vals = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
    n = len(vals)
    if not n:
        return {"n": 0}
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    cum = peak = dd = 0.0
    for v in vals:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    rs = [float(r["r_multiple"]) for r in rows if isinstance(r.get("r_multiple"), (int, float))]
    return {"n": n, "win": len(wins) / n, "sum": sum(vals), "avg": sum(vals) / n,
            "pf": (sum(wins) / sum(losses)) if losses else None,
            "rrr": ((sum(wins) / len(wins)) / (sum(losses) / len(losses))) if wins and losses else None,
            "dd": dd, "avg_r": (sum(rs) / len(rs)) if rs else None}


def t_stat(vals):
    n = len(vals)
    if n < 3:
        return None
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else None


def closes(data):
    rows = []
    for p, d in data.items():
        last_open = None
        for t in sorted(d["trades"], key=lambda t: str(t.get("ts") or "")):
            if t.get("type") == "OPEN":
                last_open = t
            elif t.get("type") == "CLOSE":
                row = {**t, "product": p}
                if last_open:   # 舊紀錄 CLOSE 冇入場資料：由對應 OPEN 補
                    for k_close, k_open in (("open_reason", "reason"), ("confidence", "confidence"),
                                            ("open_session", "session"), ("lessons", "lessons"),
                                            ("model", "model")):
                        if row.get(k_close) is None and last_open.get(k_open) is not None:
                            row[k_close] = last_open[k_open]
                rows.append(row)
                last_open = None
    rows.sort(key=lambda r: str(r.get("ts") or ""))
    return rows


def exit_kind(reason, points=None):
    r = str(reason or "")
    if r.startswith("止蝕"):
        return "移動止蝕（鎖利）" if (points or 0) > 0 else "止蝕"
    if r.startswith("止賺"):
        return "止賺"
    if r.startswith("AI"):
        return "AI 平倉"
    if "外部" in r:
        return "外部平倉"
    if "停機" in r or "STOP" in r or "轉倉" in r:
        return "停機／轉倉"
    return "其他"


def hour_bucket(ts):
    try:
        return f"{datetime.fromisoformat(str(ts)).astimezone(HKT).hour:02d} 時"
    except ValueError:
        return "—"


def conf_bucket(c):
    if not isinstance(c, (int, float)):
        return "—"
    return "高（≥0.7）" if c >= 0.7 else ("中（0.5–0.7）" if c >= 0.5 else "低（<0.5）")


# ---------------- 報告 ----------------
def fmt(v, kind="hkd"):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:.0%}"
    if kind == "x":
        return f"{v:.2f}"
    if kind == "r":
        return f"{v:+.2f}R"
    return "0" if abs(v) < 0.5 else f"{v:+,.0f}"


def table(groups, title):
    lines = [f"\n### {title}\n", "| 分組 | 筆數 | 勝率 | 合計 HK$ | 每筆 HK$ | 平均 R | 獲利因子 | 結論 |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = stats(rows)
        if not s["n"]:
            continue
        verdict = "樣本不足" if s["n"] < MIN_N else ("✅ 有優勢" if s["avg"] > 0 and (s["pf"] or 9) > 1.2 else
                                                 ("❌ 蝕錢" if s["avg"] < 0 else "⚪ 打和"))
        lines.append(f"| {name} | {s['n']} | {fmt(s['win'], 'pct')} | {fmt(s['sum'])} | {fmt(s['avg'])} | "
                     f"{fmt(s['avg_r'], 'r')} | {fmt(s['pf'], 'x')} | {verdict} |")
    return "\n".join(lines)


def candidates(rows, decs_by_p):
    """候選教學：只喺樣本夠嘅分組出；每條附證據。由使用者決定寫唔寫入 LESSONS.md。"""
    out = []
    by = lambda f: _group(rows, f)
    for title, groups in (("方向", by(lambda r: "做好" if r.get("side", 0) > 0 else "做淡")),
                          ("時段", by(lambda r: r.get("open_session") or "—")),
                          ("信心", by(lambda r: conf_bucket(r.get("confidence")))),
                          ("產品", by(lambda r: r["product"]))):
        for name, g in groups.items():
            s = stats(g)
            if s["n"] >= MIN_N and s["avg"] < 0 and (s["pf"] or 0) < 0.8:
                out.append(f"- **{title}「{name}」持續蝕錢**：{s['n']} 筆、勝率 {fmt(s['win'], 'pct')}、每筆 {fmt(s['avg'])}、"
                           f"獲利因子 {fmt(s['pf'], 'x')} → 候選教學：「{name} 嘅情況要更嚴格先入場（或者唔做）」")
    # 出場質素：曾經浮賺 ≥ 1R 但最後蝕錢
    gave_back = [r for r in rows if isinstance(r.get("mfe"), (int, float)) and r.get("risk_pts")
                 and r["mfe"] >= r["risk_pts"] and (r.get("points") or 0) <= 0]
    if len(rows) >= MIN_N and len(gave_back) / len(rows) >= 0.2:
        out.append(f"- **賺錢變蝕錢**：{len(gave_back)}／{len(rows)} 筆曾經浮賺 ≥ 1R 最後蝕或打和 → "
                   "候選教學：「浮賺達 1R 之後將止蝕移到開倉價」")
    # 止蝕太緊：贏單嘅最大浮蝕接近止蝕距離
    winners = [r for r in rows if (r.get("points") or 0) > 0 and isinstance(r.get("mae"), (int, float)) and r.get("risk_pts")]
    if len(winners) >= MIN_N:
        near = [r for r in winners if -r["mae"] >= 0.8 * r["risk_pts"]]
        if len(near) / len(winners) >= 0.3:
            out.append(f"- **止蝕可能太緊**：{len(near)}／{len(winners)} 張贏單途中浮蝕到止蝕距離八成以上 → "
                       "候選教學：「止蝕放喺結構位外多一啲，或者減少喺窄幅區間入場」")
    # 過度交易：每日開倉次數多但每筆平均蝕
    s_all = stats(rows)
    if s_all["n"] >= 2 * MIN_N and s_all["avg"] < 0:
        out.append(f"- **整體每筆平均蝕錢**（{s_all['n']} 筆，每筆 {fmt(s_all['avg'])}）→ 候選教學：「減少開倉，只做最清楚嘅形態」")
    # 決策質素：理由夾英文
    mixed = sum(1 for ds in decs_by_p.values() for d in ds
                if re.search(r"[A-Za-z]{3,}", re.sub(r"\b(HOLD|OPEN_LONG|OPEN_SHORT|UPDATE_STOP|CLOSE|ATR|K|RSI|EMA|MA|VWAP|SPY|QQQ|DIA|HSI)\b", "", str(d.get("reason") or ""))))
    if mixed >= 5:
        out.append(f"- **理由夾英文** {mixed} 次 → 候選教學：「理由只用繁體中文（粵語）」")
    return out or ["- 暫時冇：樣本未夠（每類要 ≥ {} 筆）或者未見明顯問題。".format(MIN_N)]


def _group(rows, keyf):
    g = defaultdict(list)
    for r in rows:
        g[keyf(r)].append(r)
    return g


# [R218] 每百萬 token 美元（官方價目表 2026-10）：輸入、輸出、快取讀、1 小時快取寫
PRICES = {"claude-fable-5-1": (10, 50, 0.25, 20), "claude-opus-5-5": (4, 20, 0.20, 8),
          "claude-sonnet-5-5": (2, 10, 0.10, 4), "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.20)}
DEFAULT_MODEL = "claude-sonnet-5-5"      # R218 之前嘅紀錄冇寫模型，嗰陣用 Sonnet 5.5


def usd(u):
    """一次 call 嘅美元成本（usage 冇寫模型就當 Sonnet 5.5）。"""
    if not isinstance(u, dict):
        return 0.0
    pi, po, pr, pw = PRICES.get(u.get("model") or DEFAULT_MODEL, PRICES[DEFAULT_MODEL])
    return ((u.get("in") or 0) * pi + (u.get("out") or 0) * po + (u.get("cache_read") or 0) * pr
            + (u.get("cache_write") or 0) * pw) / 1e6


def api_cost(data):
    """[R218] Claude API 費用：決策模型同 Haiku 篩選分開計；篩走幾多次。"""
    L = ["\n## Claude API 費用\n", "| 產品 | 決策次數 | 篩走 | 決策模型 | 決策費 US$ | 篩選費 US$ | 合計 US$ | 快取命中 |",
         "|---|---:|---:|---|---:|---:|---:|---:|"]
    tot = [0, 0, 0.0, 0.0]
    for p, d in data.items():
        decs = d["decisions"]
        main_u = [x["usage"] for x in decs if isinstance(x.get("usage"), dict)]
        gate_u = [x["gate_usage"] for x in decs if isinstance(x.get("gate_usage"), dict)]
        skipped = sum(1 for x in decs if x.get("gate") == "SKIP")
        if not main_u and not gate_u:
            continue
        models = sorted({u.get("model") or DEFAULT_MODEL for u in main_u})
        c_main, c_gate = sum(map(usd, main_u)), sum(map(usd, gate_u))
        inp = sum((u.get("in") or 0) + (u.get("cache_read") or 0) for u in main_u)
        hit = sum(u.get("cache_read") or 0 for u in main_u) / inp if inp else None
        L.append(f"| {p} | {len(main_u)} | {skipped} | {'、'.join(m.replace('claude-', '') for m in models) or '—'} | "
                 f"{c_main:.2f} | {c_gate:.2f} | {c_main + c_gate:.2f} | {fmt(hit, 'pct')} |")
        tot = [tot[0] + len(main_u), tot[1] + skipped, tot[2] + c_main, tot[3] + c_gate]
    L.append(f"| **合計** | {tot[0]} | {tot[1]} | | {tot[2]:.2f} | {tot[3]:.2f} | **{tot[2] + tot[3]:.2f}** | |")
    return L


def _bar_moves(dec_ts, last, bars, tz, minutes=60):
    """決策之後 N 分鐘內最大升／跌幅（%），用 1 分鐘 K 線。bars：{日期: [[HH:MM,o,h,l,c,v],...]}。"""
    from zoneinfo import ZoneInfo
    try:
        t0 = datetime.fromisoformat(str(dec_ts)).astimezone(ZoneInfo(tz))
    except ValueError:
        return None
    hi = lo = None
    for k in range(minutes + 1):
        t = t0 + timedelta(minutes=k)
        row = bars.get(t.strftime("%Y-%m-%d"), {}).get(t.strftime("%H:%M"))
        if row:
            hi = row[1] if hi is None else max(hi, row[1])
            lo = row[2] if lo is None else min(lo, row[2])
    if hi is None or not last:
        return None
    return max(hi - last, last - lo) / last * 100


def gate_audit(data, bars_by_p):
    """[R218] 用 1 分鐘 K 線檢查 Haiku 有冇篩走好機會：篩走之後 60 分鐘嘅最大波幅，對比放行（LOOK）嗰啲。
    篩走嘅波幅經常大過放行嘅中位數 → Haiku 太緊，要改篩選指引或者唔篩。"""
    L = ["\n## Haiku 篩選檢查（1 分鐘 K 線，決策後 60 分鐘最大波幅）\n"]
    rows = []
    for p, d in data.items():
        bars = bars_by_p.get(p) or {}
        if not bars:
            continue
        tz = "Asia/Hong_Kong" if p == "HSI" else "America/New_York"
        skip, look = [], []
        for x in d["decisions"]:
            if x.get("gate") not in ("SKIP", "LOOK"):
                continue
            m = _bar_moves(x.get("ts"), x.get("last"), bars, tz)
            if m is not None:
                (skip if x["gate"] == "SKIP" else look).append(m)
        if not skip or not look:
            continue
        med = sorted(look)[len(look) // 2]
        big = sum(1 for m in skip if m >= med)
        rows.append(f"| {p} | {len(look)} | {med:.2f}% | {len(skip)} | {sum(skip) / len(skip):.2f}% | "
                    f"{big}（{big / len(skip):.0%}） |")
    if not rows:
        return L + ["未有足夠數據（要有篩選紀錄同 longfei/bars/ 嘅 1 分鐘 K 線）。"]
    return L + ["| 產品 | 放行次數 | 放行後波幅中位數 | 篩走次數 | 篩走後平均波幅 | 篩走但波幅 ≥ 放行中位數 |",
                "|---|---:|---:|---:|---:|---:|"] + rows + [
        "", f"篩走但波幅 ≥ 放行中位數嘅比例長期高過 40% → Haiku 漏得太多，考慮放寬篩選指引；少過 {MIN_N} 次唔下結論。"]


def fetch_bars(days, products):
    """longfei/bars/<產品>/<日>.json → {產品: {日期: {HH:MM: [o,h,l,c,v]}}}（交易所當地日期）。"""
    out = {}
    today = datetime.now(HKT).date()
    for p in products:
        for k in range(days + 1):
            day = (today - timedelta(days=k)).isoformat()
            doc = _gcs_cat(f"longfei/bars/{p}/{day}.json")
            if isinstance(doc, dict) and isinstance(doc.get("bars"), list):
                out.setdefault(p, {})[day] = {r[0]: r[1:] for r in doc["bars"] if isinstance(r, list) and len(r) == 6}
    return out


def ranking(rows, products):
    """[R224] 真倉候選排名（使用者 10-18：一星期內決定 ETF 真倉揀邊幾隻）。用模擬成交扣費後盈虧（冇就用未扣費）。
    候選＝筆數 ≥ MIN_N、每筆平均 > 0、獲利因子 ≥ 1.2、t 值 ≥ 1；t ≥ 2 先算有統計意義。樣本少一律唔下結論。"""
    L = ["\n## 真倉候選排名（模擬成交，扣費後）\n",
         "| 排名 | 產品 | 筆數 | 勝率 | 每筆平均 | 合計 | 獲利因子 | 最大回撤 | t 值 | 判斷 |",
         "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    out = []
    for p in products:
        pr = [r for r in rows if r["product"] == p]
        key = "pnl_hkd_net" if any(isinstance(r.get("pnl_hkd_net"), (int, float)) for r in pr) else "pnl_hkd_gross"
        s = stats(pr, key)
        vals = [float(r[key]) for r in pr if isinstance(r.get(key), (int, float))]
        t = t_stat(vals)
        n = s.get("n", 0)
        if n < MIN_N:
            verdict = f"樣本不足（{n}／{MIN_N} 筆）"
        elif s["avg"] > 0 and (s.get("pf") is None or s["pf"] >= 1.2) and (t or 0) >= 1:
            verdict = "✅ 候選" + ("（t ≥ 2，有統計意義）" if (t or 0) >= 2 else "（t 未到 2，要再觀察）")
        elif s["avg"] > 0:
            verdict = "🟡 賺錢但未夠穩"
        else:
            verdict = "❌ 唔建議"
        out.append((t if t is not None else -99, s.get("sum", 0) if n else -1e18, p, s, t, verdict))
    out.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for i, (_, _, p, s, t, verdict) in enumerate(out, 1):
        if not s.get("n"):
            L.append(f"| {i} | {p} | 0 | — | — | — | — | — | — | 未有成交 |")
            continue
        L.append(f"| {i} | {p} | {s['n']} | {fmt(s['win'], 'pct')} | {fmt(s['avg'])} | {fmt(s['sum'])} | "
                 f"{fmt(s.get('pf'), 'x')} | {fmt(-s['dd'])} | {fmt(t, 'x')} | {verdict} |")
    L.append(f"\n候選條件：筆數 ≥ {MIN_N}、每筆平均 > 0、獲利因子 ≥ 1.2、t 值 ≥ 1。只得一星期數據時 t ≥ 2 好難達到，"
             "揀咗嘅產品轉真倉後照樣同模擬並排比較，表現差就撤。")
    return L


def readiness(data):
    """[R208] 真倉準備：bot 每 30 分鐘唯讀查真實戶口，結果喺 status.real_preflight。"""
    yn = lambda v: "—" if v is None else ("✅" if v else "❌")
    L = ["\n### 真倉準備（唯讀檢查真實戶口）\n", "| 產品 | 而家 | 搵到戶口 | 有錢 | 戶口類型 | 夠買 | 可沽空 | PDT | 結論 | 檢查時間 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for p, d in data.items():
        st = d["status"]
        r = st.get("real_preflight") or {}
        pdt = "—"
        if "is_pdt" in r or "pdt_seq" in r:
            pdt = f"{'係' if r.get('is_pdt') in (True, 'True', 'true') else '唔係'}／剩 {r.get('pdt_seq', '—')} 次"
        verdict = "未有結果（等 bot 更新）" if not r else ("✅ 準備好" if r.get("ok") else
                                                        "❌ " + str(r.get("error") or r.get("note") or "未齊"))
        if r.get("im_pct_long") is not None:          # 期貨：一張單嘅初始保證金佔最大購買力幾多
            verdict += f"（1 張用購買力 {r['im_pct_long']}%）"
        L.append(f"| {p} | {st.get('trd_env', '—')} | {yn(r.get('found'))} | {yn(r.get('funded'))} | "
                 f"{r.get('acc_type') or '—'} | {yn(r.get('can_long'))} | {yn(r.get('can_short'))} | {pdt} | "
                 f"{verdict.replace('|', '／')} | {str(r.get('ts') or '')[5:16]} |")
    return L


def report(data, title_date=None, real=False, bars=None):
    rows = closes(data)
    day = title_date or datetime.now(HKT).strftime("%Y-%m-%d")
    L = [f"# 🐉 龍飛陣覆盤 {day}・{'💰 真倉' if real else '🧪 模擬倉'}", "",
         ("真倉" if real else "模擬盤") + "；金額按 HK$（美股 ETF 1 美元 = 7.8 港元）、未扣佣金。少過 "
         f"{MIN_N} 筆嘅分組只供參考，唔下結論。", ""]
    s = stats(rows)
    pnl = [float(r["pnl_hkd_gross"]) for r in rows if isinstance(r.get("pnl_hkd_gross"), (int, float))]
    ts = t_stat(pnl)
    L.append("## 總覽\n")
    L.append(f"- 已平倉 **{s.get('n', 0)}** 筆；勝率 {fmt(s.get('win'), 'pct')}；合計 {fmt(s.get('sum'))}；"
             f"每筆 {fmt(s.get('avg'))}；平均 {fmt(s.get('avg_r'), 'r')}；盈虧比 {fmt(s.get('rrr'), 'x')}；"
             f"獲利因子 {fmt(s.get('pf'), 'x')}；最大回撤 {fmt(-s['dd']) if s.get('n') else '—'}；"
             f"每筆 t 值 {fmt(ts, 'x')}（≥ 2 先算有統計意義）")
    for p, d in data.items():
        st = d["status"]
        pos = st.get("pos")
        L.append(f"- {p}：{'持倉 ' + ('好' if pos.get('side', 0) > 0 else '淡') + str(pos.get('qty')) + ' @' + str(pos.get('entry')) if pos else '空手'}"
                 f"{'；⛔ 停機 ' + str(st.get('halt_reason')) if st.get('halted') else ''}；今日 {fmt(st.get('day_pnl'))}"
                 + (f"；模擬戶口淨值 {sa.get('currency')} {sa.get('equity', 0):,.0f}、購買力 {sa.get('power', 0):,.0f}"
                    if (sa := st.get("sim_account") or {}) else "")
                 + (f"；真實戶口淨值 {ra.get('currency')} {ra.get('equity', 0):,.0f}、購買力 {ra.get('power', 0):,.0f}"
                    if (ra := st.get("real_account") or {}) else ""))
    if not real:
        L += readiness(data)
        L += ranking(rows, [p for p in PRODUCTS if p in data])
    L.append(table(_group(rows, lambda r: r["product"]), "按產品"))
    L.append(table(_group(rows, lambda r: "做好" if r.get("side", 0) > 0 else "做淡"), "按方向"))
    L.append(table(_group(rows, lambda r: r.get("open_session") or "—"), "按開倉時段"))
    L.append(table(_group(rows, lambda r: hour_bucket(r.get("opened_at"))), "按開倉鐘數（香港時間）"))
    L.append(table(_group(rows, lambda r: conf_bucket(r.get("confidence"))), "按 AI 信心"))
    L.append(table(_group(rows, lambda r: exit_kind(r.get("reason"), r.get("points"))), "按出場方式"))
    L.append(table(_group(rows, lambda r: r.get("lessons") or "（未有教學簿版本）"), "按教學簿版本（學咗之後有冇進步）"))
    L.append(table(_group(rows, lambda r: (r.get("model") or DEFAULT_MODEL).replace("claude-", "")),
                   "按決策模型（R218 起 Opus 5.5；之前 Sonnet 5.5）"))
    # 出場質素
    q = [r for r in rows if isinstance(r.get("mfe"), (int, float)) and r.get("risk_pts")]
    if q:
        cap = [r["points"] / r["mfe"] for r in q if (r.get("points") or 0) > 0 and r["mfe"] > 0]
        L.append("\n### 出場質素\n")
        L.append(f"- 有 MFE／MAE 紀錄 {len(q)} 筆；贏單平均捉到最大浮賺嘅 {fmt(sum(cap) / len(cap), 'pct') if cap else '—'}")
        L.append(f"- 平均最大浮賺 {sum(r['mfe'] / r['risk_pts'] for r in q) / len(q):+.2f}R；"
                 f"平均最大浮蝕 {sum(r['mae'] / r['risk_pts'] for r in q) / len(q):+.2f}R")
    # 決策
    L.append("\n## 決策\n")
    for p, d in data.items():
        decs = d["decisions"]
        if not decs:
            continue
        cnt = defaultdict(int)
        rej = defaultdict(int)
        for x in decs:
            cnt[x.get("final") or "—"] += 1
            if x.get("rejected"):
                rej[str(x["rejected"])[:30]] += 1
        L.append(f"- {p}：{len(decs)} 次決策（" + "、".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])) + "）"
                 + ("；風控紀錄：" + "、".join(f"{k}×{v}" for k, v in rej.items()) if rej else ""))
    L += api_cost(data)
    L += gate_audit(data, bars or {})
    L.append("\n## 候選教學（要使用者批准；全部產品通用寫 LESSONS.md，只關一隻產品寫 lessons/<產品>.md，R228）\n")
    L += candidates(rows, {p: d["decisions"] for p, d in data.items()})
    L.append("\n## 最近 10 筆成交\n")
    L.append("| 產品 | 開倉 | 方向 | 點數 | R | MFE | MAE | 出場 | 入場理由 |")
    L.append("|---|---|---|---:|---:|---:|---:|---|---|")
    for r in rows[-10:]:
        L.append(f"| {r['product']} | {hour_bucket(r.get('opened_at'))} {str(r.get('opened_at') or '')[5:10]} | "
                 f"{'好' if r.get('side', 0) > 0 else '淡'} | {r.get('points')} | {fmt(r.get('r_multiple'), 'r')} | "
                 f"{r.get('mfe', '—')} | {r.get('mae', '—')} | {exit_kind(r.get('reason'), r.get('points'))} | "
                 f"{str(r.get('open_reason') or '')[:40].replace('|', '／')} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="經 gcp_agent.py 讀 GCS")
    ap.add_argument("--dir", help="離線資料夾")
    ap.add_argument("--days", type=int, default=3, help="讀幾多日嘅決策存檔（預設 3）")
    ap.add_argument("--out", help="寫入檔案（預設印出）")
    a = ap.parse_args()
    if not a.fetch and not a.dir:
        ap.error("要 --fetch 或者 --dir")
    data = fetch(a.days) if a.fetch else load_dir(a.dir)
    real = fetch(a.days, "longfei/real") if a.fetch else {}
    bars = fetch_bars(a.days, list(set(data) | set(real))) if a.fetch else {}   # [R218] 1 分鐘 K 線（模擬同真倉共用）
    text = (report(real, real=True, bars=bars) + "\n---\n\n" if real else "") + report(data, bars=bars)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
