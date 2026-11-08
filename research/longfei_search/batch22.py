"""[IDEAS #2024] 策略搜尋第二十二批：只 ES（補第三個；而家 NQ 3、ES 2；MHI 靠 C2 影子）。

家族（全部未喺 ES 測過）：
  C1 週線 Donchian（#2021 Z2 只喺 MHI 試過）：週收市破過去 N 週最高（N＝13／26）→ 週尾收市買；跌穿過去 N/2 週最低出。只做好。
  C2 收窄後突破：ATR(14) 喺過去 250 日處於最低 q 百分位（q＝20／30）期間（過去 10 日內有出現），收市破 60 日高 → 翌日開市買；
     吊燈 3×ATR 出、初始止蝕 3×ATR。
  C3 均線多頭排列：收市 > SMA20 > SMA50 > SMA100 > SMA200，由唔成立變成立 → 翌日開市買；收市 < SMA f 出（f＝50／100）；初始止蝕 3×ATR。
跨市場 YM、RTY、日經、DAX、FTSE；成本、R 同之前。

預先登記（11-09，跑之前寫，唔再改）＝ #2004 嚴格四條；同一家族只計 t 最高一個；
同 ES Donchian 20／12 個月動量入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第二十三批另行登記。
"""
import json
import daily_search as ds
import batch6 as b6
import batch13 as b13
import batch15 as b15
import batch19 as b19
import batch21 as b21

CROSS_US = b13.CROSS_US


def run22(b, ind, fam, p):
    if fam == "C1":
        return b19.run19(b, ind, "Z2", {"N": p["N"], "both": False})
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    n = len(b)
    if fam == "C2":
        low = [False] * n
        for i in range(260, n):
            w = sorted(x for x in atr[i - 250:i] if x is not None)
            if len(w) > 200 and atr[i] is not None:
                low[i] = atr[i] <= w[int(len(w) * p["q"] / 100)]
    else:
        s20 = b21.sma(c, 20)
        st = [S[200][i] is not None and c[i] > s20[i] > S[50][i] > S[100][i] > S[200][i] for i in range(n)]
    out, i = [], 261
    while i < n - 2:
        if atr[i] is None:
            i += 1
            continue
        if fam == "C2":
            sig = any(low[i - 9:i + 1]) and c[i] > max(x[2] for x in b[i - 60:i])
        else:
            sig = st[i] and not st[i - 1]
        if not sig:
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        if fam == "C2":
            ef = b15.chand(b, c, atr, a0, 1, 3, px)
        else:
            f = S[p["f"]]
            ef = (lambda j, f=f: c[j] < f[j])
        j, r = ds.trade(b, i + 1, 1, px, px - 3 * a0, ef, 250, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid():
    for N in (13, 26):
        yield "C1", {"N": N}
    for q in (20, 30):
        yield "C2", {"q": q}
    for f in (50, 100):
        yield "C3", {"f": f}


def main():
    tks = {"ES": "ES=F", **CROSS_US}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    prior = {x["d"] for x in ds.run(data["ES"], ind["ES"], "F2", {"N": 20, "k": 3, "M": 10, "both": False})}
    prior |= {x["d"] for x in b6.run6(data["ES"], ind["ES"], "K1", {"L": 12, "both": False})}
    rows = []
    for fam, p in grid():
        tr = run22(data["ES"], ind["ES"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for c in CROSS_US if c in data and ds.stats([x for x in run22(data[c], ind[c], fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch22.json").upload_from_string(
        json.dumps({"ES": {"rows": rows, "qualified_by_family": best}}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
