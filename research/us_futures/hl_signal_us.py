"""美股指數期貨（CME 全段 23 小時交易日）：「高位／低位已經出現」A／B／C 訊號回測（日、週、月），2026-10-08。

與恒指同一套程式（research/hsi_futures_range/high_low_in.py），只換市場設定：
  交易日 = 紐約前一天 18:00 至當天 17:00（用戶決定「一天 = 整段 23 小時」，與 main.MARKETS['US'] 相同）；
  日內 15 分 K 的變異比例、HAR 波幅預測全部逐日前推（不偷看）；
  C 時間點：日看 12:00（RTH 中午）／16:00（RTH 收市，之後只剩 1 小時）；週第 2／3／4 個交易日；月第 5／10／15 個交易日。
數據：--src usa500（Dukascopy USA500.IDX 差價合約 15 分 K，全段 2018-04 起）、nas100（MT5 NAS100 差價合約 15 分 K，2022-08 起）。
用法：python3 research/us_futures/hl_signal_us.py [--src usa500,nas100] [--periods day,week,month]
輸出：research/us_futures/hl_signal_us/REPORT.md、<src>_signals_<kind>.csv（每段每個主要策略的通知紀錄，核對用）、
      <src>_profile_15m.json（最近 250 個交易日各 15 分鐘時段的變異比例，給伺服器 US 日內訊號用）。
"""
import argparse, csv, json, math, sys
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(REPO / "research" / "hsi_futures_range"))
import high_low_in as hl                                  # noqa: E402
import backtest as bt                                     # noqa: E402
import dukascopy_cfd, nas100_cfd                          # noqa: E402

OUT = HERE / "hl_signal_us"
SRC = {"usa500": ("ES（USA500.IDX 差價合約，Dukascopy 15 分 K）", lambda: dukascopy_cfd.load("usa500idxusd")),
       "nas100": ("NQ（NAS100 差價合約，MT5 15 分 K）", lambda: nas100_cfd.load())}
DAY_CUTS = ("12:00", "16:00")
MAIN_STRATS = {"day": [("B", 0.05), ("A", 0.8, 0.5), ("C", "16:00", 0.4)],
               "week": [("B", 0.05), ("A", 0.8, 0.5), ("C", 4, 0.4)],
               "month": [("B", 0.05), ("A", 0.8, 0.5), ("C", 15, 0.4)]}


# ---- 市場設定：把 high_low_in 的港股部分換成美股 ----
def session_minutes_us(hhmm):
    """交易日內的分鐘數（紐約 18:00 = 0，翌日 17:00 = 1380）。"""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return ((h - 18) % 24) * 60 + m


def grid_us(kind):
    a = [("A", al, be) for al in (0.6, 0.8, 1.0, 1.2) for be in (0.2, 0.3, 0.4, 0.5)]
    b = [("B", p) for p in (0.05, 0.10, 0.15, 0.20, 0.30)]
    cuts = {"day": DAY_CUTS, "week": (2, 3, 4), "month": (5, 10, 15)}[kind]
    c = [("C", cut, be) for cut in cuts for be in (0.1, 0.2, 0.3, 0.4)]
    return a + b + c


hl.session_minutes = session_minutes_us
hl.grid = grid_us


def build_days(bars, daily):
    """同 high_low_in.build_days，但交易日直接用 K 線的 session 欄（載入時已按 CME 全段分好）。"""
    by_day = defaultdict(dict)
    for b in bars:
        by_day[b["session"]][b["time_key"]] = b
    D, C, r, F = bt.run(bt.to_rows(daily), 60)
    har = F["HAR（對數，平均）"]
    days = []
    for t in range(1, len(D)):
        d = D[t]
        if np.isnan(har[t]) or d not in by_day or len(by_day[d]) < 4:
            continue
        seq = [by_day[d][k] for k in sorted(by_day[d], key=lambda k: session_minutes_us(k[11:16]))]
        days.append({"date": d, "bars": seq, "rhat": har[t] * C[t - 1], "ref": C[t - 1]})
    window, sums, counts = deque(), defaultdict(float), defaultdict(int)
    profile = {}
    for day in days:
        mean = {k: sums[k] / counts[k] for k in sums if counts[k] >= 5}
        total = sum(mean.values())
        profile = {k: v / total for k, v in mean.items()} if total else {}
        shares = [mean.get(b["time_key"][11:16], 0.0) / total if total else 1.0 / len(day["bars"]) for b in day["bars"]]
        day["rem"] = list(np.cumsum(shares[::-1])[::-1][1:]) + [0.0]
        prev, sq = day["bars"][0]["open"], {}
        for b in day["bars"]:
            sq[b["time_key"][11:16]] = math.log(b["close"] / prev) ** 2
            prev = b["close"]
        window.append(sq)
        for k, v in sq.items():
            sums[k] += v; counts[k] += 1
        if len(window) > 250:
            for k, v in window.popleft().items():
                sums[k] -= v; counts[k] -= 1
    return days, profile


