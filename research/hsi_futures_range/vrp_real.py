"""方向一（賣波幅）用真實期權數據重做：港交所每日報告的恒指週／月期權結算價與 IV（2023-10 起）。

輸入：
  data/hkex_options/atm_iv.csv、series/<產品>_<年>.csv.gz   港交所報告（scripts/hkex_option_iv.py fetch）
  恒指日線（canary 分支 hsi_daily.csv）                        結算價近似：到期日恒指收市（官方 EAS 是當日每 5 分鐘報價平均，略有差）
  VHSI 日線（canary 分支 vhsi_daily.csv）
  恒指即月期貨交易日 K（GCS futu/daily/HK.HSI_FRONT.json）      風揚陣 HAR 波幅預測（逐日前推），年化 = R̂ ÷ 1.596 ÷ 昨收 × √252

週期權（主要）：每週最後一個交易日收市，看「下一個到期」的週期權（即下週）：
  價平 IV（C／P 平均）對 VHSI、對風揚陣預測、對之後一週實際波動；
  沽價平跨式：收 O.Q.P.（結算價）C＋P，到期付 |S_T − K|；
  沽 1σ 勒式；鐵鷹（沽 ±1σ、買 ±2σ，σ = 價平 IV × √(5/252) × 遠期）——用當天報告裡那些行使價的真實結算價；
  每腳成本 COST_LEG 點。挑時機：IV ÷ 風揚陣預測、VHSI ÷ 風揚陣預測（風揚陣頁用的規則）、IV ÷ VHSI。
月期權（次要）：上一個月到期翌日收市沽即月價平跨式，持有到到期（到期日 = 當月最後交易日的前一個交易日）。

用法：python3 research/hsi_futures_range/vrp_real.py --hsi hsi.csv --vhsi vhsi.csv --futu futu_daily.json [--opt data/hkex_options] [--cost 4]
輸出：research/hsi_futures_range/vrp_real/REPORT.md、weekly.csv、monthly.csv、manifest.json
"""
import argparse, csv, gzip, hashlib, io, json, math, sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import backtest as bt                                    # noqa: E402

OUT = HERE / "vrp_real"
COST_LEG = 4.0
RANGE_TO_SIGMA = 1.596


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path, gz=False):
    if gz:
        with io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_hsi(path):
    out = {}
    for r in read_csv(path):
        if float(r["High"]) != float(r["Low"]):
            out[r["Date"]] = {k.lower(): float(r[k]) for k in ("Open", "High", "Low", "Close")}
    return out


def load_vhsi(path):
    return {r["Date"]: float(r["Close"]) for r in read_csv(path)}


def load_har(path):
    daily = json.load(open(path))
    D, C, _, F = bt.run(bt.to_rows(daily), 60)
    har = F["HAR（對數，平均）"]
    nxt = {}                                                # 收市日 → 對下一個交易日的預測（年化 %、點）
    for t in range(1, len(D)):
        if not np.isnan(har[t]):
            pts = har[t] * C[t - 1]
            nxt[D[t - 1]] = {"pts": pts, "vol": pts / RANGE_TO_SIGMA / C[t - 1] * math.sqrt(252) * 100, "close": C[t - 1]}
    return nxt


def load_opts(root):
    atm = defaultdict(dict)                                 # (product, date) → {expiry: row}
    for r in read_csv(Path(root) / "atm_iv.csv"):
        atm[(r["product"], r["date"])][r["expiry"]] = {k: (float(v) if k not in ("date", "product", "expiry") else v)
                                                       for k, v in r.items()}
    series = defaultdict(dict)                              # (product, date, expiry) → {(strike, cp): row}
    for f in sorted((Path(root) / "series").glob("*.csv.gz")):
        for r in read_csv(f, gz=True):
            series[(r["product"], r["date"], r["expiry"])][(int(r["strike"]), r["cp"])] = {k: float(v) for k, v in r.items()
                                                                                          if k in ("oqp", "iv", "vol", "oi")}
    return atm, series


