"""[IDEAS #1467–#1469] 基金層面第二批：三隻非黃金腳。規格同門檻以 IDEAS 預先登記為準（11-13 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1467.py → research/strategy_search/FUND_1467.md（要先跑過 fund_1464.py，用佢嘅預計算快取）"""
import datetime as dt
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch6_1462 as B6     # noqa: E402
import direction_1445 as DR  # noqa: E402
import fund_1464 as F        # noqa: E402
import index_1427 as IX      # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "FUND_1467.md")
TSM = ["EURUSD=X", "GBPUSD=X", "JPY=X", "CHF=X", "CAD=X", "AUDUSD=X", "NZDUSD=X", "EURJPY=X", "GBPJPY=X", "^NDX", "^GDAXI", "^FTSE", "CL=F", "BTC-USD"]


def base():
    gd, P, fl, ex, sd, Ps, fls = pickle.load(open(F.CACHE, "rb"))
    idx = pd.period_range("2010-07", pd.Timestamp(gd[-1][0] * 86400, unit="s").to_period("M"), freq="M")
    g, _ = F.sim_daily(gd, P, fl, list(F.GOLD), 1.0, 0.5, extra=ex)
    f0 = g + F.mobrk(gd) + F.sim_daily(sd, Ps, fls, [("943", "tdsurge")], 50.0, 0.06, long_only=True)[0]
    names = [b for b, _ in F.GOLD] + ["944"]
    target = float(np.mean([F.monthly([q for q in f0 if q[0] == b], idx).std() for b in names]))
    return F.monthly(f0, idx), idx, target


def judge(L, tag, title, raw, m0, target, solo_ok, solo_txt):
    """raw＝隻腳每月回報（任何單位）；調到每月標準差＝target 美元。"""
    s0, h0 = F.stats(m0), F.halves(m0); leg = raw * (target / raw.std()); m1 = m0 + leg; s1, h1, lh = F.stats(m1), F.halves(m1), F.halves(leg); cr = float(np.corrcoef(leg, m0)[0, 1])
    g = [s1["sh"] >= 1.10 * s0["sh"], s1["rd"] >= 1.10 * s0["rd"], h1[0]["sh"] > h0[0]["sh"] and h1[1]["sh"] > h0[1]["sh"], cr < 0.2, lh[0]["tot"] > 0 and lh[1]["tot"] > 0]; ok = solo_ok and all(g)
    L += [f"## {title}", "", f"- 單獨關：{solo_txt} → {'✓' if solo_ok else '✗'}", "", "| 版本 | 總損益 $ | 最大回落 | 總÷回落 | Sharpe | 前半 Sharpe | 後半 Sharpe |", "|---|---|---|---|---|---|---|",
          f"| F0 | {s0['tot']:+,.0f} | {s0['dd']:,.0f} | {s0['rd']:.2f} | {s0['sh']:.2f} | {h0[0]['sh']:.2f} | {h0[1]['sh']:.2f} |",
          f"| F0＋呢隻腳 | {s1['tot']:+,.0f} | {s1['dd']:,.0f} | {s1['rd']:.2f} | {s1['sh']:.2f} | {h1[0]['sh']:.2f} | {h1[1]['sh']:.2f} |",
          f"| 隻腳本身 | {leg.sum():+,.0f} | {F.stats(leg)['dd']:,.0f} | {F.stats(leg)['rd']:.2f} | {F.stats(leg)['sh']:.2f} | {lh[0]['sh']:.2f} | {lh[1]['sh']:.2f} |", "",
          f"- 同 F0 每月損益相關 {cr:+.2f}；前半／後半本身損益 {lh[0]['tot']:+,.0f}／{lh[1]['tot']:+,.0f}", f"- 基金關 {''.join('✓' if v else '✗' for v in g)}；單獨關 {'✓' if solo_ok else '✗'} → **{'✅ 合格' if ok else '❌ 唔合格'}**", ""]
    return ok, leg


