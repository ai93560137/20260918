"""[IDEAS #1323–#1352] 日線出手做方向、短週期搵入場（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準（跑之前 commit；參數固定）。
方向窗口＝#1268 狀態機（xau/trend_d1rules.td_state，已完成 UTC 日線）；6 個時間框 × 5 種入場；出場全部一樣；
對照：①同窗口隨機入場 200 次 ②日線基準（狀態 × 每日升跌 ÷ 3×ATR）每月迴歸截距 ③總 R ÷ 最大回撤。
用法：python3 research/strategy_search/intraday_1323.py → research/strategy_search/INTRADAY_1323.md"""
import datetime as dt
import json
import multiprocessing as mp
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import trend_d1rules as D1R     # noqa: E402

OUT = os.path.join(HERE, "INTRADAY_1323.md")
TFS = (("H4", 14400), ("H1", 3600), ("M30", 1800), ("M15", 900), ("M5", 300), ("M1", 60))
KINDS = ("PB", "BO", "DIP", "SURGE", "MACD")
KNAME = {"PB": "重拾 SMA20", "BO": "破 20 根高位", "DIP": "RSI(2) 跌穿 10", "SURGE": "單根升 ≥ 1.5×ATR", "MACD": "MACD 柱轉正"}
COST, NRAND, SEED = 0.5, 200, 1323
SEGS = (("2010–14", "2010-01-01", "2015-01-01"), ("2015–22", "2015-01-01", "2023-01-01"), ("2023–26", "2023-01-01", "2027-01-01"))


def ts(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())


def load():
    a = A.load("duka", "2010-01-01", "2022-12-31"); b = A.load("mt5", "2023-01-01", "2026-10-30")
    return {k: np.concatenate([a[k], b[k]]) for k in ("t", "o", "h", "l", "c")}


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def atr(b, n=14):
    pc = np.r_[b["c"][0], b["c"][:-1]]
    tr = np.maximum(b["h"] - b["l"], np.maximum(abs(b["h"] - pc), abs(b["l"] - pc)))
    return pd.Series(tr).rolling(n).mean().to_numpy()


def rsi(c, n):
    d = np.r_[0.0, np.diff(c)]
    up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    return 100 - 100 / (1 + up / np.where(dn == 0, 1e-12, dn))


def crossup(x, y):
    out = np.zeros(len(x), bool); out[1:] = (x[1:] > y[1:]) & (x[:-1] <= y[:-1])
    return out & ~np.isnan(x) & ~np.isnan(y)


def neg(b):
    return {"t": b["t"], "o": -b["o"], "h": -b["l"], "l": -b["h"], "c": -b["c"]}


def trig(kind, q, a):
    c = q["c"]
    if kind == "PB":
        return crossup(c, sma(c, 20))
    if kind == "BO":
        return crossup(c, pd.Series(q["h"]).rolling(20).max().shift(1).to_numpy())
    if kind == "DIP":
        r = rsi(c, 2); return crossup(-r, np.full(len(r), -10.0))
    if kind == "SURGE":
        out = np.zeros(len(c), bool); out[1:] = (c[1:] - c[:-1]) >= 1.5 * a[:-1]; return out
    e = lambda n: pd.Series(c).ewm(span=n, adjust=False).mean()  # noqa: E731
    m = e(12) - e(26); h = (m - m.ewm(span=9, adjust=False).mean()).to_numpy()
    return crossup(h, np.zeros(len(h)))


