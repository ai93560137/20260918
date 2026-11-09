"""[IDEAS #2037] MHI 日內第五批：日線市況定方向，每個時段都跟方向做（交易次數多、統計力夠）
（數據同 #2032：恒指期貨主連 1 分鐘，日線由日市 OHLC 組成；使用者 11-09「MHI 要揾更好策略，一直揾，揾到先停」）。

市況（前一日收市計，唔偷看）：升市＝收市 > SMA(L) 而 SMA20 > SMA(L)；跌市＝收市 < SMA(L) 而 SMA20 < SMA(L)；其他＝唔做。L＝50／100。
  W1 日市跟市況：升市日市開買收賣；跌市開沽收平。
  W2 夜市跟市況：升市夜市開買、凌晨收市平；跌市鏡像。
  W3 市況＋前一日回吐：升市而前一日日市收跌 → 今日日市做好；跌市而前一日收升 → 做淡。
成本每次來回 4 點。

預先登記（11-09，跑之前寫，唔再改）＝ #2032 MHI 日內條件（樣本內 2018-11→2022、樣本外 2023→；① 樣本外 n≥150、扣成本平均>0、t≥2.0、PF≥1.15；
  ② 樣本內同方向平均>0、t≥1.0；③ 樣本外年份 ≥3/4 正；④ 同家族另一組參數樣本外平均>0）。合格 → 影子並排 AI 真倉，使用者批先換；冇 → #2038。
輸出：GCS longfei/strategy_search/mhi_intraday5.json。
"""
import json
import mhi_intraday as mi
import mhi_intraday2 as m2

COST = mi.COST


def regime(closes, L):
    if len(closes) < L:
        return 0
    c = closes[-1]
    sl = sum(closes[-L:]) / L
    s20 = sum(closes[-20:]) / 20
    if c > sl and s20 > sl:
        return 1
    if c < sl and s20 < sl:
        return -1
    return 0


def run(S, D, fam, p):
    ds = [d for d in sorted(S) if d in D]
    out = []
    for i in range(p["L"] + 1, len(ds)):
        d = ds[i]
        closes = [D[x][3] for x in ds[:i]]
        rg = regime(closes, p["L"])
        if not rg:
            continue
        s = S[d]
        r = None
        if fam == "W1":
            r = (s["day"][-1][4] - s["day"][0][1]) * rg - COST
        elif fam == "W2" and len(s["night"]) > 200:
            r = (s["night"][-1][4] - s["night"][0][1]) * rg - COST
        elif fam == "W3":
            po, ph, pl, pc = D[ds[i - 1]]
            if (rg > 0 and pc < po) or (rg < 0 and pc > po):
                r = (s["day"][-1][4] - s["day"][0][1]) * rg - COST
        if r is not None:
            out.append({"d": d, "r": r})
    return out


def grid():
    for fam in ("W1", "W2", "W3"):
        for L in (50, 100):
            yield fam, {"L": L}


def main():
    S = mi.sessions(mi.load_bars())
    D = m2.day_bars(S)
    rows = []
    for fam, p in grid():
        tr = run(S, D, fam, p)
        rows.append({"fam": fam, "p": p, "key": f"{fam} {json.dumps(p)}",
                     "is": mi.stats([x for x in tr if x["d"] <= mi.IS_END]),
                     "oos": mi.stats([x for x in tr if x["d"] >= mi.OOS_START])})
    for r in rows:
        o, i_ = r["oos"], r["is"]
        sib = [x for x in rows if x["fam"] == r["fam"] and x is not r]
        q = {"c1": bool(o.get("n", 0) >= 150 and o.get("avg", -9) > 0 and o.get("t", 0) >= 2.0 and o.get("pf", 0) >= 1.15),
             "c2": bool(i_.get("avg", -9) > 0 and i_.get("t", 0) >= 1.0),
             "c3": bool(o.get("years_pos", 0) >= 3),
             "c4": bool(sib and all(x["oos"].get("avg", -9) > 0 for x in sib))}
        r.update(q, qualified=all(q.values()))
        print(r["key"], "樣本內", {k: i_.get(k) for k in ("n", "avg", "t", "pf")}, "樣本外", {k: o.get(k) for k in ("n", "avg", "t", "pf")},
              o.get("by_year"), q, "✅" if r["qualified"] else "")
    best = {}
    for r in rows:
        if r["qualified"] and (r["fam"] not in best or r["oos"]["t"] > best[r["fam"]]["oos"]["t"]):
            best[r["fam"]] = r
    print("== 合格家族", list(best))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/mhi_intraday5.json").upload_from_string(
        json.dumps({"rows": rows, "qualified_by_family": best}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
