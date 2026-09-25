#!/usr/bin/env python3
"""外匯籃子日線回測：長週期趨勢（TSMOM 月換倉、55/20 海龜停損單）與利差（G7 對美元排序、利差+趨勢過濾）。
預先登記見 forex_research/FX_TREND_CARRY_BACKTEST.md（成本、swap、倉位、門檻都寫在那裡，這裡照做）。

    python3 fx_basket_backtest.py --root <含 data_forex/ 的資料夾> --strategy tsmom --lookback 12
    python3 fx_basket_backtest.py --root ... --strategy turtle --entry 55 --exit 20
    python3 fx_basket_backtest.py --root ... --strategy carry --top 3 [--trend-filter 12]
    python3 fx_basket_backtest.py --root ... --strategy factor --factors carry,value,mom --top 3 [--combine rank|z] [--value-def 5y|10ymean|3y] [--mom-months 12]
        （三因子籃子，登記見 forex_research/FX_THREE_FACTOR_BACKTEST.md；--random 500 跑隨機排序對照）
    共同參數：--spread-mult 2 --slip-pip 0.2 --swap-haircut 1.0 --vol-target 0.10 --vol-window 60 --start 2003-06-01 --end 2026-08-31
    --out <前綴>：寫 <前綴>_monthly.csv（月報酬）、<前綴>_pairs.csv（各對貢獻）、<前綴>_stats.json

數據：data_forex/<PAIR>/<PAIR>_D1.csv.gz（買價）與 _D1_ask.csv.gz（賣價），Dukascopy UTC 日；利率 data_forex_rates/（FRED，月，%）；
BIS 實質有效匯率 data_forex_rates/reer/（FRED 轉載，月，2020=100；寬口徑 RB<國>BIS、窄口徑 RN<國>BIS）。
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
USD_PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
CROSSES = ["EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY", "EURGBP", "EURCHF", "EURAUD", "EURCAD",
           "GBPCHF", "GBPAUD", "AUDNZD", "AUDCAD"]
BASKET = USD_PAIRS + CROSSES
PIP = {p: (0.01 if p.endswith("JPY") else 0.0001) for p in BASKET}
# 各貨幣三個月利率：主系列 → 備援（月，%）；日頻備援重採樣成月平均
RATE_SERIES = {
    "USD": ["IR3TIB01USM156N", "IRSTCI01USM156N", "DTB3", "FEDFUNDS"],
    "EUR": ["IR3TIB01EZM156N", "IRSTCI01EZM156N", "ECBDFR"],
    "GBP": ["IR3TIB01GBM156N", "IRSTCI01GBM156N", "IUDSOIA", "BOERUKM"],
    "JPY": ["IR3TIB01JPM156N", "IRSTCI01JPM156N", "IRSTCB01JPM156N"],
    "CHF": ["IR3TIB01CHM156N", "IRSTCI01CHM156N"],
    "AUD": ["IR3TIB01AUM156N", "IRSTCI01AUM156N"],
    "NZD": ["IR3TIB01NZM156N", "IRSTCI01NZM156N"],
    "CAD": ["IR3TIB01CAM156N", "IRSTCI01CAM156N", "IRSTCB01CAM156N"],
}
REER_SERIES = {c: [f"RB{k}BIS", f"RN{k}BIS"] for c, k in
               {"USD": "US", "EUR": "XM", "GBP": "GB", "JPY": "JP", "CHF": "CH", "AUD": "AU", "NZD": "NZ", "CAD": "CA"}.items()}


# ---------------------------------------------------------------- 數據
def real_start(pair: str) -> pd.Timestamp:
    """Dukascopy 每個商品「真數據」起點 = 它的 H1 第一天（之前的 D1 是 Dukascopy 合成的日線，幾乎不動、波動率極低，
    會讓波動率目標把權重推到上限並在假突破上反覆進出——2026-09-25 機制檢查時發現 NZDJPY／CADJPY 2005–2007 就是這樣）。
    取自 forex_research/snake_coil/cost_gate.csv 的 first_h1 欄。"""
    import csv
    import json
    start = pd.Timestamp("2003-05-01")
    f = ROOT / "forex_research" / "snake_coil" / "cost_gate.csv"
    for r in csv.DictReader(open(f, encoding="utf-8")):
        if r["pair"] == pair:
            start = max(start, pd.Timestamp(r["first_h1"]))
    q = ROOT / "forex_research" / "data_qc" / f"{pair}_qc.json"           # HistData M1 起點（Dukascopy D1 早年有整段缺口的商品以此為準）
    if q.exists():
        m1 = json.loads(q.read_text(encoding="utf-8")).get("m1_first")
        if m1:
            start = max(start, pd.Timestamp(m1[:10]))
    return start


def load_prices(root: Path, pairs: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    out = {}
    for p in pairs:
        d = root / "data_forex" / p
        bid = pd.read_csv(d / f"{p}_D1.csv.gz", parse_dates=["Time"]).set_index("Time")
        ask = pd.read_csv(d / f"{p}_D1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")
        df = bid.join(ask[["Close"]].rename(columns={"Close": "AskClose"}), how="inner")
        df = df[(df.index >= max(pd.Timestamp(start), real_start(p))) & (df.index <= end)]
        df = df[df.index.weekday < 5]                                  # 週日的幾根不算交易日
        df["Mid"] = (df["Close"] + df["AskClose"]) / 2
        df["Spread"] = (df["AskClose"] - df["Close"]).clip(lower=0)
        df["Spread"] = df["Spread"].rolling(20, min_periods=1).median()     # 平滑一下，避免單日異常
        out[p] = df
    return out


def load_rates(rates_dir: Path, ccys: list[str]) -> pd.DataFrame:
    """回傳月頻（月底）利率表（%），欄 = 貨幣；主系列缺的月份用備援補；再延後一個月（公布時滯）由呼叫端處理。"""
    cols = {}
    for c in ccys:
        series = None
        for sid in RATE_SERIES[c]:
            f = rates_dir / f"{sid}.csv"
            if not f.exists():
                continue
            s = pd.read_csv(f, parse_dates=["Date"]).set_index("Date")["Value"].astype(float)
            s = s.resample("ME").mean() if s.index.to_series().diff().median() < pd.Timedelta(days=20) else s.resample("ME").last()
            series = s if series is None else series.combine_first(s)
        if series is None:
            raise SystemExit(f"沒有 {c} 的利率")
        cols[c] = series
    return pd.DataFrame(cols).sort_index()


def daily_rates(rates_m: pd.DataFrame, index: pd.DatetimeIndex, lag_months: int = 1) -> pd.DataFrame:
    """月利率 → 每日（延後 lag 個月：月 t 的值從 t+lag 月初起用），前向填補。"""
    r = rates_m.copy()
    r.index = r.index + pd.offsets.MonthEnd(lag_months)
    return r.reindex(r.index.union(index)).ffill().reindex(index)


def load_reer(reer_dir: Path, ccys: list[str]) -> pd.DataFrame:
    """BIS 實質有效匯率月表（月底索引；欄 = 貨幣）。寬口徑為主，寬口徑沒有的早期月份用窄口徑**按重疊第一個月的比例接上**
    （兩個口徑水平不同，直接混用會在接點製造假跳動）。"""
    cols = {}
    for c in ccys:
        broad = narrow = None
        for sid in REER_SERIES[c]:
            f = reer_dir / f"{sid}.csv"
            if not f.exists():
                continue
            s = pd.read_csv(f, parse_dates=["Date"]).set_index("Date")["Value"].astype(float).resample("ME").last()
            if sid.startswith("RB"):
                broad = s
            else:
                narrow = s
        if broad is None and narrow is None:
            raise SystemExit(f"沒有 {c} 的 REER")
        if broad is None:
            cols[c] = narrow
            continue
        if narrow is not None:
            first = broad.first_valid_index()
            if narrow.first_valid_index() < first:
                scale = broad.loc[first] / narrow.loc[first]
                cols[c] = broad.combine_first(narrow[narrow.index < first] * scale)
                continue
        cols[c] = broad
    return pd.DataFrame(cols).sort_index()


# ---------------------------------------------------------------- 共同：由每日權重算籃子報酬
def portfolio_pnl(prices: dict[str, pd.DataFrame], weights: pd.DataFrame, rates_d: pd.DataFrame | None,
                  spread_mult: float, slip_pip: float, swap_haircut: float, fill_cost_override: pd.DataFrame | None = None):
    """weights：每日各對名義權重（t 日收市後的持倉，賺 t+1 日的報酬）。
    報酬 = Σ w_{t-1} × (Mid_t/Mid_{t-1} − 1) + swap − 換倉成本。回傳（每日籃子報酬, 每日各對貢獻 DataFrame）。"""
    idx = weights.index
    contrib = pd.DataFrame(0.0, index=idx, columns=weights.columns)
    for p in weights.columns:
        px = prices[p].reindex(idx)
        mid = px["Mid"].ffill()
        ret = mid.pct_change().fillna(0.0)
        w_prev = weights[p].shift(1).fillna(0.0)
        pnl = w_prev * ret
        # swap：基礎貨幣利率 − 報價貨幣利率（年 %），按持倉每日計，扣券商加價
        if rates_d is not None:
            base, quote = p[:3], p[3:]
            diff = (rates_d[base] - rates_d[quote]).reindex(idx).ffill().fillna(0.0) / 100.0
            pnl += w_prev * diff / 365.0 - w_prev.abs() * swap_haircut / 100.0 / 365.0
        # 換倉成本：|Δw| × (半點差 + 滑點)，以價格比例計
        turnover = (weights[p] - w_prev).abs()
        unit_cost = (spread_mult * px["Spread"].ffill() / 2.0 + slip_pip * PIP[p]) / mid
        if fill_cost_override is not None and p in fill_cost_override:
            unit_cost = unit_cost + fill_cost_override[p].reindex(idx).fillna(0.0)
        pnl -= turnover * unit_cost.fillna(0.0)
        contrib[p] = pnl
    return contrib.sum(axis=1), contrib


def vol_scaled(prices: dict[str, pd.DataFrame], idx: pd.DatetimeIndex, window: int, target: float, n: int) -> pd.DataFrame:
    """每對的「單位方向」權重 = target ÷ 年化波動 ÷ n，上限 3 倍名義；該對過去 5 個交易日沒有自己的數據（缺口）→ NaN（不交易）。"""
    out = {}
    for p, df in prices.items():
        raw = df["Mid"].reindex(idx)
        ret = raw.ffill().pct_change()
        vol = ret.rolling(window, min_periods=window // 2).std() * math.sqrt(252)
        unit = (target / vol / n).clip(upper=3.0)
        stale = raw.notna().astype(float).rolling(5, min_periods=1).max() < 1
        out[p] = unit.mask(stale)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- 策略
def strat_tsmom(prices, idx, lookback: int, vol_window: int, vol_target: float) -> pd.DataFrame:
    """月底：sign(收市 ÷ lookback 個月前收市 − 1) × 波動率權重；下月第一個交易日開市成交 → 權重在月底下一個交易日生效。"""
    mids = pd.DataFrame({p: df["Mid"] for p, df in prices.items()}).reindex(idx).ffill()
    unit = vol_scaled(prices, idx, vol_window, vol_target, len(prices))
    month_ends = mids.groupby(mids.index.to_period("M")).tail(1).index
    w = pd.DataFrame(0.0, index=idx, columns=mids.columns)
    for i, me in enumerate(month_ends):
        pos = idx.get_loc(me)
        past = mids.index[mids.index <= me - pd.DateOffset(months=lookback)]
        if len(past) == 0 or pos + 1 >= len(idx):
            continue
        ref = mids.loc[past[-1]]
        sig = np.sign(mids.loc[me] / ref - 1.0)
        nxt_end = month_ends[i + 1] if i + 1 < len(month_ends) else idx[-1]
        # 成交在 me 之後第一個交易日開市 → 從那天起持有到下個月底（含）
        span = idx[(idx > me) & (idx <= nxt_end)]
        w.loc[span] = (sig * unit.loc[me]).fillna(0.0).values
    return w


def strat_turtle(prices, idx, entry: int, exit_: int, vol_window: int, vol_target: float):
    """55/20 海龜停損單：突破前 entry 日高低進場、跌破前 exit 日反向極值出場；權重進場時定死。
    停損單觸價成交 → 成交價與收市不同，這裡用「進場日以觸價（或跳空開市價）→ 收市」與「出場日以前收 → 觸價」修正報酬，
    做法：權重表照常（賺 close-to-close），另回傳一個成交價差成本表把當日的差額補回。"""
    unit = vol_scaled(prices, idx, vol_window, vol_target, len(prices))
    w = pd.DataFrame(0.0, index=idx, columns=list(prices))
    adj = pd.DataFrame(0.0, index=idx, columns=list(prices))      # 成交價修正（以價格比例，正 = 對我們不利）
    for p, df0 in prices.items():
        df = df0.reindex(idx).ffill()
        hi, lo, cl, op = df["High"].values, df["Low"].values, df["Mid"].values, df["Open"].values
        hh = pd.Series(hi).rolling(entry).max().shift(1).values
        ll = pd.Series(lo).rolling(entry).min().shift(1).values
        xh = pd.Series(hi).rolling(exit_).max().shift(1).values
        xl = pd.Series(lo).rolling(exit_).min().shift(1).values
        u = unit[p].values
        pos, size = 0, 0.0
        wcol = np.zeros(len(idx))
        acol = np.zeros(len(idx))
        for t in range(1, len(idx)):
            if np.isnan(hh[t]) or np.isnan(u[t]):
                continue
            # 出場日：權重表在當日已歸零（模型當天算 0 報酬），實際賺的是 前收 → 觸價，整段補回（adj 為負 = 補回實際損益）
            if pos > 0 and lo[t] <= xl[t]:                   # 多單出場
                fill = min(op[t], xl[t])
                acol[t] += -size * (fill - cl[t - 1]) / cl[t - 1]
                pos, size = 0, 0.0
            elif pos < 0 and hi[t] >= xh[t]:                 # 空單出場
                fill = max(op[t], xh[t])
                acol[t] += -size * (cl[t - 1] - fill) / cl[t - 1]
                pos, size = 0, 0.0
            if pos == 0:
                if hi[t] >= hh[t] and not (lo[t] <= ll[t] and abs(op[t] - ll[t]) < abs(hh[t] - op[t])):
                    fill = max(op[t], hh[t])
                    pos, size = 1, u[t]
                    acol[t] += size * (fill - cl[t - 1]) / cl[t - 1]   # 進場日：權重當日生效，模型算 前收→收，實際只有 觸價→收，多算的扣掉
                elif lo[t] <= ll[t]:
                    fill = min(op[t], ll[t])
                    pos, size = -1, u[t]
                    acol[t] += size * (cl[t - 1] - fill) / cl[t - 1]
            wcol[t] = pos * size
        # 進出場日的 close-to-close 報酬要用當日成立的權重：把權重提前一天生效
        w[p] = pd.Series(wcol, index=idx).shift(-1).fillna(0.0)
        adj[p] = acol
    return w, adj


def strat_carry(prices, idx, rates_d: pd.DataFrame, top: int, trend_filter: int, vol_window: int, vol_target: float,
                equal_weight: bool = True) -> pd.DataFrame:
    """月底：7 個外幣按（延後一個月的）三個月利率排序，做多最高 top 個、做空最低 top 個，各 1/top；美元中性。
    trend_filter > 0：該貨幣過去 N 個月對美元的走勢須與利差方向同號，否則該槽位空手。"""
    ccy_pair = {p[:3] if p.endswith("USD") else p[3:]: p for p in USD_PAIRS}
    mids = pd.DataFrame({p: df["Mid"] for p, df in prices.items()}).reindex(idx).ffill()
    unit = vol_scaled(prices, idx, vol_window, vol_target, 2 * top)
    month_ends = mids.groupby(mids.index.to_period("M")).tail(1).index
    w = pd.DataFrame(0.0, index=idx, columns=mids.columns)
    for i, me in enumerate(month_ends):
        r = rates_d.loc[me]
        if r.isna().any():
            continue
        ranked = sorted(ccy_pair, key=lambda c: r[c])
        longs, shorts = ranked[-top:], ranked[:top]
        nxt_end = month_ends[i + 1] if i + 1 < len(month_ends) else idx[-1]
        span = idx[(idx > me) & (idx <= nxt_end)]
        row = {}
        for c, direction in [(c, 1) for c in longs] + [(c, -1) for c in shorts]:
            p = ccy_pair[c]
            sign_pair = 1 if p.endswith("USD") else -1          # 做多外幣：XXXUSD 做多、USDXXX 做空
            if trend_filter:
                past = mids.index[mids.index <= me - pd.DateOffset(months=trend_filter)]
                if len(past) == 0:
                    continue
                ccy_move = (mids.loc[me, p] / mids.loc[past[-1], p] - 1.0) * sign_pair   # 外幣對美元的漲跌
                if np.sign(ccy_move) != direction:
                    continue
            size = (1.0 / top) if equal_weight else unit.loc[me, p]
            row[p] = direction * sign_pair * size
        for p, v in row.items():
            w.loc[span, p] = v
    return w


def strat_factor(prices, idx, rates_d: pd.DataFrame, reer_m: pd.DataFrame | None, factors: list[str], top: int,
                 combine: str = "rank", value_def: str = "5y", mom_months: int = 12, rng: np.random.Generator | None = None,
                 log: list | None = None) -> pd.DataFrame:
    """三因子橫截面籃子（FX_THREE_FACTOR_BACKTEST.md 第 1、2 節）：每月最後交易日，7 個外幣按
    carry（三個月利率，延後一個月）、value（−REER 過去 5 年變動，延後一個月）、mom（對美元 12 個月即期變動）各排名（1 = 最差），
    合成 = 名次平均（或 z 分數平均）；做多最高 top 個、做空最低 top 個，各 1/top；任一因子缺值的貨幣該月不參與。
    rng 給了 = 隨機排序對照（每月隨機排列取代合成分數）。"""
    ccy_pair = {p[:3] if p.endswith("USD") else p[3:]: p for p in USD_PAIRS if p in prices}
    mids = pd.DataFrame({p: df["Mid"] for p, df in prices.items()}).reindex(idx).ffill()
    month_ends = mids.groupby(mids.index.to_period("M")).tail(1).index
    # 外幣對美元的價格（1 單位外幣值多少美元），月底表
    spot = pd.DataFrame({c: (mids[p] if p.endswith("USD") else 1.0 / mids[p]) for c, p in ccy_pair.items()}).loc[month_ends]
    mom_m = spot / spot.shift(mom_months) - 1.0
    value_m = None
    if reer_m is not None:
        r = reer_m[list(ccy_pair)]
        if value_def == "5y":
            v = -(r / r.shift(60) - 1.0)
        elif value_def == "3y":
            v = -(r / r.shift(36) - 1.0)
        elif value_def == "10ymean":
            v = -(r / r.rolling(120, min_periods=120).mean() - 1.0)
        else:
            raise SystemExit(f"未知 value-def {value_def}")
        value_m = v.shift(1)                                              # 公布時滯：t 月底用 t−1 月值
        value_m = value_m.reindex(value_m.index.union(month_ends)).ffill().loc[month_ends]
    w = pd.DataFrame(0.0, index=idx, columns=mids.columns)
    for i, me in enumerate(month_ends):
        table = {}
        if "carry" in factors:
            table["carry"] = rates_d.loc[me, list(ccy_pair)]
        if "mom" in factors:
            table["mom"] = mom_m.loc[me]
        if "value" in factors:
            table["value"] = value_m.loc[me]
        f = pd.DataFrame(table).dropna()
        if len(f) < 2 * top:
            continue
        if rng is not None:
            score = pd.Series(rng.permutation(len(f)), index=f.index, dtype=float)
        elif combine == "rank":
            score = f.rank(method="average").mean(axis=1)
        elif combine == "z":
            score = ((f - f.mean()) / f.std(ddof=0).replace(0, np.nan)).fillna(0.0).mean(axis=1)
        else:
            raise SystemExit(f"未知 combine {combine}")
        ranked = list(score.sort_values(kind="stable").index)
        longs, shorts = ranked[-top:], ranked[:top]
        if log is not None:
            log.append({"month_end": str(me.date()), "longs": longs, "shorts": shorts,
                        **{f"{k}_{c}": round(float(f.loc[c, k]), 4) for k in f.columns for c in f.index}})
        nxt_end = month_ends[i + 1] if i + 1 < len(month_ends) else idx[-1]
        span = idx[(idx > me) & (idx <= nxt_end)]
        for c, direction in [(c, 1) for c in longs] + [(c, -1) for c in shorts]:
            p = ccy_pair[c]
            sign_pair = 1 if p.endswith("USD") else -1
            w.loc[span, p] = direction * sign_pair / top
    return w


# ---------------------------------------------------------------- 統計
def stats(daily: pd.Series, contrib: pd.DataFrame, split: str = "2013-01-01") -> dict:
    monthly = daily.groupby(daily.index.to_period("M")).sum()
    monthly.index = monthly.index.to_timestamp("M")

    def t_of(m: pd.Series) -> float:
        return float(m.mean() / m.std(ddof=1) * math.sqrt(len(m))) if len(m) > 2 and m.std(ddof=1) > 0 else float("nan")
    eq = (1 + daily).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    yearly = daily.groupby(daily.index.year).sum()
    pairs = contrib.sum().sort_values(ascending=False)
    m1, m2 = monthly[monthly.index < split], monthly[monthly.index >= split]
    return {"months": int(len(monthly)), "t": round(t_of(monthly), 2), "ann_return_pct": round(float(daily.mean() * 252 * 100), 2),
            "ann_vol_pct": round(float(daily.std() * math.sqrt(252) * 100), 2),
            "sharpe": round(float(daily.mean() / daily.std() * math.sqrt(252)), 2) if daily.std() > 0 else float("nan"),
            "max_dd_pct": round(float(dd * 100), 2), "pos_years": f"{int((yearly > 0).sum())}/{len(yearly)}",
            "worst_year": (str(yearly.idxmin()), round(float(yearly.min() * 100), 2)),
            "best_year_share": round(float(yearly.max() / daily.sum()), 2) if daily.sum() > 0 else None,
            "t_before_split": round(t_of(m1), 2), "t_from_split": round(t_of(m2), 2),
            "ret_before_split_pct": round(float(m1.sum() * 100), 1), "ret_from_split_pct": round(float(m2.sum() * 100), 1),
            "pairs_positive": f"{int((pairs > 0).sum())}/{len(pairs)}",
            "pair_contrib_pct": {k: round(float(v * 100), 2) for k, v in pairs.items()},
            "yearly_pct": {str(k): round(float(v * 100), 1) for k, v in yearly.items()}}, monthly


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--rates", type=Path, default=ROOT / "data_forex_rates")
    ap.add_argument("--strategy", choices=["tsmom", "turtle", "carry", "factor"], required=True)
    ap.add_argument("--factors", default="carry,value,mom", help="factor 策略用哪些因子（逗號分隔：carry、value、mom）")
    ap.add_argument("--combine", choices=["rank", "z"], default="rank")
    ap.add_argument("--value-def", choices=["5y", "3y", "10ymean"], default="5y")
    ap.add_argument("--mom-months", type=int, default=12)
    ap.add_argument("--random", type=int, default=0, help="隨機排序對照：跑 N 次隨機排列，報告 t 分佈（不跑正式策略）")
    ap.add_argument("--seed", type=int, default=20260925)
    ap.add_argument("--reer", type=Path, default=ROOT / "data_forex_rates" / "reer")
    ap.add_argument("--pairs", nargs="*", default=None)
    ap.add_argument("--lookback", type=int, default=12)
    ap.add_argument("--entry", type=int, default=55)
    ap.add_argument("--exit", dest="exit_", type=int, default=20)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--trend-filter", type=int, default=0)
    ap.add_argument("--carry-vol-weight", action="store_true", help="利差策略用波動率權重而非等權")
    ap.add_argument("--spread-mult", type=float, default=2.0)
    ap.add_argument("--slip-pip", type=float, default=0.2)
    ap.add_argument("--swap-haircut", type=float, default=1.0)
    ap.add_argument("--no-swap", action="store_true")
    ap.add_argument("--vol-target", type=float, default=0.10)
    ap.add_argument("--vol-window", type=int, default=60)
    ap.add_argument("--start", default="2003-06-01")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--inspect", action="store_true", help="只看交易機制（曝險、換手、成本、swap、筆數），不看績效")
    args = ap.parse_args()

    pairs = args.pairs or (USD_PAIRS if args.strategy in ("carry", "factor") else BASKET)
    # 訊號要用到樣本起點之前的歷史（12 個月動量、55 日通道、60 日波動）→ 多載一年
    pre_start = (pd.Timestamp(args.start) - pd.DateOffset(months=14)).strftime("%Y-%m-%d")
    prices = load_prices(args.root, pairs, pre_start, args.end)
    idx = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in prices.values()])))
    rates_d = None
    if not args.no_swap or args.strategy in ("carry", "factor"):
        ccys = sorted({p[:3] for p in pairs} | {p[3:] for p in pairs})
        rates_d = daily_rates(load_rates(args.rates, ccys), idx, lag_months=1)
    adj = None
    if args.strategy == "tsmom":
        w = strat_tsmom(prices, idx, args.lookback, args.vol_window, args.vol_target)
        label = f"TSMOM {args.lookback}m"
    elif args.strategy == "turtle":
        w, adj = strat_turtle(prices, idx, args.entry, args.exit_, args.vol_window, args.vol_target)
        label = f"Turtle {args.entry}/{args.exit_}"
    elif args.strategy == "carry":
        w = strat_carry(prices, idx, rates_d, args.top, args.trend_filter, args.vol_window, args.vol_target,
                        equal_weight=not args.carry_vol_weight)
        label = f"Carry top{args.top}" + (f" +trend{args.trend_filter}m" if args.trend_filter else "")
    else:
        factors = [f.strip() for f in args.factors.split(",") if f.strip()]
        ccys = sorted({p[:3] for p in pairs} | {p[3:] for p in pairs})
        reer_m = load_reer(args.reer, [c for c in ccys if c != "USD"]) if "value" in factors else None
        if args.random:
            rng = np.random.default_rng(args.seed)
            ts = []
            for k in range(args.random):
                wr = strat_factor(prices, idx, rates_d, reer_m, factors, args.top, args.combine, args.value_def, args.mom_months, rng=rng)
                d, c = portfolio_pnl(prices, wr, None if args.no_swap else rates_d, args.spread_mult, args.slip_pip, args.swap_haircut)
                d = d[(d.index >= args.start) & (d.index <= args.end)]
                ts.append(stats(d, c.loc[d.index])[0]["t"])
            ts = np.array(ts)
            pct = {q: round(float(np.percentile(ts, q)), 2) for q in (2.5, 5, 25, 50, 75, 95, 97.5)}
            print(f"== 隨機排序對照 {args.random} 次（top{args.top}、加價 {args.swap_haircut:g}%）：t 中位 {pct[50]}、"
                  f"百分位 {pct}")
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                Path(f"{args.out}_random_t.json").write_text(json.dumps({"n": args.random, "seed": args.seed, "swap_haircut": args.swap_haircut,
                                                                          "top": args.top, "percentiles": pct, "t": [round(float(x), 3) for x in ts]}),
                                                              encoding="utf-8")
            return
        siglog = []
        w = strat_factor(prices, idx, rates_d, reer_m, factors, args.top, args.combine, args.value_def, args.mom_months, log=siglog)
        label = f"Factor[{'+'.join(factors)}] top{args.top} {args.combine}" + (f" value={args.value_def}" if "value" in factors else "") + \
                (f" mom={args.mom_months}m" if "mom" in factors else "")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(siglog).to_csv(f"{args.out}_signals.csv", index=False)
    if args.inspect:
        ww = w[(w.index >= args.start) & (w.index <= args.end)]
        years = (ww.index[-1] - ww.index[0]).days / 365.25
        gross = ww.abs().sum(axis=1)
        turnover = (ww - ww.shift(1)).abs().sum(axis=1).sum() / years
        cost = 0.0
        swap = 0.0
        for p in ww.columns:
            px = prices[p].reindex(ww.index).ffill()
            unit_cost = (args.spread_mult * px["Spread"] / 2.0 + args.slip_pip * PIP[p]) / px["Mid"]
            cost += float(((ww[p] - ww[p].shift(1)).abs() * unit_cost).sum()) / years
            if rates_d is not None:
                diff = (rates_d[p[:3]] - rates_d[p[3:]]).reindex(ww.index).ffill().fillna(0.0) / 100.0
                swap += float((ww[p].shift(1).fillna(0) * diff / 365.0 - ww[p].shift(1).abs().fillna(0) * args.swap_haircut / 100 / 365).sum()) / years
        changes = int(((ww != 0) & (ww.shift(1) == 0)).sum().sum())
        print(f"== {label} 機制檢查（{ww.index[0].date()} → {ww.index[-1].date()}，{years:.1f} 年）")
        print(f"  平均總曝險 {gross.mean():.2f} 倍名義（最大 {gross.max():.2f}）、平均持倉對數 {(ww != 0).sum(axis=1).mean():.1f}、"
              f"進場次數 {changes}（每年 {changes / years:.0f}）、每年換手 {turnover:.2f} 倍名義")
        print(f"  每年點差+滑點成本 {cost * 100:.2f}% 名義本金、每年 swap 淨額 {swap * 100:+.2f}%（含加價）")
        if adj is not None:
            print(f"  停損單成交價修正合計 {float(adj[(adj.index >= args.start)].sum().sum()) * 100:+.2f}%（正 = 對我們不利）")
        return
    daily, contrib = portfolio_pnl(prices, w, None if args.no_swap else rates_d, args.spread_mult, args.slip_pip, args.swap_haircut)
    if adj is not None:
        daily = daily - adj.sum(axis=1)
        contrib = contrib - adj
    daily = daily[(daily.index >= args.start) & (daily.index <= args.end)]
    contrib = contrib.loc[daily.index]
    st, monthly = stats(daily, contrib)
    st = {"label": label, "spread_mult": args.spread_mult, "slip_pip": args.slip_pip, "swap_haircut": args.swap_haircut,
          "no_swap": args.no_swap, "vol_target": args.vol_target, "vol_window": args.vol_window, "start": args.start, "end": args.end} | st
    print(f"== {label}  點差×{args.spread_mult:g} 滑點 {args.slip_pip:g}pip swap 加價 {args.swap_haircut:g}%{'（不含 swap）' if args.no_swap else ''}")
    print(f"  月數 {st['months']}、t = {st['t']}、年化 {st['ann_return_pct']}%、波動 {st['ann_vol_pct']}%、夏普 {st['sharpe']}、"
          f"最大回撤 {st['max_dd_pct']}%、正年 {st['pos_years']}、最差年 {st['worst_year']}、正貢獻對數 {st['pairs_positive']}")
    print(f"  2003–2012：t {st['t_before_split']}、累計 {st['ret_before_split_pct']}%｜2013–2026：t {st['t_from_split']}、累計 {st['ret_from_split_pct']}%")
    print("  按年%：" + "、".join(f"{k} {v:+.1f}" for k, v in st["yearly_pct"].items()))
    print("  各對貢獻%：" + "、".join(f"{k} {v:+.2f}" for k, v in st["pair_contrib_pct"].items()))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        monthly.to_csv(f"{args.out}_monthly.csv", header=["ret"])
        contrib.sum().to_csv(f"{args.out}_pairs.csv", header=["contrib"])
        Path(f"{args.out}_stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
