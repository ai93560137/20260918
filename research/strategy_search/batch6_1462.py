"""[IDEAS #1462–#1463] 回看第六批。規格同門檻以 IDEAS 預先登記為準（11-12 UTC，跑之前 commit）。
用法：python3 research/strategy_search/batch6_1462.py → research/strategy_search/BATCH6_1462.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import data_cache as DC      # noqa: E402
import direction_1445 as DR  # noqa: E402
import index_1427 as IX      # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "BATCH6_1462.md")
T = PM.tstat


def ohlc(tk):
    d = DC.get("yahood/x_" + "".join(ch if ch.isalnum() else "_" for ch in tk) + "_d.npz")
    f = pd.DataFrame({"o": np.asarray(d["o"], float), "c": np.asarray(d["c"], float)}, index=pd.to_datetime(np.asarray(d["t"], "int64"), unit="s").normalize())
    return f[~f.index.duplicated()]


def onid(tk, y0):
    f = ohlc(tk); f = f[f.index.year >= y0]; on = f.o / f.c.shift(1) - 1; idd = f.c / f.o - 1; ok = (f.o != f.c) & (f.o > 0) & on.notna() & (on.abs() < 0.3) & (idd.abs() < 0.3)
    return pd.DataFrame({"on": on[ok], "id": idd[ok]})


def sh(x):
    return float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else 0.0


def rebal(stk, bnd):
    """每月倒數第 6 個交易日收市：當月至今 股 − 債；之後最後 5 日股票回報。"""
    z = pd.DataFrame({"s": stk, "b": bnd}).dropna(); out = []
    for per, g in z.groupby(z.index.to_period("M")):
        prev = z[z.index < g.index[0]]
        if len(g) < 12 or not len(prev):
            continue
        p0 = prev.iloc[-1]; a = g.iloc[-6]; e = g.iloc[-1]; out.append((per, a.s / p0.s - 1 - (a.b / p0.b - 1), e.s / a.s - 1))
    return pd.DataFrame(out, columns=["m", "rel", "r"]).set_index("m")


def main():
    L = ["# #1462–#1463：回看第六批", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；只讀研究", ""]; res = {}
    # ---- 1462
    S = {"SPY": onid("SPY", 1993), "QQQ": onid("QQQ", 1999), "恒指": onid("^HSI", 1990)}
    L += ["## #1462 股指隔夜回報（收市買、開市賣）", "", "| 工具 | 由 | 日數 | 隔夜日均 | 日內日均 | 差 | 2010 起：隔夜淨（扣 0.02%） | 2010 起 Sharpe：只揸隔夜（淨）／長揸 | 2010 起年化：只揸隔夜（淨）／長揸 |", "|---|---|---|---|---|---|---|---|---|"]
    g1, g4, g5 = [], [], []
    for n, d in S.items():
        y = d[d.index.year >= 2010]; net = y.on - 0.0002; bh = (1 + y.on) * (1 + y["id"]) - 1; yrs = len(y) / 252; cg = lambda v: float(np.prod(1 + v) ** (1 / yrs) - 1)  # noqa: E731
        g1.append(d.on.mean() - d["id"].mean() > 0); g4.append(net.mean() > 0); g5.append(sh(net) >= sh(bh))
        L.append(f"| {n} | {d.index[0].year} | {len(d):,} | {1e4 * d.on.mean():+.2f}bp | {1e4 * d['id'].mean():+.2f}bp | {1e4 * (d.on.mean() - d['id'].mean()):+.2f}bp | {1e4 * net.mean():+.2f}bp | {sh(net):.2f}／{sh(bh):.2f} | {100 * cg(net):+.1f}%／{100 * cg(bh):+.1f}% |")
    P = pd.DataFrame({n: d.on - d["id"] for n, d in S.items()}).mean(axis=1).dropna(); h = len(P) // 2; py = P[P.index.year >= 2010]
    g = [all(g1) and T(P) >= 2.0, P.iloc[:h].mean() > 0 and P.iloc[h:].mean() > 0, py.mean() > 0, all(g4), sum(g5) >= 2]; res["1462"] = all(g)
    L += ["", f"- 合併配對差（每日跨工具平均）：{1e4 * P.mean():+.2f}bp，t {T(P):+.2f}；前半 {1e4 * P.iloc[:h].mean():+.2f}bp、後半（{P.index[h]:%Y} 起）{1e4 * P.iloc[h:].mean():+.2f}bp；2010 起 {1e4 * py.mean():+.2f}bp（t {T(py):+.2f}）",
          "- 按年代隔夜／日內日均（bp，描述）：" + "；".join(f"{n}：" + "、".join(f"{int(k)}s {1e4 * v.on:+.1f}／{1e4 * v['id']:+.1f}" for k, v in d.groupby((d.index.year // 10) * 10).mean().iterrows()) for n, d in S.items()),
          f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1462'] else '❌ 唔合格'}**", ""]
    # ---- 1463
    def ser(key):
        d = IX.load(key); return pd.Series(np.asarray(d["c"], float), index=pd.to_datetime(np.asarray(d["t"], "int64"), unit="s").normalize())
    A = rebal(ohlc("SPY").c, ohlc("TLT").c); zn = ohlc("ZN=F").c; B = rebal(ser("ES_F"), zn[zn > 0])
    L += ["## #1463 月尾股債再平衡（倒數第 6 日睇當月股 − 債；之後最後 5 日股票回報）", "", "| 數據 | 由 | 跑輸月／跑贏月 | 跑輸月之後 | 跑贏月之後 | 差 | t | 前半差 | 後半差 | 2010 起差 | 策略每月淨（t） |", "|---|---|---|---|---|---|---|---|---|---|---|"]; O = {}
    for n, z in (("SPY／TLT（判決）", A), ("ES 期貨／ZN 期貨", B)):
        lo, hi = z.r[z.rel < 0], z.r[z.rel >= 0]; d0 = lo.mean() - hi.mean(); t0 = DR.welch(lo.to_numpy(), hi.to_numpy()); h = len(z) // 2
        f = lambda q: q.r[q.rel < 0].mean() - q.r[q.rel >= 0].mean(); zy = z[z.index.year >= 2010]; st = np.where(z.rel < 0, 1.0, -1.0) * z.r - 0.0004  # noqa: E731
        O[n] = (d0, t0, f(z.iloc[:h]), f(z.iloc[h:]), f(zy), float(st.mean()))
        L.append(f"| {n} | {z.index[0].year} | {len(lo)}／{len(hi)} | {100 * lo.mean():+.2f}% | {100 * hi.mean():+.2f}% | {100 * d0:+.2f}% | {t0:+.2f} | {100 * O[n][2]:+.2f}% | {100 * O[n][3]:+.2f}% | {100 * O[n][4]:+.2f}% | {100 * st.mean():+.3f}%（{T(st):+.2f}） |")
    a, b = O["SPY／TLT（判決）"], O["ES 期貨／ZN 期貨"]; g = [a[0] > 0 and a[1] >= 2.0, a[2] > 0 and a[3] > 0, a[4] > 0, b[0] > 0, a[5] > 0]; res["1463"] = all(g)
    L += ["", f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1463'] else '❌ 唔合格'}**", "",
          f"## 總結：合格 {sum(res.values())}／2（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
