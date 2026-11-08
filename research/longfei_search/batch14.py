"""[IDEAS #2016] 策略搜尋第十四批：MHI、NQ、ES 再四個未測過嘅家族（使用者 11-09「MHI、NQ、ES 每個搵到 3 個合格策略，總共 9 個先停」）。

  S1 Supertrend：中位價 ±m×ATR(14) 帶（標準遞迴），收市由下轉上 → 翌日開市買，收市跌穿下帶出；雙向版鏡像。m＝3／4。
  S2 MACD 零軸上金叉：MACD(12,26) 上穿訊號線(9) 而 MACD > 0 → 翌日開市買；吊燈 m×ATR 出（m＝3／4），初始止蝕 2×ATR；雙向版鏡像。
  S3 順勢跳空低開回補（高頻）：昨收 > SMA200 而今日開市 < 昨日低位 − g×ATR（g＝0／0.5）→ 開市買、同日收市賣；雙向版：
     昨收 < SMA200 而開市 > 昨日高位 + g×ATR → 開市沽、收市平。
  S4 相對價值（只 MHI 同亞洲跨市場）：20 日 log 報酬差（指數 − 標普前一個美國交易日收市）嘅 250 日 z 值 < −th → 翌日開市買，
     持有 H 日，止蝕 3×ATR；雙向版 z > th 做淡。th＝1.5／2.0，H＝10／20。
NQ、ES 只做好（S3 只做好）；MHI 只做好＋雙向。跨市場、成本、R 同 #2015。

預先登記（11-09，跑之前寫，唔再改）：
  低頻（S1、S2、S4）＝ #2004 四條；高頻（S3）＝ #2012 條件（① 2015→ n ≥ 200、t ≥ 2.5、PF ≥ 1.30；②③④ 同 #2004）。
  同一家族只計 t 最高一個；同 Donchian 20 入場日重疊 ≥ 70% 唔當獨立；同已合格策略（NQ T2 Keltner）入場日重疊 ≥ 70% 亦唔當獨立。
  合格 → 影子前向，使用者批先真倉；冇 → 第十五批另行登記。
"""
import json
import math
import statistics
import daily_search as ds
import batch13 as b13

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
CROSS_US = b13.CROSS_US
CROSS_AS = b13.CROSS_AS
MAXD = 250


def ema(v, k):
    a, out = 2 / (k + 1), []
    for i, x in enumerate(v):
        out.append(x if i == 0 else a * x + (1 - a) * out[-1])
    return out


def supertrend(b, atr, m):
    n = len(b)
    up, dn, tr = [None] * n, [None] * n, [0] * n
    for i in range(n):
        if atr[i] is None:
            continue
        mid = (b[i][2] + b[i][3]) / 2
        bu, bl = mid + m * atr[i], mid - m * atr[i]
        if up[i - 1] is None:
            up[i], dn[i], tr[i] = bu, bl, 1
            continue
        up[i] = bu if bu < up[i - 1] or b[i - 1][4] > up[i - 1] else up[i - 1]
        dn[i] = bl if bl > dn[i - 1] or b[i - 1][4] < dn[i - 1] else dn[i - 1]
        c = b[i][4]
        tr[i] = 1 if c > up[i - 1] else (-1 if c < dn[i - 1] else tr[i - 1])
    return tr


def relz(b, spx):
    """20 日報酬差 z 值；標普用 HSI 日期之前最後一個美國收市（避免偷看）。"""
    sd = sorted(spx)
    import bisect
    s_prev = []
    for x in b:
        k = bisect.bisect_left(sd, x[0]) - 1
        s_prev.append(spx[sd[k]] if k >= 0 else None)
    n = len(b)
    rel = [None] * n
    for i in range(20, n):
        if s_prev[i] and s_prev[i - 20]:
            rel[i] = math.log(b[i][4] / b[i - 20][4]) - math.log(s_prev[i] / s_prev[i - 20])
    z = [None] * n
    for i in range(270, n):
        w = [x for x in rel[i - 250:i] if x is not None]
        if rel[i] is not None and len(w) > 200:
            sdv = statistics.pstdev(w)
            z[i] = (rel[i] - statistics.mean(w)) / sdv if sdv else None
    return z


