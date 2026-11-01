"""[IDEAS #170] XAUUSD M5 高勝率（細止賺、闊止蝕）策略：使用者 11-01「先唔好理 t 值，用 M1、M5 做到接近 100% 勝率，之後就算止損最後都係正期望值」。
引擎同 #169（m5_indicators.py）：M5 收市判、下一根開盤入、同一根 SL／TP 都掂當 SL（保守）、跳空過 SL 用開盤、每張扣 0.5 美元、一次一張。
網格寫死喺 FAMILIES（預先登記，跑之前 commit）。
第一關：券商 MT5 2022-08→2026-10 滾動前向（12 個月揀、3 個月測；訓練期要勝率 ≥ 90%、≥ 30 張，揀平均 R 最高）。
第二關：最常揀嗰組固定參數，Dukascopy 2015-01→2022-07。
用法：python3 research/strategy_search/highwin.py --stage wf｜duka
"""
import argparse
import datetime as dt
import itertools
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g7_long as G  # noqa: E402
import m5_indicators as M  # noqa: E402
import robust_long as R  # noqa: E402
import search as S  # noqa: E402
import search2 as W  # noqa: E402

PICKS = os.path.join(HERE, "highwin_picks.json")
TRAIN_WIN = 0.90

FAMILIES = {
    "W1 大K逆勢": [dict(k=k, a=a, b=b) for k, a, b in itertools.product((1.5, 2.5), (0.3, 0.5), (3.0, 6.0))],
    "W2 順H1趨勢 RSI2 回調": [dict(a=a, b=b, T=T) for a, b, T in itertools.product((0.3, 0.5), (3.0, 6.0), (4, 24))],
    "W3 TWAP 偏離回歸": [dict(z=z, a=a, b=b) for z, a, b in itertools.product((2.0, 3.0), (0.3, 0.5), (3.0, 6.0))],
    "W4 亞洲區間邊回歸": [dict(a=a, b=b) for a, b in itertools.product((0.3, 0.5), (3.0, 6.0))],
    "W5 偏離 EMA50 回歸": [dict(dev=d, b=b) for d, b in itertools.product((3.0, 4.0), (3.0, 6.0, 10.0))],
}


class HD(M.M5):
    def __init__(self, d):
        super().__init__(d)
        self.rsi2 = G.rsi(self.c, 2)
        self.e50 = G.ema(self.c, 50)
        t = self.t
        hr = (t // 3600) % 24
        sess = (t + 3600) // 86400                    # 23:00 UTC 起
        rh = np.full(len(t), np.nan); rl = np.full(len(t), np.nan)
        _, first, cnt = np.unique(sess, return_index=True, return_counts=True)
        for f, n in zip(first, cnt):
            idx = np.arange(f, f + n)
            rng = idx[(hr[idx] == 23) | (hr[idx] <= 6)]
            if len(rng) < 60:
                continue
            after = idx[(hr[idx] >= 7) & (hr[idx] <= 15)]
            rh[after] = self.h[rng].max(); rl[after] = self.l[rng].min()
        self.arh, self.arl = rh, rl


def run(D, fam, p):
    c, atr = D.c, D.atr
    n = len(c); key = fam[:2]; ent = []
    prev = lambda x: np.r_[np.nan, x[:-1]]   # noqa: E731

    def add(mb, ms, a, b, T):
        for i in np.flatnonzero(mb | ms):
            if i + 1 >= n or np.isnan(atr[i]) or atr[i] <= 0:
                continue
            ent.append((i + 1, 1 if mb[i] else -1, b * atr[i], a * atr[i], T))

    if key == "W1":
        body = c - D.o; big = np.abs(body) > p["k"] * prev(atr)
        add(big & (body < 0), big & (body > 0), p["a"], p["b"], 4)
    elif key == "W2":
        add((D.rsi2 < 10) & (D.h1_s50 > 0), (D.rsi2 > 90) & (D.h1_s50 < 0), p["a"], p["b"], p["T"])
    elif key == "W3":
        ok = D.sess_n >= 12
        lo, hi = D.twap - p["z"] * D.tsd, D.twap + p["z"] * D.tsd
        add(ok & (c < lo) & (prev(c) >= prev(lo)), ok & (c > hi) & (prev(c) <= prev(hi)), p["a"], p["b"], 4)
    elif key == "W4":
        add((D.l <= D.arl) & (c > D.arl), (D.h >= D.arh) & (c < D.arh), p["a"], p["b"], 4)
    elif key == "W5":
        dev = (c - D.e50) / atr
        add((dev < -p["dev"]) & (prev(dev) >= -p["dev"]), (dev > p["dev"]) & (prev(dev) <= p["dev"]), 0.5, p["b"], 24)
    ent.sort(key=lambda x: x[0])
    return R.simulate(D, ent)


def wr(rs):
    rs = np.asarray(rs, float)
    return float((rs > 0).mean()) if len(rs) else 0.0


def dd(rs):
    eq = np.cumsum(rs) if len(rs) else np.zeros(1)
    return float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())


