#!/usr/bin/env python3
"""XAUUSD 蛇蟠陣只做多（sar N=3 多頭腿）前向紙上記錄。登記：forex_research/XAUUSD_LONG_FORWARD.md。

    python3 scripts/xau_long_forward.py                      # Actions 每日：補抓 Dukascopy M1 快取 → 重跑引擎 → 寫輸出（xau_long_forward.yml）
    python3 scripts/xau_long_forward.py --no-fetch           # 只用現有快取
    python3 scripts/xau_long_forward.py --seed-local         # 一次性：用本機 data_forex/XAUUSD 的 HistData 年檔＋Dukascopy 近期檔填 2026-06-01 起的快取

做法（決定性重算，不累加狀態）：
- 快取 forex_research/forward/xau_m1/<UTC 日>.csv.gz：Dukascopy XAUUSD M1 bid OHLC（＋ask OHLC 作點差診斷）。
- 每次把快取自錨點（2026-06-01 UTC）起全部讀入，UTC → 券商時間（紐約 17:00 = 午夜，同 data/ 的 MT5），
  用 donchian_backtest.run(lookback=3, mode="sar") 跑三組：long-only 點差 0.30（主）、long-only 0.65（Dukascopy 實測）、both 0.30（空頭腿對照）。
- 期末被引擎強制平倉（reason END）的那筆 = 目前持倉，不算已實現。
- 前向期 = 進場時間（券商時間）≥ 2026-10-13 的交易；之前已開、之後才平的標 carried。
輸出：xau_long_trades.csv、xau_both_trades.csv、xau_long_daily.csv、XAU_LONG_STATUS.md（全部重寫）。
"""
import argparse
import calendar
import csv
import gzip
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import donchian_backtest as db  # noqa: E402
from get_forex_data import to_broker_time  # noqa: E402

ANCHOR = date(2026, 6, 1)                 # 引擎起跑點（UTC 日），登記寫死
FWD_START = "2026-10-13"                  # 前向起點（券商時間日曆日），登記寫死
SP_MAIN, SP_DUKA = 0.30, 0.65             # 主口徑（使用者券商）、Dukascopy 2026 實測
SCALE = 1e3                               # XAUUSD 3 位小數
CACHE_COLS = ["Time", "Open", "High", "Low", "Close", "Volume", "AskOpen", "AskHigh", "AskLow", "AskClose"]
HIST = {"long_full": dict(n=394, mean=8.81, sd=63.7, t=2.75, pf=1.77, max_dd=473, per_year=22),
        "long_oos_2009_2022": dict(n=310, mean=3.05, t=1.70, pf=1.33),
        "short_full": dict(n=394, mean=0.33, t=0.15, pf=1.03, max_dd=1006)}


