"""[IDEAS #231] #230 改波段定義：斐波那契區間＝轉勢點 → 極端（包影線）；入場／出場／組別／判斷同 #230（fib_sr.simulate）一字不改。
用法：python3 research/strategy_search/fib_sr2.py → FIB_SR2.md"""
import datetime as dt
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "research", "tianfu_charts"))
import fib_sr as S  # noqa: E402
from fib_swing import RevSwing  # noqa: E402


def build(t, o, h, l, c):
    n = len(t)
    st = [S.server_dt(x) for x in t]
    sw = {tf: RevSwing() for tf in S.LOOK}
    cur = {tf: None for tf in S.LOOK}
    lv = {tf: None for tf in S.LOOK}
    dcl = []
    levels, atr = [None] * n, np.full(n, np.nan)
    for i in range(n):
        for tf in S.LOOK:
            k = S.tf_key(st[i], tf)
            cb = cur[tf]
            if cb is None or cb[0] != k:
                if cb is not None:
                    sw[tf].add(cb[1], cb[2], cb[3])
                    lv[tf] = sw[tf].levels(S.ALL_R)
                    if tf == "D":
                        dcl.append((cb[1], cb[2], cb[3]))
                cur[tf] = [k, h[i], l[i], c[i]]
            else:
                cb[1] = max(cb[1], h[i]); cb[2] = min(cb[2], l[i]); cb[3] = c[i]
        if len(dcl) >= 15:
            trs = [max(dcl[j][0], dcl[j - 1][2]) - min(dcl[j][1], dcl[j - 1][2]) for j in range(len(dcl) - 14, len(dcl))]
            atr[i] = sum(trs) / 14
        levels[i] = dict(lv)
    return st, levels, atr


def main():
    t, o, h, l, c = S.G7.load_h1_duka()
    st, levels, atr = build(t, o, h, l, c)
    end = dt.datetime(2026, 11, 1)
    res = {}
    for v in ("M", "W", "D", "H4", "conf"):
        res[v] = [(d, r) for d, r in S.simulate(t, o, h, l, c, st, levels, atr, v) if S.SEGS[0][1] <= d < end]
        print(v, S.fmt(S.summ([r for _, r in res[v]])), flush=True)
    rand_all, rand_segs = [], []
    for seed in range(S.N_RAND):
        rng = random.Random(seed); memo = {}

        def offsets(key, A, rng=rng, memo=memo):
            if key not in memo:
                memo[key] = rng.uniform(1, 3) * rng.choice((-1, 1))
            return memo[key] * A
        tr = [(d, r) for d, r in S.simulate(t, o, h, l, c, st, levels, atr, "M", offsets) if S.SEGS[0][1] <= d < end]
        rand_all.append(S.summ([r for _, r in tr])); rand_segs.append(S.segs(tr))
    ravg = float(np.mean([s["avg"] for s in rand_all])); rn = float(np.mean([s["n"] for s in rand_all]))
    names = {"M": "Vm 月線（主判）", "W": "Vw 週線", "D": "Vd 日線", "H4": "Vh4 H4", "conf": "Vconf 月線＋其他時間框共振"}
    out = ["# 斐波那契支持／壓力・轉勢點區間（IDEAS #231，magic 926 測試）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Dukascopy H1 {len(t)} 根；波段＝轉勢點 → 極端（包影線，分形 2 根確認）；其餘同 #230",
           "- **同一批數據第二次試（#230 之後），合格都一定要影子前向先算數**", "",
           "| 組 | 全期 | " + " | ".join(s[0] for s in S.SEGS) + " | 剔走頭 5 張平均 | 中位數 |", "|---|---|---|---|---|---|---|"]
    for v in res:
        rr = np.sort([r for _, r in res[v]])
        trim = float(rr[:-5].mean()) if len(rr) > 5 else float("nan")
        med = float(np.median(rr)) if len(rr) else float("nan")
        out.append(f"| {names[v]} | {S.fmt(S.summ(list(rr)))} | " + " | ".join(S.fmt(x) for x in S.segs(res[v]))
                   + f" | {trim:+.3f}R | {med:+.2f}R |")
    rs = [float(np.mean([x[k]["avg"] for x in rand_segs])) for k in range(3)]
    out.append(f"| Vrand 月線位隨機移 ±1–3A（{S.N_RAND} 種子平均） | 平均 {rn:.0f} 張 平均 {ravg:+.3f}R | "
               + " | ".join(f"平均 {x:+.3f}R" for x in rs) + " | — | — |")
    m_all = S.summ([r for _, r in res["M"]]); m_sg = S.segs(res["M"])
    ok = {"①最後一段≥30張": m_sg[2]["n"] >= 30, "②最後一段平均R≥+0.15": m_sg[2]["avg"] >= 0.15,
          "③最後一段PF≥1.3": m_sg[2]["pf"] >= 1.3, "④三段平均R都>0": all(x["avg"] > 0 and x["n"] > 0 for x in m_sg),
          "⑤全期高過隨機≥0.10R": m_all["avg"] - ravg >= 0.10}
    out += ["", "## 判（預先登記 IDEAS #231；主判 Vm，標準同 #230）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            "- " + ("✅ 合格 → magic 926 影子前向 30 張（同一批數據第二次試，前向先算數）" if all(ok.values())
                    else "❌ 唔合格：" + "、".join(k for k, v in ok.items() if not v) + "；唔做、唔再改波段定義試同一批數據"), ""]
    open(os.path.join(HERE, "FIB_SR2.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
