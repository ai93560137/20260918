#!/usr/bin/env python3
"""第 1、2、5 項換變數重測（穩健性）。每一項用三到六種不同的變數定義重跑，看結論會不會變。

  python3 research/warrants_cbbc/robustness_125.py --k15 <15 分鐘 K 目錄> [--item 1,2,5]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import retail_flow as rf  # noqa: E402
import cbbc_heavy_zone as hz  # noqa: E402
import issuer_select as isel  # noqa: E402

HSI = ROOT / "canary" / "data_external" / "hsi_daily.csv"


def rho_ci(x: pd.Series, y: pd.Series, n=1000, seed=0):
    m = x.notna() & y.notna()
    if m.sum() < 15:
        return np.nan, np.nan, np.nan, int(m.sum())
    xs, ys = x[m].rank().to_numpy(), y[m].rank().to_numpy()
    r = np.corrcoef(xs, ys)[0, 1]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(xs), (n, len(xs)))
    v = [np.corrcoef(xs[i], ys[i])[0, 1] for i in idx]
    return r, np.percentile(v, 2.5), np.percentile(v, 97.5), int(m.sum())


def fmt(r, lo, hi, n):
    if np.isnan(r):
        return f"  n/a(n={n})"
    star = "★" if (lo > 0 or hi < 0) else " "
    return f"{r:+.3f}{star}"


# ----------------------------------------------------------------------------- 第 2 項
def item2() -> str:
    cb, dw = rf.load_cbbc(), rf.load_dwrc()
    h = pd.read_csv(HSI, parse_dates=["Date"]).set_index("Date")
    L = ["== 第 2 項：散戶淨流向，六種變數 =="]
    cb["hkd"] = cb["retail_net_units"] * cb["close"].fillna(0)
    dw["hkd"] = dw["retail_net_units"] * dw["close"].fillna(0)
    # 距收回價（用當日恒指收盤）
    cb = cb.join(h["Close"].rename("hsi"), on="date")
    cb["dist_pct"] = (cb["hsi"] - cb["call"]).abs() / cb["hsi"] * 100
    cb["contracts_os"] = cb["os"] / cb["ratio"] / 50.0

    def agg(df, val):
        return (df[val] * df["sign"]).groupby(df["date"]).sum()

    daily = pd.DataFrame({
        "A 期指張數等值（原）": agg(cb, "idx_units") / 50 + dw.groupby("date")["idx_units"].sum() / 50,
        "B 港元金額流（牛−熊＋購−沽）": agg(cb, "hkd") + (dw["hkd"] * dw["sign"]).groupby(dw["date"]).sum(),
        "C 牛證佔比 bull/(bull+bear) 淨買入": None,
        "D 持倉水平：牛 O/S − 熊 O/S（張）": agg(cb, "contracts_os"),
        "E 近收回價(<3%)投機流": (cb.loc[cb["dist_pct"] < 3, "idx_units"] * cb.loc[cb["dist_pct"] < 3, "sign"]).groupby(cb.loc[cb["dist_pct"] < 3, "date"]).sum() / 50,
        "F 廣度：淨買入隻數比例 牛−熊": None,
    })
    pos = cb["retail_net_units"].clip(lower=0)
    bull_buy = (pos * (cb["sign"] > 0) / cb["ratio"]).groupby(cb["date"]).sum()
    bear_buy = (pos * (cb["sign"] < 0) / cb["ratio"]).groupby(cb["date"]).sum()
    daily["C 牛證佔比 bull/(bull+bear) 淨買入"] = bull_buy / (bull_buy + bear_buy)
    nb = (cb["retail_net_units"] > 0)
    br = ((nb & (cb["sign"] > 0)).groupby(cb["date"]).mean() - (nb & (cb["sign"] < 0)).groupby(cb["date"]).mean())
    daily["F 廣度：淨買入隻數比例 牛−熊"] = br
    daily = daily.sort_index()
    # D 用 5 日變化
    daily["D 持倉水平：牛 O/S − 熊 O/S（張）"] = daily["D 持倉水平：牛 O/S − 熊 O/S（張）"].diff(5)
    daily = daily.rename(columns={"D 持倉水平：牛 O/S − 熊 O/S（張）": "D 持倉 5 日變化（牛 O/S − 熊 O/S）"})
    # 回報
    hh = h[h.index >= daily.index.min() - pd.Timedelta(days=5)]
    df = daily.join(hh[["Open", "Close"]], how="left").dropna(subset=["Close"])
    lc = np.log(df["Close"])
    ret = pd.DataFrame({
        "同日": lc.diff(),
        "隔夜(次日開−今收)": np.log(df["Open"].shift(-1)) - lc,
        "次日日內(開→收)": (np.log(df["Close"]) - np.log(df["Open"])).shift(-1),
        "未來1日": lc.shift(-1) - lc,
        "未來5日": lc.shift(-5) - lc,
        "未來10日": lc.shift(-10) - lc,
    })
    # 5 日累計流向版本
    L.append(f"樣本 {len(df)} 日。Spearman，★＝bootstrap 95% 區間不含 0")
    L.append(f"{'變數':<36}" + "".join(f"{c:>18}" for c in ret.columns))
    for col in daily.columns:
        x = df[col]
        L.append(f"{col:<36}" + "".join(f"{fmt(*rho_ci(x, ret[c])):>18}" for c in ret.columns))
        if col.startswith("A"):
            x5 = x.rolling(5).sum()
            L.append(f"{'A 的 5 日累計':<36}" + "".join(f"{fmt(*rho_ci(x5, ret[c])):>18}" for c in ret.columns))
            xz = (x - x.rolling(60, min_periods=30).mean()) / x.rolling(60, min_periods=30).std()
            L.append(f"{'A 的 60 日 z 分數':<36}" + "".join(f"{fmt(*rho_ci(xz, ret[c])):>18}" for c in ret.columns))
    # 極端十分位對照
    x = df[daily.columns[0]]
    q = pd.qcut(x, 10, labels=False, duplicates="drop")
    top, bot = ret.loc[q == q.max()], ret.loc[q == q.min()]
    L.append(f"A 最高十分位（狂買牛）n={len(top)}：未來1日 {top['未來1日'].mean()*1e4:+.0f}bp、未來5日 {top['未來5日'].mean()*1e4:+.0f}bp；"
             f"最低十分位（狂買熊）n={len(bot)}：{bot['未來1日'].mean()*1e4:+.0f}bp、{bot['未來5日'].mean()*1e4:+.0f}bp")
    return "\n".join(L)


# ----------------------------------------------------------------------------- 第 1 項
def item1(k15: Path) -> str:
    L = ["== 第 1 項：重貨區強制對沖，換變數 =="]
    cb = rf.load_cbbc()
    hmap = hz.hedge_map(cb)
    k = hz.load_k15(k15, "2025-11-01", "2026-09-30")
    basis = hz.basis_table(k)
    ev = hz.build_events(k, hmap, basis, horizons=(1, 2, 4, 8))
    ev0 = hz.build_events(k, hmap, basis * 0.0, horizons=(1, 2, 4, 8))   # 不調基差
    intr = ev[~ev["gap_open"]].copy()
    intr["S_per_vol"] = intr["S"] / intr["bar_vol"].clip(lower=1)

    def grp(df, mask_hi, mask_lo, title, cols=("r1", "r2", "r4", "r8", "r_gap", "r_next_oc")):
        a, b = df[mask_hi], df[mask_lo]
        line = f"  {title:<40} 高 n={len(a):4d} / 低 n={len(b):4d} |"
        for c in cols:
            line += f" {c}:{a[c].mean()*1e4:+5.1f}/{b[c].mean()*1e4:+5.1f}"
        L.append(line)

    for side in ("bull", "bear"):
        d = intr[intr["side"] == side]
        hit = d[d["S"] > 0]
        L.append(f"[{side}] 日內事件 {len(d)}，觸發 {len(hit)}；數字＝高組/低組 平均回報 bp（方向對齊，正＝續走）")
        grp(d, d["S"] > 0, d["S"] == 0, "① 觸發 vs 未觸發（原）")
        q = hit["S_per_vol"].quantile([.25, .75])
        grp(hit, hit["S_per_vol"] >= q[.75], hit["S_per_vol"] <= q[.25], "② S ÷ 該根期指成交量 前25% vs 後25%")
        q = hit["cum_S"].quantile([.25, .75])
        grp(hit, hit["cum_S"] >= q[.75], hit["cum_S"] <= q[.25], "③ 當日累計 S（連鎖）前25% vs 後25%")
        q = hit["S_rel"].quantile([.25, .75])
        grp(hit, hit["S_rel"] >= q[.75], hit["S_rel"] <= q[.25], "④ S ÷ 當日該方向總對沖量 前25% vs 後25%")
        # 波動（不看方向）：觸發後下一根振幅
        a, b = d[d["S"] > 0], d[d["S"] == 0]
        L.append(f"  ⑤ 下一根振幅（高−低，點）：觸發 {a['range1'].mean():.0f} vs 未觸發 {b['range1'].mean():.0f}；|r1| {a['abs_r1'].mean()*1e4:.1f} vs {b['abs_r1'].mean()*1e4:.1f} bp")
        hit_big = hit[hit["S"] >= hit["S"].quantile(.9)]
        L.append(f"  ⑥ S 前 10% 的 |r1| {hit_big['abs_r1'].mean()*1e4:.1f} bp、振幅 {hit_big['range1'].mean():.0f} 點（n={len(hit_big)}）")
        # 不調基差
        d0 = ev0[(~ev0["gap_open"]) & (ev0["side"] == side)]
        grp(d0, d0["S"] > 0, d0["S"] == 0, "⑦ 不調基差（期貨價直接比收回價）")
        # 排除開市首 30 分鐘
        late = d[d["bar"] >= 2]
        grp(late, late["S"] > 0, late["S"] == 0, "⑧ 排除 09:30–10:00")
        for c in ("r1", "r2", "r4", "r8"):
            r, lo, hi, n = rho_ci(hit["S_per_vol"], hit[c])
            L.append(f"  Spearman(S/成交量, {c}) = {fmt(r, lo, hi, n)}  n={n}")
    # 100 點整數關口穿越（不要求創新低）：關口上掛的對沖量 重 vs 輕
    L.append("[⑨ 100 點關口穿越事件（不要求創當日新低／新高）]")
    hdates = sorted(hmap)
    h = pd.read_csv(HSI, parse_dates=["Date"]).set_index("Date")["Close"]
    rows = []
    for d, g in k.groupby("date"):
        prev = [x for x in hdates if x < d]
        if not prev or d not in basis.index or pd.isna(basis.loc[d]):
            continue
        bull, bear = hmap[prev[-1]]
        bs = float(basis.loc[d])
        g = g.reset_index(drop=True)
        c = (g["close"] - bs).to_numpy()
        lc = np.log(g["close"].to_numpy())
        for j in range(1, len(g) - 4):
            lo, hi = sorted((c[j - 1], c[j]))
            levels = np.arange(np.ceil(lo / 100) * 100, hi + 1e-9, 100)
            if len(levels) == 0:
                continue
            down = c[j] < c[j - 1]
            for Lv in levels:
                if down:
                    w = float(bull[(bull.index >= Lv) & (bull.index < Lv + 100)].sum())
                    rows.append({"side": "down", "w": w, "r1": -(lc[j + 1] - lc[j]), "r4": -(lc[j + 4] - lc[j])})
                else:
                    w = float(bear[(bear.index > Lv - 100) & (bear.index <= Lv)].sum())
                    rows.append({"side": "up", "w": w, "r1": lc[j + 1] - lc[j], "r4": lc[j + 4] - lc[j]})
    cr = pd.DataFrame(rows)
    for side in ("down", "up"):
        s = cr[cr["side"] == side]
        q = s["w"].quantile([.25, .75])
        hi_, lo_ = s[s["w"] >= q[.75]], s[s["w"] <= q[.25]]
        r, lo, hi, n = rho_ci(s["w"], s["r4"])
        L.append(f"  {side}: n={len(s)} 關口重（前25%, 中位 {hi_['w'].median():.0f} 張）r1 {hi_['r1'].mean()*1e4:+.1f} r4 {hi_['r4'].mean()*1e4:+.1f} bp；"
                 f"輕（後25%）r1 {lo_['r1'].mean()*1e4:+.1f} r4 {lo_['r4'].mean()*1e4:+.1f}；Spearman(w, r4) {fmt(r, lo, hi, n)}")
    return "\n".join(L)


# ----------------------------------------------------------------------------- 第 5 項
def item5() -> str:
    L = ["== 第 5 項：跨發行商與 O/S，換變數 =="]
    df = isel.load(isel.CSV)
    w = df[df["type"].isin(["CALL", "PUT"]) & df["premium_pct"].notna() & (df["fwd"] > 0) & (df["turnover"] > 0)].copy()
    w = w[w["premium_pct"].between(-50, 200)]
    w["mny"] = np.where(w["type"] == "CALL", w["strike"] / w["fwd"] - 1, 1 - w["strike"] / w["fwd"])
    w["mny_b"] = pd.cut(w["mny"], [-1, -0.04, 0, 0.04, 0.08, 0.12, 1])
    w["days_b"] = pd.cut(w["days"], [0, 30, 60, 120, 400])
    specs = {
        "A 原：貨性×年期格子，溢價% 偏差中位": ("premium_pct", ["type", "mny_b", "days_b", "date"], "median"),
        "B 同格子，用發行商 IV 偏差": ("iv_issuer", ["type", "mny_b", "days_b", "date"], "median"),
        "C 同格子，平均數": ("premium_pct", ["type", "mny_b", "days_b", "date"], "mean"),
        "D 粗格子：只控制年期與方向": ("premium_pct", ["type", "days_b", "date"], "median"),
        "E 細格子：貨性 2% 一檔": ("premium_pct", ["type", "mny_fine", "days_b", "date"], "median"),
        "F 只看成交 ≥10 萬港元": ("premium_pct", ["type", "mny_b", "days_b", "date"], "median"),
    }
    w["mny_fine"] = pd.cut(w["mny"], np.arange(-0.2, 0.42, 0.02))
    out = {}
    for name, (val, keys, how) in specs.items():
        d = w[w["turnover"] >= 1e5] if name.startswith("F") else w
        d = d[d[val].notna()]
        cell = d.groupby(keys, observed=True)[val]
        ref = cell.transform(how)
        cnt = cell.transform("size")
        dev = (d[val] - ref)[cnt >= 3]
        d = d[cnt >= 3].assign(dev=dev)
        tab = d.groupby("issuer")["dev"].agg(["median", "size"])
        tab = tab[tab["size"] >= 150]
        out[name] = tab["median"]
        if len(tab) < 2:
            L.append(f"{name:<34} 樣本不足（n={len(d)}）")
            continue
        m = d.groupby(["month", "issuer"])["dev"].median().unstack()
        m = m.loc[:, m.notna().sum() >= len(m) * 0.7].rank(axis=1)
        rho = np.nanmean([m.iloc[i].corr(m.iloc[i + 1]) for i in range(len(m) - 1)])
        order = tab["median"].sort_values()
        L.append(f"{name:<34} 最便宜 {order.index[0]}({order.iloc[0]:+.1f}) {order.index[1]}({order.iloc[1]:+.1f})  最貴 {order.index[-1]}({order.iloc[-1]:+.1f}) {order.index[-2]}({order.iloc[-2]:+.1f})  "
                 f"月排名持續 {rho:+.2f}  n={len(d)}")
    tab = pd.DataFrame(out).round(1)
    L.append("發行商 × 變數（相對格子基準的偏差；B 欄單位是 IV 點，其餘是溢價百分點）：")
    L.append(tab.sort_values(tab.columns[0]).to_string())
    rk = tab.rank()
    L.append(f"各變數下發行商排名與 A 的 Spearman：" + "，".join(f"{c[:1]} {rk[c].corr(rk[tab.columns[0]]):+.2f}" for c in tab.columns[1:]))

    # O/S 效應換變數
    L.append("\nO/S 效應（窩輪）：")
    d = w.copy()
    cell = d.groupby(["type", "mny_b", "days_b", "date"], observed=True)["premium_pct"]
    d["dev"] = d["premium_pct"] - cell.transform("median")
    d = d[cell.transform("size") >= 3]
    d = d.sort_values(["code", "date"])
    g = d.groupby("code")
    d["d_os"] = g["os_pct"].diff()
    d["d_dev"] = g["dev"].diff()
    r = rho_ci(d["d_os"], d["d_dev"])
    L.append(f"  ① 日變化：ΔO/S vs Δ偏差（同一隻、相鄰成交日）Spearman {fmt(*r)} n={r[3]}")
    # 分發行商：O/S 效應在每家是否都成立
    L.append("  ② 分發行商，同一隻內 Spearman(O/S, 偏差)：")
    for iss, gg in d.groupby("issuer"):
        if len(gg) < 300:
            continue
        gi = gg.groupby("code")
        x = gg["os_pct"] - gi["os_pct"].transform("mean")
        y = gg["dev"] - gi["dev"].transform("mean")
        r = rho_ci(x, y)
        L.append(f"     {iss}: {fmt(*r)} n={r[3]}")
    # 用發行商 IV 當因變數
    d["dev_iv"] = d["iv_issuer"] - d.groupby(["type", "mny_b", "days_b", "date"], observed=True)["iv_issuer"].transform("median")
    gi = d.groupby("code")
    x = d["os_pct"] - gi["os_pct"].transform("mean")
    y = d["dev_iv"] - gi["dev_iv"].transform("mean")
    r = rho_ci(x, y)
    beta = np.polyfit(x[x.notna() & y.notna()], y[x.notna() & y.notna()], 1)[0]
    L.append(f"  ③ 因變數換成發行商 IV（同一隻內）：Spearman {fmt(*r)}，斜率 {beta*10:+.2f} IV 點 / 每 +10% O/S")
    # 控制年齡後
    d["age"] = (d["date"] - gi["date"].transform("min")).dt.days
    xa = d["age"] - gi["age"].transform("mean")
    X = np.column_stack([x, xa, np.ones(len(x))])
    m = np.isfinite(X).all(1) & y.notna()
    yy = (d["dev"] - gi["dev"].transform("mean"))
    m &= yy.notna()
    b = np.linalg.lstsq(X[m], yy[m], rcond=None)[0]
    L.append(f"  ④ 同時控制掛牌天數：O/S 斜率 {b[0]*10:+.2f} 點/+10%，天數斜率 {b[1]*30:+.2f} 點/+30 日")

    # 牛熊證：換 discount_pct、換成交門檻、換距離格子
    L.append("\n牛熊證發行商效應換變數：")
    c = df[df["type"].isin(["BULL", "BEAR"]) & df["discount_pts"].notna() & (df["turnover"] > 0) & (df["days"] > 0)].copy()
    c = c[c["discount_pts"].between(-600, 600)]
    c["discount_pct"] = c["discount_pts"] / c["strike"] * 100      # 折讓佔行使價 %
    c["days_b"] = pd.cut(c["days"], [0, 60, 180, 365, 730, 2000])
    c["dist_b"] = pd.cut(c["dist_call_pct"], [0, 2, 4, 8, 15, 100])
    c["dist_fine"] = pd.cut(c["dist_call_pct"], [0, 1, 2, 3, 4, 6, 8, 12, 15, 25, 100])
    cspecs = {
        "A 原：折讓點、年期×距離": ("discount_pts", ["type", "days_b", "dist_b", "date"], c),
        "B 折讓佔行使價 %": ("discount_pct", ["type", "days_b", "dist_b", "date"], c),
        "C 距離細分 10 檔": ("discount_pts", ["type", "days_b", "dist_fine", "date"], c),
        "D 成交 ≥10 萬港元": ("discount_pts", ["type", "days_b", "dist_b", "date"], c[c["turnover"] >= 1e5]),
        "E 只看一年以上": ("discount_pts", ["type", "dist_b", "date"], c[c["days"] > 365]),
        "F 只看三個月內": ("discount_pts", ["type", "dist_b", "date"], c[c["days"] <= 90]),
    }
    cout = {}
    for name, (val, keys, d) in cspecs.items():
        cell = d.groupby(keys, observed=True)[val]
        dev = d[val] - cell.transform("median")
        d = d[cell.transform("size") >= 3].assign(dev=dev)
        tab = d.groupby("issuer")["dev"].agg(["median", "size"])
        tab = tab[tab["size"] >= 100]
        cout[name] = tab["median"]
        order = tab["median"].sort_values(ascending=False)
        if len(order) < 2:
            L.append(f"{name:<28} 樣本不足（n={len(d)}）")
            continue
        L.append(f"{name:<28} 最便宜 {order.index[0]}({order.iloc[0]:+.1f}) {order.index[1]}({order.iloc[1]:+.1f})  最貴 {order.index[-1]}({order.iloc[-1]:+.1f}) {order.index[-2]}({order.iloc[-2]:+.1f})  n={len(d)}")
    ctab = pd.DataFrame(cout).round(1)
    L.append(ctab.sort_values(ctab.columns[0], ascending=False).to_string())
    rk = ctab.rank()
    L.append(f"各變數下排名與 A 的 Spearman：" + "，".join(f"{c[:1]} {rk[c].corr(rk[ctab.columns[0]]):+.2f}" for c in ctab.columns[1:]))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k15")
    ap.add_argument("--item", default="2,1,5")
    a = ap.parse_args()
    for it in a.item.split(","):
        if it == "2":
            print(item2())
        elif it == "1":
            print(item1(Path(a.k15)))
        elif it == "5":
            print(item5())
        print()


if __name__ == "__main__":
    main()
