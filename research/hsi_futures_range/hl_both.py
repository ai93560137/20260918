"""預測高位、預測低位「都出現後」才入市，1:2 RRR 離場（用戶策略，2026-10-04）。

規格見 research/hsi_futures_range/hl_both/README.md。共用 snake_week.py 的數據、預測位、蛇蟠陣重建、紀錄格式與核對程式。

設定：
  S  跟蛇蟠陣方向（蛇反向反手也平倉）
  F  反向回歸：第二個被碰到的是預測低位 → 買；是預測高位 → 沽（不理蛇）
  S0 對照：跟蛇、每天開市就入（不等高低位都出現），止蝕／目標同 S
止蝕：入市當天日預計範圍九成邊（做多＝低位下限、做空＝高位上限），入市後固定；目標：入市價 ± 2 × 風險。
未到止蝕或目標就持倉（可多日）；同一根先看止蝕（保守）；開市越過止蝕／目標用開市價。

用法：python3 research/hsi_futures_range/hl_both.py [--json 15 分 K 快取] [--cost 3] [--q 0.95] [--rr 2]
核對：python3 research/hsi_futures_range/hl_both.py --verify
"""
import argparse, hashlib, json, math, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import snake_week as sw                                  # noqa: E402
import snake_band as sb                                  # noqa: E402

OUT = HERE / "hl_both"
CONFIGS = {"S": "跟蛇蟠陣方向（蛇反手也平倉）", "F": "反向回歸（最後碰低位買、碰高位沽，不理蛇）",
           "S0": "對照：跟蛇、開市就入（不等高低位都出現）"}


