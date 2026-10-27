"""[IDEAS #135] MHI 真倉波段出場（R299）歷史回測：同一批入場，比較「波段出場」同「即日出場」。

使用者 10-27：「5 筆樣本仲好細，用歷史回測」。
入場（AI 歷史決定只得 19 筆，唔夠，所以用三批代替）：
  U  使用者自己嘅恒指／MHI 期貨入場（富途成交，同一分鐘同方向當一個）
  T  順日線隨機入場：每個交易日喺日市下午或夜市（13:00–16:00、17:15–23:30）隨機揀一支 5 分鐘收市，
     方向跟日線（昨收 vs 20 日均線），模擬「AI 每日最多開 1 次、順勢」；固定種子，重複 20 次取平均
  A  龍飛陣 AI 真倉＋模擬實際入場（GCS longfei/HSI、longfei/real/MHI 嘅 trades）
出場：
  S  波段（R299）：止蝕 120 點；浮賺 ≥ 120 點（1R）止蝕移開倉價；浮賺 ≥ 165 點後 165 點移動止蝕（只收緊）；
     最多揸 3 個交易日，第 3 日 16:20 平；可以過夜（跳空照計）
  D  即日（而家大約做法）：止蝕 50 點；R297 保本；同一個時段收市前 10 分鐘平（日市 16:20、夜市 02:50）
成本每邊 2 點（MHI 每點 HK$10）。數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，含夜市）。

用法：python3 research/longfei_rulesim/swing_check.py [--out 報告.md]
"""
import argparse
import json
import math
import random
import statistics
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402

COST = 2.0
SWING = {"stop": 120, "be": 120, "trail_start": 165, "trail": 165, "days": 3}
DAY = {"stop": 50, "be": 50}
WINDOWS = ((time(13, 0), time(16, 0)), (time(17, 15), time(23, 30)))


def day_keys(bars):
    """每支 K 線 → 交易日序號（17:00 之後同凌晨夜市屬下一個有日市嘅日子；週末跳到星期一）。"""
    from bisect import bisect_left
    day_dates = sorted({b[0].date() for b in bars if time(9, 15) <= b[0].time() < time(16, 30)})
    return [bisect_left(day_dates, t.date() + timedelta(days=1) if t.time() >= time(17, 0) else t.date())
            for t, *_ in bars]


def run(bars, keys, i, side, entry, mode):
    p = SWING if mode == "S" else DAY
    stop, mfe = entry - side * p["stop"], 0.0
    k0, sess_night = keys[i], not (time(9, 15) <= bars[i][0].time() < time(16, 30))
    for j in range(i + 1, len(bars)):
        t, o, h, lo, c = bars[j]
        if (side > 0 and lo <= stop) or (side < 0 and h >= stop):
            px = min(stop, o) if side > 0 else max(stop, o)
            return (px - entry) * side - 2 * COST
        mfe = max(mfe, (h - entry) if side > 0 else (entry - lo))
        if mfe >= p["be"]:
            stop = max(stop, entry) if side > 0 else min(stop, entry)
        if mode == "S" and mfe >= p["trail_start"]:
            tr = entry + side * (mfe - p["trail"])
            stop = max(stop, tr) if side > 0 else min(stop, tr)
        if mode == "S":
            if keys[j] - k0 >= p["days"] - 1 and time(16, 20) <= t.time() < time(16, 30):
                return (c - entry) * side - 2 * COST
        else:
            night = not (time(9, 15) <= t.time() < time(16, 30))
            end = (night and time(2, 50) <= t.time() < time(3, 0)) or (not night and time(16, 20) <= t.time() < time(16, 30))
            if end or keys[j] != k0 or night != sess_night:
                return (c - entry) * side - 2 * COST
    return (bars[-1][4] - entry) * side - 2 * COST


