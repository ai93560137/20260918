"""[IDEAS #200] 935 同時最多 2 張（現行 1 張）：六個成份樣本外成交（同 #186）按入場時間排，手上 < 2 張先做新訊號；
同一刻有幾個按成份次序；同一成份唔會同時兩張（成份本身已經一次一張）。另列 3 張（＝#183 多倉上限內）做描述。
判「2 張版可以取代 935」：合計 R > 935（+82.1R）、平均 ≥ +0.07R、PF ≥ 1.20、最近 10 年 ≥ 7/10、最大回撤唔差過 −40R（風險最多兩倍，放寬 1.5 倍）、
MT5 > 0、過 #183 六條；另計本金 30,000 每張 1%（同時有倉疊加）。…69 戶口合共 3 張上限要另計（931／933／934 都佔位），合格都只係提案。
用法：python3 research/strategy_search/multi2_935.py → MULTI2_935.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402


def multi(ds, keys, k):
    allt = sorted([(x[0], ki, x) for ki, kk in enumerate(keys) for x in ds[kk] if R.yr(x[0]) >= 2009], key=lambda z: (z[0], z[1]))
    out, open_ = [], []
    for ts, ki, x in allt:
        open_ = [e for e in open_ if e > ts]
        if len(open_) >= k:
            continue
        out.append(x); open_.append(x[4])
    return out


def months(trs):
    mm = {}
    for x in trs:
        t = dt.datetime.fromtimestamp(x[4], dt.timezone.utc)
        if 2017 <= t.year <= 2026:
            mm[(t.year, t.month)] = mm.get((t.year, t.month), 0) + x[3]
    return sum(v > 0 for v in mm.values()), len(mm)


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA); keys = [k for k in ds if not k.startswith("7")]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    out = ["# 935 同時最多 2 張（IDEAS #200）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Dukascopy 2009→2026 樣本外", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 18 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 近 10 年正數月 | 判 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, k in (("935 現行（1 張）", 1), ("主判：2 張", 2), ("描述：3 張", 3)):
        trs = multi(ds, keys, k); mt = multi(msA, keys, k)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt); p10, _ = XL.pos10(trs)
        eq = np.cumsum([x[3] for x in sorted(trs, key=lambda z: z[4])]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, mo, _ = P.equity(trs, 30000, 1.0); pm, nm = months(trs)
        good = s["sum"] > 82.1 and s["avg"] >= 0.07 and s["pf"] >= 1.20 and p10 >= 7 and dd >= -40 and m["n"] > 0 and m["avg"] > 0 and all(ok.values())
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pos}/{ny} | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {pm}/{nm} | {('✅' if good else '❌') if label.startswith('主判') else '—'} |")
        print(label, s, p10, dd, flush=True)
    out += ["", "- 回撤按平倉時間排序計；…69 戶口 931＋933＋934＋935 合共 3 張上限，935 用 2 張會令其他書少位。", ""]
    open(os.path.join(HERE, "MULTI2_935.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
