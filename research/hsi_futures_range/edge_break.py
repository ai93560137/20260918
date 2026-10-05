"""投資人追問（2026-10-04）：碰到九成邊界如果會繼續走，那就跟着邊界的方向做（突破）。

規則（每個交易日 09:15 至翌日 03:00，只用當時已知數據；基準 = 昨收或 09:15 開市價）：
  上邊界 = 基準 + q 分位(u) × R̂、下邊界對稱；價格碰到上邊界就買（stop 單）、碰到下邊界就沽；一天每邊最多一次。
  止蝕：(r, 0.3) = 回到邊界內 0.3 × R̂；(mid) = 回到預測高（低）位（中位數）。
  離場：close 收市；1R／2R／3R 賺幾倍風險止賺；其餘收市平倉。
  成交：15 分 K 碰到邊界就成交（開市已越過用開市價；同一根碰到止蝕當止蝕）。
過濾（可疊加）：snake = 只做跟蛇蟠陣當時持倉同方向的突破；half = 只做上半日（09:15–16:30）發生的突破；
  nosig = 那一邊的「高位／低位已出現」訊號（A 或 B）已亮就不追（風揚陣頁的「不追」提示）。
用法：python3 research/hsi_futures_range/edge_break.py --json 15 分 K 快取 [--cost 3]
輸出：research/hsi_futures_range/edge_break/REPORT.md
"""
import argparse, csv, json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import band_limit as bl                                  # noqa: E402
import snake_band as sb                                  # noqa: E402

OUT = HERE / "edge_break"
EXITS = {"close": "收市平倉", "1R": "賺 1 倍風險", "2R": "賺 2 倍風險", "3R": "賺 3 倍風險"}
FILTERS = {"": "不過濾", "snake": "跟蛇方向", "half": "只上半日", "nosig": "訊號已亮不追", "snake+half": "跟蛇＋上半日", "snake+nosig": "跟蛇＋不追"}


def load_signals():
    out = defaultdict(dict)
    p = HERE / "r_sweep" / "futu" / "signals.csv"
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8")):
            k = (r["date"], r["side"])
            out[k][r["signal"]] = r["time_key"]
    return out


def trade(day, anchor, side, q_in, stop_spec, exit_rule, cost, flt, before, sigs):
    """side：'up' 向上突破買、'down' 向下突破沽。回傳 (淨點數, 風險, 原因) 或 None。"""
    R, ref, bars = day["rhat"], day["refs"][anchor], day["bars"]
    sign = 1 if side == "up" else -1
    ratios = day["ups" if side == "up" else "downs"][anchor]
    entry = ref + sign * bl.q(ratios, q_in) * R
    stop = entry - sign * (stop_spec[1] * R) if stop_spec[0] == "r" else ref + sign * bl.q(ratios, 0.5) * R
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    o = bars[0]["open"]
    if (side == "up" and o >= entry) or (side == "down" and o <= entry):
        return None                                      # 開市已在邊界外：沒有「碰到」的一刻，不做
    target = None if exit_rule == "close" else entry + sign * float(exit_rule[0]) * risk
    filled, px = False, None
    for b in bars:
        h, l = b["high"], b["low"]
        t = b["time_key"]
        if not filled:
            if not (h >= entry if side == "up" else l <= entry):
                continue
            if "half" in flt and not (t[:10] == day["date"] and t[11:16] <= "16:30"):
                return None
            if "snake" in flt and (before.get(t) or 0) != sign:
                return None
            if "nosig" in flt:
                s = sigs.get((day["date"], "high" if side == "up" else "low"), {})
                if any(v <= t for v in s.values()):
                    return None
            filled = True
            px = max(entry, b["open"]) if side == "up" else min(entry, b["open"])
            if (side == "up" and l <= stop) or (side == "down" and h >= stop):
                return sign * (stop - px) - cost, risk, "止蝕"
            if target is not None and ((h >= target) if side == "up" else (l <= target)):
                return sign * (target - px) - cost, risk, "止賺"
            continue
        if (side == "up" and b["open"] <= stop) or (side == "down" and b["open"] >= stop):
            return sign * (b["open"] - px) - cost, risk, "止蝕（跳空）"
        if (side == "up" and l <= stop) or (side == "down" and h >= stop):
            return sign * (stop - px) - cost, risk, "止蝕"
        if target is not None and ((h >= target) if side == "up" else (l <= target)):
            return sign * (target - px) - cost, risk, "止賺"
    if not filled:
        return None
    return sign * (bars[-1]["close"] - px) - cost, risk, "收市平倉"


