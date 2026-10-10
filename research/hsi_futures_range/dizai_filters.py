"""地載陣加倍攤平版：加入入場前已知的條件，能否擴大安全邊際？同時列勝率與 RRR。

基準規則：RSI(14) 轉向逆市、當日升跌 ≥ 2%、全日、間距 0.75 × ATR20、1→2→4、止賺 30、留倉（dizai_martingale）。
做法：先把止蝕設成無限大，記錄每筆「離最終平均成本最遠的逆向點數」（MAE）；條件能把 MAE 最大的幾筆擋掉、又保留大部分交易，
就是擴大安全邊際。之後再用止蝕 1000／2000／3000 點實跑，列勝率、RRR、總點數，分訓練（2018-10 至 2023-12）／測試期（2024 起）。

條件（全部是入場前已知）：
  trend_with   只順大市逆市：上日收市在 20 日均線之下才沽急升、之上才買急跌
  trend_against 只逆大市逆市：相反
  vol_lo／vol_hi ATR20 ÷ 過去 250 日 ATR20 中位數 < 0.8 不做／> 1.3 不做
  no_mon／no_fri 星期一／五不做
  gap_only／intraday_only 當日升跌主要來自開市跳空（|開市 − 上日收市| ≥ 一半升跌）／主要來自日內
  run5_x       過去 5 個交易日已經同方向走 ≥ x%（沽時已升 ≥ x%、買時已跌 ≥ x%）不做，x = 3／5
RRR：實際 = 平均贏 ÷ 平均輸（有輸才有）；最壞 = 平均贏 ÷ 一次止蝕會輸的點數（止蝕點數 × 4 張）。

用法：python3 research/hsi_futures_range/dizai_filters.py --json /tmp/hsimain.json
"""
import argparse, json, sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

BASE = {"trig": "confirm", "move": 0.02, "win": "all", "g": 0.75, "tp": 30, "lots": (1, 2)}


def day_features(D):
    days, starts, ends = D["days"], D["starts"], D["ends"]
    dc = D["c"][ends - 1]
    do = D["o"][starts]
    nd = len(days)
    atr_d = np.array([D["atr"][s] for s in starts])
    ma20 = np.full(nd, np.nan)
    vol_ratio = np.full(nd, np.nan)
    ret5 = np.full(nd, np.nan)
    ret10 = np.full(nd, np.nan)
    prev_move = np.full(nd, np.nan)
    for k in range(nd):
        if k >= 20:
            ma20[k] = dc[k - 20:k].mean()                    # 到上日為止
        if k >= 270 and not np.isnan(atr_d[k]):
            vol_ratio[k] = atr_d[k] / np.nanmedian(atr_d[k - 250:k])
        if k >= 6:
            ret5[k] = dc[k - 1] / dc[k - 6] - 1             # 上日收市對 5 日前收市
        if k >= 11:
            ret10[k] = dc[k - 1] / dc[k - 11] - 1
        if k >= 2:
            prev_move[k] = dc[k - 1] / dc[k - 2] - 1        # 上一個交易日的升跌
    prev_close = np.r_[np.nan, dc[:-1]]
    weekday = np.array([date.fromisoformat(d).weekday() for d in days])
    return {"ma20": ma20, "vol_ratio": vol_ratio, "ret5": ret5, "ret10": ret10, "prev_move": prev_move, "atr_d": atr_d, "prev_close": prev_close, "open": do, "weekday": weekday}


def keep(F, D, i, side, name):
    d = D["sid"][i]
    pc, c = F["prev_close"][d], D["c"][i]
    if name == "none":
        return True
    if name in ("trend_with", "trend_against"):
        if np.isnan(F["ma20"][d]):
            return False
        below = pc < F["ma20"][d]
        with_ = (side < 0 and below) or (side > 0 and not below)
        return with_ if name == "trend_with" else not with_
    if name == "vol_lo":
        return not (F["vol_ratio"][d] < 0.8)
    if name == "vol_hi":
        return not (F["vol_ratio"][d] > 1.3)
    if name == "no_mon":
        return F["weekday"][d] != 0
    if name == "no_fri":
        return F["weekday"][d] != 4
    if name in ("gap_only", "intraday_only"):
        gap = abs(F["open"][d] - pc) >= 0.5 * abs(c - pc)
        return gap if name == "gap_only" else not gap
    if "&" in name:
        return all(keep(F, D, i, side, n) for n in name.split("&"))
    if name.startswith("run10_"):
        x = float(name[6:]) / 100
        r = F["ret10"][d]
        return not ((side < 0 and r >= x) or (side > 0 and r <= -x))
    if name.startswith("madist_"):                            # 上日收市離 20 日均線 ≥ x × ATR20（同方向）不做
        x = float(name[7:])
        if np.isnan(F["ma20"][d]):
            return False
        dist = (pc - F["ma20"][d]) / F["atr_d"][d]
        return not ((side < 0 and dist >= x) or (side > 0 and dist <= -x))
    if name == "no_prev2":                                    # 上一個交易日也同方向升跌 ≥ 2% 不做
        m = F["prev_move"][d]
        return not ((side < 0 and m >= 0.02) or (side > 0 and m <= -0.02))
    if name == "no_first_hour":                               # 日市開市第一小時（09:15–10:15）不入場
        t = D["tk"][i][11:16]
        return not ("09:00" <= t < "10:15")
    if name.startswith("run5_"):
        x = float(name[5:]) / 100
        r = F["ret5"][d]
        return not ((side < 0 and r >= x) or (side > 0 and r <= -x))
    raise ValueError(name)