def desc(rs):
    rs = np.asarray(rs, float); s = R.summ(rs)
    if not len(rs):
        return "0 張"
    return (f"{s['n']} 張 勝率 {wr(rs):.1%} 平均 {s['avg']:+.3f}R ΣR {rs.sum():+.1f} PF {s['pf']:.2f} "
            f"最大單蝕 {rs.min():+.2f}R 最大回撤 {dd(rs):+.1f}R")


def stage_wf():
    D = HD(W.to_m5(S.load("mt5", "2022-08-03", "2026-10-30")))
    qs = []; q = M.WF_FIRST_TEST
    while q <= M.WF_LAST_TEST:
        qs.append(q); q = M.add_months(q, 3)
    out = ["# M5 高勝率策略（IDEAS #170）第一關：券商 MT5 滾動前向", "",
           f"- 12 個月揀（勝率 ≥ {TRAIN_WIN:.0%}、≥ 30 張，揀平均 R 最高）、測下 3 個月；同一根 SL／TP 都掂當 SL；每張扣 {R.COST} 美元", "",
           "| 家族 | 樣本外 | 正數季 | 最常揀 | 第一關 |", "|---|---|---|---|---|"]
    picks = {}
    for fam, grid in FAMILIES.items():
        trs = [run(D, fam, p) for p in grid]
        oos, qpos, sel = [], 0, []
        for q in qs:
            a, b, e = M.ts_ym(M.add_months(q, -12)), M.ts_ym(q), M.ts_ym(M.add_months(q, 3))
            best = None
            for gi, tr in enumerate(trs):
                rs = [x[3] for x in tr if a <= x[0] < b]
                if len(rs) >= 30 and wr(rs) >= TRAIN_WIN and (best is None or np.mean(rs) > best[1]):
                    best = (gi, float(np.mean(rs)))
            yt = [] if best is None else [x[3] for x in trs[best[0]] if b <= x[0] < e]
            if best is not None:
                sel.append(best[0])
            qpos += 1 if yt and np.mean(yt) > 0 else 0
            oos += yt
        ok = dict(n=len(oos) >= 100, win=wr(oos) >= 0.90, avg=bool(oos) and np.mean(oos) > 0, q=qpos >= 8)
        top = max(set(sel), key=sel.count) if sel else None
        picks[fam] = {"pass1": all(ok.values()), "param": None if top is None else grid[top]}
        out.append(f"| {fam} | {desc(oos)} | {qpos}/{len(qs)} | {'—' if top is None else grid[top]} | "
                   f"{'✅ 入第二關' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(fam, desc(oos), flush=True)
    out += ["", "## 全期描述（每組，唔算數）", ""]
    for fam, grid in FAMILIES.items():
        for p in grid:
            out.append(f"- {fam} {p}：{desc([x[3] for x in run(D, fam, p)])}")
    json.dump(picks, open(PICKS, "w"), ensure_ascii=False, indent=1)
    out += ["", f"- 入第二關：{'、'.join(f for f, v in picks.items() if v['pass1']) or '冇'}", ""]
    open(os.path.join(HERE, "HIGHWIN_WF.md"), "w").write("\n".join(out))


def stage_duka():
    picks = json.load(open(PICKS)); todo = {f: v for f, v in picks.items() if v["pass1"]}
    out = ["# M5 高勝率策略（IDEAS #170）第二關：Dukascopy 2015-01→2022-07 固定參數", ""]
    if not todo:
        out.append("- 第一關冇家族過，第二關唔使跑。")
    else:
        D = HD(W.to_m5(S.load("duka", "2015-01-01", "2022-07-31")))
        for fam, v in todo.items():
            tr = run(D, fam, v["param"]); yy = {}
            for x in tr:
                yy.setdefault(R.yr(x[0]), []).append(x[3])
            rs = [x[3] for x in tr]; pos = sum(1 for r in yy.values() if np.mean(r) > 0)
            ok = dict(n=len(rs) >= 100, win=wr(rs) >= 0.85, avg=bool(rs) and np.mean(rs) > 0, yrs=pos >= 5)
            out += [f"## {fam} {v['param']}", "", f"- {desc(rs)}；{pos}/{len(yy)} 年正",
                    f"- 判：{'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, x in ok.items() if not x)}", ""]
    open(os.path.join(HERE, "HIGHWIN_DUKA.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--stage", choices=("wf", "duka"), required=True)
    stage_wf() if ap.parse_args().stage == "wf" else stage_duka()
