"""[IDEAS #1482–#1493] 論文實證：月尾股債再平衡（a）時間樣本外 1990–2010-06；（b）九個新地區 2010-07 起。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/paper_1482.py → research/strategy_search/PAPER_1482.md（要先跑過 fund_1464.py）"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import batch6_1462 as B6     # noqa: E402
import data_cache as DC      # noqa: E402
import direction_1445 as DR  # noqa: E402
import fetch_yahoo_daily as FY  # noqa: E402
import fund_1464 as F        # noqa: E402
import fund_1467 as G        # noqa: E402
import fund_1470 as F3       # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "PAPER_1482.md")
COST = 0.0004
DUR = 7.5
OOS = [("1482", "美國", [("標普", "^GSPC")], False, "1990-01"), ("1483", "歐洲", [("DAX", "^GDAXI"), ("富時", "^FTSE")], False, "1990-01"), ("1484", "亞洲", [("日經", "^N225"), ("ASX200", "^AXJO")], True, "1992-12")]
NEW = [("1485", "加拿大", "^GSPTSE", False), ("1486", "瑞士", "^SSMI", False), ("1487", "法國", "^FCHI", False), ("1488", "香港", "^HSI", True), ("1489", "韓國", "^KS11", True),
       ("1490", "印度", "^BSESN", True), ("1491", "台灣", "^TWII", True), ("1492", "新加坡", "^STI", True), ("1493", "巴西", "^BVSP", False)]


def tnx():
    key = "yahood/x__TNX_d.npz"; d = DC.get(key)
    if d is None:
        d = FY.fetch("^TNX"); DC.put(key, d)
    return B6.ohlc("^TNX").c


def bonds():
    """→ (接駁序列：2000-09 之前用孳息近似、之後 ZN=F；純孳息近似序列；ZN)。"""
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]; y = tnx(); y = y[(y > 0) & (y < 30)]
    syn = (1 - DUR * y.diff().fillna(0) / 100).cumprod(); cut = pd.Timestamp("2000-09-29"); a = syn[syn.index <= cut]; b = zn[zn.index > cut]
    return pd.concat([a * (zn[zn.index <= cut].iloc[-1] / a.iloc[-1]), b]), syn, zn


def leg(tk, bond, lag, start, end):
    s = B6.ohlc(tk).c; s = s[(s > 0) & (s.index.dayofweek < 5)]; b = (bond.shift(1) if lag else bond).reindex(s.index, method="ffill")
    z = B6.rebal(s, b); z = z[(z.index >= pd.Period(start, "M")) & (z.index <= pd.Period(end, "M"))]
    return z, pd.Series(np.where(z.rel < 0, 1.0, -1.0) * z.r.to_numpy() - COST, index=z.index)


def main():
    spl, syn, zn = bonds()
    L = ["# #1482–#1493：論文實證（月尾股債再平衡：時間樣本外＋九個新地區）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；現貨指數日線；來回成本 {100 * COST:.2f}%；只讀研究", ""]
    # ---------- (a) 時間樣本外
    za, _ = leg("^GSPC", zn, False, "2000-10", "2010-06"); zb, _ = leg("^GSPC", syn, False, "2000-10", "2010-06"); k = za.index.intersection(zb.index)
    agree = float((np.sign(za.rel[k]) == np.sign(zb.rel[k])).mean())
    L += ["## （a）時間樣本外：1990-01–2010-06（美債 2000-10 起 ZN=F，之前 ^TNX 孳息近似）", "",
          f"- 孳息近似對 ZN=F：2000-10–2010-06 標普 {len(k)} 個月，方向判斷一致率 {100 * agree:.0f}%", "",
          "| 編號 | 地區 | 月數 | 跑輸−跑贏 差 | Welch t | 各指數差 | 策略每月淨 | t | 前半／後半每月淨 | 判決 |", "|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for tag, nm, idxs, lag, start in OOS:
        lo_all, hi_all, each, X = [], [], [], {}
        for n, tk in idxs:
            z, x = leg(tk, spl, lag, start, "2010-06"); lo, hi = z.r[z.rel < 0], z.r[z.rel >= 0]; lo_all += list(lo); hi_all += list(hi); each.append((n, float(lo.mean() - hi.mean()))); X[n] = x
        st = pd.DataFrame(X).mean(axis=1); d0 = float(np.mean(lo_all) - np.mean(hi_all)); t_ = DR.welch(np.array(lo_all), np.array(hi_all))
        a, b = st[st.index < pd.Period("2000-10", "M")], st[st.index >= pd.Period("2000-10", "M")]
        ok = d0 > 0 and t_ >= 2.0 and all(v > 0 for _, v in each) and st.mean() > 0 and a.mean() > 0 and b.mean() > 0; res[tag] = ok
        L.append(f"| #{tag} | {nm} | {len(st)} | {100 * d0:+.3f}% | {t_:+.2f} | " + "、".join(f"{n} {100 * v:+.3f}%" for n, v in each) + f" | {100 * st.mean():+.3f}% | {PM.tstat(st):+.2f} | {100 * a.mean():+.3f}%／{100 * b.mean():+.3f}% | {'✅' if ok else '❌'} |")
    L += ["", f"- 小結：時間樣本外過關 {sum(res.values())}／3（論文證據，唔當新策略計數）", ""]
    # ---------- (b) 新地區
    m0, idx, target = G.base(); S = pd.Period(f"{F.SPLIT}-01", "M")
    base = {"美國": leg("^GSPC", zn, False, "2010-07", "2026-10")[1].reindex(idx).fillna(0.0),
            "歐洲": pd.DataFrame({t: leg(t, zn, False, "2010-07", "2026-10")[1] for t in ("^GDAXI", "^FTSE")}).mean(axis=1).reindex(idx).fillna(0.0),
            "亞洲": pd.DataFrame({t: leg(t, zn, True, "2010-07", "2026-10")[1] for t in ("^N225", "^AXJO")}).mean(axis=1).reindex(idx).fillna(0.0)}
    L += ["## （b）九個新地區：2010-07–2026-10（同 #1481 規則；亞洲用前一個交易日美債）", ""]; passed = {}; summ = []; allz = []
    for tag, nm, tk, lag in NEW:
        z, x = leg(tk, zn, lag, "2010-07", "2026-10"); lo, hi = z.r[z.rel < 0], z.r[z.rel >= 0]; d0 = float(lo.mean() - hi.mean()); t_ = DR.welch(lo.to_numpy(), hi.to_numpy()); st = x.reindex(idx).fillna(0.0)
        solo = d0 > 0 and t_ >= 2.0 and x.mean() > 0; allz.append(z)
        ok = F3.judge(L, f"#{tag} {nm}（{tk}）", st, m0, target, solo, f"{len(x)} 個月；跑輸−跑贏差 {100 * d0:+.3f}%（Welch t {t_:+.2f}；跑輸 {len(lo)}／跑贏 {len(hi)}）；策略每月淨 {100 * x.mean():+.3f}%（t {PM.tstat(x):+.2f}）", S)
        cr = {k: float(np.corrcoef(st, v)[0, 1]) for k, v in {**base, **passed}.items()}; dup = [k for k, v in cr.items() if v > 0.7]
        L[-1:-1] = ["- 每月相關：" + "、".join(f"{k} {v:+.2f}" for k, v in cr.items()) + ("；> 0.7：" + "、".join(dup) + " → 唔另計" if dup else "")]
        if ok and not dup:
            passed[nm] = st
        summ.append((tag, nm, d0, t_, float(x.mean()), ok, bool(dup)))
    lo = np.concatenate([z.r[z.rel < 0].to_numpy() for z in allz]); hi = np.concatenate([z.r[z.rel >= 0].to_numpy() for z in allz])
    L += ["## 新地區總表", "", "| 編號 | 地區 | 跑輸−跑贏差 | Welch t | 策略每月淨 | 全部關卡 | 另計 |", "|---|---|---|---|---|---|---|"]
    L += [f"| #{t} | {n} | {100 * d:+.3f}% | {tt:+.2f} | {100 * m:+.3f}% | {'✅' if ok else '❌'} | {'—' if not ok else ('否（相關 > 0.7）' if dup else '是')} |" for t, n, d, tt, m, ok, dup in summ]
    L += ["", f"- 面板：九個地區差為正 {sum(d > 0 for _, _, d, *_ in summ)}／9；合併 差 {100 * (lo.mean() - hi.mean()):+.3f}%（Welch t {DR.welch(lo, hi):+.2f}，各地區月份當獨立，實際有相關，t 偏高）",
          f"- 新增合格（可另計）：{len(passed)} 個" + ("（" + "、".join(passed) + "）" if passed else ""), ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
