"""[IDEAS #2014] 策略搜尋第十二批：NQ、ES 新家族（使用者 11-09「MHI、NQ、ES 每個搵到 3 個合格策略，總共 9 個先停」）。

只用之前未喺 NQ／ES 測過嘅家族（避免重用已睇過嘅結果）：
  V  VIX 恐慌：^VIX 收市 > 20 日平均 × m（1.3／1.5）而指數收市 < SMA20 → 翌日開市買，持有 H 日（5／10／20），止蝕 3×ATR（batch9.vixspike）
  P  長假前：交易日相隔 ≥ 4 日曆日前，第 −k 日收市買、假期前最後一日收市賣（k＝1／2／3）（batch9.holiday）
  O  隔夜：O1 收市買翌日開市賣；O2 同上但限收市 > SMA200（batch10.run10）
  W  52 週新高突破：收市破 250 日最高做好，止蝕 k×ATR（2／3），M 日低位出（20／50）（daily_search F2 N=250 只做好）
跨市場（冇參與揀選）：YM=F、RTY=F、^N225、^GDAXI、^FTSE（2015→）。成本、R 同之前。

預先登記（11-09，跑之前寫，唔再改）：
  低頻（V、P、W）＝ #2004 四條：① 該市場 2015→ n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0；② 2021→ 平均 > 0、年份 ≥ 4／6 正；③ 5 隻跨市場 ≥ 4 隻平均 > 0；④ 2000–2014 平均 > 0。
  高頻（O）＝ #2012 條件：① 2015→ n ≥ 200、t ≥ 2.5、PF ≥ 1.30；②③④ 同上。
  每個市場所有合格嘅都計入（唔限一個），但同一家族只計 t 最高一個（避免同一個想法換參數重複計數）。
  合格 → 影子前向（同 #2004），使用者批先真倉；冇 → 第十三批另行登記。
"""
import json
import daily_search as ds
import batch9 as b9
import batch10 as b10

MKTS = {"NQ": "NQ=F", "ES": "ES=F"}
CROSS = {"YM": "YM=F", "RTY": "RTY=F", "N225": "^N225", "DAX": "^GDAXI", "FTSE": "^FTSE"}


def grid():
    for m in (1.3, 1.5):
        for H in (5, 10, 20):
            yield "V", {"m": m, "H": H}
    for k in (1, 2, 3):
        yield "P", {"k": k}
    yield "O", {"v": "O1"}
    yield "O", {"v": "O2"}
    for k in (2, 3):
        for M in (20, 50):
            yield "W", {"k": k, "M": M}


def main():
    data = {mk: ds.load(tk) for mk, tk in {**MKTS, **CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    vix = {x[0]: x[4] for x in ds.load("^VIX")}
    es = {x[0]: x[4] for x in data["ES"]}

    def run(mk, fam, p):
        if fam == "V":
            return b9.vixspike(data[mk], ind[mk], vix, p["m"], p["H"])
        if fam == "P":
            return b9.holiday(data[mk], ind[mk], p["k"])
        if fam == "O":
            return b10.run10(data[mk], ind[mk], p["v"], es)
        return ds.run(data[mk], ind[mk], "F2", {"N": 250, "k": p["k"], "M": p["M"], "both": False})

    res = {}
    for mk in MKTS:
        rows = []
        for fam, p in grid():
            tr = run(mk, fam, p)
            s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
            fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
            srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
            cpos = sum(1 for c in CROSS if ds.stats([x for x in run(c, fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
            hf = fam == "O"
            c1 = (s15.get("n", 0) >= 200 and s15.get("t", 0) >= 2.5 and s15.get("pf", 0) >= 1.30) if hf else \
                 (s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
            q = {"c1": bool(c1), "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4,
                 "c4": bool(srch.get("avg", -9) > 0)}
            rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                         "cross_pos": cpos, **q, "qualified": all(q.values())})
            print(mk, fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, q, "✅" if all(q.values()) else "")
        best = {}
        for r in rows:
            if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
                best[r["fam"]] = r
        res[mk] = {"rows": rows, "qualified_by_family": best}
        print("==", mk, "合格家族", list(best))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch12.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
