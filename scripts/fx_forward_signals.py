#!/usr/bin/env python3
"""外匯前向記錄（路線 C：CME 期貨路徑）：每月初用最新數據算「上月底」的訊號與倉位，並記錄上一個完整月份的模型損益，
另抓 CME 貨幣期貨前月 vs 現貨的基差（實際可拿到的利差，扣掉了融資加價），與模型用的三個月利差對照。

    python3 scripts/fx_forward_signals.py [--asof YYYY-MM-DD] [--no-futures]

輸出（進 git，forex_research/forward/）：
- signals.csv       每月每個策略的多空名單與權重（carry_top2、carry_top3、factor3_top3；機構口徑候選）
- pnl.csv           每月每個策略上一完整月份的模型月報酬（swap 加價 0.25%，與登記引擎同一條程式）
- futures_basis.csv 月底 CME 期貨（6E 6B 6J 6S 6A 6N 6C 前月連續）vs Yahoo 現貨的基差、到下一個 IMM 日的天數、年化基差、模型三個月利差
沙盒連不到 Yahoo → 基差那段在 Actions（fx_forward.yml）跑；訊號與損益只要 data_forex/ 與 data_forex_rates/。
不是回測、不做判決：只是把「若機構口徑上線會怎樣」逐月記下來，累積 24 個月後再議（登記見 FX_TREND_CARRY_BACKTEST.md、FX_THREE_FACTOR_BACKTEST.md）。
"""
import argparse
import csv
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fx_basket_backtest import (USD_PAIRS, daily_rates, load_prices, load_rates, load_reer, portfolio_pnl,  # noqa: E402
                                strat_carry, strat_factor)

OUT = ROOT / "forex_research" / "forward"
HAIRCUT = 0.25                                       # 機構口徑（FX_COST_MODEL.md）
FUTURES = {"EUR": "6E=F", "GBP": "6B=F", "JPY": "6J=F", "CHF": "6S=F", "AUD": "6A=F", "NZD": "6N=F", "CAD": "6C=F"}
SPOT_YAHOO = {"EUR": ("EURUSD=X", 1), "GBP": ("GBPUSD=X", 1), "JPY": ("JPY=X", -1), "CHF": ("CHF=X", -1),
              "AUD": ("AUDUSD=X", 1), "NZD": ("NZDUSD=X", 1), "CAD": ("CAD=X", -1)}          # 1 = 美元／外幣，-1 = 外幣／美元要倒數
STRATS = {
    "carry_top2": lambda P, idx, rd, reer: strat_carry(P, idx, rd, 2, 0, 60, 0.10),
    "carry_top3": lambda P, idx, rd, reer: strat_carry(P, idx, rd, 3, 0, 60, 0.10),
    "factor3_top3": lambda P, idx, rd, reer: strat_factor(P, idx, rd, reer, ["carry", "value", "mom"], 3),
}


def next_imm(d: date) -> date:
    """下一個 IMM 日（3、6、9、12 月第三個星期三），至少 7 天後（前月換倉週避開）。"""
    for m in range(0, 15):
        y, mo = d.year + (d.month - 1 + m) // 12, (d.month - 1 + m) % 12 + 1
        if mo in (3, 6, 9, 12):
            first = date(y, mo, 1)
            third_wed = first + timedelta(days=(2 - first.weekday()) % 7 + 14)
            if third_wed >= d + timedelta(days=7):
                return third_wed
    raise RuntimeError


