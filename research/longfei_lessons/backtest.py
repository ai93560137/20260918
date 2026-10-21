"""[R268] 龍飛陣教學研究：用歷史 15 分鐘 K 線測試覆盤提出嘅幾個問題（唔係交易策略，係檢驗教學方向）。

使用者 10-21：「可唔可以利用現有數據做回測？另外加上我富途賺錢嘅交易，睇吓有咩結果可以寫喺教學入面。」

基本入場（開市區間突破，同 AI 常用嘅入場理由最接近）：
- 開市區間（OR）＝ 頭 30 分鐘（HSI 09:15–09:45；美股 09:30–10:00）高低位。
- 之後第一支 15 分鐘 K 線收市升穿 OR 高 → 做好；跌穿 OR 低 → 做淡（每日每方向最多一次）。
- 止蝕：OR 另一邊（風險 R＝入場價到止蝕距離；最少 HSI 30 點、美股 0.15%）；止賺 2R；收市前最後一支平倉。
- 成本：每邊 HSI 1.5 點、美股指數 0.015%（ETF 買賣差＋佣金近似）。

逐個問題分組比較（每筆以 R 計，扣成本）：
Q1 沽空：日線跌勢（收市 < 20 日均線）同當日走勢一致 vs 唔一致
Q2 開倉時間：上午 vs 下午（美股 12:00 ET 後；HSI 13:00 後）
Q3 追昨日高低位：突破時同時升穿昨日高位（做好）／跌穿昨日低位（做淡） vs 未過
Q4 「單靠日線方向」入場：開市即按日線方向開倉（唔理當日走勢），對照 OR 突破
Q5 移動止蝕：去到 1R 後止蝕移到開倉價 vs 唔移

用法：python3 research/longfei_lessons/backtest.py --hsi <hsi_15m.json> --spx <usa500…gz> --ndx <usatech…gz> --out 報告.md
"""
import argparse
import math
import os
import sys
from datetime import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bars import load_dukascopy, load_hsi  # noqa: E402

MARKETS = {
    # 名、OR 完結、下午開始、最後開倉、成本函數（每邊，價格單位）、最少止蝕距離（太近嘅止蝕會令成本變成幾個 R）
    "HSI": {"or_end": time(9, 45), "pm": time(13, 0), "last_entry": time(16, 0), "cost": lambda px: 1.5,
            "min_risk": lambda px: 30.0},
    "SPX": {"or_end": time(10, 0), "pm": time(12, 0), "last_entry": time(15, 30), "cost": lambda px: px * 0.00015,
            "min_risk": lambda px: px * 0.0015},
    "NDX": {"or_end": time(10, 0), "pm": time(12, 0), "last_entry": time(15, 30), "cost": lambda px: px * 0.00015,
            "min_risk": lambda px: px * 0.0015},
}


def daily_context(days):
    """每日：昨日高低收、20 日均線（用昨日及之前收市）。"""
    keys = sorted(days)
    ctx, closes = {}, []
    for i, d in enumerate(keys):
        if i and len(closes) >= 20:
            prev = days[keys[i - 1]]
            ctx[d] = {"pdh": max(b[2] for b in prev), "pdl": min(b[3] for b in prev), "pdc": prev[-1][4],
                      "sma20": sum(closes[-20:]) / 20}
        closes.append(days[d][-1][4])
    return ctx


def run_trade(bars, i, side, entry, stop, cost, be_at=None, min_risk=0.0):
    """由第 i+1 支 K 線開始管理；回傳 R（扣成本）。be_at：去到幾多 R 就移止蝕去開倉價。"""
    if abs(entry - stop) < min_risk:
        stop = entry - side * min_risk
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = entry + side * 2 * risk
    cur_stop, moved = stop, False
    for b in bars[i + 1:]:
        _, o, h, lo, c = b
        hit_stop = (lo <= cur_stop) if side > 0 else (h >= cur_stop)
        hit_tgt = (h >= target) if side > 0 else (lo <= target)
        if hit_stop:                          # 同一支 K 線兩樣都中，保守當止蝕
            exit_px = cur_stop
            break
        if hit_tgt:
            exit_px = target
            break
        if be_at and not moved and (c - entry) * side >= be_at * risk:
            cur_stop, moved = entry, True
    else:
        exit_px = bars[-1][4]
    return ((exit_px - entry) * side - 2 * cost) / risk


