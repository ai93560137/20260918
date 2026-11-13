"""[IDEAS #1464–#1466] 基金層面第一批：…63＋…69 當一個基金。規格同門檻以 IDEAS 預先登記為準（11-13 UTC，跑之前 commit）。
用法：python3 research/strategy_search/fund_1464.py → research/strategy_search/FUND_1464.md"""
import datetime as dt
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import batch6_1462 as B6       # noqa: E402
import h4wide_1402 as H        # noqa: E402
import intraday_1323 as I      # noqa: E402
import multi_1422 as MU        # noqa: E402
import trend_d1rules as D1R    # noqa: E402

OUT = os.path.join(HERE, "FUND_1464.md")
WIN, NRAND, SPLIT = 420, 200, 2018
GOLD = (("926", "tdflip"), ("942", "td"), ("940", "tdsurge"), ("937", "spike"), ("939", "kelt"))   # 同日有幾個訊號時嘅先後次序（固定）
CACHE = "/tmp/fund_1464_pre.pkl"


def precompute(days, rules, min_abs):
    """每日（已完成到嗰日）嘅訊號、最低止蝕、兩邊嘅規則出場；同持倉路徑無關。"""
    n = len(days); P = {r: {"sig": [None] * n, "xl": [False] * n, "xs": [False] * n} for r in rules}; fl = [None] * n
    for j in range(60, n):
        w = days[max(0, j - WIN + 1):j + 1]; fl[j] = D1R.floor(w, min_abs)
        for r in rules:
            P[r]["sig"][j] = D1R.signal(r, w); P[r]["xl"][j] = D1R.exit_hit(r, 1, w) is not None; P[r]["xs"][j] = D1R.exit_hit(r, -1, w) is not None
    return P, fl


def sim_daily(days, P, fl, books, mult, cost, cap=None, extra=(), skip=None, long_only=False):
    """逐日聯合模擬。books＝[(名, 規則)]；extra＝944 候選 [(t0, t1, side, pnl$)]（按 t0 排序）。cap＝同向最多幾張；skip＝(rng, p) 隨機擋。
    回傳 [(名, 入場 ts, 出場 ts, side, 損益$, 風險$)] 同被擋張數。"""
    n = len(days); pos = {}; pend_in = {}; pend_out = set(); busy = {b: -1 for b, _ in books}; out = []; blocked = 0
    xi = 0; xopen = None                                   # 944 持倉：(t1, side, pnl, risk, t0)
    T = [k * 86400 for k, _ in days]

    def count(sg):
        return sum(1 for p in pos.values() if p["side"] == sg) + (1 if xopen and xopen[1] == sg else 0)

    def allow(sg):
        nonlocal blocked
        if cap is not None and count(sg) >= cap:
            blocked += 1; return False
        if skip is not None and skip[0].random() < skip[1]:
            blocked += 1; return False
        return True
    for j in range(61, n):
        k, r = days[j]; t = T[j]
        for b in list(pend_out):                           # 開市：規則出場
            p = pos.pop(b); out.append((b, p["t"], t, p["side"], ((r["o"] - p["e"]) * p["side"] - cost) * mult, p["risk"] * mult)); busy[b] = j - 1
        pend_out.clear()
        for b, _ in books:                                 # 開市：入場（固定次序）
            s = pend_in.pop(b, None)
            if s and b not in pos and allow(s["side"]):
                pos[b] = {"side": s["side"], "e": r["o"], "sl": r["o"] - s["side"] * s["risk"], "risk": s["risk"], "t": t, "j": j, "rule": s["rule"]}
        pend_in.clear()
        t_end = T[j] + 86400                               # 944：日內事件（按時間）
        while True:
            if xopen and xopen[0] < t_end:
                out.append(("944", xopen[4], xopen[0], xopen[1], xopen[2], xopen[3])); xopen = None; continue
            if xi < len(extra) and extra[xi][0] < t_end:
                c = extra[xi]; xi += 1
                if xopen is None and allow(c[2]):
                    xopen = (c[1], c[2], c[3], c[4], c[0])
                continue
            break
        for b in list(pos):                                # 日內：止蝕
            p = pos[b]; sg = p["side"]
            if (r["l"] <= p["sl"]) if sg > 0 else (r["h"] >= p["sl"]):
                px = p["sl"] if p["j"] == j else (min(r["o"], p["sl"]) if sg > 0 else max(r["o"], p["sl"]))
                out.append((b, p["t"], t, sg, ((px - p["e"]) * sg - cost) * mult, p["risk"] * mult)); pos.pop(b); busy[b] = j
        for b, rule in books:                              # 收市：決定聽日
            if b in pos:
                p = pos[b]
                if (j - p["j"] + 1) >= D1R.MAX_BARS[rule] or (P[rule]["xl"][j] if p["side"] > 0 else P[rule]["xs"][j]):
                    pend_out.add(b)
            elif j > busy[b]:
                s = P[rule]["sig"][j]
                if s and fl[j] is not None and not (long_only and s["side"] < 0):
                    pend_in[b] = {"side": s["side"], "risk": max(s["risk"] or 0.0, fl[j]), "rule": rule}
    return out, blocked


