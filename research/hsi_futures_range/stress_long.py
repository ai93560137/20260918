"""投資人問（2026-10-04）：尾部日連續出現怎麼辦？沽勒式的倉位最多回撤多少？

真實期權數據只有 51 週、沒有大跌週，所以用恒指日線 36 年（1990 起）做合成壓力測試：
  每週（週五收市）沽下週到期的 1σ 勒式：σ_週 = 過去 20 日標準差 × √5；行使價 = 收市 × (1 ± σ_週)；
  權利金用 Black-76 計，IV = 過去 20 日波幅 × IV_MULT（真實數據 IV ÷ 之後實際 ≈ 1.03）；到期按下週五收市結算。
  不對沖；每日對沖 = 每天收市算淨 Delta，|淨 Delta| > 0.5 就用期貨調回 0（日線只能每日一次，比 15 分 K 粗）；
  2 倍權利金止蝕 = 任何一天收市內在值 ≥ 2 × 權利金就平倉。
  盈虧以「指數百分比」計，再換成今天（恒指 24,000）的點數與港元（HK$50／點）。
另報：尾部日（|日變動| > 1.65σ）的連續出現：連續 2 日、3 日的次數，最長連續，一週內 ≥ 2 個尾部日的週數。
用法：python3 research/hsi_futures_range/stress_long.py --hsi hsi.csv
輸出：research/hsi_futures_range/stress_long/REPORT.md、weekly.csv
"""
import argparse, csv, math
from datetime import date
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "stress_long"
IV_MULT = 1.03
LEVEL = 24000.0
PT = 50.0
COST_LEG_PCT = 4 / LEVEL                  # 每腳 4 點（今天的水平）→ 百分比


def ncdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def black(F, K, sig, T, call):
    if T <= 0 or sig <= 0:
        return max(0.0, F - K) if call else max(0.0, K - F)
    d1 = (math.log(F / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T)); d2 = d1 - sig * math.sqrt(T)
    return F * ncdf(d1) - K * ncdf(d2) if call else K * ncdf(-d2) - F * ncdf(-d1)


