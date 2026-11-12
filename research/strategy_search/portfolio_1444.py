"""[IDEAS #1444] 天覆組合 v1：已驗證嘅方向部件等權組合（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準（跑之前 commit；部件唔加唔改）。
G 黃金 #1268 狀態機雙向（stooq）；S 白銀 #1285 只做多（SI=F）；E 標普 ES=F #1268 事件版雙向；H 恒指 ^HSI #1268 事件版雙向。每張 1R。
用法：python3 research/strategy_search/portfolio_1444.py → research/strategy_search/PORTFOLIO_1444.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import data_cache as DC      # noqa: E402
import index_1427 as IX      # noqa: E402
import multi_1422 as MU      # noqa: E402

OUT = os.path.join(HERE, "PORTFOLIO_1444.md")
T0, T1 = "2001-07-01", "2026-10-31"


def parts():
    si = DC.get("yahood/SI_F_d.npz"); si = {k: si[k] for k in ("t", "o", "h", "l", "c")}
    return {"G 黃金 #1268 雙向": MU.run(MU.stooq("xauusd", "1990-01-01"), 0.0005)["#1422"],
            "S 白銀 #1285 只做多": IX.sim(si, IX.CFG[2], 0.0012, long_only=True)[0],
            "E 標普 #1427 雙向": IX.sim(IX.load("ES_F"), IX.CFG[0], 0.0002)[0],
            "H 恒指 #1427 雙向": IX.sim(IX.load("HSI"), IX.CFG[0], 0.0005)[0]}


def mkey(t):
    x = dt.datetime.fromtimestamp(int(t), dt.timezone.utc); return x.year * 12 + x.month - 1


def monthly(tr, m0, m1):
    v = np.zeros(m1 - m0 + 1)
    for t, _, r in tr:
        if m0 <= mkey(t) <= m1:
            v[mkey(t) - m0] += r
    return v


def dd(v):
    c = np.cumsum(v); return float((np.maximum.accumulate(np.r_[0, c]) - np.r_[0, c]).max())


def stat(v, m0):
    yrs = {}
    for i, x in enumerate(v):
        yrs[(m0 + i) // 12] = yrs.get((m0 + i) // 12, 0) + x
    w12 = min(v[i:i + 12].sum() for i in range(len(v) - 11))
    return {"sum": float(v.sum()), "dd": dd(v), "ratio": float(v.sum() / dd(v)) if dd(v) > 0 else float("inf"), "w12": float(w12), "neg": sum(1 for y in yrs.values() if y < 0), "ny": len(yrs)}


def main():
    P = parts(); m0, m1 = mkey(MU.OG.ts(T0)), mkey(MU.OG.ts(T1)); M = {k: monthly(v, m0, m1) for k, v in P.items()}; keys = list(P); g = keys[0]
    half = (m1 - m0 + 1) // 2; port = sum(M.values())
    row = lambda name, v: (lambda s, a, b: f"| {name} | {s['sum']:+.1f} | {s['dd']:.1f} | {s['ratio']:.2f} | {a['ratio']:.2f} | {b['ratio']:.2f} | {s['w12']:+.1f} | {s['neg']}／{s['ny']} |")(stat(v, m0), stat(v[:half], m0), stat(v[half:], m0 + half))  # noqa: E731
    L = ["# #1444：天覆組合 v1（已驗證方向部件等權組合）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；共同期 {T0} → {T1}；每張 1R、等權相加；每月 R；只讀研究，唔落單",
         "- **樣本內**：部件係因為喺重疊數據上合格先揀入嚟，結果會高估；真正考驗係影子前向", "",
         "| 組合 | ΣR | 最大回落 R | ΣR÷回落 | 前半 | 後半 | 最差連續 12 月 R | 蝕錢年數 |", "|---|---|---|---|---|---|---|---|"]
    for k in keys:
        L.append(row(k, M[k]))
    L.append(row("**組合 G＋S＋E＋H**", port))
    loo = {}
    for k in keys[1:]:
        v = sum(M[j] for j in keys if j != k); loo[k] = stat(v, m0)["ratio"]; L.append(row(f"剔走 {k.split()[0]}", v))
    sg, sp = stat(M[g], m0), stat(port, m0)
    corr = {k: float(np.corrcoef(M[g], M[k])[0, 1]) for k in keys[1:]}
    g1 = sp["ratio"] > sg["ratio"]; g2 = stat(port[:half], m0)["ratio"] > stat(M[g][:half], m0)["ratio"] and stat(port[half:], m0 + half)["ratio"] > stat(M[g][half:], m0 + half)["ratio"]
    g3 = sp["neg"] <= sg["neg"]; g4 = all(c < 0.5 for c in corr.values()); g5 = all(r > sg["ratio"] for r in loo.values())
    L += ["", "## 每月 R 相關", "", "| | " + " | ".join(k.split()[0] for k in keys) + " |", "|---|" + "---|" * len(keys)]
    for a in keys:
        L.append(f"| {a.split()[0]} | " + " | ".join(f"{np.corrcoef(M[a], M[b])[0, 1]:+.2f}" for b in keys) + " |")
    L += ["", "## 判決", "", f"- ①全期組合 > 黃金：{sp['ratio']:.2f} 對 {sg['ratio']:.2f} {'✓' if g1 else '✗'}", f"- ②前後半都 > 黃金：{'✓' if g2 else '✗'}",
          f"- ③蝕錢年數 ≤ 黃金：{sp['neg']} 對 {sg['neg']} {'✓' if g3 else '✗'}", f"- ④新部件同黃金相關 < 0.5：" + "、".join(f"{k.split()[0]} {c:+.2f}" for k, c in corr.items()) + f" {'✓' if g4 else '✗'}",
          f"- ⑤剔走任何一個仍 > 黃金：" + "、".join(f"剔 {k.split()[0]} {r:.2f}" for k, r in loo.items()) + f" {'✓' if g5 else '✗'}",
          f"- **{'✅ 合格' if all((g1, g2, g3, g4, g5)) else '❌ 唔合格'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
