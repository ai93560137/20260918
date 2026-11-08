"""[IDEAS #2012] 策略搜尋第十批：MHI 隔夜 vs 日內（Cliff、Cooper、Gulen 2008「Return differences between trading and non-trading hours」；Lou、Polk、Skouras 2019「A tug of war」）。

美股大部分回報喺隔夜；亞洲指數有研究話相反。MHI 有夜市，可以收市買、翌日開市賣（或者反過來）。
  O1 隔夜做好：收市買（^HSI 收市≈MHI 日市收市）、翌日開市賣。
  O2 隔夜做好，只限收市 > SMA200。
  O3 日內做好：開市買、收市賣。
  O4 日內做淡：開市沽、收市平。
  O5 日內跟美股：前一晚 ES 收市對收市升就做好、跌就做淡（開市入收市出）。
  O6 日內逆美股：同 O5 相反。
成本來回 0.03%；R＝2×ATR(14)。

預先登記（11-09，跑之前寫，唔再改）——今批係高頻（每日一筆），用適合高頻嘅條件：
  ① MHI 2015→：n ≥ 200、t ≥ 2.5、PF ≥ 1.30；② 2021→：平均 > 0、年份 ≥ 4／6 正；
  ③ 亞洲 5 隻（^TWII、^KS11、^N225、^AXJO、000001.SS）2015→ ≥ 4 隻平均 > 0；④ 2000–2014 平均 > 0。
  （呢套高頻條件只用於今批及之後新登記嘅高頻策略；唔可以倒返轉套落之前已睇過結果嘅批次。）
  合格 → 影子前向 60 張；冇 → 第十一批另行登記。
"""
import json
import daily_search as ds
import batch3 as b3


def run10(b, ind, fam, es):
    c, atr, S = ind["c"], ind["atr"], ind["sma"][200]
    ek = sorted(es)
    out = []
    for i in range(201, len(b) - 1):
        if atr[i] is None:
            continue
        R = 2 * atr[i]
        if fam in ("O1", "O2"):
            if fam == "O2" and not (S[i] and c[i] > S[i]):
                continue
            out.append({"d": b[i][0], "r": ((b[i + 1][1] - c[i]) - 0.0003 * c[i]) / R})
        else:
            o, cl = b[i][1], c[i]
            if fam == "O3":
                side = 1
            elif fam == "O4":
                side = -1
            else:
                prev = [k for k in ek if k < b[i][0]]
                if len(prev) < 2:
                    continue
                r = es[prev[-1]] / es[prev[-2]] - 1
                side = (1 if r > 0 else -1) * (1 if fam == "O5" else -1)
            out.append({"d": b[i][0], "r": ((cl - o) * side - 0.0003 * o) / R})
    return out


def main():
    data = {mk: ds.load(tk) for mk, tk in {"MHI": "^HSI", **b3.CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    es = {x[0]: x[4] for x in ds.load("ES=F")}
    rows = []
    for fam in ("O1", "O2", "O3", "O4", "O5", "O6"):
        tr = run10(data["MHI"], ind["MHI"], fam, es)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
        cpos = sum(1 for mk in b3.CROSS if ds.stats([x for x in run10(data[mk], ind[mk], fam, es) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        q = {"c1": bool(s15.get("n", 0) >= 200 and s15.get("t", 0) >= 2.5 and s15.get("pf", 0) >= 1.30),
             "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4, "c4": bool(srch.get("avg", -9) > 0)}
        rows.append({"key": fam, "since2015": s15, "final": fin, "search": srch, "cross_pos": cpos, **q, "qualified": all(q.values())})
        print(fam, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, q, "✅" if all(q.values()) else "")
    ok = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["since2015"]["t"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch10.json").upload_from_string(
        json.dumps({"rows": rows, "pick": ok[0] if ok else None}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
