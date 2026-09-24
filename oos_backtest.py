#!/usr/bin/env python3
"""樣本外驗證（預先登記：stock_research/OOS_VALIDATION.md，寫程式與抓數據之前已 commit；只測一次）。

    python3 oos_backtest.py --market tw --trades-only     # H5a 預設格逐筆明細抽 300 筆（給 verify_trades，不算績效）
    python3 oos_backtest.py --market tw --random 200      # 正式：H5a（主要）＋ Minervini、PPP 逆下半身（次要）
    python3 oos_backtest.py --pool                        # 三個市場合併檢定 + 判決
    # 第二輪（第三部分：加拿大、印度、新加坡，只驗證 Minervini）
    python3 oos_backtest.py --market ca --only minervini --trades-only   # 全部 Minervini 交易明細（給 verify_trades）
    python3 oos_backtest.py --market ca --only minervini --random 200
    python3 oos_backtest.py --pool --round 2

規格全部沿用原判決的預設格（newhigh_backtest H5a／vcp_minervini／aiba_ppp），只換宇宙與成本：
- H5a：成交額前 N（台 150／韓 200／澳 200）代替指數成分股；Minervini／PPP：全市場前 N（台 500／韓 700／澳 500）
- 台灣、韓國：入場日「漲停鎖死」（開 = 高 = 低 = 收 且較前收 ≥ 漲停 − 0.5%）視為買不到，跳過
"""
import argparse
import gzip
import json
import random
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import aiba_ppp as ap  # noqa: E402
import newhigh_backtest as nb  # noqa: E402
import vcp_backtest as vb  # noqa: E402
import vcp_minervini as vm  # noqa: E402
from expectancy_report import stats  # noqa: E402

MARKETS = ("tw", "kr", "au")               # 第一輪
ROUND2 = ("ca", "in", "sg")                 # 第二輪（只驗證 Minervini）
H5A_N = {"tw": 150, "kr": 200, "au": 200}
OUT = ROOT / "research" / "oos"
KEYS = ("H5a", "Minervini", "PPP")


def limit_up(mk: str, d: date) -> float | None:
    if mk == "tw":
        return 0.07 if d < date(2015, 6, 1) else 0.10
    if mk == "kr":
        return 0.15 if d < date(2015, 6, 15) else 0.30
    if mk == "in":            # 個股漲跌幅上限 5／10／20%：取最低一級（登記：≥ +4.5% 且開高低收相同 = 買不到）
        return 0.05
    return None


def locked_matrix(m, mk: str) -> np.ndarray:
    """[股票, 日曆日] = 當天漲停鎖死（買不到）。"""
    L = np.zeros(m.adj.shape, dtype=bool)
    if limit_up(mk, date(2020, 1, 1)) is None:
        return L
    for s, t in enumerate(m.tickers):
        rows = m.loader(t)
        for i in range(1, len(rows)):
            r, pc = rows[i], rows[i - 1]["Close"]
            j = m.ci.get(r["Date"])
            if j is None or not pc:
                continue
            o, h, lo, c = r["Open"], r["High"], r["Low"], r["Close"]
            if o == h == lo == c and c / pc - 1 >= limit_up(mk, r["Date"]) - 0.005:
                L[s, j] = True
    return L


def drop_locked(m, ev: np.ndarray, locked: np.ndarray) -> np.ndarray:
    D = len(m.cal)
    ev = ev.copy()
    for s, e in zip(*np.nonzero(ev)):
        a = m.next_px[s, e + 1] if e + 1 < D else D
        if a < D and locked[s, a]:
            ev[s, e] = False
    return ev


def abn(m, daily: np.ndarray) -> dict:
    """每月超額（CAPM alpha + 殘差 = 組合 − beta × ETF）。"""
    mo, me = m.monthly(daily), m.monthly(m.etf_ret)
    _, b, _ = m.capm(mo, me)
    x = (mo - b * me).dropna()
    return {str(k.date())[:7]: float(v) for k, v in x.items()}


def summary(m, daily, tr, holds, trades_n) -> dict:
    st = stats(m, daily, tr, holds)
    mo, me = m.monthly(daily), m.monthly(m.etf_ret)
    a, b, t = m.capm(mo, me)
    sp = pd.Timestamp(m.cfg["split"])
    st.update({"alpha_t": t, "beta": b,
               "t_pre": m.capm(mo[mo.index < sp], me[me.index < sp])[2],
               "t_post": m.capm(mo[mo.index >= sp], me[me.index >= sp])[2], "n_trades_portfolio": trades_n})
    return st


