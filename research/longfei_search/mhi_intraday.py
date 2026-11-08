"""[IDEAS #2032] MHI 日內／夜市第一批（數據：#2031 回補嘅恒指期貨主連 1 分鐘 K 線，GCS longfei/bars/HSI/，2018-11 起，含夜市）。

使用者 11-09「繼續做研究直至 MHI、NQ 同 ES 每個 3 個合格」→ MHI 日線 26 批冇合格 → 揀「1」改用期貨分鐘數據。
時段（香港時間；Futu time_key 係每分鐘 K 線結束時間）：
  日市 D：09:15–16:30（午休 12:00–13:00）；夜市 D：17:15–23:59（D）＋ 00:00–03:00（D+1）。
  時段入場價＝時段第一根開市價；出場價＝時段最後一根收市價。成本：每次來回 4 點（MHI 1 點＝HK$10，含滑價同佣金）。

家族（全部參數一次寫死）：
  N1／N2 夜帶日：前一晚夜市（D−1 夜）報酬 > +k／< −k → 日市 D 跟（N1）／逆（N2）方向，日市開入、收出。k＝0／0.3%
  D1／D2 日帶夜：日市 D 報酬 > +k／< −k → 夜市 D 跟（D1）／逆（D2）。k＝0／0.3%
  L1／L2 午市跟／逆早市：早市（09:15–12:00）報酬 > +k／< −k → 午市（13:00–16:30）跟（L1）／逆（L2）。k＝0／0.2%
  O1 日市開市區間突破：首 m 分鐘（m＝15／30）高低位，之後第一次升穿高位做好（止蝕低位）、跌穿低位做淡（止蝕高位），16:29 收市平；每日最多一單。
  O2 夜市開市區間突破：夜市首 m 分鐘（m＝30／60），規則同 O1，02:59 收市平。
  M1 日內動量（Gao 等 2018）：日市首 30 分鐘報酬 > +k／< −k → 最後 30 分鐘（16:00–16:30）跟方向。k＝0／0.2%

預先登記（11-09，跑之前寫，唔再改）——MHI 日內條件（新數據冇 2000–2014，唔可以用 #2004／#2021 嘅 ④；跨市場冇長分鐘數據，改用參數鄰域）：
  樣本內 2018-11→2022-12；樣本外 2023-01→而家（一次過）。
  ① 樣本外 n ≥ 150、扣成本後每筆平均 > 0、t ≥ 2.0、PF ≥ 1.15；
  ② 樣本內同方向：平均 > 0、t ≥ 1.0；
  ③ 樣本外年份（2023／2024／2025／2026）≥ 3 個正數；
  ④ 參數鄰域：同家族另一組參數樣本外平均都 > 0。
  跟／逆係兩個家族（最多一個合格）；同一家族只計 t 最高一組。合格 → 影子前向（30 張或 3 個月），使用者批先真倉；冇 → #2033 另行登記。
輸出：GCS longfei/strategy_search/mhi_intraday.json。
"""
import json
import math
import statistics
from datetime import date, timedelta

COST = 4.0
IS_END, OOS_START = "2022-12-31", "2023-01-01"


def load_bars():
    from google.cloud import storage
    cli = storage.Client()
    b = cli.bucket("zhuge-risk-manager-bucket")
    days = {}
    for blob in cli.list_blobs(b, prefix="longfei/bars/HSI/"):
        if not blob.name.endswith(".json"):
            continue
        d = json.loads(blob.download_as_text())
        days[d["date"]] = [(r[0], r[1], r[2], r[3], r[4]) for r in d["bars"]]
    return days


