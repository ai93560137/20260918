"""美股指數期貨第一步（CME 全段 23 小時交易日）：波幅預測、高低位校準、蛇蟠陣（2026-10-05）。
來源：--src nas100（MT5 NAS100 差價合約 15 分 K，2022-08 起）或 usa500（Dukascopy USA500.IDX 差價合約 15 分 K，全段數據 2018-04 起）。

與恒指同一套程式：HAR(1,5,22) 對數波幅預測（main.har_forecasts）、高低位 = 昨收 ± 比例 × R̂（main.futu_accuracy，逐日前推，
預計範圍 2%／98% 分位）、週／月同理；蛇蟠陣 = 前 N 個交易日最高／最低做通道，15 分 K 觸價反手（snake_band.snake_run）。
成本：蛇每筆來回 1.5 點（NQ 一跳 0.25 點 = 5 美元，加佣金與滑點）。
用法：python3 research/us_futures/range_step1.py --src usa500
輸出：research/us_futures/<src>_range/REPORT.md、daily_forecast.csv（每天預測高低與實際）、snake_trades.csv
"""
import csv, math, os, sys, types
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "research" / "hsi_futures_range"))
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "x")
import google, google.cloud                                      # noqa: E402  main.py 的 GCS／genai 依賴用假模組
_sm = types.ModuleType("google.cloud.storage"); _sm.Client = lambda *a, **k: None; sys.modules["google.cloud.storage"] = _sm; google.cloud.storage = _sm
_g = types.ModuleType("google.genai"); _g.Client = lambda *a, **k: None; _g.types = types.SimpleNamespace(); sys.modules["google.genai"] = _g
_e = types.ModuleType("google.api_core.exceptions"); _e.PreconditionFailed = type("PC", (Exception,), {}); _e.NotFound = KeyError
_ac = types.ModuleType("google.api_core"); _ac.exceptions = _e; sys.modules["google.api_core"] = _ac; sys.modules["google.api_core.exceptions"] = _e
import main                                                      # noqa: E402
import snake_band as sb                                          # noqa: E402
import nas100_cfd, dukascopy_cfd                                 # noqa: E402
import argparse                                                  # noqa: E402

SRC = {"nas100": {"zh": "NQ（NAS100 差價合約，MT5）", "cost": 1.5, "load": lambda: nas100_cfd.load(), "hsi_pct": "恒指期貨對照 2.0% 左右"},
       "usa500": {"zh": "ES（USA500.IDX 差價合約，Dukascopy）", "cost": 0.75, "load": lambda: dukascopy_cfd.load("usa500idxusd"), "hsi_pct": "恒指期貨對照 2.0%、NQ 1.85%"}}


def acc_line(kind, a, unit):
    s = (f"| {kind} | {a['n']} | {a.get('hit_range_rate')}% | {a['hit_rate']}% | {a.get('hit_high_rate')}%／{a.get('hit_low_rate')}% | "
         f"{a.get('mae_high')}／{a.get('mae_low')} | {a.get('within_rate')}%（{a.get('ok_pct')}%） |")
    return s


def snake_stats(trades, dates_by_year=None):
    x = np.array([t[2] for t in trades]); wins, losses = x[x > 0], x[x <= 0]
    eq = np.cumsum(x); dd = float((np.maximum.accumulate(eq) - eq).max())
    return {"n": len(x), "mean": x.mean(), "win": (x > 0).mean(), "aw": wins.mean() if len(wins) else 0, "al": losses.mean() if len(losses) else 0,
            "t": x.mean() / x.std(ddof=1) * math.sqrt(len(x)), "total": x.sum(), "dd": dd}


