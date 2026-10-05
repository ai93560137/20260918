"""R118 開閘雙倍張數的預期回報、回撤、RRR（2026-10-04，用戶問：「這個策略預期回報是多少回撤是多少？RRR」）。

把紙上交易三條策略（🐍 蛇蟠陣、🅱️＋跟蛇＋3R、🅰️＋跟蛇＋2R）按 R118 規則重算：
  入市日 R̂ ÷ 過去 250 日 R̂ 中位 ≥ 1.2 → 2 張，否則 1 張（「開閘傾斜」）；對照「固定 1 張」與「全部 2 張」。
  蛇的張數按**入市日**（上一個反手日）算——vol_gate.py 原本的蛇那段是按出場日分組（紀錄的日期是反手平倉那天），這裡兩種都列出來對照。
每條與三條合計：筆數、每年點數、勝率、平均賺／平均蝕（RRR）、獲利因子、最大回撤（逐日權益，按出場日歸入）、週 t、年化點數 ÷ 回撤、逐年。
資料：Futu 15 分 K（2024-06 起）與 HK50 差價合約（2022-08 起）；成本每筆 3 點。🅱️🅰️ 的逐筆用 r_sweep/<src>/trades/*.csv。
用法：python3 research/hsi_futures_range/gate_tilt.py --json 15 分 K 快取
輸出：research/hsi_futures_range/gate_tilt/REPORT.md、trades_<src>.csv（每筆附入市日 R̂、中位、比值、張數）
"""
import argparse, csv, json, math, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import snake_band as sb                                  # noqa: E402
import hk50_cfd                                          # noqa: E402

OUT = HERE / "gate_tilt"
COST, TH, LOOK, MIN = 3.0, 1.2, 250, 60
ZH = {"SNAKE": "🐍 蛇蟠陣", "B_S_R3": "🅱️＋跟蛇＋3R", "A_S_R2": "🅰️＋跟蛇＋2R"}


def prep(bars, daily):
    days = hl.build_days(bars, daily)
    rh = np.array([d["rhat"] for d in days])
    for i, d in enumerate(days):
        past = rh[max(0, i - LOOK):i]
        d["med"] = float(np.median(past)) if len(past) >= MIN else None
        d["ratio"] = d["rhat"] / d["med"] if d["med"] else None
        d["gate"] = bool(d["ratio"] >= TH) if d["ratio"] is not None else None
    return days


def snake_trades(days):
    """蛇：snake_run 記的日期是反手（出場）日；入市日 = 上一筆的出場日。第一筆沒有入市日 → 不計。"""
    _, _, tr = sb.snake_run(sb.snake_days(days), COST)
    out = []
    for i in range(1, len(tr)):
        out.append({"strat": "SNAKE", "entry_date": tr[i - 1][0], "exit_date": tr[i][0], "side": tr[i][1], "net": tr[i][2],
                    "exit_day_date": tr[i][0]})
    return out


def ledger_trades(path, strat):
    return [{"strat": strat, "entry_date": r["entry_date"], "exit_date": r["exit_date"], "side": 1 if r["side"] == "多" else -1,
             "net": float(r["net"]), "risk": float(r["risk"]), "r": float(r["r_multiple"])} for r in csv.DictReader(open(path, encoding="utf-8"))]


def attach(trades, days):
    by = {d["date"]: d for d in days}
    out = []
    for t in trades:
        d = by.get(t["entry_date"])
        if not d or d["gate"] is None:
            continue
        t = dict(t, rhat=d["rhat"], med=d["med"], ratio=d["ratio"], gate=d["gate"], lots=2 if d["gate"] else 1)
        out.append(t)
    return out


