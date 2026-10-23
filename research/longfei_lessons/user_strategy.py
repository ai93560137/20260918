"""[R285] 使用者成功模式變策略：「日線跌勢 + 當日向下 → 沽空恒指，揸到移動止蝕或者最多 3 日」。

使用者 10-22：「嘗試分析我過去咁多贏錢嘅倉位，將佢變成一個策略。」
來源：使用者富途 HSI／MHI 期貨成交（2026-06 至 10，時區已更正）：日線跌勢 + 當日向下沽空 34 筆、獲利因子 5.1；
當日向上都沽空 28 筆、0.33；做好 29 筆、0.05。最大贏單係順勢沽空揸 1–3 日。

規則（IDEAS #117 預先登記；只用 HSI 日市 15 分鐘 K 線，2023-09 至 2026-10）：
- 日線跌勢：昨日收市 < 20 日均線。
- 當日向下：開市區間（09:15–09:45）之後，第一支 15 分鐘 K 線收市同時低過今日開市價同開市區間低位 → 收市價沽空（每日最多一次；已有倉唔再開）。
- 止蝕：開市區間高位（最少離入場 0.3 × ATR14）。風險 R＝入場到止蝕。
- 移動止蝕：浮賺 ≥ 1R 之後，止蝕移到「最近 4 支 K 線最高位」同開倉價之間較低者（只收緊）。
- 可以過夜：最多揸到第 3 個交易日收市；冇止蝕就收市平。過夜用下一日開市價（跳空照計）。
- 成本：每邊 2 點。
對照組：(a) 唔理日線（只要當日向下）(b) 即日平倉（唔過夜）(c) 鏡像做好（日線升勢 + 當日向上）。

用法：python3 research/longfei_lessons/user_strategy.py --hsi hsi_15m.json --period is|oos|all [--out 報告.md]
樣本內（is）＝ 頭一半交易日；樣本外（oos）＝ 後一半，只喺登記之後跑一次。
"""
import argparse
import math
import os
import sys
from datetime import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bars import load_hsi  # noqa: E402

OR_END = time(9, 45)
COST = 2.0
MAX_DAYS = 3
TRAIL_BARS = 4


def context(days):
    keys = sorted(days)
    out = {}
    for i, d in enumerate(keys):
        if i < 20:
            continue
        prev = [days[k] for k in keys[i - 20:i]]
        sma = sum(b[-1][4] for b in prev) / 20
        atr = sum(max(x[2] for x in b) - min(x[3] for x in b) for b in prev[-14:]) / 14
        out[d] = {"pdc": prev[-1][-1][4], "sma": sma, "atr": atr}
    return keys, out