def week_key(d):
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def nearest_expiry(rows, d):
    exps = sorted(e for e in rows if e > d)
    return exps[0] if exps else None


def settle(hsi, dates, e):
    """到期日的恒指收市（到期日不是交易日就用之前最近一天）。"""
    cands = [d for d in dates if d <= e]
    return (cands[-1], hsi[cands[-1]]["close"]) if cands else (None, None)


def realized(hsi, dates, d0, d1):
    seg = [d for d in dates if d0 < d <= d1]
    if len(seg) < 2:
        return None, None
    rets = np.diff(np.log([hsi[d]["close"] for d in [d0] + seg]))
    rv = float(np.sqrt(np.mean(rets ** 2) * 252) * 100)
    rng = (max(hsi[d]["high"] for d in seg) - min(hsi[d]["low"] for d in seg)) / hsi[d0]["close"] * 100
    return rv, rng


def leg(series, strike_target, cp, side_up):
    """找最接近目標的行使價（side_up=True 往上找、否則往下找），回傳 (行使價, 結算價)。"""
    ks = sorted({k for k, c in series if c == cp and series[(k, cp)]["oqp"] > 0})
    if not ks:
        return None, None
    cand = [k for k in ks if (k >= strike_target if side_up else k <= strike_target)]
    k = (min(cand) if side_up else max(cand)) if cand else (ks[-1] if side_up else ks[0])
    return k, series[(k, cp)]["oqp"]


def weekly(atm, series, hsi, vhsi, har, cost):
    dates = sorted(hsi)
    by_week = defaultdict(list)
    for (p, d) in atm:
        if p == "hsiwo" and d in hsi:
            by_week[week_key(d)].append(d)
    rows = []
    for wk in sorted(by_week):
        d = max(by_week[wk])                                # 這週最後一個有報告的交易日
        e = nearest_expiry(atm[("hsiwo", d)], d)
        if not e:
            continue
        a = atm[("hsiwo", d)][e]
        sd, s_t = settle(hsi, dates, e)
        if s_t is None or sd <= d:
            continue
        F, K = a["forward"], a["atm_strike"]
        iv = (a["iv_call"] + a["iv_put"]) / 2
        n_days = len([x for x in dates if d < x <= sd])
        T = n_days / 252
        rv, rng = realized(hsi, dates, d, sd)
        h = har.get(d)
        row = {"entry": d, "expiry": e, "settle_date": sd, "days": n_days, "forward": F, "atm_strike": K,
               "call": a["call_oqp"], "put": a["put_oqp"], "straddle": a["straddle"], "iv_call": a["iv_call"], "iv_put": a["iv_put"],
               "iv": iv, "vhsi": vhsi.get(d), "har_vol": h["vol"] if h else None, "har_pts": h["pts"] if h else None,
               "spot_close": hsi[d]["close"], "settle": s_t, "move": s_t - K, "rv": rv, "range_pct": rng,
               "vol_total": a["vol_total"], "oi_total": a["oi_total"]}
        row["straddle_net"] = a["straddle"] - abs(s_t - K) - 2 * cost
        # 1σ 勒式與鐵鷹（用當天報告裡的真實結算價）
        sig_pts = iv / 100 * math.sqrt(T) * F if T > 0 else 0
        srs = series.get(("hsiwo", d, e), {})
        kp, pp = leg(srs, F - sig_pts, "P", False)
        kc, pc = leg(srs, F + sig_pts, "C", True)
        kp2, pp2 = leg(srs, F - 2 * sig_pts, "P", False)
        kc2, pc2 = leg(srs, F + 2 * sig_pts, "C", True)
        if kp and kc and sig_pts > 0:
            payoff = max(0, kp - s_t) + max(0, s_t - kc)
            row.update(strangle_credit=pp + pc, strangle_net=pp + pc - payoff - 2 * cost, kp=kp, kc=kc)
            if kp2 and kc2 and kp2 < kp and kc2 > kc:
                credit = pp + pc - pp2 - pc2
                payoff2 = payoff - max(0, kp2 - s_t) - max(0, s_t - kc2)
                row.update(condor_credit=credit, condor_net=credit - payoff2 - 4 * cost, kp2=kp2, kc2=kc2,
                           condor_max_loss=min(kp - kp2, kc2 - kc) - credit)
        rows.append(row)
    return rows


