"""[IDEAS #2011] 策略搜尋第九批：MHI 事件型——長假前效應、VIX 恐慌急升後買入。

#2003–#2010 MHI 趨勢／回歸／動量規則都唔合格。今批試兩類有經濟原因、之前未試過嘅事件：
  P 長假前：交易日之間相隔 ≥ 4 個日曆日（長假，例如農曆新年、復活節、聖誕）之前最後 k 個交易日：第 −k 日收市買，假期前最後一日收市賣。k∈{1,2,3}
     文獻：Ariel 1990、Kim & Park 1994（假期前效應）；香港農曆新年前效應（多篇亞洲研究）。
  V VIX 恐慌：^VIX 收市 > 過去 20 日平均 × m（m∈{1.3,1.5}）而恒指收市 < SMA20 → 翌日開市買，持有 H 日（H∈{5,10,20}）收市賣；止蝕 3×ATR。
     文獻：恐慌過度反應、VIX 急升後股指短期回報偏正（多篇實務研究）。
成本、R（2×ATR）同之前一樣。跨市場（冇參與揀選）：^TWII、^KS11、^N225、^AXJO、000001.SS（P 用各自長假，V 用同一個 VIX）。

預先登記（11-09，跑之前寫，唔再改）——同 #2004 四條（R 制）：
  ① MHI 2015→：n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0；② 2021→：平均 > 0、年份 ≥ 4／6 正；③ 亞洲 5 隻 ≥ 4 正；④ 2000–2014 平均 > 0。
  合格 → 影子前向；冇 → 第十批另行登記。
"""
import json
from datetime import date
import daily_search as ds
import batch3 as b3


def holiday(b, ind, k):
    d = [date.fromisoformat(x[0]) for x in b]
    c, atr = ind["c"], ind["atr"]
    out = []
    for i in range(len(b) - 1):
        if (d[i + 1] - d[i]).days >= 4 and i - k >= 0 and atr[i - k]:
            e = i - k
            out.append({"d": b[e][0], "r": ((c[i] - c[e]) - 0.0003 * c[e]) / (2 * atr[e])})
    return out


def vixspike(b, ind, vix, m, H):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    vk = sorted(vix)
    vi = {k: n for n, k in enumerate(vk)}
    out, i, n = [], 30, len(b)
    while i < n - 2:
        day = b[i][0]
        prev = [k for k in vk if k <= day]
        if not prev or atr[i] is None or S[5][i] is None:
            i += 1
            continue
        j0 = vi[prev[-1]]
        if j0 < 20:
            i += 1
            continue
        avg = sum(vix[vk[j]] for j in range(j0 - 20, j0)) / 20
        sma20 = sum(c[i - 19:i + 1]) / 20
        if vix[vk[j0]] > avg * m and c[i] < sma20:
            px = b[i + 1][1]
            j, r = ds.trade(b, i + 1, 1, px, px - 3 * atr[i], lambda j: False, H, 2 * atr[i])
            if j is None:
                break
            out.append({"d": day, "r": r})
            i = j + 1
        else:
            i += 1
    return out


def grid():
    for k in (1, 2, 3):
        yield "P", {"k": k}
    for m in (1.3, 1.5):
        for H in (5, 10, 20):
            yield "V", {"m": m, "H": H}


def main():
    data = {mk: ds.load(tk) for mk, tk in {"MHI": "^HSI", **b3.CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    vix = {x[0]: x[4] for x in ds.load("^VIX")}
    run = lambda mk, fam, p: holiday(data[mk], ind[mk], p["k"]) if fam == "P" else vixspike(data[mk], ind[mk], vix, p["m"], p["H"])  # noqa: E731
    rows = []
    for fam, p in grid():
        tr = run("MHI", fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for mk in b3.CROSS if ds.stats([x for x in run(mk, fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
             "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        rows.append({"key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch, "cross_pos": cpos, **q,
                     "qualified": all(q.values())})
        print(fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, q, "✅" if all(q.values()) else "")
    ok = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["since2015"]["t"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch9.json").upload_from_string(
        json.dumps({"rows": rows, "pick": ok[0] if ok else None}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
