"""[IDEAS #2030] 策略搜尋第二十八批：只 MHI——按量度到嘅市況自動切換（#2021 寬條件；進度 NQ 3、ES 3、MHI 0）。

背景：恒指 2000–2014 偏順勢、2021 後偏均值回歸，所以單一順勢／逆勢規則過唔到 ②（2021→）同 ④（2000–14）兩頭。
#2006 用 200 日線方向切換（唔得）；今批用統計量度切換：
  Q1 方差比率切換：過去 250 日 VR(5)＝var(5 日報酬)／(5×var(1 日報酬))。
     VR > 1+δ（順勢期）→ Donchian 20 雙向：收市破 20 日高買／破低沽，止蝕 2×ATR，10 日反向通道出；
     VR < 1−δ（回歸期）→ RSI2 雙向：RSI2 < 10 買、> 90 沽，收市穿 SMA5 或 5 日出，止蝕 3×ATR；中間唔做。δ＝0／0.1
  Q2 月度自相關切換：過去 L 個月（24／36）月報酬一階自相關 > 0 → 跟上月方向；< 0 → 逆上月方向；月尾收市入、下月尾出。
跨市場：台、韓、日、澳、上證。成本、R 同之前。

預先登記（11-09，跑之前寫，唔再改）＝ #2021 MHI 寬條件；同一家族只計 t 最高一個；標明嚴／寬。
合格 → 影子前向（30 張或 6 個月），使用者批先真倉；冇 → 第二十九批另行登記。
"""
import json
import math
import statistics
import daily_search as ds
import batch13 as b13

CROSS_AS = b13.CROSS_AS


def vr(c, i, W=250, q=5):
    r1 = [math.log(c[k] / c[k - 1]) for k in range(i - W + 1, i + 1)]
    rq = [math.log(c[k] / c[k - q]) for k in range(i - W + q, i + 1)]
    v1 = statistics.pvariance(r1)
    return statistics.pvariance(rq) / (q * v1) if v1 else 1.0


def run28(b, ind, fam, p):
    c, atr, S = ind["c"], ind["atr"], ind["sma"]
    n, out = len(b), []
    if fam == "Q2":
        ends = [i for i in range(n - 1) if b[i + 1][0][:7] != b[i][0][:7]]
        mr = [None] + [math.log(c[ends[a]] / c[ends[a - 1]]) for a in range(1, len(ends))]
        L = p["L"]
        for a in range(L + 2, len(ends) - 1):
            e, x = ends[a], ends[a + 1]
            if atr[e] is None:
                continue
            w = mr[a - L + 1:a + 1]
            m = sum(w) / L
            num = sum((w[k] - m) * (w[k - 1] - m) for k in range(1, L))
            den = sum((v - m) ** 2 for v in w)
            ac = num / den if den else 0
            side = (1 if mr[a] > 0 else -1) * (1 if ac > 0 else -1)
            out.append({"d": b[e][0], "r": ((c[x] - c[e]) * side - ds.COST * c[e]) / (2 * atr[e])})
        return out
    i, d = 260, p["d"]
    while i < n - 2:
        if atr[i] is None:
            i += 1
            continue
        v = vr(c, i)
        sig, mode = 0, None
        if v > 1 + d:
            hi = max(x[2] for x in b[i - 20:i]); lo = min(x[3] for x in b[i - 20:i])
            sig = 1 if c[i] > hi else (-1 if c[i] < lo else 0)
            mode = "T"
        elif v < 1 - d and ind["rsi2"][i] is not None:
            r2 = ind["rsi2"][i]
            sig = 1 if r2 < 10 else (-1 if r2 > 90 else 0)
            mode = "M"
        if not sig:
            i += 1
            continue
        a0, px = atr[i], b[i + 1][1]
        if mode == "T":
            ef = (lambda j, s=sig: c[j] < min(x[3] for x in b[j - 10:j]) if s > 0 else c[j] > max(x[2] for x in b[j - 10:j]))
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 2 * a0, ef, 250, 2 * a0)
        else:
            ef = (lambda j, s=sig: c[j] > S[5][j] if s > 0 else c[j] < S[5][j])
            j, r = ds.trade(b, i + 1, sig, px, px - sig * 3 * a0, ef, 5, 2 * a0)
        if j is None:
            break
        out.append({"d": b[i][0], "r": r})
        i = j + 1
    return out


def grid():
    for d in (0.0, 0.1):
        yield "Q1", {"d": d}
    for L in (24, 36):
        yield "Q2", {"L": L}


def main():
    tks = {"MHI": "^HSI", **CROSS_AS}
    data = {mk: ds.load(tk) for mk, tk in tks.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    rows = []
    for fam, p in grid():
        tr = run28(data["MHI"], ind["MHI"], fam, p)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for c in CROSS_AS if c in data and ds.stats([x for x in run28(data[c], ind[c], fam, p) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        c234 = {"c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        loose = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.25 and s15.get("pf", 0) >= 1.40 and s15.get("t", 0) >= 1.8)
        strict = bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
        ok = loose and all(c234.values())
        rows.append({"fam": fam, "key": f"{fam} {json.dumps(p, sort_keys=True)}", "since2015": s15, "final": fin, "search": srch,
                     "cross_pos": cpos, "c1": loose, "c1_strict": strict, **c234, "qualified": ok,
                     "grade": ("嚴" if strict else "寬") if ok else None})
        print("MHI", fam, p, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, c234, "✅" if ok else "")
    best = {}
    for r in rows:
        if r["qualified"] and (r["fam"] not in best or r["since2015"]["t"] > best[r["fam"]]["since2015"]["t"]):
            best[r["fam"]] = r
    print("== MHI 合格家族", {k: v["grade"] for k, v in best.items()})
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch28.json").upload_from_string(
        json.dumps({"MHI": {"rows": rows, "qualified_by_family": best}}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
