"""在「預測高位」預先掛沽單、「預測低位」預先掛買單，止蝕放在預計範圍外邊——賺不賺錢？（盈虧回測）

想法（用戶）：預計範圍的外邊就是止蝕位；範圍放闊 → 止蝕少被觸發，虧損用倉位控制。
跟方向二（事後追入）不同：這裡預先在預測位置等價，入市位離止蝕近。

每個交易日（日市 09:15 至翌日 03:00），只用當時已知的數據：
  R̂ = 逐日前推 HAR 預測；高位比例 u = (高 − 基準) ÷ R̂、低位比例 d = (基準 − 低) ÷ R̂，取之前所有日子（≥ 120 天）的分位。
  基準：prev = 昨收（07:53 開市前就能掛單）；open = 09:15 開市價（開市後才掛單）。
  沽：入市價 = 基準 + q_入 分位(u) × R̂，止蝕 = 基準 + q_止 分位(u) × R̂。買：對稱，用 d。
  q_止 = 0.90 → 止蝕在八成範圍的上（下）限；0.95 → 九成範圍。
  成交：15 分 K 碰到入市價就成交；開市已越過入市價 → 用開市價成交；開市已越過止蝕 → 當天不做。
  同一根 K 線碰到入市價又碰到止蝕 → 當作止蝕（保守）。
  離場：close = 收市（翌日 03:00）平倉；ref = 回到基準價止賺；1R = 賺到跟風險一樣多止賺；其餘收市平倉。
  成本：每筆來回 COST 點。恒指期貨每點 HK$50，小型恒指 HK$10。
評分：每筆淨點數、以風險（入市到止蝕）為單位的 R 倍數；參數前半段挑、後半段測試；另列逐年。

用法：python3 research/hsi_futures_range/band_limit.py [--json 15 分 K 快取] [--cost 3]
"""
import argparse, bisect, json, math, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import high_low_in as hl                                 # noqa: E402

COST = 3.0
MIN_DAYS = 120
ANCHORS = {"prev": "昨收（開市前掛單）", "open": "開市價（09:15 後掛單）"}
EXITS = {"close": "收市平倉", "ref": "回到基準價止賺", "1R": "賺 1 倍風險止賺"}


def q(a, p):
    pos = (len(a) - 1) * p
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(a) - 1)
    return a[lo] + (a[hi] - a[lo]) * (pos - lo)


def prepare(days):
    """每天加上逐日前推的高低位比例分位（prev／open 兩種基準）。"""
    hist = {"prev": ([], []), "open": ([], [])}
    out = []
    for d in days:
        bars, R = d["bars"], d["rhat"]
        hi, lo = max(b["high"] for b in bars), min(b["low"] for b in bars)
        refs = {"prev": d["ref"], "open": bars[0]["open"]}
        if len(hist["prev"][0]) >= MIN_DAYS:
            out.append({**d, "refs": refs, "ups": {k: list(v[0]) for k, v in hist.items()},
                        "downs": {k: list(v[1]) for k, v in hist.items()}})
        for k, ref in refs.items():
            bisect.insort(hist[k][0], (hi - ref) / R)
            bisect.insort(hist[k][1], (ref - lo) / R)
    return out


def trade(day, anchor, side, q_in, q_stop, exit_rule, cost):
    """回傳 (淨點數, 風險點數, 出場原因) 或 None（沒成交／當天不做）。"""
    R, ref, bars = day["rhat"], day["refs"][anchor], day["bars"]
    ratios = day["ups" if side == "short" else "downs"][anchor]
    sign = -1 if side == "short" else 1
    entry = ref - sign * q(ratios, q_in) * R            # 沽：基準之上；買：基準之下
    stop = ref - sign * q(ratios, q_stop) * R
    risk = abs(stop - entry)
    if risk <= 0:
        return None
    o = bars[0]["open"]
    if (side == "short" and o >= stop) or (side == "long" and o <= stop):
        return None                                      # 開市已越過止蝕：不做
    target = {"close": None, "ref": ref, "1R": entry + sign * risk}[exit_rule]
    filled, px = False, None
    for b in bars:
        h, l = b["high"], b["low"]
        if not filled:
            touched = h >= entry if side == "short" else l <= entry
            if not touched:
                continue
            filled = True
            px = max(entry, b["open"]) if side == "short" else min(entry, b["open"])   # 開市越過入市價 → 開市價成交
            if (side == "short" and h >= stop) or (side == "long" and l <= stop):
                return sign * (stop - px) - cost, risk, "止蝕"
            continue
        if side == "short":
            if b["open"] >= stop:
                return sign * (b["open"] - px) - cost, risk, "止蝕（跳空）"
            if h >= stop:
                return sign * (stop - px) - cost, risk, "止蝕"
            if target is not None and l <= target:
                return sign * (target - px) - cost, risk, "止賺"
        else:
            if b["open"] <= stop:
                return sign * (b["open"] - px) - cost, risk, "止蝕（跳空）"
            if l <= stop:
                return sign * (stop - px) - cost, risk, "止蝕"
            if target is not None and h >= target:
                return sign * (target - px) - cost, risk, "止賺"
    if not filled:
        return None
    return sign * (bars[-1]["close"] - px) - cost, risk, "收市平倉"