def simulate(days, daily, weekly, before, flips, mode, q=0.95, rr=2.0, cost=3.0):
    trades, tr = [], None
    ek = lambda side: f"{'low' if side > 0 else 'high'}_edge_{q}"

    def close(tr, px, t, d, why):
        gross = (px - tr["entry_price"]) * tr["side"]
        risk = abs(tr["entry_price"] - tr["initial_stop"])
        trades.append({**tr, "exit_date": d["date"], "exit_time": t, "exit_price": px, "exit_reason": why,
                       "gross": gross, "cost": cost, "net": gross - cost, "risk": risk,
                       "r_multiple": (gross - cost) / risk if risk > 0 else float("nan")})

    def open_(side, px, t, d, kind, lv, wl):
        stop = lv[ek(side)]
        if (stop - px) * side >= 0:
            return None
        risk = abs(px - stop)
        tg = px + side * rr * risk
        return {"side": side, "entry_date": d["date"], "entry_time": t, "entry_price": px, "entry_type": kind,
                "snake_at_entry": before.get(t), "week": wl["week"], "week_anchor": wl["anchor"], "week_R": wl["R_week"],
                "initial_stop": stop, "stop": stop, "target": tg, "initial_target": tg, "stop_path": [(t, stop)], "bars": 0}

    def manage(tr, b, t, d, entry_bar):
        """持倉中的一根：跳空止蝕／止賺 → 盤中止蝕（與蛇反手取較差）→ 目標。回傳仍持倉的 tr 或 None。"""
        s, stop, tg = tr["side"], tr["stop"], tr["target"]
        tr["bars"] += 1
        if not entry_bar:
            if (b["open"] - stop) * s <= 0:
                close(tr, b["open"], t, d, "止蝕（跳空）"); return None
            if (b["open"] - tg) * s >= 0:
                close(tr, b["open"], t, d, f"{rr:g}R 止賺"); return None
        hit_stop = (b["low"] <= stop) if s > 0 else (b["high"] >= stop)
        against = [f for f in flips.get(b["time_key"], []) if f[0] == -s] if (mode != "F" and not entry_bar) else []
        if hit_stop or against:
            c = ([(stop, "止蝕" if not entry_bar else "止蝕（同一根）")] if hit_stop else []) + ([(against[0][1], "蛇反手")] if against else [])
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
        hi_hit = lo_hit = False
        done_today = False
        for j, b in enumerate(d["bars"]):
            t = b["time_key"]
            if tr:
                tr = manage(tr, b, t, d, entry_bar=False)
                if tr is None:
                    done_today = True                                  # 同一天平倉後不再入
            if mode == "S0":
                if not tr and not done_today and j == 0 and (before.get(t) or 0) != 0:
                    tr = open_(before[t], b["open"], t, d, "空手・開市再入", lv, wl)
                    done_today = True
                    if tr:
                        tr = manage(tr, b, t, d, entry_bar=False)      # 開市價入：這一根之後照常管理
                continue
            new_hi = not hi_hit and b["high"] >= lv["pred_high"]
            new_lo = not lo_hit and b["low"] <= lv["pred_low"]
            trigger = (new_hi or new_lo) and (hi_hit or new_hi) and (lo_hit or new_lo)
            hi_hit, lo_hit = hi_hit or new_hi, lo_hit or new_lo
            if not trigger or tr or done_today:
                continue
            done_today = True
            if new_hi and new_lo:                                      # 同一根兩個都碰到：先後不知 → 收市價
                last, px = None, b["close"]
            elif new_lo:
                last, px = -1, min(lv["pred_low"], b["open"])
            else:
                last, px = 1, max(lv["pred_high"], b["open"])
            if mode == "S":
                side = before.get(t) or 0
            else:
                side = {-1: 1, 1: -1, None: 0}[last]                   # 最後碰低位 → 買；碰高位 → 沽
            if side == 0:
                continue
            tr = open_(side, px, t, d, "高低都現後入", lv, wl)
            if tr and px != b["close"]:
                tr = manage(tr, b, t, d, entry_bar=True)
            elif tr:
                tr["bars"] += 1                                        # 收市價入：這根之後的事在下一根處理
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
    res = {}
    for mode in CONFIGS:
        res[mode] = sw.add_sessions(simulate(days, dl, wl, before, flips, mode, a.q, a.rr, a.cost), days)
    (out / "trades").mkdir(parents=True, exist_ok=True)
    for mode, trs in res.items():
        sw.write_ledger(out / "trades" / f"{mode}.csv", mode, trs)
    sw.write_csv(out / "levels_daily.csv", dl.values(), ["date", "rhat", "ref", "n_hist", "pred_high", "pred_low"]
                 + [f"{s}_edge_{x}" for x in sw.QS for s in ("high", "low")])
    sw.write_csv(out / "levels_weekly.csv", wl.values(), ["week", "first", "sessions", "anchor", "R_week", "n_hist",
                 "pred_high", "pred_low"] + [f"{s}_edge_{x}" for x in sw.QS for s in ("high", "low")])
    sw.write_csv(out / "snake_flips.csv", [{"time_key": t, "new_side": s, "price": p} for t in sorted(flips) for s, p in flips[t]],
                 ["time_key", "new_side", "price"])
    manifest = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "git_head": sw.git_head(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "engine_sha256": hashlib.sha256((HERE / "snake_week.py").read_bytes()).hexdigest(),
                "input": {"bars": len(bars), "bars_sha256": sw.sha256_json(sorted(bars, key=lambda b: b["time_key"])),
                          "daily": len(daily_k), "daily_sha256": sw.sha256_json(sorted(daily_k, key=lambda b: str(b["time_key"])))},
                "params": {"cost_per_round_trip": a.cost, "stop_band_q": a.q, "rr": a.rr, "configs": CONFIGS},
                "configs": {m: {"trades": len(t), "net_total": round(sum(x["net"] for x in t), 2)} for m, t in res.items()}}
    json.dump(manifest, open(out / "manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    text = report(res, days, snake_trades, a, manifest)
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


def report(res, days, snake_trades, a, manifest):
    start = min(t["entry_date"] for trs in res.values() for t in trs)
    tradable = [d["date"] for d in days if d["date"] >= start]
    mid = tradable[len(tradable) // 2]
    sp = np.array([t[2] for t in snake_trades if t[0] >= start])
    eq = np.cumsum(sp)
    sdd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq))
    L = [f"# 預測高低位都出現後入市・1:{a.rr:g} RRR 離場", "",
         f"- 期間：{start} 至 {days[-1]['date']}（{len(tradable)} 個交易日；前半段到 {mid} 前）；成本每筆 {a.cost:g} 點；1 張",
         f"- 止蝕：入市當天日範圍 {a.q:.0%} 邊（固定）；目標：{a.rr:g} 倍風險；可持倉多日",
         f"- 輸入 SHA-256：15 分 K `{manifest['input']['bars_sha256'][:16]}…`；程式 `{manifest['script_sha256'][:16]}…`；規格見 README.md",
         "", f"**蛇蟠陣本身（同期）**：{len(sp)} 筆、每筆 {sp.mean():+.1f} 點、勝率 {(sp > 0).mean():.0%}、"
         f"RRR {sp[sp > 0].mean() / -sp[sp <= 0].mean():.2f}、總 {sp.sum():+,.0f}、最大回撤 {sdd:,.0f}", "", sw.HEAD]
    for m, trs in res.items():
        L.append(f"| {m} {CONFIGS[m]} " + sw.fmt(sw.stats(trs)))
    years = sorted({t["entry_date"][:4] for trs in res.values() for t in trs})
    L += ["", "| 設定 | 前半段 | 後半段 | " + " | ".join(years) + " | 做多 | 做空 | 離場原因 |",
          "|---|---|---|" + "---|" * len(years) + "---|---|---|"]
    for m, trs in res.items():
        def cell(sel):
            s = sw.stats(sel)
            return f"{s['mean']:+.1f}（{s['n']}）" if s.get("n") else "—"
        reasons = {}
        for t in trs:
            reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
        L.append(f"| {m} | {cell([t for t in trs if t['entry_date'] < mid])} | {cell([t for t in trs if t['entry_date'] >= mid])} | "
                 + " | ".join(cell([t for t in trs if t['entry_date'][:4] == y]) for y in years)
                 + f" | {cell([t for t in trs if t['side'] > 0])} | {cell([t for t in trs if t['side'] < 0])} | "
                 + "、".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])) + " |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
