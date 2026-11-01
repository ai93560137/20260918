"""[IDEAS #184] 組合 A（#183）影子前向（唔落單）。六個成份照 #183：D1 Keltner 突破／拋物線 SAR／威廉 %R、H4 MACD／拋物線 SAR、星期效應。
每個成份每年用前 4 年揀參數（同滾動前向一樣；2026 年用 2022–2025 揀，2027 年自動改用 2023–2026），只計 2026-11-02 00:00 UTC 之後入場嘅成交。
數據：Dukascopy＋券商 MT5 做預熱，之後用經紀 EA 心跳 M1（xau/sig/bars/）。輸出 PORTFOLIO_FORWARD.md（commit＋PR 由排程做）。
用法：python3 research/strategy_search/portfolio_forward.py"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import b_forward as BF  # noqa: E402
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402

START_TS = int(dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc).timestamp())
END_DAY = dt.date(2027, 11, 1)
COMPS = [  # 名、家族鍵、時框、時間止蝕（小時）、網格
    ("1 D1 Keltner 突破", "J5", "D1", 480, Q.FAMILIES["J5 Keltner 突破"]),
    ("2 D1 拋物線 SAR", "J7", "D1", 480, Q.FAMILIES["J7 拋物線 SAR 轉向"]),
    ("3 D1 威廉 %R", "J8", "D1", 480, Q.FAMILIES["J8 威廉 %R 極端回歸"]),
    ("4 H4 MACD", "J2", "H4", 80, Q.FAMILIES["J2 MACD 交叉"]),
    ("5 H4 拋物線 SAR", "J7", "H4", 80, Q.FAMILIES["J7 拋物線 SAR 轉向"]),
    ("6 星期效應", "S2", "W", 24, S2.FAMILIES["S2 星期效應"]),
]


def entries(D, key, th, p):
    if key == "S2":
        return [(int(D.dfirst[d]), p["dir"], 1.5 * D.datr[d - 1], None, 24) for d in range(21, len(D.dc)) if D.bwd[d] == p["w"]]
    b, x = Q.signals(D, key, p); tp, sl = Q.EXITS[p["ex"]]
    return [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], th)
            for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]


def pick(D, key, th, grid, year):
    def fn(p):
        Q.T_H = th
        return S2.s2(D, p) if key == "S2" else Q.run(D, key, p)
    _, picks = P.wf_stream(fn, grid, years=[year])
    return picks[year]


def main():
    R.COST = 0.5
    arr, n_new = BF.load_h1()
    frames = {"D1": Q.DI(*arr), "H4": H.H4I(*arr), "W": S2.D2(*arr)}
    now = dt.datetime.now(dt.timezone.utc); year = max(now.year, 2026)
    out = ["# 組合 A 影子前向（IDEAS #184）", "",
           f"- 更新：{now:%Y-%m-%d %H:%M} UTC；最後一根 H1：{dt.datetime.fromtimestamp(int(arr[0][-1]), dt.timezone.utc):%Y-%m-%d %H:%M} UTC（經紀心跳新增 {n_new} 根）",
           "- 六個成份同 #183；每年用前 4 年揀參數；只計 2026-11-02 起入場；唔落單；每張扣 0.5 美元",
           f"- 到期 {END_DAY}；回測對照（樣本外 2009→2026）：2,853 張 +0.074R PF 1.22、14/18 年正、最大回撤 −45R", "",
           "| 成份 | 今年參數 | 已平倉 | ΣR | 持倉中／待入場 |", "|---|---|---|---|---|"]
    allr, opens, rows = [], [], []
    for name, key, tf, th, grid in COMPS:
        D = frames[tf]
        g = pick(D, key, th, grid, year)
        if g is None:
            out.append(f"| {name} | 今年唔做（訓練期過唔到 PF 1.1） | 0 | +0.00 | — |"); continue
        Q.T_H = th
        ent = [e for e in entries(D, key, th, grid[g]) if int(D.t[e[0]]) >= START_TS]
        done = R.simulate(D, sorted(ent))
        done_ts = {x[0] for x in done}
        rs = [x[3] for x in done]; allr += rs
        op = [e for e in ent if int(D.t[e[0]]) not in done_ts and int(D.t[e[0]]) > (max(done_ts) if done_ts else 0)][:1]
        for e in op:
            px = D.o[e[0]]
            opens.append(f"- {name}：{'多' if e[1] > 0 else '空'} {dt.datetime.fromtimestamp(int(D.t[e[0]]), dt.timezone.utc):%m-%d %H:%M} 入 {px:.2f}，SL {px - e[1] * e[2]:.2f}" +
                         (f"，TP {px + e[1] * e[3]:.2f}" if e[3] else "") + f"，最多 {e[4]:.0f} 小時")
        for x in done:
            rows.append(f"| {dt.datetime.fromtimestamp(x[0], dt.timezone.utc):%Y-%m-%d %H:%M} | {name} | {'多' if x[1] > 0 else '空'} | "
                        f"{dt.datetime.fromtimestamp(x[4], dt.timezone.utc):%m-%d %H:%M} | {x[3]:+.2f} |")
        out.append(f"| {name} | {grid[g]} | {len(rs)} | {sum(rs):+.2f} | {len(op)} |")
    rs = np.array(allr); s = R.summ(rs)
    eq = np.cumsum(rs) if len(rs) else np.zeros(1); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if len(rs) else 0.0
    warn = (len(rs) and rs.sum() <= -15) or dd <= -20
    out += ["", "## 持倉中", "", *(opens or ["- 冇"]), "", "## 已平倉", "", "| 入場（UTC） | 成份 | 方向 | 出場 | R |", "|---|---|---|---|---|",
            *(sorted(rows) or ["| — | — | — | — | — |"]), "", "## 累計", "",
            f"- {len(rs)} 張；ΣR {rs.sum() if len(rs) else 0:+.2f}；" + (f"平均 {s['avg']:+.3f}R PF {s['pf']:.2f}；最大回撤 {dd:+.1f}R" if len(rs) else "未有平倉"),
            f"- 判：{'⚠ 觸發警示（累計 ≤ −15R 或回撤 ≤ −20R）→ 報總指揮重評' if warn else ('到期，照 IDEAS #184 判' if now.date() >= END_DAY else '未到期')}", ""]
    open(os.path.join(HERE, "PORTFOLIO_FORWARD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