def month_expiries(dates):
    """每月到期日 = 當月最後交易日的前一個交易日。回傳 {YYYY-MM: 到期日}。"""
    by_m = defaultdict(list)
    for d in dates:
        by_m[d[:7]].append(d)
    return {m: ds[-2] for m, ds in by_m.items() if len(ds) >= 2}


def monthly(atm, hsi, vhsi, har, cost):
    dates = sorted(hsi)
    exp = month_expiries(dates)
    rows, prev_exp = [], None
    for m in sorted(exp):
        e = exp[m]
        if prev_exp is None:
            prev_exp = e
            continue
        entry = next((d for d in dates if d > prev_exp and ("hsio", d) in atm), None)
        prev_exp = e
        if not entry or entry >= e or m not in atm[("hsio", entry)]:
            continue
        a = atm[("hsio", entry)][m]
        sd, s_t = settle(hsi, dates, e)
        if s_t is None:
            continue
        iv = (a["iv_call"] + a["iv_put"]) / 2
        n_days = len([x for x in dates if entry < x <= sd])
        rv, rng = realized(hsi, dates, entry, sd)
        h = har.get(entry)
        rows.append({"entry": entry, "expiry": sd, "days": n_days, "forward": a["forward"], "atm_strike": a["atm_strike"],
                     "straddle": a["straddle"], "iv": iv, "vhsi": vhsi.get(entry), "har_vol": h["vol"] if h else None,
                     "settle": s_t, "move": s_t - a["atm_strike"], "rv": rv, "range_pct": rng,
                     "straddle_net": a["straddle"] - abs(s_t - a["atm_strike"]) - 2 * cost})
    return rows


def st(x):
    x = np.array([v for v in x if v is not None], dtype=float)
    if len(x) < 2:
        return None
    eq = np.cumsum(x)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return {"n": len(x), "mean": x.mean(), "win": (x > 0).mean(), "worst": x.min(), "t": x.mean() / x.std(ddof=1) * math.sqrt(len(x)),
            "total": x.sum(), "dd": dd}


def fmt(s):
    if not s:
        return "| — | — | — | — | — | — |"
    return f"| {s['n']} | **{s['mean']:+.0f}** | {s['win']:.0%} | {s['worst']:+,.0f} | {s['t']:+.2f} | {s['total']:+,.0f}／{s['dd']:,.0f} |"


HEAD = "| 週數 | **每週平均（點）** | 賺錢週 | 最差一週 | t 值 | 總點數／最大回撤 |\n|---|---|---|---|---|---|"


def write_csv(path, rows):
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})


