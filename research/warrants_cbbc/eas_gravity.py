#!/usr/bin/env python3
"""結算日 max-pain 磁吸（第 3 項）：恒指期權（月／週）到期前一日的各行使價未平倉，算 max-pain 行使價 K*，
看到期日的結算價（EAS 近似：日市 15 分鐘 K 收盤平均，期貨轉現貨）是否比前一日收盤更靠近 K*。

資料：data/hkex_options/series/hsio_*.csv.gz、hsiwo_*.csv.gz（各系列每日 OI，遠期 ±12% 內）；
      <k15>/YYYY-MM-DD.json 恒指期貨 15 分鐘 K；canary/data_external/hsi_daily.csv。
到期日：系列最後出現的日期（T−1）之後的下一個交易日（週期權以到期代碼日期為準）。
對照：同一套 OI 用在到期前 3 個交易日（T−4→T−3），看「靠近 K*」是不是任何一天都會發生的回歸現象。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cbbc_heavy_zone import load_k15, basis_table  # noqa: E402

SER = ROOT / "data" / "hkex_options" / "series"
HSI = ROOT / "canary" / "data_external" / "hsi_daily.csv"


def load_series() -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in sorted(SER.glob("hsio_*.csv.gz")) + sorted(SER.glob("hsiwo_*.csv.gz"))]
    s = pd.concat(frames, ignore_index=True)
    s["date"] = pd.to_datetime(s["date"])
    return s


def max_pain(g: pd.DataFrame) -> tuple[float, float, float]:
    """回傳 (K*, 總 OI, 痛苦曲線在 K* 的值)。"""
    ks = np.sort(g["strike"].unique().astype(float))
    oi_c = g[g["cp"] == "C"].groupby("strike")["oi"].sum().reindex(ks, fill_value=0).to_numpy(float)
    oi_p = g[g["cp"] == "P"].groupby("strike")["oi"].sum().reindex(ks, fill_value=0).to_numpy(float)
    pain = np.array([(oi_c * np.clip(S - ks, 0, None)).sum() + (oi_p * np.clip(ks - S, 0, None)).sum() for S in ks])
    i = int(np.argmin(pain))
    return float(ks[i]), float(oi_c.sum() + oi_p.sum()), float(pain[i])


def expiry_events(s: pd.DataFrame, trading_days: list) -> pd.DataFrame:
    rows = []
    td = pd.DatetimeIndex(trading_days)
    for (prod, exp), g in s.groupby(["product", "expiry"]):
        last = g["date"].max()
        if prod == "hsiwo":
            T = pd.Timestamp(exp)
        else:
            nxt = td[td > last]
            if len(nxt) == 0:
                continue
            T = nxt[0]
        if T not in td or last not in td:
            continue
        gl = g[g["date"] == last]
        kstar, oi, _ = max_pain(gl)
        # 加權 OI 重心（另一個「磁吸點」定義）
        w = gl.groupby("strike")["oi"].sum()
        centroid = float((w.index.to_numpy(float) * w.to_numpy(float)).sum() / max(w.sum(), 1))
        rows.append({"product": prod, "expiry": exp, "T": T, "T1": last, "kstar": kstar, "oi": oi, "centroid": centroid,
                     "n_strikes": int(gl["strike"].nunique()), "days_cover": int((T - g["date"].min()).days)})
    return pd.DataFrame(rows).sort_values("T").reset_index(drop=True)


def attach_prices(ev: pd.DataFrame, k: pd.DataFrame, basis: pd.Series, hsi: pd.Series, lag_days: int = 0,
                  trading_days: list = None) -> pd.DataFrame:
    """對每個事件接上：前一日現貨收盤 S0、到期日開盤 S_open、EAS 近似 S_eas、到期日收盤。lag_days>0 → 把 T 往前挪當對照。"""
    td = pd.DatetimeIndex(trading_days)
    out = []
    for _, r in ev.iterrows():
        T = r["T"]
        if lag_days:
            pos = td.get_loc(T) - lag_days
            if pos < 1:
                continue
            T = td[pos]
        pos = td.get_loc(T)
        T1 = td[pos - 1]
        g = k[k["date"] == T]
        if len(g) < 20 or T not in basis.index or T1 not in hsi.index:
            continue
        bs = float(basis.loc[T])
        S0 = float(hsi.loc[T1])
        S_open = float(g.iloc[0]["open"]) - bs
        S_eas = float(g["close"].mean()) - bs
        S_close = float(hsi.loc[T]) if T in hsi.index else float(g.iloc[-1]["close"]) - bs
        out.append({**r.to_dict(), "T_used": T, "S0": S0, "S_open": S_open, "S_eas": S_eas, "S_close": S_close})
    return pd.DataFrame(out)


def evaluate(df: pd.DataFrame, anchor: str = "kstar") -> str:
    K = df[anchor]
    d0, d_eas = (df["S0"] - K).abs(), (df["S_eas"] - K).abs()
    d_open = (df["S_open"] - K).abs()
    toward_from_prev = np.sign(K - df["S0"]) * (df["S_eas"] - df["S0"])
    toward_intraday = np.sign(K - df["S_open"]) * (df["S_eas"] - df["S_open"])
    # 若前一日已在 K* 附近（<50 點）就沒有方向可言
    far = (df["S0"] - K).abs() >= 50
    far_o = (df["S_open"] - K).abs() >= 50
    L = [f"  n={len(df)}  |S0−K|中位 {d0.median():.0f} → |EAS−K| 中位 {d_eas.median():.0f}；靠近比例 {(d_eas < d0).mean():.0%}",
         f"  前收→EAS 朝 K 方向的位移（點）：平均 {toward_from_prev[far].mean():+.0f}，中位 {toward_from_prev[far].median():+.0f}，"
         f"正向比例 {(toward_from_prev[far] > 0).mean():.0%}（n={int(far.sum())}）",
         f"  開盤→EAS 朝 K 方向的位移（點）：平均 {toward_intraday[far_o].mean():+.0f}，中位 {toward_intraday[far_o].median():+.0f}，"
         f"正向比例 {(toward_intraday[far_o] > 0).mean():.0%}（n={int(far_o.sum())}）；|開盤−K| 中位 {d_open.median():.0f}"]
    # 以 |S0−K| 分層：離得遠的是否拉得多（磁吸應與距離成正比）
    if far.sum() >= 20:
        sub = df[far].copy()
        sub["dist"] = (sub["S0"] - K[far])
        sub["tw"] = toward_from_prev[far]
        q = pd.qcut(sub["dist"].abs(), 2, labels=["近", "遠"])
        for lab in ("近", "遠"):
            x = sub[q == lab]
            L.append(f"    |S0−K| {lab}（中位 {x['dist'].abs().median():.0f} 點）：位移 平均 {x['tw'].mean():+.0f} 正向 {(x['tw']>0).mean():.0%} n={len(x)}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k15", required=True)
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--csv")
    a = ap.parse_args()
    s = load_series()
    k = load_k15(Path(a.k15), a.start, a.end)
    hsi = pd.read_csv(HSI, parse_dates=["Date"]).set_index("Date")["Close"]
    tdays = sorted(set(k["date"].unique()) | set(hsi[(hsi.index >= a.start) & (hsi.index <= a.end)].index))
    basis = basis_table(k)
    ev = expiry_events(s, tdays)
    print(f"到期事件：{len(ev)}（月 {int((ev['product']=='hsio').sum())}、週 {int((ev['product']=='hsiwo').sum())}）")
    for prod, title in (("hsiwo", "週期權"), ("hsio", "月期權"), (None, "全部")):
        sub = ev if prod is None else ev[ev["product"] == prod]
        df = attach_prices(sub, k, basis, hsi, 0, tdays)
        print(f"\n== {title}：到期日 ==")
        print(evaluate(df))
        print("  （以 OI 重心取代 K*）")
        print(evaluate(df, "centroid"))
        for lag in (3,):
            dfl = attach_prices(sub, k, basis, hsi, lag, tdays)
            print(f"  -- 對照：同一套 OI、往前 {lag} 個交易日（非到期日） --")
            print(evaluate(dfl))
        if prod is None and a.csv:
            df.to_csv(a.csv, index=False)
            print("已寫", a.csv)


if __name__ == "__main__":
    main()
