"""[IDEAS #1442] 白銀趨勢簿冷啟動日線種子：MT5 XAGUSD M1（研究快取 mt5x/）→ UTC 日線 → xau/trend_d1_seed_xagusd.py。
上線前要用最新 MT5 匯出重跑（種子尾同上線日之間唔可以有缺日，否則「單日升」會用錯兩日差）。
用法：python3 research/strategy_search/build_seed_xag.py"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import data_cache as DC      # noqa: E402

KEEP = 420


def closed(ts):                                          # 同 xau/trend_live.closed_window（XAU_TREND_DROP_SUNDAY=1）
    wd = (int(ts) // 86400 + 3) % 7
    return wd in (5, 6)                                  # 白銀：XAU_TREND_DROP_SUNDAY 預設開，星期日全日唔收


def main():
    parts = [DC.get(f"mt5x/XAGUSD_m1_{y}.npz") for y in ("2024", "2025", "2026p")]
    d = {k: np.concatenate([p[k] for p in parts if p is not None]) for k in ("t", "o", "h", "l", "c")}
    ok = np.array([not closed(t) for t in d["t"]]); d = {k: v[ok] for k, v in d.items()}
    day = d["t"] // 86400; st = np.r_[0, np.nonzero(np.diff(day))[0] + 1]; en = np.r_[st[1:], len(day)]
    seed = {str(int(day[a])): {"o": round(float(d["o"][a]), 3), "h": round(float(d["h"][a:b].max()), 3), "l": round(float(d["l"][a:b].min()), 3),
                               "c": round(float(d["c"][b - 1]), 3), "t0": int(d["t"][a]), "t1": int(d["t"][b - 1])} for a, b in zip(st, en)}
    keys = sorted(seed, key=int)[-KEEP:]; seed = {k: seed[k] for k in keys}
    f = lambda k: dt.datetime.fromtimestamp(int(k) * 86400, dt.timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    out = os.path.join(HERE, "..", "..", "xau", "trend_d1_seed_xagusd.py")
    with open(out, "w") as fh:
        fh.write(f'"""[IDEAS #1442] 白銀趨勢簿日線種子（UTC 日；MT5 XAGUSD M1 {f(keys[0])}→{f(keys[-1])}；只係冷啟動用）。自動產生（research/strategy_search/build_seed_xag.py），唔好手改。"""\n')
        fh.write("SEED = " + json.dumps(seed, separators=(",", ":")) + "\n")
    print(len(seed), f(keys[0]), f(keys[-1]), seed[keys[-1]])
    gaps = [f(keys[i]) for i in range(1, len(keys)) if int(keys[i]) - int(keys[i - 1]) > 3]; print("gaps>3d:", gaps)


if __name__ == "__main__":
    main()
