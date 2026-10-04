"""方向一進一步：沽週期權 1σ 勒式 ＋ 動態對沖（Delta 對沖，用小型恒指期貨）——真實結算價、15 分 K 路徑回測。

用戶 2026-10-04：「那我們就做期權，再加上動態對沖」。
輸入：vrp_real/weekly.csv（每週的勒式兩腳與結算，見 vrp_real.py）、data/hkex_options/series/（每日每腳的 IV）、
      恒指即月期貨 15 分 K（Futu 快取，期貨路徑 → 指數路徑 = 期貨 − 入市日基差）、恒指日線（結算與交易日曆）。
每週一筆：週五收市沽 1σ 勒式（真實 O.Q.P.），持有到下週五結算。
Delta：Black-76，IV 用當天港交所報告那一腳的 IV（沒有就沿用上一個有的），剩餘時間 = 剩餘交易日（含當日剩餘比例）÷ 252。
對沖：每根 15 分 K 收市算組合淨 Delta（1 張勒式）；|淨 Delta ＋ 對沖倉| > 門檻 就用小型恒指期貨（1 張 = 0.2 個大合約 Delta）
      把它調回 0 附近；到期最後一根（16:30 前）平掉對沖倉。成本：小型期貨每張每邊 HEDGE_COST_HKD（佣金＋滑價）。
門檻：none（不對沖）、0.5、0.3、0.2、0.1；另測「只在日市對沖」與「日市＋夜市」；另測止蝕規則：虧損達 2 倍權利金（每日收市用 O.Q.P. 計）就平倉。
盈虧全部用港元，再換成大合約點數（÷ HK$50）方便跟其他回測比較。

用法：python3 research/hsi_futures_range/hedge_real.py --json 15 分 K 快取 --hsi hsi.csv
輸出：vrp_real/hedge_REPORT.md、hedge_weekly.csv
"""
import argparse, csv, gzip, io, json, math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "vrp_real"
BIG, MINI = 50.0, 10.0                 # 恒指期權／期貨每點 HK$50，小型期貨 HK$10
OPT_COST_HKD = 4 * BIG                 # 期權每腳 4 點（與 vrp_real 相同）
HEDGE_COST_HKD = 15.0                  # 小型期貨每張每邊：佣金約 HK$10 ＋ 滑價半點 HK$5
BANDS = (None, 0.5, 0.3, 0.2, 0.1)
DAY_END = "16:30"


def ncdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def delta(F, K, sig, T, call):
    if T <= 0 or sig <= 0:
        return (1.0 if F > K else 0.0) if call else (-1.0 if F < K else 0.0)
    d1 = (math.log(F / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    return ncdf(d1) if call else ncdf(d1) - 1.0


def load_series(root):
    iv = {}                                                # (date, expiry, strike, cp) → iv
    for f in sorted((Path(root) / "series").glob("hsiwo_*.csv.gz")):
        with io.TextIOWrapper(gzip.open(f, "rb"), encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                iv[(r["date"], r["expiry"], int(r["strike"]), r["cp"])] = float(r["iv"])
    return iv


def load_hsi(path):
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if float(r["High"]) != float(r["Low"]):
            out[r["Date"]] = float(r["Close"])
    return out


def session_of(tk):
    """交易日 = 09:00 至翌日 09:00（與風揚陣相同）。"""
    return (datetime.strptime(tk, "%Y-%m-%d %H:%M:%S") - timedelta(hours=9)).strftime("%Y-%m-%d")


def time_left(tk, session, dates, expiry):
    """剩餘交易日（含當日剩餘比例）。日市 09:15–16:30 算 1 天內的比例；夜市當日已過。"""
    later = sum(1 for d in dates if session < d <= expiry)
    hhmm = tk[11:16]
    if tk[:10] == session and hhmm <= DAY_END:
        mins = (int(hhmm[:2]) - 9) * 60 + int(hhmm[3:]) - 15
        frac = max(0.0, 1 - mins / 435)
    else:
        frac = 0.0
    return later + frac


def week_of(d):
    y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
    return f"{y}-W{w:02d}"


def load_levels(root):
    out = {"day": {}, "week": {}}
    for r in csv.DictReader(open(root / "levels_daily.csv", encoding="utf-8")):
        out["day"][r["date"]] = {k: float(r[k]) for k in ("pred_high", "pred_low", "high_edge_0.9", "low_edge_0.9")}
    for r in csv.DictReader(open(root / "levels_weekly.csv", encoding="utf-8")):
        out["week"][r["week"]] = {k: float(r[k]) for k in ("pred_high", "pred_low", "high_edge_0.9", "low_edge_0.9")}
    return out


def load_oqp(root):
    oqp = defaultdict(dict)                                  # (date, expiry) → {(strike, cp): 結算價}
    for f in sorted((Path(root) / "series").glob("hsiwo_*.csv.gz")):
        with io.TextIOWrapper(gzip.open(f, "rb"), encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                oqp[(r["date"], r["expiry"])][(int(r["strike"]), r["cp"])] = float(r["oqp"])
    return oqp


def simulate(week, bars, ivmap, dates, hsi, band, night, stop_mult, levels=None, range_mode=None, strike_mode=None, series=None):
    """回傳 dict：期權盈虧、對沖盈虧、對沖成本、交易次數、最壞路徑。
    range_mode：'day'／'week' = 不看 Delta 門檻，指數走出風揚陣預測範圍（九成邊）就對沖到中性，回到預測高低位之內就拆掉對沖。
    strike_mode：'week' = 兩腳行使價改放在風揚陣下週預測範圍的九成邊（最接近的掛牌行使價），權利金用當天真實結算價。"""
    d0, e = week["entry"], week["expiry"]
    kp, kc = int(float(week["kp"])), int(float(week["kc"]))
    credit = float(week["strangle_credit"])
    F0 = float(week["forward"])
    if strike_mode:
        srs = (series or {}).get((d0, e), {})
        if strike_mode == "week":                            # 風揚陣下週預測範圍的九成邊
            wl = (levels or {}).get("week", {}).get(week_of(e))
            if not wl:
                return None
            lo_t, hi_t = wl["low_edge_0.9"], wl["high_edge_0.9"]
        else:                                                # 對照：IV 的 m 倍 σ（同樣更遠的行使價）
            m = float(strike_mode.replace("sigma", ""))
            sig = float(week["iv"]) / 100 * math.sqrt(float(week["days"]) / 252) * F0
            lo_t, hi_t = F0 - m * sig, F0 + m * sig
        if not srs:
            return None
        kp = max((k for k, c in srs if c == "P" and k <= lo_t and srs[(k, "P")] > 0), default=None)
        kc = min((k for k, c in srs if c == "C" and k >= hi_t and srs[(k, "C")] > 0), default=None)
        if kp is None or kc is None:
            return None
        credit = srs[(kp, "P")] + srs[(kc, "C")]
    seg = [b for b in bars if d0 < b["time_key"][:10] <= e and (b["time_key"][:10] < e or b["time_key"][11:16] <= DAY_END)]
    seg = [b for b in seg if session_of(b["time_key"]) > d0]
    if not seg:
        return None
    basis = seg[0]["open"] - hsi[d0] if d0 in hsi else 0.0      # 期貨 − 指數（入市後第一根開市對入市日指數收市）
    ivp, ivc = float(week["iv_put"]) if week.get("iv_put") else float(week["iv"]), float(week["iv_call"]) if week.get("iv_call") else float(week["iv"])
    ivp = ivmap.get((d0, e, kp, "P"), ivp); ivc = ivmap.get((d0, e, kc, "C"), ivc)
    hedge = 0.0                                              # 小型期貨張數 × 0.2 = 大合約 Delta 單位
    hedge_pnl = 0.0; cost = 0.0; trades = 0; last_px = None; cur_day = None
    stopped = None; worst = 0.0; max_abs_delta = 0.0
    for b in seg:
        tk = b["time_key"]; s = session_of(tk)
        is_day = tk[:10] == s and "09:15" <= tk[11:16] <= DAY_END
        if not night and not is_day:
            # 夜市不對沖，但對沖倉的盈虧照算
            if last_px is not None and hedge:
                hedge_pnl += hedge * (b["close"] - last_px) * BIG   # hedge 以大合約 Delta 單位計 → HK$50/點
            last_px = b["close"]
            continue
        if s != cur_day:                                     # 新交易日：更新 IV（當天報告在收市後才有 → 用前一天的）
            cur_day = s
            prev = max((d for d in dates if d < s), default=None)
            if prev:
                ivp = ivmap.get((prev, e, kp, "P"), ivp); ivc = ivmap.get((prev, e, kc, "C"), ivc)
        px = b["close"]
        if last_px is not None and hedge:
            hedge_pnl += hedge * (px - last_px) * BIG
        last_px = px
        S = px - basis
        T = time_left(tk, s, dates, e) / 252
        net = -(delta(S, kc, ivc / 100, T, True)) - (delta(S, kp, ivp / 100, T, False))   # 短倉的 Delta
        max_abs_delta = max(max_abs_delta, abs(net))
        # 止蝕（每日收市看 O.Q.P. 太粗，這裡用 Black-76 近似市值：不做；改用「到期前任何一根指數穿過短腳行使價 ± 權利金」的簡化規則）
        if stop_mult and stopped is None:
            intrinsic = max(0.0, S - kc) + max(0.0, kp - S)
            if intrinsic >= stop_mult * credit:
                stopped = (tk, S, intrinsic)
                break
        target = None
        if range_mode:
            lv = (levels or {}).get(range_mode, {}).get(s if range_mode == "day" else week_of(s))
            if lv:
                if S > lv["high_edge_0.9"] or S < lv["low_edge_0.9"]:
                    target = -round(net / 0.2) * 0.2                       # 走出預測範圍：對沖到中性
                elif lv["pred_low"] <= S <= lv["pred_high"] and hedge:
                    target = 0.0                                            # 回到預測高低位之內：拆掉對沖
        elif band is not None and abs(net + hedge) > band:
            target = -round(net / 0.2) * 0.2
        if target is not None and abs(target - hedge) > 1e-9:
            lots = abs(target - hedge) / 0.2
            cost += lots * HEDGE_COST_HKD
            trades += int(round(lots))
            hedge = target
    # 結算
    if stopped:
        settle = stopped[1]
        opt_pnl = (credit - stopped[2]) * BIG
    else:
        settle = hsi.get(week["settle_date"], week.get("settle") and float(week["settle"]))
        payoff = max(0.0, kp - settle) + max(0.0, settle - kc)
        opt_pnl = (credit - payoff) * BIG
    if hedge and last_px is not None:                        # 平對沖倉（用最後一根期貨收市）
        cost += abs(hedge) / 0.2 * HEDGE_COST_HKD
        trades += int(round(abs(hedge) / 0.2))
    opt_pnl -= 2 * OPT_COST_HKD
    total = opt_pnl + hedge_pnl - cost
    return {"opt": opt_pnl, "hedge": hedge_pnl, "cost": cost, "trades": trades, "total": total, "credit": credit, "kp": kp, "kc": kc,
            "stopped": bool(stopped), "max_abs_delta": max_abs_delta}


def st(x):
    x = np.array(x, dtype=float) / BIG                       # 換成大合約點數
    if len(x) < 2:
        return None
    eq = np.cumsum(x)
    return {"n": len(x), "mean": x.mean(), "win": (x > 0).mean(), "worst": x.min(), "t": x.mean() / x.std(ddof=1) * math.sqrt(len(x)),
            "total": x.sum(), "dd": float((np.maximum.accumulate(eq) - eq).max()), "std": x.std(ddof=1)}


def fmt(s):
    return (f"| {s['n']} | **{s['mean']:+.0f}** | {s['win']:.0%} | {s['worst']:+,.0f} | {s['std']:,.0f} | {s['t']:+.2f} | {s['total']:+,.0f}／{s['dd']:,.0f} |"
            if s else "| — | — | — | — | — | — | — |")


HEAD = "| 週數 | **每週平均（大合約點）** | 賺錢週 | 最差一週 | 週標準差 | t 值 | 總點數／最大回撤 |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True); ap.add_argument("--hsi", required=True)
    ap.add_argument("--opt", default=str(REPO / "data" / "hkex_options"))
    a = ap.parse_args()
    bars = sorted(json.load(open(a.json))["bars"], key=lambda b: b["time_key"])
    hsi = load_hsi(a.hsi); dates = sorted(hsi)
    ivmap = load_series(a.opt)
    levels = load_levels(HERE / "r_sweep" / "futu")
    oqp = load_oqp(a.opt)
    weeks = [r for r in csv.DictReader(open(OUT / "weekly.csv", encoding="utf-8")) if r.get("kp") and r.get("kc")]
    configs = [("不對沖", None, True, 0), ("對沖門檻 0.5", 0.5, True, 0), ("對沖門檻 0.3", 0.3, True, 0), ("對沖門檻 0.2", 0.2, True, 0),
               ("對沖門檻 0.1", 0.1, True, 0), ("門檻 0.3・只日市對沖", 0.3, False, 0), ("門檻 0.2・只日市對沖", 0.2, False, 0),
               ("不對沖・2 倍權利金止蝕", None, True, 2.0), ("門檻 0.3・2 倍權利金止蝕", 0.3, True, 2.0),
               ("風揚陣日範圍對沖（出九成邊才對沖）", None, True, 0, "day"), ("風揚陣週範圍對沖", None, True, 0, "week"),
               ("行使價 = 週預測九成邊・不對沖", None, True, 0, None, "week"), ("行使價 = 週預測九成邊・門檻 0.5", 0.5, True, 0, None, "week"),
               ("行使價 = 週預測九成邊・日範圍對沖", None, True, 0, "day", "week"),
               ("對照：行使價 = 1.5σ・不對沖", None, True, 0, None, "sigma1.5"), ("對照：行使價 = 2σ・不對沖", None, True, 0, None, "sigma2"),
               ("對照：行使價 = 1.5σ・門檻 0.5", 0.5, True, 0, None, "sigma1.5")]
    res = {c[0]: [] for c in configs}
    ledger = []
    for w in weeks:
        row = {"entry": w["entry"], "expiry": w["expiry"], "kp": w["kp"], "kc": w["kc"], "credit": w["strangle_credit"]}
        for name, band, night, stop, *extra in configs:
            rm, sm = (extra + [None, None])[:2]
            r = simulate(w, bars, ivmap, dates, hsi, band, night, stop, levels, rm, sm, oqp)
            if r is None:
                continue
            r["entry"] = w["entry"]
            res[name].append(r)
            key = name.replace("・", "_").replace(" ", "")
            row[f"{key}_total_pts"] = round(r["total"] / BIG, 1)
            row[f"{key}_hedge_pts"] = round(r["hedge"] / BIG, 1)
            row[f"{key}_trades"] = r["trades"]
        ledger.append(row)
    cols = []
    for r in ledger:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(OUT / "hedge_weekly.csv", "w", newline="", encoding="utf-8") as fh:
        wtr = csv.DictWriter(fh, fieldnames=cols); wtr.writeheader(); wtr.writerows(ledger)
    L = ["# 沽週期權 1σ 勒式 ＋ 動態 Delta 對沖（小型恒指期貨）：真實結算價、15 分 K 路徑", "",
         f"- {len(weeks)} 週（{weeks[0]['entry']} 至 {weeks[-1]['entry']}）；期權每腳 {OPT_COST_HKD / BIG:g} 點；小型期貨每張每邊 HK${HEDGE_COST_HKD:g}；"
         "盈虧換成大合約點（HK$50）", "- Delta 用 Black-76，IV 用前一個交易日港交所報告該腳的 IV；指數路徑 = 期貨 15 分 K − 入市後首根基差",
         "- 對沖：每根 15 分 K 收市，|淨 Delta ＋ 對沖倉| 超過門檻就用小型期貨（0.2 Delta／張）調回 0 附近；到期前最後一根平對沖倉",
         "- 止蝕規則（簡化）：到期前任何一根指數內在值 ≥ 2 倍權利金就平倉（用內在值，略低估時間值）", "",
         "| 設定 " + HEAD[1:], "|---|---|---|---|---|---|---|---|"]
    for name, *_ in configs:
        L.append(f"| {name} " + fmt(st([r["total"] for r in res[name]])))
    L += ["", "## 行使價離遠期價多遠（平均 %，Put／Call）", ""]
    for name, *_ in configs:
        rs = res[name]
        if rs and all(r.get("kp") for r in rs):
            dp = np.mean([(float(w["forward"]) - r["kp"]) / float(w["forward"]) * 100 for w, r in zip(weeks, rs)]) if len(rs) == len(weeks) else float("nan")
            dc = np.mean([(r["kc"] - float(w["forward"])) / float(w["forward"]) * 100 for w, r in zip(weeks, rs)]) if len(rs) == len(weeks) else float("nan")
            L.append(f"- {name}：Put −{dp:.2f}%、Call +{dc:.2f}%、權利金 {np.mean([r['credit'] for r in rs]):.0f} 點")
    L += ["", "## 拆開看：期權本身、對沖盈虧、對沖成本、每週交易次數（平均，大合約點）", "", "| 設定 | 權利金 | 期權 | 對沖盈虧 | 對沖成本 | 合計 | 每週對沖次數 | 止蝕週數 |", "|---|---|---|---|---|---|---|---|"]
    for name, *_ in configs:
        rs = res[name]
        if rs:
            L.append(f"| {name} | {np.mean([r['credit'] for r in rs]):.0f} | {np.mean([r['opt'] for r in rs]) / BIG:+.0f} | {np.mean([r['hedge'] for r in rs]) / BIG:+.0f} | "
                     f"{-np.mean([r['cost'] for r in rs]) / BIG:+.1f} | {np.mean([r['total'] for r in rs]) / BIG:+.0f} | "
                     f"{np.mean([r['trades'] for r in rs]):.1f} | {sum(r['stopped'] for r in rs)} |")
    L += ["", "## 分段（每週平均，大合約點）", "", "| 設定 | 2025Q4 | 2026H1 | 2026H2 |", "|---|---|---|---|"]
    for name, *_ in configs:
        parts = []
        for a_, b_ in (("2025-10", "2026-01"), ("2026-01", "2026-06"), ("2026-06", "2026-10")):
            sel = [r["total"] for r in res[name] if a_ <= r["entry"][:7] < b_]
            parts.append(f"{np.mean(sel) / BIG:+.0f}" if sel else "—")
        L.append(f"| {name} | " + " | ".join(parts) + " |")
    text = "\n".join(L) + "\n"
    (OUT / "hedge_REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
