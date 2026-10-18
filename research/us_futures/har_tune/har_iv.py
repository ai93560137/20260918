"""[IDEAS #107] ES／NQ 日波幅 HAR（R231）加隱含波幅（VXN→NQ、VIX→ES）回測。
特徵：R231 嘅 8 個（常數、log 前一日／5 日／22 日波幅%、前一日跌幅、升幅、星期一、星期五）＋ log(前一日 IV 收市 ÷ 100 ÷ √252)。
逐日前推、擴展窗口最小二乘（每 20 日重估一次）、殘差窗口 500 日；評分期 2016-01-01 至最新；IV 只用前一個交易日收市（無偷看）。
輸出 har_iv_<sym>.csv（逐日）＋ 印出結果（貼入 REPORT_IV.md）。用法：python3 research/us_futures/har_tune/har_iv.py
"""
import csv, math, os
from datetime import date
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.dirname(os.path.abspath(__file__))
START, SUB = "2016-01-01", "2024-01-01"


def load(name):
    return {r["Date"]: r for r in csv.DictReader(open(os.path.join(ROOT, "data", "us_futures", name)))}


def run(sym, iv_file):
    px = [r for r in load(f"{sym}_daily.csv").values() if float(r["High"]) > 0]
    px.sort(key=lambda r: r["Date"])
    iv = {d: float(r["Close"]) for d, r in load(iv_file).items() if float(r["Close"] or 0) > 0}
    d = [r["Date"] for r in px]; H = np.array([float(r["High"]) for r in px]); L = np.array([float(r["Low"]) for r in px]); C = np.array([float(r["Close"]) for r in px])
    pc = np.r_[np.nan, C[:-1]]; rng = (H - L) / pc; ret = (C / pc - 1) * 100
    ok = [i for i in range(1, len(px)) if rng[i] > 0]
    res_all = {}
    for use_iv in (False, True):
        X, Y, out = [], [], []
        b = None
        for k, t in enumerate(ok):
            if k < 22:
                continue
            p = ok[k - 22:k]; prev = p[-1]
            if use_iv and d[prev] not in iv:
                continue
            wd = date.fromisoformat(d[t]).weekday()
            f = [1, math.log(rng[prev]), math.log(rng[p[-5:]].mean()), math.log(rng[p].mean()),
                 max(0, -ret[prev]), max(0, ret[prev]), 1 if wd == 0 else 0, 1 if wd == 4 else 0]
            if use_iv:
                f.append(math.log(iv[d[prev]] / 100 / math.sqrt(252)))
            if d[t] >= START and len(X) > 500:
                if b is None or len(out) % 20 == 0:
                    A = np.array(X); b = np.linalg.lstsq(A, np.array(Y), rcond=None)[0]
                    res = np.array(Y[-500:]) - A[-500:] @ b; q10, q90 = np.quantile(res, [0.1, 0.9])
                fit = float(np.array(f) @ b)
                out.append((d[t], H[t] - L[t], math.exp(fit) * pc[t], math.exp(fit + q10) * pc[t], math.exp(fit + q90) * pc[t]))
            X.append(f); Y.append(math.log(rng[t]))
        res_all[use_iv] = {o[0]: o for o in out}
    common = sorted(set(res_all[False]) & set(res_all[True]))
    rows = []
    for label, sub in (("2016+", START), ("2024+", SUB)):
        days = [x for x in common if x >= sub]
        for use_iv in (False, True):
            o = [res_all[use_iv][x] for x in days]
            act = np.array([x[1] for x in o]); fc = np.array([x[2] for x in o])
            mae = np.mean(abs(act - fc) / act); rmse = np.sqrt(np.mean((np.log(act) - np.log(fc)) ** 2))
            cov = np.mean([(x[3] <= x[1] <= x[4]) for x in o])
            rows.append((sym, label, "R231+IV" if use_iv else "R231", len(o), mae, rmse, cov))
    with open(os.path.join(OUT, f"har_iv_{sym}.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["date", "actual", "r231_fc", "r231_lo", "r231_hi", "iv_fc", "iv_lo", "iv_hi"])
        for x in common:
            a, b2 = res_all[False][x], res_all[True][x]
            w.writerow([x, round(a[1], 2), *(round(v, 2) for v in a[2:]), *(round(v, 2) for v in b2[2:])])
    return rows


for sym, f in (("NQ", "IDX_VXN_daily.csv"), ("ES", "IDX_VIX_daily.csv")):
    for r in run(sym, f):
        print(f"{r[0]} {r[1]} {r[2]:8s} n={r[3]} 平均誤差 {r[4]:.1%} log RMSE {r[5]:.3f} 80% 覆蓋 {r[6]:.1%}")