def main_():
    ap = argparse.ArgumentParser(); ap.add_argument("--src", default="nas100", choices=list(SRC)); a = ap.parse_args()
    cfg = SRC[a.src]; OUT = HERE / f"{a.src}_range"; SNAKE_COST = cfg["cost"]
    bars, daily = cfg["load"]()
    rows = main.futu_range_rows(daily)
    har = main.har_forecasts(rows)
    acc = main.futu_accuracy(rows, har)
    yrs = (len(rows)) / 252
    L = [f"# {cfg['zh']}，CME 全段 23 小時：波幅預測、高低位、蛇蟠陣（range_step1.py --src {a.src}）", "",
         f"- {daily[0]['time_key'][:10]} 至 {daily[-1]['time_key'][:10]}，{len(daily)} 個交易日（{yrs:.1f} 年）；一天 = CME 全段，紐約前一天 18:00 至當天 17:00；"
         f"平均全日波幅 {np.mean([r['range'] for r in rows]):,.0f} 點（{np.mean([r['range_pct'] for r in rows if r['range_pct']]):.2f}%），"
         f"{cfg['hsi_pct']}。", "",
         "## 一、HAR 波幅預測與高低位（與恒指同一程式、逐日前推）", "",
         "| 期間 | 段數 | 波幅落在 80% 範圍 | 高、低都落在預計範圍 | 高／低各自 | 高／低平均差（點） | 高、低都在門檻內（門檻） |", "|---|---|---|---|---|---|---|"]
    for kind, unit in (("day", "天"), ("week", "週"), ("month", "月")):
        L.append(acc_line({"day": "今日", "week": "本週", "month": "本月"}[kind], acc[kind], unit))
    d = acc["day"]
    recs = [r for r in d["records"] if r.get("err_high") is not None]
    pct_h = np.array([abs(r["err_high"]) / r["high"] * 100 for r in recs]); pct_l = np.array([abs(r["err_low"]) / r["low"] * 100 for r in recs])
    L += ["", f"- 日：高位誤差中位 {np.median(pct_h):.2f}%、低位 {np.median(pct_l):.2f}%（恒指 0.52%／0.52%）；兩邊都在 1% 內 {d.get('within_rate')}%（恒指 65%）、"
          f"落在範圍 {d['hit_rate']}%（恒指 92%）", "", "逐年（日，兩邊都落在預計範圍 ／ 都在 1% 內）：", "",
          "| 年 | 天數 | 落在範圍 | 1% 內 | 高位平均差 | 低位平均差 |", "|---|---|---|---|---|---|"]
    for y in sorted({r["key"][:4] for r in recs}):
        sel = [r for r in recs if r["key"][:4] == y]
        L.append(f"| {y} | {len(sel)} | {np.mean([r['hit'] for r in sel]):.0%} | "
                 f"{np.mean([abs(r['err_high']) / r['high'] * 100 <= 1 and abs(r['err_low']) / r['low'] * 100 <= 1 for r in sel]):.0%} | "
                 f"{np.mean([abs(r['err_high']) for r in sel]):.0f} | {np.mean([abs(r['err_low']) for r in sel]):.0f} |")
    # 蛇蟠陣：交易日 = 整段，sdays 直接按交易日分組
    by = {}
    for b in bars:
        by.setdefault(b["session"], []).append(b)
    sdays = [(k, sorted(v, key=lambda b: b["time_key"])) for k, v in sorted(by.items())]
    L += ["", f"## 二、蛇蟠陣（前 N 個交易日高／低通道，15 分 K 觸價反手，成本每筆 {SNAKE_COST:g} 點）", "",
          "| N | 筆 | 每筆（點） | 每筆（%） | 勝率 | 平均賺／蝕 | RRR | t | 總點數 | 最大回撤 |", "|---|---|---|---|---|---|---|---|---|---|"]
    lvl = np.mean([r["close"] for r in rows])
    trades3 = None
    for n in (2, 3, 5, 10, 20):
        sb.LOOKBACK = n
        _, _, tr = sb.snake_run(sdays, SNAKE_COST)
        s = snake_stats(tr)
        if n == 3:
            trades3 = tr
        L.append(f"| {n} | {s['n']} | **{s['mean']:+.1f}** | {s['mean'] / lvl * 100:+.3f} | {s['win']:.0%} | {s['aw']:+.0f}／{s['al']:+.0f} | "
                 f"{(s['aw'] / -s['al']) if s['al'] else float('nan'):.2f} | {s['t']:+.2f} | {s['total']:+,.0f} | {s['dd']:,.0f} |")
    sb.LOOKBACK = 3
    L += ["", "N=3 逐年（點）：" + "；".join(f"{y} {sum(t[2] for t in trades3 if t[0][:4] == y):+,.0f}（{sum(1 for t in trades3 if t[0][:4] == y)} 筆）"
                                        for y in sorted({t[0][:4] for t in trades3})),
          "", f"恒指對照（snake_band.py，Futu 3 年）：N=3 每筆 +76 點（0.3%），勝率 41%，t 約 1.3。", ""]
    OUT.mkdir(exist_ok=True)
    with open(OUT / "daily_forecast.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["date", "rhat", "lo", "hi", "actual_range", "high", "high_lo", "high_hi", "actual_high", "low", "low_lo", "low_hi", "actual_low", "hit"])
        for r in d["records"]:
            w.writerow([r["key"], r["forecast"], r["lo"], r["hi"], r["actual"], r.get("high"), r.get("high_lo"), r.get("high_hi"), r["actual_high"],
                        r.get("low"), r.get("low_lo"), r.get("low_hi"), r["actual_low"], r.get("hit")])
    with open(OUT / "snake_trades.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["exit_day", "side", "net"]); w.writerows(trades3)
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_()
