#!/usr/bin/env python3
"""ETF 擇時：VCP 突破日之後持有指數 ETF（預先登記：stock_research/ETF_TIMING_BACKTEST.md，寫程式前已 commit；9 國一次、只測一次）。

    python3 etf_timing_backtest.py --selftest                  # 曝險聯集／重新起算的小例子（不用數據）
    python3 etf_timing_backtest.py --market hk --inspect 10    # 印預設格前 10 段曝險（不看績效）
    python3 etf_timing_backtest.py --market hk --random 200    # 正式：T1／MF／9 格／R
    python3 etf_timing_backtest.py --pool                      # 9 市場合併檢定 + 判決

- 突破日：當天 ≥ 1 檔 Minervini 樞紐點突破（開市 ≤ 樞紐點 × 1.05；台韓印漲停鎖死不算）
- T1：過去 W 日內有突破日 → 當天收市買 ETF，持有 H 個交易日（曝險 = 聯集，重新起算）；每段曝險一筆交易、進出各一邊成本；空倉記 0
- MF：t−1 收市 ETF > 50 日線且 > 200 日線 → t 日持有
- R：突破日換成同樣數目、從大市過濾通過的日子隨機抽（200 次）
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import newhigh_backtest as nb  # noqa: E402
import oos_backtest as ob  # noqa: E402
import vcp_backtest as vb  # noqa: E402
import vcp_minervini as vm  # noqa: E402
from discipline_backtest import GROUPS, MARKETS, minervini_suspects, split_abn, diff_series  # noqa: E402

GRID = [(h, w) for h in (42, 63, 126) for w in (1, 5, 10)]
DEFAULT = (63, 5)
OUT = ROOT / "research" / "etf_timing"


def key(h: int, w: int) -> str:
    return f"持有{h}日 W{w}"


def exposure_from_days(days: np.ndarray, D: int, h: int, w: int, start_j: int) -> np.ndarray:
    """突破日 → 訊號日（過去 w 日內有突破）→ 曝險 [j+1, j+h] 的聯集（布林，長度 D）。"""
    br = np.zeros(D, dtype=bool)
    br[days] = True
    sig = np.zeros(D, dtype=bool)
    for k in range(w):
        sig[k:] |= br[:D - k]
    sig[:start_j] = False
    e = np.zeros(D + 1, dtype=np.int32)
    for j in np.nonzero(sig)[0]:
        e[j + 1] += 1
        e[min(j + h + 1, D)] -= 1
    return np.cumsum(e[:D]) > 0


def episodes(e: np.ndarray) -> list[tuple[int, int]]:
    """連續曝險段 [a, b]（含）。"""
    out, a = [], None
    for t, x in enumerate(e):
        if x and a is None:
            a = t
        if not x and a is not None:
            out.append((a, t - 1))
            a = None
    if a is not None:
        out.append((a, len(e) - 1))
    return out


class ETFTiming:
    def __init__(self, mk: str):
        self.mk = mk
        self.vf = vf = vb.VCPData(mk, full=True, scan=False)
        self.m = m = vf.m
        self.mv = mv = vm.Minervini(mk, minervini_suspects(mk), v=vf)
        locked = ob.locked_matrix(m, mk)
        days = {j for (s, p, j, pivot, o, _) in mv.setups if o <= pivot * (1 + vm.DEFAULT[1]) and not locked[s, j] and j >= m.start_j}
        self.days = np.array(sorted(days), dtype=int)
        self.D = len(m.cal)
        self.cost = nb.MARKETS[mk]["cost"]
        self.mkt_prev = np.r_[False, mv.mkt_ok[:-1]]          # t 日持有的條件：t−1 收市 ETF > 50 & 200 日線
        self.mkt_prev[:m.start_j] = False
        print(f"[{mk}] 突破日 {len(self.days)} 天（樣本 {self.D - m.start_j} 個交易日；大市過濾通過 {int(self.mkt_prev.sum())} 天）", file=sys.stderr)

    def daily(self, e: np.ndarray) -> tuple[np.ndarray, list[float], list[tuple[int, int]]]:
        m = self.m
        r = np.where(e, m.etf_ret, 0.0)
        eps = episodes(e)
        tr = []
        for a, b in eps:
            r[a] -= self.cost
            r[b] -= self.cost
            tr.append(float(np.prod(1 + m.etf_ret[a:b + 1]) * (1 - self.cost) ** 2 - 1))
        return r, tr, eps

    def stats(self, e: np.ndarray) -> tuple[dict, dict, np.ndarray]:
        m = self.m
        daily, tr, eps = self.daily(e)
        st = ob.summary(m, daily, tr, [b - a + 1 for a, b in eps], len(eps))
        mo, me = m.monthly(daily), m.monthly(m.etf_ret)
        yrs = (self.D - m.start_j) / 252
        st["exposure"] = float(e[m.start_j:].mean())
        st["trades_per_year"] = len(eps) / yrs
        return st, ob.abn(m, daily), daily

    def random_days(self, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        pool = np.nonzero(self.mkt_prev)[0]
        return np.sort(rng.choice(pool, size=min(len(self.days), len(pool)), replace=False))

    def inspect(self, n: int) -> None:
        m = self.m
        e = exposure_from_days(self.days, self.D, *DEFAULT, m.start_j)
        _, tr, eps = self.daily(e)
        for (a, b), x in list(zip(eps, tr))[:n]:
            trig = [m.cal[j].isoformat() for j in self.days if a - DEFAULT[1] <= j <= b]
            print(f"曝險 {m.cal[a]} ~ {m.cal[b]}（{b - a + 1} 日）  觸發突破日 {trig[:4]}{'…' if len(trig) > 4 else ''}  筆報酬 {x:+.2%}")


def selftest() -> None:
    D, t = 300, 20
    e = exposure_from_days(np.array([t, t + 10, t + 80]), D, 63, 1, 0)
    eps = episodes(e)
    exp = [(t + 1, t + 73), (t + 81, t + 143)]
    assert eps == exp, (eps, exp)
    e5 = exposure_from_days(np.array([t]), D, 63, 5, 0)          # W=5：t..t+4 都是訊號日 → 曝險 [t+1, t+67]
    assert episodes(e5) == [(t + 1, t + 67)], episodes(e5)
    print("selftest ok:", eps, episodes(e5))


def run_market(mk: str, n_random: int) -> None:
    x = ETFTiming(mk)
    m = x.m
    res = {"market": mk, "n_breakout_days": int(len(x.days)), "cells": {}, "abn": {}, "monthly": {}}
    for h, w in GRID:
        st, ab, daily = x.stats(exposure_from_days(x.days, x.D, h, w, m.start_j))
        k = key(h, w)
        res["cells"][k], res["abn"][k] = st, ab
        if (h, w) == DEFAULT:
            res["cells"]["T1"], res["abn"]["T1"] = st, ab
            res["monthly"]["T1"] = {str(d.date())[:7]: float(v) for d, v in m.monthly(daily).items()}
    st, ab, daily = x.stats(x.mkt_prev.copy())
    res["cells"]["MF"], res["abn"]["MF"] = st, ab
    res["monthly"]["MF"] = {str(d.date())[:7]: float(v) for d, v in m.monthly(daily).items()}
    res["monthly"]["ETF"] = {str(d.date())[:7]: float(v) for d, v in m.monthly(m.etf_ret).items()}
    rnd = [ob.abn(m, x.daily(exposure_from_days(x.random_days(sd), x.D, *DEFAULT, m.start_j))[0]) for sd in range(n_random)]
    if rnd:
        ts = sorted(ob.tstat(pd.Series(v)) for v in rnd)
        real = res["cells"]["T1"]["alpha_t"]
        res["random"] = {"n": len(ts), "median": ts[len(ts) // 2], "p95": ts[int(0.95 * len(ts))], "real_pctl": sum(v < real for v in ts) / len(ts)}
    for k in ("T1", "MF"):
        st = res["cells"][k]
        print(f"[{mk}] {k:3} 交易 {st['trades']:4d}（每年 {st['trades_per_year']:.1f}）  曝險 {st['exposure']:.0%}  alpha t {st['alpha_t']:5.2f}  beta {st['beta']:.2f}  "
              f"前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  MDD {st['mdd']:.0%}（ETF {st['mdd_etf'] if 'mdd_etf' in st else float('nan'):.0%}）  "
              f"勝率 {st['win']:.0%}  平均贏 {st['avg_win']:+.1%}  平均輸 {st['avg_loss']:+.1%}  RRR {st['rrr']:.2f}  獲利因子 {st['profit_factor']:.2f}  持有 {st['avg_hold']:.0f} 日", file=sys.stderr)
    for h, w in GRID:
        c = res["cells"][key(h, w)]
        print(f"[{mk}] {key(h, w)}  交易 {c['trades']:4d}  曝險 {c['exposure']:.0%}  alpha t {c['alpha_t']:5.2f}  勝率 {c['win']:.0%}  PF {c['profit_factor']:.2f}", file=sys.stderr)
    if rnd:
        q = res["random"]
        print(f"[{mk}] 隨機對照 {q['n']} 次：中位 {q['median']:.2f}、p95 {q['p95']:.2f}；T1 在第 {q['real_pctl']:.0%} 百分位", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def pool_all() -> None:
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in MARKETS}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in MARKETS}

    def pt(k, mks=MARKETS):
        return ob.tstat(ob.pooled([R[mk]["abn"][k] for mk in mks]))

    out = {"pooled": {"T1": pt("T1"), "MF": pt("MF")}, "groups": {g: {"T1": pt("T1", mks), "MF": pt("MF", mks)} for g, mks in GROUPS.items()},
           "grid": {key(h, w): pt(key(h, w)) for h, w in GRID}, "per_market": {}}
    out["pooled"]["T1_pre"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["abn"]["T1"])[0] for mk in MARKETS]))
    out["pooled"]["T1_post"] = ob.tstat(ob.pooled([split_abn(mk, R[mk]["abn"]["T1"])[1] for mk in MARKETS]))
    out["diff"] = {"T1-MF (月報酬差)": ob.tstat(ob.pooled([diff_series(R[mk]["monthly"]["T1"], R[mk]["monthly"]["MF"]) for mk in MARKETS])),
                   "T1-MF (超額差)": ob.tstat(ob.pooled([diff_series(R[mk]["abn"]["T1"], R[mk]["abn"]["MF"]) for mk in MARKETS]))}
    n = min(len(RN[mk]) for mk in MARKETS)
    rt = sorted(ob.tstat(ob.pooled([RN[mk][i] for mk in MARKETS])) for i in range(n))
    real = out["pooled"]["T1"]
    out["random"] = {"n": n, "median": rt[n // 2], "p95": rt[int(0.95 * n)], "real_pctl": sum(v < real for v in rt) / n}
    # A：全部交易合併
    trs = []
    for mk in MARKETS:
        c = R[mk]["cells"]["T1"]
        trs.append((c["trades"], c["win"], c["avg_win"], c["avg_loss"]))
    for mk in MARKETS:
        c = R[mk]["cells"]
        out["per_market"][mk] = {k: {x: c[k][x] for x in ("alpha_t", "beta", "t_pre", "t_post", "cagr", "cagr_etf", "cum", "cum_etf", "mdd",
                                                           "trades", "trades_per_year", "exposure", "win", "avg_win", "avg_loss", "rrr",
                                                           "profit_factor", "avg_hold")} for k in ("T1", "MF")}
        out["per_market"][mk]["random"] = R[mk].get("random")
        out["per_market"][mk]["n_breakout_days"] = R[mk]["n_breakout_days"]
        out["per_market"][mk]["grid_ge15"] = sum(c[key(h, w)]["alpha_t"] >= 1.5 for h, w in GRID)
    n_tr = sum(t[0] for t in trs)
    n_w = sum(t[0] * t[1] for t in trs)
    aw = sum(t[0] * t[1] * t[2] for t in trs) / max(n_w, 1)
    al = sum(t[0] * (1 - t[1]) * t[3] for t in trs) / max(n_tr - n_w, 1)
    out["A"] = {"n": n_tr, "win": n_w / n_tr, "avg_win": aw, "avg_loss": al, "rrr": aw / -al if al < 0 else float("nan"),
                "profit_factor": (n_w * aw) / -((n_tr - n_w) * al) if al < 0 else float("nan")}
    pos = sum(R[mk]["cells"]["T1"]["alpha_t"] > 0 for mk in MARKETS)
    neg = sum(R[mk]["cells"]["T1"]["alpha_t"] < 0 for mk in MARKETS)
    grid_ok = sum(v >= 1.5 for v in out["grid"].values())
    min_tr = min(R[mk]["cells"]["T1"]["trades"] for mk in MARKETS)
    A = {"A1 合併 RRR ≥ 1.0": out["A"]["rrr"] >= 1.0, "A2 獲利因子 ≥ 1.5": out["A"]["profit_factor"] >= 1.5, "A3 勝率 ≥ 55%": out["A"]["win"] >= 0.55}
    B = {"B1 合併 alpha t ≥ 2.5": real >= 2.5, "B2 ≥ 6/9 市場 alpha t > 0": pos >= 6, "B3 隨機對照 ≥ 95%": out["random"]["real_pctl"] >= 0.95,
         "B4 鄰域 ≥ 6/9 格合併 ≥ 1.5": grid_ok >= 6, "B5 前後段合併都 > 0": out["pooled"]["T1_pre"] > 0 and out["pooled"]["T1_post"] > 0,
         "B6 T1 − MF 月報酬差合併 t ≥ 1.5": out["diff"]["T1-MF (月報酬差)"] >= 1.5, "B7 每市場 ≥ 30 筆": min_tr >= 30}
    if all(A.values()) and all(B.values()):
        v = "🔍 有希望未證實（A、B 全過）"
    elif real < 1.0 or neg >= 4:
        v = "☠️"
    elif all(B[k] for k in list(B)[:5]) and not B["B6 T1 − MF 月報酬差合併 t ≥ 1.5"]:
        v = "只是 MA 過濾（B1–B5 過、B6 不過）"
    else:
        v = "不確定"
    out["conditions"], out["verdict"] = {**A, **B}, v
    out["summary"] = {"pos_markets": pos, "neg_markets": neg, "grid_ge15": grid_ok, "min_trades": min_tr}
    (OUT / "pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    a = out["A"]
    print(f"A：{a['n']} 筆  勝率 {a['win']:.0%}  平均贏 {a['avg_win']:+.1%}  平均輸 {a['avg_loss']:+.1%}  RRR {a['rrr']:.2f}  獲利因子 {a['profit_factor']:.2f}", file=sys.stderr)
    print(f"T1 合併 alpha t {real:.2f}（前 {out['pooled']['T1_pre']:.2f}／後 {out['pooled']['T1_post']:.2f}）  MF 合併 {out['pooled']['MF']:.2f}  "
          f"T1−MF 月報酬差 t {out['diff']['T1-MF (月報酬差)']:.2f}（超額差 {out['diff']['T1-MF (超額差)']:.2f}）  隨機第 {out['random']['real_pctl']:.0%} 百分位（中位 {out['random']['median']:.2f}、p95 {out['random']['p95']:.2f}）  "
          f"alpha>0 {pos}/9  鄰域 {grid_ok}/9  最少交易 {min_tr}", file=sys.stderr)
    for g, r in out["groups"].items():
        print(f"{g}：T1 {r['T1']:.2f}  MF {r['MF']:.2f}", file=sys.stderr)
    for k, ok in out["conditions"].items():
        print(f"  {'✓' if ok else '✗'} {k}", file=sys.stderr)
    print(f"→ {v}", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--inspect", type=int, default=0)
    a.add_argument("--selftest", action="store_true")
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.selftest:
        selftest()
    elif args.pool:
        pool_all()
    elif args.market and args.inspect:
        ETFTiming(args.market).inspect(args.inspect)
    elif args.market:
        run_market(args.market, args.random)
    else:
        a.error("要給 --market 或 --pool")


if __name__ == "__main__":
    main()