def run(days, p, cost, before, sigs, sides=("up", "down")):
    out = []
    for d in days:
        for side in sides:
            r = trade(d, p[0], side, p[1], p[2], p[3], cost, p[4], before, sigs)
            if r:
                out.append((d["date"], side, *r))
    return out


def name(p):
    a, qi, st, ex, flt = p
    stop = f"止蝕 回內 {st[1]:g}R̂" if st[0] == "r" else "止蝕 回到預測位"
    return f"{bl.ANCHORS[a]}・{'九成邊' if qi == 0.9 else '九成半邊'}突破・{stop}・{EXITS[ex]}・{FILTERS[flt]}"


def grid():
    return [(a, qi, st, ex, flt) for a in bl.ANCHORS for qi in (0.9, 0.95) for st in (("r", 0.3), ("r", 0.5), ("mid", 0))
            for ex in EXITS for flt in FILTERS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True); ap.add_argument("--cost", type=float, default=3.0)
    a = ap.parse_args()
    cache = json.load(open(a.json))
    days0 = hl.build_days(cache["bars"], cache["daily"])
    before, _, _ = sb.snake_run(sb.snake_days(days0), a.cost)
    sigs = load_signals()
    days = bl.prepare(days0)
    half = len(days) // 2
    train, test = days[:half], days[half:]
    L = [f"# 碰到九成邊界就跟方向做（突破，edge_break.py）", "",
         f"- {len(days)} 個交易日（{days[0]['date']} 至 {days[-1]['date']}），訓練 {len(train)}／測試 {len(test)}；每筆成本 {a.cost:g} 點；上下兩邊合計", "",
         "## 一、全樣本：代表性設定", "", bl.HEAD]
    core = [("prev", 0.9, ("r", 0.3), "close", ""), ("prev", 0.9, ("r", 0.5), "close", ""), ("prev", 0.9, ("mid", 0), "close", ""),
            ("prev", 0.9, ("r", 0.3), "1R", ""), ("prev", 0.9, ("r", 0.3), "2R", ""), ("prev", 0.9, ("r", 0.3), "3R", ""),
            ("open", 0.9, ("r", 0.3), "close", ""), ("prev", 0.95, ("r", 0.3), "close", ""),
            ("prev", 0.9, ("r", 0.3), "close", "snake"), ("prev", 0.9, ("r", 0.3), "close", "half"), ("prev", 0.9, ("r", 0.3), "close", "nosig"),
            ("prev", 0.9, ("r", 0.3), "close", "snake+half"), ("prev", 0.9, ("r", 0.3), "close", "snake+nosig"),
            ("prev", 0.9, ("r", 0.3), "2R", "snake"), ("prev", 0.9, ("mid", 0), "close", "snake")]
    for p in core:
        L.append(f"| {name(p)} " + bl.fmt(bl.stats(run(days, p, a.cost, before, sigs), len(days))))
    res = sorted(((bl.stats(run(train, p, a.cost, before, sigs), len(train)).get("mean", -1e9), p) for p in grid()), reverse=True)
    L += ["", "## 二、前半段挑最好的 8 組 → 後半段", "", bl.HEAD]
    for m, p in res[:8]:
        L.append(f"| {name(p)}（訓練 {m:+.1f}） " + bl.fmt(bl.stats(run(test, p, a.cost, before, sigs), len(test))))
    L += ["", "## 三、逐年與分邊（昨收、九成邊、止蝕回內 0.3R̂、收市平倉；不過濾／跟蛇）", "", bl.HEAD]
    for flt in ("", "snake"):
        p = ("prev", 0.9, ("r", 0.3), "close", flt)
        for y in sorted({d["date"][:4] for d in days}):
            L.append(f"| {FILTERS[flt]} {y} " + bl.fmt(bl.stats(run([d for d in days if d["date"][:4] == y], p, a.cost, before, sigs), 1)))
        for side, zh in (("up", "只向上突破買"), ("down", "只向下突破沽")):
            L.append(f"| {FILTERS[flt]} {zh} " + bl.fmt(bl.stats(run(days, p, a.cost, before, sigs, (side,)), len(days))))
    OUT.mkdir(exist_ok=True)
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
