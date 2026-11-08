"""[IDEAS #2029] 策略搜尋第二十七批：只 MHI（#2021 寬條件；使用者 11-09「直至 MHI、NQ、ES 每個 3 個、總共 9 個先停」；而家 NQ 3、ES 3、MHI 0）。

家族（全部未喺 MHI 測過）：
  G1 大陽延續（政策／消息驅動嘅爆發）：當日升幅 > k×ATR(14)（k＝2.0／2.5）而收市喺當日波幅頂 25% → 翌日開市買，持有 H 日（10／20），止蝕 3×ATR；
     雙向版：當日跌幅 > k×ATR 而收市喺底 25% → 做淡。
  G2 收窄後突破（#2024 C2 只喺 ES 試過）：ATR 喺過去 250 日最低 q 百分位（q＝20／30）出現後 10 日內，收市破 60 日高 → 翌日開市買；
     吊燈 3×ATR 出、初始止蝕 3×ATR；雙向版：破 60 日低做淡。
  G3 Aroon(25)（#2023 B3 只喺 ES 試過）：升 > u（70／90）而跌 < 30 由唔成立變成立 → 翌日開市買；升 < 50 出；初始止蝕 3×ATR；雙向版鏡像。
跨市場：台、韓、日、澳、上證。成本、R 同之前；最長持倉 250 日。

預先登記（11-09，跑之前寫，唔再改）＝ #2021 MHI 寬條件；同一家族只計 t 最高一個；標明嚴／寬。
合格 → 影子前向（30 張或 6 個月），使用者批先真倉；冇 → 第二十八批另行登記。
"""
import json
import daily_search as ds
import batch13 as b13
import batch15 as b15
import batch21 as b21

CROSS_AS = b13.CROSS_AS


def run27(b, ind, fam, p):
    c, atr = ind["c"], ind["atr"]
    both = p.get("both", False)
    n = len(b)
    if fam == "G2":
        low = [False] * n
        for i in range(260, n):
            w = sorted(x for x in atr[i - 250:i] if x is not None)
            if len(w) > 200 and atr[i] is not None:
                low[i] = atr[i] <= w[int(len(w) * p["q"] / 100)]
    if fam == "G3":
        au, ad = b21.aroon(b)
        def st(i):
            if au[i] is None:
                return 0
            return 1 if au[i] > p["u"] and ad[i] < 30 else (-1 if ad[i] > p["u"] and au[i] < 30 else 0)
    out, i = [], 261
    while i < n - 2:
        if atr[i] is None:
            i += 1
            continue
        sig, a0 = 0, atr[i]
        if fam == "G1":
            rng = b[i][2] - b[i][3]
            mv = c[i] - c[i - 1]
            if rng > 0:
                pos = (c[i] - b[i][3]) / rng
                if mv > p["k"] * a0 and pos >= 0.75:
                    sig = 1
                elif both and -mv > p["k"] * a0 and pos <= 0.25:
                    sig = -1
        elif fam == "G2":
            if any(low[i - 9:i + 1]):
                if c[i] > max(x[2] for x in b[i - 60:i]):
                    sig = 1
                elif both and c[i] < min(x[3] for x in b[i - 60:i]):
                    sig = -1
        else:
            s0, s1 = st(i), st(i - 1)
            sig = 1 if s0 == 1 and s1 != 1 else (-1 if both and s0 == -1 and s1 != -1 else 0)
        if not sig:
            i += 1
            continue
        px = b[i + 1][1]
        if fam == "G1":
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, lambda j: False, p["H"], 2 * a0)
        elif fam == "G2":
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, b15.chand(b, c, atr, a0, sig, 3, px), 250, 2 * a0)
        else:
            ef = (lambda j, s=sig: au[j] is not None and (au[j] < 50 if s > 0 else ad[j] < 50))
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, ef, 250, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid():
    for both in (False, True):
        for k in (2.0, 2.5):
            for H in (10, 20):
                yield "G1", {"k": k, "H": H, "both": both}
        for q in (20, 30):
            yield "G2", {"q": q, "both": both}
        for u in (70, 90):
            yield "G3", {"u": u, "both": both}


def main():
    tks = {"MHI": "^HSI", **CROSS_AS}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    rows = []
    for fam, p in grid():
        tr = run27(data["MHI"], ind["MHI"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for c in CROSS_AS if c in data and ds.stats([x for x in run27(data[c], ind[c], fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        c234 = {"c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        loose = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.25 and s15.get("pf", 0) >= 1.40 and s15.get("t", 0) >= 1.8)
        strict = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
        ok = loose and all(c234.values())
        rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                     "cross_pos": cpos, "c1": loose, "c1_strict": strict, **c234, "prior_overlap": 0, "qualified": ok,
                     "grade": ("嚴" if strict else "寬") if ok else None})
        print("MHI", fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, c234, "✅" if ok else "")
    best = {}
    for r in rows:
        if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
            best[r["fam"]] = r
    print("== MHI 合格家族", {k: v["grade"] for k, v in best.items()})
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch27.json").upload_from_string(
        json.dumps({"MHI": {"rows": rows, "qualified_by_family": best}}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
