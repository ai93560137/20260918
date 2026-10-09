"""地載陣：RSI 以外的指標有沒有幫助？八年主連 1 分 K，訓練期 2018-10 至 2023-12、測試期 2024-01 起。

全部是「走過頭 → 逆市」的用法（沽的訊號；買的訊號對稱），訊號 K 線收市確認、下一根開市入場：
  rsi14／rsi7／rsi28   RSI(n) 由 80 以上跌回 80 以下（買：由 20 以下升回）
  rsi5m／rsi15m        5 分／15 分 K 的 RSI(14) 由 80 以上跌回（在 5／15 分鐘的最後一根 1 分 K 判斷）
  bb2.5／bb3           保力加通道（20 根、2.5σ／3σ）：上一根收市在上軌以上、這一根收回軌內
  stoch                隨機指標 %K(14) 由 90 以上跌回
  z2.5／z3             收市對 60 根均線的 Z 分數由 +2.5／+3 以上跌回
  run8／run10          連續 8／10 根收陽之後第一根收陰
  exh0.5／exh0.75      30 根內升幅 ≥ 0.5／0.75 × ATR20 之後第一根收陰
  newhi                創當日新高，但收市在該根高低的下半部
開閘：當日升跌（對上日收市）≥ 2%／≥ 1.5%／不設；時段全日。同一指標的訊號之間至少隔 30 根。

三把尺（都分訓練／測試）：
  1. 指標本身：入場後 15／60／240 根，逆市方向的平均點數（不扣成本）與正數比例
  2. 高勝率版：dizai_search.simulate，止蝕 0.3 × ATR20、止賺 0.06 × ATR20、每日 1 筆、收市平倉
  3. 加倍攤平版：dizai_martingale.simulate_mg，間距 0.75 × ATR20、止賺 30、止蝕 1000、1→2→4、留倉

用法：python3 research/hsi_futures_range/dizai_indicators.py --json /tmp/hsimain.json
"""
import argparse, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

COOLDOWN = 30
HORIZONS = (15, 60, 240)


def rsi_np(x, n):
    return np.array([np.nan if v is None else v for v in rad.rsi_series(list(x), n)])


def tf_rsi(D, tf):
    """tf 分鐘 K 的 RSI(14)：只在每個 tf 分鐘最後一根 1 分 K 有值，其餘 NaN。"""
    mins = np.array([int(t[14:16]) for t in D["tk"]])
    idx = np.flatnonzero(mins % tf == tf - 1)
    out = np.full(len(D["c"]), np.nan)
    out[idx] = rsi_np(D["c"][idx], 14)
    return out, idx


def indicators(D):
    c, o, h, l = D["c"], D["o"], D["h"], D["l"]
    s = pd.Series(c)
    prev = lambda a: np.r_[np.nan, a[:-1]]
    sig = {}

    def back_from(x, hi, lo):                               # 由極端區跌回／升回
        px = prev(x)
        return (px >= hi) & (x < hi), (px <= lo) & (x > lo)
    for n in (14, 7, 28):
        r = rsi_np(c, n)
        sig[f"rsi{n}"] = back_from(r, 80, 20)
    for tf in (5, 15):
        r, idx = tf_rsi(D, tf)
        sh, lo = np.zeros(len(c), bool), np.zeros(len(c), bool)
        rr = r[idx]
        pr = np.r_[np.nan, rr[:-1]]
        sh[idx] = (pr >= 80) & (rr < 80)
        lo[idx] = (pr <= 20) & (rr > 20)
        sig[f"rsi{tf}m"] = (sh, lo)
    m20, sd20 = s.rolling(20).mean().to_numpy(), s.rolling(20).std().to_numpy()
    for k in (2.5, 3.0):
        up, dn = m20 + k * sd20, m20 - k * sd20
        sig[f"bb{k:g}"] = ((prev(c) > prev(up)) & (c <= up), (prev(c) < prev(dn)) & (c >= dn))
    hh, ll = pd.Series(h).rolling(14).max().to_numpy(), pd.Series(l).rolling(14).min().to_numpy()
    k_ = 100 * (c - ll) / np.where(hh - ll > 0, hh - ll, np.nan)
    sig["stoch"] = back_from(k_, 90, 10)
    m60, sd60 = s.rolling(60).mean().to_numpy(), s.rolling(60).std().to_numpy()
    z = (c - m60) / np.where(sd60 > 0, sd60, np.nan)
    for k in (2.5, 3.0):
        sig[f"z{k:g}"] = back_from(z, k, -k)
    green, red = c > o, c < o
    for n in (8, 10):
        g_run = pd.Series(green.astype(int)).rolling(n).sum().to_numpy()
        r_run = pd.Series(red.astype(int)).rolling(n).sum().to_numpy()
        sig[f"run{n}"] = ((prev(g_run) == n) & red, (prev(r_run) == n) & green)
    chg30 = c - np.r_[np.full(30, np.nan), c[:-30]]
    for a in (0.5, 0.75):
        sig[f"exh{a:g}"] = ((prev(chg30) >= a * prev(D["atr"])) & red, (prev(chg30) <= -a * prev(D["atr"])) & green)
    new_hi = (h >= D["run_hi"]) & (prev(D["run_hi"]) < h)
    new_lo = (l <= D["run_lo"]) & (prev(D["run_lo"]) > l)
    mid = (h + l) / 2
    sig["newhi"] = (new_hi & (c < mid), new_lo & (c > mid))
    return sig


