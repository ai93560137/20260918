"""[IDEAS #224] 日線跌勢日「唔做好」（規則 #129）有冇錯過嘢：跌勢日隨機做好 vs 做淡（同一批入場時間）。

起因：11-02 覆盤——恒指喺日線跌勢入面反彈（11-02 升約 340 點），MHI 只准沽空，連續 3 個交易日冇開倉。
網上只有實務講法（跌穿均線後多數跌幅喺之後、亦有 whipsaw），冇針對恒指即日／波段嘅研究 → 用自己數據驗。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，含夜市）。日線跌勢＝昨收 < 20 日均（user_method.daily）。
入場：跌勢日 13:00–16:00／17:15–23:30 隨機一支 5 分鐘收市（swing_check 一樣，20 個種子），
同一個入場時間分別做好（L）同做淡（S），波段出場（止蝕 120、1R 保本、165 移動止蝕、最多 3 日、每邊成本 2 點）。
另外描述性：跌勢日日市收市 > 開市嘅比例同平均變動。

預先登記（11-03，結果出嚟之前寫，唔再改）：
  「規則 #129 錯過咗嘢」成立 ＝ 20 種子平均（L − S）每筆 ≥ +10 點，L 每筆平均 > 0，
  同一批入場配對差嘅 t ≥ 2（種子 0），而且前後兩半樣本 L − S 都 > 0。
  成立 → 提案放寬 #129（例如跌勢日都准做好），真倉要使用者批；唔成立 → 維持 #129。

用法：python3 research/longfei_rulesim/downtrend_long_check.py [--out 結果.json]（要 GCS 讀權）
"""
import argparse
import json
import math
import random
import statistics
import sys
from datetime import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402
import swing_check as sc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    from google.cloud import storage
    b = storage.Client().bucket(um.GCS_BUCKET)
    raw = {}
    for x in b.list_blobs(prefix=um.GCS_BARS):
        try:
            raw[x.name.rsplit("/", 1)[1][:10]] = json.loads(x.download_as_bytes())
        except Exception:  # noqa: BLE001
            continue
    bars = um.load(raw)
    dkeys, ctx = um.daily(bars)
    keys = sc.day_keys(bars)
    down = {d for d, x in ctx.items() if x["pdc"] < x["sma"]}
    by_day = {}
    for i, (t, *_r) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in sc.WINDOWS):
            sd = um.session_date(t)
            if sd in down:
                by_day.setdefault(sd, []).append(i)
    days = sorted(by_day)
    split = days[len(days) // 2]
    seeds = []
    paired0 = None
    for seed in range(20):
        rnd = random.Random(seed)
        rows = []
        for sd in days:
            i = rnd.choice(by_day[sd])
            px = bars[i][4]
            rows.append((sd, sc.run(bars, keys, i, 1, px, "S"), sc.run(bars, keys, i, -1, px, "S")))
        L = [r[1] for r in rows]
        S = [r[2] for r in rows]
        diff = [l - s for l, s in zip(L, S)]
        h1 = [d for (sd, *_x), d in zip(rows, diff) if sd < split]
        h2 = [d for (sd, *_x), d in zip(rows, diff) if sd >= split]
        seeds.append({"L": statistics.mean(L), "S": statistics.mean(S), "diff": statistics.mean(diff),
                      "h1": statistics.mean(h1), "h2": statistics.mean(h2)})
        if seed == 0:
            sd_ = statistics.stdev(diff)
            paired0 = {"n": len(diff), "mean": round(statistics.mean(diff), 1),
                       "t": round(statistics.mean(diff) / (sd_ / math.sqrt(len(diff))), 2) if sd_ else None}
    # 描述性：跌勢日日市 開→收
    day_oc = {}
    for t, o, h, lo, c in bars:
        if time(9, 15) < t.time() <= time(16, 30) and t.date() in down:
            r = day_oc.setdefault(t.date(), [o, c])
            r[1] = c
    moves = [c - o for o, c in day_oc.values()]
    m = lambda k: round(statistics.mean(s[k] for s in seeds), 2)  # noqa: E731
    res = {"from": str(bars[0][0]), "to": str(bars[-1][0]), "downtrend_days": len(days),
           "all_days": len(ctx), "seed_mean": {k: m(k) for k in ("L", "S", "diff", "h1", "h2")},
           "diff_seed_range": [round(min(s["diff"] for s in seeds), 1), round(max(s["diff"] for s in seeds), 1)],
           "paired_seed0": paired0,
           "downtrend_day_session": {"n": len(moves), "up_share": round(sum(x > 0 for x in moves) / len(moves), 3),
                                     "mean_pts": round(statistics.mean(moves), 1),
                                     "median_abs_pts": statistics.median(abs(x) for x in moves)}}
    sm = res["seed_mean"]
    res["pass"] = bool(sm["diff"] >= 10 and sm["L"] > 0 and (paired0["t"] or 0) >= 2 and sm["h1"] > 0 and sm["h2"] > 0)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
