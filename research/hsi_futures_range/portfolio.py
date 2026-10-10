"""地載陣整體組合（使用者 2026-10-10：衡＋缺合併有意外收穫，朝這方向變成一個整體策略）。

候選成份（恒指主連 1 分 K，1 張大期，每日盈虧點；衡用滾動選參，其他用固定規則）：
  衡      地載・衡（每年用前兩年選參，選法 b，2% 災難止蝕）——2021 起
  缺      地載・缺（跳空 ≥ 0.5%、Nasdaq 反向、±0.25% 突破、RSI 不追極端、收市平倉）
  穩60    地載・穩用 60 分 RSI 轉向（加倉 1→2→4、止賺 30、止蝕 1000、留倉）
  進NQ    地載・進＋Nasdaq 篩選（止蝕 1500）
  突破    開市突破 ±0.25%、止蝕對面、收市平倉（無篩選）
  突破V   開市突破 ±0.25%、VHSI > 一年 75 分位、1R 止賺
組合：每個成份 0／1／2 份（1 份 = 1 張起），只用 2021–2023 挑「Sharpe 最高而且最大回撤 ≤ 年化」的一組，2024 起只報告；
另列等風險（按 2021–2023 每日波動倒數分配）作對照。注意：缺、穩60、進NQ、突破V 本身是用全期數據挑出來的條件，2024 起不是完全樣本外。

用法：python3 research/hsi_futures_range/portfolio.py --json /tmp/hsimain.json
"""
import argparse, functools, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_cross as dc                                    # noqa: E402
import dizai_filters as fl                                  # noqa: E402
import dizai_martingale as mg                               # noqa: E402
import dizai_more as dm                                     # noqa: E402
import dizai_search as ds                                   # noqa: E402
import dizai_vhsi as dv                                     # noqa: E402
import open_breakout as ob                                  # noqa: E402
import open_breakout2 as ob2                                # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402
import rsi_basic as rb                                      # noqa: E402

HENG = {"2021": ("confirm", 75, 25, .01, .005, (), None), "2022": ("confirm", 75, 25, .01, .005, (1, 1, 1, 1), .02),
        "2023": ("confirm", 75, 25, .02, .003, (), None), "2024": ("cross", 75, 25, .02, .005, (), None),
        "2025": ("cross", 85, 15, .01, .005, (1, 1, 1, 1), .01), "2026": ("cross", 75, 25, .02, .003, (), None)}
TRAIN = ("2021-01-01", "2023-12-31")
TEST = ("2024-01-01", "9999")


def components(D):
    days = D["days"]
    idx = {d: i for i, d in enumerate(days)}
    out = {}
    heng = np.zeros(len(days))
    for y, (trig, hi, lo, mv, tp, al, sp) in HENG.items():
        for x in rb.run_adds(D, rb.signals(D, hi, lo, trig, mv), None, al, tp_pct=tp, step_pct=sp, dstop_pct=.02, entry_day=True):
            if x["entry"][:4] == y and x["reason"] != "open":
                heng[idx[x["entry"]] + x["days"]] += x["pnl"]
    out["衡"] = heng
    dsl = ob.day_slices(D)
    o, c, tk = D["o"], D["c"], D["tk"]
    nq = dc.load_us("usatechidxusd")
    vh = ob2.vhsi_prev(days)
    feat, prev = {}, None
    for k, s, e in dsl:
        if prev:
            pk, ps, pe = prev
            feat[k] = (o[s] / c[D["ends"][k - 1] - 1] - 1, dc.us_move(nq, dc.hk_to_utc_min(tk[pe - 1]), dc.hk_to_utc_min(tk[s]) - 1), vh.get(days[k]))
        prev = (k, s, e)

    def daily(res):
        a = np.zeros(len(days))
        for r in res:
            a[r[0]] += r[1]
        return a
    out["缺"] = daily(ob.simulate(D, dsl, .0025, "對面", None, ob.RSI_RULES["不追極端"], 1,
                                 lambda k, b: k in feat and abs(feat[k][0]) >= .005 and feat[k][1] is not None and feat[k][1] * b < 0))
    out["突破"] = daily(ob.simulate(D, dsl, .0025, "對面", None, None, 1))
    out["突破V"] = daily(ob.simulate(D, dsl, .0025, "對面", 1, None, 1,
                                    lambda k, b: k in feat and feat[k][2] is not None and feat[k][2][0] > feat[k][2][2]))
    F = fl.day_features(D)
    orig = mg.simulate_mg

    def mgcomp(trig, tf, g, tp, sl, f5=None, nqf=None):
        sig = dm.tf_signals(D, trig, tf)
        if f5:
            sig = [(i, s) for i, s in sig if fl.keep(F, D, i, s, f5)]
        if nqf:
            ft = dc.features(D, sig, nq)
            sig = [(i, s) for i, s in sig if dc.keep(ft, i, s, nqf)]
        mg.simulate_mg = functools.partial(orig, add_lots=(1, 2))
        try:
            t = dm.run_seq(D, sig, g, tp, sl)
        finally:
            mg.simulate_mg = orig
        eq = dv.daily_equity(D, t, [1.0] * len(t))
        return np.diff(np.r_[0.0, eq])
    out["穩60"] = mgcomp("confirm", 60, .75, 30, 1000)
    out["進NQ"] = mgcomp("cross", 1, 1.0, 150, 1500, "run5_3", "oppo")
    return out


