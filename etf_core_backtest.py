#!/usr/bin/env python3
"""ETF 核心配置回測（預先登記：stock_research/ETF_CORE_BACKTEST.md，寫程式與抓數據之前已 commit；只跑一次）。

    python3 etf_core_backtest.py --inspect      # 只看數據起點、缺日、極端單日報酬（不算績效）
    python3 etf_core_backtest.py                # 正式：10 個組合 × 主設定與敏感度 → research/etf_core/

描述性比較：固定權重、不優化、不按結果挑組合（登記第一、六節）。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402

OUT = ROOT / "research" / "etf_core"
MAIN_START = date(2008, 1, 2)
AUX_START = date(2005, 1, 3)
COST = 0.0005                    # 每邊 5 bps（登記第四節）
TAX = 0.30                       # 香港投資人持美國上市 ETF 的股息預扣
HK_LISTED = {"2800.HK"}
NINE = ["SPY", "EWH", "EWJ", "EWT", "EWY", "EWA", "EWC", "INDA", "EWS"]
PORTS = {   # 登記第三節（寫死）
    "P1 全美股": {"SPY": 1.0},
    "P2 全港股": {"2800.HK": 1.0},
    "P3 港美各半": {"2800.HK": 0.5, "SPY": 0.5},
    "P4 全球股票": {"SPY": 0.6, "EFA": 0.3, "EEM": 0.1},
    "P5 9國等權股票": {t: 1 / 9 for t in NINE},
    "P6 美國60/40": {"SPY": 0.6, "IEF": 0.4},
    "P7 全球60/40": {"SPY": 0.36, "EFA": 0.18, "EEM": 0.06, "IEF": 0.4},
    "P8 永久組合": {"SPY": 0.25, "TLT": 0.25, "GLD": 0.25, "SHY": 0.25},
    "P9 全天候": {"SPY": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075},
    "P10 全球60/40+趨勢(探索性)": {"SPY": 0.36, "EFA": 0.18, "EEM": 0.06, "IEF": 0.4},
}
AUX_PORTS = ["P1 全美股", "P2 全港股", "P3 港美各半", "P4 全球股票", "P6 美國60/40", "P7 全球60/40", "P8 永久組合"]
REF = {"VT（對照列）": {"VT": 1.0}}
TREND = "P10 全球60/40+趨勢(探索性)"
SMA_N = 210                      # 10 個月
TICKERS = sorted({t for w in list(PORTS.values()) + list(REF.values()) for t in w} | {"BIL", "SHY"})


def load(t: str, tax: bool) -> tuple[pd.Series, pd.Series]:
    """(每日總回報（以美股日曆前的原始交易日計）, 還原收市價)。tax：美國上市 ETF 的現金股息乘 0.7。"""
    s = md.load_series(t)
    idx = pd.to_datetime(sorted(s))
    adj = pd.Series([s[d][1] for d in sorted(s)], index=idx)
    raw = pd.Series([s[d][2] for d in sorted(s)], index=idx)
    ret = adj.pct_change()
    if tax and t not in HK_LISTED:
        divs, _ = md.load_actions(t)
        for d, amt in divs:
            ts = pd.Timestamp(d)
            if ts in ret.index:
                i = ret.index.get_loc(ts)
                if i > 0 and raw.iloc[i - 1] > 0:
                    ret.iloc[i] -= TAX * amt / raw.iloc[i - 1]
    return ret, adj


def build(tax: bool, start: date) -> tuple[pd.DatetimeIndex, pd.DataFrame, pd.DataFrame]:
    """美股交易日曆上的每日回報矩陣（非美股交易日的回報併入下一個美股日；未上市 = NaN）。"""
    cal = pd.to_datetime(sorted(d for d in md.load_series("SPY") if d >= start))
    R, A = {}, {}
    for t in TICKERS:
        ret, adj = load(t, tax)
        lvl = (1 + ret.fillna(0)).cumprod()
        lvl = lvl.reindex(lvl.index.union(cal)).ffill().reindex(cal)        # 港股假期：前一收市價
        first = ret.index[1] if len(ret) > 1 else None
        r = lvl.pct_change()
        if first is not None:
            r[cal <= first] = np.nan                                       # 上市（有回報）之前 = NaN
        R[t] = r
        A[t] = adj.reindex(adj.index.union(cal)).ffill().reindex(cal)
    return cal, pd.DataFrame(R), pd.DataFrame(A)


def cash_ret(R: pd.DataFrame) -> pd.Series:
    return R["BIL"].where(R["BIL"].notna(), R["SHY"]).fillna(0)


def is_rebal(cal: pd.DatetimeIndex, i: int, freq: str) -> bool:
    if i == 0:
        return True
    a, b = cal[i - 1], cal[i]
    if freq == "year":
        return a.year != b.year
    if freq == "quarter":
        return (a.year, (a.month - 1) // 3) != (b.year, (b.month - 1) // 3)
    if freq == "month":
        return (a.year, a.month) != (b.year, b.month)
    return False


def target(w: dict, R: pd.DataFrame, i: int) -> dict:
    """當天有回報（已上市）的資產才配；未上市的權重按比例攤給其餘（P5 INDA 2012 前）。"""
    have = {t: x for t, x in w.items() if not np.isnan(R[t].iloc[i]) or (i + 1 < len(R) and not np.isnan(R[t].iloc[i + 1]))}
    tot = sum(have.values())
    return {t: x / tot for t, x in have.items()} if tot else {}


def simulate(name: str, w: dict, cal, R: pd.DataFrame, A: pd.DataFrame, freq: str) -> tuple[pd.Series, float]:
    """回傳（每日組合回報, 平均年換手）。權重在再平衡日開市前設定，當日回報按該權重計（收市價回測近似）。"""
    trend = name == TREND
    cash = cash_ret(R)
    cash_t = "BIL"
    hold: dict = {}
    out = np.zeros(len(cal))
    turnover = 0.0
    sma = A.rolling(SMA_N, min_periods=SMA_N).mean() if trend else None
    for i in range(len(cal)):
        rb = is_rebal(cal, i, "month" if trend else freq)
        if rb:
            tgt = target(w, R, i)
            if trend and i > 0:
                tgt2 = {}
                for t, x in tgt.items():
                    px, ma = A[t].iloc[i - 1], sma[t].iloc[i - 1]       # 上月最後一個交易日收市 vs 10 個月均線
                    if np.isnan(ma) or px >= ma:
                        tgt2[t] = tgt2.get(t, 0) + x
                    else:
                        tgt2["__cash"] = tgt2.get("__cash", 0) + x
                tgt = tgt2
            tot = sum(hold.values()) or 1.0
            cur = {t: v / tot for t, v in hold.items()}
            tv = sum(abs(tgt.get(t, 0) - cur.get(t, 0)) for t in set(tgt) | set(cur))
            if i > 0:
                turnover += tv / 2
            hold = dict(tgt)
            cost = COST * tv
        else:
            cost = 0.0
        tot0 = sum(hold.values())
        new = {}
        for t, v in hold.items():
            r = cash.iloc[i] if t == "__cash" else R[t].iloc[i]
            new[t] = v * (1 + (0.0 if np.isnan(r) else r))
        tot1 = sum(new.values())
        out[i] = (tot1 / tot0 - 1 if tot0 else 0.0) - cost
        hold = new
    yrs = len(cal) / 252
    return pd.Series(out, index=cal, name=name), turnover / yrs


def metrics(r: pd.Series, cash: pd.Series) -> dict:
    lvl = (1 + r).cumprod()
    yrs = len(r) / 252
    peak = lvl.cummax()
    dd = lvl / peak - 1
    # 最長水下（由高位到收復的日曆日數；未收復的算到最後一日）
    longest, start = 0, None
    for d, x in dd.items():
        if x < 0 and start is None:
            start = d
        elif x >= 0 and start is not None:
            longest = max(longest, (d - start).days)
            start = None
    if start is not None:
        longest = max(longest, (dd.index[-1] - start).days)
    ex = r - cash.reindex(r.index).fillna(0)
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    roll5 = lvl.pct_change(252 * 5).dropna()
    cagr = lvl.iloc[-1] ** (1 / yrs) - 1
    mdd = float(dd.min())

    def seg(a, b):
        x = r[(r.index >= pd.Timestamp(a)) & (r.index < pd.Timestamp(b))]
        return float((1 + x).prod() ** (252 / len(x)) - 1) if len(x) > 20 else float("nan")
    return {"cagr": float(cagr), "vol": float(r.std() * np.sqrt(252)), "mdd": mdd,
            "longest_underwater_days": int(longest), "sharpe": float(ex.mean() / ex.std() * np.sqrt(252)),
            "calmar": float(cagr / -mdd) if mdd < 0 else float("nan"), "worst_year": float(yearly.min()),
            "positive_years": f"{int((yearly > 0).sum())}/{len(yearly)}",
            "cagr_2008_2015": seg("2008-01-01", "2016-01-01"), "cagr_2016_end": seg("2016-01-01", "2100-01-01"),
            "min_roll5y_annual": float((1 + roll5.min()) ** 0.2 - 1) if len(roll5) else float("nan"),
            "yearly": {int(k): float(v) for k, v in yearly.items()}, "start": str(r.index[0].date()),
            "end": str(r.index[-1].date())}


def inspect() -> None:
    cal, R, _ = build(False, AUX_START)
    for t in TICKERS:
        s = md.load_series(t)
        ds = sorted(s)
        r = R[t].dropna()
        ext = r[r.abs() > 0.12]
        print(f"{t:8} 數據 {ds[0]} ~ {ds[-1]}（{len(ds)} 日）  美股日曆上有回報 {len(r)} 日  "
              f"單日 |報酬| > 12%：{len(ext)} 日" + (f" {[(str(d.date()), round(float(x), 3)) for d, x in ext.items()][:6]}" if len(ext) else ""))


def run() -> None:
    res = {"settings": {}, "notes": "見 stock_research/ETF_CORE_BACKTEST.md"}
    OUT.mkdir(parents=True, exist_ok=True)
    for tag, tax, start, freq, ports in (("main", False, MAIN_START, "year", {**PORTS, **REF}),
                                         ("quarterly", False, MAIN_START, "quarter", PORTS),
                                         ("buy_hold", False, MAIN_START, "none", PORTS),
                                         ("tax30", True, MAIN_START, "year", PORTS),
                                         ("aux_2005", False, AUX_START, "year", {k: PORTS[k] for k in AUX_PORTS})):
        cal, R, A = build(tax, start)
        cash = cash_ret(R)
        out = {}
        for name, w in ports.items():
            if any(R[t].first_valid_index() is None for t in w):
                continue
            first = max(R[t].first_valid_index() for t in w) if name not in ("P5 9國等權股票",) else cal[1]
            r, to = simulate(name, w, cal, R, A, freq)
            r = r[r.index >= first]
            m = metrics(r, cash)
            m["turnover_per_year"] = to
            out[name] = m
            print(f"[{tag:9}] {name:26} {m['start']}  年化 {m['cagr']:+6.1%}  波幅 {m['vol']:5.1%}  MDD {m['mdd']:6.1%}  "
                  f"Sharpe {m['sharpe']:4.2f}  最差年 {m['worst_year']:+6.1%}  正年 {m['positive_years']}  "
                  f"水下最長 {m['longest_underwater_days']} 日  滾動5年最低 {m['min_roll5y_annual']:+.1%}  "
                  f"08-15 {m['cagr_2008_2015']:+.1%} / 16- {m['cagr_2016_end']:+.1%}", file=sys.stderr)
        res["settings"][tag] = out
    # 登記第六節：按最大回撤分三級，每級列年化回報最高的一個（主設定；P10 探索性不入選）
    main = {k: v for k, v in res["settings"]["main"].items() if k in PORTS and k != TREND}
    tiers = {}
    for lab, lo, hi in (("回撤 < 25%", -0.25, 0.0), ("回撤 25–40%", -0.40, -0.25), ("回撤 > 40%", -9.0, -0.40)):
        cand = {k: v for k, v in main.items() if lo < v["mdd"] <= hi}
        tiers[lab] = max(cand, key=lambda k: cand[k]["cagr"]) if cand else None
    res["tiers"] = tiers
    print(f"分級參考核心：{tiers}", file=sys.stderr)
    (OUT / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--inspect", action="store_true")
    args = a.parse_args()
    inspect() if args.inspect else run()


if __name__ == "__main__":
    main()
