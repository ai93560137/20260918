"""地載陣再試三個方向（八年主連 1 分 K；Sharpe = 每日收市權益含浮動 × √252；訓練 2018-10 至 2023-12、測試 2024 起）：

A. RSI 時間框：RSI(14) 用 1／5／15／60 分 K 計（5／15 分：每 5／15 分鐘最後一根 1 分 K；60 分：每小時 xx:59），
   在該時間框收市判斷穿越／轉向，下一根 1 分 K 開市入場；其他規則同穩／進（升跌 ≥ 2%、加倉、止賺止蝕、留倉）。
B. 每月加滿倉上限：一個月內已有 cap 組加滿 4 張，該月不再開新倉。
C. 加滿倉後時間止蝕：加滿 4 張後持有 N 個交易日仍未止賺，該交易日收市全部平倉。

用法：python3 research/hsi_futures_range/dizai_more.py --json /tmp/hsimain.json
"""
import argparse, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_filters as fl                                  # noqa: E402
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import dizai_vhsi as dv                                     # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

VARIANTS = {"穩": ("confirm", 0.75, 30, 1000, None), "進": ("cross", 1.0, 150, 3000, "run5_3")}
HKD = 50


def tf_signals(D, trig, tf, move=0.02):
    """RSI(14) 用 tf 分 K（1 = 原本）。回傳 [(i, side)]，跟 ds.signals 同一套開閘與同一交易日規則。"""
    if tf == 1:
        return ds.signals(D, "fade", trig, move, "all")
    mins = np.array([int(t[14:16]) for t in D["tk"]])
    idx = np.flatnonzero(mins % tf == tf - 1) if tf < 60 else np.flatnonzero(mins == 59)
    r = np.array([np.nan if v is None else v for v in rad.rsi_series(list(D["c"][idx]), 14)])
    rp = np.r_[np.nan, r[:-1]]
    if trig == "cross":
        hi_x, lo_x = (rp <= 80) & (r > 80), (rp >= 20) & (r < 20)
    else:
        hi_x, lo_x = (rp >= 80) & (r < 80), (rp <= 20) & (r > 20)
    chg = D["c"][idx] / D["prev_close"][idx] - 1
    sid = D["sid"]
    same = np.r_[False, sid[idx][1:] == sid[idx][:-1]]       # 上一個 tf 收市同一交易日
    ok = same & ~np.isnan(D["atr"][idx])
    out = [(int(idx[k]), -1) for k in np.flatnonzero(hi_x & (chg >= move) & ok)]
    out += [(int(idx[k]), 1) for k in np.flatnonzero(lo_x & (chg <= -move) & ok)]
    return sorted(out)


def run_seq(D, sigs, g, tp, sl, month_cap=None, time_stop=None):
    """逐個訊號模擬（可加每月加滿倉上限、加滿倉後時間止蝕）。回傳已平倉交易（含 fills）。"""
    days, sid, c, ends = D["days"], D["sid"], D["c"], D["ends"]
    trades, busy, opened, full_by_month = [], -1, set(), {}
    for i, side in sigs:
        if i + 1 <= busy or sid[i] in opened or i + 1 >= len(c) or sid[i + 1] != sid[i]:
            continue
        month = days[sid[i]][:7]
        if month_cap is not None and full_by_month.get(month, 0) >= month_cap:
            continue
        t = mg.simulate_mg(D, [(i, side)], g, tp, sl_pts=sl)
        if not t or t[0]["reason"] == "open":
            break
        x = t[0]
        opened.add(sid[i])
        full = next((fj for fj, k, px, lt in x["fills"] if k == "add" and lt == 4), None)
        if time_stop is not None and full is not None:
            cut_sid = sid[full] + time_stop
            end = x["fills"][-1][0]
            if cut_sid < len(days) and sid[end] > cut_sid:      # 到期限仍未平倉 → 該交易日收市全平
                cut = ends[cut_sid] - 1
                fills = [f for f in x["fills"] if f[0] <= cut and f[1] in ("open", "add")]
                lots, avg, paid = 0, 0.0, 0.0
                for fj, k, px, lt in fills:
                    q = lt - lots
                    avg, lots, paid = (avg * lots + px * q) / lt, lt, paid + q
                pnl = lots * side * (c[cut] - avg) - paid - lots
                x = {**x, "fills": fills + [(int(cut), "time", float(c[cut]), 0)], "pnl": float(pnl), "reason": "time"}
        if full is not None and full <= x["fills"][-1][0]:
            full_by_month[days[sid[full]][:7]] = full_by_month.get(days[sid[full]][:7], 0) + 1
        trades.append(x)
        busy = x["fills"][-1][0]
    return trades


def report(D, label, t):
    days = D["days"]
    daily = dv.daily_equity(D, t, [1.0] * len(t)) * HKD
    al, tr, te = dv.metrics(daily, days), dv.metrics(daily, days, hi=ds.TRAIN_END), dv.metrics(daily, days, lo="2024-01-01")
    reasons = {}
    for x in t:
        reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    win = sum(1 for x in t if x["pnl"] > 0) / len(t) if t else 0
    print(f"  {label:28s} 筆{len(t):4d} 勝{win:6.1%} {reasons}｜Sharpe 全{al['sharpe']:5.2f} 訓{tr['sharpe']:5.2f} 測{te['sharpe']:5.2f}"
          f"｜年化 HK${al['ann'] / 1e4:5.1f}萬 回撤 HK${al['mdd'] / 1e4:6.1f}萬 Calmar {al['calmar']:.2f}")
    return al


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    F = fl.day_features(D)
    for name, (trig, g, tp, sl, f5) in VARIANTS.items():
        print(f"\n######## 地載・{name} ########")
        print("A. RSI 時間框（穿越／轉向都試）")
        for tf, tg in itertools.product((1, 5, 15, 60), ("cross", "confirm")):
            sig = tf_signals(D, tg, tf)
            if f5:
                sig = [(i, s) for i, s in sig if fl.keep(F, D, i, s, f5)]
            report(D, f"{tf} 分 RSI {'穿越' if tg == 'cross' else '轉向'}{'（現時）' if (tf == 1 and tg == trig) else ''}", run_seq(D, sig, g, tp, sl))
        base_sig = tf_signals(D, trig, 1)
        if f5:
            base_sig = [(i, s) for i, s in base_sig if fl.keep(F, D, i, s, f5)]
        print("B. 每月加滿倉上限")
        for cap in (1, 2, 3):
            report(D, f"每月最多 {cap} 組加滿倉", run_seq(D, base_sig, g, tp, sl, month_cap=cap))
        print("C. 加滿倉後 N 個交易日仍未止賺 → 收市全平")
        for n in (1, 2, 3, 5, 10):
            report(D, f"加滿倉後 {n} 日", run_seq(D, base_sig, g, tp, sl, time_stop=n))


if __name__ == "__main__":
    main()
