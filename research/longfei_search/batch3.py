"""[IDEAS #2005] 策略搜尋第三批：MHI 專用（#2003／#2004 MHI 冇合格；NQ、ES 已喺 #2004 合格）。

恒指 2018 後長期跌勢／橫行，美股式只做好順勢失效。今批試雙向同均值回歸：
  G1 Donchian 雙向：N∈{10,20,55} k∈{2,3} M∈{10,20}
  G2 均線雙向：n∈{50,100,200}
  G3 RSI2 雙向：收市 > SMA200 而 RSI2 < th 做好；< SMA200 而 RSI2 > 100−th 做淡；收市反穿 SMA5 或 5 日出；止蝕 3×ATR。th∈{5,10,15}
  G4 IBS 雙向：IBS < th 而 > SMA200 做好；IBS > 1−th 而 < SMA200 做淡；收市入翌日收市出。th∈{0.1,0.2}
  G5 只做淡 Donchian：N∈{10,20} k∈{2,3} M∈{10,20}
  G6 布林帶回歸：收市 < SMA20−2σ 做好／> SMA20+2σ 做淡，返 SMA20 或 10 日出；止蝕 3×ATR
跨市場（冇參與揀選）：^TWII、^KS11、^N225、^AXJO、000001.SS（2015 起）。
成本、R、執行同第一批。

預先登記（11-09，跑之前寫，唔再改）——同 #2004 一樣四條：
  ① MHI 2015→：n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0；② 2021→：平均 > 0、年份 ≥ 4／6 正；
  ③ 5 隻亞洲指數 2015→ ≥ 4 隻平均 R > 0；④ 2000–2014 平均 R > 0。多過一個揀 ① t 最高。
  合格 → 影子前向；冇 → 第四批（換時框：恒指 1 小時，用 GCS 1 分鐘存檔）。
"""
import json
import daily_search as ds

CROSS = {"TWII": "^TWII", "KS11": "^KS11", "N225": "^N225", "AXJO": "^AXJO", "SSE": "000001.SS"}


def run2(b, ind, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    n = len(b)
    if fam == "G1":
        return ds.run(b, ind, "F2", {**p, "both": True})
    if fam == "G2":
        return ds.run(b, ind, "F1", {**p, "both": True})
    out, i = [], 201
    sd20 = [None] * n
    for k in range(20, n):
        w = c[k - 19:k + 1]
        m = sum(w) / 20
        sd20[k] = (sum((x - m) ** 2 for x in w) / 20) ** 0.5
    while i < n - 2:
        sig = 0
        if fam == "G3":
            r = ind["rsi2"][i]
            if r is not None:
                sig = 1 if c[i] > S[200][i] and r < p["th"] else (-1 if c[i] < S[200][i] and r > 100 - p["th"] else 0)
        elif fam == "G4":
            rng = b[i][2] - b[i][3]
            if rng > 0:
                ibs = (c[i] - b[i][3]) / rng
                sig = 1 if ibs < p["th"] and c[i] > S[200][i] else (-1 if ibs > 1 - p["th"] and c[i] < S[200][i] else 0)
        elif fam == "G5":
            lo = min(x[3] for x in b[i - p["N"]:i])
            sig = -1 if c[i] < lo else 0
        elif fam == "G6":
            m = sum(c[i - 19:i + 1]) / 20
            if sd20[i]:
                sig = 1 if c[i] < m - 2 * sd20[i] else (-1 if c[i] > m + 2 * sd20[i] else 0)
        if not sig or atr[i] is None:
            i += 1
            continue
        R = 2 * atr[i]
        if fam == "G3":
            px = b[i + 1][1]
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * atr[i], lambda j, s=sig: (c[j] > S[5][j]) if s > 0 else (c[j] < S[5][j]), 5, R)
        elif fam == "G4":
            j, r = ds.trade(b, i + 1, sig, c[i], None, lambda j: True, 1, R)
        elif fam == "G5":
            px = b[i + 1][1]
            M = p["M"]
            j, r = ds.trade(b, i + 1, -1, px, px + p["k"] * atr[i], lambda j, M=M: c[j] > max(x[2] for x in b[j - M:j]), 250, R)
        else:
            px = b[i + 1][1]
            def ef(j, s=sig):
                m = sum(c[j - 19:j + 1]) / 20
                return c[j] >= m if s > 0 else c[j] <= m
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * atr[i], ef, 10, R)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid():
    for N in (10, 20, 55):
        for k in (2, 3):
            for M in (10, 20):
                yield "G1", {"N": N, "k": k, "M": M}
    for n in (50, 100, 200):
        yield "G2", {"n": n}
    for th in (5, 10, 15):
        yield "G3", {"th": th}
    for th in (0.1, 0.2):
        yield "G4", {"th": th}
    for N in (10, 20):
        for k in (2, 3):
            for M in (10, 20):
                yield "G5", {"N": N, "k": k, "M": M}
    yield "G6", {}


def main():
    data = {mk: ds.load(tk) for mk, tk in {"MHI": "^HSI", **CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    rows = []
    for fam, p in grid():
        tr = run2(data["MHI"], ind["MHI"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cross = {mk: ds.stats([x for x in run2(data[mk], ind[mk], fam, p) if x["d"] >= "2015-01-01"]) for mk in CROSS}
        cpos = sum(1 for v in cross.values() if v.get("avg", -1) > 0)
        q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
             "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        rows.append({"key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                     "cross": cross, "cross_pos": cpos, **q, "qualified": all(q.values())})
    ok = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["since2015"]["t"])
    print("== MHI 合格", len(ok))
    for r in sorted(rows, key=lambda r: -r["since2015"].get("t", -9))[:8]:
        print(" ", r["key"], "2015→", r["since2015"], "最終", r["final"], "搜尋", r["search"].get("avg"), "跨", r["cross_pos"], r["c1"], r["c2"], r["c3"], r["c4"])
    txt = json.dumps({"rows": rows, "pick": ok[0] if ok else None}, ensure_ascii=False)
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch3.json").upload_from_string(txt, content_type="application/json")


if __name__ == "__main__":
    main()