def records(periods, strat, side):
    rows = []
    for per in periods:
        idx, ext, dist = hl.run_period(per, strat, side)
        if idx is None:
            rows.append({"period": per["key"], "signal": "", "ext": "", "dist": "", "final": "", "hit": ""}); continue
        later = [b for b, _ in per["bars"][idx + 1:]]
        final = max([ext] + [b["high"] for b in later]) if side == "high" else min([ext] + [b["low"] for b in later])
        rows.append({"period": per["key"], "signal": per["bars"][idx][0]["time_key"], "ext": ext, "dist": round(dist, 2),
                     "final": final, "hit": int(final == ext)})
    return rows


def yearly(periods, strat, side):
    by = defaultdict(lambda: [0, 0, 0])
    for per, r in zip(periods, records(periods, strat, side)):
        y = per["key"][:4]; by[y][0] += 1
        if r["signal"]:
            by[y][1] += 1; by[y][2] += r["hit"]
    return by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="usa500,nas100")
    ap.add_argument("--periods", default="day,week,month")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    L = ["# 美股指數期貨「高位／低位已經出現」A／B／C 訊號回測（hl_signal_us.py）", "",
         "與恒指同一套程式（high_low_in.py）：每根 15 分 K 收市時只用當時已知的資料判斷，每邊每段只通知第一次；"
         "交易日 = CME 全段（紐約前一天 18:00 至當天 17:00）；A、C 參數在前半段挑（通知率 ≥ 30% 中準確率最高），後半段報成績；"
         "B 不用挑參數。C 的時間點：日 12:00／16:00（RTH 收市，之後只剩 1 小時）；週第 2／3／4 個交易日收市；月第 5／10／15 個。", "",
         "準確率 = 通知之後到這段結束，高位（低位）都沒有再被突破的比例（附 95% Wilson 區間）。", ""]
    for src in a.src.split(","):
        zh, load = SRC[src]
        bars, daily = load()
        days, profile = build_days(bars, daily)
        json.dump(profile, open(OUT / f"{src}_profile_15m.json", "w"), indent=1)
        L += [f"## {zh}", "", f"- {len(days)} 個交易日有 HAR 預測與日內 K（{days[0]['date']} 至 {days[-1]['date']}），每天中位 "
              f"{int(np.median([len(d['bars']) for d in days]))} 根 15 分 K；平均 R̂ {np.mean([d['rhat'] for d in days]):,.1f} 點。"]
        for kind in a.periods.split(","):
            periods = hl.build_periods(days, kind)
            text, _ = hl.report(periods, kind, src)
            L.append(text)
            # 主要策略全樣本逐年 + 紀錄 CSV
            with open(OUT / f"{src}_signals_{kind}.csv", "w", newline="") as fh:
                w = csv.writer(fh); w.writerow(["period", "side", "strat", "signal_bar_close", "ext", "dist", "final", "hit"])
                for strat in MAIN_STRATS[kind]:
                    for side in ("high", "low"):
                        for r in records(periods, strat, side):
                            w.writerow([r["period"], side, hl.name(strat, kind), r["signal"], r["ext"], r["dist"], r["final"], r["hit"]])
            L += ["", f"主要策略全樣本逐年（{hl.PERIOD_ZH[kind]}；每格 = 通知率／準確率）：", ""]
            years = sorted({p["key"][:4] for p in periods})
            L.append("| 策略 | 邊 | " + " | ".join(years) + " |"); L.append("|---|---|" + "---|" * len(years))
            for strat in MAIN_STRATS[kind]:
                for side in ("high", "low"):
                    by = yearly(periods, strat, side)
                    cells = [f"{by[y][1] / by[y][0]:.0%}／{by[y][2] / by[y][1]:.0%}" if by[y][1] else "—" for y in years]
                    L.append(f"| {hl.name(strat, kind)} | {'高' if side == 'high' else '低'} | " + " | ".join(cells) + " |")
            L.append("")
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