def equity_stats(trades, lots_fn, dates):
    """逐日權益（按出場日歸入）→ 回撤、週 t；逐筆 → 勝率、RRR、獲利因子。"""
    x = np.array([t["net"] * lots_fn(t) for t in trades])
    if len(x) == 0:
        return None
    daily = defaultdict(float)
    for t, v in zip(trades, x):
        daily[t["exit_date"]] += v
    ser = np.array([daily.get(d, 0.0) for d in dates])
    eq = np.cumsum(ser); dd = float((np.maximum.accumulate(eq) - eq).max())
    wk = defaultdict(float)
    for d, v in zip(dates, ser):
        y, w, _ = date.fromisoformat(d).isocalendar(); wk[f"{y}-W{w:02d}"] += v
    w = np.array(list(wk.values()))
    yrs = len(dates) / 250
    wins, losses = x[x > 0], x[x <= 0]
    aw = wins.mean() if len(wins) else 0.0; al = losses.mean() if len(losses) else 0.0
    return {"n": len(x), "total": x.sum(), "per_year": x.sum() / yrs, "win": (x > 0).mean(), "aw": aw, "al": al,
            "rrr": aw / -al if al else float("inf"), "pf": wins.sum() / -losses.sum() if losses.sum() else float("inf"),
            "dd": dd, "t_week": w.mean() / w.std(ddof=1) * math.sqrt(len(w)) if w.std(ddof=1) else 0.0,
            "calmar": (x.sum() / yrs) / dd if dd else float("inf"), "worst": x.min(), "ser": ser,
            "lots_avg": np.mean([lots_fn(t) for t in trades])}


def row(lab, s):
    return (f"| {lab} | {s['n']} | {s['lots_avg']:.2f} | **{s['per_year']:+,.0f}** | {s['win']:.0%} | {s['aw']:+,.0f}／{s['al']:+,.0f} | "
            f"{s['rrr']:.2f} | {s['pf']:.2f} | {s['dd']:,.0f} | {s['worst']:+,.0f} | {s['t_week']:+.2f} | {s['calmar']:.2f} |")


HEAD = ("| 設定 | 筆 | 平均張 | 每年點數 | 勝率 | 平均賺／平均蝕 | RRR | 獲利因子 | 最大回撤 | 最差一筆 | 週 t | 年點數÷回撤 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|")
MODES = (("固定 1 張", lambda t: 1), ("開閘傾斜（開閘日 2 張）", lambda t: t["lots"]), ("全部 2 張", lambda t: 2))


