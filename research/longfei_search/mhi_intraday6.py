"""[IDEAS #2038] MHI 日內第六批：A 股 15:00 收市帶恒指最後 90 分鐘（數據同 #2032；A 股日線由 yfinance；使用者 11-09「MHI 要揾更好策略，一直揾，揾到先停」）。

背景：A 股 15:00（香港時間）收市，恒指期貨日市 16:30 先收。南向資金同 A 股情緒對港股有預測力（Ding 等 2025，週度）；
期貨延長時段有價格發現（Cheng & Jiang 2004）。測 A 股收市方向會唔會延續到恒指最後 90 分鐘。
  A1 跟上證：上證當日報酬（收市÷前收−1）> +k／< −k → 恒指 15:00 後第一根開市入場跟方向，16:29 收市平。k＝0／0.5%
  A2 逆上證：同上逆方向。
  A3 跟滬深 300 日內：滬深 300 當日（收市÷開市−1）> +k／< −k → 同 A1 時間跟方向。k＝0／0.5%
成本每次來回 4 點；只計兩邊都有交易嘅日子。

預先登記（11-09，跑之前寫，唔再改）＝ #2032 MHI 日內條件（樣本內 2018-11→2022、樣本外 2023→；① 樣本外 n≥150、扣成本平均>0、t≥2.0、PF≥1.15；
  ② 樣本內同方向平均>0、t≥1.0；③ 樣本外年份 ≥3/4 正；④ 同家族另一組參數樣本外平均>0）。跟／逆分開兩個家族。
  合格 → 影子並排 AI 真倉，使用者批先換；冇 → #2039。
輸出：GCS longfei/strategy_search/mhi_intraday6.json。
"""
import json
import daily_search as ds
import mhi_intraday as mi

COST = mi.COST


def a_share():
    sse = ds.load("000001.SS")
    csi = ds.load("000300.SS")
    sret = {}
    for i in range(1, len(sse)):
        sret[sse[i][0]] = sse[i][4] / sse[i - 1][4] - 1
    cintra = {x[0]: x[4] / x[1] - 1 for x in csi if x[1]}
    return sret, cintra


def run(S, sig, fam, p):
    out = []
    for d in sorted(S):
        if d not in sig:
            continue
        seg = [x for x in S[d]["day"] if mi.tmin(x[0]) > 15 * 60]
        if len(seg) < 60:
            continue
        r0 = sig[d]
        if abs(r0) <= p["k"]:
            continue
        side = (1 if r0 > 0 else -1) * (-1 if fam == "A2" else 1)
        out.append({"d": d, "r": (seg[-1][4] - seg[0][1]) * side - COST})
    return out


def grid():
    for fam in ("A1", "A2", "A3"):
        for k in (0.0, 0.005):
            yield fam, {"k": k}


def main():
    S = mi.sessions(mi.load_bars())
    sret, cintra = a_share()
    print("上證", len(sret), "滬深300", len(cintra))
    rows = []
    for fam, p in grid():
        tr = run(S, cintra if fam == "A3" else sret, fam, p)
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/mhi_intraday6.json").upload_from_string(
        json.dumps({"rows": rows, "qualified_by_family": best}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
