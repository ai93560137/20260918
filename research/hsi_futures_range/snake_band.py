"""蛇蟠陣定方向 ＋ 風揚陣定入市位與止蝕：盈虧回測（期望值、RRR、盈虧比…）

用戶規則：
  蛇蟠陣當時做多 → 在風揚陣「預測低位」掛買單，跌破低位預計範圍下限就止蝕；
  蛇蟠陣當時做空 → 在「預測高位」掛沽單，升破高位預計範圍上限就止蝕。

蛇蟠陣（SNAKE_COIL_SPEC.md，分支 claude/gifted-carson-v2tvhw）：前 3 個完整交易日通道觸價反手（Donchian N=3 SAR）。
  通道 = 前 3 個「蛇日」的最高／最低；蛇日按富途日界：夜市（17:15–03:00）屬下一個交易日，日市 16:30 收市即完結。
  觸價（停損單）成交，跳空用開市價；永遠在場；每個蛇日每個方向最多進場一次。
  這裡用風揚陣同一條 15 分 K（即月連續、轉月不調整）重建蛇蟠陣每一刻的持倉——轉月日的跳空可能令少數反手跟
  TradingView HSI1! 不同。

風揚陣（同 band_limit.py）：交易日 09:15 至翌日 03:00；R̂ = 逐日前推 HAR；高／低位比例取之前 ≥ 120 天的分位。
  09:15 讀蛇蟠陣當時的持倉決定方向（之後蛇反手也不改方向；flip 選項＝蛇反手就跟著平倉）。
  入市價 = 基準 ± q_入 分位 × R̂（基準：昨收＝開市前掛單／開市價＝09:15 後掛單）；止蝕 = 範圍外邊（q_止 0.90＝八成、0.95＝九成）。
  離場：close 收市（翌日 03:00）；opp 去到另一邊的預測位（做多去預測高位）；1R／2R 賺到 1／2 倍風險；其餘收市平倉。
  同一根 K 線碰到入市又碰到止蝕 → 當作止蝕（保守）；開市已越過止蝕 → 當天不做。
成本：每筆來回 COST 點（蛇蟠陣規格：佣金 HK$55／邊 ≈ 2.2 點，加滑價）。恒指每點 HK$50，小型恒指 HK$10。
基準對照：同方向 09:15 開市價直接入市（看「等到預測位才入」有沒有幫助）；反方向（看蛇的方向有沒有用）；不分方向兩邊都做；蛇蟠陣本身。

用法：python3 research/hsi_futures_range/snake_band.py [--json 15 分 K 快取] [--cost 3]
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import high_low_in as hl                                 # noqa: E402
import band_limit as bl                                  # noqa: E402

COST = 3.0
LOOKBACK = 3


# ---- 蛇蟠陣 ---------------------------------------------------------------------
def snake_days(days):
    """風揚陣交易日 → 蛇日：日市（09:00–16:59）屬當天；夜市屬下一個交易日。回傳 [(蛇日, [K 線])]。"""
    out = {}
    for i, d in enumerate(days):
        for b in d["bars"]:
            hhmm = b["time_key"][11:16]
            if b["time_key"][:10] == d["date"] and "09:00" <= hhmm < "17:00":
                key = d["date"]
            elif i + 1 < len(days):
                key = days[i + 1]["date"]
            else:
                continue
            out.setdefault(key, []).append(b)
    return [(k, sorted(v, key=lambda b: b["time_key"])) for k, v in sorted(out.items())]


def snake_run(sdays, cost):
    """逐根 K 線模擬蛇蟠陣。回傳 (before：K 線 → 該根之前的持倉, flips：K 線 → [(新持倉, 成交價)], 交易清單)。"""
    before, flips, trades = {}, {}, []
    pos, px = 0, None
    for k in range(LOOKBACK, len(sdays)):
        prev = sdays[k - LOOKBACK:k]
        upper = max(b["high"] for _, bars in prev for b in bars)
        lower = min(b["low"] for _, bars in prev for b in bars)
        used = set()
        for b in sdays[k][1]:
            before[b["time_key"]] = pos
            order = ("down", "up") if pos > 0 else ("up", "down")
            for side in order:
                if side == "up" and pos <= 0 and "up" not in used and b["high"] >= upper:
                    fill = max(upper, b["open"])
                    if pos < 0:
                        trades.append((sdays[k][0], -1, px - fill - cost))
                    pos, px = 1, fill
                    used.add("up")
                    flips.setdefault(b["time_key"], []).append((1, fill))
                elif side == "down" and pos >= 0 and "down" not in used and b["low"] <= lower:
                    fill = min(lower, b["open"])
                    if pos > 0:
                        trades.append((sdays[k][0], 1, fill - px - cost))
                    pos, px = -1, fill
                    used.add("down")
                    flips.setdefault(b["time_key"], []).append((-1, fill))
    return before, flips, trades


# ---- 合併策略 -------------------------------------------------------------------
def trade(day, side, params, cost, flips, market_entry=False):
    """side：1 做多／−1 做空。params = (基準, q_入, q_止, 離場, 蛇反手平倉)。回傳 (淨點數, 風險, 原因) 或 None。"""
    anchor, q_in, q_stop, exit_rule, flip_exit = params
    R, ref, bars = day["rhat"], day["refs"][anchor], day["bars"]
    ups, downs = day["ups"][anchor], day["downs"][anchor]
    if side > 0:
        entry, stop, opp = ref - bl.q(downs, q_in) * R, ref - bl.q(downs, q_stop) * R, ref + bl.q(ups, 0.5) * R
    else:
        entry, stop, opp = ref + bl.q(ups, q_in) * R, ref + bl.q(ups, q_stop) * R, ref - bl.q(downs, 0.5) * R
    o = bars[0]["open"]
    if (side > 0 and o <= stop) or (side < 0 and o >= stop):
        return None
    if market_entry:
        entry = o
    risk = (entry - stop) * side
    if risk <= 0:
        return None
    target = {"close": None, "opp": opp, "1R": entry + side * risk, "2R": entry + side * 2 * risk}[exit_rule]
    if target is not None and (target - entry) * side <= 0:
        target = None
    filled, px = market_entry, (o if market_entry else None)
    for j, b in enumerate(bars):
        h, l = b["high"], b["low"]
        if not filled:
            if not ((side > 0 and l <= entry) or (side < 0 and h >= entry)):
                continue
            filled = True
            px = min(entry, b["open"]) if side > 0 else max(entry, b["open"])
            if (side > 0 and l <= stop) or (side < 0 and h >= stop):
                return (stop - px) * side - cost, risk, "止蝕"
            continue
        if (side > 0 and b["open"] <= stop) or (side < 0 and b["open"] >= stop):
            return (b["open"] - px) * side - cost, risk, "止蝕（跳空）"
        if (side > 0 and l <= stop) or (side < 0 and h >= stop):
            return (stop - px) * side - cost, risk, "止蝕"
        if flip_exit:
            against = [f for f in flips.get(b["time_key"], []) if f[0] == -side]
            if against:
                return (against[0][1] - px) * side - cost, risk, "蛇反手平倉"
        if target is not None and ((side > 0 and h >= target) or (side < 0 and l <= target)):
            return (target - px) * side - cost, risk, "止賺"
    if not filled:
        return None
    return (bars[-1]["close"] - px) * side - cost, risk, "收市平倉"


def run(days, params, cost, before, flips, mode="snake"):
    """mode：snake 跟蛇方向；counter 反方向；both 不分方向兩邊都做；market 跟蛇方向但開市直接入市。"""
    out = []
    for d in days:
        s = before.get(d["bars"][0]["time_key"])
        if not s:
            continue
        sides = {"snake": [s], "counter": [-s], "both": [1, -1], "market": [s]}[mode]
        for side in sides:
            r = trade(d, side, params, cost, flips, market_entry=(mode == "market"))
            if r:
                out.append((d["date"], side, *r))
    return out


def stats(trades, n_days):
    if not trades:
        return {"n": 0}
    p = np.array([t[2] for t in trades]); rr = np.array([t[2] / t[3] for t in trades])
    wins, losses = p[p > 0], p[p <= 0]
    eq = np.cumsum(p)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq))
    sd = p.std(ddof=1) if len(p) > 1 else float("nan")
    return {"n": len(p), "fill": len(p) / max(n_days, 1), "win": float((p > 0).mean()),
            "avg_win": float(wins.mean()) if len(wins) else 0.0, "avg_loss": float(losses.mean()) if len(losses) else 0.0,
            "rrr": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else float("nan"),
            "mean": float(p.mean()), "R": float(rr.mean()),
            "t": float(p.mean() / sd * math.sqrt(len(p))) if sd > 0 else float("nan"),
            "pf": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
            "stop": sum(1 for t in trades if t[4].startswith("止蝕")) / len(p),
            "risk": float(np.mean([t[3] for t in trades])), "total": float(p.sum()), "dd": dd}


HEAD = ("| 設定 | 交易 | 止蝕率 | 勝率 | 平均賺／平均蝕 | **RRR** | **期望值／筆** | 期望值（R） | 盈虧比 | t 值 | 總點數／最大回撤 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|")


def fmt(s):
    if not s.get("n"):
        return "| 0 | — | — | — | — | — | — | — | — | — |"
    return (f"| {s['n']} | {s['stop']:.0%} | {s['win']:.0%} | +{s['avg_win']:,.0f}／{s['avg_loss']:,.0f} | **{s['rrr']:.2f}** | "
            f"**{s['mean']:+.1f} 點** | {s['R']:+.2f} | {s['pf']:.2f} | {s['t']:+.2f} | {s['total']:+,.0f}／{s['dd']:,.0f} |")


ANCH = {"prev": "開市前掛單（昨收）", "open": "09:15 掛單（開市價）"}
EXZH = {"close": "收市平倉", "opp": "去到另一邊預測位止賺", "1R": "賺 1R 止賺", "2R": "賺 2R 止賺"}


def name(p):
    a, qi, qs, ex, fx = p
    entry = {0.3: "較近", 0.5: "預測位", 0.7: "較遠"}[qi]
    return (f"{ANCH[a]}・入市{entry}・止蝕{'九' if qs == 0.95 else '八'}成範圍外・{EXZH[ex]}"
            + ("・蛇反手即平" if fx else ""))


def grid():
    return [(a, qi, qs, ex, fx) for a in ANCH for qi in (0.3, 0.5, 0.7) for qs in (0.9, 0.95)
            for ex in EXZH for fx in (False, True)]


def report(days, sdays, cost):
    before, flips, snake_trades = snake_run(sdays, cost)
    first = days[0]["date"]
    st_snake = [t for t in snake_trades if t[0] >= first]
    sp = np.array([t[2] for t in st_snake])
    long_days = sum(1 for d in days if before.get(d["bars"][0]["time_key"]) == 1)
    short_days = sum(1 for d in days if before.get(d["bars"][0]["time_key"]) == -1)
    lines = [f"共 {len(days)} 個交易日（{first} 至 {days[-1]['date']}）；開市時蛇做多 {long_days} 天、做空 {short_days} 天；"
             f"每筆成本 {cost:g} 點。",
             "",
             f"**蛇蟠陣本身（同期、同一條 15 分 K 重建）**：{len(sp)} 筆反手，每筆 {sp.mean():+.1f} 點、"
             f"勝率 {(sp > 0).mean():.0%}、RRR {sp[sp > 0].mean() / -sp[sp <= 0].mean():.2f}、"
             f"盈虧比 {sp[sp > 0].sum() / -sp[sp <= 0].sum():.2f}、總 {sp.sum():+,.0f} 點。",
             ""]
    core = [("prev", 0.5, 0.9, "close", False), ("prev", 0.5, 0.95, "close", False),
            ("prev", 0.5, 0.95, "opp", False), ("prev", 0.5, 0.95, "2R", False),
            ("open", 0.5, 0.9, "close", False), ("open", 0.5, 0.95, "close", False),
            ("open", 0.5, 0.95, "opp", False), ("open", 0.5, 0.95, "2R", False)]
    lines += ["### 你的規則（跟蛇方向，入市在預測高／低位，止蝕在範圍外）：全樣本", "", HEAD]
    for p in core:
        lines.append(f"| {name(p)} " + fmt(stats(run(days, p, cost, before, flips), len(days))))
    lines += ["", "### 對照（同一組：開市前掛單・預測位・九成範圍止蝕・收市平倉）", "", HEAD]
    p0 = ("prev", 0.5, 0.95, "close", False)
    for mode, zh in (("snake", "跟蛇方向（你的規則）"), ("market", "跟蛇方向但 09:15 直接入市"),
                     ("counter", "反蛇方向"), ("both", "不理蛇、兩邊都掛")):
        lines.append(f"| {zh} " + fmt(stats(run(days, p0, cost, before, flips, mode), len(days))))
    lines += ["", "### 做多腿／做空腿（開市前掛單・預測位・九成範圍止蝕・收市平倉）", "", HEAD]
    tr = run(days, p0, cost, before, flips)
    for side, zh in ((1, "蛇做多 → 預測低位買"), (-1, "蛇做空 → 預測高位沽")):
        lines.append(f"| {zh} " + fmt(stats([t for t in tr if t[1] == side], len(days))))
    half = len(days) // 2
    train, test = days[:half], days[half:]
    res = sorted(((stats(run(train, p, cost, before, flips), len(train)).get("mean", -1e9), p) for p in grid()),
                 key=lambda x: -x[0])
    lines += ["", f"### 前半段（{train[0]['date']} 至 {train[-1]['date']}）挑最好 5 組 → 後半段（{test[0]['date']} 起）成績",
              "", HEAD]
    picks = []
    for m, p in res[:5]:
        te = stats(run(test, p, cost, before, flips), len(test))
        picks.append((p, m, te))
        lines.append(f"| {name(p)}（訓練 {m:+.1f}） " + fmt(te))
    years = sorted({d["date"][:4] for d in days})
    lines += ["", "### 逐年（期望值／筆，括號是交易數）", "", "| 設定 | " + " | ".join(years) + " |",
              "|---|" + "---|" * len(years)]
    for p in core[:3] + [picks[0][0]]:
        cells = []
        for y in years:
            s = stats(run([d for d in days if d["date"][:4] == y], p, cost, before, flips), 1)
            cells.append(f"{s['mean']:+.1f}（{s['n']}）" if s.get("n") else "—")
        lines.append(f"| {name(p)} | " + " | ".join(cells) + " |")
    return "\n".join(lines), picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="15 分 K 快取 {bars, daily}")
    ap.add_argument("--cost", type=float, default=COST)
    a = ap.parse_args()
    if a.json and Path(a.json).exists():
        cache = json.load(open(a.json))
        bars, daily = cache["bars"], cache["daily"]
    else:
        bars, daily = hl.load_gcs("K_15M")
    all_days = hl.build_days(bars, daily)
    days = bl.prepare(all_days)
    text, _ = report(days, snake_days(all_days), a.cost)
    print(text)


if __name__ == "__main__":
    main()
