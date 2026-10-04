"""投資人堅持「用預測波幅＋期貨」（2026-10-04）：把預測波幅當作「當天的波幅預算」，找期貨策略。

四個想法（都只用當時已知的數據；期貨 15 分 K，交易日 09:15 至翌日 03:00；成本每筆 3 點）：
  S1 午後擴張突破：12:00 時已走 = (上午高 − 上午低) ÷ R̂；已走 ≤ u 時，上午高掛買 stop、上午低掛沽 stop（先到先做，一天一筆）；
     止蝕 = 上午範圍中點；目標 = 入市價 ± k × (R̂ − 上午範圍)（剩餘預算）；否則 03:00 收市平。
  S2 夜市擴張突破：16:30 日市收市，已走 = 日市範圍 ÷ R̂；已走 ≤ u 時，夜市突破日市高／低就跟（stop 單）；止蝕 = 日市中點；目標 = 剩餘預算 × k；03:00 平。
  S3 壓縮日突破：R̂ 在過去 250 日最低 20% 的日子，突破開市首 60 分鐘範圍就跟；止蝕 = 另一邊；目標 = 1 × R̂；03:00 平。
  S4 波幅倉位：蛇蟠陣本身的交易，倉位 = clip(過去 250 日 R̂ 中位數 ÷ 入市日 R̂, 0.5, 2)（大波幅日減倉、小波幅日加倉），比較夏普。
每個想法前半段挑參數、後半段驗證；逐年。
用法：python3 research/hsi_futures_range/forecast_fut.py --json 15 分 K 快取
輸出：research/hsi_futures_range/forecast_fut/REPORT.md
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import snake_band as sb                                  # noqa: E402

OUT = HERE / "forecast_fut"
COST = 3.0


def day_bars(d):
    return [b for b in d["bars"] if b["time_key"][:10] == d["date"] and "09:15" <= b["time_key"][11:16] <= "16:30"]


def breakout(bars, hi, lo, stop_long, stop_short, tgt_pts, cost):
    """stop 單在 hi 買／lo 沽（先到先做），止蝕、目標、最後收市平。回傳 (淨點數, 風險) 或 None。"""
    for i, b in enumerate(bars):
        up, dn = b["high"] >= hi, b["low"] <= lo
        if not (up or dn):
            continue
        if up and dn:                                     # 同一根兩邊都碰：按開市價較近那邊，並當止蝕（保守）
            side = 1 if abs(b["open"] - hi) <= abs(b["open"] - lo) else -1
            px = hi if side > 0 else lo
            stop = stop_long if side > 0 else stop_short
            return side * (stop - px) - cost, abs(px - stop)
        side = 1 if up else -1
        px = max(hi, b["open"]) if side > 0 else min(lo, b["open"])
        stop = stop_long if side > 0 else stop_short
        tgt = px + side * tgt_pts if tgt_pts else None
        risk = abs(px - stop)
        if (side > 0 and b["low"] <= stop) or (side < 0 and b["high"] >= stop):
            return side * (stop - px) - cost, risk
        for c in bars[i + 1:]:
            if (side > 0 and c["open"] <= stop) or (side < 0 and c["open"] >= stop):
                return side * (c["open"] - px) - cost, risk
            if (side > 0 and c["low"] <= stop) or (side < 0 and c["high"] >= stop):
                return side * (stop - px) - cost, risk
            if tgt is not None and ((side > 0 and c["high"] >= tgt) or (side < 0 and c["low"] <= tgt)):
                return side * (tgt - px) - cost, risk
        return side * (bars[-1]["close"] - px) - cost, risk
    return None


def s1(d, u, k):
    db = day_bars(d)
    am = [b for b in db if b["time_key"][11:16] <= "12:00"]
    if len(am) < 4 or len(db) <= len(am):
        return None
    hi, lo = max(b["high"] for b in am), min(b["low"] for b in am)
    used = (hi - lo) / d["rhat"]
    if used > u:
        return None
    rest = [b for b in d["bars"] if b["time_key"] > am[-1]["time_key"]]
    mid = (hi + lo) / 2
    tgt = k * max(0.0, d["rhat"] - (hi - lo))
    return breakout(rest, hi, lo, mid, mid, tgt, COST)


def s2(d, u, k):
    db = day_bars(d)
    night = [b for b in d["bars"] if b["time_key"] > f"{d['date']} 16:30:00"]
    if len(db) < 10 or len(night) < 4:
        return None
    hi, lo = max(b["high"] for b in db), min(b["low"] for b in db)
    if (hi - lo) / d["rhat"] > u:
        return None
    mid = (hi + lo) / 2
    tgt = k * max(0.0, d["rhat"] - (hi - lo))
    return breakout(night, hi, lo, mid, mid, tgt, COST)


def s3(d, pct_ok, k):
    if not pct_ok:
        return None
    db = day_bars(d)
    first = [b for b in db if b["time_key"][11:16] <= "10:15"]
    if len(first) < 3 or len(db) <= len(first):
        return None
    hi, lo = max(b["high"] for b in first), min(b["low"] for b in first)
    rest = [b for b in d["bars"] if b["time_key"] > first[-1]["time_key"]]
    return breakout(rest, hi, lo, lo, hi, k * d["rhat"], COST)


def stats(res):
    x = np.array([r[0] for r in res]) if res else np.array([])
    if len(x) < 5:
        return {"n": len(x)}
    eq = np.cumsum(x)
    return {"n": len(x), "mean": x.mean(), "win": (x > 0).mean(), "t": x.mean() / x.std(ddof=1) * math.sqrt(len(x)),
            "total": x.sum(), "dd": float((np.maximum.accumulate(eq) - eq).max()),
            "R": float(np.mean([r[0] / r[1] for r in res if r[1] > 0]))}


def fmt(s):
    if s.get("n", 0) < 5:
        return f"| {s.get('n', 0)} | — | — | — | — | — |"
    return f"| {s['n']} | **{s['mean']:+.1f}** | {s['win']:.0%} | {s['R']:+.2f} | {s['t']:+.2f} | {s['total']:+,.0f}／{s['dd']:,.0f} |"


HEAD = "| 設定 | 交易 | 每筆淨利 | 勝率 | 每筆 R | t | 總點數／最大回撤 |\n|---|---|---|---|---|---|---|"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--json", required=True); a = ap.parse_args()
    cache = json.load(open(a.json))
    days = hl.build_days(cache["bars"], cache["daily"])
    # R̂ 的過去 250 日分位
    rh = [d["rhat"] for d in days]
    for i, d in enumerate(days):
        past = rh[max(0, i - 250):i]
        d["low20"] = len(past) >= 60 and d["rhat"] <= np.percentile(past, 20)
        d["rmed"] = np.median(past) if len(past) >= 60 else None
    half = len(days) // 2
    L = [f"# 用預測波幅做「波幅預算」的期貨策略（forecast_fut.py）", "", f"- {days[0]['date']} 至 {days[-1]['date']}，{len(days)} 個交易日；成本每筆 3 點；前半段 {half} 日挑參數、後半段驗證", ""]
    for name, fn, grid in (("S1 午後擴張突破（12:00 已走 ≤ u，目標 = k × 剩餘預算）", s1, [(u, k) for u in (0.3, 0.4, 0.5) for k in (0.5, 1.0, 0)]),
                           ("S2 夜市擴張突破（日市已走 ≤ u）", s2, [(u, k) for u in (0.4, 0.5, 0.6) for k in (0.5, 1.0, 0)])):
        L += [f"## {name}", "", "全樣本：", "", HEAD]
        res_all = {}
        for u, k in grid:
            res = [r for r in (fn(d, u, k) for d in days) if r]
            res_all[(u, k)] = res
            L.append(f"| u={u} k={k if k else '收市平'} " + fmt(stats(res)))
        best = max(grid, key=lambda g: stats([r for r in (fn(d, *g) for d in days[:half]) if r]).get("mean", -1e9))
        te = [r for r in (fn(d, *best) for d in days[half:]) if r]; tr = [r for r in (fn(d, *best) for d in days[:half]) if r]
        L += ["", f"前半段最好 u={best[0]} k={best[1]}：訓練 {stats(tr).get('mean', 0):+.1f} → 後半段 " + fmt(stats(te)).replace("|", "", 1).strip(), ""]
        L += ["逐年（全樣本最好那組）：" + "；".join(f"{y} {stats([r for r in (fn(d, *best) for d in days if d['date'][:4] == y) if r]).get('mean', float('nan')):+.1f}" for y in sorted({d['date'][:4] for d in days})), ""]
    L += ["## S3 壓縮日突破（R̂ 在過去 250 日最低 20% 的日子，突破首 60 分鐘範圍）", "", HEAD]
    for k in (0.5, 1.0, 1.5, 0):
        res = [r for r in (s3(d, d["low20"], k) for d in days) if r]
        L.append(f"| 目標 {k if k else '收市平'}×R̂ " + fmt(stats(res)))
    res_all_days = [r for r in (s3(d, True, 1.0) for d in days) if r]
    L.append(f"| 對照：所有日子都做（目標 1×R̂） " + fmt(stats(res_all_days)))
    L.append("")
    # S4 波幅倉位
    sdays = sb.snake_days(days)
    _, _, trades = sb.snake_run(sdays, COST)
    rmed = {d["date"]: d["rmed"] for d in days}; rhat = {d["date"]: d["rhat"] for d in days}
    base = np.array([t[2] for t in trades if rmed.get(t[0])])
    scaled = np.array([t[2] * min(2.0, max(0.5, rmed[t[0]] / rhat[t[0]])) for t in trades if rmed.get(t[0])])
    inv = np.array([t[2] * min(2.0, max(0.5, rhat[t[0]] / rmed[t[0]])) for t in trades if rmed.get(t[0])])
    def line(x, lab):
        eq = np.cumsum(x); dd = (np.maximum.accumulate(eq) - eq).max()
        return f"| {lab} | {len(x)} | {x.mean():+.1f} | {x.sum():+,.0f} | {dd:,.0f} | {x.mean() / x.std(ddof=1) * math.sqrt(len(x)):+.2f} | {x.sum() / dd:.2f} |"
    L += ["## S4 蛇蟠陣 × 波幅倉位（倉位 = 中位 R̂ ÷ 當日 R̂，限 0.5–2）", "", "| 倉位 | 筆 | 每筆 | 總點數 | 最大回撤 | t | 總點數 ÷ 回撤 |", "|---|---|---|---|---|---|---|",
          line(base, "固定 1 張"), line(scaled, "大波幅日減倉、小波幅日加倉"), line(inv, "反過來：大波幅日加倉"), ""]
    OUT.mkdir(exist_ok=True)
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
