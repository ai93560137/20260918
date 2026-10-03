"""恒指即月期貨每日波幅（高−低）預測回測：逐日前推（walk-forward），每個預測只用前一天夜市收市前已知的數據。

交易日 = 香港時間 09:00 至翌日 09:00（日市 09:15–16:30 加當晚夜市 17:15–翌日 03:00），跟 GCP 的
futu/daily/HK.HSI_FRONT.json（main.py R97、本地腳本 v7）同一個定義。

用法（在 repo 根目錄）：
  python3 research/hsi_futures_range/backtest.py futures --gcs          # 從 GCS 讀期貨交易日序列（需要 GCP_SA_KEY）
  python3 research/hsi_futures_range/backtest.py futures --json 檔案     # 或讀本地 JSON（[{time_key, open, high, low, close}]）
  python3 research/hsi_futures_range/backtest.py index                  # 恒指指數日市 2008 起（穩健性檢查，讀網站數據分支）

需要 numpy、scipy（只給研究用，不部署）。結果與結論見同目錄 RESULTS.md。
"""
import csv, io, json, math, os, subprocess, sys
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy import stats

REPO = Path(__file__).resolve().parents[2]
WEB_REF = os.environ.get("WEB_REF", "origin/claude/gifted-carson-v2tvhw")


def load_futures_gcs(symbol="HK.HSI_FRONT"):
    sys.path.insert(0, str(REPO / "scripts"))
    import argparse
    import gcp_agent as g
    ctx = g.Ctx(argparse.Namespace(region=None, function=None, bucket=None, project=None))
    obj = f"futu/daily/{symbol}.json".replace("/", "%2F")
    resp = ctx.session.get(f"https://storage.googleapis.com/storage/v1/b/{ctx.bucket}/o/{obj}", params={"alt": "media"})
    resp.raise_for_status()
    return to_rows(resp.json())


def load_futures_json(path):
    return to_rows(json.load(open(path, encoding="utf-8")))


