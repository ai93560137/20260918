"""[IDEAS #2010] 策略搜尋第八批：MHI 多週期趨勢組合＋波幅目標（AQR／Hurst、Ooi、Pedersen 2017《A Century of Evidence on Trend-Following》標準做法）。

#2008 顯示恒指時間序列動量方向一致咁正但單條唔夠強；呢度用文獻標準規格（一次寫死，唔調）：
  訊號＝1、3、6、12 個月報酬正負號嘅平均（−1 至 +1）；每月最後交易日收市調倉。
  倉位＝訊號 × (目標年化波幅 10% ÷ 過去 60 日實際年化波幅)，上限 2 倍名義。
  版本：E1 雙向；E2 只做好（訊號 < 0 就空手）。
  成本：每次調倉按名義變動 0.03%。結果用月報酬（唔用 R，因為係倉位大細變動嘅組合策略）。
同時報 NQ、ES 作參考（唔影響 #2004 判定）。跨市場：^TWII、^KS11、^N225、^AXJO、000001.SS。

預先登記（11-09，跑之前寫，唔再改）：MHI 某版本合格要全部符合：
  ① 2015-01→：年化 Sharpe ≥ 0.60，而且月報酬平均 t ≥ 2.0；
  ② 2021-01→：年化 Sharpe > 0，有交易年份 ≥ 4／6 正；
  ③ 5 隻亞洲指數 2015→ ≥ 4 隻 Sharpe > 0；
  ④ 2000–2014：Sharpe > 0；
  ⑤ 最大回撤（2015→，月度）好過 −25%。
  兩個都合格揀 ① Sharpe 高嗰個。合格 → 影子前向 6 個月（每月一次調倉，真倉要使用者批，MHI 張數按波幅計再四捨五入，上限 2 張）；
  冇 → 第九批另行登記。
"""
import json
import math
import statistics
import daily_search as ds
import batch3 as b3


def strat(b, long_only):
    c = [x[4] for x in b]
    d = [x[0] for x in b]
    ends = [i for i in range(len(b) - 1) if d[i + 1][:7] != d[i][:7]]
    rets = {}
    pos_prev = 0.0
    for a in range(12, len(ends) - 1):
        e, nx = ends[a], ends[a + 1]
        sig = sum((1 if c[e] > c[ends[a - L]] else -1) for L in (1, 3, 6, 12)) / 4
        if long_only:
            sig = max(sig, 0.0)
        r = [c[k] / c[k - 1] - 1 for k in range(max(1, e - 59), e + 1)]
        vol = statistics.pstdev(r) * math.sqrt(252) if len(r) > 20 else None
        if not vol:
            continue
        pos = max(-2.0, min(2.0, sig * 0.10 / vol))
        ret = pos * (c[nx] / c[e] - 1) - abs(pos - pos_prev) * 0.0003
        pos_prev = pos
        rets[d[nx][:7]] = ret
    return rets


def perf(rets, a, z):
    v = [r for k, r in sorted(rets.items()) if a <= k <= z]
    if len(v) < 12:
        return {"n": len(v)}
    m, sd = statistics.mean(v), statistics.pstdev(v)
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in v:
        eq *= 1 + r
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
    yrs = {}
    for k, r in rets.items():
        if a <= k <= z:
            yrs[k[:4]] = yrs.get(k[:4], 0) + r
    return {"n": len(v), "ann_ret": round(m * 12, 4), "sharpe": round(m / sd * math.sqrt(12), 2) if sd else 0,
            "t": round(m / (sd / math.sqrt(len(v))), 2) if sd else 0, "maxdd": round(dd, 3),
            "years_pos": sum(1 for x in yrs.values() if x > 0), "years": len(yrs)}


def main():
    mk_all = {"MHI": "^HSI", "NQ": "NQ=F", "ES": "ES=F", **b3.CROSS}
    data = {mk: ds.load(tk) for mk, tk in mk_all.items()}
    res = {}
    for ver, lo in (("E1", False), ("E2", True)):
        rr = {mk: strat(b, lo) for mk, b in data.items()}
        p15 = {mk: perf(rr[mk], "2015-01", "2099-12") for mk in rr}
        fin = perf(rr["MHI"], "2021-01", "2099-12")
        srch = perf(rr["MHI"], "2000-01", "2014-12")
        cpos = sum(1 for mk in b3.CROSS if p15[mk].get("sharpe", -9) > 0)
        m = p15["MHI"]
        q = {"c1": bool(m.get("sharpe", 0) >= 0.60 and m.get("t", 0) >= 2.0), "c2": bool(fin.get("sharpe", -9) > 0 and fin.get("years_pos", 0) >= 4),
             "c3": cpos >= 4, "c4": bool(srch.get("sharpe", -9) > 0), "c5": bool(m.get("maxdd", -1) > -0.25)}
        res[ver] = {"since2015": p15, "final_MHI": fin, "search_MHI": srch, "cross_pos": cpos, **q, "qualified": all(q.values())}
        print(ver, "MHI 2015→", m, "2021→", fin, "2000–14", srch, "跨", cpos, q, "✅" if all(q.values()) else "")
        print("   NQ", p15["NQ"], "ES", p15["ES"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/batch8.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
