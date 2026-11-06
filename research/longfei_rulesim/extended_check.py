"""[IDEAS #229] 升勢日「兩日急升之後追好」係咪較差（11-06 真倉覆盤）。

起因：11-05 第 2 筆（兩日升咗過千點後追好，+130）同 11-06 10:30 筆（−143，−1R）都係急升之後喺升勢日做好。
網上（11-06 RESEARCH_LOG）：大幅變動之後多數部分回吐、細幅變動之後延續（European Journal of Finance）；
S&P 連兩日升 ≥1% 之後短期偏負（SentimenTrader，細樣本）。冇恒指期貨研究 → 用自己數據驗。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，含夜市）。升勢日＝昨收 ≥ 20 日均（user_method.daily）。
急升＝昨收 − 三日前收市（兩個交易日變動）≥ 1.5 × ATR(14)。
入場：升勢日 13:00–16:00／17:15–23:30 隨機 5 分鐘收市做好（20 種子），波段出場（止蝕 120、1R 保本、165 移動、3 日、每邊成本 2 點）。
  E  急升後嘅升勢日做好      N  其他升勢日做好

預先登記（11-06，結果出嚟之前寫，唔再改）：
  「急升後追好較差」成立 ＝ 20 種子平均 E ≤ N − 15 點、E 日子 ≥ 15、≥ 15/20 種子 E < N、前後兩半 E − N 都 < 0。
  成立 → 提案（使用者批）真倉加「兩日急升 ≥ 1.5 ATR 後唔追好」；唔成立 → 唔改，記低。

用法：python3 research/longfei_rulesim/extended_check.py [--out 結果.json]（要 GCS 讀權）
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
            raw[x.name.rsplit("/", 1)[1][:10]] = json.loads(b.blob(x.name).download_as_bytes())
        except Exception:  # noqa: BLE001
            continue
    bars = um.load(raw)
    dkeys, ctx = um.daily(bars)
    keys = sc.day_keys(bars)
    ds = sorted(ctx)
    ext = {}
    for k, d in enumerate(ds):
        x = ctx[d]
        if x["pdc"] < x["sma"] or k < 2:
            continue
        ext[d] = (x["pdc"] - ctx[ds[k - 2]]["pdc"]) >= 1.5 * x["atr"]
    by_day = {}
    for i, (t, *_r) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in sc.WINDOWS):
            sd = um.session_date(t)
            if sd in ext:
                by_day.setdefault(sd, []).append(i)
    days = sorted(by_day)
    split = days[len(days) // 2]
    seeds = []
    for seed in range(20):
        rnd = random.Random(seed)
        E, N, Eh, Nh = [], [], {0: [], 1: []}, {0: [], 1: []}
        for sd in days:
            i = rnd.choice(by_day[sd])
            r = sc.run(bars, keys, i, 1, bars[i][4], "S")
            h = 0 if sd < split else 1
            (E if ext[sd] else N).append(r)
            (Eh if ext[sd] else Nh)[h].append(r)
        mm = lambda v: statistics.mean(v) if v else 0.0  # noqa: E731
        seeds.append({"E": mm(E), "N": mm(N), "d1": mm(Eh[0]) - mm(Nh[0]), "d2": mm(Eh[1]) - mm(Nh[1])})
    m = lambda k: round(statistics.mean(s[k] for s in seeds), 2)  # noqa: E731
    ne = sum(1 for d in days if ext[d])
    res = {"from": str(bars[0][0]), "to": str(bars[-1][0]), "uptrend_days": len(days), "extended_days": ne,
           "seed_mean": {k: m(k) for k in ("E", "N", "d1", "d2")},
           "seeds_E_lt_N": sum(1 for s in seeds if s["E"] < s["N"])}
    sm = res["seed_mean"]
    res["pass"] = bool(sm["E"] <= sm["N"] - 15 and ne >= 15 and res["seeds_E_lt_N"] >= 15 and sm["d1"] < 0 and sm["d2"] < 0)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
