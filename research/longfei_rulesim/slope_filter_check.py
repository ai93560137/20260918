"""[IDEAS #226] 跌勢定義：「昨收 < 20 日均」（現行 #129）vs「20 日均線向下（今日 SMA20 < 5 日前 SMA20）」vs 兩樣都要。

起因：IDEAS #224 證實跌勢日做好平均 −20 點，但做淡都只係 ≈0；實務講法（LuxAlgo 等）話均線斜率比價喺均線上下穩定，
價喺平坦均線上下可以穿好多次。所以試用斜率定義跌勢，睇做淡會唔會好啲。

入場：swing_check 隨機入場（每日 1 次，13:00–16:00／17:15–23:30 5 分鐘收市，20 個種子），只做淡；
波段出場（止蝕 120、1R 保本、165 移動止蝕、最多 3 日），每邊成本 2 點。數據：GCS HSI_FRONT 1 分鐘。
  P  現行：昨收 < 昨日計嘅 20 日均（user_method ctx）
  S  斜率：今日 SMA20 < 5 個交易日前 SMA20
  B  P 同 S 都成立

預先登記（11-04，結果出嚟之前寫，唔再改）：
  S 或 B「好過現行」＝ 20 種子平均每筆 ≥ P + 5 點、≥ 15/20 種子每筆平均好過 P、該定義合資格日子 ≥ 60。
  好過 → 提案改跌勢定義（真倉要使用者批）；唔好過 → 維持 P。

用法：python3 research/longfei_rulesim/slope_filter_check.py [--out 結果.json]（要 GCS 讀權）
"""
import argparse
import json
import random
import statistics
import sys
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
    order = [d for d in dkeys if d in ctx]
    defs = {"P": set(), "S": set(), "B": set()}
    for i, d in enumerate(order):
        p = ctx[d]["pdc"] < ctx[d]["sma"]
        s = i >= 5 and ctx[d]["sma"] < ctx[order[i - 5]]["sma"]
        if p:
            defs["P"].add(d)
        if s:
            defs["S"].add(d)
        if p and s:
            defs["B"].add(d)
    by_day = {}
    for i, (t, *_r) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in sc.WINDOWS):
            sd = um.session_date(t)
            if sd in ctx:
                by_day.setdefault(sd, []).append(i)
    res = {"from": str(bars[0][0]), "to": str(bars[-1][0]), "days": {k: len(v & set(by_day)) for k, v in defs.items()}}
    per = {k: [] for k in defs}
    for seed in range(20):
        rnd = random.Random(seed)
        pick = {sd: rnd.choice(by_day[sd]) for sd in sorted(by_day)}
        for k, ds in defs.items():
            xs = [sc.run(bars, keys, pick[sd], -1, bars[pick[sd]][4], "S") for sd in sorted(ds) if sd in pick]
            per[k].append(statistics.mean(xs) if xs else 0.0)
    base = statistics.mean(per["P"])
    for k in defs:
        m = statistics.mean(per[k])
        r = {"avg_pts": round(m, 2), "seed_range": [round(min(per[k]), 1), round(max(per[k]), 1)],
             "wins_vs_P": sum(1 for x, y in zip(per[k], per["P"]) if x > y)}
        if k != "P":
            r["pass"] = bool(m >= base + 5 and r["wins_vs_P"] >= 15 and res["days"][k] >= 60)
        res[k] = r
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
