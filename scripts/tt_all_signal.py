#!/usr/bin/env python3
"""趨勢模板股全部等權——月底名單（前向記錄；規格 = stock_research/TT_MOMENTUM_BACKTEST.md 第三部分，凍結）。

    python3 scripts/tt_all_signal.py --market hk sg            # 只在「最新數據日 = 該市場當月最後一個交易日」時出名單
    python3 scripts/tt_all_signal.py --market hk sg --force    # 測試：不管是不是月底都出（訊息會標「測試」）

輸出：analysis/tt_all/<市場>_<日期>.csv（名單）、analysis/tt_all/tg_<市場>.txt（Telegram 一則，< 4000 字，超長切段 tg_<市場>_2.txt…）、
analysis/tt_all/log.csv（每次訊號一行：日期、市場、大市過濾、候選數、40 檔種子）。
規則：t 收市 宇宙內（60 日成交額中位數前 N）、通過趨勢模板（收市>50>150>200 日線、200 日線高於 21 日前、≥252 日低×1.3、≥252 日高×0.75、
252 日報酬在宇宙內百分位 ≥ 70）、非數據斷點窗口；ETF 收市 > 50 且 > 200 日線才持股，否則整月現金；t+1 開市等權買入、持一個月。
40 檔版：超過 40 檔時隨機抽（種子 = 年月，例 202609）。
"""
import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import tt_momentum_backtest as T  # noqa: E402

OUT = ROOT / "analysis" / "tt_all"
NAME = {"hk": "港股", "jp": "日股", "us": "美股", "tw": "台灣", "kr": "韓國", "au": "澳洲", "ca": "加拿大", "in": "印度", "sg": "新加坡"}
ETF = {"hk": "盈富 2800", "jp": "1321", "us": "SPY", "tw": "0050", "kr": "KODEX200", "au": "STW", "ca": "XIU", "in": "NIFTYBEES", "sg": "ES3"}
CAP = 40
TG_LIMIT = 3900


def hk_names() -> dict[str, str]:
    p = ROOT / "data" / "equities" / "hk" / "_hkex_listed.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8")).get("listed", {})
    return {k: (v.get("name_zh") or v.get("name_en") or "") for k, v in d.items()}


def is_month_end(mk: str, d: date) -> bool:
    """d 之後同月內還有沒有交易日（週一至五、不在官方假期表；沒有假期表的市場只看週末）。"""
    hol = set()
    p = ROOT / "universes" / "calendars" / f"{mk}.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            hol = {date.fromisoformat(r["date"]) for r in csv.DictReader(f)}
    x = d + timedelta(days=1)
    while x.month == d.month:
        if x.weekday() < 5 and x not in hol:
            return False
        x += timedelta(days=1)
    return True


def chunks(lines: list[str], head: str, limit: int = TG_LIMIT) -> list[str]:
    out, cur = [], head
    for ln in lines:
        if len(cur) + len(ln) + 1 > limit:
            out.append(cur)
            cur = head.splitlines()[0] + "（續）\n"
        cur += ln + "\n"
    out.append(cur)
    return out


