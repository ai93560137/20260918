"""[IDEAS #2003] 龍飛陣策略搜尋第一批（使用者 11-08「參考天覆陣，繼續做研究直至找到合格 MHI、NQ 同 ES 策略先停」）。

做法跟天覆陣（research/strategy_search）：三段數據、預先登記、最終測試一次過，合格先影子前向 30 張，夠數再提案真倉（使用者批）。
數據（yfinance 日線，GitHub Actions 跑）：^HSI（MHI 代理，現貨冇夜市跳空）、NQ=F、ES=F。
  搜尋 2000-01→2014-12｜驗證 2015-01→2020-12｜最終 2021-01→而家（一次過，唔再調）。
成本：每次來回 0.03%（約 HSI 7 點、NQ 8 點、ES 2 點，含滑價）。R＝2×ATR(14)（入場時）。
執行：收市出訊號 → 翌日開市入（F6 例外：收市入、翌日收市出）；止蝕用最高／最低判斷，同一日掂止蝕當止蝕。

家族（全部參數一次寫死）：
  F1 均線趨勢：收市 > SMA(n) 做好（雙向版本 < SMA(n) 做淡），反穿出場。n∈{50,100,200}
  F2 Donchian 突破：收市破 N 日高（低）入；止蝕 k×ATR；M 日反向通道出。N∈{20,55} k∈{2,3} M∈{10,20} 只做好／雙向
  F3 RSI(2) 回吐：收市 > SMA200 而 RSI2 < th 做好；收市 > SMA5 或 5 日出；止蝕 3×ATR。th∈{5,10,15}
  F4 趨勢回調：收市 > SMA200 而收市係 N 日最低收市做好；收市 > 昨日高位或 T 日出；止蝕 2×ATR。N∈{3,5,7} T∈{5,10}
  F5 月尾月頭：月尾倒數第 k 個交易日收市買，新月第 d 個交易日收市賣。k∈{1,2,4} d∈{2,3,4}
  F6 IBS：收市 > SMA200 而 IBS=(收−低)/(高−低) < th，收市買、翌日收市賣。th∈{0.1,0.2,0.3}

選法（預先登記，11-08，跑之前寫，唔再改）：
  搜尋段：n ≥ 30、平均 R > 0、PF ≥ 1.10 先入圍；入圍再睇驗證段：n ≥ 15、PF ≥ 1.15；每個市場揀驗證平均 R 最高 3 個去最終。
  **合格（最終段一次過）**：n ≥ 40、平均 ≥ +0.15R、PF ≥ 1.30、t ≥ 1.5、最長連敗 ≤ 8、最終段有交易嘅年份 ≥ 4／6 正數。
  合格 → 影子前向 30 張（照天覆陣），夠數達標先提案真倉（固定 1 張，使用者批）；冇合格 → 第二批（新家族、重新登記），直至搵到。
輸出：GCS longfei/strategy_search/batch1.json、印表。
"""
import json
import math
import statistics

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
COST = 0.0003
SEGS = (("search", "2000-01-01", "2014-12-31"), ("valid", "2015-01-01", "2020-12-31"), ("final", "2021-01-01", "2099-12-31"))


