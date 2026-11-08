"""[IDEAS #2002] 200 日線跌穿後第一次觸碰：用「前高、形態、反彈力度」擬合邊啲情況會被壓返（使用者 11-08「寫埋出來，擬合都得」）。

承接 #2001（^NDX、^GSPC 1990 起，觸碰後第 10 日仍喺 200 SMA 下＝壓返，整體約 50%）。今次喺觸碰當日量度：
  前高（上方阻力）：
    overhead   ＝ 跌穿前 60 日最高 ÷ 觸碰日 200 SMA − 1（前高離 200 SMA 幾遠；越近＝阻力疊埋）
  形態／趨勢：
    slope20    ＝ 200 SMA 對比 20 日前嘅變化（%）；負＝200 SMA 已經向下
    death      ＝ 50 SMA < 200 SMA（死亡交叉）
    depth      ＝ 跌穿後最低點離 200 SMA 幾深（%）
  反彈力度：
    rebound    ＝ 由跌穿後最低點反彈到觸碰日收市（%）
    speed      ＝ rebound ÷ 由最低點到觸碰日嘅交易日數（每日 %）
    touch_close＝ 觸碰日收市喺 200 SMA 上（收穿）定只係盤中掂到
  另加 days_to_touch（跌穿後幾日先觸碰）。
方法：逐個特徵分高／低兩組睇壓返比例；再做邏輯迴歸（標準化、L2），用留一法（LOO）計樣本外準確率。
注意：只有約 47 次事件，擬合好易過度配合；呢個係探索，唔係預先登記嘅驗證，結論要前向再驗。
輸出：GCS ops/longfei/analyst/research/ma200_fit.json。
"""
import json
import math
import statistics


def events(tk):
    import yfinance as yf
    df = yf.download(tk, start="1990-01-01", interval="1d", progress=False, auto_adjust=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df["s200"] = df["Close"].rolling(200).mean()
    df["s50"] = df["Close"].rolling(50).mean()
    df = df.dropna()
    c, h, l = df["Close"].tolist(), df["High"].tolist(), df["Low"].tolist()
    s, s50 = df["s200"].tolist(), df["s50"].tolist()
    idx = [d.strftime("%Y-%m-%d") for d in df.index]
    out, i = [], 60
    while i < len(c) - 70:
        if c[i] < s[i] and all(c[j] > s[j] for j in range(i - 60, i)):
            t = next((j for j in range(i + 1, min(i + 61, len(c))) if h[j] >= s[j]), None)
            if t is not None and t + 20 < len(c):
                lo_i = min(range(i, t + 1), key=lambda j: l[j])
                rb = c[t] / l[lo_i] - 1
                out.append({
                    "tk": tk, "break": idx[i], "touch": idx[t],
                    "overhead": max(h[i - 60:i]) / s[t] - 1,
                    "slope20": s[t] / s[t - 20] - 1,
                    "death": 1.0 if s50[t] < s[t] else 0.0,
                    "depth": l[lo_i] / s[lo_i] - 1,
                    "rebound": rb,
                    "speed": rb / max(t - lo_i, 1),
                    "touch_close": 1.0 if c[t] >= s[t] else 0.0,
                    "days_to_touch": float(t - i),
                    "rejected": 1 if c[t + 10] < s[t + 10] else 0,
                    "ret20": c[t + 20] / c[t] - 1})
            i += 60
        else:
            i += 1
    return out


FEATS = ["overhead", "slope20", "death", "depth", "rebound", "speed", "touch_close", "days_to_touch"]


def split(ev, f):
    xs = sorted(e[f] for e in ev)
    med = statistics.median(xs)
    lo = [e for e in ev if e[f] <= med] if len(set(xs)) > 2 else [e for e in ev if e[f] == 0]
    hi = [e for e in ev if e not in lo]
    r = lambda g: (round(sum(e["rejected"] for e in g) / len(g), 2), len(g)) if g else (None, 0)  # noqa: E731
    return {"cut": round(med, 4) if len(set(xs)) > 2 else "0/1", "low": r(lo), "high": r(hi)}


def logit_fit(X, y, lam=1.0, it=3000, lr=0.1):
    n, k = len(X), len(X[0])
    w, b = [0.0] * k, 0.0
    for _ in range(it):
        gw, gb = [lam * wj / n for wj in w], 0.0
        for xi, yi in zip(X, y):
            p = 1 / (1 + math.exp(-(b + sum(a * c for a, c in zip(w, xi)))))
            for j in range(k):
                gw[j] += (p - yi) * xi[j] / n
            gb += (p - yi) / n
        w = [wj - lr * g for wj, g in zip(w, gw)]
        b -= lr * gb
    return w, b


def main():
    ev = events("^NDX") + events("^GSPC")
    y = [e["rejected"] for e in ev]
    mu = {f: statistics.mean(e[f] for e in ev) for f in FEATS}
    sd = {f: statistics.pstdev(e[f] for e in ev) or 1 for f in FEATS}
    X = [[(e[f] - mu[f]) / sd[f] for f in FEATS] for e in ev]
    w, b = logit_fit(X, y)
    ins = sum((1 / (1 + math.exp(-(b + sum(a * c for a, c in zip(w, x))))) > 0.5) == yy for x, yy in zip(X, y)) / len(y)
    loo = 0
    for k in range(len(X)):
        wk, bk = logit_fit(X[:k] + X[k + 1:], y[:k] + y[k + 1:], it=1500)
        p = 1 / (1 + math.exp(-(bk + sum(a * c for a, c in zip(wk, X[k])))))
        loo += (p > 0.5) == y[k]
    res = {"n": len(ev), "base_rejected": round(sum(y) / len(y), 3),
           "splits": {f: split(ev, f) for f in FEATS},
           "logit_weights_std": {f: round(wj, 3) for f, wj in zip(FEATS, w)}, "logit_bias": round(b, 3),
           "acc_in_sample": round(ins, 3), "acc_loo": round(loo / len(y), 3),
           "mean": {f: round(mu[f], 4) for f in FEATS}, "sd": {f: round(sd[f], 4) for f in FEATS},
           "events": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in e.items()} for e in ev]}
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    print(txt[:3000])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("ops/longfei/analyst/research/ma200_fit.json") \
        .upload_from_string(txt, content_type="application/json")


if __name__ == "__main__":
    main()
