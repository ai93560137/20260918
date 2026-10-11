#!/usr/bin/env python3
"""HTF 曲線擬合版（預先登記：stock_research/HTF_CURVEFIT.md；使用者 2026-10-11 指示）。

    python3 htf_curvefit.py --market hk            # 單市場：隨機 400 組 + 座標上升 + 前段選參 + 隨機對照
    python3 htf_curvefit.py --common               # 四市場共用一組參數（讀各市場快取的候選）
    python3 htf_curvefit.py --market hk --time 3   # 只量 3 組評估的耗時

引擎 htf_backtest.HTF 原封不動；本檔只把寫死的常數（G、D、量縮、旗面長度、20 日線、動能百分位、大市、追價、ADR 下限、
停損倍數、賣一半日、移動均線、最長持有、加權）變成參數。輸出 research/htf_curvefit/。
"""
import argparse
import json
import math
import pickle
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import htf_backtest as H  # noqa: E402

OUT = ROOT / "research" / "htf_curvefit"
SEED = 20261011
N_RANDOM = 400
MIN_TRADES = 100
SPACE = {
    "g": [0.15, 0.25, 0.40, 0.60, 1.00],
    "d": [0.10, 0.15, 0.20, 0.25, 0.35],
    "vol": [0.6, 0.8, 1.0, None],
    "flag_max": [10, 20, 30, 40],
    "ma20": [True, False],
    "mom_q": [97, 98, 99],
    "mkt": [True, False],
    "chase": [0.02, 0.05, 0.10],
    "adr_min": [0.0, 0.03, 0.05],
    "stop": [0.5, 1.0, 1.5],
    "partial": [None, 3, 5],
    "trail": ["ma10", "ma20", "ma50"],
    "hold": [60, 252],
    "risk": [False, True],
}
DEFAULT = {"g": 0.25, "d": 0.20, "vol": 0.8, "flag_max": 30, "ma20": True, "mom_q": 98, "mkt": True, "chase": 0.05,
           "adr_min": 0.0, "stop": 1.0, "partial": 3, "trail": "ma10", "hold": 252, "risk": False}
# 註：原預設 G=0.30 不在搜尋格內，0.25 是最近一格；原判決 G 不影響結果（三個 G 差 < 0.2，見 HTF_BACKTEST.md）


def key(p: dict) -> str:
    return json.dumps(p, sort_keys=True)


