"""H1 回調策略（IDEAS #162 G7）複利回測：用 #162 滾動前向樣本外成交（2023-09→2026-10，按實際次序），
比較「每張風險＝資金 f%」（複利）同「固定 0.05 手」。唔寫本金：資金用倍數（起點＝1）；固定手數用 HKD 盈虧。
再做 2,000 次重抽（bootstrap，打亂次序）估最大回撤分佈。
用法：python3 research/strategy_search/g7_compound.py"""
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import search as S    # noqa: E402
import search2 as W   # noqa: E402

FAM = "G7_h1_pullback"
RISKS = (0.005, 0.01, 0.02, 0.03)
HKD_PER_USD = 7.8
OZ_PER_LOT = 100
FIXED_LOTS = 0.05


def oos_trades():
    d = W.to_m5(S.load("mt5", "2022-08-03", "2026-10-30"))
    ctx = W.Ctx(d)
    tr = {}
    for p in W.grid(FAM):
        sig = W.signals(ctx, FAM, p)
        mats = W.trade_mats(d, sig)
        idx = np.array([i for i, _ in sig], dtype=np.int64)
        atr = ctx.atr_at(FAM, idx) if len(sig) else np.array([])
        for e in W.exits():
            sl = e["K"] * atr
            r, ei, xi = W.simulate(sl, mats, e["R"], e["T"])
            keep = S.one_at_a_time(r, ei, xi)
            tr[W.gkey(FAM, p, e)] = (p, e, d["t"][ei[keep]], r[keep], sl[keep])
    dims = [len(W.FAMILIES[FAM][k]) for k in W.FAMILIES[FAM]] + [len(W.EXITS[k]) for k in W.EXITS]
    T, R, SL = [], [], []
    for tr0, te0, te1 in W.windows():
        a, b, c_ = (S.ts_of(x.isoformat()) for x in (tr0, te0, te1))
        avg = {k: float(v[3][(v[2] >= a) & (v[2] < b)].mean()) for k, v in tr.items() if ((v[2] >= a) & (v[2] < b)).sum() >= W.MIN_TRAIN_N}
        if not avg:
            continue
        plat = {}
        for k in avg:
            vals = [avg[k]]
            for dp in range(len(dims)):
                for st in (-1, 1):
                    nk = list(k); nk[dp] += st; nk = tuple(nk)
                    if nk in avg:
                        vals.append(avg[nk])
            plat[k] = statistics.median(vals)
        best = max(plat, key=lambda k: plat[k])
        _, _, ts, r, sl = tr[best]
        m = (ts >= b) & (ts < c_)
        T.append(ts[m]); R.append(r[m]); SL.append(sl[m])
    return np.concatenate(T), np.concatenate(R), np.concatenate(SL)


def curve(rs, f):
    eq = np.cumprod(1 + f * rs)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return eq, float((eq / peak - 1).min())


def main():
    ts, rs, sl = oos_trades()
    years = (ts[-1] - ts[0]) / (365.25 * 86400)
    out = ["# H1 回調策略複利回測（#162 滾動前向樣本外成交，按實際次序）", "",
           f"- {len(rs)} 張，{years:.2f} 年（{S.fmt(S.stats(rs))}）；每張 R 已扣 0.5 美元成本",
           f"- 止損距離：中位 {np.median(sl):.1f} 美元（範圍 {sl.min():.1f}–{sl.max():.1f}）", "",
           "## 複利：每張風險＝當時資金 f%", "",
           "| 每張風險 | 最終資金（倍） | 年化 | 最大回撤 | 重抽 2,000 次：最大回撤中位／最差 5% | 重抽：最終蝕本機會 |", "|---|---|---|---|---|---|"]
    rng = np.random.default_rng(162)
    for f in RISKS:
        eq, dd = curve(rs, f)
        cagr = eq[-1] ** (1 / years) - 1
        dds, fins = [], []
        for _ in range(2000):
            e2, d2 = curve(rng.permutation(rs), f)
            dds.append(d2); fins.append(e2[-1])
        out.append(f"| {f:.1%} | {eq[-1]:.2f} | {cagr:+.1%} | {dd:.1%} | {np.median(dds):.1%}／{np.percentile(dds, 5):.1%} | {np.mean(np.array(fins) < 1):.1%} |")
    # 固定 0.05 手（而家 934 做法）：HKD 盈虧＝R × 止損美元 × 0.05 × 100 盎司 × 7.8
    pnl = rs * sl * FIXED_LOTS * OZ_PER_LOT * HKD_PER_USD
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.r_[0.0, cum])[1:]
    out += ["", "## 固定 0.05 手（934 而家做法）", "",
            f"- 每張風險：中位 {np.median(sl) * FIXED_LOTS * OZ_PER_LOT * HKD_PER_USD:,.0f} HKD（止損中位 {np.median(sl):.1f} 美元）",
            f"- 合計 {cum[-1]:+,.0f} HKD；每年約 {cum[-1] / years:+,.0f} HKD；最大回撤 {(cum - peak).min():,.0f} HKD；最差單張 {pnl.min():,.0f} HKD",
            "", "## 每年", "", "| 年 | 張 | 平均 R | 1% 複利當年回報 | 固定 0.05 手 HKD |", "|---|---|---|---|---|"]
    import datetime as dt
    yrs = np.array([dt.datetime.fromtimestamp(int(t), dt.timezone.utc).year for t in ts])
    for y in sorted(set(yrs)):
        m = yrs == y
        out.append(f"| {y} | {m.sum()} | {rs[m].mean():+.3f} | {np.prod(1 + 0.01 * rs[m]) - 1:+.1%} | {pnl[m].sum():+,.0f} |")
    out += ["", "## 注意",
            "- 樣本外成交只有 155 張；重抽結果假設將來分佈同過去一樣，實際可能差好多（尤其冇經新數據驗證）。",
            "- 複利要隨資金調手數；MT5 最細 0.01 手，資金細時做唔到精確百分比（例如止損 20 美元、0.01 手已經係風險約 156 HKD）。",
            "- 冇計隔夜息、數據公佈極端滑價；最大回撤喺真倉通常會大過回測。"]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "G7_COMPOUND.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