def to_rows(bars):
    bars = sorted((b for b in bars if isinstance(b, dict)), key=lambda b: str(b.get("time_key", "")))
    return [(str(b["time_key"])[:10], float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"]))
            for b in bars if float(b["high"]) >= float(b["low"]) > 0]


def load_index(years):
    rows = {}
    for y in years:
        try:
            text = subprocess.run(["git", "-C", str(REPO), "show", f"{WEB_REF}:data/equities/hk/_HSI/prices_{y}.csv"],
                                  capture_output=True, text=True, check=True).stdout
        except subprocess.CalledProcessError:
            continue
        for r in csv.DictReader(io.StringIO(text)):
            try:
                o, h, l, c = (float(r[k]) for k in ("Open", "High", "Low", "Close"))
            except (ValueError, KeyError):
                continue
            if h > l > 0:
                rows[r["Date"]] = (o, h, l, c)
    return [(d, *rows[d]) for d in sorted(rows)]


def garch_fit(x):
    x = x - x.mean()
    def nll(p):
        w, a, b = p
        if w <= 0 or a < 0 or b < 0 or a + b >= 0.999:
            return 1e10
        v = np.empty_like(x); v[0] = x.var()
        for t in range(1, len(x)):
            v[t] = w + a * x[t - 1] ** 2 + b * v[t - 1]
        return 0.5 * np.sum(np.log(v) + x * x / v)
    r = minimize(nll, [x.var() * 0.05, 0.08, 0.9], method="Nelder-Mead", options={"maxiter": 1500})
    return r.x


def run(data, burn, garch_every=20, garch_window=750):
    D = [d for d, *_ in data]
    O, H, L, C = (np.array([row[i] for row in data], float) for i in range(1, 5))
    n = len(D)
    r = np.full(n, np.nan); r[1:] = (H[1:] - L[1:]) / C[:-1]          # 波幅 ÷ 昨收
    tr = np.full(n, np.nan); tr[1:] = (np.maximum(H[1:], C[:-1]) - np.minimum(L[1:], C[:-1])) / C[:-1]
    gap = np.full(n, np.nan); gap[1:] = np.abs(np.log(O[1:] / C[:-1]))
    ret = np.full(n, np.nan); ret[1:] = np.log(C[1:] / C[:-1])
    F = {}                                                            # 策略 → 預測（波幅%）
    def put(name, t, v):
        F.setdefault(name, np.full(n, np.nan))[t] = v
    ew = {lam: np.nan for lam in (0.80, 0.90, 0.94)}
    atr = np.nan
    garch_p, gv = None, None
    for t in range(23, n):
        hist = r[1:t]                                                 # 到 t−1 為止
        put("昨日波幅", t, r[t - 1])
        for k in (5, 10, 20, 60):
            if len(hist) >= k:
                put(f"{k} 日平均", t, hist[-k:].mean())
        put("20 日中位數", t, np.median(hist[-20:]))
        for lam in ew:
            ew[lam] = r[t - 1] if np.isnan(ew[lam]) else lam * ew[lam] + (1 - lam) * r[t - 1]
            put(f"EWMA λ={lam}", t, ew[lam])
        atr = np.nanmean(tr[1:t][-14:]) if np.isnan(atr) else (atr * 13 + tr[t - 1]) / 14
        put("ATR(14)", t, atr)
        # HAR（對數）：用 t−1 為止的數據擬合，預測 t
        if t >= 60:
            lr = np.log(r)
            X, Y, Xg = [], [], []
            for s in range(23, t):
                row = [1, lr[s - 1], math.log(r[s - 5:s].mean()), math.log(r[s - 22:s].mean())]
                X.append(row); Y.append(lr[s]); Xg.append(row + [gap[s] * 100])
            X, Y, Xg = np.array(X), np.array(Y), np.array(Xg)
            xf = np.array([1, lr[t - 1], math.log(r[t - 5:t].mean()), math.log(r[t - 22:t].mean())])
            b, *_ = np.linalg.lstsq(X, Y, rcond=None); res = Y - X @ b
            put("HAR（對數，平均）", t, math.exp(xf @ b) * np.mean(np.exp(res)))
            put("HAR（對數，中位）", t, math.exp(xf @ b + np.median(res)))
            lo, hi = np.percentile(res, [10, 90])
            put("_HAR_lo", t, math.exp(xf @ b + lo)); put("_HAR_hi", t, math.exp(xf @ b + hi))
            bl, *_ = np.linalg.lstsq(np.exp(X[:, [0]]) * 0 + np.c_[np.ones(len(X)), np.exp(X[:, 1:])], np.exp(Y), rcond=None)
            put("HAR（線性）", t, max(1e-5, np.r_[1, np.exp(xf[1:])] @ bl))
            bg, *_ = np.linalg.lstsq(Xg, Y, rcond=None); rg = Y - Xg @ bg
            put("◆ HAR＋開市跳空", t, math.exp(np.r_[xf, gap[t] * 100] @ bg) * np.mean(np.exp(rg)))
            put("HAR＋EWMA 0.94 平均", t, 0.5 * (F["HAR（對數，平均）"][t] + ew[0.94]))
        # GARCH(1,1)：σ̂ × 校準係數（過去 波幅 ÷ σ̂ 的平均）
        if t >= 120:
            if garch_p is None or (t - 120) % garch_every == 0:
                x = ret[max(1, t - garch_window):t]
                garch_p = garch_fit(x)
                w, a, bb = garch_p
                xx = x - x.mean(); v = np.empty(len(xx)); v[0] = xx.var()
                for s in range(1, len(xx)):
                    v[s] = w + a * xx[s - 1] ** 2 + bb * v[s - 1]
                gv = v[-1]; gk = np.mean(r[max(1, t - garch_window):t][-len(v):] / np.sqrt(v)); last_x = xx[-1]
                mu = x.mean()
            else:
                w, a, bb = garch_p
                gv = w + a * (ret[t - 2] - mu) ** 2 + bb * gv if t >= 2 else gv
            w, a, bb = garch_p
            vf = w + a * (ret[t - 1] - mu) ** 2 + bb * gv
            put("GARCH(1,1)", t, math.sqrt(vf) * gk)
    return D, C, r, F


def evaluate(D, C, r, F, start, base="20 日平均"):
    names = [k for k in F if not k.startswith("_")]
    idx = [t for t in range(start, len(D)) if all(not np.isnan(F[k][t]) for k in names) and not np.isnan(r[t])]
    idx = np.array(idx)
    act = r[idx] * C[idx - 1]
    out = []
    eb = np.abs(F[base][idx] * C[idx - 1] - act)
    for k in names:
        f = F[k][idx] * C[idx - 1]
        e = f - act
        q = r[idx] / F[k][idx]; qlike = np.mean(q - np.log(q) - 1)
        d = np.abs(e) - eb                                             # Diebold-Mariano（MAE，HAC 5 期）
        T = len(d); dm = d.mean(); g = [np.mean((d[l:] - dm) * (d[:T - l] - dm)) for l in range(6)]
        var = g[0] + 2 * sum((1 - l / 6) * g[l] for l in range(1, 6))
        p = 2 * (1 - stats.norm.cdf(abs(dm / math.sqrt(var / T)))) if var > 0 and k != base else float("nan")
        out.append(dict(name=k, mae=np.mean(np.abs(e)), rmse=math.sqrt(np.mean(e ** 2)), mape=np.mean(np.abs(e) / act) * 100,
                        bias=np.mean(e), r2=np.corrcoef(f, act)[0, 1] ** 2, qlike=qlike, dm_p=p, better=dm < 0))
    out.sort(key=lambda x: x["mae"])
    cov = None
    if "_HAR_lo" in F:
        lo, hi = F["_HAR_lo"][idx], F["_HAR_hi"][idx]
        cov = float(np.mean((r[idx] >= lo) & (r[idx] <= hi)))
    return out, len(idx), D[idx[0]], D[idx[-1]], cov, float(act.mean())


def show(title, res):
    out, n, a, b, cov, avg = res
    print(f"\n=== {title}：測試 {n} 天（{a} 至 {b}），實際平均波幅 {avg:.0f} 點 ===")
    print(f"{'策略':<22}{'MAE':>7}{'RMSE':>7}{'MAPE%':>7}{'偏差':>7}{'R²':>6}{'QLIKE':>7}{'對20日平均 p':>12}")
    for x in out:
        p = "基準" if math.isnan(x["dm_p"]) else f"{x['dm_p']:.3f}{'↑' if x['better'] else '↓'}"
        print(f"{x['name']:<22}{x['mae']:>7.0f}{x['rmse']:>7.0f}{x['mape']:>7.1f}{x['bias']:>7.0f}{x['r2']:>6.2f}{x['qlike']:>7.3f}{p:>12}")
    if cov is not None:
        print(f"HAR 80% 區間實際命中率：{cov:.0%}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "futures"
    if which == "futures":
        data = load_futures_json(sys.argv[sys.argv.index("--json") + 1]) if "--json" in sys.argv else load_futures_gcs()
        D, C, r, F = run(data, 60)
        F2 = {k: v for k, v in F.items() if k != "GARCH(1,1)"}       # GARCH 要 120 天暖身，另外比
        show("恒指即月期貨交易日（日市＋夜市），不含 GARCH", evaluate(D, C, r, F2, 61))
        show("恒指即月期貨交易日（含 GARCH，測試期較短）", evaluate(D, C, r, F, 120))
    else:
        data = load_index(range(2008, 2027))
        D, C, r, F = run(data, 60, garch_every=60, garch_window=750)
        show("恒指指數日市（2012 起）", evaluate(D, C, r, F, next(i for i, d in enumerate(D) if d >= "2012-01-01")))
        show("恒指指數日市（最近 3 年）", evaluate(D, C, r, F, next(i for i, d in enumerate(D) if d >= "2023-10-01")))
