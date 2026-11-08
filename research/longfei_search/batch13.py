"""[IDEAS #2015] 策略搜尋第十三批：MHI、NQ、ES 新趨勢家族（使用者 11-09「MHI、NQ、ES 每個搵到 3 個合格策略，總共 9 個先停」）。

#2004 證明只有「長持倉、讓利潤跑」先過到 +0.30R；之前只試過 Donchian／均線穿越／動量。今批用四個未測過嘅入場＋出場結構：
  T1 均線排列回調再上：SMA50 > SMA200 而收市由 SMA50 下方收返上面 → 翌日開市買；吊燈止蝕：收市 < 持倉期最高位 − m×ATR 出（m＝3／4），
     初始止蝕 3×ATR。雙向版：SMA50 < SMA200 而收市跌返落 SMA50 下面做淡（鏡像）。
  T2 Keltner 突破：收市 > EMA20 + k×ATR（k＝1.5／2.0／2.5）→ 買；收市 < EMA20 出；初始止蝕 2×ATR。雙向版鏡像。
  T3 ADX 趨勢突破：ADX(14) > th（20／25）而 +DI > −DI，收市破 10 日高 → 買；吊燈 3×ATR 出；初始止蝕 2×ATR。雙向版鏡像。
  T4 趨勢內短回調：收市 > SMA200，收市由 SMA10 下方收返上面 → 買；收市 < SMA50 出（f＝50）或 < SMA20 出（f＝20）；初始止蝕 2×ATR。雙向版鏡像。
NQ、ES 只做好（#2004 雙向全部差過只做好）；MHI 兩個版本都試（恒指 2018 後跌勢）。
跨市場（冇參與揀選）：NQ／ES 用 YM、RTY、日經、DAX、FTSE；MHI 用台灣、韓國、日經、澳洲、上證（同 #2005）。
成本 0.03% 來回；R＝2×ATR(14)（入場時）；收市出訊號、翌日開市入；最長持倉 250 日。

預先登記（11-09，跑之前寫，唔再改）＝ #2004 四條：
  ① 該市場 2015→ n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0；② 2021→ 平均 > 0、年份 ≥ 4／6 正；
  ③ 5 隻跨市場 2015→ ≥ 4 隻平均 > 0；④ 2000–2014 平均 > 0。
  同一家族只計 t 最高一個；同 Donchian（F2）入場同日重疊 ≥ 70% 嘅唔當獨立策略（避免換個名嘅 Donchian），會喺結果列明。
  合格 → 影子前向（同 #2004），使用者批先真倉；冇 → 第十四批另行登記。
"""
import json
import daily_search as ds

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
CROSS_US = {"YM": "YM=F", "RTY": "RTY=F", "N225": "^N225", "DAX": "^GDAXI", "FTSE": "^FTSE"}
CROSS_AS = {"TWII": "^TWII", "KS11": "^KS11", "N225": "^N225", "AXJO": "^AXJO", "SSE": "000001.SS"}
MAXD = 250


def extra(b, ind):
    n, c, atr = len(b), ind["c"], ind["atr"]
    def sma(k):
        out, s = [None] * n, 0.0
        for i in range(n):
            s += c[i]
            if i >= k:
                s -= c[i - k]
            if i >= k - 1:
                out[i] = s / k
        return out
    ema = [None] * n
    a = 2 / 21
    for i in range(n):
        ema[i] = c[i] if i == 0 else a * c[i] + (1 - a) * ema[i - 1]
    # Wilder ADX(14)
    pdm, ndm, tr = [0.0] * n, [0.0] * n, [0.0] * n
    for i in range(1, n):
        up, dn = b[i][2] - b[i - 1][2], b[i - 1][3] - b[i][3]
        pdm[i] = up if up > dn and up > 0 else 0.0
        ndm[i] = dn if dn > up and dn > 0 else 0.0
        tr[i] = max(b[i][2], b[i - 1][4]) - min(b[i][3], b[i - 1][4])
    adx, pdi, ndi = [None] * n, [None] * n, [None] * n
    st = sp = sn = 0.0
    dxs = []
    ax = None
    for i in range(1, n):
        if i <= 14:
            st += tr[i]; sp += pdm[i]; sn += ndm[i]
            if i < 14:
                continue
        else:
            st = st - st / 14 + tr[i]; sp = sp - sp / 14 + pdm[i]; sn = sn - sn / 14 + ndm[i]
        if st <= 0:
            continue
        pdi[i], ndi[i] = 100 * sp / st, 100 * sn / st
        s = pdi[i] + ndi[i]
        dx = 100 * abs(pdi[i] - ndi[i]) / s if s else 0.0
        if ax is None:
            dxs.append(dx)
            if len(dxs) == 14:
                ax = sum(dxs) / 14
        else:
            ax = (ax * 13 + dx) / 14
        adx[i] = ax
    return {"s10": sma(10), "s20": sma(20), "ema": ema, "adx": adx, "pdi": pdi, "ndi": ndi}


