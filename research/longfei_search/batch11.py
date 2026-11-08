"""[IDEAS #2013] 策略搜尋第十一批：MHI 跨資產訊號（中國資金流／匯率）。

用恒指開市前已知嘅資訊揀方向：
  X1 FXI（美國上市中國大型股 ETF）前一晚收市對收市：跟（X1f）／逆（X1r），恒指日市開市入、收市出。高頻。
  X2 上證（000001.SS）前一日收市對收市：跟（X2f）／逆（X2r），恒指開市入、收市出。高頻。
  X3 人民幣（USDCNH=X）5 日變動：人民幣升（USDCNH 跌）做好恒指、跌做淡；收市入、持有 5 日收市出。低頻。
  X4 美元指數（DX-Y.NYB）收市 < 50 日均做好恒指（收市入、持有 10 日），> 50 日均唔做。低頻。
成本來回 0.03%；R＝2×ATR(14)。跨市場（冇參與揀選）：^TWII、^KS11、^N225、^AXJO、000001.SS（X2 跨市場唔計上證本身，用其餘 4 隻，≥3 正）。

預先登記（11-09，跑之前寫，唔再改）：
  高頻（X1、X2）：① 2015→ n ≥ 200、t ≥ 2.5、PF ≥ 1.30；② 2021→ 平均 > 0、年份 ≥ 4／6 正；③ 跨市場 ≥ 4／5（X2 ≥ 3／4）正；④ 2000–2014 平均 > 0（FXI 2005 起，就用 2005–2014）。
  低頻（X3、X4）：#2004 四條（2015→ n ≥ 30、平均 ≥ +0.30R、PF ≥ 1.50、t ≥ 2.0；②③④ 同上；USDCNH 2011 起，就用 2011–2014 做 ④）。
  合格 → 影子前向；冇 → 第十二批另行登記。
"""
import json
import daily_search as ds
import batch3 as b3


def closes(tk):
    return {x[0]: x[4] for x in ds.load(tk)}


def prev_ret(ser, day, lag=1):
    ks = [k for k in ser if k < day]
    if len(ks) < lag + 1:
        return None
    return ser[ks[-1]] / ser[ks[-1 - lag]] - 1


def run11(b, ind, fam, ext):
    c, atr = ind["c"], ind["atr"]
    out = []
    ser = ext[fam[:2]]
    ks = sorted(ser)
    import bisect
    def pr(day, lag):
        j = bisect.bisect_left(ks, day)
        if j - 1 - lag < 0:
            return None
        return ser[ks[j - 1]] / ser[ks[j - 1 - lag]] - 1
    i = 60
    n = len(b)
    while i < n - 11:
        if atr[i] is None:
            i += 1
            continue
        R, day = 2 * atr[i], b[i][0]
        if fam in ("X1f", "X1r", "X2f", "X2r"):
            r = pr(day, 1)
            if r is None or r == 0:
                i += 1
                continue
            side = (1 if r > 0 else -1) * (1 if fam.endswith("f") else -1)
            out.append({"d": day, "r": ((c[i] - b[i][1]) * side - 0.0003 * b[i][1]) / R})
            i += 1
        elif fam == "X3":
            r = pr(day, 5)
            if r is None or r == 0:
                i += 1
                continue
            side = 1 if r < 0 else -1
            out.append({"d": day, "r": ((c[i + 5] - c[i]) * side - 0.0003 * c[i]) / R})
            i += 5
        else:
            j = bisect.bisect_left(ks, day)
            if j < 51:
                i += 1
                continue
            last = [ser[ks[k]] for k in range(j - 50, j)]
            if last[-1] < sum(last) / 50:
                out.append({"d": day, "r": ((c[i + 10] - c[i]) - 0.0003 * c[i]) / R})
                i += 10
            else:
                i += 1
    return out


def main():
    data = {mk: ds.load(tk) for mk, tk in {"MHI": "^HSI", **b3.CROSS}.items()}
    ind = {mk: ds.indicators(b) for mk, b in data.items()}
    ext = {"X1": closes("FXI"), "X2": closes("000001.SS"), "X3": closes("USDCNH=X"), "X4": closes("DX-Y.NYB")}
    start_s = {"X1": "2005-01-01", "X2": "2000-01-01", "X3": "2011-01-01", "X4": "2000-01-01"}
    rows = []
    for fam in ("X1f", "X1r", "X2f", "X2r", "X3", "X4"):
        tr = run11(data["MHI"], ind["MHI"], fam, ext)
        s15 = ds.stats([x for x in tr if x["d"] >= "2015-01-01"])
        fin = ds.stats([x for x in tr if x["d"] >= "2021-01-01"])
        srch = ds.stats([x for x in tr if start_s[fam[:2]] <= x["d"] <= "2014-12-31"])
        cmk = [mk for mk in b3.CROSS if not (fam.startswith("X2") and mk == "SSE")]
        cpos = sum(1 for mk in cmk if ds.stats([x for x in run11(data[mk], ind[mk], fam, ext) if x["d"] >= "2015-01-01"]).get("avg", -1) > 0)
        hf = fam[:2] in ("X1", "X2")
        c1 = (s15.get("n", 0) >= 200 and s15.get("t", 0) >= 2.5 and s15.get("pf", 0) >= 1.30) if hf else \
             (s15.get("n", 0) >= 30 and s15.get("avg", -9) >= 0.30 and s15.get("pf", 0) >= 1.5 and s15.get("t", 0) >= 2.0)
        q = {"c1": bool(c1), "c2": bool(fin.get("avg", -9) > 0 and fin.get("years_pos", 0) >= 4),
             "c3": cpos >= (3 if fam.startswith("X2") else 4), "c4": bool(srch.get("avg", -9) > 0)}
        rows.append({"key": fam, "since2015": s15, "final": fin, "search": srch, "cross_pos": cpos, **q, "qualified": all(q.values())})
        print(fam, "2015→", s15, "最終", fin, "搜尋", srch.get("avg"), "跨", cpos, q, "✅" if all(q.values()) else "")
    ok = sorted([r for r in rows if r["qualified"]], key=lambda r: -r["since2015"]["t"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch11.json").upload_from_string(
        json.dumps({"rows": rows, "pick": ok[0] if ok else None}, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
