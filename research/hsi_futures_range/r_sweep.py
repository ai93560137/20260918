"""R 測試：訊號版（hl_signal）與對照（S0）在不同止賺倍數下的期望值——找一個「R 夠大、期望值為正」的組合。

用戶要求（2026-10-04）：低勝率不重要，最緊要 R 夠大、正期望值，所以 R 要再測。
兩個數據來源：
  futu  恒指即月期貨 15 分 K（Futu，2023-09 起；GCS archive/futu_k_15m）
  hk50  HK50 差價合約 15 分 K（蛇蟠陣分支 data/HK50_M15.csv.gz，2022-08 起；hk50_cfd.py 轉成香港時間）
規則與 hl_signal.py 完全相同，只改止賺倍數：RR ∈ {1, 1.5, 2, 3, 4, 5, 8, 0}，0 = 不設目標（只靠止蝕或蛇反手離場）。
設定：<訊號>_<方向>_R<倍數>（例 A_S_R3），S0_R<倍數> 為對照（跟蛇、開市就入）。

輸出 research/hsi_futures_range/r_sweep/<來源>/：REPORT.md、manifest.json、signals.csv、預測位、蛇反手、trades/*.csv
核對：python3 research/hsi_futures_range/r_sweep.py --source futu|hk50 --verify
用法：python3 research/hsi_futures_range/r_sweep.py --source futu [--json 15 分 K 快取]；--source hk50 不需快取
"""
import argparse, hashlib, json, math, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import snake_week as sw                                  # noqa: E402
import hl_signal as hs                                   # noqa: E402
import hl_both as hb                                     # noqa: E402
import hk50_cfd                                          # noqa: E402

RRS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 8.0, 0.0)      # 用戶 2026-10-04：高勝率＋小 R（1:0.5）也可以正期望值
STRATS = ("A_S", "B_S", "A_F", "B_F")
SRC_ZH = {"futu": "恒指即月期貨（Futu）", "hk50": "HK50 差價合約（蛇蟠陣分支）"}


def rr_tag(rr):
    return "R無" if not rr else f"R{rr:g}"


def load(source, path):
    if source == "hk50":
        return hk50_cfd.load()
    return sw.load(path)


def run(source, bars, daily_k, cost, q=0.95):
    days, sdays, before, flips, snake_trades, dl, wl = sw.build(bars, daily_k, cost)
    rows, trig = hs.signals(days, dl)
    res = {}
    for strat in STRATS:
        k, dr = strat.split("_")
        for rr in RRS:
            res[f"{strat}_{rr_tag(rr)}"] = sw.add_sessions(
                hs.simulate(days, dl, wl, before, flips, trig[k], dr, q, rr, cost), days)
    for rr in RRS:
        res[f"S0_{rr_tag(rr)}"] = sw.add_sessions(hb.simulate(days, dl, wl, before, flips, "S0", q, rr, cost), days)
    return days, before, flips, snake_trades, dl, wl, rows, trig, res


