"""[IDEAS #190] 935 改良版（#189 出場交滾動揀）影子前向（唔落單），同 935 現行版（固定出場）並列。
兩個都係單倉（同時 1 張，同時出訊號按成份次序 1→6）；每個成份每年用前 4 年揀（改良版：參數 × 出場模式 fix／be／tr2／tr3／opp；現行版：參數）；
星期效應兩邊一樣。只計 2026-11-02 00:00 UTC 之後入場。數據：Dukascopy＋券商 MT5 預熱，之後用經紀 EA 心跳 M1（xau/sig/bars/）。
輸出 EXITS_FORWARD.md（commit＋PR 由排程做）。到期 2027-11-01：改良版 ΣR 同最大回撤都要好過現行版先建議換。
用法：python3 research/strategy_search/exits_forward.py"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import b_forward as BF  # noqa: E402
import d1_indicators as Q  # noqa: E402
import exits_a as X  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402

START_TS = int(dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc).timestamp())
END_DAY = dt.date(2027, 11, 1)


def comp_entries(D, fam, p, th):
    b, x = Q.signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]; m = p.get("xm", "fix")
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d] if m in ("fix", "be") else None, th, D.datr[d])
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0 and int(D.t[D.dfirst[d + 1]]) >= START_TS]
    eL = eS = None
    if m == "opp":
        eL = np.zeros(len(D.t), bool); eL[D.dlast[np.flatnonzero(x)]] = True
        eS = np.zeros(len(D.t), bool); eS[D.dlast[np.flatnonzero(b)]] = True
    return ent, m, eL, eS


def book(frames, year, improved):
    """回傳 (各成份 [(名, 揀法, 已平倉 trades, 未完 entries)]) 。"""
    rows = []
    for name, fam, tf, th in X.COMPS:
        D = frames[tf]; base = Q.FAMILIES[fam]
        grid = [dict(p, xm=m) for p in base for m in X.MODES] if improved else [dict(p, xm="fix") for p in base]
        T = [X.run(D, fam, p, th) for p in grid]
        _, pk = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid, years=[year])
        g = pk[year]
        if g is None:
            rows.append((name, "今年唔做", [], [])); continue
        ent, m, eL, eS = comp_entries(D, fam, grid[g], th)
        done = X.sim2(D, ent, m, eL, eS); dts = {x[0] for x in done}
        last = max([x[4] for x in done], default=0)
        pend = [e for e in ent if int(D.t[e[0]]) not in dts and int(D.t[e[0]]) >= last][:1]
        rows.append((name, grid[g], done, [(int(D.t[e[0]]), e[1], float(D.o[e[0]]), e[2], e[3], e[4]) for e in pend]))
    DW = frames["W"]; g6 = S2.FAMILIES["S2 星期效應"]
    _, pk = P.wf_stream(lambda p: S2.s2(DW, p), g6, years=[year]); g = pk[year]
    if g is None:
        rows.append(("6 星期效應", "今年唔做", [], []))
    else:
        p = g6[g]
        ent = [(int(DW.dfirst[d]), p["dir"], 1.5 * DW.datr[d - 1], None, 24) for d in range(21, len(DW.dc))
               if DW.bwd[d] == p["w"] and int(DW.t[DW.dfirst[d]]) >= START_TS]
        done = R.simulate(DW, ent); dts = {x[0] for x in done}; last = max([x[4] for x in done], default=0)
        pend = [e for e in ent if int(DW.t[e[0]]) not in dts and int(DW.t[e[0]]) >= last][:1]
        rows.append(("6 星期效應", p, done, [(int(DW.t[e[0]]), e[1], float(DW.o[e[0]]), e[2], None, 24) for e in pend]))
    return rows


def single(rows):
    allt = sorted([(x[0], ki, x, rows[ki][0]) for ki, r in enumerate(rows) for x in r[2]], key=lambda z: (z[0], z[1]))
    out, busy = [], -1
    for ts, ki, x, nm in allt:
        if ts < busy:
            continue
        out.append((nm, x)); busy = x[4]
    pend = sorted([(e[0], ki, e, rows[ki][0]) for ki, r in enumerate(rows) for e in r[3] if e[0] >= busy], key=lambda z: (z[0], z[1]))[:1]
    return out, pend


def stats(tr):
    rs = np.array([x[3] for _, x in tr]); s = R.summ(rs)
    eq = np.cumsum(rs) if len(rs) else np.zeros(1)
    dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if len(rs) else 0.0
    st = mx = 0
    for r in rs:
        st = st + 1 if r < 0 else 0; mx = max(mx, st)
    return s, dd, mx


def main():
    R.COST = 0.5
    arr, n_new = BF.load_h1()
    frames = {"D1": Q.DI(*arr), "H4": H.H4I(*arr), "W": S2.D2(*arr)}
    now = dt.datetime.now(dt.timezone.utc); year = max(now.year, 2026)
    out = ["# 935 改良版（出場交滾動揀）影子前向（IDEAS #190）", "",
           f"- 更新：{now:%Y-%m-%d %H:%M} UTC；最後一根 H1：{dt.datetime.fromtimestamp(int(arr[0][-1]), dt.timezone.utc):%Y-%m-%d %H:%M} UTC（經紀心跳新增 {n_new} 根）",
           "- 兩個都係單倉、2026-11-02 起入場、唔落單、每張扣 0.5 美元；現行版＝935 真倉嘅影子對照",
           f"- 到期 {END_DAY}；回測對照（2009→2026 單倉）：現行 989 張 +0.083R PF 1.24 回撤 −26.6R；改良 911 張 +0.111R PF 1.33 回撤 −17.8R", ""]
    res = {}
    for label, imp in (("改良版", True), ("現行版", False)):
        rows = book(frames, year, imp); tr, pend = single(rows); s, dd, mx = stats(tr); res[label] = (s, dd)
        out += [f"## {label}", "", "| 成份 | 今年揀法 |", "|---|---|", *[f"| {r[0]} | {r[1]} |" for r in rows], ""]
        out += ["持倉中／待入場：" + ("冇" if not pend else "；".join(
            f"{nm} {'多' if e[1] > 0 else '空'} {dt.datetime.fromtimestamp(e[0], dt.timezone.utc):%m-%d %H:%M} 入 {e[2]:.2f} SL {e[2] - e[1] * e[3]:.2f}"
            + (f" TP {e[2] + e[1] * e[4]:.2f}" if e[4] else "") + f" 最多 {e[5]:.0f}h" for _, _, e, nm in pend)), ""]
        out += ["| 入場（UTC） | 成份 | 方向 | 出場 | R |", "|---|---|---|---|---|"]
        out += [f"| {dt.datetime.fromtimestamp(x[0], dt.timezone.utc):%Y-%m-%d %H:%M} | {nm} | {'多' if x[1] > 0 else '空'} | "
                f"{dt.datetime.fromtimestamp(x[4], dt.timezone.utc):%m-%d %H:%M} | {x[3]:+.2f} |" for nm, x in tr] or ["| — | — | — | — | — |"]
        out += ["", f"- {s['n']} 張；ΣR {s['sum']:+.2f}；" + (f"平均 {s['avg']:+.3f}R PF {s['pf']:.2f}；最大回撤 {dd:+.1f}R；最長連輸 {mx}" if s["n"] else "未有平倉"), ""]
    (si, di), (sc, dc) = res["改良版"], res["現行版"]
    warn = si["n"] and (si["sum"] <= -12 or di <= -15)
    out += ["## 判", "",
            f"- 改良 − 現行：ΣR {si['sum'] - sc['sum']:+.2f}、回撤 {di - dc:+.1f}R",
            f"- {'⚠ 改良版觸發警示（累計 ≤ −12R 或回撤 ≤ −15R）→ 報總指揮' if warn else ('到期，照 IDEAS #190 判' if now.date() >= END_DAY else '未到期')}", ""]
    open(os.path.join(HERE, "EXITS_FORWARD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