def main():
    m0, idx, target = base(); res = {}; legs = {}
    L = ["# #1467–#1469：基金層面第二批（三隻非黃金腳）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{idx[0]}–{idx[-1]}；每隻腳注碼調到每月損益標準差＝{target:,.0f} 美元（6 本黃金簿平均）；樣本內；只讀研究", ""]
    # 1467
    tr, _ = IX.sim(IX.load("ES_F"), IX.CFG[0], 0.0002); s = pd.Series(0.0, index=idx); n = 0; rs = []
    for t, sg, r in tr:
        m = pd.Timestamp(int(t), unit="s").to_period("M")
        if m in s.index:
            s[m] += r; n += 1; rs.append(r)
    t_ = PM.tstat(s); solo = float(np.mean(rs)) > 0 and t_ >= 2.0
    res["1467"], legs["1467"] = judge(L, "1467", "#1467 標普 #1268 雙向腳（ES 期貨）", s, m0, target, solo, f"{n} 張、每張平均 {np.mean(rs):+.3f}R、每月損益 t {t_:+.2f}")
    # 1468
    P, V = {}, {}
    for tk in TSM:
        x = PM.series(tk)
        if x is None:
            continue
        r = x.pct_change(); P[tk] = x.resample("ME").last(); V[tk] = (r.rolling(60).std() * np.sqrt(252)).resample("ME").last()
    P, V = pd.DataFrame(P), pd.DataFrame(V); R = P.pct_change(); R = R.where(R.abs() < 1.0); x, contrib = PM.port(PM.tsmom(P, V, 12), R)
    x.index = x.index.to_period("M"); x = x.reindex(idx).fillna(0.0); hh = len(x) // 2; t_ = PM.tstat(x); a, b = F.halves(x)
    solo = x.mean() > 0 and t_ >= 2.0 and a["tot"] > 0 and b["tot"] > 0; per = contrib.mean().dropna()
    res["1468"], legs["1468"] = judge(L, "1468", f"#1468 券商可買賣品種嘅時間序列動量腳（{P.shape[1]} 個品種）", x, m0, target, solo,
                                      f"月均 {100 * x.mean():+.3f}%、t {t_:+.2f}、前半／後半月均 {100 * x[x.index.year < F.SPLIT].mean():+.3f}%／{100 * x[x.index.year >= F.SPLIT].mean():+.3f}%；{int((per > 0).sum())}／{len(per)} 個品種為正")
    # 1469
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]; Z = {}; lo_all, hi_all, each = [], [], []
    for nm, tk in (("DAX", "^GDAXI"), ("富時", "^FTSE")):
        z = B6.rebal(B6.ohlc(tk).c, zn); z = z[z.index >= idx[0]]; lo, hi = z.r[z.rel < 0], z.r[z.rel >= 0]; lo_all += list(lo); hi_all += list(hi); each.append((nm, float(lo.mean() - hi.mean())))
        Z[nm] = pd.Series(np.where(z.rel < 0, 1.0, -1.0) * z.r.to_numpy() - 0.0004, index=z.index)
    st = pd.DataFrame(Z).mean(axis=1).reindex(idx).fillna(0.0); d0 = float(np.mean(lo_all) - np.mean(hi_all)); t_ = DR.welch(np.array(lo_all), np.array(hi_all))
    solo = d0 > 0 and t_ >= 2.0 and all(v > 0 for _, v in each) and st.mean() > 0
    res["1469"], legs["1469"] = judge(L, "1469", "#1469 月尾股債再平衡喺歐洲指數（DAX＋富時）", st, m0, target, solo,
                                      f"合併差 {100 * d0:+.2f}%（t {t_:+.2f}）；" + "、".join(f"{n} 差 {100 * v:+.2f}%" for n, v in each) + f"；策略每月平均 {100 * st.mean():+.3f}%（t {PM.tstat(st):+.2f}）")
    L += [f"## 總結：合格 {sum(res.values())}／3（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
