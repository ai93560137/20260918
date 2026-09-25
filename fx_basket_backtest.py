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
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
from scripts.fetch_fx_rates import INFO_SERIES, REER_SERIES as _REER_ALL, SERIES as _RATES_ALL  # noqa: E402
from scripts.fetch_forex import INSTRUMENTS  # noqa: E402

USD_PAIRS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
G10 = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK", "DKK"}
EM_PAIRS = [p for p, v in INSTRUMENTS.items() if v[2] in ("em1", "em2")]
COT_CODE = {"EUR": "099741", "JPY": "097741", "GBP": "096742", "CHF": "092741", "CAD": "090741", "AUD": "232741", "NZD": "112741",
            "MXN": "095741", "BRL": "102741", "ZAR": "122741"}
CROSSES = ["EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY", "EURGBP", "EURCHF", "EURAUD", "EURCAD",
           "GBPCHF", "GBPAUD", "AUDNZD", "AUDCAD"]
BASKET = USD_PAIRS + CROSSES


def pip_of(pair: str) -> float:
    """1 pip = 小數位 − 1（EURUSD 0.0001、USDJPY 0.01）；em 組小數位在 data_forex/<PAIR>/_done.json。"""
    dec = INSTRUMENTS[pair][1]
    if dec is None:
        f = ROOT / "data_forex" / pair / "_done.json"
        dec = json.loads(f.read_text()).get("decimals", 5) if f.exists() else 5
    return 10.0 ** -(dec - 1)


class _Pip(dict):
    def __missing__(self, k):
        self[k] = pip_of(k)
        return self[k]


PIP = _Pip()
# 各貨幣三個月利率：主系列 → 備援（月，%）；日頻備援重採樣成月平均；表在 scripts/fetch_fx_rates.py（含新興市場）
RATE_SERIES = {c: [sid for sid in ids if sid not in ("ECBMRRFR",)] for c, ids in _RATES_ALL.items()}
REER_SERIES = dict(_REER_ALL)
TENY_SERIES = {c: f"IRLTLT01{k}M156N" for c, k in
               {"USD": "US", "EUR": "EZ", "GBP": "GB", "JPY": "JP", "CHF": "CH", "AUD": "AU", "NZD": "NZ", "CAD": "CA", "MXN": "MX", "ZAR": "ZA",
                "PLN": "PL", "HUF": "HU", "CZK": "CZ", "SEK": "SE", "NOK": "NO", "DKK": "DK", "ILS": "IL", "KRW": "KR"}.items()}


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
        if m1 and pair not in EM_PAIRS:                                       # em 組沒有 HistData M1，只有近 62 天，不能當起點
            start = max(start, pd.Timestamp(m1[:10]))
    if pair in EM_PAIRS:                                                      # em 組：H1 檔第一筆 = 真數據起點
        h1 = ROOT / "data_forex" / pair / f"{pair}_H1.csv.gz"
        if h1.exists():
            import gzip
            with gzip.open(h1, "rt", encoding="utf-8") as fh:
                next(fh)
                start = max(start, pd.Timestamp(next(fh)[:10]))
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