def delta(F, K, sig, T, call):
    if T <= 0 or sig <= 0:
        return (1.0 if F > K else 0.0) if call else (-1.0 if F < K else 0.0)
    d1 = (math.log(F / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    return ncdf(d1) if call else ncdf(d1) - 1.0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--hsi", required=True); a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(a.hsi, encoding="utf-8")) if float(r["High"]) != float(r["Low"]) and r["Date"] >= "1990-01-01"]
    d = [r["Date"] for r in rows]; c = np.array([float(r["Close"]) for r in rows])
    ret = np.r_[np.nan, np.diff(np.log(c))]
    sig20 = np.array([np.std(ret[max(1, i - 20):i], ddof=1) if i > 21 else np.nan for i in range(len(c))])
    # 週：以 ISO 週分組，入市 = 該週最後一個交易日，到期 = 下一週最後一個交易日
    wk = {}
    for i, s in enumerate(d):
        y, w, _ = date.fromisoformat(s).isocalendar()
        wk.setdefault(f"{y}-W{w:02d}", []).append(i)
    keys = sorted(wk)
    weekly = []
    for a_, b_ in zip(keys[:-1], keys[1:]):
        i0, i1 = wk[a_][-1], wk[b_][-1]
        if np.isnan(sig20[i0]) or i1 - i0 < 3:
            continue
        F0 = c[i0]; sw = sig20[i0] * math.sqrt(i1 - i0); iv = sig20[i0] * IV_MULT * math.sqrt(252)
        T0 = (i1 - i0) / 252
        kp, kc = F0 * (1 - sw), F0 * (1 + sw)
        credit = (black(F0, kc, iv, T0, True) + black(F0, kp, iv, T0, False)) / F0
        payoff = (max(0.0, kp - c[i1]) + max(0.0, c[i1] - kc)) / F0
        unhedged = credit - payoff - 2 * COST_LEG_PCT
        # 每日對沖（收市）
        hedge = 0.0; hpnl = 0.0; last = F0; trades = 0
        for j in range(i0 + 1, i1 + 1):
            px = c[j]; hpnl += hedge * (px - last) / F0; last = px
            T = (i1 - j) / 252
            net = -delta(px, kc, iv, T, True) - delta(px, kp, iv, T, False)
            if abs(net + hedge) > 0.5 and j < i1:
                target = -round(net / 0.2) * 0.2; trades += abs(target - hedge) / 0.2; hedge = target
        hedged = unhedged + hpnl - trades * 15 / PT / LEVEL          # 小型期貨每張 HK$15 → 指數百分比
        # 2 倍權利金止蝕
        stopped = None
        for j in range(i0 + 1, i1 + 1):
            intr = (max(0.0, kp - c[j]) + max(0.0, c[j] - kc)) / F0
            if intr >= 2 * credit:
                stopped = credit - intr - 2 * COST_LEG_PCT; break
        stop_pnl = stopped if stopped is not None else unhedged
        weekly.append({"week": a_, "entry": d[i0], "expiry": d[i1], "move_pct": (c[i1] / F0 - 1) * 100, "sigma_w_pct": sw * 100,
                       "credit_pct": credit * 100, "unhedged": unhedged * 100, "hedged": hedged * 100, "stop2x": stop_pnl * 100,
                       "hedge_trades": trades})
    OUT.mkdir(exist_ok=True)
    with open(OUT / "weekly.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(weekly[0])); w.writeheader(); w.writerows(weekly)
    L = [f"# 36 年合成壓力測試：每週沽 1σ 勒式（stress_long.py）", "",
         f"- {len(weekly)} 週（{weekly[0]['entry']} 至 {weekly[-1]['expiry']}）；IV = 20 日波幅 × {IV_MULT}；盈虧用指數百分比，點數按恒指 {LEVEL:,.0f}、HK$50／點換算；1 張大合約", ""]

    def pts(x):
        return x / 100 * LEVEL

    for name, key in (("不對沖", "unhedged"), ("每日 Delta 對沖（門檻 0.5）", "hedged"), ("2 倍權利金止蝕", "stop2x")):
        x = np.array([r[key] for r in weekly]); eq = np.cumsum(x); dd = np.maximum.accumulate(eq) - eq
        worst_i = int(np.argmin(x)); dd_i = int(np.argmax(dd)); peak_i = int(np.argmax(eq[:dd_i + 1])) if dd_i else 0
        # 最長連續虧損
        run = best = 0; run_loss = 0.0; worst_run = 0.0
        for v in x:
            if v < 0:
                run += 1; run_loss += v; best = max(best, run); worst_run = min(worst_run, run_loss)
            else:
                run = 0; run_loss = 0.0
        L += [f"## {name}", "",
              f"- 每週平均 {x.mean():+.3f}%（{pts(x.mean()):+.0f} 點）、賺錢週 {(x > 0).mean():.0%}、週標準差 {x.std(ddof=1):.2f}%、t {x.mean() / x.std(ddof=1) * math.sqrt(len(x)):+.2f}",
              f"- 最差一週 {x.min():+.2f}%（{pts(x.min()):+,.0f} 點 = HK${pts(x.min()) * PT:+,.0f}），{weekly[worst_i]['entry']} 起那週，指數變動 {weekly[worst_i]['move_pct']:+.1f}%",
              f"- **最大回撤 {dd.max():.2f}%（{pts(dd.max()):,.0f} 點 = HK${pts(dd.max()) * PT:,.0f}）**，由 {weekly[peak_i]['entry']} 到 {weekly[dd_i]['expiry']}",
              f"- 最長連續虧損 {best} 週；連續虧損期最大累計 {worst_run:+.2f}%（{pts(worst_run):+,.0f} 點）",
              f"- 虧損超過 1% 指數（{pts(1):,.0f} 點）的週數 {(x < -1).sum()}；超過 2% 的 {(x < -2).sum()}；超過 4% 的 {(x < -4).sum()}", ""]
        L += ["| 年 | 週數 | 全年（%） | 最差一週（%） |", "|---|---|---|---|"]
        for y in sorted({r["entry"][:4] for r in weekly}):
            xs = np.array([r[key] for r in weekly if r["entry"][:4] == y])
            L.append(f"| {y} | {len(xs)} | {xs.sum():+.1f} | {xs.min():+.2f} |")
        L.append("")
    worst = sorted(weekly, key=lambda r: r["unhedged"])[:12]
    L += ["## 最差 12 週（不對沖／每日對沖／止蝕，指數百分比）", "", "| 入市週五 | 指數變動 | 1σ（週） | 權利金 | 不對沖 | 每日對沖 | 2 倍止蝕 |", "|---|---|---|---|---|---|---|"]
    for r in worst:
        L.append(f"| {r['entry']} | {r['move_pct']:+.1f}% | {r['sigma_w_pct']:.1f}% | {r['credit_pct']:.2f}% | {r['unhedged']:+.2f}% | {r['hedged']:+.2f}% | {r['stop2x']:+.2f}% |")
    # 尾部日連續出現
    z = ret / sig20
    tail = np.abs(z) >= 1.65
    idx = [i for i in range(22, len(tail)) if tail[i]]
    runs = []; run = 1
    for p_, q_ in zip(idx[:-1], idx[1:]):
        if q_ == p_ + 1:
            run += 1
        else:
            runs.append(run); run = 1
    runs.append(run)
    nxt = np.mean([tail[i + 1] for i in idx if i + 1 < len(tail)])
    wk_tail = {}
    for i in idx:
        y, w, _ = date.fromisoformat(d[i]).isocalendar(); wk_tail[f"{y}-W{w:02d}"] = wk_tail.get(f"{y}-W{w:02d}", 0) + 1
    L += ["", "## 尾部日（|日變動| > 1.65σ）連續出現", "",
          f"- 36 年共 {len(idx)} 個尾部日（{len(idx) / (len(tail) - 22):.1%}）；尾部日翌日仍是尾部日的機會 {nxt:.0%}（平常 {len(idx) / (len(tail) - 22):.0%}）",
          f"- 連續 2 日 {sum(1 for r in runs if r >= 2)} 次、連續 3 日 {sum(1 for r in runs if r >= 3)} 次、連續 4 日以上 {sum(1 for r in runs if r >= 4)} 次；最長連續 {max(runs)} 日",
          f"- 一週內有 ≥ 2 個尾部日的週：{sum(1 for v in wk_tail.values() if v >= 2)} 週、≥ 3 個：{sum(1 for v in wk_tail.values() if v >= 3)} 週（共 {len(keys)} 週）",
          "- 尾部日成群出現的時期：1997–98 亞洲金融風暴、2008 金融海嘯、2015 年 8 月、2020 年 3 月、2024 年 9–10 月、2025 年 4 月"]
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