def h5a_random(m, ev, locked, seed) -> list:
    """同日宇宙內、在 200 日線上、當天不是訊號的股票隨機挑一檔，t+1 開市買（漲停鎖死同樣跳過），X2 出場。"""
    rng = np.random.default_rng(seed)
    D = len(m.cal)
    out, cache = [], {}
    for s, e in zip(*np.nonzero(ev)):
        if e + 1 >= D:
            continue
        if e not in cache:
            cache[e] = np.nonzero(m.member[:, e] & m.above[:, e] & ~ev[:, e])[0]
        if len(cache[e]) == 0:
            continue
        r = int(cache[e][rng.integers(len(cache[e]))])
        a = m.next_px[r, e + 1]
        if a >= D or locked[r, a]:
            continue
        ex, op = m.exit_index(r, a, "x2")
        if ex >= a:
            out.append((r, int(a), ex, op))
    return out


def minervini_detail(mv, trs) -> list[dict]:
    """Minervini 逐筆原始價（訊號日 = 突破日前一日；給 verify_trades 內部一致性）。"""
    m, out, rc = mv.m, [], {}
    for t in trs:
        tk = m.tickers[t["s"]]
        rw = mv.v.raw[t["s"]]
        dl = list(rw["dates"])
        p = rw["dates"][m.cal[t["a"]]]
        R = rc.setdefault(tk, {r["Date"]: r for r in m.loader(tk)})
        rs, ra = R.get(dl[p - 1]), R.get(dl[p])
        out.append({"ticker": tk, "signal": dl[p - 1].isoformat(), "entry": dl[p].isoformat(), "exit": m.cal[t["b"]].isoformat(),
                    "exit_at_open": not t["at_close"], "signal_close": rs["Close"] if rs else None,
                    "signal_volume": rs["Volume"] if rs else None, "entry_open": ra["Open"] if ra else None, "exit_px": None})
    return out


