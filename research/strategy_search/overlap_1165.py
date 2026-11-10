"""[11-10 描述性分析，唔係新策略] 急動順勢合格 3 條（#1165／#1174／#1178）同趨勢家族嚴格版合格 5 條（#1105／#1107／#1113／#1114／#1116）重疊幾多。
做法（同一份數據：Duka 2015–2022 M1、MT5 2023-01→2026-10 M1；趨勢規則用由 M1 合成嘅 H1）：
① 時間重疊：每張急動順勢單入場嗰日，有冇趨勢規則喺「最長持倉窗口」內入過場（同方向／反方向）。窗口用各規則最長持倉（上限估計，因為止蝕可能早走）：
   #1105 20 日、#1107 到季尾、#1113 14 曆日、#1114 到月尾、#1116 170 曆日（120 根 D1）。
② 每月 R 相關：每條規則每月 R 合計，計急動順勢對趨勢 5 條合計嘅相關系數。
用法：python3 research/strategy_search/overlap_1165.py → research/strategy_search/OVERLAP_1165.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import h1_lab5 as L5            # noqa: E402
import h1_lab6 as H6            # noqa: E402
import h1_lab7 as H7            # noqa: E402
import h1_lab8 as H8            # noqa: E402
import momo_strict_1164 as MS3  # noqa: E402
import momo_strict_1171 as MS4  # noqa: E402
import momo_strict_1178 as MS5  # noqa: E402

OUT = os.path.join(HERE, "OVERLAP_1165.md")
D = 86400


def q_end(ts):
    x = dt.datetime.fromtimestamp(ts, dt.timezone.utc); qm = (x.month - 1) // 3 * 3 + 3
    y, m = (x.year + 1, 1) if qm == 12 else (x.year, qm + 1)
    return dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp()


def m_end(ts):
    x = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    y, m = (x.year + 1, 1) if x.month == 12 else (x.year, x.month + 1)
    return dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp()


TREND = [("#1105", L5.r1105, lambda ts: ts + 28 * D), ("#1107", H6.r1107, q_end), ("#1113", H7.r1113, lambda ts: ts + 14 * D),
         ("#1114", H8.r1114, m_end), ("#1116", H8.r1116, lambda ts: ts + 170 * D)]
MOMO = [("#1165", MS3.r1165), ("#1174", MS4.r1174), ("#1178", MS5.r1178)]


def monthly(tr):
    out = {}
    for ts, _, r in tr:
        x = dt.datetime.fromtimestamp(ts, dt.timezone.utc); out[(x.year, x.month)] = out.get((x.year, x.month), 0.0) + r
    return out


def main():
    segs = [("Duka 2015–22", A.load("duka", "2015-01-01", "2022-12-31")), ("MT5 2023–26", A.load("mt5", "2023-01-01", "2026-10-30"))]
    L = ["# 急動順勢 3 條 vs 趨勢家族 5 條：重疊分析", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；描述性分析（唔係新策略、冇判決）；窗口用最長持倉，所以重疊係上限估計", ""]
    for name, d in segs:
        g = B.resample(d, 3600)
        tr_trades = {k: [(int(ts), int(sg), float(r), int(end(ts))) for ts, sg, r in fn(g)] for k, fn, end in TREND}
        mo_trades = {k: [(int(ts), int(sg), float(r)) for ts, sg, r in fn(d)] for k, fn in MOMO}
        L += [f"## {name}", "", "| 急動順勢 | 張數 | " + " | ".join(f"同向 {k}" for k, _, _ in TREND) + " | 同向任何一條 | 反向任何一條 |",
              "|---|---|" + "---|" * (len(TREND) + 2)]
        for mk, mt in mo_trades.items():
            cells = []; any_same = any_opp = 0
            hit = {k: 0 for k, _, _ in TREND}
            for ts, sg, _ in mt:
                s_any = o_any = False
                for k, tt in tr_trades.items():
                    live = [x for x in tt if x[0] <= ts < x[3]]
                    if any(x[1] == sg for x in live):
                        hit[k] += 1; s_any = True
                    if any(x[1] == -sg for x in live):
                        o_any = True
                any_same += s_any; any_opp += o_any
            n = len(mt)
            cells = [f"{hit[k] / n:.0%}" if n else "—" for k, _, _ in TREND]
            L.append(f"| {mk} | {n} | " + " | ".join(cells) + f" | {any_same / n:.0%} | {any_opp / n:.0%} |" if n else f"| {mk} | 0 |")
        tm = {}
        for k, tt in tr_trades.items():
            for key, v in monthly([(a, b, c) for a, b, c, _ in tt]).items():
                tm[key] = tm.get(key, 0.0) + v
        L += ["", "| 急動順勢 | 每月 R 對趨勢 5 條合計嘅相關系數 | 有交易月份 |", "|---|---|---|"]
        for mk, mt in mo_trades.items():
            mm = monthly(mt); ks = sorted(set(mm) | set(tm))
            x = np.array([mm.get(k, 0.0) for k in ks]); y = np.array([tm.get(k, 0.0) for k in ks])
            cor = float(np.corrcoef(x, y)[0, 1]) if len(ks) > 2 and x.std() > 0 and y.std() > 0 else float("nan")
            L.append(f"| {mk} | {cor:+.2f} | {len(mm)} |")
        L.append("")
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