class CF(H.HTF):
    def scan(self) -> None:
        """同原 scan，但用搜尋空間最寬邊界預篩，並把量縮比例、20 日線、旗面長度存下來給 trades 過濾。"""
        m = self.m
        g_min, d_max, fmax = min(SPACE["g"]), max(SPACE["d"]), max(SPACE["flag_max"])
        self.setups = []
        for s, rw in self.raw.items():
            jarr, high, low, vol, adj, opn = (rw[k] for k in ("jarr", "high", "low", "vol", "adj", "open"))
            cand = np.nonzero((jarr[1:] >= m.start_j) & (jarr[:-1] >= 0))[0] + 1
            if len(cand) == 0:
                continue
            cand = cand[self.mom_ok[97][s, jarr[cand - 1]] & m.member[s, jarr[cand - 1]]]
            for p in cand:
                if p < 2 * H.POLE_LOOK + 1:
                    continue
                win = high[p - H.POLE_LOOK:p]
                k = int(np.argmax(win))
                ptop = p - H.POLE_LOOK + k
                P = high[ptop]
                flag_len = (p - 1) - ptop
                if not (H.FLAG_MIN <= flag_len <= fmax) or not high[p] > P:
                    continue
                pole_low = low[ptop - H.POLE_LOOK:ptop + 1].min()
                G = P / pole_low - 1 if pole_low > 0 else 0.0
                Dflag = (P - low[ptop + 1:p].min()) / P
                if G < g_min or Dflag > d_max:
                    continue
                volp = vol[ptop - 19:ptop + 1].mean()
                volf = vol[ptop + 1:p].mean()
                vr = volf / volp if volp > 0 else math.inf
                adr = rw["adr"][p - 1]
                if not (adr == adr and adr > 0):
                    continue
                o = opn[p] if opn[p] == opn[p] and opn[p] > 0 else P
                self.setups.append({"s": s, "p": p, "j": int(jarr[p]), "pivot": P, "open": o, "G": G, "D": Dflag,
                                    "flag_len": int(flag_len), "adr": adr, "vr": vr,
                                    "ma20ok": bool(adj[p - 1] > rw["ma20"][p - 1]), "mkt": bool(self.mkt_ok[jarr[p - 1]])})
        self.setups.sort(key=lambda x: (x["j"], x["s"]))
        self.setup_days = {}
        for st in self.setups:
            self.setup_days.setdefault(st["j"], set()).add(st["s"])
        print(f"[{self.market}] 最寬邊界候選 {len(self.setups)}", file=sys.stderr)

    def sim(self, s: int, p: int, fill: float, adr: float, c: dict) -> list:
        """同原 simulate，停損倍數、賣一半日、移動均線、最長持有可調。"""
        rw = self.raw[s]
        high, low, close, opn, adj, ma = (rw[k] for k in ("high", "low", "close", "open", "adj", c["trail"]))
        n = len(close)
        stop = fill * (1 - c["stop"] * adr)
        o0 = opn[p] if opn[p] == opn[p] and opn[p] > 0 else fill
        pre_fill_low = o0 < fill and low[p] == o0
        if low[p] <= stop and not pre_fill_low:
            return [(p, stop, False, 1.0)]
        stop = max(stop, low[p])
        legs, units, exit_next_open = [], 1.0, False
        pd_ = c["partial"]
        start_trail = p + (pd_ if pd_ else 1)
        last = min(n, p + c["hold"] + 1)
        for k in range(p + 1, last):
            o = opn[k] if opn[k] == opn[k] and opn[k] > 0 else close[k]
            if exit_next_open:
                legs.append((k, o, False, units))
                return legs
            if low[k] <= stop:
                legs.append((k, min(o, stop), False, units))
                return legs
            if pd_ and k == p + pd_:
                legs.append((k, close[k], True, 0.5))
                units = 0.5
                stop = max(stop, fill)
            if k >= start_trail and ma[k] == ma[k] and adj[k] < ma[k]:
                exit_next_open = True
        k = last - 1
        legs.append((k, close[k], True, units))
        return legs

    def ctrades(self, c: dict, random_seed: int | None = None) -> list[dict]:
        m = self.m
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        out, busy = [], {}
        mq = self.mom_ok[c["mom_q"]]
        for st in self.setups:
            s, p, j, P, o = st["s"], st["p"], st["j"], st["pivot"], st["open"]
            if st["G"] < c["g"] or st["D"] > c["d"] or st["adr"] < c["adr_min"] or st["flag_len"] > c["flag_max"]:
                continue
            if c["vol"] is not None and not st["vr"] < c["vol"]:
                continue
            if c["ma20"] and not st["ma20ok"]:
                continue
            if not mq[s, j - 1]:
                continue
            if c["mkt"] and not st["mkt"]:
                continue
            rw = self.raw[s]
            if rng is None:
                if o > P * (1 + c["chase"]) or self.locked[s, j] or p <= busy.get(s, -1):
                    continue
                fill = max(o, P)
                legs = self.sim(s, p, fill, st["adr"], c)
                busy[s] = legs[-1][0]
                out.append(self._trade(s, p, fill, legs, st))
            else:
                pool = np.nonzero(mq[:, j - 1] & m.member[:, j - 1])[0]
                pool = pool[~np.isin(pool, list(self.setup_days[j]))]
                if len(pool) == 0:
                    continue
                r = int(pool[rng.integers(len(pool))])
                rr = self.raw[r]
                pr = rr["dates"].get(m.cal[j])
                if pr is None or pr < 1 or self.locked[r, j]:
                    continue
                o_r, adr_r = rr["open"][pr], rr["adr"][pr - 1]
                if not (o_r == o_r and o_r > 0 and adr_r == adr_r and adr_r > 0):
                    continue
                legs = self.sim(r, pr, o_r, adr_r, c)
                out.append(self._trade(r, pr, o_r, legs, {"adr": adr_r}))
        return out

    def score(self, c: dict, pre_only: bool = False) -> dict:
        tr = self.ctrades(c)
        if len(tr) < MIN_TRADES:
            return {"alpha_t": float("nan"), "trades": len(tr)}
        if not pre_only:
            ev = self.evaluate(tr, c["risk"])
            ev.pop("by_year", None)
            ev.pop("by_year_etf", None)
            return ev
        m = self.m
        daily, _, _ = self.daily(tr, c["risk"])
        mo, me = m.monthly(daily), m.monthly(m.etf_ret)
        sp = pd.Timestamp(m.cfg["split"])
        return {"alpha_t": m.capm(mo[mo.index < sp], me[me.index < sp])[2], "trades": len(tr)}


