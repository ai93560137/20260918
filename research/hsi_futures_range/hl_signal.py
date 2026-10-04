"""訊號版：同一交易日「高位已出現」與「低位已出現」兩個訊號都亮了才入市，1:2 RRR 離場（用戶策略，2026-10-04）。

規格見 research/hsi_futures_range/hl_signal/README.md。訊號用 high_low_in.run_period（與「高低位已出現」回測同一套，
逐日前推）；數據、預測位、蛇蟠陣、紀錄格式、核對沿用 snake_week.py／snake_week_verify.py。

設定：<訊號>_<方向>
  訊號：B 機率法（再創新高／新低機率 < 5%）、A 耗盡回落（已走 ≥ 0.8R̂ 且回落 ≥ 0.5R̂）、C 時間點（16:30 回落 ≥ 0.4R̂）
  方向：S 跟蛇蟠陣（蛇反向反手也平倉）；F 反向（最後亮的是高位已出現 → 沽，低位已出現 → 買；同一根亮 → 不做；不理蛇）
  S0：對照，跟蛇、每天開市就入（同 hl_both.py 的 S0）
入市：兩個訊號都亮的那根收市後，下一根開市價（同一交易日內；那根已是當天最後一根就不做）。
止蝕：入市當天日範圍九成邊（固定）；目標：入市價 ± 2 × 風險；可持倉多日；每天最多入一次、當天平倉後不再入。

用法：python3 research/hsi_futures_range/hl_signal.py [--json 15 分 K 快取] [--cost 3]
核對：python3 research/hsi_futures_range/hl_signal.py --verify
"""
import argparse, csv, hashlib, json, math, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import snake_week as sw                                  # noqa: E402
import hl_both as hb                                     # noqa: E402

OUT = HERE / "hl_signal"
SIGNALS = {"B": ("B", 0.05), "A": ("A", 0.8, 0.5), "C": ("C", "16:30", 0.4)}
SIG_ZH = {"B": "B 機率法", "A": "A 耗盡回落", "C": "C 時間點"}
DIR_ZH = {"S": "跟蛇蟠陣", "F": "反向（最後亮高位已現 → 沽、低位已現 → 買）"}


def day_period(d):
    return {"key": d["date"], "kind": "day", "sessions": [d], "bars": [(b, 0) for b in d["bars"]], "n": 1, "R": d["rhat"]}


def signals(days, daily):
    """每日、每個訊號：高位／低位訊號在哪一根亮（與 high_low_in.run_period 同一套）。回傳 rows 與 triggers。"""
    rows, trig = [], {k: {} for k in SIGNALS}
    for d in days:
        if d["date"] not in daily:
            continue
        per = day_period(d)
        for k, strat in SIGNALS.items():
            got = {}
            for side in ("high", "low"):
                idx, ext, dist = hl.run_period(per, strat, side)
                got[side] = idx
                if idx is not None:
                    b = d["bars"][idx]
                    rem = d["rem"][idx] if k == "B" else None
                    sig = d["rhat"] / 1.596 / d["ref"] * math.sqrt(rem) * b["close"] if k == "B" and rem > 0 else None
                    rows.append({"date": d["date"], "signal": k, "side": side, "time_key": b["time_key"], "bar_index": idx,
                                 "ext": ext, "close": b["close"], "dist": dist, "R": d["rhat"],
                                 "rem": "" if rem is None else f"{rem:.12f}", "sigma_pts": "" if sig is None else f"{sig:.8f}",
                                 "prob": "" if sig is None else f"{math.erfc(dist / sig / math.sqrt(2)):.12f}"})
            ih, il = got["high"], got["low"]
            if ih is not None and il is not None and max(ih, il) + 1 < len(d["bars"]):
                last = "high" if ih > il else ("low" if il > ih else None)
                trig[k][d["date"]] = (max(ih, il) + 1, last)
    return rows, trig


