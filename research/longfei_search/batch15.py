"""[IDEAS #2017] 策略搜尋第十五批：MHI、NQ、ES（使用者 11-09「MHI、NQ、ES 每個搵到 3 個合格策略，總共 9 個先停」）。

  U1 回吐入、趨勢出：收市 > SMA200 而 RSI2 < th（5／10）→ 翌日開市買；吊燈 m×ATR 出（m＝3／4），初始止蝕 3×ATR。
     （#2003 F3 係 5 日內出、每筆太細；今次入場一樣但讓利潤跑）雙向版鏡像（RSI2 > 100−th、收市 < SMA200 做淡）。
  U2 低波幅先跟趨勢：收市 > SMA200 而波幅過濾成立 → 翌日開市買（唔使轉向，冇倉就入），任何一個條件唔成立收市出。
     NQ／ES 同美歐跨市場過濾＝VIX < VIX 50 日平均 × th（日經、DAX、FTSE 用前一個美國交易日 VIX）；MHI 同跨市場＝20 日實現波幅 < 60 日實現波幅 × th。th＝1.0／1.2。雙向版鏡像（收市 < SMA200 做淡）。
  U3 NR7 收窄突破：今日波幅係 7 日最細而收市 > SMA200 → 翌日升穿今日高位就入（價 = max(開市, 今日高)），止蝕今日低位；
     吊燈 m×ATR 出（m＝3／4）。雙向版鏡像。
  U4 標普帶恒指（只 MHI 同亞洲跨市場）：標普（前一個美國收市）破 20 日收市高而 > 標普 SMA200 → 翌日開市買恒指；
     標普跌穿 M 日收市低（M＝10／20）出；止蝕 3×ATR。雙向版鏡像。
NQ、ES 只做好；MHI 只做好＋雙向。跨市場、成本、R 同 #2015；最長持倉 250 日。

預先登記（11-09，跑之前寫，唔再改）＝ #2004 四條；同一家族只計 t 最高一個；
同 Donchian 20 或 NQ Keltner（#2015）入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第十六批另行登記。
"""
import bisect
import json
import math
import daily_search as ds
import batch13 as b13

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
MAXD = 250


def rvol(c, k):
    n = len(c)
    r = [0.0] + [math.log(c[i] / c[i - 1]) for i in range(1, n)]
    out = [None] * n
    for i in range(k, n):
        w = r[i - k + 1:i + 1]
        m = sum(w) / k
        out[i] = math.sqrt(sum((x - m) ** 2 for x in w) / k)
    return out


def us_map(b, spx_b):
    """每個本地交易日 → 之前最後一個美國交易日 index（避免偷看）。"""
    sd = [x[0] for x in spx_b]
    return [bisect.bisect_left(sd, x[0]) - 1 for x in b]


def chand(b, c, atr, a0, s, m, px):
    ext = {"x": px}
    def ef(j):
        ext["x"] = max(ext["x"], b[j][2]) if s > 0 else min(ext["x"], b[j][3])
        a = atr[j] or a0
        return c[j] < ext["x"] - m * a if s > 0 else c[j] > ext["x"] + m * a
    return ef


