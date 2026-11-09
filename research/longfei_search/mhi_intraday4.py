"""[IDEAS #2036] MHI 日內第四批：入場用「順日線趨勢開市區間突破」（#2034 T1，AI 真倉主要做法），改出場；加假突破反轉
（數據同 #2032；使用者 11-09「MHI 要揾更好策略，一直揾，揾到先停」）。

  S1 突破後持倉過夜：T1 入場（首 m 分鐘區間，m＝15／30），止蝕＝區間另一邊；之後每日日市收市檢查，
     好倉跌穿前一日日市低位／淡倉升穿前一日日市高位就平（用收市價），最多 10 個交易日。
  S2 突破＋固定目標：T1 入場，目標＝入場 ± r×區間闊度（r＝1.5／2.5），止蝕＝區間另一邊，日市收市未到就平。
  S3 假跌破／假突破反轉（turtle soup）：日線升勢（前一日收市 > 20 日平均）而日市跌穿前一日低位再收返上去（1 分鐘收市重返）→ 做好，
     止蝕＝當日最低 − b 點（b＝10／30），日市收市平；跌勢鏡像。
成本每次來回 4 點（S1 隔夜唔另計）。

預先登記（11-09，跑之前寫，唔再改）＝ #2032 MHI 日內條件（樣本內 2018-11→2022、樣本外 2023→；① 樣本外 n≥150、扣成本平均>0、t≥2.0、PF≥1.15；
  ② 樣本內同方向平均>0、t≥1.0；③ 樣本外年份 ≥3/4 正；④ 同家族另一組參數樣本外平均>0）。S1 n 可能少過 150，照登記唔改。
  合格 → 影子並排 AI 真倉，使用者批先換；冇 → #2037。
輸出：GCS longfei/strategy_search/mhi_intraday4.json。
"""
import json
import mhi_intraday as mi
import mhi_intraday2 as m2

COST = mi.COST


def orb_entry(seg, m, allow):
    """回傳 (side, entry, stop, k_index, rng) 或 None。"""
    if len(seg) < m + 10:
        return None
    hi = max(x[2] for x in seg[:m]); lo = min(x[3] for x in seg[:m])
    for k, x in enumerate(seg[m:], start=m):
        up, dn = x[2] > hi, x[3] < lo
        if up and dn:
            return None
        if up and allow >= 0:
            return 1, hi, lo, k, hi - lo
        if dn and allow <= 0:
            return -1, lo, hi, k, hi - lo
        if up or dn:
            return None
    return None


def run(S, D, fam, p):
    ds = [d for d in sorted(S) if d in D]
    out = []
    i = 21
    while i < len(ds):
        d = ds[i]
        seg = S[d]["day"]
        prev = ds[i - 1]
        closes = [D[x][3] for x in ds[i - 20:i]]
        trend = 1 if D[prev][3] > sum(closes) / 20 else -1
        r, skip = None, 0
        if fam in ("S1", "S2") and len(seg) >= 100:
            e = orb_entry(seg, p["m"], trend)
            if e:
                side, entry, stop, k, rng = e
                if fam == "S2":
                    r = m2.exit_path(seg[k:], side, entry, stop, entry + side * p["r"] * rng)
                else:
                    # 當日：止蝕先；收市仍持倉就逐日檢查
                    hit = None
                    for y in seg[k:]:
                        if (side > 0 and y[3] <= stop) or (side < 0 and y[2] >= stop):
                            hit = (stop - entry) * side - COST
                            break
                    if hit is not None:
                        r = hit
                    else:
                        j = i
                        while True:
                            dj = ds[j]
                            o, h, l, c = D[dj]
                            if j > i:
                                ph, pl = D[ds[j - 1]][1], D[ds[j - 1]][2]
                                if (side > 0 and c < pl) or (side < 0 and c > ph) or j - i >= 10 or j == len(ds) - 1:
                                    r = (c - entry) * side - COST
                                    skip = j - i
                                    break
                            if j == len(ds) - 1:
                                r = (c - entry) * side - COST
                                break
                            j += 1
        elif fam == "S3" and len(seg) >= 100:
            ph, pl = D[prev][1], D[prev][2]
            low = high = None
            for k, x in enumerate(seg):
                low = x[3] if low is None else min(low, x[3])
                high = x[2] if high is None else max(high, x[2])
                if trend > 0 and low < pl and x[4] > pl and k > 0:
                    entry = x[4]
                    r = m2.exit_path(seg[k + 1:] or seg[-1:], 1, entry, low - p["b"], None)
                    break
                if trend < 0 and high > ph and x[4] < ph and k > 0:
                    entry = x[4]
                    r = m2.exit_path(seg[k + 1:] or seg[-1:], -1, entry, high + p["b"], None)
                    break
        if r is not None:
            out.append({"d": d, "r": r})
        i += 1 + skip
    return out


def grid():
    for m in (15, 30):
        yield "S1", {"m": m}
    for rr in (1.5, 2.5):
        yield "S2", {"m": 15, "r": rr}
    for b in (10, 30):
        yield "S3", {"b": b}


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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/mhi_intraday4.json").upload_from_string(
        json.dumps({"rows": rows, "qualified_by_family": best}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
