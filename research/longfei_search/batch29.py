"""[IDEAS #2033] 12 個月時間序列動量雙向版（NQ、ES；使用者 11-09「好，測雙向版」）。

#2018 只測咗只做好（已真倉 MNQ／MES 各 1 張）。今批測：12 個月報酬 ≤ 0 時唔係空手，而係沽 1 張（雙向）。
  W1b：batch6 K1 月度 L＝3／6／12 雙向；K3（加 200 日線：做好要收市 > SMA200、做淡要 < SMA200）L＝6／12 雙向。
跨市場（冇參與揀選）：YM、RTY、日經、DAX、FTSE。成本、R 同之前（R＝2×ATR，月尾收市入、下月尾收市出）。

預先登記（11-09，跑之前寫，唔再改）：
  合格＝ #2004 嚴格四條（雙向全部交易計）＋ 沽空腳本身有用：
    ⑤ 沽空腳（只計做淡嗰啲月）2015→ 平均 R > 0 而且 2000–2014 平均 R > 0；
    ⑥ 雙向 2015→ t ≥ 同參數只做好版 t（唔可以差過而家真倉嗰個）。
  合格 → 先影子前向沽空腳（唔即刻改真倉），夠數再提案；唔合格 → 真倉維持只做好，喺網頁同 IDEAS 寫明。
輸出：GCS longfei/strategy_search/batch29.json。
"""
import json
import daily_search as ds
import batch13 as b13

MKTS = {"NQ": "NQ=F", "ES": "ES=F"}
CROSS = b13.CROSS_US


def run_tsm(b, ind, fam, L, both):
    c, atr, S = ind["c"], ind["atr"], ind["sma"][200]
    n = len(b)
    ends = [i for i in range(n - 1) if b[i + 1][0][:7] != b[i][0][:7]]
    out = []
    for a, e in enumerate(ends):
        if a < L or a + 1 >= len(ends) or atr[e] is None or (fam == "K3" and S[e] is None):
            continue
        past = c[e] / c[ends[a - L]] - 1
        side = 1 if past > 0 else (-1 if both else 0)
        if fam == "K3":
            side = 1 if past > 0 and c[e] > S[e] else (-1 if both and past <= 0 and c[e] < S[e] else 0)
        if not side:
            continue
        x = ends[a + 1]
        out.append({"d": b[e][0], "side": side, "r": ((c[x] - c[e]) * side - 0.0003 * c[e]) / (2 * atr[e])})
    return out


def grid():
    for L in (3, 6, 12):
        yield "K1", L
    for L in (6, 12):
        yield "K3", L


def main():
    data = {mk: ds.load(tk) for mk, tk in {**MKTS, **CROSS}.items()}
    data = {mk: b for mk, b in data.items() if len(b) > 300}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    res = {}
    for mk in MKTS:
        rows = []
        for fam, L in grid():
            tr = run_tsm(data[mk], ind[mk], fam, L, True)
            lo = run_tsm(data[mk], ind[mk], fam, L, False)
            s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
            fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
            srch = ds.stats([x for x in tr if x["d"] <= "2014-12-31"])
            sh15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01" and x["side"] < 0])
            shs = ds.stats([x for x in tr if x["d"] <= "2014-12-31" and x["side"] < 0])
            lo15 = ds.stats([x for x in lo if x["d"] >= "2015-01-01"])
            cpos = sum(1 for c in CROSS if c in data and
                       ds.stats([x for x in run_tsm(data[c], ind[c], fam, L, True) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
            q = {"c1": bool(s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0),
                 "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4), "c3": cpos >= 4,
                 "c4": bool(srch.get("avg", -9) > 0),
                 "c5": bool(sh15.get("avg", -9) > 0 and shs.get("avg", -9) > 0),
                 "c6": bool(s15.get("t", -9) >= lo15.get("t", 99))}
            rows.append({"fam": fam, "L": L, "both_2015": s15, "final": fin, "search": srch, "short_2015": sh15,
                         "short_search": shs, "long_only_2015": lo15, "cross_pos": cpos, **q, "qualified": all(q.values())})
            print(mk, fam, L, "雙向 2015→", s15, "只做好", {k: lo15.get(k) for k in ("n", "avg", "t")},
                  "沽空腳 2015→", {k: sh15.get(k) for k in ("n", "avg", "t")}, "沽空腳 2000–14", {k: shs.get(k) for k in ("n", "avg", "t")},
                  "跨", cpos, q, "✅" if all(q.values()) else "")
        res[mk] = {"rows": rows, "qualified": [f"{r['fam']} L{r['L']}" for r in rows if r["qualified"]]}
        print("==", mk, "合格", res[mk]["qualified"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch29.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