def rand_configs(n: int, seed: int) -> list[dict]:
    rnd = random.Random(seed)
    return [{k: rnd.choice(v) for k, v in SPACE.items()} for _ in range(n)]


def climb(fn, start: dict, cache: dict) -> tuple[dict, float]:
    """座標上升：每次改一個參數，有改善就接受，直到一輪沒有改善。fn(c) → 分數（nan = 作廢）。"""
    def f(c):
        k = key(c)
        if k not in cache:
            cache[k] = fn(c)
        v = cache[k]
        return -math.inf if v != v else v
    best, bv = dict(start), f(start)
    improved = True
    while improved:
        improved = False
        for p, vals in SPACE.items():
            for v in vals:
                if v == best[p]:
                    continue
                c = dict(best, **{p: v})
                x = f(c)
                if x > bv + 1e-9:
                    best, bv, improved = c, x, True
    return best, bv


def search(fn, label: str, log=print) -> dict:
    cache = {}
    cfgs = rand_configs(N_RANDOM, SEED)
    t0 = time.time()
    for i, c in enumerate(cfgs):
        k = key(c)
        if k not in cache:
            cache[k] = fn(c)
        if (i + 1) % 50 == 0:
            log(f"  [{label}] 隨機 {i + 1}/{N_RANDOM}，{time.time() - t0:.0f} 秒")
    ranked = sorted(((v, k) for k, v in cache.items() if v == v), reverse=True)
    starts = [json.loads(k) for _, k in ranked[:5]]
    results = []
    for st in starts:
        b, bv = climb(fn, st, cache)
        results.append((bv, b))
        log(f"  [{label}] 起點 {cache[key(st)]:.2f} → 上升到 {bv:.2f}")
    results.sort(key=lambda x: -x[0])
    return {"best": results[0][1], "best_score": results[0][0], "n_evaluated": len(cache),
            "random_top5": [(v, json.loads(k)) for v, k in ranked[:5]],
            "random_median": float(np.median([v for v, _ in ranked])) if ranked else float("nan")}


