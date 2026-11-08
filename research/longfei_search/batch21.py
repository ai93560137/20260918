"""[IDEAS #2023] 策略搜尋第二十一批：只 ES（使用者 11-09「MHI 先靠 C2 影子前向」→ 研究集中補 ES 第三個；而家 NQ 3、ES 2）。

家族（全部未喺 ES 測過）：
  B1 雙均線交叉：SMA(a) 上穿 SMA(b) → 翌日開市買；下穿收市出；初始止蝕 3×ATR。(a,b)＝(10,50)／(20,100)
  B2 回歸趨勢質素：L 日收市線性回歸斜率 > 0 而 R² > 0.5，由唔成立變成立 → 翌日開市買；斜率 ≤ 0 收市出；初始止蝕 3×ATR。L＝50／100
  B3 Aroon(25)：Aroon 升 > 70 而 Aroon 跌 < 30，由唔成立變成立 → 翌日開市買；Aroon 升 < 50 收市出；初始止蝕 3×ATR。門檻 u＝70／90
  B4 拋物線 SAR：SAR 由上方轉到下方 → 翌日開市買；SAR 轉返上方收市出。(步長, 上限)＝(0.02,0.2)／(0.01,0.1)
只做好。跨市場 YM、RTY、日經、DAX、FTSE；成本、R 同之前；最長持倉 250 日。

預先登記（11-09，跑之前寫，唔再改）＝ #2004 嚴格四條；同一家族只計 t 最高一個；
同 ES 已合格策略（Donchian 20 #2004、12 個月動量 #2018）入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第二十二批另行登記。
"""
import json
import daily_search as ds
import batch6 as b6
import batch13 as b13

CROSS_US = b13.CROSS_US
MAXD = 250


def sma(v, k):
    out, s = [None] * len(v), 0.0
    for i in range(len(v)):
        s += v[i]
        if i >= k:
            s -= v[i - k]
        if i >= k - 1:
            out[i] = s / k
    return out


def regr(c, L):
    n = len(c)
    slope, r2 = [None] * n, [None] * n
    xs = list(range(L))
    mx = (L - 1) / 2
    sxx = sum((x - mx) ** 2 for x in xs)
    for i in range(L - 1, n):
        y = c[i - L + 1:i + 1]
        my = sum(y) / L
        sxy = sum((x - mx) * (v - my) for x, v in zip(xs, y))
        syy = sum((v - my) ** 2 for v in y)
        slope[i] = sxy / sxx
        r2[i] = (sxy * sxy) / (sxx * syy) if syy else 0.0
    return slope, r2


def aroon(b, L=25):
    n = len(b)
    up, dn = [None] * n, [None] * n
    for i in range(L, n):
        w = b[i - L:i + 1]
        hi = max(range(L + 1), key=lambda k: w[k][2])
        lo = min(range(L + 1), key=lambda k: w[k][3])
        up[i], dn[i] = 100 * hi / L, 100 * lo / L
    return up, dn


def psar(b, step, mx):
    n = len(b)
    trend = [0] * n
    up, sar, ep, af = True, b[0][3], b[0][2], step
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, b[i - 1][3], b[i - 2][3] if i >= 2 else b[i - 1][3])
            if b[i][3] < sar:
                up, sar, ep, af = False, ep, b[i][3], step
            elif b[i][2] > ep:
                ep, af = b[i][2], min(af + step, mx)
        else:
            sar = max(sar, b[i - 1][2], b[i - 2][2] if i >= 2 else b[i - 1][2])
            if b[i][2] > sar:
                up, sar, ep, af = True, ep, b[i][2], step
            elif b[i][3] < ep:
                ep, af = b[i][3], min(af + step, mx)
        trend[i] = 1 if up else -1
    return trend


def run21(b, ind, fam, p):
    c, atr = ind["c"], ind["atr"]
    n = len(b)
    if fam == "B1":
        fa, sb = sma(c, p["a"]), sma(c, p["b"])
        st = [fa[i] is not None and sb[i] is not None and fa[i] > sb[i] for i in range(n)]
    elif fam == "B2":
        sl, r2 = regr(c, p["L"])
        st = [sl[i] is not None and sl[i] > 0 and r2[i] > 0.5 for i in range(n)]
        ex = [sl[i] is not None and sl[i] <= 0 for i in range(n)]
    elif fam == "B3":
        au, ad = aroon(b)
        st = [au[i] is not None and au[i] > p["u"] and ad[i] < 30 for i in range(n)]
        ex = [au[i] is not None and au[i] < 50 for i in range(n)]
    else:
        tr = psar(b, p["s"], p["m"])
        st = [x == 1 for x in tr]
    out, i = [], 201
    while i < n - 2:
        if atr[i] is None or not (st[i] and not st[i - 1]):
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        if fam in ("B1", "B4"):
            ef = (lambda j: not st[j])
            stop = px - 3 * a0 if fam == "B1" else None
        else:
            ef = (lambda j: ex[j])
            stop = px - 3 * a0
        j, r = ds.trade(b, i + 1, 1, px, stop, ef, MAXD, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid():
    for a, bb in ((10, 50), (20, 100)):
        yield "B1", {"a": a, "b": bb}
    for L in (50, 100):
        yield "B2", {"L": L}
    for u in (70, 90):
        yield "B3", {"u": u}
    for s, m in ((0.02, 0.2), (0.01, 0.1)):
        yield "B4", {"s": s, "m": m}


def main():
    tks = {"ES": "ES=F", **CROSS_US}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    prior = {x["d"] for x in ds.run(data["ES"], ind["ES"], "F2", {"N": 20, "k": 3, "M": 10, "both": False})}
    prior |= {x["d"] for x in b6.run6(data["ES"], ind["ES"], "K1", {"L": 12, "both": False})}
    rows = []
    for fam, p in grid():
        tr = run21(data["ES"], ind["ES"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for c in CROSS_US if c in data and ds.stats([x for x in run21(data[c], ind[c], fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        ov = round(sum(1 for x in tr if x["d"] in prior) / len(tr), 2) if tr else 0
        q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
             "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        indep = ov < 0.70
        rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                     "cross_pos": cpos, "prior_overlap": ov, **q, "independent": indep, "qualified": all(q.values()) and indep})
        print("ES", fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, "重疊", ov, q, "✅" if rows[-1]["qualified"] else "")
    best = {}
    for r in rows:
        if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
            best[r["fam"]] = r
    print("== ES 合格家族", list(best))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch21.json").upload_from_string(
        json.dumps({"ES": {"rows": rows, "qualified_by_family": best}}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
