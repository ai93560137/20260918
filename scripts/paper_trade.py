#!/usr/bin/env python3
"""港股低波動前向模擬盤（手冊鐵律第12條）：每月初按寫死的規則「假裝下單」，
只記錄不投錢，次月初結算並跟 2800.HK 比較，產出 Telegram 月報。

規則寫死在 LOWVOL_HK_BACKTEST.md「前向模擬盤」一節，選股與回測引擎共用同一份
程式碼（stock_momentum_backtest.trailing_vol / sector_neutral_pick），保證可比：
- A：低波動，過去 252 日波動最低 10 檔，等權
- B：行業中性低波動，名額按當期行業檔數比例分配，行業內取最低波動，共 10 檔
- 訊號日 = 上月最後交易日收市；建倉/結算 = 本月第一個交易日開盤（AdjOpen，含股息）
- 成本：單邊 15bps，只對換手的名字收；持倉期間下市/停牌以最後可得收市價結算
- 成分股：換倉當下從 Wikipedia 抓現行恒指成分股與行業（不足 60 檔視為解析失敗，
  退回最近的年度快照並在月報標明）

由 .github/workflows/fetch_stock_data.yml 每天抓完數據後執行：不是新月份第一個
交易日就只更新現行成分股清單；是的話（且本月尚未換倉）就結算上月、建本月籃子，
寫 paper/tg_monthly.txt 給 Telegram。錯過一天會在下一次執行補做（選股只用訊號日
以前的數據，晚算不會偷看）。

本機驗證（不需網路）：
    python3 scripts/paper_trade.py --check-selection 2026-07-31   # 選股是否等於回測引擎
    python3 scripts/paper_trade.py --check-settlement 2026-06 2026-09  # 結算是否等於回測
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import stock_momentum_backtest as eng  # noqa: E402

PAPER_DIR = ROOT / "paper"
LEDGER = PAPER_DIR / "ledger.json"
REPORT = PAPER_DIR / "PAPER_REPORT.md"
TG_MONTHLY = PAPER_DIR / "tg_monthly.txt"
LIVE_UNIVERSE = ROOT / "scripts" / "universe_hsi_live.txt"
LIVE_SECTORS = PAPER_DIR / "live_sectors.json"
PIT_DIR = ROOT / "scripts" / "pointintime"
HKEX_DIR = ROOT / "data" / "stocks_hkex"

BENCH = "2800.HK"
VOL_DAYS = 252
TOP_K = 10
COST_BPS = 15.0
STOP_DRAWDOWN = -0.35
ALPHA_WINDOW = 24
MIN_LIVE_MEMBERS = 60
STRATEGIES = {"A": "低波動10檔", "B": "行業中性低波動10檔"}


# ---------- 成分股 ----------

def fetch_live_constituents() -> tuple[dict[str, str], str]:
    """從 Wikipedia 現行版本抓恒指成分股與行業；回傳 ({ticker: sector}, 來源說明)。"""
    import requests
    from parse_hsi_snapshots import parse_bullet_format, parse_sehk_format
    r = requests.get("https://en.wikipedia.org/w/api.php", timeout=30, params={
        "action": "query", "prop": "revisions", "titles": "Hang Seng Index", "rvlimit": 1,
        "rvprop": "content|timestamp", "rvslots": "main", "format": "json", "formatversion": 2,
    }, headers={"User-Agent": "Mozilla/5.0 (paper trading; HSI constituents)"})
    r.raise_for_status()
    rev = r.json()["query"]["pages"][0]["revisions"][0]
    text = rev["slots"]["main"]["content"]
    rows = parse_sehk_format(text) or parse_bullet_format(text)
    return {f"{c}.HK": sec for c, _, sec in rows}, f"Wikipedia 現行版 {rev['timestamp']}"


def latest_snapshot_constituents() -> tuple[dict[str, str], str]:
    snaps = eng.load_pointintime(PIT_DIR)
    snap_date, members = snaps[-1]
    sectors = json.loads((PIT_DIR / "hsi_sectors.json").read_text(encoding="utf-8"))
    y = str(snap_date.year)
    return {t: sectors.get(t, {}).get(y, "") for t in members}, f"年度快照 {snap_date}（退回用）"


def get_constituents(offline: bool) -> tuple[dict[str, str], str]:
    if not offline:
        try:
            live, src = fetch_live_constituents()
            if len(live) >= MIN_LIVE_MEMBERS:
                return live, src
            print(f"WARN 現行成分股只解析到 {len(live)} 檔，退回年度快照", file=sys.stderr)
        except Exception as exc:
            print(f"WARN 抓現行成分股失敗（{exc}），退回年度快照", file=sys.stderr)
    return latest_snapshot_constituents()


# ---------- 價格與選股 ----------

class Prices:
    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def series(self, t: str) -> dict | None:
        if t not in self._cache:
            path = eng.DATA_DIR / (t.replace("^", "_") + ".csv.gz")  # noqa: 港股仍是舊格式
            self._cache[t] = eng.load_series(t) if path.exists() else None
        return self._cache[t]

    def daily(self, t: str):
        s = self.series(t)
        if s is None:
            return None, None
        rows = sorted((d, v[1]) for d, v in s.items())
        return rows, [d for d, _ in rows]


def select(prices: Prices, members: dict[str, str], signal_date: date,
           sector_neutral: bool) -> tuple[list[str], list[str]]:
    """回傳 (籃子, 沒價格/數據不足而跳過的成分股)。邏輯同回測引擎的 lowvol。"""
    scored, skipped = [], []
    for t in sorted(members):
        rows, dates = prices.daily(t)
        vol = eng.trailing_vol(rows, dates, signal_date, VOL_DAYS) if rows else None
        if vol is None:
            skipped.append(t)
            continue
        scored.append((-vol, t))
    scored.sort(reverse=True)
    if sector_neutral:
        basket = eng.sector_neutral_pick(scored, {t: members[t] for _, t in scored}, TOP_K)
    else:
        basket = {t for _, t in scored[:TOP_K]}
    return sorted(basket), skipped


def period_return(prices: Prices, basket: list[str], entry: date, exit_: date,
                  prev_basket: list[str]) -> tuple[float, list[str]]:
    """AdjOpen 對 AdjOpen 等權報酬，扣換手成本；回傳 (淨報酬, 備註)。同回測引擎。"""
    rets, notes = [], []
    for t in basket:
        s = prices.series(t) or {}
        if entry not in s:
            notes.append(f"{t} 建倉日無報價（停牌?），不計")
            continue
        p0 = s[entry][0]
        if exit_ in s:
            p1 = s[exit_][0]
        else:
            last = [d for d in s if entry <= d < exit_]
            if not last:
                notes.append(f"{t} 持有期無報價，不計")
                continue
            p1 = s[max(last)][1]
            notes.append(f"{t} 持有期中斷，以 {max(last)} 收市價結算")
        if p0 > 0:
            rets.append(p1 / p0 - 1.0)
    gross = sum(rets) / len(rets) if rets else 0.0
    changed = len(set(basket) ^ set(prev_basket))
    return gross - changed * (1.0 / TOP_K) * COST_BPS / 10000.0, notes


def bench_return(prices: Prices, entry: date, exit_: date) -> float:
    s = prices.series(BENCH)
    return s[exit_][0] / s[entry][0] - 1.0


# ---------- 行事曆 ----------

def month_starts(prices: Prices) -> list[tuple[date, date]]:
    """[(上月最後交易日=訊號日, 本月第一個交易日=執行日)]，以 2800 的交易日為準。"""
    cal = sorted(prices.series(BENCH))
    return [(cal[i - 1], cal[i]) for i in range(1, len(cal)) if cal[i].month != cal[i - 1].month]


# ---------- 帳本與報告 ----------

def load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"rules": "見 LOWVOL_HK_BACKTEST.md「前向模擬盤」與本腳本 docstring",
            "started": None, "periods": []}


def stats(periods: list[dict], key: str) -> dict:
    settled = [p for p in periods if "returns" in p]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for p in settled:
        eq *= 1.0 + p["returns"][key]
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1.0)
    return {"cum": eq - 1.0, "mdd": mdd, "dd_now": eq / peak - 1.0, "n": len(settled)}


def rolling_alpha(periods: list[dict], key: str) -> float | None:
    """最近 ALPHA_WINDOW 期的 CAPM 年化 alpha；期數不足回 None。"""
    settled = [p for p in periods if "returns" in p][-ALPHA_WINDOW:]
    if len(settled) < ALPHA_WINDOW:
        return None
    r = [p["returns"][key] for p in settled]
    b = [p["returns"]["bench"] for p in settled]
    n = len(r)
    mb, mr = sum(b) / n, sum(r) / n
    sbb = sum((x - mb) ** 2 for x in b)
    beta = sum((x - mb) * (y - mr) for x, y in zip(b, r)) / sbb if sbb else 0.0
    return (mr - beta * mb) * 12


def display_name(t: str) -> str:
    snaps = sorted(HKEX_DIR.glob("quotes_*.json")) if HKEX_DIR.exists() else []
    if snaps:
        q = json.loads(snaps[-1].read_text(encoding="utf-8")).get("quotes", {})
        if t in q and q[t].get("name"):
            return q[t]["name"]
    names = json.loads((PIT_DIR / "hsi_names.json").read_text(encoding="utf-8"))
    return names.get(t, {}).get(max(names.get(t, {"": ""})), "") or "?"


def write_outputs(ledger: dict, new_period: dict | None) -> None:
    periods = ledger["periods"]
    sA, sB, sM = stats(periods, "A"), stats(periods, "B"), stats(periods, "bench")
    stop = []
    for key in ("A", "B"):
        st = stats(periods, key)
        if st["mdd"] < STOP_DRAWDOWN:
            stop.append(f"{key} 回撤 {st['mdd']:.1%} 超過 {STOP_DRAWDOWN:.0%}")
        ra = rolling_alpha(periods, key)
        if ra is not None and ra < 0:
            stop.append(f"{key} 滾動{ALPHA_WINDOW}月 alpha {ra:+.1%} < 0")

    # PAPER_REPORT.md
    title = (f"# 港股低波動前向模擬盤（自 {ledger['started']} 起）" if ledger["started"]
             else "# 港股低波動前向模擬盤（尚未開始：下一個月份的第一個交易日自動開始）")
    lines = [title, "",
             "規則見 `LOWVOL_HK_BACKTEST.md`「前向模擬盤」；由 `scripts/paper_trade.py` 每月自動結算。", "",
             f"累計：A {sA['cum']:+.2%}（MDD {sA['mdd']:.1%}）｜ B {sB['cum']:+.2%}（MDD {sB['mdd']:.1%}）"
             f"｜ 2800 {sM['cum']:+.2%}（MDD {sM['mdd']:.1%}），已結算 {sA['n']} 期", "",
             "證偽狀態：" + ("🔴 " + "；".join(stop) if stop else "🟢 未觸發"), "",
             "| 月份 | 建倉日 | 結算日 | A | B | 2800 | 成分股來源 |", "|---|---|---|---|---|---|---|"]
    for p in periods:
        rt = p.get("returns")
        cells = [f"{rt[k]:+.2%}" for k in ("A", "B", "bench")] if rt else ["持有中"] * 3
        lines.append(f"| {p['month']} | {p['entry']} | {p.get('exit', '')} | " + " | ".join(cells)
                     + f" | {p['universe_source']} |")
    lines += ["", "## 各期持倉", ""]
    for p in periods:
        lines.append(f"- **{p['month']}** A：{', '.join(p['baskets']['A'])}")
        lines.append(f"  B：{', '.join(p['baskets']['B'])}")
    PAPER_DIR.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Telegram 月報：只在這次有換倉時寫
    if new_period is None:
        if TG_MONTHLY.exists():
            TG_MONTHLY.unlink()
        return
    msg = [f"📅 前向模擬盤月報 {new_period['month']}"]
    prev = [p for p in periods if "returns" in p]
    if prev and prev[-1]["exit"] == new_period["entry"]:
        last = prev[-1]
        rt = last["returns"]
        msg += ["", f"✅ 結算 {last['month']}（{last['entry']} → {last['exit']} 開盤）",
                f"A 低波動：{rt['A']:+.2%}",
                f"B 行業中性：{rt['B']:+.2%}",
                f"基準 2800：{rt['bench']:+.2%}"]
        msg += [f"⚠️ {n}" for n in last.get("notes", [])[:3]]
        msg += ["", f"📈 累計（自 {ledger['started']}，{sA['n']} 期）",
                f"A {sA['cum']:+.2%} ｜ B {sB['cum']:+.2%} ｜ 2800 {sM['cum']:+.2%}",
                f"最大回撤 A {sA['mdd']:.1%} ｜ B {sB['mdd']:.1%} ｜ 2800 {sM['mdd']:.1%}"]
    else:
        msg += ["", f"🚀 模擬盤開始（{ledger['started']}），首期建倉"]
    ra_a = rolling_alpha(periods, "A")
    msg += ["", "🧯 證偽：" + ("🔴 停！" + "；".join(stop) if stop else
                             f"🟢 未觸發（回撤門檻 {STOP_DRAWDOWN:.0%}；滾動{ALPHA_WINDOW}月 alpha "
                             + ("需滿 24 期" if ra_a is None else f"A {ra_a:+.1%}") + "）")]
    for key in ("A", "B"):
        b = new_period["baskets"][key]
        prev_b = prev[-1]["baskets"][key] if prev and prev[-1]["exit"] == new_period["entry"] else []
        chg = len(set(b) - set(prev_b)) if prev_b else len(b)
        msg += ["", f"🆕 {new_period['month']} 持倉 {key} {STRATEGIES[key]}（換入 {chg} 檔）"]
        msg += [f"{t[:-3]} {display_name(t)}" for t in b]
    msg += ["", f"成分股：{new_period['universe_source']}",
            "建倉價＝本月第一個交易日開盤；只記錄不下單",
            "報告：paper/PAPER_REPORT.md（分支 claude/gifted-carson-v2tvhw）"]
    TG_MONTHLY.write_text("\n".join(msg)[:4000] + "\n", encoding="utf-8")


# ---------- 主流程 ----------

def run(offline: bool) -> None:
    PAPER_DIR.mkdir(exist_ok=True)
    prices = Prices()
    members, src = get_constituents(offline)
    LIVE_UNIVERSE.write_text("# 現行恒指成分股（paper_trade.py 每天更新），供每日抓取\n"
                             + "\n".join(sorted(members)) + "\n", encoding="utf-8")
    ledger = load_ledger()
    starts = month_starts(prices)
    signal_date, entry = starts[-1]
    month = entry.strftime("%Y-%m")
    latest = max(prices.series(BENCH))
    done = {p["month"] for p in ledger["periods"]}

    if month in done or latest < entry:
        print(f"本月 {month} 已換倉或未到換倉日（最新 {latest}），只更新現行成分股清單（{len(members)} 檔，{src}）")
        write_outputs(ledger, None)
        return
    if ledger["started"] is None and latest > entry:
        # 首次啟動不回補已過去的月份：從下一個月初才開始，避免在已知結果的日子「建倉」
        print(f"模擬盤尚未開始，{month} 的換倉日 {entry} 已過；等下個月第一個交易日才開始")
        write_outputs(ledger, None)
        return

    # 結算上一期
    if ledger["periods"] and "returns" not in ledger["periods"][-1]:
        last = ledger["periods"][-1]
        e0 = date.fromisoformat(last["entry"])
        prev_prev = ledger["periods"][-2]["baskets"] if len(ledger["periods"]) > 1 else {"A": [], "B": []}
        rets, notes = {}, []
        for key in ("A", "B"):
            rets[key], n = period_return(prices, last["baskets"][key], e0, entry, prev_prev[key])
            notes += n
        rets["bench"] = bench_return(prices, e0, entry)
        last.update({"exit": entry.isoformat(), "returns": rets, "notes": notes})

    LIVE_SECTORS.write_text(json.dumps(members, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8")
    baskets, skipped = {}, []
    for key, neutral in (("A", False), ("B", True)):
        baskets[key], sk = select(prices, members, signal_date, neutral)
        skipped = sk
    period = {"month": month, "signal_date": signal_date.isoformat(), "entry": entry.isoformat(),
              "universe_source": src, "n_members": len(members), "skipped": skipped,
              "baskets": baskets, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ledger["periods"].append(period)
    ledger["started"] = ledger["started"] or month
    PAPER_DIR.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_outputs(ledger, period)
    print(f"換倉完成 {month}：A={baskets['A']} B={baskets['B']}；跳過 {len(skipped)} 檔（無足夠價格）")


def check_selection(signal: date) -> None:
    """本機驗證：用年度快照當成分股，選股結果必須與回測引擎該期持倉完全相同。"""
    prices = Prices()
    snaps = eng.load_pointintime(PIT_DIR)
    snap_date, members_set = [x for x in snaps if x[0] <= signal][-1]
    sectors = json.loads((PIT_DIR / "hsi_sectors.json").read_text(encoding="utf-8"))
    members = {t: sectors.get(t, {}).get(str(snap_date.year), "") for t in members_set
               if prices.series(t) and min(prices.series(t)) <= snap_date}
    pool = sorted(t for t in set().union(*(m for _, m in snaps)) if t != BENCH and prices.series(t))
    ok = True
    for key, neutral in (("A", False), ("B", True)):
        mine, _ = select(prices, members, signal, neutral)
        res = eng.run_backtest(pool, BENCH, 12, 1, TOP_K, COST_BPS, None, True, None, snaps, "lowvol", VOL_DAYS,
                               sectors, neutral, None)
        entry = [e for s, e in month_starts(prices) if s == signal][0]
        theirs = [b for d, b in res["baskets"] if d == entry][0]
        same = mine == sorted(theirs)
        ok &= same
        print(f"{key} {'一致' if same else '不一致!'}：模擬盤 {mine}\n   回測引擎 {sorted(theirs)}")
    sys.exit(0 if ok else 1)


def check_settlement(first_month: str, last_month: str) -> None:
    """本機驗證：用年度快照在歷史月份上跑整套換倉/結算，報酬必須與回測引擎逐期相同。"""
    prices = Prices()
    snaps = eng.load_pointintime(PIT_DIR)
    sectors = json.loads((PIT_DIR / "hsi_sectors.json").read_text(encoding="utf-8"))
    pool = sorted(t for t in set().union(*(m for _, m in snaps)) if t != BENCH and prices.series(t))
    engine = {}
    for key, neutral in (("A", False), ("B", True)):
        res = eng.run_backtest(pool, BENCH, 12, 1, TOP_K, COST_BPS, None, True, None, snaps, "lowvol", VOL_DAYS,
                               sectors, neutral, None)
        dates = [d for d, _ in res["baskets"]]
        engine[key] = {d: r for d, (_, r) in zip(dates, res["period_returns"])}
    all_starts = month_starts(prices)
    idx = [i for i, x in enumerate(all_starts) if first_month <= x[1].strftime("%Y-%m") <= last_month]
    # 從前一個月開始建倉（不比較），第一個比較月的換手成本才有正確的「上期持倉」
    starts = all_starts[idx[0] - 1: idx[-1] + 1]
    prev = {"A": None, "B": None}
    all_ok = True
    for (sig, entry), (_, nxt) in zip(starts, starts[1:]):
        snap_date, ms = [x for x in snaps if x[0] <= sig][-1]
        members = {t: sectors.get(t, {}).get(str(snap_date.year), "") for t in ms
                   if prices.series(t) and min(prices.series(t)) <= snap_date}
        for key, neutral in (("A", False), ("B", True)):
            b, _ = select(prices, members, sig, neutral)
            if prev[key] is not None:
                r, _ = period_return(prices, b, entry, nxt, prev[key])
                e = engine[key].get(entry)
                same = e is not None and abs(r - e) < 1e-9
                all_ok &= same
                print(f"{entry} {key}: 模擬盤 {r:+.4%}  引擎 {e:+.4%}  {'一致' if same else '差異!'}")
            prev[key] = b
    sys.exit(0 if all_ok else 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="不抓 Wikipedia，用最近年度快照（測試用）")
    ap.add_argument("--check-selection", type=date.fromisoformat, metavar="SIGNAL_DATE")
    ap.add_argument("--check-settlement", nargs=2, metavar=("FIRST_YYYY-MM", "LAST_YYYY-MM"))
    args = ap.parse_args()
    if args.check_selection:
        check_selection(args.check_selection)
    elif args.check_settlement:
        check_settlement(*args.check_settlement)
    else:
        run(args.offline)


if __name__ == "__main__":
    main()
