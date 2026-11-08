"""[IDEAS #2007] 策略搜尋第五批：MHI 1 小時（恒指期貨連續合約 1 分鐘存檔，2025-10 起，含夜市）。

#2003–#2006 日線 MHI 全部唔合格。今批改 1 小時，跟日線趨勢（昨收 vs 20 日均，user_method.daily）方向：
  J1 1 小時 Donchian 順日線：N∈{20,50} 小時、止蝕 k×ATR(14h) k∈{2,3}、M∈{10,20} 小時反向通道出
  J2 1 小時 RSI2 順勢回吐：日線升勢 RSI2<th 做好／跌勢 RSI2>100−th 做淡；RSI2 反過 70／30 或 10 小時出；止蝕 3×ATR。th∈{5,10}
  J3 1 小時布林帶回歸（雙向，唔理日線）：±2σ(20h)，返中線或 10 小時出；止蝕 3×ATR
執行：小時收市出訊號 → 下一小時開市入；成本來回 MHI 4 點、NQ 1 點；R＝2×ATR(14h)。
跨市場：NQ=F 1 小時（yfinance 最近 730 日），日線趨勢用 NQ 日線 20 日均。

預先登記（11-09，跑之前寫，唔再改）：
  合格＝MHI：n ≥ 60、平均 ≥ +0.15R、PF ≥ 1.30、t ≥ 2.0、前後兩半平均都 > 0；而且 NQ 1 小時同設定平均 R > 0。
  多過一個揀 t 最高。合格 → 影子前向 30 張（MHI 模擬），達標先提案真倉（使用者批）；冇 → 第六批（換方向：恒指日市開市後首小時／收市前事件等，另行登記）。
"""
import json
import math
import statistics
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "longfei_lessons"))
import user_method as um  # noqa: E402
import daily_search as ds  # noqa: E402


def hourly(bars1):
    out = {}
    for t, o, h, l, c in bars1:
        k = t.replace(minute=0, second=0)
        x = out.get(k)
        out[k] = [k, o, h, l, c] if x is None else [k, x[1], max(x[2], h), min(x[3], l), c]
    return [tuple(out[k]) for k in sorted(out)]


def atr14(b):
    tr = [b[0][2] - b[0][3]] + [max(b[i][2], b[i - 1][4]) - min(b[i][3], b[i - 1][4]) for i in range(1, len(b))]
    return [None if i < 14 else sum(tr[i - 13:i + 1]) / 14 for i in range(len(b))]


def rsi2(c):
    out = [None] * len(c)
    for i in range(2, len(c)):
        g = sum(max(c[j] - c[j - 1], 0) for j in (i - 1, i)) / 2
        l_ = sum(max(c[j - 1] - c[j], 0) for j in (i - 1, i)) / 2
        out[i] = 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)
    return out


def sim(b, trend, fam, p, cost):
    c = [x[4] for x in b]
    atr, rs = atr14(b), rsi2(c)
    n, out, i = len(b), [], 60
    while i < n - 2:
        tdir = trend[i]
        sig = 0
        if fam == "J1" and tdir:
            hi = max(x[2] for x in b[i - p["N"]:i]); lo = min(x[3] for x in b[i - p["N"]:i])
            sig = 1 if tdir > 0 and c[i] > hi else (-1 if tdir < 0 and c[i] < lo else 0)
        elif fam == "J2" and tdir and rs[i] is not None:
            sig = 1 if tdir > 0 and rs[i] < p["th"] else (-1 if tdir < 0 and rs[i] > 100 - p["th"] else 0)
        elif fam == "J3":
            w = c[i - 19:i + 1]; m = sum(w) / 20; sd = (sum((x - m) ** 2 for x in w) / 20) ** 0.5
            sig = 1 if c[i] < m - 2 * sd else (-1 if c[i] > m + 2 * sd else 0)
        if not sig or not atr[i]:
            i += 1
            continue
        R, px = 2 * atr[i], b[i + 1][1]
        k = p.get("k", 3)
        stop = px - sig * k * atr[i]
        res = None
        for j in range(i + 1, min(i + 200, n)):
            _, o, h, l, cc = b[j]
            if (sig > 0 and l <= stop) or (sig < 0 and h >= stop):
                ex = (min(o, stop) if sig > 0 else max(o, stop)) if j > i + 1 else stop
                res = (j, ((ex - px) * sig - cost) / R)
                break
            if fam == "J1":
                M = p["M"]
                done = cc < min(x[3] for x in b[j - M:j]) if sig > 0 else cc > max(x[2] for x in b[j - M:j])
            elif fam == "J2":
                done = (rs[j] is not None and ((sig > 0 and rs[j] > 70) or (sig < 0 and rs[j] < 30))) or j - i >= 10
            else:
                m = sum(c[j - 19:j + 1]) / 20
                done = (cc >= m if sig > 0 else cc <= m) or j - i >= 10
            if done:
                res = (j, ((cc - px) * sig - cost) / R)
                break
        if res is None:
            break
        out.append({"d": b[i][0].strftime("%Y-%m-%d %H:%M"), "r": res[1]})
        i = res[0] + 1
    return out