def fixed_spreads(root: Path, pairs: list[str], start: str = "2003-06-01", end: str = "2006-12-31") -> dict[str, float]:
    """每對 Dukascopy 買賣價差中位數（start→end）——FRED 單一價樣本用的固定點差（FX_COT_OOS_BACKTEST.md F1）。"""
    out = {}
    for p in pairs:
        d = root / "data_forex" / p
        bid = pd.read_csv(d / f"{p}_D1.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
        ask = pd.read_csv(d / f"{p}_D1_ask.csv.gz", parse_dates=["Time"]).set_index("Time")["Close"]
        sp = (ask - bid)
        w = sp.loc[start:end]
        if (w > 0).sum() < 250:                                          # 該窗沒有真買賣價（例如 USDMXN 真數據 2007-03 起）→ 真數據起 3 年
            rs = real_start(p)
            w = sp.loc[rs:rs + pd.DateOffset(years=3)]
            print(f"  {p}：{start}→{end} 沒有真價差，改用真數據起 3 年（{rs.date()} 起）")
        out[p] = float(w[w > 0].median())
    return out


def load_prices_fred(root: Path, pairs: list[str], start: str, end: str, spreads: dict[str, float]) -> dict[str, pd.DataFrame]:
    """FRED H.10 紐約中午價（data_forex/<PAIR>/_ref_fred.csv.gz，Date,Close）→ 與 load_prices 同格式：Mid = Close、Spread 固定、開高低 = 收。"""
    out = {}
    for p in pairs:
        f = root / "data_forex" / p / "_ref_fred.csv.gz"
        s_ = pd.read_csv(f, parse_dates=["Date"]).set_index("Date")["Close"].astype(float)
        s_ = s_[(s_.index >= start) & (s_.index <= end)]
        s_ = s_[s_.index.weekday < 5]
        df = pd.DataFrame({"Open": s_, "High": s_, "Low": s_, "Close": s_, "AskClose": s_ + spreads[p], "Mid": s_, "Spread": spreads[p]})
        df.index.name = "Time"
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


def load_teny(info_dir: Path, ccys: list[str]) -> pd.DataFrame:
    """OECD 十年期公債殖利率月表（%，月底索引）；沒有的貨幣整欄 NaN。"""
    cols = {}
    for c in ccys:
        f = info_dir / f"{TENY_SERIES.get(c, '')}.csv"
        cols[c] = (pd.read_csv(f, parse_dates=["Date"]).set_index("Date")["Value"].astype(float).resample("ME").last()
                   if f.exists() else pd.Series(dtype=float))
    return pd.DataFrame(cols).sort_index()


def load_vix(info_dir: Path) -> pd.Series:
    return pd.read_csv(info_dir / "VIXCLS.csv", parse_dates=["Date"]).set_index("Date")["Value"].astype(float).sort_index()


def load_cot(cot_dir: Path, ccys: list[str], window: int = 156, min_weeks: int = 52, raw: bool = False, calendar: bool = False) -> pd.DataFrame:
    """CFTC 非商業淨部位比 (多−空)/未平倉 → 相對過去 window 週的 z 分數（raw=True 就用原比率）；索引 = 報告日（週二）。
    calendar=True：窗改為 window × 7 個日曆天（1992 年前是雙週報，FX_COT_OOS_BACKTEST.md 用這個）。"""
    df = pd.read_csv(cot_dir / "cot_currencies.csv", dtype={"code": str}, parse_dates=["date"])
    out = {}
    for c in ccys:
        code = COT_CODE.get(c)
        if not code:
            continue
        d = df[df["code"] == code].sort_values("date").drop_duplicates("date").set_index("date")
        net = ((d["nc_long"] - d["nc_short"]) / d["oi"].replace(0, np.nan)).dropna()
        if raw:
            out[c] = net
        else:
            roll = net.rolling(f"{window * 7}D", min_periods=min_weeks) if calendar else net.rolling(window, min_periods=min_weeks)
            m, sd = roll.mean(), roll.std()
            out[c] = (net - m) / sd.replace(0, np.nan)
    # 各合約報告日不一定同步（1992 年前雙週報、各合約起迄不同）→ 轉成日頻、每欄各自前向填補最多 21 天；
    # 之後「≤ 調倉日 − 3 天的最後一列」就是每個貨幣各自最近 21 天內的報告（2026-09-25 發現英鎊 1991–92 被漏掉後修正，E3 數字不變）
    df_ = pd.DataFrame(out).sort_index()
    return df_.resample("D").last().ffill(limit=21)


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
            hc = swap_haircut[p] if isinstance(swap_haircut, dict) else swap_haircut
            pnl += w_prev * diff / 365.0 - w_prev.abs() * hc / 100.0 / 365.0
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


def k_of(rule: str, n: int, top: int) -> int:
    if rule == "fixed":
        return top
    if rule == "quarter":
        return max(2, int(round(n / 4)))
    if rule == "third":
        return max(2, int(round(n / 3)))
    raise SystemExit(f"未知 k-rule {rule}")


def strat_factor(prices, idx, rates_d: pd.DataFrame, reer_m: pd.DataFrame | None, factors: list[str], top: int,
                 combine: str = "rank", value_def: str = "5y", mom_months: int = 12, rng: np.random.Generator | None = None,
                 log: list | None = None, k_rule: str = "fixed", rates_m: pd.DataFrame | None = None, ratemom_months: int = 6,
                 teny_m: pd.DataFrame | None = None, cot_w: pd.DataFrame | None = None, cot_follow: bool = False,
                 vix: pd.Series | None = None, vix_max: float = 0.0, vix_rel: bool = False, freq: str = "M") -> pd.DataFrame:
    """三因子橫截面籃子（FX_THREE_FACTOR_BACKTEST.md 第 1、2 節）：每月最後交易日，7 個外幣按
    carry（三個月利率，延後一個月）、value（−REER 過去 5 年變動，延後一個月）、mom（對美元 12 個月即期變動）各排名（1 = 最差），
    合成 = 名次平均（或 z 分數平均）；做多最高 top 個、做空最低 top 個，各 1/top；任一因子缺值的貨幣該月不參與。
    rng 給了 = 隨機排序對照（每月隨機排列取代合成分數）。
    路線 A／B 擴充：k_rule 動態 k_t；因子 ratemom（三個月利率過去 ratemom_months 個月變動，延後一個月）、term（十年期 − 三個月，延後一個月）、
    cot（CFTC 非商業淨部位 z 分數，反向：−z；cot_follow=True 取 +z；用月底 − 3 天前最後一份報告）；vix_max > 0：月底 VIX > 門檻該月空手
    （vix_rel=True：門檻 = 過去 252 個交易日平均 + 1 標準差）。"""
    ccy_pair = {p[:3] if p.endswith("USD") else p[3:]: p for p in prices if "USD" in p}
    mids = pd.DataFrame({p: df["Mid"] for p, df in prices.items()}).reindex(idx).ffill()
    month_ends = mids.groupby(mids.index.to_period("W-FRI" if freq == "W" else "M")).tail(1).index   # 調倉日（週頻 = 每週最後交易日）
    # 外幣對美元的價格（1 單位外幣值多少美元），調倉日表；動量用日期位移（週頻時不能用列位移）
    spot_d = pd.DataFrame({c: (mids[p] if p.endswith("USD") else 1.0 / mids[p]) for c, p in ccy_pair.items()})
    spot = spot_d.loc[month_ends]
    if freq == "M":                                                  # 月頻：與登記時一致（月底表往前 mom_months 列）
        mom_m = spot / spot.shift(mom_months) - 1.0
    else:                                                            # 週頻：日期位移（不能用列位移）
        past_idx = [spot_d.index[spot_d.index <= me - pd.DateOffset(months=mom_months)] for me in month_ends]
        ref = pd.DataFrame([spot_d.loc[pi[-1]] if len(pi) else pd.Series(np.nan, index=spot_d.columns) for pi in past_idx], index=month_ends)
        mom_m = spot / ref - 1.0
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
    ratemom_m = term_m = None
    if "ratemom" in factors or "term" in factors:
        r = rates_m[list(ccy_pair)]
        if "ratemom" in factors:
            ratemom_m = r.diff(ratemom_months).shift(1)
            ratemom_m = ratemom_m.reindex(ratemom_m.index.union(month_ends)).ffill().loc[month_ends]
        if "term" in factors:
            t10 = teny_m.reindex(columns=list(ccy_pair))
            term_m = (t10 - r.reindex(t10.index)).shift(1)
            term_m = term_m.reindex(term_m.index.union(month_ends)).ffill().loc[month_ends]
    w = pd.DataFrame(0.0, index=idx, columns=mids.columns)
    for i, me in enumerate(month_ends):
        table = {}
        if "carry" in factors:
            table["carry"] = rates_d.loc[me, list(ccy_pair)]
        if "mom" in factors:
            table["mom"] = mom_m.loc[me]
        if "value" in factors:
            table["value"] = value_m.loc[me]
        if "ratemom" in factors:
            table["ratemom"] = ratemom_m.loc[me]
        if "term" in factors:
            table["term"] = term_m.loc[me]
        if "cot" in factors:
            avail = cot_w[cot_w.index <= me - pd.Timedelta(days=3)]
            if avail.empty or (me - avail.index[-1]).days > 21:
                continue
            z = avail.iloc[-1].reindex(list(ccy_pair))
            table["cot"] = z if cot_follow else -z
        f = pd.DataFrame(table).dropna()
        k = k_of(k_rule, len(f), top)
        if len(f) < 2 * k:
            continue
        if vix is not None and vix_max > 0:
            v_hist = vix[vix.index <= me]
            if v_hist.empty:
                continue
            thr = (v_hist.iloc[-252:].mean() + v_hist.iloc[-252:].std()) if vix_rel else vix_max
            if v_hist.iloc[-1] > thr:
                if log is not None:
                    log.append({"month_end": str(me.date()), "longs": [], "shorts": [], "vix": round(float(v_hist.iloc[-1]), 2), "flat": True})
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
        longs, shorts = ranked[-k:], ranked[:k]
        if log is not None:
            log.append({"month_end": str(me.date()), "n": len(f), "k": k, "longs": longs, "shorts": shorts,
                        **{f"{kk}_{c}": round(float(f.loc[c, kk]), 4) for kk in f.columns for c in f.index}})
        nxt_end = month_ends[i + 1] if i + 1 < len(month_ends) else idx[-1]
        span = idx[(idx > me) & (idx <= nxt_end)]
        for c, direction in [(c, 1) for c in longs] + [(c, -1) for c in shorts]:
            p = ccy_pair[c]
            sign_pair = 1 if p.endswith("USD") else -1
            w.loc[span, p] = direction * sign_pair / k
    return w


# ---------------------------------------------------------------- 統計
def stats(daily: pd.Series, contrib: pd.DataFrame, split: str = "2013-01-01") -> dict:
    monthly = daily.groupby(daily.index.to_period("M")).sum()
    monthly.index = monthly.index.to_timestamp("M")
    weekly = daily.groupby(daily.index.to_period("W-FRI")).sum()

    def t_of(m: pd.Series) -> float:
        return float(m.mean() / m.std(ddof=1) * math.sqrt(len(m))) if len(m) > 2 and m.std(ddof=1) > 0 else float("nan")
    eq = (1 + daily).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    yearly = daily.groupby(daily.index.year).sum()
    pairs = contrib.sum().sort_values(ascending=False)
    m1, m2 = monthly[monthly.index < split], monthly[monthly.index >= split]
    return {"months": int(len(monthly)), "t": round(t_of(monthly), 2), "t_weekly": round(t_of(weekly), 2), "ann_return_pct": round(float(daily.mean() * 252 * 100), 2),
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
    ap.add_argument("--factors", default="carry,value,mom", help="factor 策略用哪些因子（逗號分隔：carry、value、mom、ratemom、term、cot）")
    ap.add_argument("--k-rule", choices=["fixed", "quarter", "third"], default="fixed", help="多空各幾個：fixed = --top；quarter = max(2, N_t/4)；third")
    ap.add_argument("--ratemom-months", type=int, default=6)
    ap.add_argument("--cot-window", type=int, default=156)
    ap.add_argument("--cot-raw", action="store_true", help="COT 用原始淨部位比，不做 z 分數")
    ap.add_argument("--cot-calendar", action="store_true", help="COT z 的窗用日曆天（--cot-window × 7 天），早期雙週報用")
    ap.add_argument("--rebalance", choices=["M", "W"], default="M", help="factor 策略調倉頻率：月底或每週最後交易日")
    ap.add_argument("--price-source", choices=["dukascopy", "fred"], default="dukascopy",
                    help="fred = FRED H.10 單一價（1971 起），點差固定為該對 2003-06→2006-12 Dukascopy 價差中位數 × spread-mult")
    ap.add_argument("--split", default="2013-01-01", help="分段日期（統計用）")
    ap.add_argument("--cot-follow", action="store_true", help="COT 跟隨投機客（預設反向）")
    ap.add_argument("--vix-max", type=float, default=0.0, help="> 0：月底 VIX 高於此值該月空手")
    ap.add_argument("--vix-rel", action="store_true", help="VIX 門檻改為過去 252 日平均 + 1 標準差")
    ap.add_argument("--swap-haircut-em", type=float, default=None, help="非 G10 貨幣對的 swap 加價（%），預設同 --swap-haircut")
    ap.add_argument("--universe", choices=["g7", "wide"], default="g7", help="wide = 七大 + em 組全部（再用 --exclude 剔）")
    ap.add_argument("--exclude", nargs="*", default=[], help="剔除的貨幣（如 TRY DKK）")
    ap.add_argument("--only-new", action="store_true", help="只用 em 組（不含 G7）")
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
    if args.strategy == "factor" and args.universe == "wide" and not args.pairs:
        pairs = ([] if args.only_new else USD_PAIRS) + [p for p in EM_PAIRS if (ROOT / "data_forex" / p / f"{p}_D1.csv.gz").exists()]
    pairs = [p for p in pairs if not any(c in p for c in args.exclude)]
    haircut = args.swap_haircut
    if args.swap_haircut_em is not None:
        haircut = {p: (args.swap_haircut if (p[:3] in G10 and p[3:] in G10) else args.swap_haircut_em) for p in pairs}
    # 訊號要用到樣本起點之前的歷史（12 個月動量、55 日通道、60 日波動）→ 多載一年
    pre_start = (pd.Timestamp(args.start) - pd.DateOffset(months=14)).strftime("%Y-%m-%d")
    if args.price_source == "fred":
        base_sp = fixed_spreads(args.root, pairs)
        print("固定點差（Dukascopy 2003-06→2006-12 價差中位數）：" + "、".join(f"{p} {v / PIP[p]:.2f} pip" for p, v in base_sp.items()))
        prices = load_prices_fred(args.root, pairs, pre_start, args.end, base_sp)
    else:
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
        rates_m = load_rates(args.rates, ccys)
        info_dir = args.rates / "info"
        teny_m = load_teny(info_dir, ccys) if "term" in factors else None
        cot_w = load_cot(args.rates / "cot", ccys, args.cot_window, raw=args.cot_raw, calendar=args.cot_calendar) if "cot" in factors else None
        vix = load_vix(info_dir) if args.vix_max > 0 else None
        extra = dict(k_rule=args.k_rule, rates_m=rates_m, ratemom_months=args.ratemom_months, teny_m=teny_m, cot_w=cot_w,
                     cot_follow=args.cot_follow, vix=vix, vix_max=args.vix_max, vix_rel=args.vix_rel, freq=args.rebalance)
        if args.random:
            rng = np.random.default_rng(args.seed)
            ts = []
            for k in range(args.random):
                wr = strat_factor(prices, idx, rates_d, reer_m, factors, args.top, args.combine, args.value_def, args.mom_months, rng=rng, **extra)
                d, c = portfolio_pnl(prices, wr, None if args.no_swap else rates_d, args.spread_mult, args.slip_pip, haircut)
                d = d[(d.index >= args.start) & (d.index <= args.end)]
                ts.append(stats(d, c.loc[d.index], args.split)[0]["t" if args.rebalance == "M" else "t_weekly"])
            ts = np.array(ts)
            pct = {q: round(float(np.percentile(ts, q)), 2) for q in (2.5, 5, 25, 50, 75, 95, 97.5)}
            print(f"== 隨機排序對照 {args.random} 次（top{args.top}、加價 {args.swap_haircut:g}%）：t 中位 {pct[50]}、"
                  f"百分位 {pct}")
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                Path(f"{args.out}_random_t.json").write_text(json.dumps({"n": args.random, "seed": args.seed, "swap_haircut": args.swap_haircut, "swap_haircut_em": args.swap_haircut_em, "pairs": pairs,
                                                                          "top": args.top, "percentiles": pct, "t": [round(float(x), 3) for x in ts]}),
                                                              encoding="utf-8")
            return
        siglog = []
        w = strat_factor(prices, idx, rates_d, reer_m, factors, args.top, args.combine, args.value_def, args.mom_months, log=siglog, **extra)
        label = f"Factor[{'+'.join(factors)}] " + (f"top{args.top}" if args.k_rule == "fixed" else f"k={args.k_rule}") + f" {args.combine}" + \
                (f" value={args.value_def}" if "value" in factors else "") + (f" mom={args.mom_months}m" if "mom" in factors else "") + \
                (f" ratemom={args.ratemom_months}m" if "ratemom" in factors else "") + \
                (f" cot={'raw' if args.cot_raw else str(args.cot_window) + ('cal' if args.cot_calendar else 'w')}{'+follow' if args.cot_follow else ''}" if "cot" in factors else "") + \
                (" weekly" if args.rebalance == "W" else "") + (" FRED" if args.price_source == "fred" else "") + \
                (f" vix{'rel' if args.vix_rel else '>' + str(args.vix_max)}" if args.vix_max > 0 else "") + \
                (f" N={len(pairs)}" if args.universe == "wide" or args.pairs else "")
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
                hc = haircut[p] if isinstance(haircut, dict) else haircut
                swap += float((ww[p].shift(1).fillna(0) * diff / 365.0 - ww[p].shift(1).abs().fillna(0) * hc / 100 / 365).sum()) / years
        changes = int(((ww != 0) & (ww.shift(1) == 0)).sum().sum())
        print(f"== {label} 機制檢查（{ww.index[0].date()} → {ww.index[-1].date()}，{years:.1f} 年）")
        print(f"  平均總曝險 {gross.mean():.2f} 倍名義（最大 {gross.max():.2f}）、平均持倉對數 {(ww != 0).sum(axis=1).mean():.1f}、"
              f"進場次數 {changes}（每年 {changes / years:.0f}）、每年換手 {turnover:.2f} 倍名義")
        print(f"  每年點差+滑點成本 {cost * 100:.2f}% 名義本金、每年 swap 淨額 {swap * 100:+.2f}%（含加價）")
        if adj is not None:
            print(f"  停損單成交價修正合計 {float(adj[(adj.index >= args.start)].sum().sum()) * 100:+.2f}%（正 = 對我們不利）")
        return
    daily, contrib = portfolio_pnl(prices, w, None if args.no_swap else rates_d, args.spread_mult, args.slip_pip, haircut)
    if adj is not None:
        daily = daily - adj.sum(axis=1)
        contrib = contrib - adj
    daily = daily[(daily.index >= args.start) & (daily.index <= args.end)]
    contrib = contrib.loc[daily.index]
    st, monthly = stats(daily, contrib, args.split)
    st = {"label": label, "spread_mult": args.spread_mult, "slip_pip": args.slip_pip, "swap_haircut": args.swap_haircut, "swap_haircut_em": args.swap_haircut_em,
          "pairs": pairs, "exclude": args.exclude,
          "no_swap": args.no_swap, "vol_target": args.vol_target, "vol_window": args.vol_window, "start": args.start, "end": args.end} | st
    print(f"== {label}  點差×{args.spread_mult:g} 滑點 {args.slip_pip:g}pip swap 加價 {args.swap_haircut:g}%{'（不含 swap）' if args.no_swap else ''}")
    print(f"  月數 {st['months']}、t = {st['t']}、週報酬 t = {st['t_weekly']}、年化 {st['ann_return_pct']}%、波動 {st['ann_vol_pct']}%、夏普 {st['sharpe']}、"
          f"最大回撤 {st['max_dd_pct']}%、正年 {st['pos_years']}、最差年 {st['worst_year']}、正貢獻對數 {st['pairs_positive']}")
    print(f"  {args.split} 前：t {st['t_before_split']}、累計 {st['ret_before_split_pct']}%｜之後：t {st['t_from_split']}、累計 {st['ret_from_split_pct']}%")
    print("  按年%：" + "、".join(f"{k} {v:+.1f}" for k, v in st["yearly_pct"].items()))
    print("  各對貢獻%：" + "、".join(f"{k} {v:+.2f}" for k, v in st["pair_contrib_pct"].items()))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        monthly.to_csv(f"{args.out}_monthly.csv", header=["ret"])
        contrib.sum().to_csv(f"{args.out}_pairs.csv", header=["contrib"])
        Path(f"{args.out}_stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
