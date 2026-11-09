"""[IDEAS #2035] MHI 日內第三批：夜市同美股開市、月尾月頭、期指結算日（數據同 #2032；使用者 11-09「MHI 要揾更好策略，一直揾，揾到先停」）。

美股開市時間 t0＝美東 09:30 換算香港時間（冬令 22:30、夏令 21:30），逐日計。
家族（成本每次來回 4 點；全部參數一次寫死）：
  U1 美股開市前一個鐘帶方向：夜市 [t0−60, t0] 報酬 > +k／< −k → t0 入場跟方向，t0+90 分鐘平。k＝0／0.2%
  U2 美股首 30 分鐘帶夜市後段：夜市 [t0, t0+30] 報酬 > +k／< −k → t0+30 入場跟方向，持到夜市收市（03:00）。k＝0／0.2%
  M2 月尾月頭日市做好：每月最後一個交易日同新月首 3 個交易日（v＝"4d"）或只新月首日（v＝"1d"），日市開入收出。只做好。
  X1／X2 期指結算日（每月倒數第二個交易日）日市：跟（X1）／逆（X2）前一日日市方向；k＝0／0.3%（前一日日市報酬門檻）。
預先登記（11-09，跑之前寫，唔再改）＝ #2032 MHI 日內條件（樣本內 2018-11→2022、樣本外 2023→；① 樣本外 n≥150、扣 4 點平均>0、t≥2.0、PF≥1.15；
  ② 樣本內同方向平均>0、t≥1.0；③ 樣本外年份 ≥3/4 正；④ 同家族另一組參數樣本外平均>0）。
  注意：M2、X1、X2 每年樣本少（M2 1d 約 12 次／年），① n≥150 可能過唔到——照登記，唔為佢改條件。
  合格 → 影子並排 AI 真倉，使用者批先換；冇 → #2036。
輸出：GCS longfei/strategy_search/mhi_intraday3.json。
"""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo
import mhi_intraday as mi

ET = ZoneInfo("America/New_York")
HKT = ZoneInfo("Asia/Hong_Kong")
COST = mi.COST


def us_open_hkt_min(d):
    dt = datetime(*map(int, d.split("-")), 9, 30, tzinfo=ET).astimezone(HKT)
    return dt.hour * 60 + dt.minute


def night_window(seg, a, b):
    """夜市 bar 喺 [a, b]（分鐘，夜市開始計 17:15 起；凌晨部分 +1440）。"""
    out = []
    for x in seg:
        m = mi.tmin(x[0])
        m = m + 1440 if m < 4 * 60 else m
        if a <= m <= b:
            out.append(x)
    return out


def ret(seg):
    return seg[-1][4] / seg[0][1] - 1 if seg else None


def run(S, fam, p):
    ds = sorted(S)
    months = {}
    for d in ds:
        months.setdefault(d[:7], []).append(d)
    out = []
    for i, d in enumerate(ds):
        s = S[d]
        r = None
        if fam in ("U1", "U2"):
            if len(s["night"]) < 200:
                continue
            t0 = us_open_hkt_min(d)
            if fam == "U1":
                pre, post = night_window(s["night"], t0 - 60, t0), night_window(s["night"], t0 + 1, t0 + 90)
            else:
                pre, post = night_window(s["night"], t0, t0 + 30), night_window(s["night"], t0 + 31, 1440 + 180)
            rr = ret(pre)
            if rr is not None and abs(rr) > p["k"] and len(post) > 10:
                side = 1 if rr > 0 else -1
                r = (post[-1][4] - post[0][1]) * side - COST
        elif fam == "M2":
            mon = months[d[:7]]
            if d[:7] in (ds[0][:7], ds[-1][:7]):          # 頭尾唔完整嘅月份唔計
                continue
            pos = mon.index(d)
            ok = (pos == 0) if p["v"] == "1d" else (pos < 3 or pos == len(mon) - 1)
            if ok and len(s["day"]) >= 100:
                r = (s["day"][-1][4] - s["day"][0][1]) - COST
        elif fam in ("X1", "X2"):
            mon = months[d[:7]]
            complete = d[:7] < ds[-1][:7]
            if complete and len(mon) >= 2 and d == mon[-2] and i > 0 and len(s["day"]) >= 100:
                pr = ret(S[ds[i - 1]]["day"])
                if pr is not None and abs(pr) > p["k"]:
                    side = (1 if pr > 0 else -1) * (1 if fam == "X1" else -1)
                    r = (s["day"][-1][4] - s["day"][0][1]) * side - COST
        if r is not None:
            out.append({"d": d, "r": r})
    return out


def grid():
    for fam in ("U1", "U2"):
        for k in (0.0, 0.002):
            yield fam, {"k": k}
    for v in ("4d", "1d"):
        yield "M2", {"v": v}
    for fam in ("X1", "X2"):
        for k in (0.0, 0.003):
            yield fam, {"k": k}


def main():
    S = mi.sessions(mi.load_bars())
    rows = []
    for fam, p in grid():
        tr = run(S, fam, p)
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
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/mhi_intraday3.json").upload_from_string(
        json.dumps({"rows": rows, "qualified_by_family": best}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
