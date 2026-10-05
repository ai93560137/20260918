"""投資人問（2026-10-04）：既然當天範圍九成準，可否在九成邊界掛 limit sell／limit buy（反向等價）？

與 band_limit.py 的分別：那裡入市在「預測高／低位」（中位數），這裡入市在**九成（或九成半）範圍的邊界**本身——
價格十日只有約一日碰到，碰到就反向做，賭它「回到範圍內」。
規則（每個交易日 09:15 至翌日 03:00，只用當時已知數據；基準 = 昨收（開市前掛單）或 09:15 開市價）：
  沽：限價 = 基準 + q_入 分位(u) × R̂（q_入 0.90 = 九成邊、0.95 = 九成半邊）；買對稱。
  止蝕：(q, 0.98) = 更外的分位；(r, 0.3) = 入市價再外 0.3 × R̂（固定距離，避免分位尾巴太窄）。
  離場：close 收市；ref 回到基準；mid 回到預測高（低）位（中位數）；1R 賺 1 倍風險。
  成交：15 分 K 碰到限價就成交（開市已越過用開市價；同一根碰到止蝕當止蝕）；開市已越過止蝕不做。
另報：碰到邊界的日數比例、碰到之後收市在哪裡（繼續走 vs 回來）。
用法：python3 research/hsi_futures_range/edge_limit.py --json 15 分 K 快取 [--cost 3]
輸出：research/hsi_futures_range/edge_limit/REPORT.md
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import band_limit as bl                                  # noqa: E402

OUT = HERE / "edge_limit"
EXITS = {"close": "收市平倉", "ref": "回到基準價", "mid": "回到預測高（低）位", "1R": "賺 1 倍風險"}


def trade(day, anchor, side, q_in, stop_spec, exit_rule, cost):
    R, ref, bars = day["rhat"], day["refs"][anchor], day["bars"]
    ratios = day["ups" if side == "short" else "downs"][anchor]
    sign = -1 if side == "short" else 1
    entry = ref - sign * bl.q(ratios, q_in) * R
    stop = ref - sign * bl.q(ratios, stop_spec[1]) * R if stop_spec[0] == "q" else entry - sign * stop_spec[1] * R
    risk = abs(stop - entry)
    if risk <= 0:
        return None
    o = bars[0]["open"]
    if (side == "short" and o >= stop) or (side == "long" and o <= stop):
        return None
    target = {"close": None, "ref": ref, "mid": ref - sign * bl.q(ratios, 0.5) * R, "1R": entry + sign * risk}[exit_rule]
    filled, px = False, None
    for b in bars:
        h, l = b["high"], b["low"]
        if not filled:
            if not (h >= entry if side == "short" else l <= entry):
                continue
            filled = True
            px = max(entry, b["open"]) if side == "short" else min(entry, b["open"])
            if (side == "short" and h >= stop) or (side == "long" and l <= stop):
                return sign * (stop - px) - cost, risk, "止蝕", px
            continue
        if side == "short":
            if b["open"] >= stop:
                return sign * (b["open"] - px) - cost, risk, "止蝕（跳空）", px
            if h >= stop:
                return sign * (stop - px) - cost, risk, "止蝕", px
            if target is not None and l <= target:
                return sign * (target - px) - cost, risk, "止賺", px
        else:
            if b["open"] <= stop:
                return sign * (b["open"] - px) - cost, risk, "止蝕（跳空）", px
            if l <= stop:
                return sign * (stop - px) - cost, risk, "止蝕", px
            if target is not None and h >= target:
                return sign * (target - px) - cost, risk, "止賺", px
    if not filled:
        return None
    return sign * (bars[-1]["close"] - px) - cost, risk, "收市平倉", px


def run(days, p, cost, sides=("short", "long")):
    out = []
    for d in days:
        for side in sides:
            r = trade(d, p[0], side, p[1], p[2], p[3], cost)
            if r:
                out.append((d["date"], side, r[0], r[1], r[2]))
    return out


def touch_stats(days, anchor, q_in):
    """碰到邊界的日數比例，與碰到之後的去向（收市相對入市價、之後最多再走多遠）。"""
    rows = []
    for d in days:
        R, ref, bars = d["rhat"], d["refs"][anchor], d["bars"]
        for side in ("short", "long"):
            ratios = d["ups" if side == "short" else "downs"][anchor]
            sign = -1 if side == "short" else 1
            entry = ref - sign * bl.q(ratios, q_in) * R
            idx = next((i for i, b in enumerate(bars) if (b["high"] >= entry if side == "short" else b["low"] <= entry)), None)
            if idx is None:
                continue
            after = bars[idx:]
            beyond = (max(b["high"] for b in after) - entry) if side == "short" else (entry - min(b["low"] for b in after))
            close_gain = sign * (bars[-1]["close"] - entry)          # 反向做、收市平倉的毛利（點）
            rows.append({"date": d["date"], "side": side, "beyond_R": beyond / R, "close_gain": close_gain, "R": R,
                         "first_half": idx < len(bars) / 2})
    return rows


def name(p):
    a, qi, st, ex = p
    stop = f"止蝕 {st[1]:.0%} 分位" if st[0] == "q" else f"止蝕 再外 {st[1]:g}R̂"
    return f"{bl.ANCHORS[a]}・入市 {'九成邊' if qi == 0.9 else '九成半邊'}・{stop}・{EXITS[ex]}"


def grid():
    return [(a, qi, st, ex) for a in bl.ANCHORS for qi in (0.9, 0.95)
            for st in (("q", 0.98), ("r", 0.15), ("r", 0.3), ("r", 0.5)) for ex in EXITS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True); ap.add_argument("--cost", type=float, default=3.0)
    a = ap.parse_args()
    cache = json.load(open(a.json))
    days = bl.prepare(hl.build_days(cache["bars"], cache["daily"]))
    half = len(days) // 2
    train, test = days[:half], days[half:]
    L = [f"# 在九成邊界掛反向限價單（edge_limit.py）", "",
         f"- {len(days)} 個交易日（{days[0]['date']} 至 {days[-1]['date']}），訓練 {len(train)}／測試 {len(test)}；每筆成本 {a.cost:g} 點；沽、買兩邊合計", ""]
    L += ["## 一、碰到邊界的頻率與之後去向", "", "| 基準 | 邊界 | 碰到的日數（每邊平均） | 碰到後再走（中位數，R̂） | 再走 ≥ 0.3R̂ 的比例 | 收市回到邊界內（反向毛利 > 0）| 反向到收市毛利平均（點） | 上半日碰到的比例 |", "|---|---|---|---|---|---|---|---|"]
    for anc in bl.ANCHORS:
        for qi in (0.9, 0.95):
            rows = touch_stats(days, anc, qi)
            b = np.array([r["beyond_R"] for r in rows]); g = np.array([r["close_gain"] for r in rows])
            L.append(f"| {bl.ANCHORS[anc]} | {'九成' if qi == 0.9 else '九成半'} | {len(rows) / 2 / len(days):.1%} | {np.median(b):.2f} | {(b >= 0.3).mean():.0%} | "
                     f"{(g > 0).mean():.0%} | {g.mean():+.1f} | {np.mean([r['first_half'] for r in rows]):.0%} |")
    L += ["", "## 二、全樣本：代表性設定", "", bl.HEAD]
    core = [("prev", 0.9, ("q", 0.98), "close"), ("prev", 0.9, ("r", 0.3), "close"), ("prev", 0.9, ("r", 0.3), "mid"), ("prev", 0.9, ("r", 0.3), "ref"),
            ("prev", 0.9, ("r", 0.5), "mid"), ("prev", 0.95, ("r", 0.3), "mid"), ("open", 0.9, ("r", 0.3), "mid"), ("open", 0.9, ("r", 0.3), "close"),
            ("prev", 0.9, ("r", 0.15), "1R"), ("prev", 0.9, ("r", 0.3), "1R")]
    for p in core:
        L.append(f"| {name(p)} " + bl.fmt(bl.stats(run(days, p, a.cost), len(days))))
    res = sorted(((bl.stats(run(train, p, a.cost), len(train)).get("mean", -1e9), p) for p in grid()), reverse=True)
    L += ["", "## 三、前半段挑最好的 6 組 → 後半段", "", bl.HEAD]
    for m, p in res[:6]:
        L.append(f"| {name(p)}（訓練 {m:+.1f}） " + bl.fmt(bl.stats(run(test, p, a.cost), len(test))))
    L += ["", "## 四、逐年與分邊（基準昨收、九成邊、止蝕再外 0.3R̂、回到預測位）", "", bl.HEAD]
    p = ("prev", 0.9, ("r", 0.3), "mid")
    for y in sorted({d["date"][:4] for d in days}):
        L.append(f"| {y} " + bl.fmt(bl.stats(run([d for d in days if d["date"][:4] == y], p, a.cost), 1)))
    for side, zh in (("short", "只沽（上邊界）"), ("long", "只買（下邊界）")):
        L.append(f"| {zh} " + bl.fmt(bl.stats(run(days, p, a.cost, (side,)), len(days))))
    OUT.mkdir(exist_ok=True)
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
