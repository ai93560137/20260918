#!/usr/bin/env python3
"""NQ（NAS100 CFD）研究 — 照 NQ_HANDOFF.md §5 的順序執行。

測試 1：錦囊規則原封不動搬到 NAS100 M15（一個參數都不調）。
測試 2：週期階梯 M5 / M15 / M30 / H1 / H4。
附帶：M1 微結構 VR 檢定、真實成交價重建（§18.2 的方法）、
      切半驗證、隨機控制組、異常值檢查、點差生死線。

用法：
    python3 nq_study.py                # 全部
    python3 nq_study.py --part ladder  # 只跑週期階梯
"""
import argparse
import numpy as np
import pandas as pd

from bazhentu_sim import PRESETS, states, atr

DATA = "data/NAS100_{tf}.csv.gz"
TF_MIN = {"M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}


def load_tf(tf):
    df = pd.read_csv(DATA.format(tf=tf), parse_dates=["Time"],
                     date_format="%Y.%m.%d %H:%M:%S")
    return df.set_index("Time").sort_index()


# ── 訊號產生：與 bazhentu_sim.trades() 完全相同的狀態機，只是把進出場交給呼叫者 ──
def signals(df, p, maxBars=10):
    s = states(df, p)
    st, hi, lo, a = s.st.values, s.hi.values, s.lo.values, s.atr.values
    C = df.Close.values
    n = len(df)
    boxTop = boxBot = np.nan
    live, lastR, run, pdir, pc = False, -1, 0, 0, 0
    out = []
    for i in range(1, n):
        run = run + 1 if st[i] == 0 else 0
        if st[i] == 0 and run >= p["rangeMinBars"]:
            boxTop, boxBot, live, lastR = hi[i - 1], lo[i - 1], True, i
        elif live and i - lastR > p["boxMaxAge"]:
            live = False
        if not live or np.isnan(a[i]):
            pdir, pc = 0, 0
            continue
        raw = 1 if C[i] > boxTop + p["bufATR"] * a[i] else (
            -1 if C[i] < boxBot - p["bufATR"] * a[i] else 0)
        if raw != 0 and raw == pdir:
            pc += 1
        elif raw != 0:
            pdir, pc = raw, 1
        else:
            pdir, pc = 0, 0
        if pdir != 0 and pc == p["confirmBars"]:
            j = min(i + maxBars, n - 1)
            out.append(dict(i=i, j=j, dir=pdir, t=df.index[i]))
            live, pdir, pc = False, 0, 0
    return out


def close_exec(df, sigs):
    """情境①：訊號根收盤進場、第 10 根收盤出場（bazhentu_sim.trades 的算法）"""
    C = df.Close.values
    rows = [dict(t=s["t"], dir=s["dir"], px=C[s["i"]],
                 ret=(C[s["j"]] / C[s["i"]] - 1) * s["dir"] * 100) for s in sigs]
    return pd.DataFrame(rows)


def real_exec(df, sigs, m1, tf_min):
    """情境③：訊號根收盤確認後，下一根 M1 開盤進場；持有到期後下一根 M1 開盤出場。
    MT 慣例 Time = 開盤時間，所以標 T 的 K 線在 T+tf 收盤。"""
    m1t = m1.index.values
    m1o = m1.Open.values
    dt = np.timedelta64(tf_min, "m")
    rows = []
    for s in sigs:
        te = np.datetime64(df.index[s["i"]]) + dt
        tx = np.datetime64(df.index[s["j"]]) + dt
        ke, kx = np.searchsorted(m1t, te), np.searchsorted(m1t, tx)
        if ke >= len(m1t) or kx >= len(m1t):
            continue
        pe, pxx = m1o[ke], m1o[kx]
        rows.append(dict(t=df.index[s["i"]], dir=s["dir"], px=pe,
                         ret=(pxx / pe - 1) * s["dir"] * 100,
                         lag_e=(m1t[ke] - te) / np.timedelta64(1, "m")))
    return pd.DataFrame(rows)


def stats(tr, spread_pts=0.0):
    """net = 毛利 − 點差/進場價（逐筆用當時價換算，同 §18.4）"""
    if len(tr) == 0:
        return None
    net = tr.ret - spread_pts / tr.px * 100
    t = net.mean() / (net.std() / np.sqrt(len(net))) if net.std() > 0 else np.nan
    return dict(n=len(tr), gross=tr.ret.mean(), net=net.mean(), t=t,
                win=(net > 0).mean() * 100, total=net.sum())


def line(label, tr, spread):
    r = stats(tr, spread)
    if r is None:
        print(f"  {label:<26} 無訊號")
        return
    yrs = (tr.t.iloc[-1] - tr.t.iloc[0]).days / 365.25 if len(tr) > 1 else 1
    print(f"  {label:<26} {r['n']:>5} 筆  毛 {r['gross']:+.4f}%  淨 {r['net']:+.4f}%"
          f"  勝率 {r['win']:.1f}%  t={r['t']:+.2f}  合計 {r['total']:+.2f}%"
          f"  年化 {r['total']/yrs:+.2f}%")


def block_bootstrap_ci(tr, spread, n_boot=20000, seed=0):
    """以月為區塊、重抽（同 §17.6）"""
    net = (tr.ret - spread / tr.px * 100).values
    mkey = pd.to_datetime(tr.t).dt.to_period("M").values
    groups = [net[mkey == m] for m in pd.unique(mkey)]
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        sample = np.concatenate([groups[k] for k in pick])
        means[b] = sample.mean()
    return np.percentile(means, 2.5), np.percentile(means, 97.5), (means > 0).mean()


def part_m15(spreads):
    print("=" * 78)
    print("測試 1：錦囊規則原封不動 → NAS100 M15（八陣圖 M15 原廠門檻，持有 10 根，無停損）")
    print("=" * 78)
    df = load_tf("M15")
    m1 = load_tf("M1")
    p = PRESETS["M15"]
    sigs = signals(df, p, maxBars=10)
    print(f"資料 {df.index[0]} → {df.index[-1]}，{len(df)} 根 M15，訊號 {len(sigs)} 筆")

    tr_c = close_exec(df, sigs)
    tr_r = real_exec(df, sigs, m1, TF_MIN["M15"])
    print(f"\n【執行價重建】（§18.2 方法）")
    line("① M15 收盤成交・零成本", tr_c, 0.0)
    line("③ 下一根 M1 開盤成交", tr_r, 0.0)
    print(f"  進場延遲：中位 {tr_r.lag_e.median():.1f} 分鐘，>15 分鐘的有 {(tr_r.lag_e>15).sum()} 筆")
    slip = tr_r.ret.mean() - tr_c.ret.iloc[:len(tr_r)].mean()
    print(f"  滑價（③−①）每筆 {slip:+.4f}%")

    print(f"\n【點差階梯】（真實成交價，逐筆按當時指數換算成本）")
    for sp in spreads:
        line(f"③ − 點差 {sp:.1f} 點", tr_r, sp)

    a = atr(df, 14)
    px = df.Close
    print(f"\n【成本 ÷ ATR】（生死線指標：黃金 11.1% 活、HK50 22.9% 死）")
    for sp in spreads:
        print(f"  點差 {sp:.1f} 點  = {(sp/px).median()*100:.4f}% 名義"
              f"   佔 ATR 中位 {(sp/a).median()*100:.1f}%")

    print(f"\n【切半驗證】（資料切半，兩半都要正才算結構性）")
    mid = df.index[len(df) // 2]
    for sp in spreads:
        h1, h2 = tr_r[tr_r.t < mid], tr_r[tr_r.t >= mid]
        r1, r2 = stats(h1, sp), stats(h2, sp)
        print(f"  點差 {sp:.1f}：前半 {r1['n']} 筆 淨 {r1['net']:+.4f}% t={r1['t']:+.2f}"
              f"   後半 {r2['n']} 筆 淨 {r2['net']:+.4f}% t={r2['t']:+.2f}")

    print(f"\n【隨機進場控制組】（同持有 10 根、隨機方向、200 倍樣本）")
    rng = np.random.default_rng(0)
    C = df.Close.values
    ok = np.arange(60, len(df) - 11)
    idx = rng.choice(ok, size=min(len(sigs) * 200, len(ok)), replace=True)
    d = rng.choice([1, -1], size=len(idx))
    rnd = (C[idx + 10] / C[idx] - 1) * d * 100
    print(f"  n={len(rnd)}  平均 {rnd.mean():+.4f}%  勝率 {(rnd>0).mean()*100:.1f}%"
          f"  標準差 {rnd.std():.3f}%")

    print(f"\n【異常值檢查】（§6 規矩 6：拿掉最賺的 5% 還剩什麼，毛利）")
    k = max(1, int(len(tr_r) * 0.05))
    trimmed = tr_r.nlargest(k, "ret")
    rest = tr_r.drop(trimmed.index)
    print(f"  全部 {len(tr_r)} 筆 合計 {tr_r.ret.sum():+.2f}%"
          f"   最賺 {k} 筆貢獻 {trimmed.ret.sum():+.2f}%"
          f"   其餘 {len(rest)} 筆合計 {rest.ret.sum():+.2f}%  平均 {rest.ret.mean():+.4f}%")

    print(f"\n【逐年】（毛利）")
    yr = tr_r.assign(y=pd.to_datetime(tr_r.t).dt.year).groupby("y").ret.agg(["count", "sum", "mean"])
    for y, v in yr.iterrows():
        print(f"  {y}  {int(v['count']):>4} 筆  合計 {v['sum']:+7.2f}%  每筆 {v['mean']:+.4f}%")

    mo = tr_r.assign(m=pd.to_datetime(tr_r.t).dt.to_period("M")).groupby("m").ret.sum()
    eq = (1 + (tr_r.ret) / 100).cumprod()
    mdd = (eq / eq.cummax() - 1).min() * 100
    print(f"\n  {(mo>0).sum()} 個月正 / {(mo<=0).sum()} 個月負；序列最大回撤（毛，名義）{mdd:.2f}%")
    print(f"  單筆最壞 {tr_r.ret.min():+.3f}%  最好 {tr_r.ret.max():+.3f}%")

    for sp in [s for s in spreads if s > 0][:3]:
        lo95, hi95, pgt0 = block_bootstrap_ci(tr_r, sp)
        print(f"\n【月區塊 bootstrap ×20000・點差 {sp:.1f} 點】"
              f" 每筆淨利 95% 區間 [{lo95:+.4f}%, {hi95:+.4f}%]  P(優勢>0)={pgt0*100:.1f}%")
    return tr_r


def part_ladder(spreads):
    print("\n" + "=" * 78)
    print("測試 2：週期階梯（各週期用八陣圖該週期原廠門檻；H4 用 H4 預設；收盤成交）")
    print("=" * 78)
    for tf in ["M5", "M15", "M30", "H1", "H4"]:
        df = load_tf(tf)
        p = PRESETS.get(tf, PRESETS["D"])
        sigs = signals(df, p, maxBars=10)
        tr = close_exec(df, sigs)
        if len(tr) < 10:
            print(f"  {tf:<4} {len(df):>7} 根  訊號 {len(tr)} 筆 — 不足以下結論")
            continue
        for sp in spreads:
            line(f"{tf} − 點差 {sp:.1f} 點", tr, sp)
        print()


def part_micro():
    print("\n" + "=" * 78)
    print("M1 微結構：VR 檢定（同 §18.1 / §19.3）")
    print("=" * 78)
    m1 = load_tf("M1")
    r = np.log(m1.Close / m1.Close.shift(1)).dropna()

    def vr(x, q):
        x = x.values
        n = len(x)
        mu = x.mean()
        v1 = ((x - mu) ** 2).mean()
        xq = pd.Series(x).rolling(q).sum().dropna().values
        vq = ((xq - q * mu) ** 2).mean() / q
        z = (vq / v1 - 1) / np.sqrt(2 * (2 * q - 1) * (q - 1) / (3 * q * n))
        return vq / v1, z

    def row(label, x):
        v5, z5 = vr(x, 5)
        v15, z15 = vr(x, 15)
        ac1 = x.autocorr(1)
        print(f"  {label:<16} n={len(x):>9}  lag-1 {ac1:+.4f}  VR(5) {v5:.3f} z={z5:+.2f}"
              f"  VR(15) z={z15:+.2f}")

    row("全期", r)
    for y in sorted(r.index.year.unique()):
        row(str(y), r[r.index.year == y])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="all", choices=["all", "m15", "ladder", "micro"])
    ap.add_argument("--spreads", default="0,1,2,3,5")
    a = ap.parse_args()
    spreads = [float(x) for x in a.spreads.split(",")]
    if a.part in ("all", "m15"):
        part_m15(spreads)
    if a.part in ("all", "ladder"):
        part_ladder(spreads)
    if a.part in ("all", "micro"):
        part_micro()