def run13(b, ind, ex, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    out, i, n = [], 201, len(b)
    both = p.get("both", False)
    while i < n - 2:
        sig = 0
        if atr[i] is None:
            i += 1
            continue
        if fam == "T1":
            s50, s200 = S[50], S[200]
            if s50[i] > s200[i] and c[i] > s50[i] and c[i - 1] <= s50[i - 1]:
                sig = 1
            elif both and s50[i] < s200[i] and c[i] < s50[i] and c[i - 1] >= s50[i - 1]:
                sig = -1
        elif fam == "T2":
            up, dn = ex["ema"][i] + p["k"] * atr[i], ex["ema"][i] - p["k"] * atr[i]
            sig = 1 if c[i] > up else (-1 if both and c[i] < dn else 0)
        elif fam == "T3":
            ax = ex["adx"][i]
            if ax is not None and ax > p["th"]:
                hi = max(x[2] for x in b[i - 10:i]); lo = min(x[3] for x in b[i - 10:i])
                if ex["pdi"][i] > ex["ndi"][i] and c[i] > hi:
                    sig = 1
                elif both and ex["ndi"][i] > ex["pdi"][i] and c[i] < lo:
                    sig = -1
        elif fam == "T4":
            s10 = ex["s10"]
            if c[i] > S[200][i] and c[i] > s10[i] and c[i - 1] <= s10[i - 1]:
                sig = 1
            elif both and c[i] < S[200][i] and c[i] < s10[i] and c[i - 1] >= s10[i - 1]:
                sig = -1
        if not sig:
            i += 1
            continue
        R, px, start, a0 = 2 * atr[i], b[i + 1][1], i + 1, atr[i]
        if fam in ("T1", "T3"):
            m = p.get("m", 3)
            ext = {"x": px}
            def ef(j, s=sig, m=m, ext=ext):
                ext["x"] = max(ext["x"], b[j][2]) if s > 0 else min(ext["x"], b[j][3])
                a = atr[j] or a0
                return c[j] < ext["x"] - m * a if s > 0 else c[j] > ext["x"] + m * a
            j, r = ds.trade(b, start, sig, px, px - sig * (3 if fam == "T1" else 2) * a0, ef, MAXD, R)
        elif fam == "T2":
            ef = (lambda j, s=sig: c[j] < ex["ema"][j] if s > 0 else c[j] > ex["ema"][j])
            j, r = ds.trade(b, start, sig, px, px - sig * 2 * a0, ef, MAXD, R)
        else:
            f = S[50] if p["f"] == 50 else ex["s20"]
            ef = (lambda j, s=sig, f=f: c[j] < f[j] if s > 0 else c[j] > f[j])
            j, r = ds.trade(b, start, sig, px, px - sig * 2 * a0, ef, MAXD, R)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid(mk):
    sides = (False, True) if mk == "MHI" else (False,)
    for both in sides:
        for m in (3, 4):
            yield "T1", {"m": m, "both": both}
        for k in (1.5, 2.0, 2.5):
            yield "T2", {"k": k, "both": both}
        for th in (20, 25):
            yield "T3", {"th": th, "both": both}
        for f in (20, 50):
            yield "T4", {"f": f, "both": both}


def main():
    tks = {**MKTS, **CROSS_US, **CROSS_AS}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    ex = {mk: extra(b, ind[mk]) for mk, b in data.items()}
    don = {mk: {x["d"] for x in ds.run(data[mk], ind[mk], "F2", {"N": 20, "k": 2, "M": 20, "both": False})} for mk in MKTS}

    def run(mk, fam, p):
        return run13(data[mk], ind[mk], ex[mk], fam, p)

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
            q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
                 "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
            indep = ov < 0.70
            rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                         "cross_pos": cpos, "donchian_overlap": ov, **q, "independent": indep, "qualified": all(q.values()) and indep})
            print(mk, fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, "重疊", ov, q, "✅" if rows[-1]["qualified"] else "")
        best = {}
        for r in rows:
            if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
                best[r["fam"]] = r
        res[mk] = {"rows": rows, "qualified_by_family": best}
        print("==", mk, "合格家族", list(best))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch13.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
