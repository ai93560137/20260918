"""[IDEAS #2025] 策略搜尋第二十三批：多訊號投票（使用者 11-09 再講「繼續做研究直至 MHI、NQ 同 ES 每個找到 3 個合格策略，總共 9 個先停」；
而家 NQ 3、ES 2、MHI 0）。

MHI（用 #2021 寬條件）：
  E1 三個趨勢狀態投票：週線 Donchian 13 週狀態（破 13 週收市高 = +1，跌穿 6 週收市低 = −1，否則維持）、一目均衡表狀態
     （收市 > 雲頂而轉換線 > 基準線 = +1，鏡像 = −1，否則 0）、Supertrend m3（±1）。總分 ≥ k（k＝2／3）由唔成立變成立 → 翌日開市買；
     總分 ≤ 0 收市出；初始止蝕 3×ATR。雙向版鏡像（總分 ≤ −k 做淡、≥ 0 出）。
  E2 同 E1（k＝2）但入場時要 20 日實現波幅 < 60 日實現波幅 × 1.2（避開波動期）。只做好＋雙向。
ES（用 #2004 嚴格四條）：
  E3 四個風險偏好狀態數目：Aroon(25) 狀態（升 > 90 而跌 < 30 開、升 < 50 關）、澳元兌日圓 > 100 日平均（前一日）、
     VIX < VIX 50 日平均、收市 > SMA200。成立數目 ≥ k（k＝3／4）由唔成立變成立 → 翌日開市買；數目 ≤ 1 收市出；初始止蝕 3×ATR。只做好。
跨市場：MHI 用台韓日澳上證；ES 用 YM、RTY、日經、DAX、FTSE（非美國用前一日 VIX、澳元日圓）。成本、R 同之前；最長持倉 250 日。

預先登記（11-09，跑之前寫，唔再改）：MHI ＝ #2021 寬條件；ES ＝ #2004 嚴格四條。同一家族只計 t 最高一個；
ES 同 Donchian 20／12 個月動量入場日重疊 ≥ 70% 唔當獨立。合格 → 影子前向，使用者批先真倉；冇 → 第二十四批另行登記。
注意：成員訊號之前個別測過（#2014–#2023），投票組合係新家族，但有樣本內選擇偏差，③ 跨市場係主要防線。
"""
import bisect
import json
from datetime import date
import daily_search as ds
import batch6 as b6
import batch13 as b13
import batch14 as b14
import batch15 as b15
import batch16 as b16
import batch18 as b18
import batch21 as b21

CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
US_SAME = {"ES", "YM", "RTY"}


def weekly_dc_state(b, c, N=13):
    n = len(b)
    wk = lambda i: date.fromisoformat(b[i][0]).isocalendar()[:2]  # noqa: E731
    ends = [i for i in range(n - 1) if wk(i + 1) != wk(i)]
    st, cur, a = [0] * n, 0, -1
    wc = [c[e] for e in ends]
    for i in range(n):
        while a + 1 < len(ends) and ends[a + 1] <= i:
            a += 1
            if a >= N:
                if wc[a] > max(wc[a - N:a]):
                    cur = 1
                elif wc[a] < min(wc[a - N // 2:a]):
                    cur = -1
        st[i] = cur
    return st


def mhi_votes(b, ind):
    c = ind["c"]
    s1 = weekly_dc_state(b, c)
    ten, kij, top, bot = b16.ichimoku(b)
    s2 = [0 if top[i] is None else (1 if c[i] > top[i] and ten[i] > kij[i] else (-1 if c[i] < bot[i] and ten[i] < kij[i] else 0)) for i in range(len(b))]
    s3 = b14.supertrend(b, ind["atr"], 3)
    return [s1[i] + s2[i] + s3[i] for i in range(len(b))]


def run_vote(b, ind, vote, k, both, vf=None, exit_at=0):
    c, atr = ind["c"], ind["atr"]
    n = len(b)
    out, i = [], 201
    while i < n - 2:
        if atr[i] is None:
            i += 1
            continue
        sig = 0
        if vote[i] >= k and vote[i - 1] < k:
            sig = 1
        elif both and vote[i] <= -k and vote[i - 1] > -k:
            sig = -1
        if sig and vf is not None and not vf[i]:
            sig = 0
        if not sig:
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        ef = (lambda j, s=sig: vote[j] <= exit_at if s > 0 else vote[j] >= -exit_at)
        j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, ef, 250, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j
    return out


def es_count(b, ind, vix, aud, strict):
    c, S = ind["c"], ind["sma"][200]
    n = len(b)
    au, ad = b21.aroon(b)
    ar, cur = [0] * n, 0
    for i in range(n):
        if au[i] is not None:
            if au[i] > 90 and ad[i] < 30:
                cur = 1
            elif au[i] < 50:
                cur = 0
        ar[i] = cur
    vd, von = vix
    adt, aon = aud
    def look(dts, on, d, same):
        k = (bisect.bisect_right(dts, d) if same else bisect.bisect_left(dts, d)) - 1
        return bool(k >= 0 and on[k])
    cnt = []
    for i in range(n):
        d = b[i][0]
        v = look(vd, von, d, not strict)
        a = look(adt, aon, d, False)
        cnt.append(ar[i] + int(v) + int(a) + int(S[i] is not None and c[i] > S[i]))
    return cnt


def grid():
    for both in (False, True):
        for k in (2, 3):
            yield "MHI", "E1", {"k": k, "both": both}
        yield "MHI", "E2", {"k": 2, "both": both}
    for k in (3, 4):
        yield "ES", "E3", {"k": k}


def main():
    tks = {"MHI": "^HSI", "ES": "ES=F", **CROSS_US, **CROSS_AS, "VIX": "^VIX", "AUDJPY": "AUDJPY=X"}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    vser = b18.ratio_series(data["VIX"])
    vd, von_raw = b18.state_on(vser, 50)
    von = [None if x is None else (not x) for x in von_raw]          # VIX 低過 50 日平均 = 開
    aud = b18.state_on(b18.ratio_series(data["AUDJPY"]), 100)
    data = {mk: b for mk, b in data.items() if len(b) > 300 and mk not in ("VIX", "AUDJPY")}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    prior = {x["d"] for x in ds.run(data["ES"], ind["ES"], "F2", {"N": 20, "k": 3, "M": 10, "both": False})}
    prior |= {x["d"] for x in b6.run6(data["ES"], ind["ES"], "K1", {"L": 12, "both": False})}
    cache = {}

    def run(mk, fam, p):
        if fam in ("E1", "E2"):
            if (mk, "v") not in cache:
                cache[(mk, "v")] = mhi_votes(data[mk], ind[mk])
            vf = None
            if fam == "E2":
                v20, v60 = b15.rvol(ind[mk]["c"], 20), b15.rvol(ind[mk]["c"], 60)
                vf = [v20[i] is not None and v60[i] is not None and v20[i] < v60[i] * 1.2 for i in range(len(data[mk]))]
            return run_vote(data[mk], ind[mk], cache[(mk, "v")], p["k"], p["both"], vf)
        if (mk, "c") not in cache:
            cache[(mk, "c")] = es_count(data[mk], ind[mk], (vd, von), aud, mk not in US_SAME)
        return run_vote(data[mk], ind[mk], cache[(mk, "c")], p["k"], False, None, exit_at=1)

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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch23.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
