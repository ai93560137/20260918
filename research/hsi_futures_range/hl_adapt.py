"""每日高位／低位預測的三個自適應機制（2026-10-05，用戶：「1,2,3 一起做」）。

問題：連錯 7 天模型會不會調整？現在不會（全歷史重擬合、比例用全歷史中位數）。測三個機制，逐日前推、只用當時已知的數據：
  1. 偏差修正：把近 N 天「實際高 − 預測高」的平均加到預測高（低位同理），範圍一起移。N = 10／20／40。
  2. 比例視窗：高低位比例的中位數與分位只用近 W 天，不用全歷史。W = 120／250／500。
  3. 連偏放寬：同一邊連續 S 天同方向偏差（例如實際高連續高過預測高），那一邊的範圍外緣多放 K × R̂。S = 5，K = 0.25／0.5。
  4. 三個一起（偏差 20 日 ＋ 視窗 250 ＋ 連偏 5 日 0.25）。
基準 = 現在的做法（全歷史比例中位數、2%／98% 分位範圍）。
指標：高位／低位平均差（點）、兩邊都在 1% 內、兩邊都落在範圍、範圍平均寬、連續沒有 ✓（1% 內）的最長日數、逐年。
數據：Futu 日線（production 的 futu/daily 序列，HAR 與 production 同一函數）；HK50 差價合約 15 分 K 併成日線做獨立對照。
用法：python3 research/hsi_futures_range/hl_adapt.py --daily futu_daily.json
輸出：research/hsi_futures_range/hl_adapt/REPORT.md、daily_<src>.csv（每天每個變體的預測與實際）
"""
import argparse, csv, json, math, os, sys, types
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(REPO))
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "x")
# main.py 需要 GCS／genai 模組；這裡只用純函數，塞假模組
import google, google.cloud                                      # noqa: E402
_sm = types.ModuleType("google.cloud.storage"); _sm.Client = lambda *a, **k: None; sys.modules["google.cloud.storage"] = _sm; google.cloud.storage = _sm
_g = types.ModuleType("google.genai"); _g.Client = lambda *a, **k: None; _g.types = types.SimpleNamespace(); sys.modules["google.genai"] = _g
_e = types.ModuleType("google.api_core.exceptions"); _e.PreconditionFailed = type("PC", (Exception,), {}); _e.NotFound = KeyError
_ac = types.ModuleType("google.api_core"); _ac.exceptions = _e; sys.modules["google.api_core"] = _ac; sys.modules["google.api_core.exceptions"] = _e
import main                                                      # noqa: E402
import high_low_in as hl                                         # noqa: E402
import hk50_cfd                                                  # noqa: E402

OUT = HERE / "hl_adapt"
Q = main.HL_BAND_Q                       # 0.02
OK_PCT = 1.0
MIN_DAYS = main.HL_MIN_DAYS              # 120


def futu_days(path):
    raw = open(path, encoding="utf-8").read()
    series = json.loads(raw[raw.find("["):])
    rows = main.futu_range_rows(sorted((b for b in series if isinstance(b, dict)), key=lambda b: str(b.get("time_key", ""))))
    har = main.har_forecasts(rows)
    out = []
    for i, r in enumerate(rows):
        f = har.get(i)
        if f and r.get("prev_close"):
            out.append({"date": r["date"], "ref": r["prev_close"], "high": r["high"], "low": r["low"], "rhat": f[0]})
    return out


def hk50_days():
    bars, daily = hk50_cfd.load()
    days = hl.build_days(bars, daily)
    return [{"date": d["date"], "ref": d["ref"], "high": max(b["high"] for b in d["bars"]), "low": min(b["low"] for b in d["bars"]),
             "rhat": d["rhat"]} for d in days]


def quant(sorted_vals, q):
    return main._quantile(sorted_vals, q)


def run(days, bias_n=0, window=0, streak_s=0, streak_k=0.0):
    """逐日前推。回傳每天的紀錄（預測高／低、範圍、實際）。"""
    ups, downs = [], []                      # 全部歷史的比例（依時間）
    err_h, err_l = [], []                    # 過去的誤差（實際 − 預測，未修正前的原始預測）
    recs = []
    for d in days:
        R, ref = d["rhat"], d["ref"]
        if len(ups) >= MIN_DAYS:
            su = sorted(ups[-window:] if window else ups); sd = sorted(downs[-window:] if window else downs)
            high = ref + quant(su, 0.5) * R; low = ref - quant(sd, 0.5) * R
            h_lo, h_hi = ref + quant(su, Q) * R, ref + quant(su, 1 - Q) * R
            l_lo, l_hi = ref - quant(sd, 1 - Q) * R, ref - quant(sd, Q) * R
            raw_high, raw_low = high, low
            if bias_n and len(err_h) >= bias_n:                 # 1. 偏差修正
                bh = float(np.mean(err_h[-bias_n:])); bl = float(np.mean(err_l[-bias_n:]))
                high += bh; h_lo += bh; h_hi += bh; low += bl; l_lo += bl; l_hi += bl
            if streak_s and len(err_h) >= streak_s:               # 3. 連偏放寬
                last_h, last_l = err_h[-streak_s:], err_l[-streak_s:]
                if all(e > 0 for e in last_h): h_hi += streak_k * R
                if all(e < 0 for e in last_h): h_lo -= streak_k * R
                if all(e > 0 for e in last_l): l_hi += streak_k * R
                if all(e < 0 for e in last_l): l_lo -= streak_k * R
            recs.append({"date": d["date"], "ref": ref, "rhat": R, "high": high, "h_lo": h_lo, "h_hi": h_hi, "low": low, "l_lo": l_lo, "l_hi": l_hi,
                         "a_high": d["high"], "a_low": d["low"]})
            err_h.append(d["high"] - raw_high); err_l.append(d["low"] - raw_low)
        ups.append((d["high"] - ref) / R); downs.append((ref - d["low"]) / R)
    return recs