def section(src, days, ledger_dir):
    dates = [d["date"] for d in days if d["gate"] is not None]
    yrs = len(dates) / 250
    all_tr = {"SNAKE": attach(snake_trades(days), days),
              "B_S_R3": attach(ledger_trades(ledger_dir / "B_S_R3.csv", "B_S_R3"), days),
              "A_S_R2": attach(ledger_trades(ledger_dir / "A_S_R2.csv", "A_S_R2"), days)}
    for k in all_tr:
        all_tr[k] = [t for t in all_tr[k] if t["entry_date"] >= dates[0]]
    gate_days = sum(1 for d in days if d["gate"])
    L = [f"## {src}：{dates[0]} 至 {dates[-1]}，{len(dates)} 個有開閘指標的交易日（{yrs:.1f} 年），開閘日 {gate_days} 日（{gate_days / len(dates):.0%}）", ""]
    combo = {k: [] for k, _ in MODES}
    S = {}
    for strat, tr in all_tr.items():
        L += [f"### {ZH[strat]}（{len(tr)} 筆，開閘日入市 {sum(t['gate'] for t in tr)} 筆）", "", HEAD]
        for lab, fn in MODES:
            s = equity_stats(tr, fn, dates); S[(strat, lab)] = s
            L.append(row(lab, s))
            combo[lab].append(s["ser"])
        hi = np.array([t["net"] for t in tr if t["gate"]]); lo = np.array([t["net"] for t in tr if not t["gate"]])
        L += ["", f"開閘日入市每筆 {hi.mean():+,.0f}（{len(hi)} 筆、勝率 {(hi > 0).mean():.0%}）；其餘每筆 {lo.mean():+,.0f}（{len(lo)} 筆、勝率 {(lo > 0).mean():.0%}）"
              + (f"；t（兩組差） {(hi.mean() - lo.mean()) / math.sqrt(hi.var(ddof=1) / len(hi) + lo.var(ddof=1) / len(lo)):+.2f}" if len(hi) > 2 and len(lo) > 2 else ""), ""]
    L += ["### 三條合計（同時最多 3 條各 1 或 2 張）", "", "| 設定 | 每年點數 | 每年 HK$（×50） | 最大回撤（點） | 最大回撤 HK$ | 最差一日 | 週勝率 | 週 t | 年點數÷回撤 |", "|---|---|---|---|---|---|---|---|---|"]
    tot = {}
    for lab, _ in MODES:
        ser = np.sum(combo[lab], axis=0); eq = np.cumsum(ser); dd = float((np.maximum.accumulate(eq) - eq).max())
        wk = defaultdict(float)
        for d, v in zip(dates, ser):
            y, w, _ = date.fromisoformat(d).isocalendar(); wk[f"{y}-W{w:02d}"] += v
        w = np.array(list(wk.values()))
        tot[lab] = {"per_year": ser.sum() / yrs, "dd": dd, "ser": ser, "t": w.mean() / w.std(ddof=1) * math.sqrt(len(w)), "win_w": (w > 0).mean()}
        L.append(f"| {lab} | **{ser.sum() / yrs:+,.0f}** | {ser.sum() / yrs * 50:+,.0f} | {dd:,.0f} | {dd * 50:,.0f} | {ser.min():+,.0f} | {(w > 0).mean():.0%} | "
                 f"{tot[lab]['t']:+.2f} | {(ser.sum() / yrs) / dd:.2f} |")
    L += ["", "逐年（三條合計，點）：", "", "| 設定 | " + " | ".join(sorted({d[:4] for d in dates})) + " |", "|---|" + "---|" * len({d[:4] for d in dates})]
    for lab, _ in MODES:
        L.append(f"| {lab} | " + " | ".join(f"{sum(v for d, v in zip(dates, tot[lab]['ser']) if d[:4] == y):+,.0f}" for y in sorted({d[:4] for d in dates})) + " |")
    L.append("")
    # 蛇：按出場日分組（vol_gate 原本）對照
    _, _, raw = sb.snake_run(sb.snake_days(days), COST)
    by = {d["date"]: d for d in days}
    ex_hi = [p for d, _, p in raw if by.get(d) and by[d]["gate"]]; ex_lo = [p for d, _, p in raw if by.get(d) and by[d]["gate"] is False]
    en = all_tr["SNAKE"]
    L += ["核對——蛇的分組日：", "",
          f"- 按出場日（vol_gate.py 一、二節原本的分法）：開 {len(ex_hi)} 筆每筆 {np.mean(ex_hi):+,.0f}、關 {len(ex_lo)} 筆每筆 {np.mean(ex_lo):+,.0f}",
          f"- 按入市日（R118 實際的張數規則）：開 {sum(t['gate'] for t in en)} 筆每筆 {np.mean([t['net'] for t in en if t['gate']]):+,.0f}、"
          f"關 {sum(not t['gate'] for t in en)} 筆每筆 {np.mean([t['net'] for t in en if not t['gate']]):+,.0f}", ""]
    OUT.mkdir(exist_ok=True)
    with open(OUT / f"trades_{src.lower()}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["strat", "entry_date", "exit_date", "side", "net", "rhat", "med250", "ratio", "gate", "lots", "net_tilt"])
        for strat, tr in all_tr.items():
            for t in tr:
                w.writerow([strat, t["entry_date"], t["exit_date"], t["side"], f"{t['net']:.1f}", f"{t['rhat']:.1f}", f"{t['med']:.1f}", f"{t['ratio']:.3f}", int(t["gate"]), t["lots"], f"{t['net'] * t['lots']:.1f}"])
    return L, tot


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--json", required=True); a = ap.parse_args()
    cache = json.load(open(a.json))
    L = ["# R118 開閘傾斜：預期回報、回撤、RRR（gate_tilt.py）", "",
         f"- 規則：入市日 HAR 預測 R̂ ÷ 過去 {LOOK} 日 R̂ 中位 ≥ {TH} → 2 張，否則 1 張；對照固定 1 張、全部 2 張。成本每筆 {COST:g} 點（每張）。",
         "- 回撤用逐日權益（盈虧按出場日歸入）；週 t = 週盈虧平均 ÷ 標準誤；RRR = 平均賺 ÷ 平均蝕；獲利因子 = 總賺 ÷ 總蝕。",
         "- 蛇的張數按入市日（上一次反手那天的開閘狀態）；第一筆沒有入市日不計。逐筆核對檔：trades_futu.csv、trades_hk50.csv。", ""]
    secs = {}
    for src, (bars, daily), ledger in (("Futu", (cache["bars"], cache["daily"]), HERE / "r_sweep" / "futu" / "trades"),
                                       ("HK50", hk50_cfd.load(), HERE / "r_sweep" / "hk50" / "trades")):
        sec, tot = section(src, prep(bars, daily), ledger)
        L += sec; secs[src] = tot
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