def or_trades(days, mk, be_at=None):
    ctx = daily_context(days)
    out = []
    for d, bars in days.items():
        if d not in ctx:
            continue
        c = ctx[d]
        orb = [b for b in bars if b[0].time() < mk["or_end"]]
        if len(orb) < 2:
            continue
        hi, lo = max(b[2] for b in orb), min(b[3] for b in orb)
        day_open = bars[0][1]
        trend = 1 if c["pdc"] > c["sma20"] else -1
        done = set()
        for i, b in enumerate(bars):
            t = b[0].time()
            if t < mk["or_end"] or t >= mk["last_entry"]:
                continue
            close = b[4]
            for side, cond, stop in ((1, close > hi, lo), (-1, close < lo, hi)):
                if side in done or not cond:
                    continue
                done.add(side)
                r = run_trade(bars, i, side, close, stop, mk["cost"](close), be_at, mk["min_risk"](close))
                if r is None:
                    continue
                out.append({"day": d, "side": side, "r": r, "pm": t >= mk["pm"],
                            "with_daily": side == trend,
                            "beyond_prev": (close > c["pdh"]) if side > 0 else (close < c["pdl"]),
                            "intraday_up": close > day_open})
    return out


def daily_only_trades(days, mk):
    """Q4：OR 完結即按日線方向開倉，止蝕＝OR 另一邊，唔理當日走勢。"""
    ctx = daily_context(days)
    out = []
    for d, bars in days.items():
        if d not in ctx:
            continue
        c = ctx[d]
        idx = [i for i, b in enumerate(bars) if b[0].time() < mk["or_end"]]
        if len(idx) < 2:
            continue
        i = idx[-1]
        hi, lo = max(bars[j][2] for j in idx), min(bars[j][3] for j in idx)
        side = 1 if c["pdc"] > c["sma20"] else -1
        entry = bars[i][4]
        stop = lo if side > 0 else hi
        r = run_trade(bars, i, side, entry, stop, mk["cost"](entry), min_risk=mk["min_risk"](entry))
        if r is not None:
            out.append({"day": d, "side": side, "r": r,
                        "against_intraday": (entry < bars[0][1]) if side > 0 else (entry > bars[0][1])})
    return out


def stats(rs):
    n = len(rs)
    if not n:
        return None
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1)) if n > 1 else 0
    wins, losses = [x for x in rs if x > 0], [-x for x in rs if x < 0]
    return {"n": n, "avg": m, "t": m / (sd / math.sqrt(n)) if sd else None, "win": len(wins) / n,
            "pf": sum(wins) / sum(losses) if losses else None}


def row(name, rs):
    s = stats(rs)
    if not s:
        return f"| {name} | 0 | — | — | — | — |"
    pf = "—" if s["pf"] is None else f"{s['pf']:.2f}"
    t = "—" if s["t"] is None else f"{s['t']:.2f}"
    return f"| {name} | {s['n']} | {s['win']:.0%} | {s['avg']:+.3f}R | {pf} | {t} |"


def halves(trades):
    trades = sorted(trades, key=lambda x: x["day"])
    h = len(trades) // 2
    return [x["r"] for x in trades[:h]], [x["r"] for x in trades[h:]]


def section(title, groups):
    L = [f"\n#### {title}\n", "| 分組 | 筆數 | 勝率 | 每筆平均 | 獲利因子 | t 值 |", "|---|---:|---:|---:|---:|---:|"]
    L += [row(name, rs) for name, rs in groups]
    return L