def tmin(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def sessions(days):
    """→ {D: {"day": [...], "am": [...], "pm": [...], "night": [...]}}，bar=(t, o, h, l, c)。"""
    out = {}
    for d, bars in days.items():
        s = out.setdefault(d, {"day": [], "am": [], "pm": [], "night": []})
        for bar in bars:
            m = tmin(bar[0])
            if 9 * 60 + 15 <= m <= 16 * 60 + 30:
                s["day"].append(bar)
                if m <= 12 * 60:
                    s["am"].append(bar)
                elif m > 13 * 60:
                    s["pm"].append(bar)
            elif m >= 17 * 60 + 15:
                s["night"].append(bar)
            elif m <= 3 * 60:
                # 夜市凌晨部分屬於前一日嘅夜市
                prev = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
                out.setdefault(prev, {"day": [], "am": [], "pm": [], "night": []})["night"].append(bar)
    for s in out.values():
        for k in ("day", "am", "pm"):
            s[k].sort(key=lambda x: tmin(x[0]))
        s["night"].sort(key=lambda x: (tmin(x[0]) < 4 * 60, tmin(x[0])))   # 17:15→23:59 先、00:00→03:00 後
    return {d: s for d, s in out.items() if s["day"]}


def ret(seg):
    return (seg[-1][4] / seg[0][1] - 1) if seg else None


def pnl(seg, side):
    return (seg[-1][4] - seg[0][1]) * side - COST


def orb(seg, m):
    if len(seg) < m + 10:
        return None
    hi = max(x[2] for x in seg[:m]); lo = min(x[3] for x in seg[:m])
    for x in seg[m:]:
        if x[2] > hi and x[3] < lo:
            return None                                  # 同一分鐘兩邊都穿，唔知先後，跳過
        if x[2] > hi:
            side, entry, stop = 1, hi, lo
            break
        if x[3] < lo:
            side, entry, stop = -1, lo, hi
            break
    else:
        return None
    idx = seg.index(x)
    for y in seg[idx:]:
        if (side > 0 and y[3] <= stop) or (side < 0 and y[2] >= stop):
            return (stop - entry) * side - COST
    return (seg[-1][4] - entry) * side - COST


def run(S, fam, p):
    ds = sorted(S)
    out = []
    for i, d in enumerate(ds):
        s = S[d]
        r = None
        if fam in ("N1", "N2") and i > 0:
            nr = ret(S[ds[i - 1]]["night"])
            if nr is not None and abs(nr) > p["k"] and s["day"]:
                side = (1 if nr > 0 else -1) * (1 if fam == "N1" else -1)
                r = pnl(s["day"], side)
        elif fam in ("D1", "D2"):
            dr = ret(s["day"])
            if dr is not None and abs(dr) > p["k"] and len(s["night"]) > 30:
                side = (1 if dr > 0 else -1) * (1 if fam == "D1" else -1)
                r = pnl(s["night"], side)
        elif fam in ("L1", "L2"):
            ar = ret(s["am"])
            if ar is not None and abs(ar) > p["k"] and len(s["pm"]) > 30:
                side = (1 if ar > 0 else -1) * (1 if fam == "L1" else -1)
                r = pnl(s["pm"], side)
        elif fam == "O1":
            r = orb(s["day"], p["m"])
        elif fam == "O2":
            r = orb(s["night"], p["m"]) if len(s["night"]) > 60 else None
        elif fam == "M1":
            first = [x for x in s["day"] if tmin(x[0]) <= 9 * 60 + 45]
            last = [x for x in s["day"] if tmin(x[0]) > 16 * 60]
            fr = ret(first)
            if fr is not None and abs(fr) > p["k"] and len(last) > 20:
                r = pnl(last, 1 if fr > 0 else -1)
        if r is not None:
            out.append({"d": d, "r": r})
    return out


def stats(rs):
    v = [x["r"] for x in rs]
    if len(v) < 2:
        return {"n": len(v)}
    m, sd = statistics.mean(v), statistics.stdev(v)
    w, l_ = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
    yrs = {}
    for x in rs:
        yrs.setdefault(x["d"][:4], []).append(x["r"])
    return {"n": len(v), "avg": round(m, 2), "pf": round(w / l_, 2) if l_ else 99,
            "t": round(m / (sd / math.sqrt(len(v))), 2) if sd else 0,
            "years_pos": sum(1 for a in yrs.values() if sum(a) > 0), "years": len(yrs),
            "by_year": {y: round(sum(a), 1) for y, a in sorted(yrs.items())}}


def grid():
    for fam in ("N1", "N2", "D1", "D2"):
        for k in (0.0, 0.003):
            yield fam, {"k": k}
    for fam in ("L1", "L2"):
        for k in (0.0, 0.002):
            yield fam, {"k": k}
    for m in (15, 30):
        yield "O1", {"m": m}
    for m in (30, 60):
        yield "O2", {"m": m}
    for k in (0.0, 0.002):
        yield "M1", {"k": k}


def main():
    days = load_bars()
    S = sessions(days)
    ds = sorted(S)
    print("交易日", len(S), ds[0], "→", ds[-1])
    rows = []
    for fam, p in grid():
        tr = run(S, fam, p)
        ins = stats([x for x in tr if x["d"] <= IS_END])
        oos = stats([x for x in tr if x["d"] >= OOS_START])
        rows.append({"fam": fam, "p": p, "key": f"{fam} {json.dumps(p)}", "is": ins, "oos": oos})
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/mhi_intraday.json").upload_from_string(
        json.dumps({"days": len(S), "from": ds[0], "to": ds[-1], "rows": rows, "qualified_by_family": best}, ensure_ascii=False),
        content_type="application/json")


if __name__ == "__main__":
    main()
