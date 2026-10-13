"""ops_heartbeat.py — 流水線心跳（FUND_SOP 缺口 6）：每天一次，看昨天所有自動化有沒有跑、跑對沒有、數據有沒有更新。

每日 07:30 HKT，GitHub Actions `ops_heartbeat.yml` 跑。兩類檢查：

1. **排程 workflow**：讀預設分支每個 .github/workflows/*.yml 的 cron，算過去 24 小時「應該觸發幾次」，
   跟 GitHub API 的 schedule run 比對：應跑 ≥ 1 但 0 次 → 🔴「沒跑」；有失敗 → 🔴「失敗 n/m」。
   GitHub 會延遲或丟掉高頻排程，所以每 15 分鐘那種只在「一次都沒有」或「失敗」時才紅。
2. **數據新鮮度**：GCS（富途快照、成交檔、MT5 心跳、通報狀態、晨會簡報）、repo（金絲雀、對帳表、偏離報告）、
   其他陣分支（蛇蟠通道 levels.json、三地日線、新高名單、雲垂掃描）。每項有「最舊可接受幾小時」，
   週末與週一放寬（市場沒開就不會有新數據）。

輸出：Telegram 一則——全綠只一行；有紅只列紅項。全文寫 GitHub step summary 與 GCS ops/heartbeat/latest.txt。
Claude Routines 的 last_run 由總指揮每週用 list_triggers 看（Actions 讀不到），不在本腳本內。

用法：python3 scripts/ops_heartbeat.py [--dry-run] [--now "2026-10-14 07:30"]
需要環境變數 GITHUB_TOKEN、GITHUB_REPOSITORY（Actions 內建）；GCS 由 gcp_agent.py（WIF）讀。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops_notify import HKT, gcs_cat, gcs_put, parse_hkt, send_telegram  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
WINDOW_H = 24


# ---------------------------------------------------------------- cron
def _field(spec: str, lo: int, hi: int) -> set[int]:
    vals: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = b = int(part)
        vals.update(range(a, b + 1, step))
    return vals


def cron_matches(expr: str, t: datetime) -> bool:
    """5 欄 cron（UTC），支援 *、*/n、a-b、a,b。日與週同時受限時照 cron 慣例取「或」。"""
    mi, ho, dom, mon, dow = expr.split()[:5]
    if t.minute not in _field(mi, 0, 59) or t.hour not in _field(ho, 0, 23) or t.month not in _field(mon, 1, 12):
        return False
    wd = (t.weekday() + 1) % 7            # cron：0 = 週日
    dom_ok = t.day in _field(dom, 1, 31)
    dow_ok = wd in _field(dow, 0, 7) or (wd == 0 and 7 in _field(dow, 0, 7))
    if dom != "*" and dow != "*":
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def expected_fires(crons: list[str], start: datetime, end: datetime) -> int:
    n, t = 0, start.replace(second=0, microsecond=0)
    while t < end:
        if any(cron_matches(c, t) for c in crons):
            n += 1
        t += timedelta(minutes=1)
    return n


def load_workflows() -> dict[str, dict]:
    import yaml
    out = {}
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        on = d.get("on") or d.get(True) or {}
        crons = [s["cron"] for s in (on.get("schedule") or [])] if isinstance(on, dict) else []
        if crons:
            out[f.name] = {"name": d.get("name") or f.name, "crons": crons}
    return out


# ---------------------------------------------------------------- GitHub API
def gh_schedule_runs(since: datetime) -> list[dict]:
    import requests
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        raise RuntimeError("缺 GITHUB_REPOSITORY／GITHUB_TOKEN")
    runs, page = [], 1
    while page <= 10:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/runs",
                         params={"event": "schedule", "created": f">={since:%Y-%m-%dT%H:%M:%SZ}", "per_page": 100, "page": page},
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
        r.raise_for_status()
        batch = r.json().get("workflow_runs") or []
        runs += batch
        if len(batch) < 100:
            break
        page += 1
    return runs


def gh_workflow_meta() -> dict[str, dict]:
    """{檔名: {"created_at": datetime, "state": "active"/"disabled_manually"/...}}，讀不到就回空 dict。"""
    import requests
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return {}
    r = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows", params={"per_page": 100},
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
    r.raise_for_status()
    out = {}
    for w in r.json().get("workflows") or []:
        out[Path(w.get("path") or "").name] = {
            "created_at": datetime.fromisoformat(w["created_at"].replace("Z", "+00:00")).astimezone(UTC),
            "state": w.get("state")}
    return out


def gh_first_on_branch(fname: str) -> datetime | None:
    """這個 workflow 檔第一次出現在預設分支的 commit 時間（排程只在預設分支生效；
    GitHub 的 workflow created_at 可能是它在別的分支出現的日子）。"""
    import requests
    repo, token, branch = (os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"),
                           os.environ.get("GITHUB_REF_NAME"))
    if not repo or not token:
        return None
    params = {"path": f".github/workflows/{fname}", "per_page": 100}
    if branch:
        params["sha"] = branch
    r = requests.get(f"https://api.github.com/repos/{repo}/commits", params=params,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=30)
    if r.status_code != 200 or not r.json():
        return None
    oldest = r.json()[-1]["commit"]["committer"]["date"]
    return datetime.fromisoformat(oldest.replace("Z", "+00:00")).astimezone(UTC)


def load_config() -> dict:
    p = ROOT / "ops" / "heartbeat_config.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def check_workflows(wfs: dict, runs: list[dict], start: datetime, end: datetime,
                    meta: dict | None = None, first_on_branch=None,
                    must_be_active: dict | None = None) -> list[tuple[str, str, str]]:
    """回傳 [(燈, 名稱, 說明)]。meta 有 created_at 時，窗口從建立時間起算（今天才加的 workflow 不會被誤判沒跑）。"""
    meta = meta or {}
    by_file: dict[str, list[dict]] = {}
    for r in runs:
        by_file.setdefault(Path(r.get("path") or "").name, []).append(r)
    out = []
    for fname, wf in wfs.items():
        m = meta.get(fname) or {}
        if m.get("state") == "disabled_manually" and fname in (must_be_active or {}):
            out.append(("🔴", fname, f"已手動停用，但應恢復：{must_be_active[fname]}"))
            continue
        if m.get("state") == "disabled_manually":       # 有人刻意停用：只列在全文，不當紅燈
            out.append(("⚪", fname, "已手動停用（排程不會跑；要恢復到 Actions 頁 Enable workflow）"))
            continue
        if m.get("state") and m["state"] != "active":   # 例如 disabled_inactivity：GitHub 自動停用
            out.append(("🔴", fname, f"workflow 狀態 {m['state']}（排程不會跑）"))
            continue
        exp = expected_fires(wf["crons"], max(start, m.get("created_at") or start), end)
        if exp == 0:
            continue
        rs = by_file.get(fname, [])
        done = [r for r in rs if r.get("status") == "completed"]
        bad = [r for r in done if r.get("conclusion") not in ("success", "skipped", "neutral")]
        label = f"{fname}"
        if not rs and first_on_branch:
            added = first_on_branch(fname)          # 只在疑似沒跑時才多查一次 API
            if added and added > start:
                exp = expected_fires(wf["crons"], added, end)
                if exp == 0:
                    out.append(("⚪", label, f"{added.astimezone(HKT):%m-%d %H:%M} 才放上預設分支，窗口內未到排程時間"))
                    continue
        if not rs:
            out.append(("🔴", label, f"應觸發 {exp} 次，實際 0 次（GitHub 沒排到或 workflow 壞了）"))
        elif bad:
            concl = ",".join(sorted({str(r.get('conclusion')) for r in bad}))
            out.append(("🔴", label, f"失敗 {len(bad)}/{len(done)}（{concl}）：{bad[0].get('html_url', '')}"))
        else:
            out.append(("🟢", label, f"{len(done)}/{exp} 次成功"))
    return out


# ---------------------------------------------------------------- 新鮮度
def git_show(branch: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"origin/{branch}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


# 市場日期 → 該日收市的香港時間（日線檔只有日期；用收市時間才不會把「昨晚美股收市」算成舊了一整天）
CLOSE_HKT = {"us": (1, 5, 0), "hk": (0, 16, 30), "jp": (0, 14, 30)}   # (加幾日, 時, 分)


def last_csv_date(text: str | None, market: str | None = None) -> datetime | None:
    if not text:
        return None
    for ln in reversed(text.strip().splitlines()):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", ln)
        if m:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=HKT)
            if market in CLOSE_HKT:
                add, h, mi = CLOSE_HKT[market]
                d = (d + timedelta(days=add)).replace(hour=h, minute=mi)
            return d
    return None


def first_date(text: str | None) -> datetime | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?", text or "")
    if not m:
        return None
    return parse_hkt(f"{m.group(1)} {m.group(2) or '00:00'}")


def allowance(now: datetime) -> float:
    """週末與週一早上放寬 48 小時（週五收市後到週一沒有新市場數據）。"""
    return 48.0 if now.weekday() in (5, 6, 0) else 0.0


def freshness_checks(now: datetime) -> list[tuple[str, str, datetime | None, float]]:
    """回傳 [(名稱, 來源說明, 最新時間, 最舊可接受小時)]。"""
    def gcs_json(obj):
        try:
            v = gcs_cat(obj)
            return v if isinstance(v, dict) else None
        except Exception:  # noqa: BLE001
            return None

    items = []
    risk = gcs_json("futu/risk/latest.json")
    items.append(("富途持倉快照（本機 auto_risk）", "GCS futu/risk/latest.json run_hkt", parse_hkt((risk or {}).get("run_hkt")), 6))
    mt5 = gcs_json("mt5_account_snapshot.txt")
    mt5_t = None
    if mt5 and mt5.get("received_utc"):
        mt5_t = datetime.strptime(mt5["received_utc"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).astimezone(HKT)
    items.append(("MT5 EA 心跳（黃金系統）", "GCS mt5_account_snapshot.txt received_utc", mt5_t, 1))
    # 本機每日匯出成交（16:35／03:05）：不論有冇成交都會寫 fetched_hkt。找最近一個平日的檔。
    d = now.date()
    for _ in range(5):
        if d.weekday() < 5:
            break
        d -= timedelta(days=1)
    deals = gcs_json(f"futu/deals/{d:%Y-%m-%d}.json") or gcs_json(f"futu/deals/{d - timedelta(days=1):%Y-%m-%d}.json")
    items.append(("富途成交匯出（本機 16:35／03:05）", f"GCS futu/deals/<最近平日>.json fetched_hkt",
                  parse_hkt((deals or {}).get("fetched_hkt")), 30))
    items.append(("晨會簡報（Actions 08:30）", "GCS ops/brief/latest.txt", _brief_time(now), 26))
    items.append(("金絲雀日報（06:30）", "repo canary/tg_daily.txt 📅", first_date(_read("canary/tg_daily.txt")), 26))
    items.append(("對帳表（17:20）", "repo research/reconcile/latest.md", first_date(_read("research/reconcile/latest.md")), 40))
    items.append(("偏離／評分卡（週日）", "repo research/divergence/DIVERGENCE.md", first_date(_read("research/divergence/DIVERGENCE.md")), 8 * 24))
    gc = "claude/gifted-carson-v2tvhw"
    lv = git_show(gc, "tradingview/data_external/levels.json")
    lv_t = None
    if lv:
        try:
            lv_t = parse_hkt(json.loads(lv).get("fetched_at", "").replace(" HKT", ""))
        except json.JSONDecodeError:
            pass
    items.append(("蛇蟠通道 levels.json（12:00／16:45）", f"{gc} tradingview/data_external/levels.json", lv_t, 20))
    for mkt, code, path in (("美股 SPY", "us", "data/equities/us/SPY/prices_2026.csv"),
                            ("港股 2800", "hk", "data/equities/hk/2800.HK/prices_2026.csv"),
                            ("日股 1321", "jp", "data/equities/jp/1321.T/prices_2026.csv")):
        items.append((f"{mkt} 日線（收市時間計）", f"{gc} {path}", last_csv_date(git_show(gc, path), code), 26))
    items.append(("新高名單（美股收市計）", f"{gc} analysis/newhighs/summary.csv",
                  last_csv_date(git_show(gc, "analysis/newhighs/summary.csv"), "us"), 26))
    try:
        es = gcs_cat("futu/daily/US.ES_FRONT.json")
        es_last = es[-1].get("time_key") if isinstance(es, list) and es else None
    except Exception:  # noqa: BLE001
        es_last = None
    # 本機 mt5_push.py 推的 ES 日 K（取代已退役的 es_daily_push.yml）；time_key 是美股交易日 → 按美股收市計
    items.append(("ES 日線（本機 MT5 推送）", "GCS futu/daily/US.ES_FRONT.json 最後 time_key",
                  last_csv_date(es_last, "us") if es_last else None, 26))
    dc = "claude/dazzling-curie-f3xzb8"
    items.append(("雲垂每日掃描", f"{dc} tradingview/data_external/scan_report.md",
                  first_date(git_show(dc, "tradingview/data_external/scan_report.md")), 40))
    return items


def _read(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


def _brief_time(now: datetime) -> datetime | None:
    try:
        b = gcs_cat("ops/brief/latest.txt")
    except Exception:  # noqa: BLE001
        return None
    text = b.get("_text") if isinstance(b, dict) else None
    m = re.search(r"晨會簡報 (\d{2})-(\d{2})", text or "")
    if not m:
        return None
    t = datetime(now.year, int(m.group(1)), int(m.group(2)), 8, 30, tzinfo=HKT)
    return t if t <= now + timedelta(days=1) else t.replace(year=now.year - 1)


def judge_freshness(items, now: datetime) -> list[tuple[str, str, str]]:
    out = []
    extra = allowance(now)
    for name, src, t, max_h in items:
        if t is None:
            out.append(("🔴", name, f"讀不到時間（{src}）"))
            continue
        age = (now - t).total_seconds() / 3600
        limit = max_h + (extra if max_h < 24 * 7 else 0)
        if age > limit:
            out.append(("🔴", name, f"最新 {t:%m-%d %H:%M}，已 {age:.0f} 小時（上限 {limit:.0f}）｜{src}"))
        else:
            out.append(("🟢", name, f"最新 {t:%m-%d %H:%M}（{'盤中，未收市' if age < 0 else f'{age:.1f} 小時'}）"))
    return out


# ---------------------------------------------------------------- main
def compose(now: datetime, wf_rows, fresh_rows, errors: list[str], retired: dict | None = None) -> tuple[str, str]:
    reds = [r for r in wf_rows + fresh_rows if r[0] == "🔴"]
    n_all = len(wf_rows) + len(fresh_rows)
    head = f"💓 流水線心跳 {now:%m-%d %H:%M} HKT"
    if not reds and not errors:
        short = f"{head}：全部 {n_all} 項 🟢（{len(wf_rows)} 個排程 workflow、{len(fresh_rows)} 個數據來源）"
    else:
        lines = [f"{head}：🔴 {len(reds)}／{n_all} 項"]
        lines += [f"🔴 {name}：{msg}" for _, name, msg in reds]
        lines += [f"⚠ {e}" for e in errors]
        short = "\n".join(lines)
    full = [head, "", "## 排程 workflow（過去 24 小時）", *[f"{l} {n}：{m}" for l, n, m in wf_rows],
            "", "## 數據新鮮度", *[f"{l} {n}：{m}" for l, n, m in fresh_rows]]
    if retired:
        full += ["", "## 已退役（不檢查）", *[f"⚪ {k}：{v}" for k, v in retired.items()]]
    if errors:
        full += ["", "## 檢查本身的錯誤", *errors]
    full += ["", "Claude Routines 的 last_run 不在此（Actions 讀不到），由總指揮每週用 list_triggers 看。"]
    return short, "\n".join(full)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="覆寫現在時間（HKT，YYYY-MM-DD HH:MM）")
    a = ap.parse_args()
    now = parse_hkt(a.now) if a.now else datetime.now(HKT)
    end = now.astimezone(UTC) - timedelta(minutes=30)          # 剛排的還沒跑完，不算
    start = end - timedelta(hours=WINDOW_H)
    errors: list[str] = []
    wf_rows: list = []
    try:
        wf_rows = check_workflows(load_workflows(), gh_schedule_runs(start - timedelta(minutes=30)), start, end,
                                  gh_workflow_meta(), gh_first_on_branch, load_config().get("must_be_active"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"讀 GitHub Actions 紀錄失敗：{exc}")
    fresh_rows = judge_freshness(freshness_checks(now), now)
    short, full = compose(now, wf_rows, fresh_rows, errors, load_config().get("retired"))
    print(full)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(full.replace("\n", "  \n") + "\n", encoding="utf-8")
    if not a.dry_run:
        send_telegram(short)
        gcs_put("ops/heartbeat/latest.txt", full + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
