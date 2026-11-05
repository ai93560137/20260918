"""[IDEAS #228] 跌勢日「日內企返 20 日均線」後做好有冇優勢（IDEAS #129 11-05 重新登記嘅離線驗證）。

起因：11-04 MHI 真倉喺跌勢日（昨收 23,503 < 20 日均 23,681）日內企返均線後做好，+629 點；使用者 11-05 揀「維持 AI 判斷」。
#224 已證：跌勢日隨機做好平均 −20 點。問題：加「入場時 5 分鐘收市已企返 20 日均線上面」呢個條件，會唔會變正？
網上（11-05 RESEARCH_LOG）：收市確認可以減少假訊號，但冇證據話扣成本後一定改善 → 用自己數據驗。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，含夜市）。跌勢日＝昨收 < 20 日均（user_method.daily）。
入場窗口同 swing_check（13:00–16:00／17:15–23:30 5 分鐘收市），波段出場（止蝕 120、1R 保本、165 移動、最多 3 日、每邊成本 2 點）。
  R  企返做好：跌勢日入面，5 分鐘收市 > 20 日均線嘅入場點隨機揀 1 個（冇就嗰日唔做）
  RF 第一次企返：嗰日第一支收市 > 20 日均線嘅 5 分鐘 K 入場（確定性）
  L  對照：同一批日子（有企返嘅日子）隨機時間做好（唔理均線）

預先登記（11-05，結果出嚟之前寫，唔再改）：
  「企返做好有優勢」成立 ＝ 20 種子平均 R 每筆 ≥ +10 點、R − L ≥ +15 點、合資格日子 ≥ 25、
  RF 每筆 > 0，而且前後兩半 R 都 > 0。
  成立 → #129 (a) 嘅「日內企返均線」例外有數據支持，維持 AI 判斷；唔成立 → 記低，日內轉勢做好前向 10 筆照計，
  同時提案（要使用者批）考慮硬閘門。

用法：python3 research/longfei_rulesim/reclaim_check.py [--out 結果.json]（要 GCS 讀權）
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
    down = {d: x for d, x in ctx.items() if x["pdc"] < x["sma"]}
    allc, rec = {}, {}
    for i, (t, *_r, c) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in sc.WINDOWS):
            sd = um.session_date(t)
            if sd in down:
                allc.setdefault(sd, []).append(i)
                if c > down[sd]["sma"]:
                    rec.setdefault(sd, []).append(i)
    days = sorted(rec)
    split = days[len(days) // 2] if days else None
    rf = [sc.run(bars, keys, rec[sd][0], 1, bars[rec[sd][0]][4], "S") for sd in days]
    seeds = []
    for seed in range(20):
        rnd = random.Random(seed)
        R, L, h1, h2 = [], [], [], []
        for sd in days:
            i = rnd.choice(rec[sd])
            j = rnd.choice(allc[sd])
            r = sc.run(bars, keys, i, 1, bars[i][4], "S")
            R.append(r)
            L.append(sc.run(bars, keys, j, 1, bars[j][4], "S"))
            (h1 if sd < split else h2).append(r)
        seeds.append({"R": statistics.mean(R), "L": statistics.mean(L),
                      "h1": statistics.mean(h1) if h1 else 0, "h2": statistics.mean(h2) if h2 else 0})
    m = lambda k: round(statistics.mean(s[k] for s in seeds), 2)  # noqa: E731
    res = {"from": str(bars[0][0]), "to": str(bars[-1][0]), "downtrend_days": len(down), "reclaim_days": len(days),
           "seed_mean": {k: m(k) for k in ("R", "L", "h1", "h2")},
           "R_seed_range": [round(min(s["R"] for s in seeds), 1), round(max(s["R"] for s in seeds), 1)],
           "RF": {"n": len(rf), "mean": round(statistics.mean(rf), 2) if rf else None,
                  "win": round(sum(x > 0 for x in rf) / len(rf), 3) if rf else None}}
    sm = res["seed_mean"]
    res["pass"] = bool(sm["R"] >= 10 and sm["R"] - sm["L"] >= 15 and len(days) >= 25
                       and (res["RF"]["mean"] or 0) > 0 and sm["h1"] > 0 and sm["h2"] > 0)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
