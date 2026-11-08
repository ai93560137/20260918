"""[IDEAS #2009] 策略搜尋第七批：MHI 組合（將 #2006／#2008 幾條「差少少」嘅策略一齊做）。

單條都唔過 t≥2，但如果彼此唔相關，一齊做每筆平均唔變、筆數多咗，t 會升。組合（預先寫死，唔再揀）：
  C1＝K3 月度動量 L6 雙向（#2008）＋ H1 市況切換 Donchian55 k2 M20（#2006）
  C2＝C1 ＋ K2 週度動量 L4 雙向（#2008）
  C3＝K3 L6 雙向 ＋ K2 L4 雙向（只動量）
每條策略每筆都係 1 張（各自 R），組合嘅交易＝所有成員交易合埋（可以同時有倉，即係最多 2–3 張 MHI）。
跨市場（冇參與揀選）：^TWII、^KS11、^N225、^AXJO、000001.SS。

預先登記（11-09，跑之前寫，唔再改）——同 #2004 四條，用組合嘅全部交易計：
  ① 2015→：n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0；② 2021→：平均 > 0、年份 ≥ 4／6 正；③ 亞洲 5 隻 ≥ 4 正；④ 2000–2014 平均 > 0。
  另外報（唔係條件）：成員之間嘅月度 R 相關系數。
  注意：成員係由之前批次揀出嚟（見過 2015→ 數據），① 有樣本內偏差；③ 跨市場係主要防偏差。合格都要影子前向先講真倉。
  冇合格 → 承認日線／1 小時經典規則喺恒指搵唔到合格策略，向使用者報告，提議 MHI 改用 NQ／ES 合格策略嘅思路或者維持 AI 判斷，唔再無限加批次（避免過度搜尋）。
"""
import json
import statistics
import daily_search as ds
import batch3 as b3
import batch4 as b4
import batch6 as b6

MEMBERS = {"K3": ("b6", "K3", {"L": 6, "both": True}), "H1": ("b4", "H1", {"N": 55, "k": 2, "M": 20}),
           "K2": ("b6", "K2", {"L": 4, "both": True})}
COMBOS = {"C1": ["K3", "H1"], "C2": ["K3", "H1", "K2"], "C3": ["K3", "K2"]}


def member(b, ind, m):
    mod, fam, p = MEMBERS[m]
    return (b6.run6 if mod == "b6" else b4.run4)(b, ind, fam, p)


def monthly(tr):
    out = {}
    for x in tr:
        out[x["d"][:7]] = out.get(x["d"][:7], 0) + x["r"]
    return out


def corr(a, b):
    ks = sorted(set(a) & set(b))
    if len(ks) < 10:
        return None
    x, y = [a[k] for k in ks], [b[k] for k in ks]
    return round(statistics.correlation(x, y), 2) if statistics.pstdev(x) and statistics.pstdev(y) else None


def main():
    data = {mk: ds.load(tk) for mk, tk in {"MHI": "^HSI", **b3.CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    mem = {mk: {m: member(data[mk], ind[mk], m) for m in MEMBERS} for mk in data}
    mo = {m: monthly([x for x in mem["MHI"][m] if x["d"] >= "2015-01-01"]) for m in MEMBERS}
    res = {"corr_2015": {f"{a}-{b}": corr(mo[a], mo[b]) for a in MEMBERS for b in MEMBERS if a < b}, "rows": []}
    for cname, ms in COMBOS.items():
        tr = sorted([x for m in ms for x in mem["MHI"][m]], key=lambda x: x["d"])
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cross = {mk: ds.stats([x for m in ms for x in mem[mk][m] if x["d"] >= "2015-01-01"]) for mk in b3.CROSS}
        cpos = sum(1 for v in cross.values() if v.get("avg", -1) > 0)
        q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
             "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        row = {"combo": cname, "members": ms, "since2015": s15, "final": fin, "search": srch, "cross_pos": cpos, **q, "qualified": all(q.values())}
        res["rows"].append(row)
        print(cname, ms, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, q, "✅" if row["qualified"] else "")
    print("相關", res["corr_2015"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch7.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