def append_rows(path: Path, rows: list[dict], key: tuple[str, ...]) -> int:
    """按 key 去重後追加（同一月同一策略重跑不會重複）。"""
    old = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            old = list(csv.DictReader(f))
    seen = {tuple(r[k] for k in key) for r in old}
    new = [r for r in rows if tuple(str(r[k]) for k in key) not in seen]
    if not new:
        return 0
    cols = list(rows[0])
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if not old:
            w.writeheader()
        w.writerows(new)
    return len(new)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--asof", default="", help="以這天（含）之前的數據算；預設全部")
    ap.add_argument("--no-futures", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    end = args.asof or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prices = load_prices(ROOT, USD_PAIRS, "2002-01-01", end)
    idx = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in prices.values()])))
    ccys = sorted({p[:3] for p in USD_PAIRS} | {p[3:] for p in USD_PAIRS})
    rates_m = load_rates(ROOT / "data_forex_rates", ccys)
    rates_d = daily_rates(rates_m, idx, lag_months=1)
    reer = load_reer(ROOT / "data_forex_rates" / "reer", [c for c in ccys if c != "USD"])
    month_ends = pd.DatetimeIndex(pd.Series(idx).groupby(idx.to_period("M")).max().values)
    # 只用「已完成」的月份：最後一個月底要是該月最後一個平日（或之後還有數據），否則月中跑會把半個月當成月底
    if not (month_ends[-1] == pd.offsets.BMonthEnd().rollforward(month_ends[-1]) or idx[-1] > month_ends[-1]):
        month_ends = month_ends[:-1]
    last_me = month_ends[-1]
    prev_me = month_ends[-2]
    print(f"數據到 {idx[-1].date()}；訊號月底 {last_me.date()}；上一完整月份 {prev_me.date()} → {last_me.date()}")
    sig_rows, pnl_rows = [], []
    for name, fn in STRATS.items():
        w = fn(prices, idx, rates_d, reer)
        # 訊號：last_me 收市後決定、之後生效的權重 = w 在 last_me 之後第一列；沒有下一列就用「假如有下一天」的算法——
        # 引擎把權重寫在 (me, next_me] 區間，所以 last_me 的新倉位要看 last_me 之後；月底當天跑的話還沒有那一列，改為重算一次到 last_me 為止的排序：
        after = w[w.index > last_me]
        if len(after):
            row = after.iloc[0]
        else:                                                       # 沒有下一個交易日：用同一函數的最後一個月區間表示「當前持倉」，訊號待下月初補
            row = w.loc[last_me]
        longs = [p for p, v in row.items() if v > 0]
        shorts = [p for p, v in row.items() if v < 0]
        ccy = lambda p, v: (p[:3] if p.endswith("USD") else p[3:]) if (v > 0) == p.endswith("USD") else None   # 做多的外幣
        ccy_long = [c for p, v in row.items() if v != 0 for c in [ccy(p, v)] if c]
        ccy_short = [(p[:3] if p.endswith("USD") else p[3:]) for p, v in row.items() if v != 0 and ccy(p, v) is None]
        sig_rows.append({"month_end": str(last_me.date()), "strategy": name, "long_ccy": " ".join(ccy_long), "short_ccy": " ".join(ccy_short),
                         "longs": " ".join(longs), "shorts": " ".join(shorts),
                         "weights": " ".join(f"{p}:{v:+.3f}" for p, v in row.items() if v != 0),
                         "effective_from": str(after.index[0].date()) if len(after) else "(下一交易日)",
                         "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")})
        # 上一完整月份的模型月報酬（含 swap、加價 0.25%、點差×2、0.2 pip）
        daily, contrib = portfolio_pnl(prices, w, rates_d, 2.0, 0.2, HAIRCUT)
        seg = daily[(daily.index > prev_me) & (daily.index <= last_me)]
        pnl_rows.append({"month_end": str(last_me.date()), "strategy": name, "ret_pct": round(float(seg.sum() * 100), 3),
                         "gross_exposure": round(float(w.loc[seg.index].abs().sum(axis=1).mean()), 2),
                         "top_contrib": " ".join(f"{p}:{v * 100:+.2f}" for p, v in contrib.loc[seg.index].sum().sort_values(ascending=False).items()),
                         "haircut_pct": HAIRCUT})
    n1 = append_rows(OUT / "signals.csv", sig_rows, ("month_end", "strategy"))
    n2 = append_rows(OUT / "pnl.csv", pnl_rows, ("month_end", "strategy"))
    print(f"signals.csv 新增 {n1} 列、pnl.csv 新增 {n2} 列")
    for r in sig_rows:
        print(f"  {r['strategy']:13} 做多 {r['long_ccy'] or '—':12} 做空 {r['short_ccy'] or '—':12}（{r['weights']}）")
    for r in pnl_rows:
        print(f"  {r['strategy']:13} 上月 {r['ret_pct']:+.2f}%")

    if args.no_futures:
        return
    try:
        import yfinance as yf
    except ImportError:
        print("沒有 yfinance，略過期貨基差")
        return
    rows = []
    today = datetime.now(timezone.utc).date()
    imm = next_imm(today)
    r_last = rates_d.loc[last_me]
    for c, fsym in FUTURES.items():
        try:
            fut = yf.download(fsym, period="10d", auto_adjust=False, progress=False, threads=False)["Close"].dropna()
            ssym, power = SPOT_YAHOO[c]
            spot = yf.download(ssym, period="10d", auto_adjust=False, progress=False, threads=False)["Close"].dropna()
            if hasattr(fut, "columns"):
                fut, spot = fut.iloc[:, 0], spot.iloc[:, 0]
            f_px, s_px = float(fut.iloc[-1]), float(spot.iloc[-1]) ** power
            days = (imm - today).days
            basis = f_px / s_px - 1.0
            rows.append({"date": str(today), "ccy": c, "spot_usd_per_ccy": round(s_px, 6), "futures": round(f_px, 6), "basis_pct": round(basis * 100, 4),
                         "days_to_imm": days, "imm": str(imm), "ann_basis_pct": round(basis * 365 / max(days, 1) * 100, 3),
                         "model_rate_diff_pct": round(float(r_last["USD"] - r_last[c]), 3),
                         "note": "無套利：期貨/現貨−1 ≈ (美元利率−外幣利率)×天數/360；年化基差與模型利差的差 = 期貨路徑的實際成本"})
        except Exception as exc:  # noqa: BLE001
            rows.append({"date": str(today), "ccy": c, "spot_usd_per_ccy": "", "futures": "", "basis_pct": "", "days_to_imm": "", "imm": str(imm),
                         "ann_basis_pct": "", "model_rate_diff_pct": "", "note": f"失敗 {exc!r}"})
    n3 = append_rows(OUT / "futures_basis.csv", rows, ("date", "ccy"))
    print(f"futures_basis.csv 新增 {n3} 列")
    for r in rows:
        print(f"  {r['ccy']} 期貨 {r['futures']} 現貨 {r['spot_usd_per_ccy']} 年化基差 {r['ann_basis_pct']}% 模型利差 {r['model_rate_diff_pct']}% {r['note'][:20]}")


if __name__ == "__main__":
    main()
