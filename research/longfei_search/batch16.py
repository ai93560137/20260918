"""[IDEAS #2018] 策略搜尋第十六批：MHI、NQ、ES（使用者 11-09「MHI、NQ、ES 每個搵到 3 個合格策略，總共 9 個先停」）。

  W1 時間序列動量（只 NQ、ES；#2008 只喺 MHI 試過）：batch6 K1 月度 L＝3／6／12、K2 週度 L＝13／26、K3 月度＋200 日線 L＝6／12，全部只做好。
  W2 一目均衡表：收市 > 雲頂（先行 A、B 嘅較高者，26 日前計）而轉換線 > 基準線，由唔成立變成立 → 翌日開市買；
     出場 e＝"kijun"（收市 < 基準線）或 "cloud"（收市 < 雲底）；初始止蝕 2×ATR。雙向版鏡像。
  W3 布林帶突破：收市 > SMA20 + k×σ20（k＝2.0／2.5）→ 翌日開市買；收市 < SMA20 出；初始止蝕 2×ATR。雙向版鏡像。
  W4 上證帶恒指（只 MHI）：上證同日收市（15:00 早過恒指收市，翌日開市先入，唔偷看）破 20 日收市高而 > 上證 SMA200 → 翌日開市買恒指；
     上證跌穿 M 日收市低出（M＝10／20）；止蝕 3×ATR。雙向版鏡像。跨市場用台、韓、日、澳 4 隻（上證係訊號本身，唔計），≥ 3／4 正。
NQ、ES 只做好；MHI 只做好＋雙向。其他跨市場、成本、R 同 #2015；最長持倉 250 日。

預先登記（11-09，跑之前寫，唔再改）＝ #2004 四條（W4 跨市場 ≥ 3／4）；同一家族只計 t 最高一個；
同 Donchian 20 或 NQ Keltner（#2015）入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第十七批另行登記。
"""
import bisect
import json
import statistics
import daily_search as ds
import batch6 as b6
import batch13 as b13

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
MAXD = 250


def ichimoku(b):
    n = len(b)
    def mid(i, k):
        if i < k - 1:
            return None
        w = b[i - k + 1:i + 1]
        return (max(x[2] for x in w) + min(x[3] for x in w)) / 2
    ten = [mid(i, 9) for i in range(n)]
    kij = [mid(i, 26) for i in range(n)]
    sb = [mid(i, 52) for i in range(n)]
    top, bot = [None] * n, [None] * n
    for i in range(n):
        k = i - 26
        if k >= 0 and ten[k] is not None and kij[k] is not None and sb[k] is not None:
            a = (ten[k] + kij[k]) / 2
            top[i], bot[i] = max(a, sb[k]), min(a, sb[k])
    return ten, kij, top, bot