def st(rs):
    v = [x["r"] for x in rs]
    if len(v) < 2:
        return {"n": len(v)}
    m, sd = statistics.mean(v), statistics.stdev(v)
    w, l_ = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
    h = len(v) // 2
    return {"n": len(v), "avg": round(m, 3), "pf": round(w / l_, 2) if l_ else 99, "t": round(m / (sd / math.sqrt(len(v))), 2) if sd else 0,
            "h1": round(statistics.mean(v[:h]), 3), "h2": round(statistics.mean(v[h:]), 3)}


def grid():
    for N in (20, 50):
        for k in (2, 3):
            for M in (10, 20):
                yield "J1", {"N": N, "k": k, "M": M}
    for th in (5, 10):
        yield "J2", {"th": th}
    yield "J3", {}


def main():
    from google.cloud import storage
    bk = storage.Client().bucket(um.GCS_BUCKET)
    raw = {}
    for x in bk.list_blobs(prefix=um.GCS_BARS):
        try:
            raw[x.name.rsplit("/", 1)[1][:10]] = json.loads(bk.blob(x.name).download_as_bytes())
        except Exception:  # noqa: BLE001
            continue
    b1 = um.load(raw)
    _, ctx = um.daily(b1)
    hb = hourly(b1)
    tr_m = [(1 if ctx[um.session_date(t)]["pdc"] > ctx[um.session_date(t)]["sma"] else -1) if um.session_date(t) in ctx else 0 for t, *_ in hb]
    import yfinance as yf
    dfh = yf.download("NQ=F", period="730d", interval="1h", progress=False, auto_adjust=False)
    if hasattr(dfh.columns, "levels"):
        dfh.columns = [c[0] for c in dfh.columns]
    nqh = [(t.to_pydatetime().replace(tzinfo=None), float(r.Open), float(r.High), float(r.Low), float(r.Close)) for t, r in zip(dfh.index, dfh.itertuples())]
    nqd = ds.load("NQ=F")
    dc = {d: c for d, _, _, _, c in nqd}
    dk = sorted(dc)
    def nq_tr(t):
        prev = [dc[d] for d in dk if d < t.strftime("%Y-%m-%d")][-20:]
        return 0 if len(prev) < 20 else (1 if prev[-1] > sum(prev) / 20 else -1)
    cache = {}
    tr_n = []
    for t, *_ in nqh:
        k = t.strftime("%Y-%m-%d")
        if k not in cache:
            cache[k] = nq_tr(t)
        tr_n.append(cache[k])
    rows = []
    for fam, p in grid():
        m = st(sim(hb, tr_m, fam, p, 4.0))
        q = st(sim(nqh, tr_n, fam, p, 1.0))
        ok = bool(m.get("n", 0) >= 60 and m.get("avg", -9) >= 0.15 and m.get("pf", 0) >= 1.3 and m.get("t", 0) >= 2.0
                  and m.get("h1", -9) > 0 and m.get("h2", -9) > 0 and q.get("avg", -9) > 0)
        rows.append({"key": f"{fam} {json.dumps(p, sort_keys=True)}", "MHI": m, "NQ": q, "qualified": ok})
        print(fam, p, "MHI", m, "NQ", q, "✅" if ok else "")
    okr = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["MHI"]["t"])
    res = {"mhi_from": str(hb[0][0]), "mhi_to": str(hb[-1][0]), "rows": rows, "pick": okr[0] if okr else None}
    bk.blob("longfei/strategy_search/batch5.json").upload_from_string(json.dumps(res, ensure_ascii=False), content_type="application/json")
    print("合格", len(okr))


if __name__ == "__main__":
    main()
