"""RSI 做趨勢（順勢）可以嗎？八年主連 1 分 K；訓練 2018-10 至 2023-12、測試 2024 起；Sharpe = 每日盈虧 × √252。

A. 日內 RSI 順勢：RSI(14)（1／5／15／60 分 K）向上穿 80 → 買、向下穿 20 → 沽（跟地載陣相反），當日升跌 ≥ m（同方向）才做；
   止蝕 k × ATR20、止賺 R × 止蝕或收市平倉；每日 1 筆、不加倉、當日收市平倉（dizai_search.simulate）。
B. 同上，再要求 Nasdaq 同一段時間同方向走 ≥ y%（地載陣篩選的另一面：有外圍支持的趨勢日）。
C. 日線 RSI(14) 趨勢（交易日 K，收市判斷、下一日開市成交、可持倉多日、1 張）：
   regime50  RSI > 50 持好倉、< 50 持淡倉（一直在市）
   break70   RSI 升穿 70 開好倉、跌穿 30 開淡倉，RSI 回到 50 平倉
每張每邊成本 1 點；金額每點 HK$50。

用法：python3 research/hsi_futures_range/dizai_trend.py --json /tmp/hsimain.json
"""
import argparse, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_cross as dc                                    # noqa: E402
import dizai_more as dm                                     # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

HKD = 50


def mom_signals(D, tf, move):
    """順勢：RSI 穿越 80 買、穿越 20 沽（dizai_more.tf_signals 是逆市，這裡把方向反過來，開閘也跟方向）。"""
    fade_short = dm.tf_signals(D, "cross", tf, move)       # 升 ≥ m 且 RSI 穿 80 → 原本沽
    return sorted((i, -s) for i, s in fade_short)          # 順勢：反過來買


def sharpe_from_daily(pnl_by_day, days, lo=None, hi=None):
    idx = [k for k, d in enumerate(days) if (lo is None or d >= lo) and (hi is None or d <= hi)]
    x = np.array([pnl_by_day.get(k, 0.0) for k in idx]) * HKD
    eq = np.cumsum(x)
    mdd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
    yrs = len(idx) / 245
    return {"sharpe": float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else 0.0,
            "ann": float(x.sum() / yrs), "mdd": mdd}


def line(label, pnl_by_day, n, days, wins=None):
    a, tr, te = (sharpe_from_daily(pnl_by_day, days), sharpe_from_daily(pnl_by_day, days, hi=ds.TRAIN_END),
                 sharpe_from_daily(pnl_by_day, days, lo="2024-01-01"))
    w = f" 勝{wins:.0%}" if wins is not None else ""
    print(f"  {label:44s} 筆{n:5d}{w}｜Sharpe 全{a['sharpe']:5.2f} 訓{tr['sharpe']:5.2f} 測{te['sharpe']:5.2f}"
          f"｜年化 HK${a['ann'] / 1e4:5.1f}萬 回撤 HK${a['mdd'] / 1e4:6.1f}萬")
    return a, tr, te


def intraday(D, sigs, k, tp):
    t = ds.simulate(D, sigs, k, tp, 1)
    by = {}
    for sid, side, pnl, reason, dist in t:
        by[sid] = by.get(sid, 0.0) + pnl
    wins = (sum(1 for x in t if x[2] > 0) / len(t)) if t else 0
    return by, len(t), wins


def daily_rsi(D):
    days, ends, starts = D["days"], D["ends"], D["starts"]
    dc_ = D["c"][ends - 1]
    do_ = D["o"][starts]
    rsi = np.array([np.nan if v is None else v for v in rad.rsi_series(list(dc_), 14)])
    return dc_, do_, rsi