def run15(b, ind, fam, p, aux):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    both = p.get("both", False)
    out, i, n = [], 201, len(b)
    if fam == "U2":
        if aux.get("vix") is not None:
            vf = aux["vix"](p["th"])
        else:
            v20, v60 = rvol(c, 20), rvol(c, 60)
            vf = [v20[k] is not None and v60[k] is not None and v20[k] < v60[k] * p["th"] for k in range(n)]
    if fam == "U4":
        if aux.get("us") is None:
            return []
        um, sc, s200 = aux["us"]
    while i < n - 2:
        if atr[i] is None or S[200][i] is None:
            i += 1
            continue
        sig, a0 = 0, atr[i]
        r2 = ind["rsi2"][i]
        if fam == "U1" and r2 is not None:
            if c[i] > S[200][i] and r2 < p["th"]:
                sig = 1
            elif both and c[i] < S[200][i] and r2 > 100 - p["th"]:
                sig = -1
        elif fam == "U2":
            if vf[i] and c[i] > S[200][i]:
                sig = 1
            elif both and vf[i] and c[i] < S[200][i]:
                sig = -1
        elif fam == "U3":
            rng = [x[2] - x[3] for x in b[i - 6:i + 1]]
            if rng[-1] == min(rng) and rng[-1] > 0:
                if c[i] > S[200][i] and b[i + 1][2] > b[i][2]:
                    sig = 1
                elif both and c[i] < S[200][i] and b[i + 1][3] < b[i][3]:
                    sig = -1
        elif fam == "U4":
            k = um[i]
            if k >= 200 and s200[k] is not None:
                if sc[k] > max(sc[k - 20:k]) and sc[k] > s200[k]:
                    sig = 1
                elif both and sc[k] < min(sc[k - 20:k]) and sc[k] < s200[k]:
                    sig = -1
        if not sig:
            i += 1
            continue
        R, start = 2 * a0, i + 1
        if fam == "U1":
            px = b[i + 1][1]
            j, r = ds.trade(b, start, sig, px, px - sig * 3 * a0, chand(b, c, atr, a0, sig, p["m"], px), MAXD, R)
        elif fam == "U2":
            px = b[i + 1][1]
            ef = (lambda j, s=sig: (not vf[j]) or (c[j] < S[200][j] if s > 0 else c[j] > S[200][j]))
            j, r = ds.trade(b, start, sig, px, None, ef, MAXD, R)
        elif fam == "U3":
            px = max(b[i + 1][1], b[i][2]) if sig > 0 else min(b[i + 1][1], b[i][3])
            stop = b[i][3] if sig > 0 else b[i][2]
            j, r = ds.trade(b, start, sig, px, stop, chand(b, c, atr, a0, sig, p["m"], px), MAXD, R)
        else:
            px, M = b[i + 1][1], p["M"]
            def ef(j, s=sig, M=M):
                k = um[j]
                return sc[k] < min(sc[k - M:k]) if s > 0 else sc[k] > max(sc[k - M:k])
            j, r = ds.trade(b, start, sig, px, px - sig * 3 * a0, ef, MAXD, R)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid(mk):
    sides = (False, True) if mk == "MHI" else (False,)
    for both in sides:
        for th in (5, 10):
            for m in (3, 4):
                yield "U1", {"th": th, "m": m, "both": both}
        for th in (1.0, 1.2):
            yield "U2", {"th": th, "both": both}
        for m in (3, 4):
            yield "U3", {"m": m, "both": both}
        if mk == "MHI":
            for M in (10, 20):
                yield "U4", {"M": M, "both": both}


def main():
    tks = {**MKTS, **CROSS_US, **CROSS_AS, "SPX": "^GSPC", "VIX": "^VIX"}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    spx_b, vix_b = data["SPX"], data["VIX"]
    sc = [x[4] for x in spx_b]
    s200 = ind["SPX"]["sma"][200]
    vd = [x[0] for x in vix_b]
    vc = [x[4] for x in vix_b]
    vs = [None] * len(vc)
    for k in range(49, len(vc)):
        vs[k] = sum(vc[k - 49:k + 1]) / 50

    def vix_filter(b, strict):
        # 美國市場用同日 VIX 收市（同時收市）；歐洲／日本收市早過美國，用之前一個美國交易日（唔偷看）
        idx = [(bisect.bisect_left(vd, x[0]) if strict else bisect.bisect_right(vd, x[0])) - 1 for x in b]
        return lambda th: [k >= 49 and vs[k] is not None and vc[k] < vs[k] * th for k in idx]

    aux = {}
    for mk in data:
        a = {}
        if mk in ("NQ", "ES", *CROSS_US):
            a["vix"] = vix_filter(data[mk], strict=mk in ("N225", "DAX", "FTSE"))
        if mk in ("MHI", *CROSS_AS):
            a["us"] = (us_map(data[mk], spx_b), sc, s200)
        aux[mk] = a
    don = {mk: {x["d"] for x in ds.run(data[mk], ind[mk], "F2", {"N": 20, "k": 2, "M": 20, "both": False})} for mk in MKTS}
    kel = {x["d"] for x in b13.run13(data["NQ"], ind["NQ"], b13.extra(data["NQ"], ind["NQ"]), "T2", {"k": 1.5, "both": False})}

    def run(mk, fam, p):
        return run15(data[mk], ind[mk], fam, p, aux.get(mk, {}))

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
            ov = round(sum(1 for x in tr if x["d"] in don[mk]) / len(tr), 2) if tr else 0
            ovk = round(sum(1 for x in tr if x["d"] in kel) / len(tr), 2) if tr and mk == "NQ" else 0
            q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
                 "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
            indep = ov < 0.70 and ovk < 0.70
            rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                         "cross_pos": cpos, "donchian_overlap": ov, "keltner_overlap": ovk, **q, "independent": indep,
                         "qualified": all(q.values()) and indep})
            print(mk, fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, "重疊", ov, ovk, q, "✅" if rows[-1]["qualified"] else "")
        best = {}
        for r in rows:
            if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
                best[r["fam"]] = r
        res[mk] = {"rows": rows, "qualified_by_family": best}
        print("==", mk, "合格家族", list(best))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch15.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
