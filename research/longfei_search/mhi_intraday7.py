"""[IDEAS #2039] MHI 4 小時 inside bar（使用者 11-11／11-12 文章嘅主要工具；數據同 #2032：恒指期貨主連 1 分鐘，2018-11 起）。

使用者用法：關鍵位攻唔破＋收 inside bar →「空軍得閃人」（11/10 ES 7500）；7665 站唔上＋向下 inside bar → 多方要小心（11/11）。
網上搵唔到 inside bar 嘅可信回測（全部係平台示範／論壇），所以用恒指期貨自己測。
4 小時 K（香港時間）：00:00、08:00、12:00、16:00、20:00 起計（同網頁恒指圖一樣；00:00 嗰根只到 03:00）。
inside bar＝高 ≤ 前一根高、低 ≥ 前一根低。成本每次來回 4 點。入場價＝inside bar 收市（I2／I3）或者突破位（I1）。
  I1 突破跟：inside bar 之後 2 根 K 內，先升穿 inside bar 高位做好／先跌穿低位做淡（同一根兩邊都穿就跳過）；
     止蝕＝inside bar 另一邊；入場後第 N 根收市平（N＝3／6）。
  I2 攻唔破＋inside bar（使用者 11/10 用法）：前一根 K 創咗 10 根新低而 inside bar 冇再破 → inside bar 收市做好，止蝕＝前一根低位；
     前一根創 10 根新高而 inside bar 冇再破 → 做淡，止蝕＝前一根高位；第 N 根收市平（N＝3／6）。
  I3 inside bar 方向（使用者圖上 ▲／▼）：收紅（收 ≥ 開）做好、收黑做淡，止蝕＝前一根對應嘅高／低位；第 N 根收市平（N＝3／6）。

預先登記（11-12，跑之前寫，唔再改）＝ #2032 MHI 日內條件（樣本內 2018-11→2022、樣本外 2023→；① 樣本外 n≥150、扣成本平均>0、t≥2.0、PF≥1.15；
  ② 樣本內同方向平均>0、t≥1.0；③ 樣本外年份 ≥3/4 正；④ 同家族另一組參數樣本外平均>0）。
  合格 → 影子並排 AI 真倉，使用者批先換；冇 → #2040。結果唔會用嚟評使用者文章（佢係配合關鍵位用，呢度係純機械版）。
輸出：GCS longfei/strategy_search/mhi_intraday7.json。
"""
import json
import mhi_intraday as mi

COST = mi.COST


def h4(days):
    """{日期: [(HH:MM, o, h, l, c, v)…]} → 4 小時 K [(key, o, h, l, c)]，key＝'YYYY-MM-DD HH'（00／08／12／16／20）。"""
    out = {}
    for d in sorted(days):
        for t, o, h, lo, c, *_ in days[d]:
            m = mi.tmin(t) - 1                     # time_key 係結束時間
            if m < 0:
                continue                           # 00:00 嗰分鐘屬前一日 23:59，量好細，略過
            hh = m // 60
            blk = 0 if hh < 4 else 8 if hh < 12 else 12 if hh < 16 else 16 if hh < 20 else 20
            k = f"{d} {blk:02d}"
            x = out.get(k)
            out[k] = [k, o, h, lo, c] if x is None else [k, x[1], max(x[2], h), min(x[3], lo), c]
    return [out[k] for k in sorted(out)]


def hold(b, i, side, entry, stop, n):
    """由第 i+1 根起揸 n 根；掂止蝕就止蝕；第 n 根收市平。回傳點數（已扣成本）。"""
    for j in range(i + 1, min(i + 1 + n, len(b))):
        if (side > 0 and b[j][3] <= stop) or (side < 0 and b[j][2] >= stop):
            return (stop - entry) * side - COST
    j = min(i + n, len(b) - 1)
    return (b[j][4] - entry) * side - COST


def run(b, fam, p):
    out = []
    for i in range(11, len(b) - 8):
        x, pv = b[i], b[i - 1]
        if not (x[2] <= pv[2] and x[3] >= pv[3]) or x[2] == x[3]:
            continue
        day = x[0][:10]
        if fam == "I1":
            for j in (i + 1, i + 2):
                up, dn = b[j][2] > x[2], b[j][3] < x[3]
                if up and dn:
                    break
                if up or dn:
                    side = 1 if up else -1
                    entry, stop = (x[2], x[3]) if up else (x[3], x[2])
                    # 入場嗰根之後先計止蝕（同一根已經排除兩邊都穿）
                    out.append({"d": day, "r": hold(b, j, side, entry, stop, p["n"])})
                    break
        elif fam == "I2":
            lo10 = min(y[3] for y in b[i - 11:i - 1])
            hi10 = max(y[2] for y in b[i - 11:i - 1])
            if pv[3] < lo10 and not pv[2] > hi10:
                out.append({"d": day, "r": hold(b, i, 1, x[4], pv[3], p["n"])})
            elif pv[2] > hi10 and not pv[3] < lo10:
                out.append({"d": day, "r": hold(b, i, -1, x[4], pv[2], p["n"])})
        elif fam == "I3":
            side = 1 if x[4] >= x[1] else -1
            out.append({"d": day, "r": hold(b, i, side, x[4], pv[3] if side > 0 else pv[2], p["n"])})
    return out


def grid():
    for fam in ("I1", "I2", "I3"):
        for n in (3, 6):
            yield fam, {"n": n}


def main():
    b = h4(mi.load_bars())
    ins = sum(1 for i in range(1, len(b)) if b[i][2] <= b[i - 1][2] and b[i][3] >= b[i - 1][3])
    print("4 小時 K", len(b), b[0][0], "→", b[-1][0], "inside bar", ins, f"({ins / len(b):.1%})")
    rows = []
    for fam, p in grid():
        tr = run(b, fam, p)
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/mhi_intraday7.json").upload_from_string(
        json.dumps({"bars": len(b), "inside": ins, "rows": rows, "qualified_by_family": best}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
