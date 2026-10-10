"""地載陣：RSI 仍是入場方法，加入「跨市場」篩選——恒指升跌 ≥ 2% 時，美股同一段時間有沒有同方向走？

道理：恒指大升大跌時，如果美股（S&P 500／Nasdaq）同一段時間也同方向大走，這次升跌有外圍支持、較可能延續 → 不逆市；
美股沒有同步 → 較可能是本地情緒過度 → 照 RSI 逆市。RSI 入場、加倉、止賺止蝕全部不變。

數據：恒指主連 1 分 K（HK 時間）；Dukascopy USA500／USATECH 差價合約 15 分 K（data/dukascopy/*_m15.csv.gz，UTC、K 線開市時間）。
同一段時間 = 恒指上一個交易日最後一根 1 分 K 的時間 → RSI 訊號那根 1 分 K 收市；美股價格取該時間之前最後一根已收完的 15 分 K 收市（不偷看）。
篩選（沽單看升、買單看跌，對稱）：
  same_y    美股同方向走 ≥ y% 不做
  ratio_r   美股升跌 ÷ 恒指升跌 ≥ r（同方向）不做
  oppo      只做美股反方向或沒走（≤ 0）的
Sharpe = 每日收市權益（含浮動）日變化 × √252；訓練 2018-10 至 2023-12、測試 2024 起。

用法：python3 research/hsi_futures_range/dizai_cross.py --json /tmp/hsimain.json
"""
import argparse, csv, gzip, json, sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_filters as fl                                  # noqa: E402
import dizai_more as dm                                     # noqa: E402
import dizai_search as ds                                   # noqa: E402
import dizai_vhsi as dv                                     # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EPOCH = datetime(2000, 1, 1)
VARIANTS = {"穩": ("confirm", 0.75, 30, 1000, None), "進": ("cross", 1.0, 150, 3000, "run5_3")}


def load_us(name):
    """回傳 (收完時間（UTC，分鐘，自 2000 年起）, 收市價)。"""
    t, c = [], []
    with gzip.open(REPO / "data" / "dukascopy" / f"{name}_m15.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            ts = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=15)
            t.append((ts - EPOCH).total_seconds() / 60)
            c.append(float(r["close"]))
    return np.array(t), np.array(c)


def hk_to_utc_min(tk):
    return (datetime.strptime(tk, "%Y-%m-%d %H:%M:%S") - timedelta(hours=8) - EPOCH).total_seconds() / 60 + 1  # 1 分 K 收市


def us_move(us, t0, t1):
    """美股由 t0 到 t1（UTC 分鐘）的升跌；任何一端沒有數據 → None。"""
    ut, uc = us
    a, b = np.searchsorted(ut, t0, "right") - 1, np.searchsorted(ut, t1, "right") - 1
    if a < 0 or b < 0 or ut[b] < t1 - 24 * 60 or ut[a] < t0 - 3 * 24 * 60:
        return None
    return uc[b] / uc[a] - 1


def features(D, sigs, us):
    """每個訊號：恒指升跌、美股同一段時間的升跌。"""
    tk, ends, sid, c = D["tk"], D["ends"], D["sid"], D["c"]
    out = {}
    for i, side in sigs:
        k = sid[i]
        if k == 0:
            continue
        t0 = hk_to_utc_min(tk[ends[k - 1] - 1])
        t1 = hk_to_utc_min(tk[i])
        out[i] = (c[i] / D["prev_close"][i] - 1, us_move(us, t0, t1))
    return out


def keep(feat, i, side, flt):
    if flt == "none":
        return True
    hk, um = feat.get(i, (None, None))
    if um is None:
        return True                                          # 沒有美股數據 → 照做
    same = um * (1 if side < 0 else -1)                      # 沽單：美股升為正；買單：美股跌為正
    kind, _, x = flt.partition("_")
    if kind == "same":
        return same < float(x) / 100
    if kind == "ratio":
        return same / abs(hk) < float(x)
    if kind == "oppo":
        return same <= 0
    raise ValueError(flt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    F = fl.day_features(D)
    markets = {"S&P": load_us("usa500idxusd"), "Nasdaq": load_us("usatechidxusd")}
    filters = ["none", "same_0.25", "same_0.5", "same_1", "ratio_0.2", "ratio_0.35", "ratio_0.5", "oppo"]
    for name, (trig, g, tp, sl, f5) in VARIANTS.items():
        sig = dm.tf_signals(D, trig, 1)
        if f5:
            sig = [(i, s) for i, s in sig if fl.keep(F, D, i, s, f5)]
        print(f"\n######## 地載・{name}（RSI 入場不變）########")
        for mname, us in markets.items():
            feat = features(D, sig, us)
            have = sum(1 for v in feat.values() if v[1] is not None)
            print(f"  {mname}：{have}／{len(feat)} 個訊號有美股數據")
            for flt in filters:
                s2 = [(i, s) for i, s in sig if keep(feat, i, s, flt)]
                t = dm.run_seq(D, s2, g, tp, sl)
                daily = dv.daily_equity(D, t, [1.0] * len(t)) * 50
                al, tr, te = dv.metrics(daily, days), dv.metrics(daily, days, hi=ds.TRAIN_END), dv.metrics(daily, days, lo="2024-01-01")
                nsl = sum(1 for x in t if x["reason"] == "sl")
                maes = sorted((x["mae"] for x in t), reverse=True)
                print(f"    {flt:11s} 筆{len(t):4d} 止蝕{nsl} 最遠逆向{maes[0]:5.0f}｜Sharpe 全{al['sharpe']:5.2f} 訓{tr['sharpe']:5.2f} 測{te['sharpe']:5.2f}"
                      f"｜年化 HK${al['ann'] / 1e4:5.1f}萬 回撤 HK${al['mdd'] / 1e4:6.1f}萬 Calmar {al['calmar']:.2f}")


if __name__ == "__main__":
    main()
