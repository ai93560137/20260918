"""[IDEAS #2034] MHI 日內第二批（數據同 #2032：恒指期貨主連 1 分鐘，2018-11 起；使用者 11-09「MHI 要揾更好策略，一直揾，揾到先停」）。

家族（全部參數一次寫死；只用日市 09:15–16:30；成本每次來回 4 點）：
  G1 開市跳空回補：跳空＝日市開市價 − 前一日日市收市價；|跳空| ≥ k×20 日平均日市波幅（k＝0.3／0.5）→ 開市逆向入場，
     目標＝前一日收市價，止蝕＝入場價再向不利方向一個跳空距離，16:29 未到就收市平。
  V1 偏離 VWAP 回歸：10:00 之後，價格偏離當日累積 VWAP ≥ d（d＝0.6%／0.9%）→ 逆向入場，目標＝VWAP，止蝕＝入場價 ± 0.5×偏離，
     16:29 平；每日最多一單。
  T1 順日線趨勢開市區間突破：前一日日市收市 > 20 日平均＝只做好，< ＝只做淡；首 m 分鐘（m＝15／30）區間突破同方向先入，
     止蝕＝區間另一邊，16:29 平。
  R1 窄幅日之後開市區間突破：前一日日市波幅係 4 日最細（NR4）→ 今日首 m 分鐘（m＝15／30）區間突破雙向，止蝕＝區間另一邊，16:29 平。

預先登記（11-09，跑之前寫，唔再改）＝ #2032 MHI 日內條件：樣本內 2018-11→2022、樣本外 2023→而家；
  ① 樣本外 n ≥ 150、扣成本平均 > 0、t ≥ 2.0、PF ≥ 1.15；② 樣本內同方向平均 > 0、t ≥ 1.0；
  ③ 樣本外年份 ≥ 3/4 正；④ 同家族另一組參數樣本外平均 > 0。同一家族只計 t 最高一組。
  合格 → 影子前向（30 張或 3 個月），同而家 MHI AI 真倉並排比較，使用者批先換；冇 → #2035 另行登記。
輸出：GCS longfei/strategy_search/mhi_intraday2.json。
"""
import json
import mhi_intraday as mi

COST = mi.COST


def day_bars(S):
    """每日日市 (開, 高, 低, 收)。"""
    out = {}
    for d, s in S.items():
        b = s["day"]
        if len(b) >= 100:
            out[d] = (b[0][1], max(x[2] for x in b), min(x[3] for x in b), b[-1][4])
    return out


def exit_path(seg, side, entry, stop, target):
    for y in seg:
        if (side > 0 and y[3] <= stop) or (side < 0 and y[2] >= stop):
            return (stop - entry) * side - COST
        if target is not None and ((side > 0 and y[2] >= target) or (side < 0 and y[3] <= target)):
            return (target - entry) * side - COST
    return (seg[-1][4] - entry) * side - COST


def orb_dir(seg, m, allow):
    if len(seg) < m + 10:
        return None
    hi = max(x[2] for x in seg[:m]); lo = min(x[3] for x in seg[:m])
    for k, x in enumerate(seg[m:], start=m):
        up, dn = x[2] > hi, x[3] < lo
        if up and dn:
            return None
        if up and allow >= 0:
            return exit_path(seg[k:], 1, hi, lo, None)
        if dn and allow <= 0:
            return exit_path(seg[k:], -1, lo, hi, None)
        if up or dn:
            return None                              # 突破方向唔准做：當日唔做
    return None


def run(S, D, fam, p):
    ds = [d for d in sorted(S) if d in D]
    out = []
    for i, d in enumerate(ds):
        if i < 21:
            continue
        seg = S[d]["day"]
        if len(seg) < 100:
            continue
        prev = ds[i - 1]
        rng20 = sum(D[x][1] - D[x][2] for x in ds[i - 20:i]) / 20
        r = None
        if fam == "G1":
            gap = D[d][0] - D[prev][3]
            if abs(gap) >= p["k"] * rng20 and gap != 0:
                side = -1 if gap > 0 else 1
                entry = seg[0][1]
                r = exit_path(seg, side, entry, entry - side * abs(gap), D[prev][3])
        elif fam == "V1":
            pv = vv = 0.0
            for k, x in enumerate(seg):
                tp = (x[2] + x[3] + x[4]) / 3
                v = x[5] if len(x) > 5 and x[5] else 1.0
                pv += tp * v; vv += v
                if mi.tmin(x[0]) < 10 * 60:
                    continue
                vwap = pv / vv
                dev = x[4] / vwap - 1
                if abs(dev) >= p["d"]:
                    side = -1 if dev > 0 else 1
                    entry = x[4]
                    stop = entry - side * 0.5 * abs(entry - vwap)
                    r = exit_path(seg[k + 1:] or seg[-1:], side, entry, stop, vwap)
                    break
        elif fam == "T1":
            closes = [D[x][3] for x in ds[i - 20:i]]
            allow = 1 if D[prev][3] > sum(closes) / 20 else -1
            r = orb_dir(seg, p["m"], allow)
        elif fam == "R1":
            last4 = [D[x][1] - D[x][2] for x in ds[i - 4:i]]
            if last4[-1] == min(last4):
                r = orb_dir(seg, p["m"], 0)
        if r is not None:
            out.append({"d": d, "r": r})
    return out


def grid():
    for k in (0.3, 0.5):
        yield "G1", {"k": k}
    for dv in (0.006, 0.009):
        yield "V1", {"d": dv}
    for m in (15, 30):
        yield "T1", {"m": m}
    for m in (15, 30):
        yield "R1", {"m": m}


def main():
    days = mi.load_bars_full()
    S = mi.sessions(days)
    D = day_bars(S)
    ds = sorted(D)
    print("交易日", len(D), ds[0], "→", ds[-1])
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/mhi_intraday2.json").upload_from_string(
        json.dumps({"days": len(D), "rows": rows, "qualified_by_family": best}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
