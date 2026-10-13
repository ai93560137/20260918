"""地載陣紙上策略的回測期望（供 research/divergence/expectations.json 登記）。

沿用 portfolio.py 的成份（恒指主連 1 分 K，1 張大期，每日盈虧點，每邊扣 1 點），2021-01 起按月加總，
輸出每月平均、標準差、t 值、月數、最大回撤（點，按日權益）、勝率月數。
權重 = DIZAI_HE：合(不含衡) = 缺×1 + 突破V×1 + 穩60×2 + 進NQ×1；合(含衡) = 再加衡×1。

用法：python3 research/hsi_futures_range/dizai_expect.py --json /path/hsimain.json
"""
import argparse, json, math, statistics, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio as pf                                      # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

W_EX = {"缺": 1, "突破V": 1, "穩60": 2, "進NQ": 1}
W_IN = dict(W_EX, 衡=1)
START = "2021-01-01"


def stats(x, days):
    sel = [i for i, d in enumerate(days) if d >= START]
    v = np.array([x[i] for i in sel])
    ds_ = [days[i] for i in sel]
    months = {}
    for d, p in zip(ds_, v):
        months[d[:7]] = months.get(d[:7], 0.0) + p
    m = list(months.values())
    n = len(m)
    mean, sd = statistics.fmean(m), statistics.stdev(m)
    eq = np.cumsum(v)
    mdd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
    return {"n_months": n, "bt_mean_pts_month": round(mean, 1), "bt_std_pts_month": round(sd, 1),
            "bt_t": round(mean / (sd / math.sqrt(n)), 2), "bt_win_months": round(sum(1 for q in m if q > 0) / n, 3),
            "bt_worst_month_pts": round(min(m), 1), "bt_max_dd_pts": round(mdd, 1),
            "ann_pts": round(v.sum() / (len(sel) / 245)), "sample": f"{ds_[0]} → {ds_[-1]}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    C = pf.components(D)
    out = {n: stats(C[n], days) for n in ("衡", "缺", "突破V", "穩60", "進NQ")}
    out["合_ex"] = stats(sum(w * C[n] for n, w in W_EX.items()), days)
    out["合_in"] = stats(sum(w * C[n] for n, w in W_IN.items()), days)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