def metrics(x, days, lo, hi):
    sel = np.array([lo <= d <= hi for d in days])
    v = x[sel]
    eq = np.cumsum(v)
    mdd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
    ann = v.sum() / (sel.sum() / 245)
    return {"ann": ann, "mdd": mdd, "sharpe": v.mean() / v.std() * np.sqrt(252) if v.std() > 0 else 0.0,
            "calmar": ann / -mdd if mdd < 0 else float("inf")}


def fmt(m):
    return f"每年 {m['ann']:+7.0f} 點 回撤 {m['mdd']:7.0f} Sharpe {m['sharpe']:5.2f} 年化÷回撤 {m['calmar']:4.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    C = components(D)
    names = list(C)
    print("######## 1. 各成份（2021–2023 訓練／2024 起測試）########")
    for n in names:
        print(f"  {n:5s} 訓練 {fmt(metrics(C[n], days, *TRAIN))}｜測試 {fmt(metrics(C[n], days, *TEST))}")
    sel = np.array([d >= "2021-01-01" for d in days])
    M = np.array([C[n][sel] for n in names])
    print("\n######## 2. 每日盈虧相關系數（2021 起）########")
    print("        " + "".join(f"{n:>7s}" for n in names))
    for i, n in enumerate(names):
        print(f"  {n:5s} " + "".join(f"{np.corrcoef(M[i], M[j])[0, 1]:7.2f}" for j in range(len(names))))

    print("\n######## 3. 組合（每成份 0／1／2 份，只用 2021–2023 挑）########")
    best, allc = None, []
    for w in itertools.product(range(3), repeat=len(names)):
        if not any(w):
            continue
        x = sum(wi * C[n] for wi, n in zip(w, names))
        tr = metrics(x, days, *TRAIN)
        allc.append((w, tr))
        if tr["calmar"] >= 1 and (best is None or tr["sharpe"] > best[1]["sharpe"]):
            best = (w, tr)
    print(f"  {len(allc)} 組；訓練期 Sharpe ≥ 1 且回撤 ≤ 年化：{sum(1 for w, t in allc if t['sharpe'] >= 1 and t['calmar'] >= 1)} 組")
    picks = {"衡＋缺（各 1）": tuple(1 if n in ("衡", "缺") else 0 for n in names)}
    if best:
        picks["訓練期最佳"] = best[0]
    tr_sd = {n: metrics(C[n], days, *TRAIN) for n in names}
    vol = {n: np.std(C[n][np.array([TRAIN[0] <= d <= TRAIN[1] for d in days])]) for n in names}
    inv = {n: 1 / vol[n] if vol[n] > 0 else 0 for n in names}
    scale = 1 / min(v for v in inv.values() if v > 0)
    picks["等風險（四捨五入）"] = tuple(max(0, round(inv[n] * scale)) if tr_sd[n]["sharpe"] > 0 else 0 for n in names)
    for lab, w in picks.items():
        x = sum(wi * C[n] for wi, n in zip(w, names))
        mix = "＋".join(f"{n}×{wi}" for wi, n in zip(w, names) if wi)
        print(f"\n  {lab}：{mix}")
        print(f"    訓練 2021–2023 {fmt(metrics(x, days, *TRAIN))}")
        print(f"    測試 2024 起   {fmt(metrics(x, days, *TEST))}")
        print(f"    全期 2021 起   {fmt(metrics(x, days, '2021-01-01', '9999'))}")
        print("    逐年 " + "  ".join(f"{y} {sum(x[i] for i, d in enumerate(days) if d[:4] == str(y)):+,.0f}" for y in range(2021, 2027)))


if __name__ == "__main__":
    main()