def stats(recs):
    eh = np.array([r["a_high"] - r["high"] for r in recs]); el = np.array([r["a_low"] - r["low"] for r in recs])
    ph = np.abs(eh) / np.array([r["high"] for r in recs]) * 100; pl = np.abs(el) / np.array([r["low"] for r in recs]) * 100
    ok = (ph <= OK_PCT) & (pl <= OK_PCT)
    inb = np.array([r["h_lo"] <= r["a_high"] <= r["h_hi"] and r["l_lo"] <= r["a_low"] <= r["l_hi"] for r in recs])
    width = np.mean([(r["h_hi"] - r["h_lo"] + r["l_hi"] - r["l_lo"]) / 2 for r in recs])
    run = best = 0
    for v in ok:
        run = 0 if v else run + 1; best = max(best, run)
    return {"n": len(recs), "mae_h": np.abs(eh).mean(), "mae_l": np.abs(el).mean(), "bias_h": eh.mean(), "bias_l": el.mean(),
            "ok": ok.mean(), "inb": inb.mean(), "width": width, "max_miss": best, "ok_arr": ok, "dates": [r["date"] for r in recs]}


def row(lab, s):
    return (f"| {lab} | {s['mae_h']:.0f}／{s['mae_l']:.0f} | {s['bias_h']:+.0f}／{s['bias_l']:+.0f} | **{s['ok']:.0%}** | {s['inb']:.0%} | "
            f"{s['width']:,.0f} | {s['max_miss']} |")


HEAD = ("| 變體 | 高／低平均差（點） | 平均偏差 高／低 | 兩邊都在 1% 內 | 兩邊都落在範圍 | 範圍平均寬 | 最長連續沒有 ✓ |\n"
        "|---|---|---|---|---|---|---|")
VARIANTS = [("基準（現在）", {}),
            ("1. 偏差修正 10 日", {"bias_n": 10}), ("1. 偏差修正 20 日", {"bias_n": 20}), ("1. 偏差修正 40 日", {"bias_n": 40}),
            ("2. 比例視窗 120 日", {"window": 120}), ("2. 比例視窗 250 日", {"window": 250}), ("2. 比例視窗 500 日", {"window": 500}),
            ("3. 連偏 5 日放寬 0.25R̂", {"streak_s": 5, "streak_k": 0.25}), ("3. 連偏 5 日放寬 0.5R̂", {"streak_s": 5, "streak_k": 0.5}),
            ("4. 三個一起（20 日＋250 日＋5 日 0.25R̂）", {"bias_n": 20, "window": 250, "streak_s": 5, "streak_k": 0.25})]


def section(src, days):
    L = [f"## {src}：{days[0]['date']} 至 {days[-1]['date']}，{len(days)} 個交易日（前 {MIN_DAYS} 天只校準）", "", HEAD]
    S = {}
    for lab, kw in VARIANTS:
        recs = run(days, **kw); S[lab] = (recs, stats(recs))
        L.append(row(lab, S[lab][1]))
    base = S["基準（現在）"][1]
    years = sorted({d[:4] for d in base["dates"]})
    L += ["", "逐年「兩邊都在 1% 內」：", "", "| 變體 | " + " | ".join(years) + " |", "|---|" + "---|" * len(years)]
    for lab, (recs, s) in S.items():
        L.append(f"| {lab} | " + " | ".join(f"{np.mean([o for o, d in zip(s['ok_arr'], s['dates']) if d[:4] == y]):.0%}" for y in years) + " |")
    # 連錯 7 天之後，基準的下一天表現
    ok = base["ok_arr"]; after = [ok[i + 1] for i in range(6, len(ok) - 1) if not any(ok[i - 6:i + 1])]
    L += ["", f"基準：連續 7 天沒有 ✓ 的次數 {len(after)}；之後一天有 ✓ 的比例 {np.mean(after):.0%}（平常 {ok.mean():.0%}）" if after
          else "基準：樣本內沒有連續 7 天沒有 ✓ 的情況", ""]
    OUT.mkdir(exist_ok=True)
    with open(OUT / f"daily_{src.split()[0].lower()}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        labs = [lab for lab, _ in VARIANTS]
        w.writerow(["date", "ref", "rhat", "actual_high", "actual_low"] + [f"{lab}|{k}" for lab in labs for k in ("high", "h_lo", "h_hi", "low", "l_lo", "l_hi")])
        n = len(S[labs[0]][0])
        for i in range(n):
            r0 = S[labs[0]][0][i]
            w.writerow([r0["date"], r0["ref"], f"{r0['rhat']:.1f}", r0["a_high"], r0["a_low"]]
                       + [f"{S[lab][0][i][k]:.0f}" for lab in labs for k in ("high", "h_lo", "h_hi", "low", "l_lo", "l_hi")])
    return L


def main_():
    ap = argparse.ArgumentParser(); ap.add_argument("--daily", required=True); a = ap.parse_args()
    L = ["# 每日高位／低位預測的自適應機制（hl_adapt.py）", "",
         "- 基準 = production 的做法：HAR 全歷史重擬合、比例用全歷史中位數、範圍 2%／98% 分位。全部逐日前推。",
         "- 偏差修正用「原始預測」的誤差（不含修正本身），免得修正追著自己跑。連偏放寬只放外緣。", ""]
    L += section("Futu 日線（production 序列）", futu_days(a.daily))
    L += section("HK50 差價合約（獨立對照）", hk50_days())
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main_()