FILTERS = ("none", "trend_with", "trend_against", "vol_lo", "vol_hi", "no_mon", "no_fri",
           "gap_only", "intraday_only", "run5_3", "run5_5")
FILTERS2 = ("none", "run5_3", "run5_2", "run10_4", "run10_6", "madist_2", "madist_3", "no_prev2", "no_first_hour",
            "run5_3&run10_4", "run5_3&madist_2", "run5_3&no_prev2", "run5_3&no_first_hour", "run5_2&madist_2")


def rrr(trades, sl, lots_max=4):
    p = np.array([x["pnl"] for x in trades])
    w, l = p[p > 0], p[p <= 0]
    real = (w.mean() / -l.mean()) if len(w) and len(l) and l.mean() < 0 else None
    worst = w.mean() / (sl * lots_max) if len(w) else None
    return real, worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--trig", default=BASE["trig"])
    ap.add_argument("--move", type=float, default=BASE["move"])
    ap.add_argument("--g", type=float, default=BASE["g"])
    ap.add_argument("--tp", type=float, default=BASE["tp"])
    ap.add_argument("--set2", action="store_true", help="用第二批條件（FILTERS2）")
    a = ap.parse_args()
    BASE.update(trig=a.trig, move=a.move, g=a.g, tp=a.tp)
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    F = day_features(D)
    sig = ds.signals(D, "fade", BASE["trig"], BASE["move"], BASE["win"])
    print(f"基準：RSI {'轉向' if BASE['trig'] == 'confirm' else '穿越'}／升跌 ≥ {BASE['move']:.2%}／全日／"
          f"間距 {BASE['g']} × ATR20／1→2→4／止賺 {BASE['tp']:.0f}／留倉\n")
    print("條件            筆數 ｜無止蝕時最遠逆向（最大／第 2／第 3，點）＞1000 ＞2000｜"
          "止蝕 1000：勝率 實際RRR 最壞RRR 每筆（訓｜測） 總｜止蝕 2000：勝率 每筆 總｜止蝕 3000：勝率 每筆 總")
    for name in (FILTERS2 if a.set2 else FILTERS):
        s2 = [(i, sd) for i, sd in sig if keep(F, D, i, sd, name)]
        t_inf = mg.simulate_mg(D, s2, BASE["g"], BASE["tp"], sl_pts=1e9, add_lots=BASE["lots"])
        mae = sorted((x["mae"] for x in t_inf), reverse=True)
        line = (f"{name:15s} {len(t_inf):4d} ｜{mae[0]:5.0f}／{mae[1]:5.0f}／{mae[2]:5.0f}  "
                f"{sum(1 for m in mae if m > 1000):3d}  {sum(1 for m in mae if m > 2000):3d}｜")
        for sl in (1000, 2000, 3000):
            t = mg.simulate_mg(D, s2, BASE["g"], BASE["tp"], sl_pts=sl, add_lots=BASE["lots"])
            s, tr, te = mg.summary(t, days), mg.summary(t, days, hi=ds.TRAIN_END), mg.summary(t, days, lo="2024-01-01")
            real, worst = rrr(t, sl)
            if sl == 1000:
                line += (f"{s['win']:.1%} {'—' if real is None else f'{real:.2f}'} {worst:.4f} "
                         f"{tr['exp']:+.1f}|{te.get('exp', 0):+.1f} {s['total']:+.0f}｜")
            else:
                line += f"{s['win']:.1%} {s['exp']:+.1f} {s['total']:+.0f}｜"
        print(line)


if __name__ == "__main__":
    main()