def to_list(D, sh, lo, move):
    chg = D["c"] / D["prev_close"] - 1
    same = np.r_[False, D["sid"][1:] == D["sid"][:-1]]
    ok = same & ~np.isnan(D["atr"])
    sh = np.nan_to_num(sh).astype(bool) & ok & (chg >= move)
    lo = np.nan_to_num(lo).astype(bool) & ok & (chg <= -move)
    raw = sorted([(int(i), -1) for i in np.flatnonzero(sh)] + [(int(i), 1) for i in np.flatnonzero(lo)])
    out, last = [], -10 ** 9
    for i, side in raw:
        if i - last >= COOLDOWN:
            out.append((i, side))
            last = i
    return out


def fwd(D, sigs, lo=None, hi=None):
    days, o, c, ends, sid = D["days"], D["o"], D["c"], D["ends"], D["sid"]
    res = {}
    for H in HORIZONS:
        v = []
        for i, side in sigs:
            d = days[sid[i]]
            if (lo and d < lo) or (hi and d > hi) or i + 1 >= len(o):
                continue
            j = min(i + H, ends[sid[i]] - 1)
            v.append(side * (c[j] - o[i + 1]))
        res[H] = (float(np.mean(v)) if v else 0.0, float(np.mean(np.array(v) > 0)) if v else 0.0, len(v))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    sigs = indicators(D)
    for move, mname in ((0.02, "升跌≥2%"), (0.015, "升跌≥1.5%"), (-1.0, "不設門檻")):
        print(f"\n################ {mname} ################")
        print("指標      訊號數｜15/60/240 根後逆市平均點（訓｜測）｜高勝率版 勝率 每筆（訓｜測）｜加倍攤平版 每筆（訓｜測） 止蝕次數")
        for name, (sh, lo) in sigs.items():
            sl = to_list(D, sh, lo, move)
            if len(sl) < 30:
                print(f"{name:8s} {len(sl):5d}（太少）")
                continue
            ftr, fte = fwd(D, sl, hi=ds.TRAIN_END), fwd(D, sl, lo="2024-01-01")
            fw = " ".join(f"{ftr[H][0]:+5.1f}|{fte[H][0]:+5.1f}" for H in HORIZONS)
            t = ds.simulate(D, sl, 0.3, 0.2, 1)
            a1, b1 = ds.stats(t, days, hi=ds.TRAIN_END), ds.stats(t, days, lo="2024-01-01")
            t2 = mg.simulate_mg(D, sl, 0.75, 30)
            a2, b2, s2 = (mg.summary(t2, days, hi=ds.TRAIN_END), mg.summary(t2, days, lo="2024-01-01"), mg.summary(t2, days))
            print(f"{name:8s} {len(sl):5d}｜{fw}｜{a1.get('win', 0):.0%} {a1.get('exp', 0):+5.1f}|{b1.get('exp', 0):+5.1f}"
                  f"｜{a2.get('exp', 0):+6.1f}|{b2.get('exp', 0):+6.1f} 止蝕{s2.get('reasons', {}).get('sl', 0)}")


if __name__ == "__main__":
    main()