# ---------- 快取 ----------
def cache_dir(out: Path) -> Path:
    d = out / "xau_m1"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_day(cdir: Path, d: date, bid: list, ask: list) -> None:
    a = {r[0]: r for r in ask}
    with gzip.open(cdir / f"{d.isoformat()}.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CACHE_COLS)
        for r in bid:
            q = a.get(r[0])
            w.writerow([r[0], f"{r[1]:.3f}", f"{r[2]:.3f}", f"{r[3]:.3f}", f"{r[4]:.3f}", r[5]] +
                       ([f"{q[1]:.3f}", f"{q[2]:.3f}", f"{q[3]:.3f}", f"{q[4]:.3f}"] if q else ["", "", "", ""]))


def fetch_missing(cdir: Path, start: date, end: date, max_days: int) -> dict:
    """逐日補抓 Dukascopy；限流到頂就停，留待下次。回傳 {fetched, empty, stopped}。"""
    from fetch_forex import Feed, Throttled, log
    feed = Feed(2, 1.0)
    st = {"fetched": 0, "empty": 0, "stopped": ""}
    today = datetime.now(timezone.utc).date()
    d = start
    while d <= end and st["fetched"] < max_days:
        f = cdir / f"{d.isoformat()}.csv.gz"
        if f.exists() or d.weekday() == 5:                       # 週六無交易
            d += timedelta(days=1)
            continue
        try:
            rows = {}
            for side in ("BID", "ASK"):
                rows[side] = feed.candles(f"XAUUSD/{d.year}/{d.month - 1:02d}/{d.day:02d}/{side}_candles_min_1.bi5",
                                          datetime(d.year, d.month, d.day), SCALE)
        except Throttled as exc:
            st["stopped"] = f"{d}: {exc}"
            log(f"限流到頂，停在 {d}；下次再補")
            break
        if rows["BID"]:
            write_day(cdir, d, rows["BID"], rows["ASK"])
            st["fetched"] += 1
            log(f"{d}: bid {len(rows['BID'])} 根、ask {len(rows['ASK'])} 根")
        elif (today - d).days >= 3:                              # 三天後仍無檔 → 假日，寫空檔免得每天重抓
            write_day(cdir, d, [], [])
            st["empty"] += 1
            log(f"{d}: 無數據（假日），寫空檔")
        else:
            log(f"{d}: 尚無數據，明天再試")
            break
        d += timedelta(days=1)
    return st


def seed_local(cdir: Path) -> None:
    """用本機 HistData 年檔（UTC、只有 bid）＋ Dukascopy 近期檔（bid＋ask）填快取；只填尚無檔的日子。"""
    src = ROOT / "data_forex" / "XAUUSD"
    bid = pd.read_csv(src / "XAUUSD_M1_2026.csv.gz")
    rec = pd.read_csv(src / "XAUUSD_M1_recent.csv.gz")
    reca = pd.read_csv(src / "XAUUSD_M1_recent_ask.csv.gz").set_index("Time")
    allbid = pd.concat([bid, rec]).drop_duplicates("Time", keep="last").sort_values("Time")
    allbid = allbid[allbid.Time >= ANCHOR.isoformat()]
    print(f"本機來源：HistData 2026 到 {bid.Time.iloc[-1]}，Dukascopy 近期 {rec.Time.iloc[0]} → {rec.Time.iloc[-1]}")
    n = 0
    for day, g in allbid.groupby(allbid.Time.str[:10]):
        f = cdir / f"{day}.csv.gz"
        if f.exists():
            continue
        rows = [(r.Time, r.Open, r.High, r.Low, r.Close, int(r.Volume) if "Volume" in g.columns and not pd.isna(r.Volume) else 0) for r in g.itertuples()]
        ask = []
        if day >= rec.Time.iloc[0][:10]:
            sub = reca[reca.index.str[:10] == day]
            ask = [(t, r.Open, r.High, r.Low, r.Close, 0) for t, r in sub.iterrows()]
        write_day(cdir, date.fromisoformat(day), rows, ask)
        n += 1
    print(f"填入 {n} 個交易日的快取")


# ---------- 讀快取 → 券商時間 K 線 ----------
def load_bars(cdir: Path):
    files = sorted(cdir.glob("*.csv.gz"))
    bars, spread_at = [], {}
    days_present = []
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            any_row = False
            for r in rd:
                any_row = True
                bt = to_broker_time(r["Time"])
                ep = calendar.timegm((int(bt[0:4]), int(bt[5:7]), int(bt[8:10]), int(bt[11:13]), int(bt[14:16]), 0, 0, 0, 0))
                bars.append({"time": ep, "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]), "close": float(r["Close"])})
                if r.get("AskClose"):
                    spread_at[ep] = float(r["AskClose"]) - float(r["Close"])
        if any_row:
            days_present.append(f.name[:10])
    bars.sort(key=lambda b: b["time"])
    out = [bars[0]] if bars else []
    for b in bars[1:]:
        if b["time"] != out[-1]["time"]:
            out.append(b)
    return out, spread_at, days_present


def missing_weekdays(days_present: list[str], end: date) -> list[str]:
    have = set(days_present)
    return [d.date().isoformat() for d in pd.bdate_range(ANCHOR, end) if d.date().isoformat() not in have]


# ---------- 引擎 ----------
def iso_broker(ep: int) -> str:
    return datetime.fromtimestamp(ep, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def run_engine(bars, trade_mode: str, spread: float, spread_at: dict):
    r = db.run(bars, lookback=3, mode="sar", trade_mode=trade_mode, spread=spread, equity=10000.0, atr_len=14, collect_trades=True)
    rows = []
    last_t = bars[-1]["time"]
    for d, entry, exit_, pnl, ot, ct, reason in r["trade_rows"]:
        oe = int(datetime.fromisoformat(ot).timestamp())
        ce = int(datetime.fromisoformat(ct).timestamp())
        open_pos = reason == "END" and ce == last_t
        rows.append({"direction": d, "entry": float(entry), "exit": float(exit_), "pnl": float(pnl),
                     "open_time": iso_broker(oe), "close_time": "" if open_pos else iso_broker(ce), "reason": "OPEN" if open_pos else reason,
                     "phase": "forward" if iso_broker(oe)[:10] >= FWD_START else ("carried" if (open_pos or iso_broker(ce)[:10] >= FWD_START) else "run-in"),
                     "spread_entry": round(spread_at.get(oe, float("nan")), 3), "spread_exit": "" if open_pos else round(spread_at.get(ce, float("nan")), 3)})
    return rows


def daily_series(bars, trades: list[dict]) -> list[dict]:
    closes = {}
    for b in bars:
        closes[db.day_key(b["time"])] = b["close"]
    closed = [t for t in trades if t["reason"] != "OPEN"]
    opens = [t for t in trades if t["reason"] == "OPEN"]
    out, cum = [], 0.0
    j = 0
    closed.sort(key=lambda t: t["close_time"])
    for day in sorted(closes):
        while j < len(closed) and closed[j]["close_time"][:10] <= day:
            cum += closed[j]["pnl"]
            j += 1
        pos, entry, opnl = 0, "", 0.0
        for t in trades:
            if t["open_time"][:10] <= day and (t["reason"] == "OPEN" or t["close_time"][:10] > day):
                pos, entry = (1 if t["direction"] == "LONG" else -1), t["entry"]
                opnl = (closes[day] - t["entry"]) * pos
        out.append({"date": day, "close_bid": closes[day], "pos": pos, "entry": entry, "open_pnl": round(opnl, 2),
                    "realized_cum": round(cum, 2), "equity": round(cum + opnl, 2)})
    return out


# ---------- 報告 ----------
def tstat(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def journal_gold_rows() -> list[str]:
    """對帳 journal 裡的黃金列（MGC／GC／XAU／2840／GLD），供對照。"""
    out = []
    for name in ("log.csv", "forward_test.csv"):
        f = ROOT / "journal" / name
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                ins = (r.get("instrument") or "").upper()
                if any(k in ins for k in ("MGC", "XAU", "2840", "GLD")) or ins.startswith("GC"):
                    out.append(f"| {name} | {r.get('date','')} | {ins} | {(r.get('target_pos') or r.get('pos') or '')} | {(r.get('notes') or r.get('mark') or '')[:80]} |")
    return out


def report(out: Path, long_main, long_duka, both, daily, days_present, fetch_st, miss) -> None:
    fwd = [t for t in long_main if t["phase"] == "forward" and t["reason"] != "OPEN"]
    fwd_d = {t["open_time"]: t for t in long_duka}
    opn = [t for t in long_main if t["reason"] == "OPEN"]
    carried = [t for t in long_main if t["phase"] == "carried"]
    pn = [t["pnl"] for t in fwd]
    pn_d = [fwd_d[t["open_time"]]["pnl"] for t in fwd if t["open_time"] in fwd_d]
    short_fwd = [t["pnl"] for t in both if t["direction"] == "SHORT" and t["phase"] == "forward" and t["reason"] != "OPEN"]
    fwd_daily = [d for d in daily if d["date"] >= FWD_START]
    eq = np.array([d["equity"] for d in fwd_daily]) if fwd_daily else np.array([0.0])
    base = eq[0] if len(eq) else 0.0
    dd = float((np.maximum.accumulate(eq - base) - (eq - base)).max()) if len(eq) else 0.0
    L = ["# XAUUSD 只做多前向狀態（自動產生，scripts/xau_long_forward.py）", "",
         f"規則：蛇蟠陣 sar N=3 多頭腿（升破前 3 個完整券商日高點買入、跌破 3 日低點只平倉不做空），券商時間日界（紐約 17:00）。登記與監測規則見 `XAUUSD_LONG_FORWARD.md`。", "",
         f"- 數據：Dukascopy M1 快取 {days_present[0] if days_present else '—'} → {days_present[-1] if days_present else '—'}（{len(days_present)} 個交易日）；本次補抓 {fetch_st.get('fetched', 0)} 日"
         + (f"；**限流中斷：{fetch_st['stopped'][:60]}**" if fetch_st.get("stopped") else "") + (f"；缺平日 {len(miss)}：{', '.join(miss[:6])}{'…' if len(miss) > 6 else ''}" if miss else ""),
         f"- 前向起點 {FWD_START}（券商時間）；引擎錨點 {ANCHOR}", "",
         f"## 前向成績（只算前向期進場且已平倉的多單，點差 {SP_MAIN}）", "",
         f"- 已平倉 **{len(fwd)}** 筆；累計 **{sum(pn):+.1f}** 美元／盎司；平均 {np.mean(pn) if pn else 0:+.2f}；t {tstat(pn):.2f}；勝率 {np.mean([p > 0 for p in pn]) if pn else 0:.0%}",
         f"- 點差 {SP_DUKA}（Dukascopy 實測）口徑累計 {sum(pn_d):+.1f}",
         f"- 自前向起點的權益最大回撤 {dd:.1f}（歷史多頭腿最大回撤 {HIST['long_full']['max_dd']}；停止線 1.5 倍 = {1.5 * HIST['long_full']['max_dd']:.0f}）",
         f"- 對照：雙向版空頭腿前向 {len(short_fwd)} 筆、累計 {sum(short_fwd):+.1f}（歷史空頭腿 PF {HIST['short_full']['pf']} ≈ 0，預期前向也接近 0）",
         f"- 目前持倉：{'多 1 單位 @ ' + format(opn[0]['entry'], '.2f') + '（' + opn[0]['open_time'] + ' 進場）' if opn else '空手'}"
         + (f"；跨越前向起點的持倉 {len(carried)} 筆（不計入成績）" if carried else ""), "",
         "## 監測規則進度", "", "| 里程碑 | 條件 | 現況 |", "|---|---|---|",
         f"| 隨時 | 自前向起點回撤 ≤ {1.5 * HIST['long_full']['max_dd']:.0f}（1.5 × 歷史最大回撤），否則停 | {dd:.0f} |",
         f"| 25 筆（約 1 年） | 累計 ≥ −93（歷史滾動 25 筆和第 5 百分位），否則停 | {len(fwd)}/25，累計 {sum(pn):+.0f} |",
         f"| 50 筆（約 2.3 年） | 累計 > 0，否則停（歷史滾動 50 筆和有 25% 時間為負：真優勢也有 1/4 機會被停） | {len(fwd)}/50 |",
         f"| 100 筆（約 4.5 年） | 累計 ≥ +37（歷史第 5 百分位）且 t ≥ 1.0 → 「與歷史一致」；**不存在「前向確認」里程碑**（真優勢的期望 t 在 100 筆時只有 1.0–1.4） | {len(fwd)}/100 |", "",
         "## 歷史基準（HistData／Dukascopy 2009-03 → 2026-09，點差 0.30，見 SNAKE_COIL_FOREX_BACKTEST.md）", "",
         "| 樣本 | 筆數 | 平均／筆 | t | PF |", "|---|---:|---:|---:|---:|",
         f"| 多頭腿全期 | {HIST['long_full']['n']} | {HIST['long_full']['mean']:+.2f} | {HIST['long_full']['t']} | {HIST['long_full']['pf']} |",
         f"| 多頭腿樣本外 2009–2022 | {HIST['long_oos_2009_2022']['n']} | {HIST['long_oos_2009_2022']['mean']:+.2f} | {HIST['long_oos_2009_2022']['t']} | {HIST['long_oos_2009_2022']['pf']} |",
         f"| 空頭腿全期 | {HIST['short_full']['n']} | {HIST['short_full']['mean']:+.2f} | {HIST['short_full']['t']} | {HIST['short_full']['pf']} |", "",
         "## 前向多單明細（點差 0.30；spread 欄 = 成交分鐘的 Dukascopy 市場點差）", "",
         "| 進場 | 出場 | 進場價 | 出場價 | 損益 | 原因 | 點差 進／出 |", "|---|---|---:|---:|---:|---|---|"]
    for t in [t for t in long_main if t["phase"] in ("forward", "carried")][-30:]:
        L.append(f"| {t['open_time']} | {t['close_time'] or '持倉中'} | {t['entry']:.2f} | {t['exit']:.2f} | {t['pnl']:+.2f} | {t['reason']}{'（carried）' if t['phase']=='carried' else ''} | {t['spread_entry']}／{t['spread_exit']} |")
    jr = journal_gold_rows()
    L += ["", "## 對帳 journal 裡的黃金記錄（實盤對照；無則表示尚未開真倉）", ""]
    L += (["| 檔 | 日期 | 商品 | 倉位 | 備註 |", "|---|---|---|---|---|"] + jr) if jr else ["（journal/log.csv、forward_test.csv 目前沒有黃金列）"]
    (out / "XAU_LONG_STATUS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:14]))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "forex_research" / "forward")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--seed-local", action="store_true")
    ap.add_argument("--max-days", type=int, default=40, help="每次最多補抓幾個交易日")
    ap.add_argument("--end", default="", help="補抓到哪天（UTC，預設昨天）")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cdir = cache_dir(args.out)
    if args.seed_local:
        seed_local(cdir)
    end = date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date() - timedelta(days=1)
    st = {} if args.no_fetch else fetch_missing(cdir, ANCHOR, end, args.max_days)
    bars, spread_at, days_present = load_bars(cdir)
    if not bars:
        print("快取為空")
        return
    miss = missing_weekdays(days_present, date.fromisoformat(days_present[-1]))
    print(f"K 線 {len(bars):,} 根（券商時間 {db.day_key(bars[0]['time'])} → {db.day_key(bars[-1]['time'])}）")
    long_main = run_engine(bars, "long", SP_MAIN, spread_at)
    long_duka = run_engine(bars, "long", SP_DUKA, spread_at)
    both = run_engine(bars, "both", SP_MAIN, spread_at)
    for t, td in zip(long_main, long_duka):
        t["pnl_sp0.65"] = td["pnl"]
    daily = daily_series(bars, long_main)
    write_csv(args.out / "xau_long_trades.csv", long_main)
    write_csv(args.out / "xau_both_trades.csv", both)
    write_csv(args.out / "xau_long_daily.csv", daily)
    (args.out / "xau_fetch_status.json").write_text(json.dumps({"ran_at": datetime.now(timezone.utc).isoformat(), **st, "days": len(days_present), "missing_weekdays": miss}, ensure_ascii=False), encoding="utf-8")
    report(args.out, long_main, long_duka, both, daily, days_present, st, miss)


if __name__ == "__main__":
    main()
