"""[IDEAS #2028] 策略搜尋第二十六批：美股風險偏好五訊號投票（使用者 11-09「直至 MHI、NQ、ES 每個 3 個、總共 9 個先停」；而家 NQ 3、ES 2、MHI 0）。

五個狀態（每個成立 = 1 分）：XLY÷XLP > 100 日平均、IWM÷SPY > 50 日平均、SMH÷SPY > 100 日平均、VIX÷VIX3M < 0.9、澳元兌日圓 > 100 日平均。
規則（batch23.run_vote）：分數 ≥ k 由唔成立變成立 → 翌日開市買；分數 ≤ x 收市出；初始止蝕 3×ATR；最長 250 日。
  V1 ES：(k, x)＝(3, 1)／(4, 2)；只做好。
  V2 MHI：同一組分數（全部用之前一個美國交易日，唔偷看），(k, x)＝(3, 1)／(4, 2)；只做好＋雙向（分數 ≤ 5−k 做淡、≥ 5−x 出）。
跨市場：ES 用 YM、RTY、日經、DAX、FTSE；MHI 用台韓日澳上證（全部非美國用前一日分數）。成本、R 同之前。

預先登記（11-09，跑之前寫，唔再改）：ES ＝ #2004 嚴格四條；MHI ＝ #2021 寬條件；同一家族只計 t 最高一個；
ES 同 Donchian 20／12 個月動量入場日重疊 ≥ 70% 唔當獨立。
⚠ 成員係 #2020、#2025–#2027 個別差少少嘅訊號，組合有明顯樣本內選擇偏差；③ 跨市場同影子前向係主要防線，合格都要影子 30 張先提案。
冇 → 第二十七批另行登記。
"""
import bisect
import json
import daily_search as ds
import batch6 as b6
import batch13 as b13
import batch18 as b18
import batch23 as b23

CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
US_SAME = {"ES", "YM", "RTY"}


def score_series(data):
    st = [b18.state_on(b18.ratio_series(data["XLY"], data["XLP"]), 100),
          b18.state_on(b18.ratio_series(data["IWM"], data["SPY"]), 50),
          b18.state_on(b18.ratio_series(data["SMH"], data["SPY"]), 100),
          b18.state_on(b18.ratio_series(data["AUDJPY"]), 100)]
    v3 = {x[0]: x[4] for x in data["VIX3M"]}
    vt = sorted((x[0], x[4] / v3[x[0]] < 0.9) for x in data["VIX"] if x[0] in v3 and v3[x[0]])
    st.append(([p[0] for p in vt], [p[1] for p in vt]))
    return st


def map_score(b, st, strict):
    out = []
    for x in b:
        s = 0
        for dts, on in st:
            k = (bisect.bisect_left(dts, x[0]) if strict else bisect.bisect_right(dts, x[0])) - 1
            s += int(bool(k >= 0 and on[k]))
        out.append(s)
    return out


def run_v(b, ind, score, k, x, both):
    if not both:
        return b23.run_vote(b, ind, score, k, False, None, exit_at=x)
    # 雙向：分數置中（−2.5..+2.5 → 用 2×分數−5，令 ±k 對稱）
    cen = [2 * s - 5 for s in score]
    return b23.run_vote(b, ind, cen, 2 * k - 5, True, None, exit_at=2 * x - 5)


def grid():
    for k, x in ((3, 1), (4, 2)):
        yield "ES", "V1", {"k": k, "x": x, "both": False}
    for both in (False, True):
        for k, x in ((3, 1), (4, 2)):
            yield "MHI", "V2", {"k": k, "x": x, "both": both}


def main():
    extra = {"XLY": "XLY", "XLP": "XLP", "IWM": "IWM", "SPY": "SPY", "SMH": "SMH", "AUDJPY": "AUDJPY=X", "VIX": "^VIX", "VIX3M": "^VIX3M"}
    tks = {"MHI": "^HSI", "ES": "ES=F", **CROSS_US, **CROSS_AS, **extra}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    st = score_series(data)
    data = {mk: b for mk, b in data.items() if len(b) > 300 and mk not in extra}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    score = {mk: map_score(b, st, mk not in US_SAME) for mk, b in data.items()}
    prior = {x["d"] for x in ds.run(data["ES"], ind["ES"], "F2", {"N": 20, "k": 3, "M": 10, "both": False})}
    prior |= {x["d"] for x in b6.run6(data["ES"], ind["ES"], "K1", {"L": 12, "both": False})}

    def run(mk, fam, p):
        return run_v(data[mk], ind[mk], score[mk], p["k"], p["x"], p["both"])

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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch26.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
