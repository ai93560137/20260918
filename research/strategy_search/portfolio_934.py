"""[IDEAS #185] 組合 A（#183 六個成份，滾動前向樣本外）加 934 H1 回調（G7，真倉固定參數 TH35 K1.5 R2 T72；參數係用 2025–26 揀，
所以 2009–2022 對佢係未見數據）。判斷同 #183（唔計張數）；並列 A 同 A＋934 比較。用法：python3 research/strategy_search/portfolio_934.py → PORTFOLIO_934.md"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g7_long as G  # noqa: E402
import portfolio as P  # noqa: E402
import robust_long as R  # noqa: E402


def g7(arr):
    t, o, h, l, c = arr
    return [(x[0], x[1], x[2], x[3], x[5]) for x in G.backtest(t, o, h, l, c)]


def main():
    duka = R.load_duka(); mt5 = R.load_mt5_spliced(duka)
    ds, picks = P.streams(duka); ms, _ = P.streams(mt5, picks)
    core = [k for k in ds if not k.startswith("7")]
    ds["934 H1 回調"] = g7(duka); ms["934 H1 回調"] = g7(mt5)
    out = ["# 組合 A 加 934（IDEAS #185）", "", "- 934＝G7 H1 回調固定參數（TH35 K1.5 R2 T72），2009→2026；組合 A 成份同 #183（樣本外）；本金 30,000 HKD", "",
           "| 組合 | 張數 | 平均 R | PF | 合計 R | 正數年 | 兩半 | 隔夜息後 | MT5 2022-10→ | 最大回撤（R） | 30,000 每張 1% | 每張 3% | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for label, keys in (("934 單獨", ["934 H1 回調"]), ("組合 A", core), ("組合 A＋934", core + ["934 H1 回調"])):
        trs = sorted([x for k in keys for x in ds[k] if R.yr(x[0]) >= 2009]); mt = [x for k in keys for x in ms[k]]
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0); e3, m3, _, _ = P.equity(trs, 30000, 3.0)
        res[label] = (ok, yy)
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {pos}/{ny} | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {e3:,.0f}（{m3:.0%}） | {'✅' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(label, s, flush=True)
    out += ["", "## 逐年合計 R", "", "| 年 | 934 | 組合 A | A＋934 |", "|---|---|---|---|"]
    for y in range(2009, 2027):
        out.append(f"| {y} | " + " | ".join(f"{np.sum(res[k][1].get(y, [0])):+.1f}" for k in ("934 單獨", "組合 A", "組合 A＋934")) + " |")
    out += ["", "- 判斷同 #183（平均 ≥ +0.05R、PF ≥ 1.15、≥ 11/18 年正、兩半都正、隔夜息後 > 0、MT5 > 0；唔計張數）。", ""]
    open(os.path.join(HERE, "PORTFOLIO_934.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