def run_market(mk: str, time_n: int = 0) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    x = CF(mk)
    print(f"[{mk}] 載入 {time.time() - t0:.0f} 秒", file=sys.stderr)
    log = lambda s: print(s, file=sys.stderr, flush=True)  # noqa: E731
    if time_n:
        for c in rand_configs(time_n, SEED):
            t1 = time.time()
            r = x.score(c)
            log(f"  評估 {time.time() - t1:.1f} 秒，筆數 {r['trades']}，alpha t {r['alpha_t']:.2f}")
        return
    full_cache = {}

    def full_t(c):
        k = key(c)
        if k not in full_cache:
            full_cache[k] = x.score(c)
        return full_cache[k]["alpha_t"]

    res = search(full_t, f"{mk} 全期", log)
    best = res["best"]
    best_ev = x.score(best)
    default_ev = x.score(DEFAULT)
    # 參考：前段選參、後段驗證
    pre = search(lambda c: x.score(c, pre_only=True)["alpha_t"], f"{mk} 前段", log)
    pre_best_ev = x.score(pre["best"])
    # 參考：最佳組隨機對照 50 次
    real = best_ev["alpha_t"]
    rnd = []
    for i in range(50):
        tr = x.ctrades(best, random_seed=i)
        if len(tr) >= 30:
            ev = x.evaluate(tr, best["risk"])
            rnd.append(ev["alpha_t"])
    pct = sum(v < real for v in rnd) / len(rnd) if rnd else float("nan")
    # 鄰域：最佳組每個參數改一格的分數
    nb_scores = {}
    for p, vals in SPACE.items():
        i = vals.index(best[p])
        for jj in (i - 1, i + 1):
            if 0 <= jj < len(vals):
                c = dict(best, **{p: vals[jj]})
                nb_scores[f"{p}={vals[jj]}"] = full_t(c)
    out = {"market": mk, "search": res, "best_eval": best_ev, "default_eval": default_ev,
           "pre_select": {"best": pre["best"], "pre_t": pre["best_score"], "full_eval": pre_best_ev},
           "random_control": {"n": len(rnd), "pctl": pct, "median": float(np.median(rnd)) if rnd else None,
                              "p95": float(np.percentile(rnd, 95)) if rnd else None},
           "neighbours": nb_scores}
    (OUT / f"{mk}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    # 給共用組搜尋用：快取候選與數據
    with open(OUT / f"{mk}_engine.pkl", "wb") as f:
        pickle.dump(x, f)
    log(f"[{mk}] 最佳 alpha t {real:.2f}（預設 {default_ev['alpha_t']:.2f}）；前段選參 → 後段 t {pre_best_ev['t_post']:.2f}；"
        f"隨機對照第 {pct:.0%}；共評估 {res['n_evaluated'] + pre['n_evaluated']} 組，{time.time() - t0:.0f} 秒")


def run_common() -> None:
    log = lambda s: print(s, file=sys.stderr, flush=True)  # noqa: E731
    xs = {}
    for mk in H.MARKETS:
        with open(OUT / f"{mk}_engine.pkl", "rb") as f:
            xs[mk] = pickle.load(f)
    abn_cache = {}

    def abn_of(mk, c):
        k = mk + key(c)
        if k not in abn_cache:
            x = xs[mk]
            tr = x.ctrades(c)
            abn_cache[k] = None if len(tr) < MIN_TRADES else x.abn(x.daily(tr, c["risk"])[0])
        return abn_cache[k]

    def pooled_t(c):
        a = [abn_of(mk, c) for mk in H.MARKETS]
        if any(v is None for v in a):
            return float("nan")
        return H.tstat_series(H.pooled(a))

    res = search(pooled_t, "四市場共用", log)
    best = res["best"]
    per = {mk: xs[mk].score(best) for mk in H.MARKETS}
    for v in per.values():
        v.pop("by_year", None)
    out = {"search": res, "best": best, "pooled_t": res["best_score"], "per_market": per,
           "default_pooled_t": pooled_t(DEFAULT)}
    (OUT / "common.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    log(f"共用組合併 alpha t {res['best_score']:.2f}（預設 {out['default_pooled_t']:.2f}）")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=H.MARKETS)
    a.add_argument("--common", action="store_true")
    a.add_argument("--time", type=int, default=0)
    args = a.parse_args()
    if args.common:
        run_common()
    else:
        run_market(args.market, args.time)


if __name__ == "__main__":
    main()
