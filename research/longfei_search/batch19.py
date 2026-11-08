"""[IDEAS #2021] 策略搜尋第十九批：MHI 專用寬條件（使用者 11-09 揀「1 先做」：MHI 另外預先登記較寬條件，只用喺新批次）。

背景：#2003–#2020 共 18 批、約 300 組 MHI 設定冇一個過 #2004 四條。使用者批准 MHI 用較寬條件，但：
  · 只用喺今批及之後新登記嘅 MHI 家族；之前睇過嘅設定（例如 #2019 X3 冬季 t 1.85）唔可以倒套返嚟計。
  · 所有家族、參數今次一次寫死。

家族（全部未喺 MHI 測過）：
  Z1 月度反轉：上個月報酬 < −k×過去 36 個月月報酬標準差（k＝1.0／1.5）→ 月尾收市買，下月尾收市賣；雙向版 > +k 做淡。
  Z2 週線 Donchian：週收市破過去 N 週最高（N＝13／26）→ 週尾收市買；週收市跌穿過去 N/2 週最低出；雙向版鏡像。
  Z3 RSI(14) 波段：RSI14 < th（30／25）→ 翌日開市買；RSI14 > 50 收市出；止蝕 4×ATR；最長 60 日；雙向版 RSI14 > 100−th 做淡。
  Z4 遠離 200 日線：收市 < SMA200 ×（1 − d）（d＝0.10／0.15）→ 翌日開市買；收市 > SMA50 出；止蝕 4×ATR；最長 60 日；
     雙向版收市 > SMA200 ×（1 + d）做淡、收市 < SMA50 出。
跨市場（冇參與揀選）：台灣、韓國、日經、澳洲、上證。成本 0.03% 來回；R＝2×ATR(14)。

預先登記（11-09，跑之前寫，唔再改）——MHI 寬條件：
  ① 2015→ n ≥ 30、平均 ≥ +0.25R、PF ≥ 1.40、t ≥ 1.8；② 2021→ 平均 > 0、年份 ≥ 4／6 正；
  ③ 亞洲 5 隻 ≥ 4 隻 2015→ 平均 > 0；④ 2000–2014 平均 > 0。
  同一家族只計 t 最高一個。同時報告係咪過埋 #2004 嚴格條件（標明「寬」定「嚴」）。
  合格 → 影子前向（同 C2：30 張或 6 個月，平均 R > 0、PF ≥ 1.2），使用者批先真倉；冇 → 第二十批另行登記。
"""
import json
import math
import statistics
from datetime import date
import daily_search as ds
import batch13 as b13

CROSS_AS = b13.CROSS_AS


def rsi14(c):
    n = len(c)
    out = [None] * n
    ag = al = 0.0
    for i in range(1, n):
        d = c[i] - c[i - 1]
        g, l_ = max(d, 0), max(-d, 0)
        if i <= 14:
            ag += g / 14; al += l_ / 14
            if i < 14:
                continue
        else:
            ag = (ag * 13 + g) / 14; al = (al * 13 + l_) / 14
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def run19(b, ind, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    both = p.get("both", False)
    n, out = len(b), []
    if fam == "Z1":
        ends = [i for i in range(n - 1) if b[i + 1][0][:7] != b[i][0][:7]]
        mr = [None] + [math.log(c[ends[a]] / c[ends[a - 1]]) for a in range(1, len(ends))]
        for a in range(37, len(ends) - 1):
            e, x = ends[a], ends[a + 1]
            if atr[e] is None:
                continue
            sd = statistics.pstdev(mr[a - 36:a])
            side = 1 if mr[a] < -p["k"] * sd else (-1 if both and mr[a] > p["k"] * sd else 0)
            if side:
                out.append({"d": b[e][0], "r": ((c[x] - c[e]) * side - ds.COST * c[e]) / (2 * atr[e])})
        return out
    if fam == "Z2":
        wk = lambda i: date.fromisoformat(b[i][0]).isocalendar()[:2]  # noqa: E731
        ends = [i for i in range(n - 1) if wk(i + 1) != wk(i)]
        wc = [c[e] for e in ends]
        N, M = p["N"], p["N"] // 2
        a = N
        while a < len(ends) - 1:
            e = ends[a]
            if atr[e] is None:
                a += 1
                continue
            side = 1 if wc[a] > max(wc[a - N:a]) else (-1 if both and wc[a] < min(wc[a - N:a]) else 0)
            if not side:
                a += 1
                continue
            z = a + 1
            while z < len(ends) - 1 and not (wc[z] < min(wc[z - M:z]) if side > 0 else wc[z] > max(wc[z - M:z])):
                z += 1
            x = ends[z]
            out.append({"d": b[e][0], "r": ((c[x] - c[e]) * side - ds.COST * c[e]) / (2 * atr[e])})
            a = z if both else z + 1
        return out
    r14 = rsi14(c) if fam == "Z3" else None
    i = 201
    while i < n - 2:
        if atr[i] is None or S[200][i] is None:
            i += 1
            continue
        sig = 0
        if fam == "Z3" and r14[i] is not None:
            sig = 1 if r14[i] < p["th"] else (-1 if both and r14[i] > 100 - p["th"] else 0)
        elif fam == "Z4":
            sig = 1 if c[i] < S[200][i] * (1 - p["d"]) else (-1 if both and c[i] > S[200][i] * (1 + p["d"]) else 0)
        if not sig:
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        if fam == "Z3":
            ef = (lambda j, s=sig: r14[j] is not None and (r14[j] > 50 if s > 0 else r14[j] < 50))
        else:
            ef = (lambda j, s=sig: c[j] > S[50][j] if s > 0 else c[j] < S[50][j])
        j, r = ds.trade(b, i + 1, sig, px, px - sig * 4 * a0, ef, 60, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid():
    for both in (False, True):
        for k in (1.0, 1.5):
            yield "Z1", {"k": k, "both": both}
        for N in (13, 26):
            yield "Z2", {"N": N, "both": both}
        for th in (30, 25):
            yield "Z3", {"th": th, "both": both}
        for d in (0.10, 0.15):
            yield "Z4", {"d": d, "both": both}


def main():
    tks = {"MHI": "^HSI", **CROSS_AS}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    rows = []
    for fam, p in grid():
        tr = run19(data["MHI"], ind["MHI"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for c in CROSS_AS if c in data and ds.stats([x for x in run19(data[c], ind[c], fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch19.json").upload_from_string(
        json.dumps({"MHI": {"rows": rows, "qualified_by_family": best}}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