def run(days, params, cost, sides=("short", "long")):
    out = []
    for d in days:
        for side in sides:
            r = trade(d, params[0], side, params[1], params[2], params[3], cost)
            if r:
                out.append((d["date"], side, *r))
    return out


def stats(trades, n_days):
    if not trades:
        return {"n": 0}
    p = np.array([t[2] for t in trades]); rr = np.array([t[2] / t[3] for t in trades])
    eq = np.cumsum(p)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq))
    sd = p.std(ddof=1) if len(p) > 1 else float("nan")
    stops = sum(1 for t in trades if t[4].startswith("止蝕"))
    return {"n": len(p), "fill": len(p) / n_days, "win": float((p > 0).mean()), "mean": float(p.mean()),
            "R": float(rr.mean()), "t": float(p.mean() / sd * math.sqrt(len(p))) if sd > 0 else float("nan"),
            "pf": float(p[p > 0].sum() / -p[p < 0].sum()) if (p < 0).any() else float("inf"),
            "stop": stops / len(p), "risk": float(np.mean([t[3] for t in trades])), "total": float(p.sum()), "dd": dd}


def fmt(s):
    if not s.get("n"):
        return "| 0 | — | — | — | — | — | — | — | — |"
    return (f"| {s['n']} | {s['stop']:.0%} | {s['win']:.0%} | {s['risk']:,.0f} | **{s['mean']:+.1f}** | {s['R']:+.2f} | "
            f"{s['t']:+.2f} | {s['pf']:.2f} | {s['total']:+,.0f}／{s['dd']:,.0f} |")


HEAD = ("| 設定 | 交易數 | 止蝕率 | 賺錢 | 平均風險（點） | **每筆淨利（點）** | 每筆 R | t 值 | 盈虧比 | 總點數／最大回撤 |\n"
        "|---|---|---|---|---|---|---|---|---|---|")


def name(p):
    a, qi, qs, ex = p
    rng = {0.9: "八成範圍", 0.95: "九成範圍"}[qs]
    entry = {0.5: "預測高（低）位", 0.3: "較近（30% 分位）", 0.7: "較遠（70% 分位）"}[qi]
    return f"{ANCHORS[a]}・入市 {entry}・止蝕 {rng}外邊・{EXITS[ex]}"


def grid():
    return [(a, qi, qs, ex) for a in ANCHORS for qi in (0.3, 0.5, 0.7) for qs in (0.9, 0.95) for ex in EXITS]


def report(days, cost):
    half = len(days) // 2
    train, test = days[:half], days[half:]
    lines = [f"共 {len(days)} 個交易日（{days[0]['date']} 至 {days[-1]['date']}），訓練 {len(train)}／測試 {len(test)}，"
             f"每筆成本 {cost:g} 點；沽、買兩邊合計（每天最多兩筆）"]
    core = [("prev", 0.5, 0.9, "close"), ("prev", 0.5, 0.95, "close"), ("open", 0.5, 0.9, "close"),
            ("open", 0.5, 0.95, "close"), ("prev", 0.5, 0.95, "ref"), ("open", 0.5, 0.95, "ref")]
    lines += ["", "**你的想法（入市在預測高／低位，止蝕在範圍外邊）：全樣本**", "", HEAD]
    for p in core:
        lines.append(f"| {name(p)} " + fmt(stats(run(days, p, cost), len(days))))
    res = sorted(((stats(run(train, p, cost), len(train)).get("mean", -1e9), p) for p in grid()), reverse=True)
    lines += ["", "**前半段挑出最好的 5 組 → 後半段成績**", "", HEAD]
    picks = []
    for m, p in res[:5]:
        te = stats(run(test, p, cost), len(test))
        picks.append((p, m, te))
        lines.append(f"| {name(p)}（訓練 {m:+.1f}） " + fmt(te))
    lines += ["", "**逐年（每筆淨利，點）**", "", "| 設定 | " + " | ".join(sorted({d['date'][:4] for d in days})) + " |",
              "|---|" + "---|" * len({d['date'][:4] for d in days})]
    for p in core[:4] + [picks[0][0]]:
        cells = []
        for y in sorted({d["date"][:4] for d in days}):
            s = stats(run([d for d in days if d["date"][:4] == y], p, cost), 1)
            cells.append(f"{s['mean']:+.1f}（{s['n']}）" if s.get("n") else "—")
        lines.append(f"| {name(p)} | " + " | ".join(cells) + " |")
    lines += ["", "**沽、買分開（全樣本）**", "", HEAD]
    for p in core[:4]:
        for side, zh in (("short", "只沽"), ("long", "只買")):
            lines.append(f"| {zh}・{name(p)} " + fmt(stats(run(days, p, cost, (side,)), len(days))))
    return "\n".join(lines), picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="15 分 K 快取 {bars, daily}（high_low_in.py 同格式）")
    ap.add_argument("--cost", type=float, default=COST)
    a = ap.parse_args()
    if a.json and Path(a.json).exists():
        cache = json.load(open(a.json))
        bars, daily = cache["bars"], cache["daily"]
    else:
        bars, daily = hl.load_gcs("K_15M")
    days = prepare(hl.build_days(bars, daily))
    text, _ = report(days, a.cost)
    print(text)


if __name__ == "__main__":
    main()
