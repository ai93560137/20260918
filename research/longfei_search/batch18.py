"""[IDEAS #2020] 策略搜尋第十八批：跨資產風險偏好訊號（使用者 11-09「MHI、NQ、ES 每個搵到 3 個合格策略，總共 9 個先停」；而家 NQ 3、ES 2、MHI 0）。

訊號（全部係比率／價格 > 自己 L 日平均 ＝ 風險偏好開；L＝50／100）：
  Y1 信用：HYG ÷ IEF（高收益債對 7–10 年國債，2007 起）
  Y2 銅金比：HG=F ÷ GC=F（環球／中國增長代理）
  Y3 澳元兌日圓：AUDJPY=X（套息、風險偏好）
規則：訊號開（之前唔開）→ 翌日開市買指數；訊號關收市出；初始止蝕 3×ATR；最長 250 日。雙向版（只 MHI）：訊號由開變關 → 做淡，翻開出。
時間：美國市場用同日訊號收市；恒指、日經、DAX、FTSE 同亞洲跨市場用之前一個美國交易日（唔偷看）。
NQ、ES 只做好；MHI 只做好＋雙向。跨市場、成本、R 同 #2015。

預先登記（11-09，跑之前寫，唔再改）＝ #2004 四條（④ 用 2000–2014 有數據嘅年份；Y1 由 2007）；同一家族只計 t 最高一個；
同已合格策略（Donchian 20、NQ Keltner、NQ／ES 12 個月動量）入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第十九批另行登記。
"""
import bisect
import json
import daily_search as ds
import batch6 as b6
import batch13 as b13

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
US_SAME = {"NQ", "ES", "YM", "RTY"}
MAXD = 250


def ratio_series(a, b=None):
    if b is None:
        return {x[0]: x[4] for x in a}
    bd = {x[0]: x[4] for x in b}
    return {x[0]: x[4] / bd[x[0]] for x in a if x[0] in bd and bd[x[0]]}


def state_on(series, L):
    d = sorted(series)
    v = [series[k] for k in d]
    on, s = [None] * len(v), 0.0
    for i in range(len(v)):
        s += v[i]
        if i >= L:
            s -= v[i - L]
        if i >= L - 1:
            on[i] = v[i] > s / L
    return d, on


def run18(b, ind, sd, on, strict, both):
    c, atr = ind["c"], ind["atr"]
    n = len(b)
    idx = [(bisect.bisect_left(sd, x[0]) if strict else bisect.bisect_right(sd, x[0])) - 1 for x in b]
    st = [on[k] if k >= 1 else None for k in idx]
    out, i = [], 201
    while i < n - 2:
        if atr[i] is None or st[i] is None or st[i - 1] is None:
            i += 1
            continue
        sig = 1 if st[i] and not st[i - 1] else (-1 if both and (not st[i]) and st[i - 1] else 0)
        if not sig:
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        ef = (lambda j, s=sig: st[j] is not None and (st[j] is False if s > 0 else st[j] is True))
        j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, ef, MAXD, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid(mk):
    sides = (False, True) if mk == "MHI" else (False,)
    for both in sides:
        for y in ("Y1", "Y2", "Y3"):
            for L in (50, 100):
                yield y, {"L": L, "both": both}


def main():
    tks = {**MKTS, **CROSS_US, **CROSS_AS, "HYG": "HYG", "IEF": "IEF", "HG": "HG=F", "GC": "GC=F", "AUDJPY": "AUDJPY=X"}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    sig = {"Y1": ratio_series(data["HYG"], data["IEF"]), "Y2": ratio_series(data["HG"], data["GC"]), "Y3": ratio_series(data["AUDJPY"])}
    for k, v in sig.items():
        print(k, "數據", len(v), min(v) if v else None)
    data = {mk: b for mk, b in data.items() if len(b) > 300 and mk in {**MKTS, **CROSS_US, **CROSS_AS}}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    states = {(y, L): state_on(sig[y], L) for y in sig for L in (50, 100)}
    prior = {mk: {x["d"] for x in ds.run(data[mk], ind[mk], "F2", {"N": 20, "k": 2, "M": 20, "both": False})} for mk in MKTS}
    prior["NQ"] |= {x["d"] for x in b13.run13(data["NQ"], ind["NQ"], b13.extra(data["NQ"], ind["NQ"]), "T2", {"k": 1.5, "both": False})}
    for mk in ("NQ", "ES"):
        prior[mk] |= {x["d"] for x in b6.run6(data[mk], ind[mk], "K1", {"L": 12, "both": False})}

    def run(mk, fam, p):
        sd, on = states[(fam, p["L"])]
        if not sd:
            return []
        return run18(data[mk], ind[mk], sd, on, mk not in US_SAME, p["both"])

    res = {}
    for mk in MKTS:
        cross = CROSS_AS if mk == "MHI" else CROSS_US
        rows = []
        for fam, p in grid(mk):
            tr = run(mk, fam, p)
            s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
            fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
            srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
            cpos = sum(1 for c in cross if c in data and ds.stats([x for x in run(c, fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
            ov = round(sum(1 for x in tr if x["d"] in prior[mk]) / len(tr), 2) if tr else 0
            q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
                 "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
            indep = ov < 0.70
            rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                         "cross_pos": cpos, "prior_overlap": ov, **q, "independent": indep, "qualified": all(q.values()) and indep})
            print(mk, fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, "重疊", ov, q, "✅" if rows[-1]["qualified"] else "")
        best = {}
        for r in rows:
            if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
                best[r["fam"]] = r
        res[mk] = {"rows": rows, "qualified_by_family": best}
        print("==", mk, "合格家族", list(best))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch18.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
