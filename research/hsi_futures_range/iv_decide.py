"""方向一：用期權波幅（IV）嘅變化決定下週沽邊個位（1σ／1.5σ／2σ 勒式）定係唔做（2026-10-14，使用者：
「最重要是要分析期權波幅變化去決定下星期應該做那一個位置/或者唔做」）。

兩份數據，結論要兩份方向一致先信：
  A. 真實（港交所 hsiwo 週期權，2025-10 至今，每個行使價嘅結算價 O.Q.P. 與 IV）：每週最後一個交易日收市入場，
     沽下一個到期嘅勒式，行使價 = 遠期 ± k × σ點（σ點 = 價平 IV × √(交易日/252) × 遠期，k = 1、1.5、2），
     用當日真實結算價收錢，到期用恒指收市近似結算，每腳 4 點成本。
  B. 長期合成（VHSI 2003 至今、恒指日線）：每週五收市，IV 用 VHSI × IV_SCALE（真實週期權價平 IV ÷ VHSI 平均 0.85），
     Black-Scholes 定價（冇偏斜：價外 Put 實際較貴，所以合成 Put 收入偏低），到期用下週五收市。

入場時已知嘅特徵（全部只用入場當日或之前嘅數據）：
  iv            價平 IV（B：VHSI × 0.85）
  d_iv          IV 一週變化（今週入場 − 上週入場，同一個「下週到期」年期）
  iv_rank       IV 喺過去 52 週嘅百分位（B 用 VHSI 252 日）
  iv_rv         IV ÷ 過去 20 個交易日實際波動
  term          （只 A）下週 IV − 下下週 IV（正數 = 近月貴，市場預期短期有事）
  skew          （只 A）1σ Put IV − 1σ Call IV
  iv_har        （只 A）IV ÷ 風揚陣 HAR 預測（vrp_real/weekly.csv）
目標：move_sig = |到期價 − 遠期| ÷ σ點（> 1 即係走出 1σ）；各 k 嘅每週淨利（點）。
分析：特徵三分位 → 平均淨利、走出 1σ 比率；Spearman 相關；B 再分前後兩半睇穩唔穩；
     前推規則（每週只用之前嘅週數，揀「同一特徵三分位入面歷史平均最高」嘅 k 或唔做），對比「每週都沽 1σ」。

用法：python3 research/hsi_futures_range/iv_decide.py --hsi canary/data_external/hsi_daily.csv --vhsi canary/data_external/vhsi_daily.csv
輸出：research/hsi_futures_range/iv_decide/REPORT.md、real_weekly.csv、long_weekly.csv、manifest.json
"""
import argparse, csv, json, math, sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import vrp_real as vr                                     # noqa: E402  共用載入、行使價與結算函數

OUT = HERE / "iv_decide"
COST_LEG = 4.0
KS = (1.0, 1.5, 2.0)
IV_SCALE = 0.85                                           # 真實週期權價平 IV ÷ VHSI（vrp_real 51 週平均）
SCALE_TO = 25000.0                                        # B：點數換算到恒指 25,000 水平
MIN_TRAIN = 20                                            # 前推規則：之前至少幾週先開始揀


# ---------------------------------------------------------------- 共用
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(F, K, T, vol, cp):
    """Black-76（無折現，週期權影響細）。vol 用小數。"""
    if T <= 0 or vol <= 0:
        return max(0.0, (F - K) if cp == "C" else (K - F))
    s = vol * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * s * s) / s
    d2 = d1 - s
    return F * norm_cdf(d1) - K * norm_cdf(d2) if cp == "C" else K * norm_cdf(-d2) - F * norm_cdf(-d1)


def rv20(hsi, dates, d):
    i = dates.index(d)
    if i < 21:
        return None
    c = np.array([hsi[x]["close"] for x in dates[i - 20:i + 1]])
    r = np.diff(np.log(c))
    return float(np.sqrt(np.mean(r ** 2) * 252) * 100)


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 8:
        return None, len(x)
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1]), len(x)


