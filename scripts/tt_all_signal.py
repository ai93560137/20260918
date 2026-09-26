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
import re
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
# 回測等級（TT_MOMENTUM_BACKTEST.md 第四部分）：試行 = 相對等權 ≥ 1.7；觀察 = alpha 正但相對等權 < 1.7；不建議 = alpha ≤ 0 或接近 0
TIER = {"hk": "試行", "sg": "試行", "ca": "試行", "in": "試行", "au": "試行", "us": "觀察", "jp": "觀察", "tw": "不建議", "kr": "不建議"}
TG_LIMIT = 3900


def ticker_key(t: str):
    """代號排序：先純數字開頭（按數值），再英文字母（按字母）。例 0805.HK < 2388.HK < 42C.SI < A31.SI < BHP.AX。"""
    mm = re.match(r"^(\d+)(.*)$", t)
    return (0, int(mm.group(1)), mm.group(2)) if mm else (1, t.upper(), "")


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
    # 訊號日 = 最後一個「宇宙內至少一半股票有價格」的日曆日（ETF 序列可能比 Release 的個股數據新一兩天）
    cover = (m.has & m.member).sum(0) / max(int(getattr(m, "top_n", 0)) or int(np.median(m.member.sum(0))), 1)   # 分母 = 宇宙前 N（成員只在有數據的股票中定義，不能當分母）
    j = int(np.nonzero(cover >= 0.5)[0][-1])
    d = m.cal[j]
    if j < x.D - 1:
        print(f"[{mk}] 日曆最後一日 {m.cal[x.D - 1]} 個股數據不足，訊號日改為 {d}", file=sys.stderr)
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
    top5_rows = rows[:5]
    rows.sort(key=lambda r: ticker_key(r["ticker"]))
    with open(OUT / f"{mk}_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "name", "close", "ret252", "rs", "above_200ma_pct", "in40"], lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({**{k: (f"{v:.4g}" if isinstance(v, float) else v) for k, v in r.items()}, "in40": int(r["ticker"] in pick40)})
    with open(OUT / "log.csv", "a", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerow([tag, mk, int(ok), len(rows), seed, int(force and not month_end)])
    # ---- 上月名單（算進出）----
    prev = sorted(OUT.glob(f"{mk}_*.csv"))
    prev = [q for q in prev if q.stem != f"{mk}_{tag}"]
    prev_set = set()
    if prev:
        with open(prev[-1], newline="", encoding="utf-8") as f:
            prev_set = {r["ticker"] for r in csv.DictReader(f)}
    cur_set = {r["ticker"] for r in rows}
    lvl = np.cumprod(1 + m.etf_ret)
    ma50, ma200 = lvl[j - 49:j + 1].mean(), lvl[j - 199:j + 1].mean()
    meta = {"market": mk, "name": NAME[mk], "etf": ETF[mk], "date": tag, "month_end": month_end, "test": bool(force and not month_end),
            "market_ok": ok, "etf_vs_ma50": float(lvl[j] / ma50 - 1), "etf_vs_ma200": float(lvl[j] / ma200 - 1),
            "n": len(rows), "top_n": int(getattr(m, "top_n", 0)), "seed": seed, "cap": CAP,
            "tier": TIER[mk], "n_enter": len(cur_set - prev_set) if prev_set else None, "n_leave": len(prev_set - cur_set) if prev_set else None,
            "prev_date": prev[-1].stem.split("_", 1)[1] if prev else None,
            "top5": [f"{r['ticker']} {r['name']}".strip() for r in top5_rows]}
    (OUT / f"{mk}_latest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[{mk}] {d} 大市過濾 {ok} 候選 {len(rows)} 檔", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", nargs="+", default=["hk"], choices=list(NAME))
    a.add_argument("--force", action="store_true")
    args = a.parse_args()
    for f in OUT.glob("tg_*.txt"):
        f.unlink()
    for mk in args.market:
        run(mk, args.force)
    write_summary(args.market)
    write_ibkr_request()


def write_ibkr_request() -> None:
    """給雲垂分支 IBKR 覆核用：所有市場最新名單的 (market, ticker, signal_date)（stock_research/IBKR_DATA_REQUEST.md）。"""
    rows = []
    for p in sorted(OUT.glob("*_latest.json")):
        meta = json.loads(p.read_text(encoding="utf-8"))
        lp = OUT / f"{meta['market']}_{meta['date']}.csv"
        if not lp.exists():
            continue
        with open(lp, newline="", encoding="utf-8") as f:
            rows += [(meta["market"], r["ticker"], meta["date"]) for r in csv.DictReader(f)]
    with open(OUT / "ibkr_request.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["market", "ticker", "signal_date"])
        w.writerows(rows)
    print(f"IBKR 請求檔 {len(rows)} 檔 → {OUT / 'ibkr_request.csv'}", file=sys.stderr)


def write_summary(markets: list[str]) -> None:
    """Telegram 一則摘要：各市場大市狀態、檔數、進出、前五名；名單本身在網頁。"""
    metas = []
    for mk in markets:
        p = OUT / f"{mk}_latest.json"
        if p.exists():
            metas.append(json.loads(p.read_text(encoding="utf-8")))
    if not metas:
        return
    url_p = OUT / "page_url.txt"
    url = url_p.read_text(encoding="utf-8").strip() if url_p.exists() else ""
    d = max(x["date"] for x in metas)
    test = any(x["test"] for x in metas)
    lines = [f"🕊 鳥翔｜趨勢模板全部等權｜月底摘要 {d}{'（測試，非月底）' if test else ''}",
             "等級：試行 = 回測相對等權顯著（港新加印澳）；觀察 = 日美；不建議 = 台韓（回測 alpha 不顯著）", ""]
    for x in metas:
        st = "✅ 持股" if x["market_ok"] else "⛔ 現金"
        chg = "" if x["n_enter"] is None else f"｜較上月 +{x['n_enter']} −{x['n_leave']}"
        lines.append(f"{x['name']}（{x.get('tier', '')}）：{st}｜{x['etf']} 對 50/200 日線 {x['etf_vs_ma50']:+.1%}/{x['etf_vs_ma200']:+.1%}｜通過模板 {x['n']} 檔{chg}")
        if x["market_ok"] and x["top5"]:
            lines.append("　RS 前五：" + "、".join(x["top5"]))
    bl = OUT / "beacon_log.csv"
    if bl.exists():
        beacon = {r["date"]: r for r in csv.DictReader(bl.open(newline="", encoding="utf-8"))}
        lamps = sorted({beacon[x["date"]]["lamp"] for x in metas if x["date"] in beacon})
        if lamps:
            lines.append("")
            lines.append("烽燧（金絲雀）訊號日收盤：" + "／".join(lamps) + "　— 鳥翔登記：只記錄、不行動（2026-09-26）")
    lines += ["", "執行：下一交易日開市等權買入（40 檔版：超過 40 檔隨機抽，種子 " + str(metas[0]["seed"]) + "），持有到下月底；不止損、不加減碼",
              "全部名單、收市價、252 日報酬、RS：" + (url if url else "（網頁連結待設定：analysis/tt_all/page_url.txt）"),
              "證偽：前向 12 個月相對當地 ETF 跑輸 15 個百分點或相對等權為負 → 停"]
    txt = "\n".join(lines)
    (OUT / "tg_summary.txt").write_text(txt[:3900] + "\n", encoding="utf-8")
    print(f"摘要 {len(txt)} 字 → {OUT / 'tg_summary.txt'}", file=sys.stderr)


if __name__ == "__main__":
    main()