def run(days, side=-1, need_trend=True, overnight=True):
    """side −1＝沽空（日線跌勢＋當日向下）；+1＝鏡像做好。回傳每筆 {day, r, pts, days_held}。"""
    keys, ctx = context(days)
    trades, i = [], 0
    while i < len(keys):
        d = keys[i]
        c = ctx.get(d)
        bars = days[d]
        if not c:
            i += 1
            continue
        if need_trend and (c["pdc"] - c["sma"]) * side > 0:      # 沽空要日線跌勢；做好要升勢
            i += 1
            continue
        orb = [b for b in bars if b[0].time() < OR_END]
        if len(orb) < 2:
            i += 1
            continue
        hi, lo, day_open = max(b[2] for b in orb), min(b[3] for b in orb), bars[0][1]
        entry_idx = None
        for j, b in enumerate(bars):
            if b[0].time() < OR_END:
                continue
            close = b[4]
            if (side < 0 and close < day_open and close < lo) or (side > 0 and close > day_open and close > hi):
                entry_idx = j
                break
        if entry_idx is None:
            i += 1
            continue
        entry = bars[entry_idx][4]
        stop = hi if side < 0 else lo
        if abs(entry - stop) < 0.3 * c["atr"]:
            stop = entry - side * 0.3 * c["atr"]
        risk = abs(entry - stop)
        path = bars[entry_idx + 1:]
        held, k = 1, i
        last_days = min(len(keys) - 1, i + (MAX_DAYS - 1 if overnight else 0))
        while k < last_days:
            k += 1
            path = path + days[keys[k]]
        exit_px, recent = None, list(bars[max(0, entry_idx - TRAIL_BARS + 1):entry_idx + 1])
        for b in path:
            _, o, h, l, cl = b
            if (side < 0 and h >= stop) or (side > 0 and l <= stop):
                exit_px = max(stop, o) if side < 0 else min(stop, o)        # 跳空過止蝕就用開市價
                break
            recent = (recent + [b])[-TRAIL_BARS:]
            if (cl - entry) * side >= risk:                                   # 浮賺 ≥ 1R 先開始移動止蝕
                trail = max(x[2] for x in recent) if side < 0 else min(x[3] for x in recent)
                new = min(trail, entry) if side < 0 else max(trail, entry)
                stop = min(stop, new) if side < 0 else max(stop, new)
        if exit_px is None:
            exit_px = path[-1][4] if path else entry
        pts = (exit_px - entry) * side - 2 * COST
        trades.append({"day": d, "r": pts / risk, "pts": pts, "days_held": k - i + 1})
        i = k + 1                                                       # 有倉期間唔再開
    return trades


def stats(tr):
    rs = [t["r"] for t in tr]
    n = len(rs)
    if n < 2:
        return {"n": n}
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1))
    w, l = [x for x in rs if x > 0], [-x for x in rs if x < 0]
    pts = [t["pts"] for t in tr]
    return {"n": n, "win": len(w) / n, "avg": m, "pf": sum(w) / sum(l) if l else None, "t": m / (sd / math.sqrt(n)) if sd else None,
            "pts": sum(pts), "pts_avg": sum(pts) / n}


def row(name, tr):
    s = stats(tr)
    if s["n"] < 2:
        return f"| {name} | {s['n']} | — | — | — | — | — |"
    pf = "—" if s["pf"] is None else f"{s['pf']:.2f}"
    return (f"| {name} | {s['n']} | {s['win']:.0%} | {s['avg']:+.3f}R | {pf} | {s['t']:.2f} | "
            f"{s['pts_avg']:+.0f} 點（合計 {s['pts']:+,.0f}） |")


def split(days, period):
    keys = sorted(days)
    h = len(keys) // 2
    pick = keys[:h] if period == "is" else keys[h - 25:] if period == "oos" else keys   # oos 前面多 25 日做均線熱身
    sub = {k: days[k] for k in pick}
    return sub, (pick[0] if period != "oos" else keys[h]), pick[-1]


def report(days, period):
    sub, start, end = split(days, period)
    keep = lambda tr: [t for t in tr if t["day"] >= start]
    L = [f"# 🐉 使用者順勢沽空策略回測（R285，{ {'is': '樣本內', 'oos': '樣本外', 'all': '全部'}[period] }：{start} 至 {end}）\n",
         "恒指期貨日市 15 分鐘 K 線；每邊成本 2 點；R＝入場到初始止蝕。\n",
         "| 版本 | 筆數 | 勝率 | 每筆平均 | 獲利因子 | t 值 | 每筆點數（扣成本） |", "|---|---:|---:|---:|---:|---:|---:|",
         row("主策略：日線跌勢＋當日向下沽空，可揸 3 日", keep(run(sub))),
         row("對照 a：唔理日線", keep(run(sub, need_trend=False))),
         row("對照 b：即日平倉（唔過夜）", keep(run(sub, overnight=False))),
         row("對照 c：鏡像做好（日線升勢＋當日向上）", keep(run(sub, side=1)))]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hsi", required=True)
    ap.add_argument("--period", choices=("is", "oos", "all"), default="is")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    text = report(load_hsi(a.hsi), a.period)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