def mobrk(days):
    """933 #1114：每月頭 3 個平日嘅高低；之後日線高低判突破（同日兩邊都穿就唔做）；SL＝區間另一邊；月尾最後一個平日收市平。"""
    out = []; by = {}
    for j, (k, r) in enumerate(days):
        d = dt.datetime.fromtimestamp(k * 86400, dt.timezone.utc)
        if d.weekday() < 5:
            by.setdefault((d.year, d.month), []).append(j)
    for (_, _), js in sorted(by.items()):
        if len(js) < 8:
            continue
        hi = max(days[j][1]["h"] for j in js[:3]); lo = min(days[j][1]["l"] for j in js[:3]); risk = hi - lo
        if risk <= 0.5:
            continue
        p = None
        for j in js[3:]:
            r = days[j][1]
            if p is None:
                up, dn = r["h"] > hi, r["l"] < lo
                if up and dn:
                    break
                if up or dn:
                    sg = 1 if up else -1; e = max(hi, r["o"]) if up else min(lo, r["o"]); p = (sg, e, e - sg * risk, days[j][0] * 86400); continue
            else:
                sg, e, sl, t0 = p
                if (r["l"] <= sl) if sg > 0 else (r["h"] >= sl):
                    px = min(r["o"], sl) if sg > 0 else max(r["o"], sl); out.append(("933", t0, days[j][0] * 86400, sg, (px - e) * sg - 0.5, risk)); p = None; break
        if p is not None:
            sg, e, sl, t0 = p; out.append(("933", t0, days[js[-1]][0] * 86400, sg, (days[js[-1]][1]["c"] - e) * sg - 0.5, risk))
    return out


def monthly(tr, idx, scale=None):
    s = pd.Series(0.0, index=idx)
    for b, _, t1, _, pnl, _ in tr:
        m = pd.Timestamp(t1, unit="s").to_period("M")
        if m in s.index:
            s[m] += pnl * (scale.get(b, 1.0) if scale else 1.0)
    return s


def stats(m):
    v = m.to_numpy(); c = np.cumsum(v); dd = float((np.maximum.accumulate(np.r_[0, c]) - np.r_[0, c]).max())
    return {"tot": float(v.sum()), "dd": dd, "rd": float(v.sum() / dd) if dd > 0 else 0.0, "sh": float(v.mean() / v.std() * np.sqrt(12)) if v.std() > 0 else 0.0}


def halves(m):
    return stats(m[m.index.year < SPLIT]), stats(m[m.index.year >= SPLIT])


