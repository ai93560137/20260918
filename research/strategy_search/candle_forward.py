"""[IDEAS #208] 935＋D1 內包線突破（#207）影子前向（唔落單），同 935 現行版（影子）並列。
單倉（同時 1 張，成份次序 1→6，內包線突破排第 7）；每個成份每年用前 4 年揀；只計 2026-11-02 00:00 UTC 之後入場。
數據同 #184／#190（Dukascopy＋券商 MT5 預熱，之後經紀 EA 心跳 M1）。輸出 CANDLE_FORWARD.md。
到期 2027-11-01：935＋內包線 ΣR 同最大回撤都好過現行版先建議加（真倉要改程式，使用者經總指揮批）；警示：累計 ≤ −12R 或回撤 ≤ −15R。
用法：python3 research/strategy_search/candle_forward.py"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import b_forward as BF  # noqa: E402
import candle_ind as CI  # noqa: E402
import d1_indicators as Q  # noqa: E402
import exits_forward as EF  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402

START_TS = EF.START_TS
END_DAY = dt.date(2027, 11, 1)
FAM = "C3 內包線突破"


def candle_row(D, year):
    grid = CI.FAMILIES[FAM]; Q.T_H = 480
    T = [CI.run(D, FAM, p, 480) for p in grid]
    _, pk = P.wf_stream(lambda p: T[grid.index(p)], grid, years=[year]); g = pk[year]
    name = "7 D1 內包線突破"
    if g is None:
        return (name, "今年唔做", [], [])
    p = grid[g]; b, x = CI.signals(D, FAM, p); tp, sl = Q.EXITS[p["ex"]]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], 480)
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0 and int(D.t[D.dfirst[d + 1]]) >= START_TS]
    done = R.simulate(D, ent); dts = {z[0] for z in done}; last = max([z[4] for z in done], default=0)
    pend = [e for e in ent if int(D.t[e[0]]) not in dts and int(D.t[e[0]]) >= last][:1]
    return (name, p, done, [(int(D.t[e[0]]), e[1], float(D.o[e[0]]), e[2], e[3], e[4]) for e in pend])


def main():
    R.COST = 0.5
    arr, n_new = BF.load_h1()
    frames = {"D1": Q.DI(*arr), "H4": H.H4I(*arr), "W": S2.D2(*arr)}
    now = dt.datetime.now(dt.timezone.utc); year = max(now.year, 2026)
    out = ["# 935＋D1 內包線突破 影子前向（IDEAS #208）", "",
           f"- 更新：{now:%Y-%m-%d %H:%M} UTC；最後一根 H1：{dt.datetime.fromtimestamp(int(arr[0][-1]), dt.timezone.utc):%Y-%m-%d %H:%M} UTC（經紀心跳新增 {n_new} 根）",
           "- 單倉、2026-11-02 起入場、唔落單、每張扣 0.5 美元；現行版＝935 真倉嘅影子對照",
           f"- 到期 {END_DAY}；回測對照（2009→2026 單倉）：935 989 張 +0.083R PF 1.24 回撤 −26.6R；935＋內包線 981 張 +0.101R PF 1.30 回撤 −25.7R", ""]
    base = EF.book(frames, year, False)
    res = {}
    for label, rows in (("935＋內包線突破", base + [candle_row(frames["D1"], year)]), ("935 現行", base)):
        tr, pend = EF.single(rows); s, dd, mx = EF.stats(tr); res[label] = (s, dd)
        out += [f"## {label}", "", "| 成份 | 今年揀法 |", "|---|---|", *[f"| {r[0]} | {r[1]} |" for r in rows], ""]
        out += ["持倉中／待入場：" + ("冇" if not pend else "；".join(
            f"{nm} {'多' if e[1] > 0 else '空'} {dt.datetime.fromtimestamp(e[0], dt.timezone.utc):%m-%d %H:%M} 入 {e[2]:.2f} SL {e[2] - e[1] * e[3]:.2f}"
            + (f" TP {e[2] + e[1] * e[4]:.2f}" if e[4] else "") + f" 最多 {e[5]:.0f}h" for _, _, e, nm in pend)), ""]
        out += ["| 入場（UTC） | 成份 | 方向 | 出場 | R |", "|---|---|---|---|---|"]
        out += [f"| {dt.datetime.fromtimestamp(x[0], dt.timezone.utc):%Y-%m-%d %H:%M} | {nm} | {'多' if x[1] > 0 else '空'} | "
                f"{dt.datetime.fromtimestamp(x[4], dt.timezone.utc):%m-%d %H:%M} | {x[3]:+.2f} |" for nm, x in tr] or ["| — | — | — | — | — |"]
        out += ["", f"- {s['n']} 張；ΣR {s['sum']:+.2f}；" + (f"平均 {s['avg']:+.3f}R PF {s['pf']:.2f}；最大回撤 {dd:+.1f}R；最長連輸 {mx}" if s["n"] else "未有平倉"), ""]
    (si, di), (sc, dc) = res["935＋內包線突破"], res["935 現行"]
    warn = si["n"] and (si["sum"] <= -12 or di <= -15)
    out += ["## 判", "", f"- 935＋內包線 − 現行：ΣR {si['sum'] - sc['sum']:+.2f}、回撤 {di - dc:+.1f}R",
            f"- {'⚠ 935＋內包線觸發警示（累計 ≤ −12R 或回撤 ≤ −15R）→ 報總指揮' if warn else ('到期，照 IDEAS #208 判' if now.date() >= END_DAY else '未到期')}", ""]
    open(os.path.join(HERE, "CANDLE_FORWARD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