def write(out, source, bars, daily_k, cost, days, flips, snake_trades, dl, wl, rows, trig, res, q=0.95):
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
    manifest = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "git_head": sw.git_head(),
                "source": source, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "engine_sha256": {f: hashlib.sha256((HERE / f).read_bytes()).hexdigest()
                                  for f in ("snake_week.py", "high_low_in.py", "hl_both.py", "hl_signal.py", "hk50_cfd.py")},
                "input": {"bars": len(bars), "bars_sha256": sw.sha256_json(sorted(bars, key=lambda b: b["time_key"])),
                          "daily": len(daily_k), "daily_sha256": sw.sha256_json(sorted(daily_k, key=lambda b: str(b["time_key"]))),
                          "first_bar": bars[0]["time_key"], "last_bar": bars[-1]["time_key"]},
                "params": {"cost_per_round_trip": cost, "stop_band_q": q, "rr_grid": list(RRS)},
                "trigger_days": {k: len(v) for k, v in trig.items()},
                "configs": {m: {"trades": len(t), "net_total": round(sum(x["net"] for x in t), 2)} for m, t in res.items()}}
    json.dump(manifest, open(out / "manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return manifest


def report(source, days, snake_trades, res, manifest, cost, q=0.95):
    start = min(t["entry_date"] for trs in res.values() for t in trs)
    tradable = [d["date"] for d in days if d["date"] >= start]
    mid = tradable[len(tradable) // 2]
    sp = np.array([t[2] for t in snake_trades if t[0] >= start])
    years = sorted({t["entry_date"][:4] for trs in res.values() for t in trs})
    L = [f"# R 測試：{SRC_ZH[source]}", "",
         f"- 期間：{start} 至 {days[-1]['date']}（{len(tradable)} 個交易日；前半段到 {mid} 前）；成本每筆 {cost:g} 點；1 張",
         f"- 規則同 hl_signal（{'九成' if q == 0.95 else '八成'}日範圍止蝕 q={q}、固定；可持倉多日；S 跟蛇反手平倉）；只改止賺倍數 R（R無 = 不設目標）",
         f"- 輸入 SHA-256：15 分 K `{manifest['input']['bars_sha256'][:16]}…`（{manifest['input']['first_bar']} → {manifest['input']['last_bar']}）",
         f"- 觸發日：" + "、".join(f"{k} {v} 天" for k, v in manifest["trigger_days"].items()),
         "", f"**蛇蟠陣本身（同期）**：{len(sp)} 筆、每筆 {sp.mean():+.1f} 點、勝率 {(sp > 0).mean():.0%}、"
         f"RRR {sp[sp > 0].mean() / -sp[sp <= 0].mean():.2f}、t {sp.mean() / sp.std(ddof=1) * math.sqrt(len(sp)):+.2f}、總 {sp.sum():+,.0f}", ""]
    for group in ("A_S", "B_S", "A_F", "B_F", "S0"):
        L += [f"## {group}", "", "| R | 交易 | 勝率 | 平均賺／平均蝕 | RRR | **期望值／筆** | **期望值（R）** | 盈虧比 | t 值 | 總點數／最大回撤 | 前半段／後半段 | "
              + "／".join(years) + " |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for rr in RRS:
            trs = res[f"{group}_{rr_tag(rr)}"]
            s = sw.stats(trs)
            if not s.get("n"):
                L.append(f"| {rr_tag(rr)} | 0 | — | — | — | — | — | — | — | — | — | — |"); continue
            def m(sel):
                x = sw.stats(sel)
                return f"{x['mean']:+.0f}" if x.get("n") else "—"
            L.append(f"| {rr_tag(rr)} | {s['n']} | {s['win']:.0%} | +{s['avg_win']:,.0f}／{s['avg_loss']:,.0f} | {s['rrr']:.2f} | "
                     f"**{s['mean']:+.1f}** | **{s['R']:+.3f}** | {s['pf']:.2f} | {s['t']:+.2f} | {s['total']:+,.0f}／{s['dd']:,.0f} | "
                     f"{m([t for t in trs if t['entry_date'] < mid])}／{m([t for t in trs if t['entry_date'] >= mid])} | "
                     + "／".join(m([t for t in trs if t['entry_date'][:4] == y]) for y in years) + " |")
        L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("futu", "hk50"), required=True)
    ap.add_argument("--json", help="futu：15 分 K 快取 {bars, daily}")
    ap.add_argument("--cost", type=float, default=3.0)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--q", type=float, default=0.95, help="止蝕用哪個日範圍邊（0.95 九成、0.9 八成）；非 0.95 輸出到 r_sweep/<來源>_q<q>/，獨立核對只支援 0.95")
    a = ap.parse_args()
    out = HERE / "r_sweep" / (a.source if a.q == 0.95 else f"{a.source}_q{int(round(a.q * 100))}")
    bars, daily_k = load(a.source, a.json)
    if a.verify:
        import snake_week_verify as v
        sys.exit(v.verify(bars, daily_k, out))
    days, before, flips, snake_trades, dl, wl, rows, trig, res = run(a.source, bars, daily_k, a.cost, a.q)
    manifest = write(out, a.source, bars, daily_k, a.cost, days, flips, snake_trades, dl, wl, rows, trig, res, a.q)
    text = report(a.source, days, snake_trades, res, manifest, a.cost, a.q)
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
