"""[IDEAS #2027] 策略搜尋第二十五批：市場內部風險偏好比率（使用者 11-09「直至 MHI、NQ、ES 每個 3 個、總共 9 個先停」；而家 NQ 3、ES 2、MHI 0）。

ES（#2004 嚴格四條），比率 > 自己 L 日平均＝開（L＝50／100），開 → 翌日開市買、關收市出、初始止蝕 3×ATR（batch18.run18 規則）：
  R1 XLY ÷ XLP（非必需對必需消費）
  R2 IWM ÷ SPY（小型對大型股，2000 起）
  R3 SMH ÷ SPY（半導體對大市，2000 起）
  R4 道氏理論：^DJT（運輸）同 ^DJI（工業）都 > 自己 L 日平均（L＝100／200）＝開
MHI（#2021 寬條件）：
  R5 EEM ÷ SPY（新興市場對標普，2003 起）> L 日平均（L＝50／100）＝開；只做好＋雙向（關＝做淡）。
時間：美國市場用同日；恒指、日經、DAX、FTSE、亞洲跨市場用之前一個美國交易日（唔偷看）。跨市場、成本、R 同之前；最長持倉 250 日。

預先登記（11-09，跑之前寫，唔再改）：ES ＝ #2004 嚴格四條（④ 用有數據嘅 2000–2014 年份）；MHI ＝ #2021 寬條件；
同一家族只計 t 最高一個；ES 同 Donchian 20／12 個月動量入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第二十六批另行登記。
"""
import json
import daily_search as ds
import batch6 as b6
import batch13 as b13
import batch18 as b18

CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
US_SAME = {"ES", "YM", "RTY"}


def both_on(s1, s2, L):
    d1, o1 = b18.state_on(s1, L)
    d2, o2 = b18.state_on(s2, L)
    m2 = dict(zip(d2, o2))
    d = [x for x in d1 if x in m2]
    m1 = dict(zip(d1, o1))
    on = [None if m1[x] is None or m2[x] is None else (m1[x] and m2[x]) for x in d]
    return d, on


def grid():
    for fam in ("R1", "R2", "R3"):
        for L in (50, 100):
            yield "ES", fam, {"L": L, "both": False}
    for L in (100, 200):
        yield "ES", "R4", {"L": L, "both": False}
    for both in (False, True):
        for L in (50, 100):
            yield "MHI", "R5", {"L": L, "both": both}


def main():
    extra = {"XLY": "XLY", "XLP": "XLP", "IWM": "IWM", "SPY": "SPY", "SMH": "SMH", "DJT": "^DJT", "DJI": "^DJI", "EEM": "EEM"}
    tks = {"MHI": "^HSI", "ES": "ES=F", **CROSS_US, **CROSS_AS, **extra}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    sig = {"R1": b18.ratio_series(data["XLY"], data["XLP"]), "R2": b18.ratio_series(data["IWM"], data["SPY"]),
           "R3": b18.ratio_series(data["SMH"], data["SPY"]), "R5": b18.ratio_series(data["EEM"], data["SPY"])}
    for k, v in sig.items():
        print(k, len(v), min(v) if v else None)
    djt, dji = b18.ratio_series(data["DJT"]), b18.ratio_series(data["DJI"])
    states = {}
    for fam, s in sig.items():
        for L in (50, 100):
            states[(fam, L)] = b18.state_on(s, L)
    for L in (100, 200):
        states[("R4", L)] = both_on(djt, dji, L)
    data = {mk: b for mk, b in data.items() if len(b) > 300 and mk not in extra}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    prior = {x["d"] for x in ds.run(data["ES"], ind["ES"], "F2", {"N": 20, "k": 3, "M": 10, "both": False})}
    prior |= {x["d"] for x in b6.run6(data["ES"], ind["ES"], "K1", {"L": 12, "both": False})}

    def run(mk, fam, p):
        sd, on = states[(fam, p["L"])]
        return b18.run18(data[mk], ind[mk], sd, on, mk not in US_SAME, p["both"]) if sd else []

    res = {"MHI": {"rows": []}, "ES": {"rows": []}}
    for mk, fam, p in grid():
        cross = CROSS_AS if mk == "MHI" else CROSS_US
        tr = run(mk, fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for c in cross if c in data and ds.stats([x for x in run(c, fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        c234 = {"c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        strict = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
        loose = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.25 and s15.get("pf", 0) >= 1.40 and s15.get("t", 0) >= 1.8)
        ov = round(sum(1 for x in tr if x["d"] in prior) / len(tr), 2) if tr and mk == "ES" else 0
        c1 = loose if mk == "MHI" else strict
        ok = c1 and all(c234.values()) and ov < 0.70
        res[mk]["rows"].append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                                "cross_pos": cpos, "c1": c1, "c1_strict": strict, **c234, "prior_overlap": ov, "qualified": ok,
                                "grade": ("嚴" if strict else "寬") if ok else None})
        print(mk, fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, c234, "重疊", ov, "✅" if ok else "")
    for mk in res:
        best = {}
        for r in res[mk]["rows"]:
            if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
                best[r["fam"]] = r
        res[mk]["qualified_by_family"] = best
        print("==", mk, "合格家族", {k: v["grade"] for k, v in best.items()})
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch25.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
