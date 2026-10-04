"""方向二：「波幅走完／頂底已現」之後反向做，賺不賺錢？（盈虧回測）

規則（每段每邊最多一筆，用 high_low_in.py 同一套逐日前推的數據與訊號）：
  訊號在某根 15 分 K 收市時出現 → 下一根開市價進場：
    高位已出現 → 沽空；低位已出現 → 買入。
  止蝕：這段時間的極值（高位／低位）再加 b × R̂_段；K 線開市已跳過止蝕價 → 用開市價成交。
  止賺（可選）：從進場價走 t × R̂_段。同一根 K 線碰到止蝕和止賺 → 當作先止蝕（保守）。
  其餘在這段時間最後一根 K 線收市平倉（交易日 = 翌日 03:00 夜市收市；週 = 週五夜市收市）。
  成本：每筆來回 COST 點（手續費＋滑價，預設 3 點）。恒指期貨每點 HK$50，小型恒指每點 HK$10。

訊號：
  A 耗盡回落、B 機率法、C 時間點（high_low_in.py 的定義）；
  E 走完即反向：已走 ≥ k × R̂_段，價格在靠近哪一邊（距極值 ≤ 0.1 R̂）就反向做那邊。沒有「回落」確認。
基準：同一段、同一邊，在訊號的中位時間無條件進場（止蝕、平倉規則相同）——用來分開「訊號的功勞」與「時間／趨勢的功勞」。

參數在前半段挑（交易 ≥ 30 筆中每筆平均淨利最高），後半段報成績；線上用的參數另外列出全樣本與後半段。

用法：python3 research/hsi_futures_range/fade_pnl.py [--json 快取] [--cost 3] [--periods day,week]
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import high_low_in as hl                                 # noqa: E402

COST = 3.0
LIVE = {"day": [("A", 0.8, 0.5), ("B", 0.05), ("C", "16:30", 0.4)],
        "week": [("A", 0.8, 0.5), ("B", 0.05), ("C", 4, 0.4)]}


_MEMO = {}


def signal(period, strat, side):
    """回傳訊號那根 K 線的序號（沒有訊號 → None）。同一段同一策略只算一次。"""
    key = (period["kind"], period["key"], strat, side)
    if key not in _MEMO:
        _MEMO[key] = _signal(period, strat, side)
    return _MEMO[key]


def _signal(period, strat, side):
    if strat[0] != "E":
        idx, _, _ = hl.run_period(period, strat, side)
        return idx
    hs, ls, R = -math.inf, math.inf, period["R"]
    for idx, (b, _) in enumerate(period["bars"]):
        hs, ls = max(hs, b["high"]), min(ls, b["low"])
        if hs - ls >= strat[1] * R:
            near = (hs - b["close"]) if side == "high" else (b["close"] - ls)
            return idx if near <= 0.1 * R else None
    return None


def trade(period, idx, side, stop_k, target_k, cost):
    """idx：訊號 K 線；下一根開市進場。回傳 (淨點數, 出場原因) 或 None（之後沒有 K 線）。"""
    bars, R = period["bars"], period["R"]
    if idx is None or idx + 1 >= len(bars):
        return None
    sign = -1 if side == "high" else 1                          # 高位已現 → 沽空
    ext = max(b["high"] for b, _ in bars[:idx + 1]) if side == "high" else min(b["low"] for b, _ in bars[:idx + 1])
    entry = bars[idx + 1][0]["open"]
    stop = ext + stop_k * R if side == "high" else ext - stop_k * R
    target = None if target_k is None else entry + sign * target_k * R
    for b, _ in bars[idx + 1:]:
        o, h, l = b["open"], b["high"], b["low"]
        if side == "high":
            if o >= stop:
                return sign * (o - entry) - cost, "止蝕（跳空）"
            if h >= stop:
                return sign * (stop - entry) - cost, "止蝕"
            if target is not None and l <= target:
                return sign * (target - entry) - cost, "止賺"
        else:
            if o <= stop:
                return sign * (o - entry) - cost, "止蝕（跳空）"
            if l <= stop:
                return sign * (stop - entry) - cost, "止蝕"
            if target is not None and h >= target:
                return sign * (target - entry) - cost, "止賺"
    return sign * (bars[-1][0]["close"] - entry) - cost, "到期平倉"


def stats(pnls):
    a = np.array(pnls, dtype=float)
    if not len(a):
        return {"n": 0}
    eq = np.cumsum(a)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq)) if len(a) else 0.0
    sd = float(a.std(ddof=1)) if len(a) > 1 else float("nan")
    gains, losses = a[a > 0].sum(), -a[a < 0].sum()
    return {"n": len(a), "mean": float(a.mean()), "median": float(np.median(a)), "win": float((a > 0).mean()),
            "total": float(a.sum()), "t": float(a.mean() / sd * math.sqrt(len(a))) if sd and sd > 0 else float("nan"),
            "pf": float(gains / losses) if losses > 0 else float("inf"), "dd": dd}


def run(periods, strat, side, stop_k, target_k, cost):
    out = []
    for per in periods:
        r = trade(per, signal(per, strat, side), side, stop_k, target_k, cost)
        if r:
            out.append((per["key"], r[0], r[1]))
    return out


def baseline(periods, side, at_frac, stop_k, target_k, cost):
    """無條件：在這段 K 線的 at_frac 位置進場（訊號中位時間的位置）。"""
    out = []
    for per in periods:
        idx = min(len(per["bars"]) - 2, max(0, int(round(at_frac * len(per["bars"]))) - 1))
        r = trade(per, idx, side, stop_k, target_k, cost)
        if r:
            out.append((per["key"], r[0], r[1]))
    return out


def grid(kind):
    a = [("A", al, be) for al in (0.6, 0.8, 1.0) for be in (0.3, 0.5)]
    b = [("B", p) for p in (0.05, 0.10, 0.20)]
    c = [("C", cut, be) for cut in ({"day": ("12:00", "16:30"), "week": (2, 3, 4)}[kind]) for be in (0.2, 0.4)]
    e = [("E", k) for k in (0.8, 1.0, 1.2)]
    exits = [(sk, tk) for sk in (0.0, 0.1, 0.25) for tk in (None, 0.25, 0.5)]
    return [(s, sk, tk) for s in a + b + c + e for sk, tk in exits]


def name(strat, kind):
    return f"E 已走≥{strat[1]}R̂ 即反向" if strat[0] == "E" else hl.name(strat, kind)


def exit_name(sk, tk):
    return f"止蝕＝極值{'+' + str(sk) + 'R̂' if sk else ''}" + (f"、止賺 {tk}R̂" if tk else "、不設止賺")


def fmt(s):
    if not s.get("n"):
        return "| 0 | — | — | — | — | — | — |"
    return (f"| {s['n']} | {s['win']:.0%} | **{s['mean']:+.1f}** | {s['median']:+.0f} | {s['t']:+.2f} | "
            f"{s['pf']:.2f} | {s['total']:+,.0f}／{s['dd']:,.0f} |")


HEAD = ("| 策略 | 出場 | 交易數 | 勝率 | **每筆平均淨利（點）** | 中位 | t 值 | 盈虧比 | 總點數／最大回撤 |\n"
        "|---|---|---|---|---|---|---|---|---|")


def signal_frac(periods, strat, side):
    fr = [signal(p, strat, side) / len(p["bars"]) for p in periods if signal(p, strat, side) is not None]
    return float(np.median(fr)) if fr else 0.5


def report(periods, kind, cost):
    half = len(periods) // 2
    train, test = periods[:half], periods[half:]
    lines = [f"\n### {hl.PERIOD_ZH[kind]}：{len(periods)} 段（{periods[0]['key']} 至 {periods[-1]['key']}），"
             f"訓練 {len(train)}／測試 {len(test)}，成本每筆 {cost:g} 點"]
    summary = {}
    for side in ("high", "low"):
        zh, act = ("高位", "沽空") if side == "high" else ("低位", "買入")
        res = []
        for s, sk, tk in grid(kind):
            st = stats([p for _, p, _ in run(train, s, side, sk, tk, cost)])
            if st["n"] >= (30 if kind == "day" else 12):
                res.append((st["mean"], s, sk, tk, st))
        res.sort(key=lambda x: -x[0])
        lines.append(f"\n**{zh}已現 → {act}**（前半段挑出最好的 3 組，後半段成績；括號是訓練期每筆平均）\n")
        lines.append(HEAD)
        picks = []
        for _, s, sk, tk, tr in res[:3]:
            te = stats([p for _, p, _ in run(test, s, side, sk, tk, cost)])
            base = stats([p for _, p, _ in baseline(test, side, signal_frac(train, s, side), sk, tk, cost)])
            picks.append({"strat": s, "stop": sk, "target": tk, "train": tr, "test": te, "base": base})
            lines.append(f"| {name(s, kind)}（訓練 {tr['mean']:+.1f}） | {exit_name(sk, tk)} " + fmt(te))
            lines.append(f"| ↳ 基準：同時間無條件{act} | 同上 " + fmt(base))
        lines.append(f"\n線上參數（止蝕＝極值、不設止賺）：全樣本／後半段\n")
        lines.append(HEAD)
        live = []
        for s in LIVE[kind]:
            full = stats([p for _, p, _ in run(periods, s, side, 0.0, None, cost)])
            te = stats([p for _, p, _ in run(test, s, side, 0.0, None, cost)])
            live.append({"strat": s, "full": full, "test": te})
            lines.append(f"| {name(s, kind)}（全樣本） | 極值止蝕 " + fmt(full))
            lines.append(f"| {name(s, kind)}（後半段） | 極值止蝕 " + fmt(te))
        summary[side] = {"picks": picks, "live": live}
    return "\n".join(lines), summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="本地快取 {bars, daily}（high_low_in.py 同格式）；沒有就從 GCS 讀")
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--periods", default="day,week")
    ap.add_argument("--out", help="把摘要另存成 JSON")
    a = ap.parse_args()
    if a.json and Path(a.json).exists():
        cache = json.load(open(a.json))
        bars, daily = cache["bars"], cache["daily"]
    else:
        bars, daily = hl.load_gcs("K_15M")
        if a.json:
            json.dump({"bars": bars, "daily": daily}, open(a.json, "w"))
    days = hl.build_days(bars, daily)
    print(f"K_15M：{len(days)} 個交易日（{days[0]['date']} 至 {days[-1]['date']}）")
    out = {}
    for kind in a.periods.split(","):
        text, out[kind] = report(hl.build_periods(days, kind), kind, a.cost)
        print(text)
    if a.out:
        json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()
