"""[IDEAS #2004] 龍飛陣策略搜尋第二批：低頻順勢策略 + 跨市場驗證（第一批 #2003 結果：NQ／ES Donchian 只做好最終段好，但筆數 15–28 < 40）。

第一批顯示日線順勢（F2 Donchian 只做好、F1 200 日線）喺 NQ／ES 有優勢但出手少，所以 n≥40 唔合理。
第二批改用「跨市場驗證」代替筆數：揀定嘅設定要喺其他 5 隻冇參與揀選嘅指數都賺錢，先算唔係運氣。
候選（全部預先寫死，唔再加）：
  F2 只做好：N∈{10,15,20} k∈{2,3} M∈{10,20}（12 組；20 係第一批入圍，10／15 係新加較快版本）
  F1 只做好：n∈{100,200}（2 組）
市場：MHI（^HSI）、NQ（NQ=F）、ES（ES=F）；跨市場驗證：YM=F、RTY=F、^N225、^GDAXI、^FTSE（2015 起）。
成本、R、執行同第一批一樣（rules from daily_search.py）。

預先登記（11-09，跑之前寫，唔再改）——某市場某設定「合格」要全部符合：
  ① 嗰個市場 2015→而家（驗證＋最終合併）：n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0
  ② 最終段 2021→：平均 > 0、有交易年份 ≥ 4／6 正數
  ③ 跨市場：同一設定喺 5 隻其他指數 2015→ 至少 4 隻平均 R > 0
  ④ 搜尋段 2000–2014 平均 R > 0（唔係只喺近年先得）
  每個市場如果多過一個合格，揀 ① 嘅 t 最高嗰個。合格 → 影子前向（日線，出手少，目標 10 張或 6 個月），使用者批先上真倉；冇合格 → 第三批。
"""
import json
import statistics
import daily_search as ds

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
CROSS = {"YM": "YM=F", "RTY": "RTY=F", "N225": "^N225", "DAX": "^GDAXI", "FTSE": "^FTSE"}


def grid():
    for N in (10, 15, 20):
        for k in (2, 3):
            for M in (10, 20):
                yield "F2", {"N": N, "k": k, "M": M, "both": False}
    for n in (100, 200):
        yield "F1", {"n": n, "both": False}


def main():
    data = {}
    for mk, tk in {**MKTS, **CROSS}.items():
        b = ds.load(tk)
        data[mk] = (b, ds.indicators(b))
    res = {"markets": {}, "cross": {}}
    cross_tr = {}
    for fam, p in grid():
        key = f"{fam} {json.dumps(p, sort_keys=True)}"
        cross_tr[key] = {mk: ds.stats([x for x in ds.run(*data[mk], fam, p) if x["d"] >= "2015-01-01"]) for mk in CROSS}
    res["cross"] = cross_tr
    for mk in MKTS:
        b, ind = data[mk]
        rows = []
        for fam, p in grid():
            key = f"{fam} {json.dumps(p, sort_keys=True)}"
            tr = ds.run(b, ind, fam, p)
            s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
            fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
            srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
            cpos = sum(1 for v in cross_tr[key].values() if v.get("avg", -1) > 0)
            q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
                 "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4),
                 "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
            rows.append({"key": key, "since2015": s15, "final": fin, "search": srch, "cross_pos": cpos, **q,
                         "qualified": all(q.values())})
        ok = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["since2015"]["t"])
        res["markets"][mk] = {"rows": rows, "pick": ok[0] if ok else None}
        print(f"== {mk} 合格 {len(ok)}")
        for r in sorted(rows, key=lambda r: -r["since2015"].get("t", -9))[:5]:
            print(" ", r["key"], "2015→", r["since2015"], "最終", r["final"], "跨市場正", r["cross_pos"], "/5",
                  "①②③④", r["c1"], r["c2"], r["c3"], r["c4"], "✅" if r["qualified"] else "")
    txt = json.dumps(res, ensure_ascii=False)
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch2.json").upload_from_string(txt, content_type="application/json")


if __name__ == "__main__":
    main()