def report(w, mo, cost, manifest):
    L = ["# 方向一（賣波幅）真實數據回測：港交所恒指週／月期權結算價與 IV", "",
         f"- 週期權 {len(w)} 週（{w[0]['entry']} 至 {w[-1]['entry']}）；月期權 {len(mo)} 個月；每腳成本 {cost:g} 點；1 張（恒指期權每點 HK$50）",
         "- 結算價用到期日恒指收市近似（官方 EAS 是當日每 5 分鐘報價的平均）；O.Q.P. = 港交所官方結算價（日市 16:30）",
         f"- 輸入 SHA-256：atm_iv `{manifest['inputs']['atm_iv.csv'][:16]}…`、恒指 `{manifest['inputs']['hsi'][:16]}…`、VHSI `{manifest['inputs']['vhsi'][:16]}…`、交易日 K `{manifest['inputs']['futu_daily'][:16]}…`",
         "", "## 一、週期權價平 IV 對 VHSI、風揚陣預測、實際波動", ""]
    iv = np.array([r["iv"] for r in w]); vh = np.array([r["vhsi"] or np.nan for r in w], dtype=float)
    hv = np.array([r["har_vol"] or np.nan for r in w], dtype=float); rv = np.array([r["rv"] or np.nan for r in w], dtype=float)
    ok = ~np.isnan(vh) & ~np.isnan(hv) & ~np.isnan(rv)
    L += [f"- 平均：週期權價平 IV **{iv.mean():.1f}%**、VHSI {np.nanmean(vh):.1f}%、風揚陣預測（年化）{np.nanmean(hv):.1f}%、之後一週實際 {np.nanmean(rv):.1f}%",
          f"- IV ÷ VHSI 平均 {np.nanmean(iv[ok] / vh[ok]):.2f}；IV ÷ 風揚陣 {np.nanmean(iv[ok] / hv[ok]):.2f}；VHSI ÷ 風揚陣 {np.nanmean(vh[ok] / hv[ok]):.2f}",
          f"- 週期權 IV 高過之後實際波動的週數：{(iv[ok] > rv[ok]).mean():.0%}；VHSI 高過實際：{(vh[ok] > rv[ok]).mean():.0%}；風揚陣高過實際：{(hv[ok] > rv[ok]).mean():.0%}",
          f"- 與之後實際波動的相關：IV {np.corrcoef(iv[ok], rv[ok])[0, 1]:.2f}、VHSI {np.corrcoef(vh[ok], rv[ok])[0, 1]:.2f}、風揚陣 {np.corrcoef(hv[ok], rv[ok])[0, 1]:.2f}", ""]
    years = sorted({r["entry"][:4] for r in w})
    L += ["| 年 | 週數 | IV | VHSI | 風揚陣 | 實際 | IV÷VHSI | IV÷風揚陣 |", "|---|---|---|---|---|---|---|---|"]
    for y in years:
        sel = [r for r in w if r["entry"][:4] == y and r["vhsi"] and r["har_vol"] and r["rv"]]
        if sel:
            L.append(f"| {y} | {len(sel)} | {np.mean([r['iv'] for r in sel]):.1f} | {np.mean([r['vhsi'] for r in sel]):.1f} | "
                     f"{np.mean([r['har_vol'] for r in sel]):.1f} | {np.mean([r['rv'] for r in sel]):.1f} | "
                     f"{np.mean([r['iv'] / r['vhsi'] for r in sel]):.2f} | {np.mean([r['iv'] / r['har_vol'] for r in sel]):.2f} |")
    L += ["", "## 二、每週沽（真實結算價）", "", "### 全部週", "", "| 策略 " + HEAD[1:], ]
    for name, key in (("沽價平跨式", "straddle_net"), ("沽 1σ 勒式", "strangle_net"), ("鐵鷹（沽 1σ、買 2σ）", "condor_net")):
        L.append(f"| {name} " + fmt(st([r.get(key) for r in w])))
    L += ["", "### 挑時機（只在比值達標的週才沽）", "", "| 規則 | 策略 " + HEAD[1:]]
    filters = [("每週都沽", lambda r: True)]
    for q in (1.0, 1.2, 1.4):
        filters.append((f"IV ÷ 風揚陣 ≥ {q}", lambda r, q=q: r["har_vol"] and r["iv"] / r["har_vol"] >= q))
    for q in (1.0, 1.2, 1.4):
        filters.append((f"VHSI ÷ 風揚陣 ≥ {q}（風揚陣頁的規則）", lambda r, q=q: r["har_vol"] and r["vhsi"] and r["vhsi"] / r["har_vol"] >= q))
    filters.append(("IV ≥ VHSI", lambda r: r["vhsi"] and r["iv"] >= r["vhsi"]))
    filters.append(("IV < VHSI", lambda r: r["vhsi"] and r["iv"] < r["vhsi"]))
    filters.append(("IV < 風揚陣（反過來買？看沽的虧損）", lambda r: r["har_vol"] and r["iv"] < r["har_vol"]))
    for name, f in filters:
        sel = [r for r in w if f(r)]
        for sname, key in (("跨式", "straddle_net"), ("鐵鷹", "condor_net")):
            L.append(f"| {name} | {sname} " + fmt(st([r.get(key) for r in sel])))
    L += ["", "### IV ÷ 風揚陣 四分位 → 沽跨式每週平均（比值有沒有預測力？）", "", "| 四分位 | 比值範圍 " + HEAD[1:]]
    sel = sorted([r for r in w if r["har_vol"]], key=lambda r: r["iv"] / r["har_vol"])
    for i in range(4):
        part = sel[i * len(sel) // 4:(i + 1) * len(sel) // 4]
        if part:
            L.append(f"| Q{i + 1} | {part[0]['iv'] / part[0]['har_vol']:.2f}–{part[-1]['iv'] / part[-1]['har_vol']:.2f} "
                     + fmt(st([r["straddle_net"] for r in part])))
    L += ["", "### 逐年（沽跨式／鐵鷹，每週平均）", "", "| 年 | 跨式 週數 | 跨式 每週 | 跨式 最差 | 鐵鷹 每週 | 鐵鷹 最差 |", "|---|---|---|---|---|---|"]
    for y in years:
        a = st([r["straddle_net"] for r in w if r["entry"][:4] == y]); b = st([r.get("condor_net") for r in w if r["entry"][:4] == y])
        L.append(f"| {y} | {a['n'] if a else 0} | {a['mean']:+.0f} | {a['worst']:+,.0f} | {b['mean']:+.0f} | {b['worst']:+,.0f} |" if a and b else f"| {y} | — | — | — | — | — |")
    L += ["", "## 三、月期權：上月到期翌日沽即月價平跨式，持有到到期", "", "| 策略 " + HEAD[1:].replace("週", "月")]
    L.append("| 沽價平跨式 " + fmt(st([r["straddle_net"] for r in mo])))
    if mo:
        ivm = np.array([r["iv"] for r in mo]); rvm = np.array([r["rv"] or np.nan for r in mo], dtype=float)
        L.append(f"\n- 月期權價平 IV 平均 {ivm.mean():.1f}%，之後實際 {np.nanmean(rvm):.1f}%；IV 高過實際 {(ivm > rvm).mean():.0%} 的月份")
    L += ["", "逐筆：weekly.csv、monthly.csv；重跑：見檔頭用法。"]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opt", default=str(REPO / "data" / "hkex_options"))
    ap.add_argument("--hsi", required=True); ap.add_argument("--vhsi", required=True); ap.add_argument("--futu", required=True)
    ap.add_argument("--cost", type=float, default=COST_LEG)
    a = ap.parse_args()
    hsi, vhsi, har = load_hsi(a.hsi), load_vhsi(a.vhsi), load_har(a.futu)
    atm, series = load_opts(a.opt)
    w = weekly(atm, series, hsi, vhsi, har, a.cost)
    mo = monthly(atm, hsi, vhsi, har, a.cost)
    OUT.mkdir(exist_ok=True)
    write_csv(OUT / "weekly.csv", w); write_csv(OUT / "monthly.csv", mo)
    manifest = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "cost_leg": a.cost,
                "script_sha256": sha(__file__), "weeks": len(w), "months": len(mo),
                "inputs": {"atm_iv.csv": sha(Path(a.opt) / "atm_iv.csv"), "hsi": sha(a.hsi), "vhsi": sha(a.vhsi), "futu_daily": sha(a.futu),
                           "series": {f.name: sha(f) for f in sorted((Path(a.opt) / "series").glob("*.csv.gz"))}}}
    json.dump(manifest, open(OUT / "manifest.json", "w"), ensure_ascii=False, indent=1)
    text = report(w, mo, a.cost, manifest)
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