def main():
    if os.path.exists(CACHE):
        pre = pickle.load(open(CACHE, "rb"))
    else:
        E, _, tl = H.eng(); d = E.d; db = I.B.resample(d, 86400)
        gd = [(int(t) // 86400, {"o": float(o), "h": float(h), "l": float(l), "c": float(c)}) for t, o, h, l, c in zip(db["t"], db["o"], db["h"], db["l"], db["c"])]
        P, fl = precompute(gd, [r for _, r in GOLD], 3.0)
        cand = np.flatnonzero(E.elig & (((E.st > 0) & tl[1]["MACD"]) | ((E.st < 0) & tl[-1]["MACD"]))); ex = []
        for i in cand:
            t0, t1, sg, R = E.go(np.array([int(i)]), None, None, True)[0]; ex.append((int(t0), int(t1), int(sg), float(R * E.risk[i]), float(E.risk[i])))
        s = MU.stooq("xagusd", "2008-06-01"); sd = [(int(t) // 86400, {"o": float(o), "h": float(h), "l": float(l), "c": float(c)}) for t, o, h, l, c in zip(s["t"], s["o"], s["h"], s["l"], s["c"])]
        Ps, fls = precompute(sd, ["tdsurge"], 0.0)
        pre = (gd, P, fl, ex, sd, Ps, fls); pickle.dump(pre, open(CACHE, "wb"))
    gd, P, fl, ex, sd, Ps, fls = pre
    idx = pd.period_range("2010-07", pd.Timestamp(gd[-1][0] * 86400, unit="s").to_period("M"), freq="M")
    other = mobrk(gd) + sim_daily(sd, Ps, fls, [("943", "tdsurge")], 50.0, 0.06, long_only=True)[0]

    def fund(cap=None, skip=None):
        g, blocked = sim_daily(gd, P, fl, list(GOLD), 1.0, 0.5, cap=cap, extra=ex, skip=skip)
        return g + other, blocked
    f0, _ = fund(); m0 = monthly(f0, idx); s0 = stats(m0); h0 = halves(m0)
    L = ["# #1464–#1466：基金層面第一批（…63＋…69 當一個基金）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{idx[0]}–{idx[-1]}；全部 0.01 手、美元；已平倉損益喺出場月入賬；只讀研究",
         "- 黃金 5 本日線簿＋白銀用真倉規則模組逐日模擬；944 用 h4wide_1402 逐張；933 用日線高低近似。**基金層面三條都係樣本內**，合格只代表值得出提案", "",
         "## 基金基準 F0（而家 8 本、各 0.01 手）", "", "| 簿 | 張 | 總損益 $ | 每張平均風險 $ | 每張平均 $ | 勝率 |", "|---|---|---|---|---|---|"]
    names = [b for b, _ in GOLD] + ["944", "933", "943"]; per = {}
    for b in names:
        x = [q for q in f0 if q[0] == b and pd.Timestamp(q[2], unit="s").to_period("M") in idx]; per[b] = x
        L.append(f"| {b} | {len(x)} | {sum(q[4] for q in x):+,.0f} | {np.mean([q[5] for q in x]):,.0f} | {np.mean([q[4] for q in x]):+,.1f} | {100 * np.mean([q[4] > 0 for q in x]):.0f}% |")
    L += ["", f"- F0：總 {s0['tot']:+,.0f} 美元、每月最大回落 {s0['dd']:,.0f}、總 ÷ 回落 {s0['rd']:.2f}、每月 Sharpe {s0['sh']:.2f}；前半 {h0[0]['rd']:.2f}／{h0[0]['sh']:.2f}、後半 {h0[1]['rd']:.2f}／{h0[1]['sh']:.2f}（總÷回落／Sharpe）"]
    M = pd.DataFrame({b: monthly(per[b], idx) for b in names}); c = M.corr()
    L += ["- 各簿每月損益相關（黃金 6 本之間平均）：" + f"{np.mean([c.loc[a, b] for i, a in enumerate(names[:6]) for b in names[:6][i + 1:]]):+.2f}；白銀對黃金 6 本平均 {np.mean([c.loc['943', b] for b in names[:6]]):+.2f}；933 對其餘黃金 {np.mean([c.loc['933', b] for b in names[:6]]):+.2f}", ""]
    res = {}
    # ---- 1464
    L += ["## #1464 黃金同方向持倉上限", "", "| 上限 K | 被擋張數 | 總損益 $ | 最大回落 | 總÷回落 | 對 F0 | 前半總÷回落 | 後半總÷回落 | Sharpe |", "|---|---|---|---|---|---|---|---|---|",
          f"| 冇上限（F0） | 0 | {s0['tot']:+,.0f} | {s0['dd']:,.0f} | {s0['rd']:.2f} | — | {h0[0]['rd']:.2f} | {h0[1]['rd']:.2f} | {s0['sh']:.2f} |"]
    K = {}
    for k in (3, 2, 4):
        f, nb = fund(cap=k); m = monthly(f, idx); K[k] = (stats(m), halves(m), nb); s, hh = K[k][0], K[k][1]
        L.append(f"| {k} | {nb} | {s['tot']:+,.0f} | {s['dd']:,.0f} | {s['rd']:.2f} | {100 * (s['rd'] / s0['rd'] - 1):+.0f}% | {hh[0]['rd']:.2f} | {hh[1]['rd']:.2f} | {s['sh']:.2f} |")
    ng = sum(len(per[b]) for b in names[:6]); p = K[3][2] / max(ng + K[3][2], 1); rng = np.random.default_rng(1464); rr = []
    for _ in range(NRAND):
        f, _ = fund(skip=(rng, p)); rr.append(stats(monthly(f, idx))["rd"])
    pct = 100.0 * float(np.mean(np.array(rr) < K[3][0]["rd"])); s3, h3 = K[3][0], K[3][1]
    g = [s3["rd"] >= 1.15 * s0["rd"], h3[0]["rd"] > h0[0]["rd"] and h3[1]["rd"] > h0[1]["rd"], K[2][0]["rd"] >= s0["rd"] and K[4][0]["rd"] >= s0["rd"], pct >= 95, s3["tot"] >= 0.8 * s0["tot"]]; res["1464"] = all(g)
    L += ["", f"- 隨機擋走同樣比例（{100 * p:.1f}%）黃金單 {NRAND} 次：總÷回落平均 {np.mean(rr):.2f}；K＝3 贏過 {pct:.0f}%", f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1464'] else '❌ 唔合格'}**", ""]
    # ---- 1465
    first = {b: [q for q in per[b] if pd.Timestamp(q[2], unit="s").year < SPLIT] for b in names}
    base = np.mean([q[5] for q in first["926"]]); mult = {b: float(base / np.mean([q[5] for q in first[b]])) for b in names}; mr = {b: float(max(1, round(v))) for b, v in mult.items()}
    L += ["## #1465 等風險注碼（每張平均風險金額拉到同 926 一樣；倍數用前半計）", "", "| 版本 | " + " | ".join(names) + " | 總損益 $ | 最大回落 | 總÷回落 | Sharpe | 前半 Sharpe | 後半 Sharpe |", "|---|" + "---|" * (len(names) + 6),
          "| F0（全部 ×1） | " + " | ".join("1" for _ in names) + f" | {s0['tot']:+,.0f} | {s0['dd']:,.0f} | {s0['rd']:.2f} | {s0['sh']:.2f} | {h0[0]['sh']:.2f} | {h0[1]['sh']:.2f} |"]
    W = {}
    for tag, mm in (("等風險（連續倍數）", mult), ("等風險（整數手數）", mr)):
        m = monthly(f0, idx, mm); W[tag] = (stats(m), halves(m)); s, hh = W[tag]
        L.append(f"| {tag} | " + " | ".join(f"{mm[b]:.2f}" for b in names) + f" | {s['tot']:+,.0f} | {s['dd']:,.0f} | {s['rd']:.2f} | {s['sh']:.2f} | {hh[0]['sh']:.2f} | {hh[1]['sh']:.2f} |")
    a, ah = W["等風險（連續倍數）"]; r_, _ = W["等風險（整數手數）"]
    g = [a["sh"] >= 1.10 * s0["sh"], a["rd"] >= 1.10 * s0["rd"], ah[0]["sh"] >= h0[0]["sh"] and ah[1]["sh"] >= h0[1]["sh"], r_["sh"] >= 1.10 * s0["sh"] and r_["rd"] >= 1.10 * s0["rd"]]; res["1465"] = all(g)
    L += ["", f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1465'] else '❌ 唔合格'}**", ""]
    # ---- 1466
    def ser(key):
        d = B6.IX.load(key); return pd.Series(np.asarray(d["c"], float), index=pd.to_datetime(np.asarray(d["t"], "int64"), unit="s").normalize())
    zn = B6.ohlc("ZN=F").c; z = B6.rebal(ser("ES_F"), zn[zn > 0]); sl = pd.Series(np.where(z.rel < 0, 1.0, -1.0) * z.r.to_numpy() - 0.0004, index=z.index).reindex(idx).fillna(0.0)
    target = float(np.mean([M[b].std() for b in names[:6]])); leg = sl * (target / sl.std()); m1 = m0 + leg; s1 = stats(m1); h1 = halves(m1); lh = halves(leg); cr = float(np.corrcoef(leg, m0)[0, 1])
    g = [s1["sh"] >= 1.10 * s0["sh"], s1["rd"] >= 1.10 * s0["rd"], h1[0]["sh"] > h0[0]["sh"] and h1[1]["sh"] > h0[1]["sh"], cr < 0.2, lh[0]["tot"] > 0 and lh[1]["tot"] > 0]; res["1466"] = all(g)
    L += ["## #1466 加入月尾股債再平衡腳（ES 期貨，#1463）", "", "| 版本 | 總損益 $ | 最大回落 | 總÷回落 | Sharpe | 前半 Sharpe | 後半 Sharpe |", "|---|---|---|---|---|---|---|",
          f"| F0 | {s0['tot']:+,.0f} | {s0['dd']:,.0f} | {s0['rd']:.2f} | {s0['sh']:.2f} | {h0[0]['sh']:.2f} | {h0[1]['sh']:.2f} |",
          f"| F0＋股債腳 | {s1['tot']:+,.0f} | {s1['dd']:,.0f} | {s1['rd']:.2f} | {s1['sh']:.2f} | {h1[0]['sh']:.2f} | {h1[1]['sh']:.2f} |",
          f"| 股債腳本身 | {leg.sum():+,.0f} | {stats(leg)['dd']:,.0f} | {stats(leg)['rd']:.2f} | {stats(leg)['sh']:.2f} | {lh[0]['sh']:.2f} | {lh[1]['sh']:.2f} |", "",
          f"- 股債腳同 F0 每月損益相關 {cr:+.2f}；注碼＝每月標準差 {target:,.0f} 美元（等於一本黃金簿嘅平均），相當於每次約 {target / sl.std():,.0f} 美元名義 ES 倉位；前半／後半本身損益 {lh[0]['tot']:+,.0f}／{lh[1]['tot']:+,.0f}",
          f"- 關卡 {''.join('✓' if v else '✗' for v in g)} → **{'✅ 合格' if res['1466'] else '❌ 唔合格'}**", "",
          f"## 總結：合格 {sum(res.values())}／3（" + "、".join(f"#{k} {'✅' if v else '❌'}" for k, v in res.items()) + "）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
