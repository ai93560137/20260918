"""[IDEAS #186] 組合 A 單倉版（真倉 magic 935 用）：六個成份嘅樣本外成交按入場時間排，有倉就跳過新訊號（同一時間最多 1 張）；
同一刻有幾個訊號就按成份次序（1 D1 Keltner → 2 D1 SAR → 3 D1 威廉 %R → 4 H4 MACD → 5 H4 SAR → 6 星期效應）揀第一個。
判斷同 #183；並列多倉版。本金 30,000 HKD 每張 1%（上限 0.01 手＝使用者 11-01 揀）。用法：python3 research/strategy_search/portfolio_single.py → PORTFOLIO_SINGLE.md"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import portfolio as P  # noqa: E402
import robust_long as R  # noqa: E402

HKD = 7.8


def single(ds, keys):
    allt = sorted([(x[0], ki, x) for ki, k in enumerate(keys) for x in ds[k] if R.yr(x[0]) >= 2009], key=lambda z: (z[0], z[1]))
    out, busy = [], -1
    for ts, ki, x in allt:
        if ts < busy:
            continue
        out.append(x); busy = x[4]
    return out


def fixed_lot(trs, start=30000.0, lot=0.01):
    eq = peak = start; mdd = 0.0; ye = {}
    for x in trs:
        eq += x[3] * x[2] * 100 * lot * HKD; peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
        ye.setdefault(R.yr(x[0]), [None, None]); ye[R.yr(x[0])][1] = eq
    return eq, mdd


def main():
    duka = R.load_duka(); ds, picks = P.streams(duka); ms, _ = P.streams(R.load_mt5_spliced(duka), picks)
    keys = [k for k in ds if not k.startswith("7")]
    out = ["# 組合 A 單倉版（IDEAS #186）", "", "- 同一時間最多 1 張；同時出訊號按成份次序；判斷同 #183；本金 30,000 HKD", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 正數年 | 兩半 | 隔夜息後 | MT5 2022-10→ | 最大回撤 R | 每張 1% | 固定 0.01 手 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, trs, mt in (("多倉（#183）", sorted(x for k in keys for x in ds[k] if R.yr(x[0]) >= 2009), [x for k in keys for x in ms[k]]),
                           ("單倉（935）", single(ds, keys), single({k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}, keys))):
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0); ef, mf = fixed_lot(trs)
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {pos}/{ny} | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {ef:,.0f}（{mf:.0%}） | {'✅' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        if label.startswith("單倉"):
            cnt = {}
            for x in trs:
                for k in keys:
                    if x in ds[k]:
                        cnt[k] = cnt.get(k, 0) + 1; break
            out += ["", "- 單倉版各成份實際做咗：" + "、".join(f"{k} {v} 張" for k, v in cnt.items()),
                    "- 逐年合計 R：" + "、".join(f"{y} {np.sum(v):+.1f}" for y, v in sorted(yy.items()))]
        print(label, s, pos, flush=True)
    open(os.path.join(HERE, "PORTFOLIO_SINGLE.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
