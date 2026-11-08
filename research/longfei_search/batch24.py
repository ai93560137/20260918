"""[IDEAS #2026] 策略搜尋第二十四批（使用者 11-09「直至 MHI、NQ、ES 每個 3 個、總共 9 個先停」；而家 NQ 3、ES 2、MHI 0）。

MHI（#2021 寬條件）：
  M1 投票狀態逐月持有：每月最後一個交易日收市，#2025 三趨勢投票（週線 Donchian 13、一目、Supertrend m3）總分 ≥ k → 收市買，
     持有到下月尾（k＝2／3）；雙向版總分 ≤ −k 做淡。（#2025 交易太少，逐月持有令每個月都係一筆）
ES（#2004 嚴格四條）：
  T1 VIX 期限結構：^VIX ÷ ^VIX3M < th（th＝0.85／0.90）由唔成立變成立 → 翌日開市買；比率 > 1.0（倒掛）收市出；初始止蝕 3×ATR。
  T2 同 T1（th＝0.90）但要收市 > SMA200 先入場。
  T1、T2 當同一家族（T）計。（VIX3M 2006 起；④ 用 2007–2014；非美國跨市場用前一日比率）
跨市場：MHI 台韓日澳上證；ES YM、RTY、日經、DAX、FTSE。成本、R 同之前。

預先登記（11-09，跑之前寫，唔再改）：MHI ＝ #2021 寬條件；ES ＝ #2004 嚴格四條；同一家族只計 t 最高一個；
ES 同 Donchian 20／12 個月動量入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第二十五批另行登記。
"""
import bisect
import json
import daily_search as ds
import batch6 as b6
import batch13 as b13
import batch23 as b23

CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
US_SAME = {"ES", "YM", "RTY"}


def run_m1(b, ind, vote, k, both):
    c, atr = ind["c"], ind["atr"]
    n = len(b)
    ends = [i for i in range(n - 1) if b[i + 1][0][:7] != b[i][0][:7]]
    out = []
    for a in range(len(ends) - 1):
        e, x = ends[a], ends[a + 1]
        if e < 300 or atr[e] is None:
            continue
        side = 1 if vote[e] >= k else (-1 if both and vote[e] <= -k else 0)
        if side:
            out.append({"d": b[e][0], "r": ((c[x] - c[e]) * side - ds.COST * c[e]) / (2 * atr[e])})
    return out


def run_t(b, ind, rd, rv, th, strict, need200):
    c, atr, S = ind["c"], ind["atr"], ind["sma"][200]
    n = len(b)
    idx = [(bisect.bisect_left(rd, x[0]) if strict else bisect.bisect_right(rd, x[0])) - 1 for x in b]
    r = [rv[k] if k >= 0 else None for k in idx]
    out, i = [], 201
    while i < n - 2:
        if atr[i] is None or r[i] is None or r[i - 1] is None:
            i += 1
            continue
        if not (r[i] < th and r[i - 1] >= th) or (need200 and not (S[i] is not None and c[i] > S[i])):
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        j, rr = ds.trade(b, i + 1, 1, px, px - 3 * a0, lambda j: r[j] is not None and r[j] > 1.0, 250, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": rr})
        i = j + 1
    return out


def grid():
    for both in (False, True):
        for k in (2, 3):
            yield "MHI", "M1", {"k": k, "both": both}
    for th in (0.85, 0.90):
        yield "ES", "T", {"th": th, "f200": False}
    yield "ES", "T", {"th": 0.90, "f200": True}


def main():
    tks = {"MHI": "^HSI", "ES": "ES=F", **CROSS_US, **CROSS_AS, "VIX": "^VIX", "VIX3M": "^VIX3M"}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    v3 = {x[0]: x[4] for x in data["VIX3M"]}
    pairs = sorted((x[0], x[4] / v3[x[0]]) for x in data["VIX"] if x[0] in v3 and v3[x[0]])
    rd, rv = [p[0] for p in pairs], [p[1] for p in pairs]
    print("VIX/VIX3M", len(rd), rd[0] if rd else None)
    data = {mk: b for mk, b in data.items() if len(b) > 300 and mk not in ("VIX", "VIX3M")}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    prior = {x["d"] for x in ds.run(data["ES"], ind["ES"], "F2", {"N": 20, "k": 3, "M": 10, "both": False})}
    prior |= {x["d"] for x in b6.run6(data["ES"], ind["ES"], "K1", {"L": 12, "both": False})}
    votes = {}

    def run(mk, fam, p):
        if fam == "M1":
            if mk not in votes:
                votes[mk] = b23.mhi_votes(data[mk], ind[mk])
            return run_m1(data[mk], ind[mk], votes[mk], p["k"], p["both"])
        return run_t(data[mk], ind[mk], rd, rv, p["th"], mk not in US_SAME, p["f200"])

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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch24.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