def daily(d):
    """UTC 日線、#1268 狀態、ATR；回傳 day→(適用當日嘅狀態, 前一日 ATR)＋基準每日 R。"""
    b = B.resample(d, 86400); a = atr(b)
    days = [(int(t) // 86400, {"c": float(c)}) for t, c in zip(b["t"], b["c"])]
    s = D1R.td_state(days); st, fl, bench = {}, {}, []
    for k in range(1, len(days)):
        if not np.isnan(a[k - 1]):
            st[days[k][0]] = s[k - 1]; fl[days[k][0]] = a[k - 1]
            bench.append((int(b["t"][k]), s[k - 1] * (b["c"][k] - b["c"][k - 1]) / (3 * a[k - 1])))
    return st, fl, bench


class TF:
    def __init__(self, d, sec, st, fl):
        self.d, self.sec = d, sec; b = self.b = B.resample(d, sec); n = self.n = len(b["c"])
        self.a = atr(b); self.ms = np.searchsorted(d["t"], b["t"]); self.mb = max(48, 86400 // sec)
        day = b["t"] // 86400
        self.st = np.array([st.get(int(x), 0) for x in day]); fa = np.array([fl.get(int(x), np.nan) for x in day])
        self.risk = np.maximum(2 * self.a, np.maximum(3.0, 0.3 * fa))
        sod = b["t"] % 86400
        self.elig = (self.st != 0) & (sod >= 7 * 3600) & (sod < 20 * 3600) & ~np.isnan(self.risk)
        self.elig[-1] = False

    def run(self, cand):
        """cand＝已排序訊號 K 線；方向＝窗口方向。回傳 [(入場 ts, 出場 ts, 方向, R)]。"""
        d, ms, n, t = self.d, self.ms, self.n, self.d["t"]; out = []; p = 0; nxt = ms[np.minimum(cand + 1, n - 1)]
        while p < len(cand):
            i = int(cand[p]); e = i + 1; sg = int(self.st[i]); risk = float(self.risk[i])
            s0 = int(ms[e]); s1 = int(ms[e + self.mb]) if e + self.mb < n else len(t)
            en = d["o"][s0]; sl = en - sg * risk; tp = en + sg * 3 * risk
            hh, ll = d["h"][s0:s1], d["l"][s0:s1]
            slh, tph = ((ll <= sl), (hh >= tp)) if sg > 0 else ((hh >= sl), (ll <= tp))
            si = int(np.argmax(slh)) if slh.any() else 10**9; ti = int(np.argmax(tph)) if tph.any() else 10**9
            if si < 10**9 or ti < 10**9:
                x = s0 + min(si, ti); px = sl if si <= ti else tp
            else:
                x = s1 - 1; px = d["c"][x]
            out.append((int(t[s0]), int(t[x]), sg, (sg * (px - en) - COST) / risk))
            p = int(np.searchsorted(nxt, x, "right"))
        return out


def work(arg):
    name, sec = arg; d = load(); st, fl, bench = daily(d); tf = TF(d, sec, st, fl); rng = np.random.default_rng(SEED + sec); res = []
    tl = {s: trig_all for s, trig_all in ((1, {k: trig(k, tf.b, tf.a) for k in KINDS}), (-1, {k: trig(k, neg(tf.b), tf.a) for k in KINDS}))}
    ne = int(tf.elig.sum())
    for k in KINDS:
        m = tf.elig & (((tf.st > 0) & tl[1][k]) | ((tf.st < 0) & tl[-1][k])); cand = np.flatnonzero(m)
        tr = tf.run(cand); mean = float(np.mean([x[3] for x in tr])) if tr else 0.0
        p = len(cand) / max(ne, 1); rm = []
        for _ in range(NRAND):
            rc = np.flatnonzero(tf.elig & (rng.random(tf.n) < p)); rt = tf.run(rc)
            rm.append(float(np.mean([x[3] for x in rt])) if rt else 0.0)
        res.append({"tf": name, "kind": k, "trades": tr, "rand": rm, "ncand": int(len(cand)), "mean": mean})
        print(name, k, len(tr), f"{mean:+.3f}", f"rand {np.mean(rm):+.3f}", flush=True)
    return res, bench


def month(t):
    x = dt.datetime.fromtimestamp(int(t), dt.timezone.utc); return x.year * 12 + x.month - 1


def monthly(pairs, m0, m1):
    v = np.zeros(m1 - m0 + 1)
    for t, r in pairs:
        v[month(t) - m0] += r
    return v


def dd(v):
    c = np.cumsum(v); return float((np.maximum.accumulate(np.r_[0, c]) - np.r_[0, c]).max())


def alpha_t(y, x):
    X = np.c_[np.ones(len(x)), x]; beta, *_ = np.linalg.lstsq(X, y, rcond=None); e = y - X @ beta
    cov = (e @ e) / (len(y) - 2) * np.linalg.inv(X.T @ X)
    return float(beta[0]), float(beta[1]), float(beta[0] / np.sqrt(cov[0, 0]))


def pf(r):
    g = sum(x for x in r if x > 0); l = -sum(x for x in r if x < 0); return g / l if l else float("inf")


def main():
    with mp.Pool(6) as pool:
        got = pool.map(work, TFS)
    bench = got[0][1]; m0, m1 = month(bench[0][0]), month(bench[-1][0]); bx = monthly(bench, m0, m1)
    L = ["# #1323–#1352：日線出手做方向、短週期搵入場", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；數據 Dukascopy M1 2010–2022＋MT5 M1 2023–2026-10；只讀研究，唔改真倉",
         "- 方向窗口＝#1268 狀態機（尋日收市後係多 → 今日只做多；空 → 只做空；0 → 唔做）。出場全部一樣：SL max(2×ATR, 3 美元, 0.3×D1 ATR)、TP 3R、到期 max(48 根, 一日)、每張扣 0.5 美元",
         f"- 日線基準（同期，#1268 狀態 × 每日升跌 ÷ 3×ATR）：總 {bx.sum():+.1f}R、每月最大回撤 {dd(bx):.1f}R、總 R ÷ 回撤 {bx.sum() / dd(bx):.2f}", "",
         "| # | 時間框 | 入場 | 張數 | 平均 R | PF | 2010–14 | 2015–22 | 2023–26 | 多 | 空 | 隨機平均 | 贏隨機百分位 | 截距 t | 總 R | 回撤 | 總R÷回撤 | 過關 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    idea = 1323; npass = 0; n3 = 0; rows = []
    for res, _ in got:
        for x in res:
            tr = x["trades"]; r = [q[3] for q in tr]; n = len(r); mean = x["mean"]
            sg = [np.mean([q[3] for q in tr if ts(a) <= q[0] < ts(b)]) if any(ts(a) <= q[0] < ts(b) for q in tr) else float("nan") for _, a, b in SEGS]
            lo = np.mean([q[3] for q in tr if q[2] > 0]) if any(q[2] > 0 for q in tr) else float("nan")
            sh = np.mean([q[3] for q in tr if q[2] < 0]) if any(q[2] < 0 for q in tr) else float("nan")
            pct = 100.0 * np.mean(np.array(x["rand"]) < mean)
            y = monthly([(q[1], q[3]) for q in tr], m0, m1); a0, b1, t0 = alpha_t(y, bx)
            ratio = y.sum() / dd(y) if dd(y) > 0 else float("inf")
            g1 = mean > 0 and pf(r) >= 1.15 and n >= 100 and all(v > 0 for v in sg)
            g2 = lo > 0 and sh > 0; g3 = pct >= 95; g4 = t0 >= 2.0; g5 = ratio > bx.sum() / dd(bx)
            ok = g1 and g2 and g3 and g4 and g5; npass += ok; n3 += g3
            marks = "".join("✓" if g else "✗" for g in (g1, g2, g3, g4, g5))
            L.append(f"| {idea} | {x['tf']} | {KNAME[x['kind']]} | {n} | {mean:+.3f} | {pf(r):.2f} | {sg[0]:+.3f} | {sg[1]:+.3f} | {sg[2]:+.3f} | {lo:+.3f} | {sh:+.3f} | "
                     f"{np.mean(x['rand']):+.3f} | {pct:.0f} | {t0:+.2f} | {y.sum():+.1f} | {dd(y):.1f} | {ratio:.2f} | {marks} {'✅' if ok else '❌'} |")
            rows.append({"idea": idea, "tf": x["tf"], "kind": x["kind"], "n": n, "mean": mean, "pf": pf(r), "pct": pct, "t": t0, "ratio": ratio, "beta": b1, "ok": bool(ok)})
            idea += 1
    L += ["", f"- 過關欄五格＝①賺錢＋三段都正 ②多空都正 ③贏隨機 ≥ 95 ④截距 t ≥ 2 ⑤總R÷回撤 > 日線基準。**五關全過：{npass}／30**；單睇關 ③ 過咗 {n3} 條（純撞彩預期 1–2 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); json.dump(rows, open(os.path.join(HERE, "intraday_1323.json"), "w"))
    print("\n".join(L))


if __name__ == "__main__":
    main()