def run(mk: str, force: bool) -> None:
    x = T.TTMom(mk)
    m = x.m
    j = x.D - 1
    d = m.cal[j]
    month_end = is_month_end(mk, d)
    if not month_end and not force:
        print(f"[{mk}] 最新數據 {d} 不是當月最後一個交易日，不出名單", file=sys.stderr)
        return
    ok = bool(x.mkt_ok[j])
    # 候選池含基準 ETF 與指數代號（build_oos_pools 的 EXTRA，例 ^STI／ES3.SI）——不是股票，剔除
    import newhigh_backtest as nb
    not_stock = np.array([t.startswith("^") or t == nb.MARKETS[mk]["etf"] for t in m.tickers])
    cand = np.nonzero(x.tt[:, j] & ~x.bad[:, j] & ~not_stock)[0]
    rl = x.rl[252][:, j]
    # RS 百分位（宇宙內 252 日報酬排名）
    mem = np.nonzero(m.member[:, j] & ~np.isnan(rl))[0]
    order = np.argsort(rl[mem])
    pct = np.full(len(rl), np.nan)
    pct[mem[order]] = np.arange(1, len(mem) + 1) / len(mem) * 100
    rows = []
    names = hk_names() if mk == "hk" else {}
    for s in cand:
        rw = x.vf.raw[s]
        p = rw["dates"].get(d)
        close = float(rw["close"][p]) if p is not None else float("nan")
        rows.append({"ticker": m.tickers[s], "name": names.get(m.tickers[s], ""), "close": close, "ret252": float(rl[s]), "rs": float(pct[s]),
                     "above_200ma_pct": float(m.adj[s, j] / np.nanmean(m.adj[s, max(0, j - 199):j + 1]) - 1)})
    rows.sort(key=lambda r: -r["rs"])
    seed = d.year * 100 + d.month
    pick40 = set()
    if len(rows) > CAP:
        rng = np.random.default_rng(seed)
        pick40 = {rows[i]["ticker"] for i in rng.choice(len(rows), size=CAP, replace=False)}
    else:
        pick40 = {r["ticker"] for r in rows}
    OUT.mkdir(parents=True, exist_ok=True)
    tag = d.isoformat()
    with open(OUT / f"{mk}_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "name", "close", "ret252", "rs", "above_200ma_pct", "in40"], lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({**{k: (f"{v:.4g}" if isinstance(v, float) else v) for k, v in r.items()}, "in40": int(r["ticker"] in pick40)})
    with open(OUT / "log.csv", "a", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerow([tag, mk, int(ok), len(rows), seed, int(force and not month_end)])
    # ---- Telegram（純文字）----
    lvl = np.cumprod(1 + m.etf_ret)
    ma50, ma200 = lvl[j - 49:j + 1].mean(), lvl[j - 199:j + 1].mean()
    title = f"📋 趨勢模板全部等權｜{NAME[mk]}｜{d.isoformat()}{'（測試，非月底）' if force and not month_end else ''}"
    head = (f"{title}\n"
            f"大市過濾：{ETF[mk]} 收市 {'高於' if ok else '低於'} 50/200 日線（{lvl[j] / ma50 - 1:+.1%} / {lvl[j] / ma200 - 1:+.1%}）→ "
            f"{'✅ 持股' if ok else '⛔ 整月持現金'}\n"
            f"通過模板 {len(rows)} 檔（宇宙前 {m.top_n if hasattr(m, 'top_n') else '?'}；已剔除數據斷點股）\n"
            f"執行：下一交易日開市等權買入，持有到下月底；不止損、不加減碼\n"
            f"40 檔版：{'★ 標記者' if len(rows) > CAP else '全部'}（隨機種子 {seed}）\n"
            f"格式：代號 名稱｜收市｜252日報酬｜RS百分位\n")
    if not ok:
        body = ["（大市過濾未通過：本月不持股，名單只作記錄）"] + [f"{r['ticker']} {r['name']}".strip() for r in rows[:30]]
        if len(rows) > 30:
            body.append(f"…共 {len(rows)} 檔，見 analysis/tt_all/{mk}_{tag}.csv")
    else:
        body = [f"{'★' if r['ticker'] in pick40 and len(rows) > CAP else '·'} {r['ticker']} {r['name']}｜{r['close']:g}｜{r['ret252']:+.0%}｜{r['rs']:.0f}".replace("  ", " ")
                for r in rows]
    parts = chunks(body, head)
    for i, ptxt in enumerate(parts, 1):
        (OUT / (f"tg_{mk}.txt" if i == 1 else f"tg_{mk}_{i}.txt")).write_text(ptxt, encoding="utf-8")
    print(f"[{mk}] {d} 大市過濾 {ok} 候選 {len(rows)} 檔 → {len(parts)} 則訊息", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", nargs="+", default=["hk"], choices=list(NAME))
    a.add_argument("--force", action="store_true")
    args = a.parse_args()
    for f in OUT.glob("tg_*.txt"):
        f.unlink()
    for mk in args.market:
        run(mk, args.force)


if __name__ == "__main__":
    main()
