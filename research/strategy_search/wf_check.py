"""[IDEAS #162] 合格家族嘅偏差檢查（唔改判斷，只係講清楚優勢係咪來自金價大升市）：
1. 樣本外成交拆做多／做空；
2. 基準：同一測試窗、同一組出場參數，喺每根 H4 收盤「盲買」（一次一張）嘅平均 R＝純順大市嘅回報。
用法：python3 research/strategy_search/wf_check.py"""
import json
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import search as S    # noqa: E402
import search2 as W   # noqa: E402

FAMS = ("G1_h4_donchian", "G6_prevweek", "G7_h1_pullback")


def trades_with_side(ctx, fam):
    d = ctx.d
    out = {}
    for p in W.grid(fam):
        sig = W.signals(ctx, fam, p)
        mats = W.trade_mats(d, sig)
        idx = np.array([i for i, _ in sig], dtype=np.int64)
        side = np.array([s for _, s in sig])
        atr = ctx.atr_at(fam, idx) if len(sig) else np.array([])
        for e in W.exits():
            r, ei, xi = W.simulate(e["K"] * atr, mats, e["R"], e["T"])
            keep = S.one_at_a_time(r, ei, xi)
            ts = d["t"][ei[keep]] if len(ei) else np.array([], np.int64)
            out[W.gkey(fam, p, e)] = (p, e, ts, r[keep], side[keep] if len(side) else side)
    return out


def blind_long(ctx, fam, e, a, b):
    d = ctx.d
    h4 = ctx.h4
    i = np.nonzero(h4.new)[0]
    i = i[(d["t"][i] >= a) & (d["t"][i] < b)]
    sig = [(int(k), 1) for k in i]
    mats = W.trade_mats(d, sig)
    atr = ctx.atr_at(fam, np.array([k for k, _ in sig], dtype=np.int64)) if sig else np.array([])
    r, ei, xi = W.simulate(e["K"] * atr, mats, e["R"], e["T"])
    keep = S.one_at_a_time(r, ei, xi)
    return r[keep]


def main():
    d = W.to_m5(S.load("mt5", "2022-08-03", "2026-10-30"))
    ctx = W.Ctx(d)
    out = ["# IDEAS #162 合格家族偏差檢查（做多／做空、對比盲買）", ""]
    for fam in FAMS:
        tr = trades_with_side(ctx, fam)
        dims = [len(W.FAMILIES[fam][k]) for k in W.FAMILIES[fam]] + [len(W.EXITS[k]) for k in W.EXITS]
        L, Sh, base = [], [], []
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
            p, e, ts, r, side = tr[best]
            m = (ts >= b) & (ts < c_)
            L.append(r[m & (side > 0)]); Sh.append(r[m & (side < 0)])
            base.append(blind_long(ctx, fam, e, b, c_))
        lr, sr, br = np.concatenate(L), np.concatenate(Sh), np.concatenate(base)
        out.append(f"## {fam}")
        out.append(f"- 做多：{S.fmt(S.stats(lr))}")
        out.append(f"- 做空：{S.fmt(S.stats(sr))}")
        out.append(f"- 基準（同出場參數，每根 H4 收盤盲買）：{S.fmt(S.stats(br))}")
        out.append("")
        print("\n".join(out[-5:]), flush=True)
    open(os.path.join(HERE, "WF_check_out.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
