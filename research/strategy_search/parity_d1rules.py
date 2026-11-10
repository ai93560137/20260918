"""[11-10] 真倉 xau/trend_d1rules.py 對回測訊號一致性（#1165 spike、#1174 wide、#1178 kelt、#1224 ichi、#1116 turtle）。
做法：同一份 Duka／MT5 M1 砌 UTC D1；回測函數（momo_strict_1164.r1165、momo_strict_1171.r1174、momo_strict_1178.r1178、strict_b_1220 一目、h1_lab8.r1116 邏輯）
攔截佢哋交畀 run_m1 嘅訊號（未計 busy）；真倉函數每日只睇最近 420 日（同 trend_live MAX_DAYS）判同一根。比較方向同 risk。
用法：python3 research/strategy_search/parity_d1rules.py → research/strategy_search/PARITY_D1RULES.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import momo_strict_1171 as M4   # noqa: E402
import momo_strict_1178 as M5   # noqa: E402
import strict_b_1220 as SB      # noqa: E402
import trend_d1rules as D1R     # noqa: E402

OUT = os.path.join(HERE, "PARITY_D1RULES.md")
WIN = 420


def captured(fn, d):
    got = []
    orig = M.run_m1
    M.run_m1 = lambda cx, sigs: got.extend((int(i), int(sg), float(r) if r is not None else None) for i, sg, r, *_ in sigs) or []
    try:
        fn(d)
    finally:
        M.run_m1 = orig
    return {i: (sg, r) for i, sg, r in got}


def turtle_sigs(b):
    c = b["c"]; a = B.atr(b, 20); out = {}
    for i in range(56, len(c) - 1):
        if np.isnan(a[i]) or a[i] <= 0:
            continue
        sg = 1 if c[i] > c[i - 55:i].max() else (-1 if c[i] < c[i - 55:i].min() else 0)
        if sg:
            out[i] = (sg, 2 * a[i])
    return out


def main():
    L = ["# 真倉 D1 規則對回測一致性", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；真倉函數每日只用最近 {WIN} 日（同服務 MAX_DAYS）", "",
         "| 數據 | 規則 | 回測訊號 | 真倉訊號 | 方向一致 | 只得回測 | 只得真倉 | risk 差中位（美元） |", "|---|---|---|---|---|---|---|---|"]
    for seg, d in (("MT5 2023–26", A.load("mt5", "2023-01-01", "2026-10-30")), ("Duka 2015–22", A.load("duka", "2015-01-01", "2022-12-31"))):
        b = B.resample(d, 86400); days = [(int(t) // 86400, {"o": float(o), "h": float(h), "l": float(l), "c": float(c)})
                                          for t, o, h, l, c in zip(b["t"], b["o"], b["h"], b["l"], b["c"])]
        bt = {"spike": captured(M3.r1165, d), "wide": captured(M4.r1174, d), "kelt": captured(M5.r1178, d),
              "ichi": captured(lambda x: SB.flips(x, SB.st_ichimoku), d), "turtle": turtle_sigs(b)}
        for rule in D1R.RULES:
            live = {}
            for i in range(60, len(days) - 1):
                sig = D1R.signal(rule, days[max(0, i - WIN + 1):i + 1])
                if sig:
                    live[i] = (sig["side"], sig.get("risk"))
            ref = {i: v for i, v in bt[rule].items() if i >= 60 + (WIN if rule in ("kelt", "ichi") else 0)}
            lv = {i: v for i, v in live.items() if i >= 60 + (WIN if rule in ("kelt", "ichi") else 0)}
            both = set(ref) & set(lv); same = sum(1 for i in both if ref[i][0] == lv[i][0])
            diffs = [abs(ref[i][1] - lv[i][1]) for i in both if ref[i][1] is not None and lv[i][1] is not None]
            L.append(f"| {seg} | {D1R.NAMES[rule]} | {len(ref)} | {len(lv)} | {same}／{len(both)} | {len(set(ref) - set(lv))} | {len(set(lv) - set(ref))} | "
                     f"{(f'{np.median(diffs):.3f}' if diffs else '—')} |")
    L += ["", "- kelt／ichi 用 EMA／一目長窗口：比較由第 480 根起（真倉 420 日窗口夠長先比）。wide 嘅 risk 用入場價計，呢度唔比。", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