def stats(xs):
    n = len(xs)
    if n < 2:
        return {"n": n}
    m = sum(xs) / n
    sd = statistics.stdev(xs)
    w, lo = [x for x in xs if x > 0], [-x for x in xs if x < 0]
    eq = peak = dd = 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"n": n, "avg_pts": round(m, 1), "win": round(len(w) / n, 3), "pf": round(sum(w) / sum(lo), 2) if lo else None,
            "t": round(m / (sd / math.sqrt(n)), 2) if sd else None, "sum_pts": round(sum(xs)), "max_dd_pts": round(dd),
            "worst_pts": round(min(xs))}


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
        except Exception:  # noqa: BLE001  今日檔案寫緊
            continue
    pnl = json.loads(b.blob("futu/pnl/latest.json").download_as_bytes())
    bars = um.load(raw)
    dkeys, ctx = um.daily(bars)
    keys = day_keys(bars)
    idx = {bb[0]: i for i, bb in enumerate(bars)}

    entries = {"U": [], "A": []}
    from user_trades import round_trips
    import re
    seen = set()
    for tr in round_trips(pnl):
        if not re.match(r"^HK\.(HSI|MHI)\d{4}$", tr["code"]):
            continue
        t = tr["open_t"].replace(second=0, microsecond=0)
        if (t, tr["side"]) in seen or t not in idx:
            continue
        seen.add((t, tr["side"]))
        entries["U"].append((idx[t], tr["side"], tr["open_px"]))
    for name in ("longfei/HSI/latest.json", "longfei/real/MHI/latest.json"):
        for tr in json.loads(b.blob(name).download_as_bytes()).get("trades", []):
            if tr.get("type") != "OPEN":
                continue
            t = datetime.fromisoformat(tr["ts"]).replace(tzinfo=None, second=0, microsecond=0)
            j = next((k for k in range(len(bars)) if bars[k][0] >= t), None)
            if j is not None:
                entries["A"].append((j, tr["side"], tr["price"]))

    by_day = {}
    for i, (t, *_rest) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in WINDOWS):
            sd = um.session_date(t)
            x = ctx.get(sd)
            if x:
                by_day.setdefault(sd, []).append((i, 1 if x["pdc"] > x["sma"] else -1))

    res = {}
    for name in ("U", "A"):
        for mode in ("S", "D"):
            res[f"{name}_{mode}"] = stats([run(bars, keys, i, s, px, mode) for i, s, px in entries[name]])
    for mode in ("S", "D"):
        reps = []
        for seed in range(20):
            rnd = random.Random(seed)
            xs = []
            for sd in sorted(by_day):
                i, s = rnd.choice(by_day[sd])
                xs.append(run(bars, keys, i, s, bars[i][4], mode))
            reps.append(stats(xs))
        res[f"T_{mode}"] = {k: round(statistics.mean(r[k] for r in reps), 2) for k in ("n", "avg_pts", "win", "t", "sum_pts", "max_dd_pts", "worst_pts")}
        res[f"T_{mode}"]["avg_pts_range"] = [min(r["avg_pts"] for r in reps), max(r["avg_pts"] for r in reps)]

    lines = [f"# 🐉 MHI 波段出場（R299）歷史回測：{bars[0][0]:%Y-%m-%d} 至 {bars[-1][0]:%Y-%m-%d}", "",
             "恒指期貨 1 分鐘 K 線（含夜市）；每邊成本 2 點；點數 × HK$10 ＝ 每張 MHI 港幣。", "",
             "| 入場 | 出場 | 筆數 | 勝率 | 每筆平均（點） | 獲利因子 | t 值 | 合計（點） | 最大回撤（點） | 最差一筆（點） |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    names = {"U": "使用者入場", "T": "順日線隨機（20 次平均）", "A": "龍飛陣 AI 入場"}
    for k, s in res.items():
        e, m = k.split("_")
        lines.append(f"| {names[e]} | {'波段 S' if m == 'S' else '即日 D'} | {s.get('n')} | {s.get('win', 0):.0%} | "
                     f"{s.get('avg_pts')} | {s.get('pf', '—')} | {s.get('t')} | {s.get('sum_pts')} | {s.get('max_dd_pts')} | {s.get('worst_pts')} |")
    text = "\n".join(lines) + "\n"
    print(text)
    print(json.dumps(res, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
