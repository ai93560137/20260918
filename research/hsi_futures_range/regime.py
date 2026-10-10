"""恒指是否已經變了？（使用者 2026-10-10：八年前的策略可能不能再用，要分兩、三個階段測試）

A. 逐年市場特徵（主連 1 分 K，HK 交易日 = 09:00 至翌日 09:00）：
   指數水平、每日波幅（點、%）、當日收市升跌 ≥ 2% 的日數比例、每日 1 分 K 根數（夜市時長）、
   日回報一階自相關（> 0 趨勢延續、< 0 反轉）、日內方差比 VR(30) = 30 分回報方差 ÷ (30 × 1 分回報方差)（< 1 均值回歸、> 1 趨勢）、
   大波幅日回吐率：日內曾升跌 ≥ 2% 的日子，收市回吐超過一半的比例。
B. 分三個階段：P1 2018-10 至 2020-12、P2 2021-01 至 2023-12、P3 2024-01 起。
   參數網格：RSI 穿越／轉向 × 70/30、75/25、80/20、85/15 × 升跌 ≥ 1%／2% × 止賺 30／50／100 點 × 不加倉／加倉 1→5（不設止蝕）。
   交易按入場日歸入階段；每個階段算每年盈虧（點 × 張）、虧損筆數、最大浮虧。
   檢查：每個階段的最佳參數，放到其他階段表現如何；階段之間的參數排名相關（Spearman）。

用法：python3 research/hsi_futures_range/regime.py --json /tmp/hsimain.json
"""
import argparse, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402
import rsi_basic as rb                                      # noqa: E402

PHASES = (("P1 2018-10–2020-12", "0000", "2020-12-31"), ("P2 2021–2023", "2021-01-01", "2023-12-31"), ("P3 2024–", "2024-01-01", "9999"))


def yearly_features(D):
    days, starts, ends, o, h, l, c = D["days"], D["starts"], D["ends"], D["o"], D["h"], D["l"], D["c"]
    dc = c[ends - 1]
    ret = np.r_[np.nan, dc[1:] / dc[:-1] - 1]
    dh = np.array([h[s:e].max() for s, e in zip(starts, ends)])
    dl = np.array([l[s:e].min() for s, e in zip(starts, ends)])
    pc = np.r_[np.nan, dc[:-1]]
    print("年份  日數  指數    日波幅(點)  日波幅%  收市升跌≥2%  每日K數  日回報自相關  日內VR(30)  大波幅日回吐>一半")
    for y in sorted({d[:4] for d in days}):
        k = np.array([d[:4] == y for d in days])
        kk = k & ~np.isnan(pc)
        rng = (dh - dl)[k]
        r = ret[kk]
        ac = np.corrcoef(r[:-1], r[1:])[0, 1] if len(r) > 3 else np.nan
        vrs = []
        for s, e in zip(starts[k], ends[k]):
            x = np.diff(np.log(c[s:e]))
            if len(x) > 120:
                x30 = np.add.reduceat(x, np.arange(0, len(x) - len(x) % 30, 30))[:-1] if len(x) >= 60 else x
                vrs.append((x30.var() / (30 * x.var())) if x.var() > 0 else np.nan)
        up = (dh[kk] / pc[kk] - 1 >= 0.02)
        dn = (dl[kk] / pc[kk] - 1 <= -0.02)
        big = up | dn
        ret_half = ((up & ((dh[kk] - dc[kk]) > 0.5 * (dh[kk] - pc[kk]))) | (dn & ((dc[kk] - dl[kk]) > 0.5 * (pc[kk] - dl[kk]))))
        print(f"{y}  {k.sum():4d}  {dc[k].mean():6.0f}   {rng.mean():7.0f}    {np.mean(rng / dc[k]):6.2%}     {np.mean(np.abs(r) >= 0.02):6.1%}"
              f"    {np.mean(ends[k] - starts[k]):6.0f}     {ac:+6.2f}       {np.nanmean(vrs):5.2f}        "
              f"{(ret_half.sum() / big.sum() if big.sum() else np.nan):6.1%}（{big.sum()} 日）")


