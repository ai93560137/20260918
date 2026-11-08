"""[IDEAS #2008] 策略搜尋第六批：MHI 時間序列動量（月度／週度持倉）——Moskowitz、Ooi、Pedersen 2012《Time Series Momentum》喺 58 隻期貨（包括股指）都成立。

#2003–#2007 MHI 日線／1 小時規則全部唔合格。今批改用較長持倉：
  K1 月度：每月最後一個交易日收市，過去 L 個月報酬 > 0 做好（雙向版本 < 0 做淡；只做好版本 < 0 就空手），持有一個月。L∈{3,6,12}
  K2 週度：每週最後一個交易日收市，過去 L 週報酬 > 0 做好（同上兩個版本），持有一週。L∈{4,13,26}
  K3 月度＋200 日線：K1 加條件——收市 > SMA200 先准做好、< SMA200 先准做淡。L∈{3,6,12}
執行：收市出訊號、收市入（期貨可以收市前落單），下期收市平；止蝕冇（持倉期固定）；成本來回 0.03%；R＝2×ATR(14)（同之前批次一樣，方便比較）。
跨市場（冇參與揀選）：^TWII、^KS11、^N225、^AXJO、000001.SS。

預先登記（11-09，跑之前寫，唔再改）——同 #2004 四條：
  ① MHI 2015→：n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0；② 2021→：平均 > 0、年份 ≥ 4／6 正；③ 亞洲 5 隻 ≥ 4 隻平均 R > 0；④ 2000–2014 平均 R > 0。
  多過一個揀 ① t 最高。合格 → 影子前向（月度出手少，目標 6 張或 6 個月）；冇 → 第七批另行登記。
"""
import json
import daily_search as ds
import batch3 as b3


def run6(b, ind, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"][200]
    n = len(b)
    if fam in ("K1", "K3"):
        ends = [i for i in range(n - 1) if b[i + 1][0][:7] != b[i][0][:7]]
        step = 1
    else:
        from datetime import date
        wk = lambda i: date.fromisoformat(b[i][0]).isocalendar()[:2]  # noqa: E731
        ends = [i for i in range(n - 1) if wk(i + 1) != wk(i)]
    out = []
    L = p["L"]
    for a, e in enumerate(ends):
        if a < L or a + 1 >= len(ends) or atr[e] is None or (fam == "K3" and S[e] is None):
            continue
        past = c[e] / c[ends[a - L]] - 1
        side = 1 if past > 0 else (-1 if p["both"] else 0)
        if fam == "K3":
            side = 1 if past > 0 and c[e] > S[e] else (-1 if p["both"] and past < 0 and c[e] < S[e] else 0)
        if not side:
            continue
        x = ends[a + 1]
        r = ((c[x] - c[e]) * side - 0.0003 * c[e]) / (2 * atr[e])
        out.append({"d": b[e][0], "r": r})
    return out


def grid():
    for L in (3, 6, 12):
        for both in (False, True):
            yield "K1", {"L": L, "both": both}
            yield "K3", {"L": L, "both": both}
    for L in (4, 13, 26):
        for both in (False, True):
            yield "K2", {"L": L, "both": both}


def main():
    data = {mk: ds.load(tk) for mk, tk in {"MHI": "^HSI", **b3.CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    rows = []
    for fam, p in grid():
        tr = run6(data["MHI"], ind["MHI"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cross = {mk: ds.stats([x for x in run6(data[mk], ind[mk], fam, p) if x["d"] >= "2015-01-01"]) for mk in b3.CROSS}
        cpos = sum(1 for v in cross.values() if v.get("avg", -1) > 0)
        q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
             "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        rows.append({"key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                     "cross_pos": cpos, **q, "qualified": all(q.values())})
    ok = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["since2015"]["t"])
    print("== MHI 合格", len(ok))
    for r in sorted(rows, key=lambda r: -r["since2015"].get("t", -9))[:8]:
        print(" ", r["key"], "2015→", r["since2015"], "最終", r["final"], "搜尋", r["search"].get("avg"), "跨", r["cross_pos"], r["c1"], r["c2"], r["c3"], r["c4"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch6.json").upload_from_string(
        json.dumps({"rows": rows, "pick": ok[0] if ok else None}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
