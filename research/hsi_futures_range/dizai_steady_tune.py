"""地載・穩：調「過去 N 個交易日已同方向走 ≥ x% 就不逆市」的 N 與 x。

地載・穩：RSI(14) 轉向逆市、當日升跌 ≥ 2%、全日、間距 0.75 × ATR20、1→2→4、止賺 30、止蝕 1000、留倉。
過去 N 日升跌 = 上日收市 ÷ N 日前收市 − 1（入場前已知）；沽時已升 ≥ x%、買時已跌 ≥ x% 就不做。
最大回撤 = 連持倉浮動盈虧，逐分鐘用盤中最差價計（4 張大期時每點 × 4）。金額以每張大期每點 HK$50 計。

用法：python3 research/hsi_futures_range/dizai_steady_tune.py --json /tmp/hsimain.json
"""
import argparse, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

STEADY = {"trig": "confirm", "move": 0.02, "g": 0.75, "tp": 30, "sl": 1000}
NS = (2, 3, 4, 5, 7, 10)
XS = (0.01, 0.015, 0.02, 0.025, 0.03, 0.04)


def float_drawdown(D, trades):
    """連浮虧的最大回撤（點，盤中最差價）與日期。"""
    h, l, tk = D["h"], D["l"], D["tk"]
    realized, peak, worst, when = 0.0, 0.0, 0.0, None
    for x in trades:
        f, side = x["fills"], x["side"]
        e, end = f[0][0], f[-1][0]
        lots, avg, paid, idx = 0, 0.0, 0.0, 0
        for b in range(e, end + 1):
            while idx < len(f) and f[idx][0] == b and f[idx][1] in ("open", "add"):
                q = f[idx][3] - lots
                avg = (avg * lots + f[idx][2] * q) / f[idx][3]
                lots, paid, idx = f[idx][3], paid + q, idx + 1
            eq = realized + lots * side * ((h[b] if side < 0 else l[b]) - avg) - paid
            if eq - peak < worst:
                worst, when = eq - peak, tk[b][:10]
        realized += x["pnl"]
        peak = max(peak, realized)
    return worst, when


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days, ends = D["days"], D["ends"]
    dc = D["c"][ends - 1]
    sig = ds.signals(D, "fade", STEADY["trig"], STEADY["move"], "all")
    rows = []
    for n, x in [(None, None)] + list(itertools.product(NS, XS)):
        if n is None:
            s2 = sig
        else:
            s2 = []
            for i, side in sig:
                k = D["sid"][i]
                r = dc[k - 1] / dc[k - 1 - n] - 1 if k - 1 - n >= 0 else 0.0
                if not ((side < 0 and r >= x) or (side > 0 and r <= -x)):
                    s2.append((i, side))
        t = mg.simulate_mg(D, s2, STEADY["g"], STEADY["tp"], sl_pts=STEADY["sl"])
        closed = [z for z in t if z["reason"] != "open"]
        s, tr, te = mg.summary(closed, days), mg.summary(closed, days, hi=ds.TRAIN_END), mg.summary(closed, days, lo="2024-01-01")
        mae = max(z["mae"] for z in closed if z["reason"] != "sl")
        dd, when = float_drawdown(D, closed)
        rows.append((n, x, s["n"], s["win"], s["total"], dd, when, mae, s["reasons"].get("sl", 0), tr["exp"], te.get("exp", 0)))
    print("地載・穩：過去 N 日同向 ≥ x% 不做（金額：每張大期每點 HK$50）\n")
    print(" N   x    筆數  勝率   八年點  HK$萬  最大回撤(點)  HK$萬  日期        最遠逆向 離止蝕 止蝕 每筆(訓|測)")
    for n, x, cnt, win, tot, dd, when, mae, nsl, etr, ete in rows:
        lab = "無條件 " if n is None else f"{n:2d} {x:4.1%}"
        print(f"{lab} {cnt:4d} {win:6.1%} {tot:+7.0f} {tot * 50 / 1e4:+6.1f} {dd:9.0f}   {dd * 50 / 1e4:6.1f}  {when}  {mae:5.0f}  {STEADY['sl'] - mae:5.0f} {nsl:3d}  {etr:+.1f}|{ete:+.1f}")


if __name__ == "__main__":
    main()
