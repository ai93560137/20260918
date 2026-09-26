#!/usr/bin/env python3
"""金絲雀考核共用程式(口徑與雲垂陣 tradingview/canary_lab.py 一致)。

供 yellow_lab.py / red_lab.py 共用:
  fwd(px, h)           訊號日 T → T+1..T+h 的實現波動率(年化 %)與「h 日內見 −2% 單日」
  disasters(iv, px)    災難月:月度對沖短跨式虧損 > 1× 權利金的月份(以月首交易日標記)
  evaluate(...)        對一組訊號、一個標的,產出 RV 倍率 / Welch t / 下跌提升 / 誤報 / 綠燈下倍率 / 災難覆蓋
  us_lag1_for_hsi      HSI 第 d 日只用曆日嚴格早於 d 的最新美訊號
需 pandas。
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data_external")
W, Q = 252, 0.9


def s(f):
    return pd.read_csv(os.path.join(D, f), parse_dates=["Date"]).set_index("Date").Close.dropna()


def hi(x, q=Q, w=W):
    """x > 自身滾動 w 日 q 分位(窗口含當日)。"""
    return x > x.rolling(w).quantile(q)


def fwd(px, h=5):
    r = np.log(px).diff()
    rv, dn = [], []
    for i in range(len(r)):
        w = r.iloc[i + 1:i + 1 + h]
        rv.append(w.std() * np.sqrt(252) * 100 if len(w) == h else np.nan)
        dn.append(int((w < -0.02).any()) if len(w) == h else np.nan)
    return pd.Series(rv, index=r.index), pd.Series(dn, index=r.index)


def disasters(ivs, px):
    VEGA = 0.8 * np.sqrt(21 / 252)
    df = pd.concat([ivs.rename("iv"), px.rename("px")], axis=1, sort=True).dropna()
    df["r"] = np.log(df.px).diff()
    out = []
    for d0 in df.groupby(df.index.to_period("M")).head(1).index:
        i0 = df.index.get_loc(d0)
        if i0 + 21 >= len(df):
            break
        iv0 = df.iv.iloc[i0]
        rv = df.r.iloc[i0 + 1:i0 + 22].std() * np.sqrt(252) * 100
        if VEGA * (iv0 - rv) <= -VEGA * iv0:
            out.append(d0)
    return out


def welch_t(a, b):
    a, b = a.dropna(), b.dropna()
    if len(a) < 2 or len(b) < 2:
        return np.nan
    return (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))


def us_lag1_for_hsi(sig, hsi_index):
    sig = sig.dropna().astype(bool)
    pos = sig.index.searchsorted(hsi_index, side="left") - 1
    out = pd.Series(False, index=hsi_index)
    ok = pos >= 0
    out[ok] = sig.values[pos[ok]]
    return out


def evaluate(sigs, px, green, dis, lag_us_for_hsi=False, h=5, extra_h=None, min_n=30):
    """回傳 DataFrame(index=訊號名)。extra_h 給一個額外期限只算 RV 倍率(例如 10 日)。"""
    rv5, dn2 = fwd(px, h)
    rvx = fwd(px, extra_h)[0] if extra_h else None
    valid = rv5.dropna().index
    rows = []
    for name, sig in sigs.items():
        if lag_us_for_hsi:
            g_full = us_lag1_for_hsi(sig, valid)
            idx = valid[valid >= sig.dropna().index.min()]
        else:
            idx = sig.dropna().index.intersection(valid)
            g_full = sig.reindex(idx).fillna(False).astype(bool)
        g = g_full.reindex(idx).fillna(False).astype(bool)
        n = int(g.sum())
        if n < min_n:
            continue
        on, off = rv5[idx][g], rv5[idx][~g]
        rvr = on.mean() / off.mean()
        t = welch_t(on, off)
        lift = dn2[idx][g].mean() / max(dn2[idx].mean(), 1e-9)
        fa = (on < rv5[idx].median()).mean() * 100
        if lag_us_for_hsi:
            gidx = idx[us_lag1_for_hsi(green, idx).values]
        else:
            gidx = idx.intersection(green[green].index)
        gg = g.reindex(gidx).fillna(False).astype(bool)
        inc = rv5[gidx][gg].mean() / rv5[gidx][~gg].mean() if gg.sum() > 30 else np.nan
        cov = 0
        for d0 in dis:
            w = g_full.loc[:d0].tail(6)
            cov += int(bool(len(w)) and bool(w.any()))
        row = dict(訊號=name, 樣本日=len(idx), 亮燈日=n, 亮燈佔=g.mean() * 100,
                   RV倍率=rvr, t=t, 下跌提升=lift, 誤報=fa, 綠燈下倍率=inc,
                   災難覆蓋=f"{cov}/{len(dis)}")
        if rvx is not None:
            ix = idx.intersection(rvx.dropna().index)
            gx = g.reindex(ix).fillna(False).astype(bool)
            row[f"RV{extra_h}日倍率"] = rvx[ix][gx].mean() / rvx[ix][~gx].mean()
        rows.append(row)
    return pd.DataFrame(rows).set_index("訊號")


def fmt_table(df):
    d = df.copy()
    d["亮燈佔"] = d["亮燈佔"].map(lambda x: f"{x:.0f}%")
    d["RV倍率"] = d["RV倍率"].map(lambda x: f"{x:.2f}")
    d["t"] = d["t"].map(lambda x: f"{x:.1f}")
    d["下跌提升"] = d["下跌提升"].map(lambda x: f"{x:.1f}×")
    d["誤報"] = d["誤報"].map(lambda x: f"{x:.0f}%")
    d["綠燈下倍率"] = d["綠燈下倍率"].map(lambda x: "—" if pd.isna(x) else f"{x:.2f}")
    for c in d.columns:
        if c.startswith("RV") and c.endswith("日倍率"):
            d[c] = d[c].map(lambda x: f"{x:.2f}")
    return d