def load(tk):
    import yfinance as yf
    df = yf.download(tk, start="1999-01-01", interval="1d", progress=False, auto_adjust=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df = df.dropna()
    return [(d.strftime("%Y-%m-%d"), float(r.Open), float(r.High), float(r.Low), float(r.Close)) for d, r in zip(df.index, df.itertuples())]


def indicators(b):
    n = len(b)
    c = [x[4] for x in b]
    tr = [b[0][2] - b[0][3]] + [max(b[i][2], b[i - 1][4]) - min(b[i][3], b[i - 1][4]) for i in range(1, n)]
    def sma(v, k):
        out, s = [None] * n, 0.0
        for i in range(n):
            s += v[i]
            if i >= k:
                s -= v[i - k]
            if i >= k - 1:
                out[i] = s / k
        return out
    atr = sma(tr, 14)
    rsi2 = [None] * n
    for i in range(2, n):
        g = [max(c[j] - c[j - 1], 0) for j in (i - 1, i)]
        l_ = [max(c[j - 1] - c[j], 0) for j in (i - 1, i)]
        ag, al = sum(g) / 2, sum(l_) / 2
        rsi2[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return {"c": c, "atr": atr, "rsi2": rsi2, "sma": {k: sma(c, k) for k in (5, 50, 100, 200)}}


def trade(b, i_in, side, px_in, stop, exit_fn, max_days, R):
    """由 i_in 日（含）開始逐日行；exit_fn(j) 回 True＝當日收市出。回 (出場日 index, pnl/R)。"""
    for j in range(i_in, min(i_in + max_days, len(b))):
        _, o, h, l, c = b[j]
        if stop is not None and ((side > 0 and l <= stop) or (side < 0 and h >= stop)):
            px = min(o, stop) if side > 0 and j > i_in else (max(o, stop) if side < 0 and j > i_in else stop)
            return j, ((px - px_in) * side - COST * px_in) / R
        if exit_fn(j) or j == min(i_in + max_days, len(b)) - 1:
            return j, ((c - px_in) * side - COST * px_in) / R
    return None, None


def run(b, ind, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    out, i, n = [], 201, len(b)
    while i < n - 2:
        sig = 0
        if fam == "F1":
            m = S[p["n"]][i]
            sig = 1 if c[i] > m and c[i - 1] <= S[p["n"]][i - 1] else (-1 if p["both"] and c[i] < m and c[i - 1] >= S[p["n"]][i - 1] else 0)
        elif fam == "F2":
            hi = max(x[2] for x in b[i - p["N"]:i]); lo = min(x[3] for x in b[i - p["N"]:i])
            sig = 1 if c[i] > hi else (-1 if p["both"] and c[i] < lo else 0)
        elif fam == "F3":
            sig = 1 if c[i] > S[200][i] and ind["rsi2"][i] is not None and ind["rsi2"][i] < p["th"] else 0
        elif fam == "F4":
            sig = 1 if c[i] > S[200][i] and c[i] <= min(c[i - p["N"] + 1:i + 1]) else 0
        elif fam == "F5":
            nxt = b[i + 1][0][:7] != b[i][0][:7] if p["k"] == 1 else (i + p["k"] < n and b[i + p["k"]][0][:7] != b[i][0][:7] and b[i + p["k"] - 1][0][:7] == b[i][0][:7])
            sig = 1 if nxt else 0
        elif fam == "F6":
            rng = b[i][2] - b[i][3]
            sig = 1 if rng > 0 and c[i] > S[200][i] and (c[i] - b[i][3]) / rng < p["th"] else 0
        if not sig or atr[i] is None:
            i += 1
            continue
        R = 2 * atr[i]
        if fam in ("F5", "F6"):                      # 收市入
            px, start = c[i], i + 1
        else:
            px, start = b[i + 1][1], i + 1
        if fam == "F1":
            m = p["n"]
            ef = (lambda j, s=sig, m=m: (c[j] < S[m][j]) if s > 0 else (c[j] > S[m][j]))
            j, r = trade(b, start, sig, px, None, ef, 400, R)
        elif fam == "F2":
            M = p["M"]
            ef = (lambda j, s=sig, M=M: c[j] < min(x[3] for x in b[j - M:j]) if s > 0 else c[j] > max(x[2] for x in b[j - M:j]))
            j, r = trade(b, start, sig, px, px - sig * p["k"] * atr[i], ef, 250, R)
        elif fam == "F3":
            j, r = trade(b, start, 1, px, px - 3 * atr[i], lambda j: c[j] > S[5][j], 5, R)
        elif fam == "F4":
            j, r = trade(b, start, 1, px, px - 2 * atr[i], lambda j: c[j] > b[j - 1][2], p["T"], R)
        elif fam == "F5":
            d = p["d"]
            cnt = {"n": 0}
            def ef(j, cnt=cnt, d=d, m0=b[i][0][:7]):
                if b[j][0][:7] != m0:
                    cnt["n"] += 1
                return cnt["n"] >= d
            j, r = trade(b, start, 1, px, None, ef, 10, R)
        else:
            j, r = trade(b, start, 1, px, None, lambda j: True, 1, R)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def stats(rs):
    v = [x["r"] for x in rs]
    if len(v) < 2:
        return {"n": len(v)}
    m, sd = statistics.mean(v), statistics.stdev(v)
    w, l_ = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
    streak = cur = 0
    for x in v:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    yrs = {}
    for x in rs:
        yrs.setdefault(x["d"][:4], []).append(x["r"])
    return {"n": len(v), "avg": round(m, 3), "pf": round(w / l_, 2) if l_ else 99, "t": round(m / (sd / math.sqrt(len(v))), 2) if sd else 0,
            "streak": streak, "years_pos": sum(1 for a in yrs.values() if sum(a) > 0), "years": len(yrs)}


def grid():
    for n in (50, 100, 200):
        for both in (False, True):
            yield "F1", {"n": n, "both": both}
    for N in (20, 55):
        for k in (2, 3):
            for M in (10, 20):
                for both in (False, True):
                    yield "F2", {"N": N, "k": k, "M": M, "both": both}
    for th in (5, 10, 15):
        yield "F3", {"th": th}
    for N in (3, 5, 7):
        for T in (5, 10):
            yield "F4", {"N": N, "T": T}
    for k in (1, 2, 4):
        for d in (2, 3, 4):
            yield "F5", {"k": k, "d": d}
    for th in (0.1, 0.2, 0.3):
        yield "F6", {"th": th}


def main():
    res = {}
    for mk, tk in MKTS.items():
        b = load(tk)
        ind = indicators(b)
        rows = []
        for fam, p in grid():
            tr = run(b, ind, fam, p)
            seg = {s: stats([x for x in tr if a <= x["d"] <= z]) for s, a, z in SEGS}
            rows.append({"fam": fam, "p": p, **seg, "final_trades": [x for x in tr if x["d"] >= "2021-01-01"]})
        ok = [r for r in rows if r["search"].get("n", 0) >= 30 and r["search"].get("avg", -1) > 0 and r["search"].get("pf", 0) >= 1.10
              and r["valid"].get("n", 0) >= 15 and r["valid"].get("pf", 0) >= 1.15]
        ok.sort(key=lambda r: -r["valid"]["avg"])
        picks = ok[:3]
        for r in picks:
            f = r["final"]
            r["qualified"] = bool(f.get("n", 0) >= 40 and f.get("avg", -9) >= 0.15 and f.get("pf", 0) >= 1.30 and f.get("t", 0) >= 1.5
                                  and f.get("streak", 99) <= 8 and f.get("years_pos", 0) >= 4)
        res[mk] = {"bars": len(b), "from": b[0][0], "to": b[-1][0], "configs": len(rows), "shortlist": len(ok),
                   "picks": [{k: v for k, v in r.items() if k != "final_trades"} for r in picks],
                   "all": [{k: v for k, v in r.items() if k != "final_trades"} for r in rows]}
        print(f"== {mk} {tk} {b[0][0]}→{b[-1][0]} 組合 {len(rows)} 入圍 {len(ok)}")
        for r in picks:
            print(" ", r["fam"], r["p"], "搜尋", r["search"], "驗證", r["valid"], "最終", r["final"], "合格" if r["qualified"] else "唔合格")
    txt = json.dumps(res, ensure_ascii=False)
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch1.json").upload_from_string(txt, content_type="application/json")


if __name__ == "__main__":
    main()