def run16(b, ind, fam, p, aux):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    both = p.get("both", False)
    n = len(b)
    if fam == "W1":
        return b6.run6(b, ind, p["K"], {"L": p["L"], "both": False})
    if fam == "W2":
        ten, kij, top, bot = ichimoku(b)
        def st(i):
            if top[i] is None:
                return 0
            if c[i] > top[i] and ten[i] > kij[i]:
                return 1
            if c[i] < bot[i] and ten[i] < kij[i]:
                return -1
            return 0
    if fam == "W3":
        sd = [None] * n
        for i in range(19, n):
            sd[i] = statistics.pstdev(c[i - 19:i + 1])
        s20 = [None] * n
        for i in range(19, n):
            s20[i] = sum(c[i - 19:i + 1]) / 20
    if fam == "W4":
        if aux.get("sse") is None:
            return []
        um, sc, s200 = aux["sse"]
    out, i = [], 201
    while i < n - 2:
        if atr[i] is None:
            i += 1
            continue
        sig, a0 = 0, atr[i]
        if fam == "W2":
            s0, s1 = st(i), st(i - 1)
            sig = 1 if s0 == 1 and s1 != 1 else (-1 if both and s0 == -1 and s1 != -1 else 0)
        elif fam == "W3":
            sig = 1 if c[i] > s20[i] + p["k"] * sd[i] else (-1 if both and c[i] < s20[i] - p["k"] * sd[i] else 0)
        elif fam == "W4":
            k = um[i]
            if k >= 200 and s200[k] is not None:
                if sc[k] > max(sc[k - 20:k]) and sc[k] > s200[k]:
                    sig = 1
                elif both and sc[k] < min(sc[k - 20:k]) and sc[k] < s200[k]:
                    sig = -1
        if not sig:
            i += 1
            continue
        R, px, start = 2 * a0, b[i + 1][1], i + 1
        if fam == "W2":
            if p["e"] == "kijun":
                ef = (lambda j, s=sig: c[j] < kij[j] if s > 0 else c[j] > kij[j])
            else:
                ef = (lambda j, s=sig: (bot[j] is not None and c[j] < bot[j]) if s > 0 else (top[j] is not None and c[j] > top[j]))
            j, r = ds.trade(b, start, sig, px, px - sig * 2 * a0, ef, MAXD, R)
        elif fam == "W3":
            ef = (lambda j, s=sig: c[j] < s20[j] if s > 0 else c[j] > s20[j])
            j, r = ds.trade(b, start, sig, px, px - sig * 2 * a0, ef, MAXD, R)
        else:
            M = p["M"]
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
    if mk != "MHI":
        for L in (3, 6, 12):
            yield "W1", {"K": "K1", "L": L}
        for L in (13, 26):
            yield "W1", {"K": "K2", "L": L}
        for L in (6, 12):
            yield "W1", {"K": "K3", "L": L}
    sides = (False, True) if mk == "MHI" else (False,)
    for both in sides:
        for e in ("kijun", "cloud"):
            yield "W2", {"e": e, "both": both}
        for k in (2.0, 2.5):
            yield "W3", {"k": k, "both": both}
        if mk == "MHI":
            for M in (10, 20):
                yield "W4", {"M": M, "both": both}


def main():
    tks = {**MKTS, **CROSS_US, **CROSS_AS}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    sse = data.get("SSE")
    aux = {}
    if sse:
        sd = [x[0] for x in sse]
        sc = [x[4] for x in sse]
        s200 = ind["SSE"]["sma"][200]
        for mk in ("MHI", "TWII", "KS11", "N225", "AXJO"):
            if mk in data:
                # 上證同日 15:00 收市；本地收市出訊號、翌日開市入。日經、韓國 14:00–14:30 收市早過上證 → 用前一日上證（唔偷看）
                strict = mk in ("N225", "KS11")
                um = [(bisect.bisect_left(sd, x[0]) if strict else bisect.bisect_right(sd, x[0])) - 1 for x in data[mk]]
                aux[mk] = {"sse": (um, sc, s200)}
    don = {mk: {x["d"] for x in ds.run(data[mk], ind[mk], "F2", {"N": 20, "k": 2, "M": 20, "both": False})} for mk in MKTS}
    kel = {x["d"] for x in b13.run13(data["NQ"], ind["NQ"], b13.extra(data["NQ"], ind["NQ"]), "T2", {"k": 1.5, "both": False})}

    def run(mk, fam, p):
        return run16(data[mk], ind[mk], fam, p, aux.get(mk, {}))

    res = {}
    for mk in MKTS:
        rows = []
        for fam, p in grid(mk):
            cross = (["TWII", "KS11", "N225", "AXJO"] if fam == "W4" else list(CROSS_AS)) if mk == "MHI" else list(CROSS_US)
            need = 3 if fam == "W4" else 4
            tr = run(mk, fam, p)
            s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
            fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
            srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
            cpos = sum(1 for c in cross if c in data and ds.stats([x for x in run(c, fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
            ov = round(sum(1 for x in tr if x["d"] in don[mk]) / len(tr), 2) if tr else 0
            ovk = round(sum(1 for x in tr if x["d"] in kel) / len(tr), 2) if tr and mk == "NQ" else 0
            q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
                 "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= need, "c4": bool(srch.get("avg", -9) > 0)}
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch16.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