def stats(v):
    v = [x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not v:
        return {"n": 0}
    a = np.array(v, float)
    sd = a.std(ddof=1) if len(a) > 1 else 0.0
    return {"n": len(a), "mean": a.mean(), "win": (a > 0).mean() * 100, "worst": a.min(),
            "t": a.mean() / (sd / math.sqrt(len(a))) if sd > 0 else float("nan"), "total": a.sum()}


def fmt_s(s):
    if not s.get("n"):
        return "— | — | — | — | —"
    return f"{s['n']} | **{s['mean']:+.0f}** | {s['win']:.0f}% | {s['worst']:+.0f} | {s['t']:+.2f}"


def terciles(rows, feat):
    vals = sorted(r[feat] for r in rows if r.get(feat) is not None)
    if len(vals) < 9:
        return None
    return vals[len(vals) // 3], vals[2 * len(vals) // 3]


def bucket(v, cuts):
    return None if v is None else (0 if v < cuts[0] else (1 if v < cuts[1] else 2))


# ---------------------------------------------------------------- A. 真實週期權
def real_weeks(hsi, vhsi, opt_root, har_csv):
    atm, series = vr.load_opts(opt_root)
    har = {}
    if har_csv and Path(har_csv).exists():
        for r in vr.read_csv(har_csv):
            if r.get("har_vol"):
                har[r["entry"]] = float(r["har_vol"])
    dates = sorted(hsi)
    by_week = defaultdict(list)
    for (p, d) in atm:
        if p == "hsiwo" and d in hsi:
            by_week[vr.week_key(d)].append(d)
    rows = []
    for wk in sorted(by_week):
        d = max(by_week[wk])
        exps = sorted(e for e in atm[("hsiwo", d)] if e > d)
        if not exps:
            continue
        e = exps[0]
        if e > dates[-1]:                                        # 未到期（冇結算價）唔計
            continue
        a = atm[("hsiwo", d)][e]
        sd, s_t = vr.settle(hsi, dates, e)
        if s_t is None or sd <= d:
            continue
        F = a["forward"]
        iv = (a["iv_call"] + a["iv_put"]) / 2
        n = len([x for x in dates if d < x <= sd])
        T = n / 252
        sig = iv / 100 * math.sqrt(T) * F
        srs = series.get(("hsiwo", d, e), {})
        row = {"entry": d, "expiry": e, "days": n, "forward": F, "iv": iv, "sig_pts": sig, "settle": s_t,
               "move_sig": abs(s_t - F) / sig if sig else None, "vhsi": vhsi.get(d), "rv20": rv20(hsi, dates, d),
               "iv_har": (iv / har[d]) if har.get(d) else None}
        row["iv_rv"] = iv / row["rv20"] if row["rv20"] else None
        if len(exps) > 1:                                        # 期限結構：下週 − 下下週
            a2 = atm[("hsiwo", d)][exps[1]]
            row["term"] = iv - (a2["iv_call"] + a2["iv_put"]) / 2
        for k in KS:
            kp, pp = vr.leg(srs, F - k * sig, "P", False)
            kc, pc = vr.leg(srs, F + k * sig, "C", True)
            if kp and kc:
                pay = max(0, kp - s_t) + max(0, s_t - kc)
                row[f"net_{k:g}"] = pp + pc - pay - 2 * COST_LEG
                row[f"credit_{k:g}"] = pp + pc
                row[f"kp_{k:g}"], row[f"kc_{k:g}"] = kp, kc
                if k == 1.0:
                    ivp, ivc = srs.get((kp, "P"), {}).get("iv"), srs.get((kc, "C"), {}).get("iv")
                    row["skew"] = (ivp - ivc) if ivp and ivc else None
        rows.append(row)
    for i, r in enumerate(rows):                                  # 一週變化、52 週百分位
        r["d_iv"] = r["iv"] - rows[i - 1]["iv"] if i else None
        past = [x["iv"] for x in rows[max(0, i - 52):i]]
        r["iv_rank"] = (sum(1 for x in past if x <= r["iv"]) / len(past) * 100) if len(past) >= 10 else None
    return rows


# ---------------------------------------------------------------- B. 長期合成（VHSI）
def long_weeks(hsi, vhsi):
    dates = sorted(d for d in hsi if d in vhsi)
    fridays = []
    for i, d in enumerate(dates):                                 # 每週最後一個交易日
        if i + 1 == len(dates) or vr.week_key(dates[i + 1]) != vr.week_key(d):
            fridays.append(d)
    all_dates = sorted(hsi)
    rows = []
    vh_series = [vhsi[d] for d in dates]
    pos = {d: i for i, d in enumerate(dates)}
    for j in range(len(fridays) - 1):
        d, e = fridays[j], fridays[j + 1]
        F, s_t = hsi[d]["close"], hsi[e]["close"]
        n = len([x for x in all_dates if d < x <= e])
        if n < 1:
            continue
        iv = vhsi[d] * IV_SCALE
        T = n / 252
        sig = iv / 100 * math.sqrt(T) * F
        i = pos[d]
        past = vh_series[max(0, i - 252):i]
        row = {"entry": d, "expiry": e, "days": n, "forward": F, "iv": iv, "vhsi": vhsi[d], "sig_pts": sig, "settle": s_t,
               "move_sig": abs(s_t - F) / sig, "rv20": rv20(hsi, all_dates, d)}
        row["iv_rv"] = vhsi[d] / row["rv20"] if row["rv20"] else None
        row["iv_rank"] = sum(1 for x in past if x <= vhsi[d]) / len(past) * 100 if len(past) >= 120 else None
        prev = fridays[j - 1] if j else None
        row["d_iv"] = (vhsi[d] - vhsi[prev]) * IV_SCALE if prev else None
        scale = SCALE_TO / F                                     # 換算成今日指數水平嘅點數，唔同年代先比較得
        for k in KS:
            kp, kc = F - k * sig, F + k * sig
            credit = bs(F, kp, T, iv / 100, "P") + bs(F, kc, T, iv / 100, "C")
            row[f"net_{k:g}"] = (credit - max(0, kp - s_t) - max(0, s_t - kc)) * scale - 2 * COST_LEG
            row[f"credit_{k:g}"] = credit * scale
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 分析
def feature_table(rows, feat, label):
    cuts = terciles(rows, feat)
    if not cuts:
        return [f"- {label}：樣本不足"]
    lines = [f"**{label}**（三分位切點 {cuts[0]:.2f}／{cuts[1]:.2f}）", "",
             "| 三分位 | 週數 | 走出 1σ | 平均 move÷σ | 1σ 每週 | 1.5σ 每週 | 2σ 每週 |", "|---|---|---|---|---|---|---|"]
    for b, name in enumerate(("低", "中", "高")):
        g = [r for r in rows if bucket(r.get(feat), cuts) == b]
        if not g:
            continue
        out1 = np.mean([r["move_sig"] > 1 for r in g]) * 100
        ms = np.mean([r["move_sig"] for r in g])
        cells = []
        for k in KS:
            s = stats([r.get(f"net_{k:g}") for r in g])
            cells.append(f"{s['mean']:+.0f}（{s['win']:.0f}%）" if s.get("n") else "—")
        lines.append(f"| {name} | {len(g)} | {out1:.0f}% | {ms:.2f} | " + " | ".join(cells) + " |")
    rho, n = spearman([r.get(feat) if r.get(feat) is not None else np.nan for r in rows], [r["move_sig"] for r in rows])
    rho1, _ = spearman([r.get(feat) if r.get(feat) is not None else np.nan for r in rows],
                       [r.get("net_1") if r.get("net_1") is not None else np.nan for r in rows])
    lines += ["", f"Spearman：特徵 對 move÷σ = {rho:+.2f}、對 1σ 淨利 = {rho1:+.2f}（n={n}）" if rho is not None else "", ""]
    return lines


def walk_forward(rows, feat):
    """每週只用之前嘅週：揀同一三分位（切點都只用之前數據）歷史平均最高嘅選擇（1σ／1.5σ／2σ／唔做=0）。"""
    pnl, picks = [], []
    for i, r in enumerate(rows):
        hist = [x for x in rows[:i] if x.get(feat) is not None and x.get("net_1") is not None]
        if len(hist) < MIN_TRAIN or r.get(feat) is None or r.get("net_1") is None:
            continue
        cuts = terciles(hist, feat)
        b = bucket(r[feat], cuts)
        same = [x for x in hist if bucket(x[feat], cuts) == b]
        opts = {"skip": 0.0}
        for k in KS:
            v = [x.get(f"net_{k:g}") for x in same if x.get(f"net_{k:g}") is not None]
            if len(v) >= 5:
                opts[f"{k:g}σ"] = float(np.mean(v))
        best = max(opts, key=opts.get)
        picks.append(best)
        pnl.append(0.0 if best == "skip" else r.get(f"net_{best[:-1]}"))
    base = [r.get("net_1") for r in rows[-len(pnl):]] if pnl else []
    return stats(pnl), stats(base), picks


def section(rows, title, feats, halves=False):
    L = [f"## {title}", ""]
    base = {f"{k:g}σ": stats([r.get(f"net_{k:g}") for r in rows]) for k in KS}
    L += ["| 每週都沽 | 週數 | **每週平均（點）** | 賺錢週 | 最差一週 | t |", "|---|---|---|---|---|---|"]
    L += [f"| {k} 勒式 | {fmt_s(s)} |" for k, s in base.items()]
    L += ["", f"走出 1σ 嘅週：{np.mean([r['move_sig'] > 1 for r in rows]) * 100:.0f}%（理論常態約 32%）；"
              f"平均 move÷σ {np.mean([r['move_sig'] for r in rows]):.2f}（理論約 0.80）", ""]
    for feat, label in feats:
        L += feature_table(rows, feat, label)
        if halves:
            mid = len(rows) // 2
            for part, seg in (("前半", rows[:mid]), ("後半", rows[mid:])):
                rho, n = spearman([r.get(feat) if r.get(feat) is not None else np.nan for r in seg], [r["move_sig"] for r in seg])
                L.append(f"- {part}（{seg[0]['entry']}–{seg[-1]['entry']}）Spearman 對 move÷σ：{rho:+.2f}（n={n}）" if rho is not None else "")
            L.append("")
    L += ["### 權利金門檻（1σ 勒式收到嘅權利金少過門檻就唔做）", "",
          "| 規則 | 週數 | **每週平均（點）** | 賺錢週 | 最差一週 | t |", "|---|---|---|---|---|---|"]
    for th in (0, 60, 80, 100, 120):
        g = [r.get("net_1") for r in rows if r.get("credit_1") is not None and r["credit_1"] >= th]
        L.append(f"| 權利金 ≥ {th} 點先沽 | {fmt_s(stats(g))} |")
    for th in (60, 80):
        lo = [r.get("net_1") for r in rows if r.get("credit_1") is not None and r["credit_1"] < th]
        L.append(f"| （對照）權利金 < {th} 點嘅週 | {fmt_s(stats(lo))} |")
    L.append("")
    L += ["### 前推規則（每週只用之前嘅週，揀同一特徵三分位歷史最好嘅 1σ／1.5σ／2σ／唔做）", "",
          "| 特徵 | 規則 週數 | **規則每週** | 賺錢週 | 最差 | t | 同期每週都沽 1σ | 揀咗乜（次數） |", "|---|---|---|---|---|---|---|---|"]
    for feat, label in feats:
        s, b, picks = walk_forward(rows, feat)
        if s.get("n"):
            cnt = {p: picks.count(p) for p in ("1σ", "1.5σ", "2σ", "skip")}
            L.append(f"| {label} | {fmt_s(s)} | {b['mean']:+.0f}（t {b['t']:+.2f}） | "
                     + "、".join(f"{'唔做' if p == 'skip' else p} {c}" for p, c in cnt.items() if c) + " |")
    L.append("")
    return L


def write_csv(path, rows):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hsi", required=True)
    ap.add_argument("--vhsi", required=True)
    ap.add_argument("--opt", default=str(REPO / "data" / "hkex_options"))
    ap.add_argument("--har", default=str(HERE / "vrp_real" / "weekly.csv"))
    a = ap.parse_args()
    hsi, vhsi = vr.load_hsi(a.hsi), vr.load_vhsi(a.vhsi)
    real = real_weeks(hsi, vhsi, a.opt, a.har)
    long = long_weeks(hsi, vhsi)
    OUT.mkdir(exist_ok=True)
    write_csv(OUT / "real_weekly.csv", real)
    write_csv(OUT / "long_weekly.csv", long)
    feats_real = [("iv", "IV 水平"), ("d_iv", "IV 一週變化"), ("iv_rank", "IV 52 週百分位"), ("iv_rv", "IV ÷ 20 日實際"),
                  ("term", "期限結構（下週 − 下下週 IV）"), ("skew", "偏斜（1σ Put IV − 1σ Call IV）"), ("iv_har", "IV ÷ 風揚陣預測")]
    feats_long = [("iv", "IV 水平（VHSI×0.85）"), ("d_iv", "IV 一週變化"), ("iv_rank", "VHSI 一年百分位"), ("iv_rv", "VHSI ÷ 20 日實際")]
    L = ["# 方向一：用期權 IV 變化決定下週沽邊個位定唔做", "",
         f"- 產生：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}；腳本 `iv_decide.py`；每腳成本 {COST_LEG:g} 點；統計估計，唔係交易建議",
         f"- A 真實週期權 {len(real)} 週（{real[0]['entry']}–{real[-1]['entry']}）；B 長期合成 {len(long)} 週（{long[0]['entry']}–{long[-1]['entry']}，IV = VHSI × {IV_SCALE}）",
         "- move÷σ = |到期價 − 遠期| ÷ σ點；> 1 即係走出 1σ（1σ 勒式要賠錢）",
         f"- B 嘅點數全部換算成恒指 {SCALE_TO:,.0f} 水平（× {SCALE_TO:,.0f} ÷ 當時指數），唔同年代先比較得；合成冇偏斜，Put 收入偏低，所以 B 嘅絕對值偏差，睇相對高低", ""]
    L += section(real, "A. 真實港交所週期權", feats_real)
    L += section(long, "B. 長期合成（VHSI，2003 起）", feats_long, halves=True)
    (OUT / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    manifest = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "script_sha256": vr.sha(__file__),
                "inputs": {"hsi": vr.sha(a.hsi), "vhsi": vr.sha(a.vhsi), "atm_iv.csv": vr.sha(Path(a.opt) / "atm_iv.csv"),
                           "har_weekly": vr.sha(a.har) if Path(a.har).exists() else None},
                "real_weeks": len(real), "long_weeks": len(long), "cost_leg": COST_LEG, "iv_scale": IV_SCALE}
    json.dump(manifest, open(OUT / "manifest.json", "w"), ensure_ascii=False, indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
