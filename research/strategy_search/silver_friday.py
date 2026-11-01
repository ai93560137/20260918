"""[IDEAS #168] 獨立市場核對：#167 喺黃金搵到「星期五（券商日，22:00 UTC 日界）開盤做多、持到下一個開盤（跨週末）、SL 1.5×D1 ATR」。
規則固定唔揀參數，喺白銀 XAGUSD Dukascopy H1 2005→2026（從未睇過）測。每張扣 0.03 美元（白銀點差級數）。
用法：python3 research/strategy_search/silver_friday.py → SILVER_FRIDAY.md"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
import robust_long as R  # noqa: E402
import robust2 as Q  # noqa: E402

RULE = dict(w=4, dir=1)


def load(prefix):
    import gb_rulesim as gb
    g = gb.Gcs(); rows = {}
    for nm in sorted(g.list(prefix)):
        for r in g.read_json(nm) or []:
            rows[int(r[0])] = r
    a = np.array([rows[k] for k in sorted(rows)], float)
    t, o, h, l, c = a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    flat = (h == l) & (np.r_[np.nan, c[:-1]] == c)
    return t[~flat], o[~flat], h[~flat], l[~flat], c[~flat]


def judge(tr):
    rs = [x[3] for x in tr]; s = R.summ(rs); yy = {}
    for x in tr:
        yy.setdefault(R.yr(x[0]), []).append(x[3])
    pos = sum(1 for v in yy.values() if np.mean(v) > 0)
    h1 = R.summ([x[3] for x in tr if R.yr(x[0]) <= 2015]); h2 = R.summ([x[3] for x in tr if R.yr(x[0]) >= 2016])
    ok = dict(n=s["n"] >= 200, avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, t=s["t"] >= 2.0, yrs=pos >= 0.6 * len(yy),
              halves=h1["avg"] > 0 and h2["avg"] > 0)
    return s, pos, len(yy), h1, h2, ok, yy


def main():
    out = ["# 獨立市場核對：星期五做多（IDEAS #168）", "", f"- 規則固定：{RULE}（星期五開盤做多、持到下一個開盤、SL 1.5×D1 ATR）", ""]
    R.COST = 0.03
    D = Q.D2(*load("xau/sig/duka_h1_xagusd/"))
    s, pos, ny, h1, h2, ok, yy = judge(Q.s2(D, RULE))
    out += ["## 白銀 XAGUSD（從未睇過）", "", f"- {R.fmt(s)}；{pos}/{ny} 年正；2005–15 {h1['avg']:+.3f}、2016–26 {h2['avg']:+.3f}",
            f"- 判：{'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)}", "",
            "| 年 | 張 | 平均 R |", "|---|---|---|"] + [f"| {y} | {len(v)} | {np.mean(v):+.3f} |" for y, v in sorted(yy.items())]
    open(os.path.join(HERE, "SILVER_FRIDAY.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[:8]))


if __name__ == "__main__":
    main()