def daily_strategy(D, mode):
    """回傳 (每日盈虧點 dict, 交易次數)。收市判斷 → 下一日開市成交；持倉以每日收市計盈虧。"""
    dc_, do_, rsi = daily_rsi(D)
    pos, by, trades = 0, {}, 0
    for k in range(1, len(dc_)):
        # 今日盈虧：持倉由昨收（或今日開市入場價）到今收
        pnl = 0.0
        if k - 1 >= 15 and not np.isnan(rsi[k - 1]):
            r, rp = rsi[k - 1], rsi[k - 2] if k >= 2 else np.nan
            if mode == "regime50":
                target = 1 if r > 50 else -1
            else:
                target = pos
                if rp <= 70 < r:
                    target = 1
                elif rp >= 30 > r:
                    target = -1
                elif (pos > 0 and r < 50) or (pos < 0 and r > 50):
                    target = 0
        else:
            target = pos
        if target != pos:                                    # 今日開市換倉
            pnl += pos * (do_[k] - dc_[k - 1])               # 舊倉昨收 → 今開
            pnl -= abs(target - pos) * 1.0                   # 成本
            pnl += target * (dc_[k] - do_[k])                # 新倉今開 → 今收
            trades += 1
            pos = target
        else:
            pnl += pos * (dc_[k] - dc_[k - 1])
        by[k] = pnl
    return by, trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    nq = dc.load_us("usatechidxusd")
    print("A. 日內 RSI 順勢（穿 80 買、穿 20 沽；當日收市平倉）")
    best = []
    for tf, move, k, tp in itertools.product((1, 5, 15, 60), (0.01, 0.02), (0.25, 0.5), (1, 2, 3)):
        sig = mom_signals(D, tf, move)
        by, n, w = intraday(D, sig, k, tp)
        a_, tr, te = (sharpe_from_daily(by, days), sharpe_from_daily(by, days, hi=ds.TRAIN_END),
                      sharpe_from_daily(by, days, lo="2024-01-01"))
        best.append((tr["sharpe"], te["sharpe"], a_["sharpe"], a_["ann"], a_["mdd"], n, w, tf, move, k, tp))
    best.sort(reverse=True)
    print(f"  共 {len(best)} 組；全期 Sharpe > 0 的 {sum(1 for b in best if b[2] > 0)} 組；訓練、測試都 > 0.5 的 {sum(1 for b in best if b[0] > 0.5 and b[1] > 0.5)} 組")
    print("  訓練期 Sharpe 最高 6 組：")
    for trs, tes, als, ann, mdd, n, w, tf, move, k, tp in best[:6]:
        print(f"    {tf} 分／升跌 ≥ {move:.0%}／止蝕 {k} ATR／止賺 {tp}R：筆{n} 勝{w:.0%}｜Sharpe 全{als:.2f} 訓{trs:.2f} 測{tes:.2f}"
              f"｜年化 HK${ann / 1e4:.1f}萬 回撤 HK${mdd / 1e4:.1f}萬")
    print("\nB. 日內 RSI 順勢 ＋ Nasdaq 同方向確認（升跌 ≥ 2%）")
    for tf, y, k, tp in itertools.product((1, 5, 15), (0.0025, 0.005), (0.25, 0.5), (1, 2, 3)):
        sig = mom_signals(D, tf, 0.02)
        feat = dc.features(D, [(i, -s) for i, s in sig], nq)  # features 用逆市方向計；同方向 = 逆市的「same」
        s2 = [(i, s) for i, s in sig if not dc.keep(feat, i, -s, f"same_{y * 100:g}")]
        by, n, w = intraday(D, s2, k, tp)
        if n >= 20:
            line(f"{tf} 分／Nasdaq 同向 ≥ {y:.2%}／止蝕 {k} ATR／止賺 {tp}R", by, n, days, w)
    print("\nC. 日線 RSI(14) 趨勢（1 張、可持倉多日）")
    for mode in ("regime50", "break70"):
        by, n = daily_strategy(D, mode)
        line({"regime50": "RSI > 50 好、< 50 淡（一直在市）", "break70": "RSI 穿 70 好／穿 30 淡，回 50 平倉"}[mode], by, n, days)
    bh = {k: D["c"][D["ends"][k] - 1] - D["c"][D["ends"][k - 1] - 1] for k in range(1, len(days))}
    line("對照：一直持有 1 張好倉", bh, 1, days)


if __name__ == "__main__":
    main()