def phase_of(day):
    for name, lo, hi in PHASES:
        if lo <= day <= hi:
            return name


def grid(D):
    cfgs, out = [], {}
    for trig, (hi, lo), move, tp, al in itertools.product(("cross", "confirm"), ((70, 30), (75, 25), (80, 20), (85, 15)),
                                                         (0.01, 0.02), (30, 50, 100), ((), (1, 1, 1, 1))):
        sig = rb.signals(D, hi, lo, trig, move)
        t = rb.run_adds(D, sig, tp, al, entry_day=True)
        key = f"{rb.NAME[trig]}{hi}/{lo} ≥{move:.0%} 賺{tp} {'加倉1→5' if al else '不加倉'}"
        cfgs.append(key)
        out[key] = t
    return cfgs, out


def phase_stats(t, ph):
    x = [r for r in t if phase_of(r["entry"]) == ph]
    lo, hi = next((a, b) for n, a, b in PHASES if n == ph)
    yrs = {"P1 2018-10–2020-12": 2.25, "P2 2021–2023": 3.0, "P3 2024–": 2.78}[ph]
    pnl = sum(r["pnl"] for r in x)
    return {"n": len(x), "ann": pnl / yrs, "loss": sum(r["pnl"] < 0 for r in x),
            "worst": -min((r["worst"] for r in x), default=0), "maxloss": -min(min((r["pnl"] for r in x), default=0), 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    print("######## A. 逐年市場特徵 ########")
    yearly_features(D)
    print("\n######## B. 分三個階段（每年盈虧 = 點 × 張／年）########")
    cfgs, res = grid(D)
    names = [p[0] for p in PHASES]
    S = {k: {p: phase_stats(res[k], p) for p in names} for k in cfgs}
    for p in names:
        best = sorted(cfgs, key=lambda k: -S[k][p]["ann"])[:5]
        print(f"\n{p} 最好 5 組 → 在各階段的每年盈虧（虧損筆數，最大浮虧）")
        for k in best:
            print(f"  {k:28s}" + "  ".join(f"{q[:2]} {S[k][q]['ann']:+6.0f}（{S[k][q]['loss']}，{S[k][q]['worst']:5.0f}）" for q in names))
    print("\n參數排名相關（Spearman，96 組按每年盈虧排名；1 = 排名完全一樣、0 = 毫無關係）")
    rank = {p: np.argsort(np.argsort([-S[k][p]["ann"] for k in cfgs])) for p in names}
    for p, q in itertools.combinations(names, 2):
        print(f"  {p[:2]} 對 {q[:2]}：{np.corrcoef(rank[p], rank[q])[0, 1]:+.2f}")
    print("\n每個階段都賺錢的組數：" + str(sum(all(S[k][p]["ann"] > 0 for p in names) for k in cfgs)) + f"／{len(cfgs)}")
    robust = sorted((k for k in cfgs if all(S[k][p]["ann"] > 0 for p in names)), key=lambda k: -min(S[k][p]["ann"] for p in names))[:8]
    print("三個階段最差那段仍最好的 8 組：")
    for k in robust:
        print(f"  {k:28s}" + "  ".join(f"{q[:2]} {S[k][q]['ann']:+6.0f}（{S[k][q]['loss']}，{S[k][q]['worst']:5.0f}）" for q in names))
    print("\n上一輪選定（轉向 80/20 ≥2% 賺30 加倉1→5）：" + "  ".join(
        f"{q[:2]} {S['轉向80/20 ≥2% 賺30 加倉1→5'][q]['ann']:+6.0f}（{S['轉向80/20 ≥2% 賺30 加倉1→5'][q]['loss']}，{S['轉向80/20 ≥2% 賺30 加倉1→5'][q]['worst']:5.0f}）" for q in names))


if __name__ == "__main__":
    main()
