"""[IDEAS #2022] 策略搜尋第二十批：MHI 寬條件（同 #2021；使用者 11-09 揀「1 先做」）。

家族（全部未喺 MHI 測過）：
  A1 週線趨勢＋日線回吐：最近一個已完成週收市 > 13 週週收市平均（升勢）而 RSI2 < 10 → 翌日開市買；吊燈 3×ATR 出、初始止蝕 3×ATR；
     雙向版：週線跌勢而 RSI2 > 90 做淡。參數 W＝13／26（週均線長度）。
  A2 自身波幅急升：5 日實現波幅 > m×60 日實現波幅（m＝1.8／2.2）而收市 < SMA20 → 翌日開市買，持有 H 日（10／20），止蝕 4×ATR。只做好。
  A3 連跌幾週：連續 k 週週收市下跌（k＝3／4）→ 週尾收市買，持有 h 週（2／4）；雙向版連升 k 週做淡。
  A4 KAMA＋效率比：收市上穿 KAMA(10,2,30) 而 10 日效率比 > th（0.3／0.4）→ 翌日開市買；收市跌穿 KAMA 出；初始止蝕 2×ATR；雙向版鏡像。
跨市場、成本、R 同 #2021。

預先登記（11-09，跑之前寫，唔再改）＝ #2021 MHI 寬條件（① n≥30、+0.25R、PF≥1.40、t≥1.8；② 2021→ 平均>0、≥4/6；③ 亞洲 ≥4/5；④ 2000–14>0）；
同一家族只計 t 最高一個；同時標明嚴／寬。合格 → 影子前向（30 張或 6 個月），使用者批先真倉；冇 → 第二十一批另行登記。
"""
import json
from datetime import date
import daily_search as ds
import batch13 as b13
import batch15 as b15

CROSS_AS = b13.CROSS_AS


def kama(c, n=10, f=2, s=30):
    out, er = [None] * len(c), [None] * len(c)
    fc, sc = 2 / (f + 1), 2 / (s + 1)
    for i in range(n, len(c)):
        ch = abs(c[i] - c[i - n])
        vol = sum(abs(c[j] - c[j - 1]) for j in range(i - n + 1, i + 1))
        er[i] = ch / vol if vol else 0.0
        a = (er[i] * (fc - sc) + sc) ** 2
        out[i] = c[i] if out[i - 1] is None else out[i - 1] + a * (c[i] - out[i - 1])
    return out, er


def run20(b, ind, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    both = p.get("both", False)
    n, out = len(b), []
    wk = lambda i: date.fromisoformat(b[i][0]).isocalendar()[:2]  # noqa: E731
    if fam == "A3":
        ends = [i for i in range(n - 1) if wk(i + 1) != wk(i)]
        k, h = p["k"], p["h"]
        a = k + 1
        while a < len(ends) - h:
            e = ends[a]
            ch = [c[ends[a - q]] - c[ends[a - q - 1]] for q in range(k)]
            side = 1 if all(x < 0 for x in ch) else (-1 if both and all(x > 0 for x in ch) else 0)
            if side and atr[e] is not None:
                x = ends[a + h]
                out.append({"d": b[e][0], "r": ((c[x] - c[e]) * side - ds.COST * c[e]) / (2 * atr[e])})
                a += h
                continue
            a += 1
        return out
    if fam == "A1":
        ends = [i for i in range(n - 1) if wk(i + 1) != wk(i)]
        W = p["W"]
        trend = [0] * n
        a = 0
        for i in range(n):
            while a + 1 < len(ends) and ends[a + 1] <= i:
                a += 1
            if a >= W and ends[a] <= i:
                wc = [c[ends[q]] for q in range(a - W + 1, a + 1)]
                trend[i] = 1 if c[ends[a]] > sum(wc) / W else -1
    if fam == "A2":
        v5, v60 = b15.rvol(c, 5), b15.rvol(c, 60)
    if fam == "A4":
        km, er = kama(c)
    i = 201
    while i < n - 2:
        if atr[i] is None:
            i += 1
            continue
        sig = 0
        r2 = ind["rsi2"][i]
        if fam == "A1" and r2 is not None:
            sig = 1 if trend[i] == 1 and r2 < 10 else (-1 if both and trend[i] == -1 and r2 > 90 else 0)
        elif fam == "A2":
            if v5[i] is not None and v60[i] and v5[i] > p["m"] * v60[i] and c[i] < sum(c[i - 19:i + 1]) / 20:
                sig = 1
        elif fam == "A4" and km[i - 1] is not None:
            up = c[i] > km[i] and c[i - 1] <= km[i - 1]
            dn = c[i] < km[i] and c[i - 1] >= km[i - 1]
            if er[i] > p["th"]:
                sig = 1 if up else (-1 if both and dn else 0)
        if not sig:
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        if fam == "A1":
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, b15.chand(b, c, atr, a0, sig, 3, px), 250, 2 * a0)
        elif fam == "A2":
            j, r = ds.trade(b, i + 1, 1, px, px - 4 * a0, lambda j: False, p["H"], 2 * a0)
        else:
            ef = (lambda j, s=sig: c[j] < km[j] if s > 0 else c[j] > km[j])
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 2 * a0, ef, 250, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j if fam == "A4" else j + 1
    return out


def grid():
    for both in (False, True):
        for W in (13, 26):
            yield "A1", {"W": W, "both": both}
        for k in (3, 4):
            for h in (2, 4):
                yield "A3", {"k": k, "h": h, "both": both}
        for th in (0.3, 0.4):
            yield "A4", {"th": th, "both": both}
    for m in (1.8, 2.2):
        for H in (10, 20):
            yield "A2", {"m": m, "H": H}


def main():
    tks = {"MHI": "^HSI", **CROSS_AS}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    rows = []
    for fam, p in grid():
        tr = run20(data["MHI"], ind["MHI"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for c in CROSS_AS if c in data and ds.stats([x for x in run20(data[c], ind[c], fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        c234 = {"c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        loose = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.25 and s15.get("pf", 0) >= 1.40 and s15.get("t", 0) >= 1.8)
        strict = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
        ok = loose and all(c234.values())
        rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                     "cross_pos": cpos, "c1_loose": loose, "c1_strict": strict, **c234, "qualified": ok,
                     "grade": ("嚴" if strict else "寬") if ok else None})
        print("MHI", fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, c234, "寬" if loose else "", "嚴" if strict else "", "✅" if ok else "")
    best = {}
    for r in rows:
        if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
            best[r["fam"]] = r
    print("== MHI 合格家族", {k: v["grade"] for k, v in best.items()})
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch20.json").upload_from_string(
        json.dumps({"MHI": {"rows": rows, "qualified_by_family": best}}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
