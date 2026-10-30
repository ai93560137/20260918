#!/usr/bin/env python3
"""跳空大跌 vs 盤中大跌——賣期權分組比較（stock_research/GAPDROP_OPTIONS_PREREG.md；登記 commit ccbc9f6e 之後寫）。

    python3 gapdrop_options.py --market us     # → research/gapdrop_options/us.json
    python3 gapdrop_options.py --market hk

母體＝bigdrop_options.Study.events（≤ −8%、收市 ≥ 5、≥ 315 日、21 日去重）；大跌日 t 用調整口徑開／高／低分組：
A 完全跳空 H_t < L_{t−1}；B 低開回補 O_t < L_{t−1} ≤ H_t；C 盤中大跌 O_t ≥ L_{t−1}。
超額基準、量度函數重用 island_reversal.py（v2：同日 PIT 成分股等權）。
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
from bigdrop_options import SPLITS  # noqa: E402
from island_reversal import Islands, summarize  # noqa: E402

OUT = ROOT / "research" / "gapdrop_options"
GROUPS = ("A", "B", "C")


class Gaps(Islands):
    def __init__(self, market: str):
        super().__init__(market)
        P = self.P
        self.op = {}
        for t in P.close:
            o = np.full(len(P.dates), np.nan)
            for r in md.load_ohlcv(t):
                i = P.di.get(r["Date"])
                if i is not None and r["Close"] and r["Close"] > 0 and r["Open"] and r["Open"] > 0:
                    o[i] = r["Open"] * r["AdjClose"] / r["Close"]
            self.op[t] = o

    def tag(self, ev: list[dict], lag: int) -> list[dict]:
        """加分組欄位；開／高／低缺漏的事件剔除（照報數目）。"""
        out = []
        for e in ev:
            t, i = e["t"], self.P.di[e["d"]] - lag
            O, Hh, L1 = self.op[t][i], self.hi[t][i], self.lo[t][i - 1]
            C0, C1 = self.P.adj[t][i - 1], self.P.adj[t][i]
            if not all(x == x and x > 0 for x in (O, Hh, L1, C0, C1)):
                continue
            e["grp"] = "A" if Hh < L1 else ("B" if O < L1 else "C")
            e["gap"] = L1 / O - 1 if O < L1 else 0.0
            e["overnight"] = math.log(O / C0) / math.log(C1 / C0) if C1 < C0 else float("nan")
            e["go_down"] = C1 <= O
            out.append(e)
        return out


def diff_t(a: list[dict], c: list[dict], k: str = "ex21") -> dict:
    """A − C：同月兩組各自平均後相減，按月 t。"""
    def by_month(ev):
        m: dict[tuple, list] = {}
        for e in ev:
            if e[k] == e[k]:
                m.setdefault((e["d"].year, e["d"].month), []).append(e[k])
        return {x: float(np.mean(v)) for x, v in m.items()}
    ma, mc = by_month(a), by_month(c)
    d = np.array([ma[x] - mc[x] for x in ma if x in mc])
    if len(d) < 3:
        return dict(months=len(d), diff_pct=float("nan"), t=float("nan"))
    return dict(months=len(d), diff_pct=float(d.mean() * 100), t=float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))))


def groups_block(ev: list[dict], cost: float) -> dict:
    g = {k: [e for e in ev if e["grp"] == k] for k in GROUPS}
    out = {"all": summarize(ev, cost), **{k: summarize(v, cost) for k, v in g.items()},
           "share": {k: len(v) / len(ev) for k, v in g.items()} if ev else {},
           "A_minus_C": {k: diff_t(g["A"], g["C"], k) for k in ("ex5", "ex21", "ex63")}}
    return out


def verdict(res_us: dict, res_hk: dict | None) -> dict:
    m = res_us["main"]
    dA = m["A_minus_C"]["ex21"]
    splits = res_us["splits"]
    same_split = lambda s: all(splits[n]["A_minus_C"]["ex21"]["diff_pct"] * s > 0 for n in splits)  # noqa: E731
    hk_dir = res_hk["main"]["A_minus_C"]["ex21"]["diff_pct"] if res_hk else float("nan")
    rho2_A = (m["A"].get("put95") or {}).get("rho2")
    rstar_C = (m["C"].get("put95") or {}).get("rho_star")
    h1 = rho2_A is not None and rho2_A >= 1.00 and dA["t"] <= -2 and same_split(-1)
    h2 = rstar_C is not None and rstar_C <= 0.85 and dA["t"] >= 2 and same_split(1)
    if h1:
        v = "H1 成立（跳空係有用過濾）" if hk_dir < 0 else "不確定（H1 美成立、港反方向）"
    elif h2:
        v = "H2 成立（盤中大跌較著數）" if hk_dir > 0 else "不確定（H2 美成立、港反方向）"
    else:
        v = "冇分別"
    return dict(verdict=v, us_rho2_A=rho2_A, us_rhostar_C=rstar_C, us_AmC_ex21=dA, hk_AmC_ex21_pct=hk_dir,
                splits_AmC={n: splits[n]["A_minus_C"]["ex21"] for n in splits})


def run(market: str) -> dict:
    G = Gaps(market)
    S, cost = G.S, G.S.cost
    res = dict(market=market, prereg_commit="ccbc9f6e", coverage=S.coverage)
    raw = S.events(-0.08, 0)
    ev = G.tag(G.add_excess(raw), 0)
    res["main"] = groups_block(ev, cost)
    res["main"]["n_raw"], res["main"]["n_tagged"] = len(raw), len(ev)
    res["main"]["by_year"] = {}
    for e in ev:
        y = res["main"]["by_year"].setdefault(str(e["d"].year), {k: 0 for k in GROUPS})
        y[e["grp"]] += 1
    res["splits"] = {n: groups_block([e for e in ev if a <= e["d"] <= b], cost) for n, a, b in SPLITS[market]}
    # 次分組（只報告）
    res["sub_overnight"] = {lab: summarize([e for e in ev if e["overnight"] == e["overnight"] and lo <= e["overnight"] < hi], cost)
                            for lab, lo, hi in (("<1/3", -1e9, 1 / 3), ("1/3–2/3", 1 / 3, 2 / 3), (">=2/3", 2 / 3, 1e9))}
    ab = [e for e in ev if e["grp"] in ("A", "B")]
    res["sub_gapsize"] = {lab: summarize([e for e in ab if lo <= e["gap"] < hi], cost)
                          for lab, lo, hi in (("<2%", 0, .02), ("2–5%", .02, .05), ("5–10%", .05, .10), (">=10%", .10, 9))}
    res["sub_gap_direction"] = {"低開高走": summarize([e for e in ab if not e["go_down"]], cost),
                                "低開低走": summarize([e for e in ab if e["go_down"]], cost)}
    # 敏感度
    res["sensitivity"] = {}
    for key, thr, lag in (("thr-6_lag0", -0.06, 0), ("thr-10_lag0", -0.10, 0), ("thr-8_lag1", -0.08, 1)):
        res["sensitivity"][key] = groups_block(G.tag(G.add_excess(S.events(thr, lag)), lag), cost)
    res["control_random"] = summarize(G.add_excess(S.events(-1.0, 0, random_ctrl=True)), cost)
    return res


def fmt(x, n=2):
    return "—" if x is None or x != x else f"{x:.{n}f}"


def show(res: dict) -> None:
    m = res["main"]
    print(f"== {res['market']}：母體 {m['n_raw']}、可分組 {m['n_tagged']}")
    for k in ("all",) + GROUPS:
        v = m[k]
        if not v.get("n"):
            print(k, "n=0"); continue
        print(f"{k:>3} n={v['n']:5d} ({m['share'].get(k, 1) * 100:4.1f}%) ex21 {fmt(v['ex21']['mean_pct'])}% t {fmt(v['ex21']['t'])} "
              f"ex63 {fmt(v['ex63']['mean_pct'])}% ret21均 {fmt(v['ret21']['mean'] * 100)}% ≤−10% {fmt(v['ret21']['le_m10'] * 100, 0)}% "
              f"RV比 {fmt(v['ratio']['median'])} put ρ* {fmt(v['put95']['rho_star'])}/ρ₂ {fmt(v['put95']['rho2'])} "
              f"call ρ* {fmt(v['call105']['rho_star'])}/ρ₂ {fmt(v['call105']['rho2'])}")
    print("A−C", {k: (fmt(d['diff_pct']), fmt(d['t'])) for k, d in m["A_minus_C"].items()})
    for n, s in res["splits"].items():
        print("分段", n, {k: s[k].get("n") for k in GROUPS}, "A−C ex21", fmt(s["A_minus_C"]["ex21"]["diff_pct"]), "t", fmt(s["A_minus_C"]["ex21"]["t"]),
              "put ρ* A/C", fmt((s["A"].get("put95") or {}).get("rho_star")), fmt((s["C"].get("put95") or {}).get("rho_star")))
    for name in ("sub_overnight", "sub_gapsize", "sub_gap_direction"):
        print(name, {k: (v.get("n"), fmt((v.get("ex21") or {}).get("mean_pct")), fmt((v.get("put95") or {}).get("rho_star"))) for k, v in res[name].items()})
    for k, s in res["sensitivity"].items():
        print("敏感度", k, {g: (s[g].get("n"), fmt((s[g].get("put95") or {}).get("rho_star"))) for g in GROUPS},
              "A−C", fmt(s["A_minus_C"]["ex21"]["diff_pct"]), "t", fmt(s["A_minus_C"]["ex21"]["t"]))
    c = res["control_random"]
    print("隨機", c["n"], "ex21", fmt(c["ex21"]["mean_pct"]), "put ρ*", fmt(c["put95"]["rho_star"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk"])
    ap.add_argument("--verdict", action="store_true", help="讀兩個 json 出判決")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.verdict:
        us = json.loads((OUT / "us.json").read_text(encoding="utf-8"))
        hk = json.loads((OUT / "hk.json").read_text(encoding="utf-8"))
        v = verdict(us, hk)
        (OUT / "verdict.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(v, ensure_ascii=False, indent=1))
        return
    res = run(a.market)
    (OUT / f"{a.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    show(res)


if __name__ == "__main__":
    main()
