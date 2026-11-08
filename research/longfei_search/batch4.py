"""[IDEAS #2006] 策略搜尋第四批：MHI 市況切換（#2005 結果：順勢 2021 後失效；布林帶回歸 2021→ t 2.21 但 2000–14 負）。

假說：恒指喺「200 日線向上」時順勢有效、其他時間均值回歸有效；單一規則跨唔到兩種市況。
規則（全部預先寫死）：
  市況 U＝收市 > SMA200 而且 SMA200 比 20 日前高；其他＝市況 X。
  H1：U → Donchian N 日只做好（止蝕 k×ATR、M 日低位出）；X → 布林帶回歸雙向（收市 < SMA20−2σ 做好／> +2σ 做淡，返 SMA20 或 10 日出，止蝕 3×ATR）
      N∈{20,55} k∈{2,3} M∈{10,20}
  H2：只做 X 市況嘅布林帶回歸（U 唔做）
  H3：只做 U 市況嘅 Donchian（X 唔做）N∈{20,55} k∈{2,3} M∈{10,20}
  H4：X 市況布林帶，帶寬 σ 倍數 b∈{1.5,2.5}
跨市場（冇參與揀選）：^TWII、^KS11、^N225、^AXJO、000001.SS。
預先登記（11-09，跑之前）——同 #2004 四條；合格 → 影子前向；冇 → 第五批（恒指 1 小時，GCS 1 分鐘存檔，約 1 年數據，標準另定）。
"""
import json
import daily_search as ds
import batch3 as b3


def regime(b, ind):
    c, S = ind["c"], ind["sma"][200]
    return [None if i < 220 or S[i] is None or S[i - 20] is None else ("U" if c[i] > S[i] and S[i] > S[i - 20] else "X") for i in range(len(b))]


def boll(b, ind, mult, allowed):
    c, atr = ind["c"], ind["atr"]
    n, out, i = len(b), [], 221
    while i < n - 2:
        if not allowed(i) or atr[i] is None:
            i += 1
            continue
        w = c[i - 19:i + 1]
        m = sum(w) / 20
        sd = (sum((x - m) ** 2 for x in w) / 20) ** 0.5
        sig = 1 if c[i] < m - mult * sd else (-1 if c[i] > m + mult * sd else 0)
        if not sig:
            i += 1
            continue
        px = b[i + 1][1]
        def ef(j, s=sig):
            mm = sum(c[j - 19:j + 1]) / 20
            return c[j] >= mm if s > 0 else c[j] <= mm
        j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * atr[i], ef, 10, 2 * atr[i])
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def donch(b, ind, p, allowed):
    tr = ds.run(b, ind, "F2", {**p, "both": False})
    idx = {x[0]: k for k, x in enumerate(b)}
    return [x for x in tr if allowed(idx[x["d"]])]


def run4(b, ind, fam, p):
    rg = regime(b, ind)
    U = lambda i: rg[i] == "U"  # noqa: E731
    X = lambda i: rg[i] == "X"  # noqa: E731
    if fam == "H1":
        return sorted(donch(b, ind, p, U) + boll(b, ind, 2.0, X), key=lambda x: x["d"])
    if fam == "H2":
        return boll(b, ind, 2.0, X)
    if fam == "H3":
        return donch(b, ind, p, U)
    return boll(b, ind, p["b"], X)


def grid():
    for N in (20, 55):
        for k in (2, 3):
            for M in (10, 20):
                yield "H1", {"N": N, "k": k, "M": M}
                yield "H3", {"N": N, "k": k, "M": M}
    yield "H2", {}
    for bb in (1.5, 2.5):
        yield "H4", {"b": bb}


def main():
    data = {mk: ds.load(tk) for mk, tk in {"MHI": "^HSI", **b3.CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    rows = []
    for fam, p in grid():
        tr = run4(data["MHI"], ind["MHI"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cross = {mk: ds.stats([x for x in run4(data[mk], ind[mk], fam, p) if x["d"] >= "2015-01-01"]) for mk in b3.CROSS}
        cpos = sum(1 for v in cross.values() if v.get("avg", -1) > 0)
        q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
             "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        rows.append({"key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                     "cross_pos": cpos, **q, "qualified": all(q.values())})
    ok = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["since2015"]["t"])
    print("== MHI 合格", len(ok))
    for r in sorted(rows, key=lambda r: -r["since2015"].get("t", -9))[:8]:
        print(" ", r["key"], "2015→", r["since2015"], "最終", r["final"], "搜尋", r["search"].get("avg"), "跨", r["cross_pos"], r["c1"], r["c2"], r["c3"], r["c4"])
    txt = json.dumps({"rows": rows, "pick": ok[0] if ok else None}, ensure_ascii=False)
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch4.json").upload_from_string(txt, content_type="application/json")


if __name__ == "__main__":
    main()
