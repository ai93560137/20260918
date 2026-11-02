"""[IDEAS #210] MHI 波段移動止蝕啟動點：120 點 vs 現行 165 點（RESEARCH_LOG 10-29「下一步」）。

起因：10-28 真倉沽 23,087，最多浮賺 132 點（1.1R）觸發保本，但未到 165 點移動止蝕，最後 +2 點平。
網上只有實務講法（啟動時機比距離重要），冇正式研究 → 用自己數據驗。

入場：swing_check 順日線隨機入場（每日 1 次、20 個種子），同埋使用者自己入場（U）。
出場（止蝕 120、1R 保本、最多 3 日、每邊成本 2 點，只改移動止蝕）：
  S165  現行：浮賺 ≥ 165 點後，最高浮賺 − 165 點
  S120  浮賺 ≥ 120 點後，最高浮賺 − 120 點
  S120w 浮賺 ≥ 120 點後，最高浮賺 − 165 點（早啟動、闊距離）
  S200  浮賺 ≥ 200 點後，最高浮賺 − 165 點

預先登記（11-02，結果出嚟之前寫，唔再改）：
  變體「好過現行」＝ 20 種子平均每筆 ≥ S165 + 5 點、≥ 15/20 種子每筆平均好過 S165、
  平均最大回撤唔差過 S165 嘅 1.1 倍，而且 U（使用者入場）每筆平均都 ≥ S165。
用途（只係提案，真倉要使用者批）：有變體過 → 提案改 SWING_TRAIL_START／SWING_TRAIL；都唔過 → 維持 165／165。

用法：python3 research/longfei_rulesim/trail_check.py [--out 結果.json]（要 GCS 讀權）
"""
import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402
import swing_check as sc  # noqa: E402

VARIANTS = {"S165": (165, 165), "S120": (120, 120), "S120w": (120, 165), "S200": (200, 165)}


def run_v(bars, keys, i, side, entry, v):
    sc.SWING["trail_start"], sc.SWING["trail"] = VARIANTS[v]
    return sc.run(bars, keys, i, side, entry, "S")


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
    pnl = json.loads(b.blob("futu/pnl/latest.json").download_as_bytes())
    bars = um.load(raw)
    dkeys, ctx = um.daily(bars)
    keys = sc.day_keys(bars)
    idx = {bb[0]: i for i, bb in enumerate(bars)}
    by_day = {}
    for i, (t, *_r) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in sc.WINDOWS):
            sd = um.session_date(t)
            x = ctx.get(sd)
            if x:
                by_day.setdefault(sd, []).append((i, 1 if x["pdc"] > x["sma"] else -1))
    per_seed = {v: [] for v in VARIANTS}
    dds = {v: [] for v in VARIANTS}
    for seed in range(20):
        rnd = random.Random(seed)
        picks = [rnd.choice(by_day[sd]) for sd in sorted(by_day)]
        for v in VARIANTS:
            xs = [run_v(bars, keys, i, s, bars[i][4], v) for i, s in picks]
            per_seed[v].append(statistics.mean(xs))
            eq = peak = dd = 0.0
            for x in xs:
                eq += x
                peak = max(peak, eq)
                dd = min(dd, eq - peak)
            dds[v].append(dd)
    from user_trades import round_trips
    seen, U = set(), []
    for tr in round_trips(pnl):
        if not re.match(r"^HK\.(HSI|MHI)\d{4}$", tr["code"]):
            continue
        t = tr["open_t"].replace(second=0, microsecond=0)
        if (t, tr["side"]) in seen or t not in idx:
            continue
        seen.add((t, tr["side"]))
        U.append((idx[t], tr["side"], tr["open_px"]))
    u = {v: statistics.mean(run_v(bars, keys, i, s, px, v) for i, s, px in U) for v in VARIANTS}
    base = per_seed["S165"]
    res = {"from": str(bars[0][0]), "to": str(bars[-1][0]), "U_n": len(U), "variants": {}}
    for v in VARIANTS:
        m = statistics.mean(per_seed[v])
        wins = sum(1 for x, y in zip(per_seed[v], base) if x > y)
        r = {"T_avg_pts": round(m, 2), "T_seed_range": [round(min(per_seed[v]), 1), round(max(per_seed[v]), 1)],
             "T_wins_vs_S165": wins, "T_avg_max_dd": round(statistics.mean(dds[v]), 1), "U_avg_pts": round(u[v], 2)}
        if v != "S165":
            r["pass"] = bool(m >= statistics.mean(base) + 5 and wins >= 15
                             and statistics.mean(dds[v]) >= 1.1 * statistics.mean(dds["S165"]) and u[v] >= u["S165"])
        res["variants"][v] = r
    sc.SWING["trail_start"], sc.SWING["trail"] = 165, 165
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