def run_minervini_only(mk: str, n_random: int, trades_only: bool) -> None:
    """第二輪：只跑 Minervini（凍結預設格）；另算「去掉最賺 10 筆」的每月超額（登記第 5 條）。"""
    sus_p = OUT / f"{mk}_suspect.json"
    sus = {tuple(x) for x in json.loads(sus_p.read_text())} if sus_p.exists() and not trades_only else set()
    vf = vb.VCPData(mk, full=True, scan=False)
    lk = locked_matrix(vf.m, mk)
    mv = vm.Minervini(mk, sus, v=vf)
    n0 = len(mv.setups)
    mv.setups = [x for x in mv.setups if not lk[x[0], x[2]]]
    trs = mv.trades(*vm.DEFAULT)
    if trades_only:
        det = minervini_detail(mv, trs)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{mk}_trades_sample.json").write_text(json.dumps({"market": mk, "n_total": len(det), "trades_detail": det},
                                                                 ensure_ascii=False, default=float) + "\n", encoding="utf-8")
        print(f"[{mk}] Minervini 預設格 {len(det)} 筆明細已寫出（全部；漲停鎖死跳過 {n0 - len(mv.setups)}；未算績效）", file=sys.stderr)
        return
    daily, tr, _ = mv.daily(trs)
    res = {"market": mk, "excluded_suspects": sorted(map(list, sus)), "locked_skipped_minervini": n0 - len(mv.setups),
           "cells": {"Minervini": summary(vf.m, daily, tr, [x["b"] - x["a"] for x in trs], len(trs))},
           "abn": {"Minervini": abn(vf.m, daily)}}
    top = set(np.argsort(-np.nan_to_num(np.array(tr), nan=-9))[:10])
    keep = [t for i, t in enumerate(trs) if i not in top]
    res["abn"]["Minervini_drop10"] = abn(vf.m, mv.daily(keep)[0])
    st = res["cells"]["Minervini"]
    st["top10_share"] = float(sum(sorted(tr, reverse=True)[:10]) / sum(tr)) if sum(tr) > 0 else float("nan")
    rnd = {"Minervini": [abn(vf.m, mv.daily(mv.trades(*vm.DEFAULT, random_seed=sd))[0]) for sd in range(n_random)]}
    print(f"[{mk}] Minervini  筆數 {st['trades']:6d}  alpha t {st['alpha_t']:5.2f}  前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  "
          f"年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  累計 {st['cum']:+.0%}（ETF {st['cum_etf']:+.0%}）  "
          f"MDD {st['mdd']:.0%}  勝率 {st['win']:.0%}  RRR {st['rrr']:.2f}  期望值 {st['expectancy']:+.2%}  "
          f"前 10 筆佔獲利 {st['top10_share']:.0%}  持有 {st['avg_hold']:.0f} 日", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def run_market(mk: str, n_random: int, trades_only: bool) -> None:
    pool = [l.strip() for l in (ROOT / "universes" / "full" / f"{mk}_pool.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]
    sus_p = OUT / f"{mk}_suspect.json"
    sus = {tuple(x) for x in json.loads(sus_p.read_text())} if sus_p.exists() and not trades_only else set()
    # ---- 主要：H5a ----
    m1 = nb.MarketData(mk, pool=pool, loader=nb.load_full(mk), top_n=H5A_N[mk], cost=vb.FULL_COST[mk])
    lk1 = locked_matrix(m1, mk)
    ev = drop_locked(m1, m1.events("H5a", nb.GRIDS["H5a"]["default"]), lk1)
    n_locked = int(m1.events("H5a", nb.GRIDS["H5a"]["default"]).sum() - ev.sum())
    for t, d in sus:
        if t in m1.tickers and date.fromisoformat(d) in m1.ci:
            ev[m1.tickers.index(t), m1.ci[date.fromisoformat(d)]] = False
    trades = m1.trades_from_events(ev, "x2")
    if trades_only:
        det = []
        rows_c = {}
        for s, a, b, op in trades:
            t = m1.tickers[s]
            j = int(np.nonzero(ev[s, :a])[0][-1])
            R = rows_c.setdefault(t, {r["Date"]: r for r in m1.loader(t)})
            rs, ra, rb = R.get(m1.cal[j]), R.get(m1.cal[a]), R.get(m1.cal[b])
            det.append({"ticker": t, "signal": m1.cal[j].isoformat(), "entry": m1.cal[a].isoformat(),
                        "exit": m1.cal[b].isoformat(), "exit_at_open": bool(op),
                        "signal_close": rs["Close"] if rs else None, "signal_volume": rs["Volume"] if rs else None,
                        "entry_open": ra["Open"] if ra else None,
                        "exit_px": (rb["Open"] if op else rb["Close"]) if rb else None})
        smp = random.Random(0).sample(det, min(300, len(det)))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{mk}_trades_sample.json").write_text(json.dumps({"market": mk, "n_total": len(det), "trades_detail": smp},
                                                                 ensure_ascii=False, default=float) + "\n", encoding="utf-8")
        print(f"[{mk}] H5a 預設格 {len(det)} 筆（漲停鎖死跳過 {n_locked} 個訊號）；抽 {len(smp)} 筆明細已寫出（未算績效）", file=sys.stderr)
        return
    res = {"market": mk, "excluded_suspects": sorted(map(list, sus)), "locked_skipped_h5a": n_locked, "cells": {}, "abn": {}}
    rnd = {k: [] for k in KEYS}
    daily, tr, _ = m1.portfolio(trades)
    res["cells"]["H5a"] = summary(m1, daily, tr, [b - a for _, a, b, _ in trades], len(trades))
    res["abn"]["H5a"] = abn(m1, daily)
    for sd in range(n_random):
        rnd["H5a"].append(abn(m1, m1.portfolio(h5a_random(m1, ev, lk1, sd))[0]))
    del m1
    # ---- 次要：Minervini、PPP 逆下半身（全市場前 N）----
    vf = vb.VCPData(mk, full=True, scan=False)
    lk2 = locked_matrix(vf.m, mk)
    mv = vm.Minervini(mk, set(), v=vf)
    n0 = len(mv.setups)
    mv.setups = [x for x in mv.setups if not lk2[x[0], x[2]]]
    res["locked_skipped_minervini"] = n0 - len(mv.setups)
    trs = mv.trades(*vm.DEFAULT)
    daily, tr, _ = mv.daily(trs)
    res["cells"]["Minervini"] = summary(vf.m, daily, tr, [x["b"] - x["a"] for x in trs], len(trs))
    res["abn"]["Minervini"] = abn(vf.m, daily)
    for sd in range(n_random):
        rnd["Minervini"].append(abn(vf.m, mv.daily(mv.trades(*vm.DEFAULT, random_seed=sd))[0]))
    pp = ap.AibaPPP(mk, m=vf.m)
    evp0 = pp.events(*ap.DEFAULT)
    evp = drop_locked(vf.m, evp0, lk2)
    res["locked_skipped_ppp"] = int(evp0.sum() - evp.sum())
    trp = vf.m.trades_from_events(evp, ap.RULE)
    daily, tr, _ = vf.m.portfolio(trp)
    res["cells"]["PPP"] = summary(vf.m, daily, tr, [b - a for _, a, b, _ in trp], len(trp))
    res["abn"]["PPP"] = abn(vf.m, daily)
    for sd in range(n_random):
        rnd["PPP"].append(abn(vf.m, vf.m.portfolio(pp.random_trades(evp, ap.DEFAULT[0], sd))[0]))
    for k, st in res["cells"].items():
        print(f"[{mk}] {k:10} 筆數 {st['trades']:6d}  alpha t {st['alpha_t']:5.2f}  前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  "
              f"年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  累計 {st['cum']:+.0%}（ETF {st['cum_etf']:+.0%}）  "
              f"MDD {st['mdd']:.0%}  勝率 {st['win']:.0%}  RRR {st['rrr']:.2f}  期望值 {st['expectancy']:+.2%}  "
              f"持有 {st['avg_hold']:.0f} 日", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 24 else float("nan")


def pooled(series: list[dict]) -> pd.Series:
    """三個市場每月超額等權合併（某月缺某市場就用有的平均）。"""
    return pd.DataFrame([pd.Series(s) for s in series]).T.sort_index().mean(axis=1)


def pool_all(markets=MARKETS, keys=KEYS, tag: str = "") -> None:
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in markets}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in markets}
    MARKETS_ = markets
    out = {}
    for k in keys:
        real = tstat(pooled([R[mk]["abn"][k] for mk in MARKETS_]))
        n = min(len(RN[mk][k]) for mk in MARKETS_)
        rt = sorted(tstat(pooled([RN[mk][k][i] for mk in MARKETS_])) for i in range(n))
        pct = sum(x < real for x in rt) / n if n else float("nan")
        cells = {mk: R[mk]["cells"][k] for mk in MARKETS_}
        drop10 = (tstat(pooled([R[mk]["abn"][k + "_drop10"] for mk in MARKETS_]))
                  if all(k + "_drop10" in R[mk]["abn"] for mk in MARKETS_) else None)
        pos_alpha = sum(c["alpha_t"] > 0 for c in cells.values())
        neg_alpha = sum(c["alpha_t"] < 0 for c in cells.values())
        abs_pos = all(c["cagr"] > 0 for c in cells.values())
        robust = drop10 is None or drop10 > 0          # 第二輪登記第 5 條（第一輪沒有這條 → None）
        if real >= 2.0 and pos_alpha >= 2 and abs_pos and pct >= 0.95 and robust:
            v = "✅ 樣本外確認"
        elif real < 0 or neg_alpha >= 2:
            v = "☠️ 樣本外失敗"
        elif 1.0 <= real < 2.0 and pos_alpha >= 2 and abs_pos:
            v = "🔍 方向一致、未確認"
        else:
            v = "不確定"
        if k != "H5a" and v.startswith("✅") and not tag:
            v += "（次要候選：只標「值得再驗證」，不取代主要候選）"
        out[k] = {"pooled_t": real, "pooled_t_drop10": drop10, "random_pctl": pct, "random_median": rt[n // 2] if n else None,
                  "random_p95": rt[int(0.95 * n)] if n else None, "pos_alpha": pos_alpha, "abs_all_positive": abs_pos,
                  "verdict": v, "per_market": {mk: {x: cells[mk][x] for x in ("alpha_t", "cagr", "cagr_etf", "cum", "cum_etf",
                                                                                "mdd", "trades", "t_pre", "t_post")}
                                               for mk in MARKETS_}}
        print(f"{k:10} 合併 alpha t {real:5.2f}  去前10筆 {drop10 if drop10 is None else round(drop10, 2)}  隨機第 {pct:.0%} 百分位（中位 {out[k]['random_median']:.2f}）  "
              f"alpha>0 市場 {pos_alpha}/3  三地絕對回報都正 {abs_pos}  → {v}", file=sys.stderr)
    (OUT / f"pooled{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS + ROUND2)
    a.add_argument("--only", choices=["minervini"])
    a.add_argument("--round", type=int, default=1)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--trades-only", action="store_true")
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.pool:
        if args.round == 2:
            pool_all(ROUND2, ("Minervini",), "_r2")
        else:
            pool_all()
    elif args.market and args.only == "minervini":
        run_minervini_only(args.market, args.random, args.trades_only)
    elif args.market:
        run_market(args.market, args.random, args.trades_only)
    else:
        a.error("要給 --market 或 --pool")


if __name__ == "__main__":
    main()