def simulate(days, daily, weekly, before, flips, trig, direction, q=0.95, rr=2.0, cost=3.0):
    trades, tr = [], None
    ek = lambda side: f"{'low' if side > 0 else 'high'}_edge_{q}"

    def close(tr, px, t, d, why):
        gross = (px - tr["entry_price"]) * tr["side"]
        risk = abs(tr["entry_price"] - tr["initial_stop"])
        trades.append({**tr, "exit_date": d["date"], "exit_time": t, "exit_price": px, "exit_reason": why,
                       "gross": gross, "cost": cost, "net": gross - cost, "risk": risk,
                       "r_multiple": (gross - cost) / risk if risk > 0 else float("nan")})

    def manage(tr, b, t, d):
        s, stop, tg = tr["side"], tr["stop"], tr["target"]
        tr["bars"] += 1
        if (b["open"] - stop) * s <= 0:
            close(tr, b["open"], t, d, "止蝕（跳空）"); return None
        if (b["open"] - tg) * s >= 0:
            close(tr, b["open"], t, d, f"{rr:g}R 止賺"); return None
        hit_stop = (b["low"] <= stop) if s > 0 else (b["high"] >= stop)
        against = [f for f in flips.get(t, []) if f[0] == -s] if direction == "S" else []
        if hit_stop or against:
            c = ([(stop, "止蝕")] if hit_stop else []) + ([(against[0][1], "蛇反手")] if against else [])
            px, why = min(c, key=lambda x: x[0] * s)
            close(tr, px, t, d, why); return None
        if (b["high"] >= tg) if s > 0 else (b["low"] <= tg):
            close(tr, tg, t, d, f"{rr:g}R 止賺"); return None
        return tr

    started = False
    for d in days:
        if d["date"] not in daily or sw.week_key(d["date"]) not in weekly:
            continue
        started = True
        lv, wl = daily[d["date"]], weekly[sw.week_key(d["date"])]
        done_today = False
        go = trig.get(d["date"])
        for j, b in enumerate(d["bars"]):
            t = b["time_key"]
            if not tr and not done_today and go and j == go[0]:
                done_today = True
                side = (before.get(t) or 0) if direction == "S" else {"low": 1, "high": -1, None: 0}[go[1]]
                if side:
                    px = b["open"]
                    stop = lv[ek(side)]
                    if (stop - px) * side < 0:
                        risk = abs(px - stop)
                        tr = {"side": side, "entry_date": d["date"], "entry_time": t, "entry_price": px,
                              "entry_type": "訊號都現後入", "snake_at_entry": before.get(t), "week": wl["week"],
                              "week_anchor": wl["anchor"], "week_R": wl["R_week"], "initial_stop": stop, "stop": stop,
                              "target": px + side * rr * risk, "initial_target": px + side * rr * risk,
                              "stop_path": [(t, stop)], "bars": 0}
            if tr:
                tr = manage(tr, b, t, d)
                if tr is None:
                    done_today = True
    if tr and started:
        d = days[-1]
        close(tr, d["bars"][-1]["close"], d["bars"][-1]["time_key"], d, "數據完結")
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--cost", type=float, default=3.0)
    ap.add_argument("--q", type=float, default=0.95)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    bars, daily_k = sw.load(a.json)
    out = Path(a.out)
    if a.verify:
        import snake_week_verify as v
        sys.exit(v.verify(bars, daily_k, out))
    days, sdays, before, flips, snake_trades, dl, wl = sw.build(bars, daily_k, a.cost)
    rows, trig = signals(days, dl)
    res = {}
    for k in SIGNALS:
        for dr in DIR_ZH:
            res[f"{k}_{dr}"] = sw.add_sessions(simulate(days, dl, wl, before, flips, trig[k], dr, a.q, a.rr, a.cost), days)
    res["S0"] = sw.add_sessions(hb.simulate(days, dl, wl, before, flips, "S0", a.q, a.rr, a.cost), days)
    (out / "trades").mkdir(parents=True, exist_ok=True)
    for name, trs in res.items():
        sw.write_ledger(out / "trades" / f"{name}.csv", name, trs)
    sw.write_csv(out / "signals.csv", rows, ["date", "signal", "side", "time_key", "bar_index", "ext", "close", "dist", "R",
                                             "rem", "sigma_pts", "prob"])
    sw.write_csv(out / "levels_daily.csv", dl.values(), ["date", "rhat", "ref", "n_hist", "pred_high", "pred_low"]
                 + [f"{s}_edge_{x}" for x in sw.QS for s in ("high", "low")])
    sw.write_csv(out / "levels_weekly.csv", wl.values(), ["week", "first", "sessions", "anchor", "R_week", "n_hist",
                 "pred_high", "pred_low"] + [f"{s}_edge_{x}" for x in sw.QS for s in ("high", "low")])
    sw.write_csv(out / "snake_flips.csv", [{"time_key": t, "new_side": s, "price": p} for t in sorted(flips) for s, p in flips[t]],
                 ["time_key", "new_side", "price"])
    n_days = sum(1 for d in days if d["date"] in dl)
    manifest = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "git_head": sw.git_head(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "engine_sha256": {f: hashlib.sha256((HERE / f).read_bytes()).hexdigest()
                                  for f in ("snake_week.py", "high_low_in.py", "hl_both.py")},
                "input": {"bars": len(bars), "bars_sha256": sw.sha256_json(sorted(bars, key=lambda b: b["time_key"])),
                          "daily": len(daily_k), "daily_sha256": sw.sha256_json(sorted(daily_k, key=lambda b: str(b["time_key"])))},
                "params": {"cost_per_round_trip": a.cost, "stop_band_q": a.q, "rr": a.rr, "signals": {k: list(v) for k, v in SIGNALS.items()}},
                "trigger_days": {k: len(v) for k, v in trig.items()}, "days_with_levels": n_days,
                "configs": {m: {"trades": len(t), "net_total": round(sum(x["net"] for x in t), 2)} for m, t in res.items()}}
    json.dump(manifest, open(out / "manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    text = report(res, days, snake_trades, trig, n_days, a, manifest)
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


def report(res, days, snake_trades, trig, n_days, a, manifest):
    start = min(t["entry_date"] for trs in res.values() for t in trs)
    tradable = [d["date"] for d in days if d["date"] >= start]
    mid = tradable[len(tradable) // 2]
    sp = np.array([t[2] for t in snake_trades if t[0] >= start])
    L = [f"# 訊號版：高位已出現＋低位已出現兩個訊號都亮後入市・1:{a.rr:g} RRR", "",
         f"- 期間：{start} 至 {days[-1]['date']}（前半段到 {mid} 前）；成本每筆 {a.cost:g} 點；1 張",
         f"- 止蝕：入市當天日範圍 {a.q:.0%} 邊（固定）；目標 {a.rr:g} 倍風險；可持倉多日",
         f"- 兩個訊號同日都亮的日子（{n_days} 個有預測位的交易日中）：" + "、".join(f"{SIG_ZH[k]} {len(v)} 天" for k, v in trig.items()),
         f"- 輸入 SHA-256：15 分 K `{manifest['input']['bars_sha256'][:16]}…`；程式 `{manifest['script_sha256'][:16]}…`；規格見 README.md",
         "", f"**蛇蟠陣本身（同期）**：{len(sp)} 筆、每筆 {sp.mean():+.1f} 點、勝率 {(sp > 0).mean():.0%}、"
         f"RRR {sp[sp > 0].mean() / -sp[sp <= 0].mean():.2f}、總 {sp.sum():+,.0f}", "", sw.HEAD]
    for m, trs in res.items():
        lab = "對照：跟蛇、開市就入" if m == "S0" else f"{SIG_ZH[m[0]]}・{DIR_ZH[m[2:]]}"
        L.append(f"| {m} {lab} " + sw.fmt(sw.stats(trs)))
    years = sorted({t["entry_date"][:4] for trs in res.values() for t in trs})
    L += ["", "| 設定 | 前半段 | 後半段 | " + " | ".join(years) + " | 做多 | 做空 | 離場原因 |",
          "|---|---|---|" + "---|" * len(years) + "---|---|---|"]
    for m, trs in res.items():
        def cell(sel):
            s = sw.stats(sel)
            return f"{s['mean']:+.1f}（{s['n']}）" if s.get("n") else "—"
        rs = {}
        for t in trs:
            rs[t["exit_reason"]] = rs.get(t["exit_reason"], 0) + 1
        L.append(f"| {m} | {cell([t for t in trs if t['entry_date'] < mid])} | {cell([t for t in trs if t['entry_date'] >= mid])} | "
                 + " | ".join(cell([t for t in trs if t['entry_date'][:4] == y]) for y in years)
                 + f" | {cell([t for t in trs if t['side'] > 0])} | {cell([t for t in trs if t['side'] < 0])} | "
                 + "、".join(f"{k} {v}" for k, v in sorted(rs.items(), key=lambda x: -x[1])) + " |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