def report(markets):
    L = ["# 🐉 龍飛陣教學研究：歷史回測（R268）\n",
         "開市區間（頭 30 分鐘）突破做基本入場，止蝕 OR 另一邊（最少 HSI 30 點／美股 0.15%）、止賺 2R、收市前平倉，扣成本；每筆以 R 計。"
         "目的係檢驗覆盤提出嘅教學方向，唔係揀策略參數。15 分鐘 K 線，同一支 K 線止蝕止賺都中當止蝕（保守）。\n"]
    for name, (days, mk) in markets.items():
        tr = or_trades(days, mk)
        be = or_trades(days, mk, be_at=1.0)
        dl = daily_only_trades(days, mk)
        span = f"{min(days)} 至 {max(days)}，{len(days)} 個交易日"
        L.append(f"\n## {name}（{span}）")
        first, second = halves(tr)
        L += section("全部（基本入場）", [("全部", [x["r"] for x in tr]), ("做好", [x["r"] for x in tr if x["side"] > 0]),
                                         ("做淡", [x["r"] for x in tr if x["side"] < 0]),
                                         ("前一半（時間）", first), ("後一半（時間）", second)])
        sh = [x for x in tr if x["side"] < 0]
        lg = [x for x in tr if x["side"] > 0]
        L += section("Q1 沽空：日線方向同當日突破一致 vs 唔一致",
                     [("沽空，日線都係跌勢", [x["r"] for x in sh if x["with_daily"]]),
                      ("沽空，日線係升勢（逆日線）", [x["r"] for x in sh if not x["with_daily"]]),
                      ("做好，日線都係升勢", [x["r"] for x in lg if x["with_daily"]]),
                      ("做好，日線係跌勢（逆日線）", [x["r"] for x in lg if not x["with_daily"]])])
        L += section("Q2 開倉時間", [("上午", [x["r"] for x in tr if not x["pm"]]), ("下午", [x["r"] for x in tr if x["pm"]]),
                                    ("下午・做好", [x["r"] for x in lg if x["pm"]]), ("下午・做淡", [x["r"] for x in sh if x["pm"]])])
        L += section("Q3 突破時同時過埋昨日高位（做好）／昨日低位（做淡）",
                     [("做好・過埋昨日高位", [x["r"] for x in lg if x["beyond_prev"]]),
                      ("做好・未過昨日高位", [x["r"] for x in lg if not x["beyond_prev"]]),
                      ("做淡・跌穿埋昨日低位", [x["r"] for x in sh if x["beyond_prev"]]),
                      ("做淡・未穿昨日低位", [x["r"] for x in sh if not x["beyond_prev"]])])
        L += section("Q4 單靠日線方向開倉（OR 完結即入，唔等當日突破）",
                     [("全部", [x["r"] for x in dl]),
                      ("逆當日走勢（日線跌但當日高開／企喺開市價上面）", [x["r"] for x in dl if x["against_intraday"]]),
                      ("順當日走勢", [x["r"] for x in dl if not x["against_intraday"]]),
                      ("只計沽空・逆當日走勢", [x["r"] for x in dl if x["side"] < 0 and x["against_intraday"]])])
        L += section("Q5 移動止蝕：去到 1R 就移止蝕去開倉價", [("唔移（基本）", [x["r"] for x in tr]),
                                                         ("1R 移去開倉價", [x["r"] for x in be])])
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hsi")
    ap.add_argument("--spx")
    ap.add_argument("--ndx")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    markets = {}
    if a.hsi:
        markets["HSI 恒指期貨"] = (load_hsi(a.hsi), MARKETS["HSI"])
    if a.spx:
        markets["標普 500（Dukascopy 指數 CFD）"] = (load_dukascopy(a.spx), MARKETS["SPX"])
    if a.ndx:
        markets["納指 100（Dukascopy 指數 CFD）"] = (load_dukascopy(a.ndx), MARKETS["NDX"])
    text = report(markets)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