def run14(b, ind, fam, p, aux):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    both = p.get("both", False)
    out, i, n = [], 201, len(b)
    if fam == "S1":
        st = supertrend(b, atr, p["m"])
    elif fam == "S2":
        e12, e26 = ema(c, 12), ema(c, 26)
        macd = [a - z for a, z in zip(e12, e26)]
        sg = ema(macd, 9)
    elif fam == "S4":
        z = aux.get("z")
        if z is None:
            return []
    while i < n - 2:
        if atr[i] is None:
            i += 1
            continue
        sig, a0 = 0, atr[i]
        if fam == "S3":                      # 開市已知訊號：今日 i 開市入、收市出；R 用昨日 ATR
            a0 = atr[i - 1]
            if a0 is None:
                i += 1
                continue
            o = b[i][1]
            if c[i - 1] > S[200][i - 1] and o < b[i - 1][3] - p["g"] * a0:
                sig = 1
            elif both and c[i - 1] < S[200][i - 1] and o > b[i - 1][2] + p["g"] * a0:
                sig = -1
            if not sig:
                i += 1
                continue
            r = ((c[i] - o) * sig - ds.COST * o) / (2 * a0)
            out.append({"d": b[i][0], "r": r})
            i += 1
            continue
        if fam == "S1":
            sig = 1 if st[i] == 1 and st[i - 1] == -1 else (-1 if both and st[i] == -1 and st[i - 1] == 1 else 0)
        elif fam == "S2":
            if macd[i] > sg[i] and macd[i - 1] <= sg[i - 1] and macd[i] > 0:
                sig = 1
            elif both and macd[i] < sg[i] and macd[i - 1] >= sg[i - 1] and macd[i] < 0:
                sig = -1
        elif fam == "S4":
            if z[i] is not None:
                sig = 1 if z[i] < -p["th"] else (-1 if both and z[i] > p["th"] else 0)
        if not sig:
            i += 1
            continue
        R, px, start = 2 * a0, b[i + 1][1], i + 1
        if fam == "S1":
            ef = (lambda j, s=sig: st[j] == -s)
            j, r = ds.trade(b, start, sig, px, None, ef, MAXD, R)
        elif fam == "S2":
            ext = {"x": px}
            def ef(j, s=sig, m=p["m"], ext=ext):
                ext["x"] = max(ext["x"], b[j][2]) if s > 0 else min(ext["x"], b[j][3])
                a = atr[j] or a0
                return c[j] < ext["x"] - m * a if s > 0 else c[j] > ext["x"] + m * a
            j, r = ds.trade(b, start, sig, px, px - sig * 2 * a0, ef, MAXD, R)
        else:
            j, r = ds.trade(b, start, sig, px, px - sig * 3 * a0, lambda j: False, p["H"], R)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j if fam == "S1" else j + 1           # Supertrend 反轉日本身可以係反向入場訊號
    return out


def grid(mk):
    sides = (False, True) if mk == "MHI" else (False,)
    for both in sides:
        for m in (3, 4):
            yield "S1", {"m": m, "both": both}
        for m in (3, 4):
            yield "S2", {"m": m, "both": both}
        for g in (0, 0.5):
            yield "S3", {"g": g, "both": both}
        if mk == "MHI":
            for th in (1.5, 2.0):
                for H in (10, 20):
                    yield "S4", {"th": th, "H": H, "both": both}


def main():
    tks = {**MKTS, **CROSS_US, **CROSS_AS, "SPX": "^GSPC"}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    spx = {x[0]: x[4] for x in data["SPX"]}
    aux = {mk: {"z": relz(data[mk], spx)} for mk in ["MHI", *CROSS_AS] if mk in data}
    don = {mk: {x["d"] for x in ds.run(data[mk], ind[mk], "F2", {"N": 20, "k": 2, "M": 20, "both": False})} for mk in MKTS}
    kel = {x["d"] for x in b13.run13(data["NQ"], ind["NQ"], b13.extra(data["NQ"], ind["NQ"]), "T2", {"k": 1.5, "both": False})}

    def run(mk, fam, p):
        return run14(data[mk], ind[mk], fam, p, aux.get(mk, {}))

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
            hf = fam == "S3"
            c1 = (s15.get("n", 0) >= 200 and s15.get("t", 0) >= 2.5 and s15.get("pf", 0) >= 1.30) if hf else \
                 (s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
            q = {"c1": bool(c1), "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4,
                 "c4": bool(srch.get("avg", -9) > 0)}
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch14.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
