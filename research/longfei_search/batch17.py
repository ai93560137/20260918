"""[IDEAS #2019] 策略搜尋第十七批：MHI、NQ、ES（使用者 11-09「MHI、NQ、ES 每個搵到 3 個合格策略，總共 9 個先停」；而家 NQ 3、ES 2、MHI 0）。

  X1 200 日線斜率趨勢：SMA200 對比 w 日前上升（w＝20／60）而收市 > SMA200 → 翌日開市買；斜率 ≤ 0 收市出；初始止蝕 3×ATR。雙向版鏡像。
  X2 波幅突破（Larry Williams，高頻）：昨收 > SMA200 時，今日升穿「開市 + k×昨日波幅」就買（k＝0.5／0.7），同日收市平；
     雙向版：昨收 < SMA200 時跌穿「開市 − k×昨日波幅」就沽。
  X3 季節：11 月至 4 月逐月持有（月尾收市買、下月尾收市賣）；s＝"plain" 或 "sma200"（月尾收市 > SMA200 先做）。只做好。
  X4 週度反轉：上一週報酬 < −k×過去 52 週週報酬標準差（k＝1.5／2.0）→ 週尾收市買、下週尾收市賣。雙向版鏡像（> +k 做淡）。
NQ、ES 只做好；MHI 只做好＋雙向（X3 只做好）。跨市場、成本、R 同 #2015。

預先登記（11-09，跑之前寫，唔再改）：
  低頻（X1、X3、X4）＝ #2004 四條；高頻（X2）＝ #2012 條件（① 2015→ n ≥ 200、t ≥ 2.5、PF ≥ 1.30；②③④ 同上）。
  同一家族只計 t 最高一個；同已合格策略入場日重疊 ≥ 70% 唔當獨立（Donchian 20、NQ Keltner、NQ／ES 12 個月動量 #2018）。
  合格 → 影子前向，使用者批先真倉；冇 → 第十八批另行登記。
"""
import json
import math
import statistics
from datetime import date
import daily_search as ds
import batch6 as b6
import batch13 as b13

MKTS = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F"}
CROSS_US, CROSS_AS = b13.CROSS_US, b13.CROSS_AS
MAXD = 250


def run17(b, ind, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"][200]
    both = p.get("both", False)
    n = len(b)
    out = []
    if fam == "X3":
        ends = [i for i in range(n - 1) if b[i + 1][0][:7] != b[i][0][:7]]
        for a in range(len(ends) - 1):
            e, x = ends[a], ends[a + 1]
            nm = int(b[x][0][5:7])
            if nm not in (11, 12, 1, 2, 3, 4) or atr[e] is None or S[e] is None:
                continue
            if p["s"] == "sma200" and c[e] <= S[e]:
                continue
            out.append({"d": b[e][0], "r": ((c[x] - c[e]) - ds.COST * c[e]) / (2 * atr[e])})
        return out
    if fam == "X4":
        wk = lambda i: date.fromisoformat(b[i][0]).isocalendar()[:2]  # noqa: E731
        ends = [i for i in range(n - 1) if wk(i + 1) != wk(i)]
        wr = [None] + [math.log(c[ends[a]] / c[ends[a - 1]]) for a in range(1, len(ends))]
        for a in range(53, len(ends) - 1):
            e, x = ends[a], ends[a + 1]
            if atr[e] is None:
                continue
            sd = statistics.pstdev(wr[a - 52:a])
            side = 1 if wr[a] < -p["k"] * sd else (-1 if both and wr[a] > p["k"] * sd else 0)
            if side:
                out.append({"d": b[e][0], "r": ((c[x] - c[e]) * side - ds.COST * c[e]) / (2 * atr[e])})
        return out
    i = 201
    while i < n - 2:
        if atr[i] is None or S[i] is None or S[i - 60] is None:
            i += 1
            continue
        if fam == "X2":
            a0 = atr[i - 1]
            if a0 is None:
                i += 1
                continue
            o, rng = b[i][1], b[i - 1][2] - b[i - 1][3]
            if c[i - 1] > S[i - 1] and b[i][2] > o + p["k"] * rng:
                px = o + p["k"] * rng
                out.append({"d": b[i][0], "r": ((c[i] - px) - ds.COST * px) / (2 * a0)})
            elif both and c[i - 1] < S[i - 1] and b[i][3] < o - p["k"] * rng:
                px = o - p["k"] * rng
                out.append({"d": b[i][0], "r": ((px - c[i]) - ds.COST * px) / (2 * a0)})
            i += 1
            continue
        w = p["w"]
        sl = S[i] - S[i - w]
        sig = 1 if sl > 0 and c[i] > S[i] else (-1 if both and sl < 0 and c[i] < S[i] else 0)
        if not sig:
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        ef = (lambda j, s=sig, w=w: (S[j] - S[j - w]) * s <= 0)
        j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, ef, MAXD, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid(mk):
    sides = (False, True) if mk == "MHI" else (False,)
    for both in sides:
        for w in (20, 60):
            yield "X1", {"w": w, "both": both}
        for k in (0.5, 0.7):
            yield "X2", {"k": k, "both": both}
        for k in (1.5, 2.0):
            yield "X4", {"k": k, "both": both}
    for s in ("plain", "sma200"):
        yield "X3", {"s": s}


def main():
    tks = {**MKTS, **CROSS_US, **CROSS_AS}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    prior = {mk: {x["d"] for x in ds.run(data[mk], ind[mk], "F2", {"N": 20, "k": 2, "M": 20, "both": False})} for mk in MKTS}
    prior["NQ"] |= {x["d"] for x in b13.run13(data["NQ"], ind["NQ"], b13.extra(data["NQ"], ind["NQ"]), "T2", {"k": 1.5, "both": False})}
    for mk in ("NQ", "ES"):
        tsm = {x["d"] for x in b6.run6(data[mk], ind[mk], "K1", {"L": 12, "both": False})}
        prior[mk + "_tsm"] = tsm

    def run(mk, fam, p):
        return run17(data[mk], ind[mk], fam, p)

    res = {}
    for mk in MKTS:
        cross = CROSS_AS if mk == "MHI" else CROSS_US
        rows = []
        for fam, p in grid(mk):
            tr = run(mk, fam, p)
            s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
            fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
            srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
            cpos = sum(1 for c in cross if c in data and ds.stats([x for x in run(c, fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
            ov = round(sum(1 for x in tr if x["d"] in prior[mk]) / len(tr), 2) if tr else 0
            ovt = round(sum(1 for x in tr if x["d"] in prior.get(mk + "_tsm", set())) / len(tr), 2) if tr else 0
            hf = fam == "X2"
            c1 = (s15.get("n", 0) >= 200 and s15.get("t", 0) >= 2.5 and s15.get("pf", 0) >= 1.30) if hf else \
                 (s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
            q = {"c1": bool(c1), "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4,
                 "c4": bool(srch.get("avg", -9) > 0)}
            indep = ov < 0.70 and ovt < 0.70
            rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                         "cross_pos": cpos, "prior_overlap": ov, "tsm_overlap": ovt, **q, "independent": indep,
                         "qualified": all(q.values()) and indep})
            print(mk, fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, "重疊", ov, ovt, q, "✅" if rows[-1]["qualified"] else "")
        best = {}
        for r in rows:
            if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
                best[r["fam"]] = r
        res[mk] = {"rows": rows, "qualified_by_family": best}
        print("==", mk, "合格家族", list(best))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch17.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
