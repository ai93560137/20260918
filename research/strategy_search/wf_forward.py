"""[IDEAS #163] #162 合格策略影子前向（唔落單）。指標預熱用券商 MT5 M1 歷史（xau/sig/mt5m1/），前向用經紀 M1 心跳（xau/sig/bars/）。
參數同判斷以 IDEAS #163 為準。輸出 FORWARD_out.md（commit＋PR 由巡檢做）。
用法：python3 research/strategy_search/wf_forward.py [--start 2026-11-01T22:00]"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import search as S    # noqa: E402
import search2 as W   # noqa: E402

START = "2026-11-01T22:00"
PARAMS = {
    "G7_h1_pullback": {"TH": 35, "K": 1.5, "R": 2.0, "T": 72},
    "G1_h4_donchian": {"N": 55, "DIR": "follow", "K": 1.0, "R": 3.0, "T": 120},
    "G6_prevweek": {"DIR": "follow", "K": 1.0, "R": 3.0, "T": 120},
}
TARGET_N = 30
END = "2027-02-01"


def merged_m1(start_ts):
    hist = S.load("mt5", "2026-06-01", "2026-10-30")
    import e6s4_forward as ef   # noqa: E402
    fwd = ef.broker_bars(start_ts)
    cut = int(hist["t"][-1]) + 60
    m = fwd["t"] >= cut
    return {k: np.r_[hist[k], fwd[k][m]] for k in ("t", "o", "h", "l", "c")}, int(m.sum())


def main():
    start = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else START
    t0 = S.ts_of(start)
    m1, nf = merged_m1(t0)
    d = W.to_m5(m1)
    ctx = W.Ctx(d)
    last = int(d["t"][-1]) + W.BASE
    out = ["# IDEAS #163 影子前向（#162 合格策略，唔落單）", "",
           f"- 由 {start} UTC 到 {dt.datetime.fromtimestamp(last, dt.timezone.utc):%Y-%m-%d %H:%M}；前向經紀 M1 {nf} 根", "",
           "| 策略 | 參數 | 全部 | 做多 | 做空 | 判斷 |", "|---|---|---|---|---|---|"]
    for fam, pe in PARAMS.items():
        p = {k: pe[k] for k in W.FAMILIES[fam]}
        sig = [(i, s) for i, s in W.signals(ctx, fam, p) if d["t"][i] + W.BASE >= t0]
        mats = W.trade_mats(d, sig)
        idx = np.array([i for i, _ in sig], dtype=np.int64)
        side = np.array([s for _, s in sig])
        atr = ctx.atr_at(fam, idx) if len(sig) else np.array([])
        r, ei, xi = W.simulate(pe["K"] * atr, mats, pe["R"], pe["T"])
        keep = S.one_at_a_time(r, ei, xi) if len(r) else np.array([], bool)
        rr, sd = (r[keep], side[keep]) if len(r) else (np.array([]), np.array([]))
        sa, sl_, ss = S.stats(rr), S.stats(rr[sd > 0]) if len(rr) else S.stats(rr), S.stats(rr[sd < 0]) if len(rr) else S.stats(rr)
        due = sa["n"] >= TARGET_N or last >= S.ts_of(END)
        ok = sa["n"] > 0 and sa["avg"] >= 0.10 and sa["pf"] >= 1.2 and (fam == "G7_h1_pullback" or (ss["n"] > 0 and ss["avg"] >= 0) or ss["n"] == 0)
        verdict = ("達標" if ok else "唔達標") if due else f"未到期（{sa['n']}／{TARGET_N} 張）"
        out.append(f"| {fam} | {json.dumps(pe, ensure_ascii=False)} | {S.fmt(sa)} | {S.fmt(sl_)} | {S.fmt(ss)} | {verdict} |")
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "FORWARD_out.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
