"""方向一：賣恒指週期權（合成回測）——期權 IV 長期高於實際波幅嗎？用風揚陣預測挑時機有沒有幫助？

數據：
  VHSI（恒指波幅指數，HK.800125）日 K：GCS archive/futu_k_day/HK.800125/（本地腳本 v11 --probe-iv --push）
  恒指即月期貨 15 分 K 與交易日 K：同 high_low_in.py（逐日前推的 HAR 預測 R̂）

合成交易（每週一筆，只用當時已知的數據）：
  進場：這週第一個交易日 09:15 開市價 S0；IV = 前一個交易日 VHSI 收市（年化 %）。
  到期：這週最後一個交易日 16:00 前最後一根 15 分 K 收市（近似週期權結算價；週期權在週五或該週最後交易日到期）。
  T = 交易日數 ÷ 252。定價用 Black-76（利率 0，期貨作標的），整條微笑都用同一個 IV（VHSI）。
  策略：沽價平跨式（Call＋Put 同一行使價 S0）；沽勒式（行使價 S0 ± m × σ√T × S0）；
        鐵鷹（沽 ±1σ、買 ±2σ 保護，最大虧損有上限）。
  成本：每一腳 COST_LEG 點（買賣差價一半＋手續費，持有到期不用平倉）。盈虧以指數點計，恒指期權每點 HK$50，小型 HK$10。
挑時機：比值 = VHSI ÷ 風揚陣預測年化波幅（第一天 R̂ ÷ 1.596 ÷ 昨收 × √252）。
  比值在「之前所有週」裡的百分位 ≥ p 才賣（p = 0 即每週都賣）；p 在前半段挑，後半段報成績。

限制：VHSI 是 30 日、價平附近的 IV，週期權的實際 IV、價差、波幅微笑（價外 Put 較貴）都不同；
  結算價用 16:00 前最後一根 K 線近似；結果只能作方向參考，不是可直接交易的回測。

用法：python3 research/hsi_futures_range/vol_premium.py [--json 15 分 K 快取] [--vhsi VHSI 快取] [--cost 4]
"""
import argparse, json, math, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import high_low_in as hl                                 # noqa: E402

COST_LEG = 4.0
SQRT2 = math.sqrt(2.0)


def ncdf(x):
    return 0.5 * math.erfc(-x / SQRT2)


def black(F, K, sig, T, kind):
    if sig <= 0 or T <= 0:
        return max(F - K, 0.0) if kind == "C" else max(K - F, 0.0)
    v = sig * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    return F * ncdf(d1) - K * ncdf(d2) if kind == "C" else K * ncdf(-d2) - F * ncdf(-d1)


def load_vhsi_gcs(code="HK.800125"):
    sys.path.insert(0, str(hl.REPO / "scripts"))
    import gcp_agent as g
    ctx = g.Ctx(argparse.Namespace(region=None, function=None, bucket=None, project=None))
    s, base = ctx.session, f"https://storage.googleapis.com/storage/v1/b/{ctx.bucket}/o"
    names, token = [], None
    while True:
        params = {"prefix": f"archive/futu_k_day/{code}/", "fields": "items(name),nextPageToken"}
        if token:
            params["pageToken"] = token
        r = s.get(base, params=params).json()
        names += [i["name"] for i in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    bars = {}
    for n in names:
        for b in s.get(f"{base}/{n.replace('/', '%2F')}", params={"alt": "media"}).json():
            bars[b["time_key"]] = b
    return [bars[k] for k in sorted(bars)]


def build_weeks(days, vhsi):
    """每週一筆：進場價、到期價、IV、風揚陣預測年化波幅、交易日數。"""
    vix_dates = sorted(vhsi)
    groups = defaultdict(list)
    for d in days:
        y, w, _ = date.fromisoformat(d["date"]).isocalendar()
        groups[f"{y}-W{w:02d}"].append(d)
    weeks = []
    for key in sorted(groups):
        sess = groups[key]
        first, last = sess[0], sess[-1]
        prior = [v for v in vix_dates if v < first["date"]]
        if not prior or len(sess) < 2:
            continue
        iv = vhsi[prior[-1]] / 100
        day_bars = [b for b in last["bars"] if b["time_key"][:10] == last["date"] and b["time_key"][11:16] <= "16:00"]
        if not day_bars:
            continue
        har = first["rhat"] / 1.596 / first["ref"] * math.sqrt(252)
        weeks.append({"key": key, "first": first["date"], "n": len(sess), "S0": first["bars"][0]["open"],
                      "ST": day_bars[-1]["close"], "iv": iv, "har": har, "ratio": iv / har,
                      "iv_date": prior[-1]})
    for i, w in enumerate(weeks):                                   # 比值在之前所有週裡的百分位（只用過去）
        past = [x["ratio"] for x in weeks[:i]]
        w["pct"] = (sum(1 for x in past if x <= w["ratio"]) / len(past) * 100) if len(past) >= 20 else None
    return weeks


STRATS = {
    "沽價平跨式": [("C", 0.0, -1), ("P", 0.0, -1)],
    "沽 0.5σ 勒式": [("C", 0.5, -1), ("P", -0.5, -1)],
    "沽 1σ 勒式": [("C", 1.0, -1), ("P", -1.0, -1)],
    "鐵鷹 1σ／2σ": [("C", 1.0, -1), ("P", -1.0, -1), ("C", 2.0, 1), ("P", -2.0, 1)],
}


def trade(w, legs, cost):
    T = w["n"] / 252
    S0, ST, sig = w["S0"], w["ST"], w["iv"]
    pnl = 0.0
    for kind, m, qty in legs:
        K = S0 * (1 + m * sig * math.sqrt(T))
        prem = black(S0, K, sig, T, kind)
        pay = max(ST - K, 0.0) if kind == "C" else max(K - ST, 0.0)
        pnl += qty * (pay - prem) - cost
    return pnl


def stats(p):
    a = np.array(p, float)
    if not len(a):
        return {"n": 0}
    eq = np.cumsum(a)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq))
    sd = float(a.std(ddof=1)) if len(a) > 1 else float("nan")
    return {"n": len(a), "mean": float(a.mean()), "win": float((a > 0).mean()), "total": float(a.sum()),
            "worst": float(a.min()), "dd": dd, "t": float(a.mean() / sd * math.sqrt(len(a))) if sd > 0 else float("nan"),
            "sharpe": float(a.mean() / sd * math.sqrt(52)) if sd > 0 else float("nan")}


def fmt(s):
    if not s.get("n"):
        return "| 0 | — | — | — | — | — | — |"
    return (f"| {s['n']} | {s['win']:.0%} | **{s['mean']:+.1f}** | {s['t']:+.2f} | {s['sharpe']:+.2f} | "
            f"{s['worst']:+,.0f} | {s['total']:+,.0f}／{s['dd']:,.0f} |")


HEAD = ("| 策略 | 挑時機 | 週數 | 賺錢週 | **每週平均（點）** | t 值 | 年化夏普 | 最差一週 | 總點數／最大回撤 |\n"
        "|---|---|---|---|---|---|---|---|---|")
PCTS = (0, 25, 50, 75)


def select(weeks, p):
    return [w for w in weeks if p == 0 or (w["pct"] is not None and w["pct"] >= p)]


def report(weeks, cost):
    ok = [w for w in weeks if w["pct"] is not None]                  # 頭 20 週只用來建立百分位
    half = len(ok) // 2
    train, test = ok[:half], ok[half:]
    iv = np.array([w["iv"] for w in ok]); har = np.array([w["har"] for w in ok])
    moves = np.array([abs(math.log(w["ST"] / w["S0"])) / math.sqrt(w["n"] / 252) for w in ok])
    straddle = np.array([2 * black(w["S0"], w["S0"], w["iv"], w["n"] / 252, "C") for w in ok])
    payoff = np.array([abs(w["ST"] - w["S0"]) for w in ok])
    lines = [f"\n共 {len(ok)} 週（{ok[0]['key']} 至 {ok[-1]['key']}），訓練 {len(train)}／測試 {len(test)}，每腳成本 {cost:g} 點",
             "",
             "**市場預期 vs 實際**",
             "",
             f"- VHSI 平均 {iv.mean() * 100:.1f}%；風揚陣預測（區間換算）平均 {har.mean() * 100:.1f}%；"
             f"實際週變動換算年化 {moves.mean() * math.sqrt(math.pi / 2) * 100:.1f}%（|週變動| 平均 × √(π/2)）。",
             f"- 價平跨式：平均權利金 {straddle.mean():,.0f} 點，平均到期價值 {payoff.mean():,.0f} 點 → "
             f"賣方平均每週毛賺 {straddle.mean() - payoff.mean():+,.0f} 點（未扣成本），"
             f"權利金高於到期價值的週數 {np.mean(straddle > payoff):.0%}。",
             f"- 比值（VHSI ÷ 風揚陣預測）中位數 {np.median([w['ratio'] for w in ok]):.2f}；"
             f"比值與賣方毛利的相關系數 {np.corrcoef([w['ratio'] for w in ok], straddle - payoff)[0, 1]:+.2f}。",
             ""]
    out = {}
    for name, legs in STRATS.items():
        res = []
        for p in PCTS:
            tr = stats([trade(w, legs, cost) for w in select(train, p)])
            res.append((tr.get("mean", -1e9) if tr["n"] >= 15 else -1e9, p, tr))
        best = max(res)[1]
        lines.append(f"\n**{name}**（前半段挑出：比值百分位 ≥ {best}）\n")
        lines.append(HEAD)
        rows = {}
        for p in PCTS:
            full = stats([trade(w, legs, cost) for w in select(ok, p)])
            te = stats([trade(w, legs, cost) for w in select(test, p)])
            rows[p] = {"full": full, "test": te}
            tag = "每週都賣" if p == 0 else f"比值 ≥ 過去 {p}% 分位"
            star = "（挑中）" if p == best else ""
            lines.append(f"| {name} | {tag}{star}・全樣本 " + fmt(full))
            lines.append(f"| {name} | {tag}{star}・後半段 " + fmt(te))
        out[name] = {"best": best, "rows": rows}
    return "\n".join(lines), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="15 分 K 快取 {bars, daily}（high_low_in.py 同格式）")
    ap.add_argument("--vhsi", help="VHSI 日 K 快取（JSON 清單）")
    ap.add_argument("--cost", type=float, default=COST_LEG)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.json and Path(a.json).exists():
        cache = json.load(open(a.json))
        bars, daily = cache["bars"], cache["daily"]
    else:
        bars, daily = hl.load_gcs("K_15M")
    vb = json.load(open(a.vhsi)) if a.vhsi and Path(a.vhsi).exists() else load_vhsi_gcs()
    vhsi = {b["time_key"][:10]: float(b["close"]) for b in vb}
    days = hl.build_days(bars, daily)
    weeks = build_weeks(days, vhsi)
    text, out = report(weeks, a.cost)
    print(f"VHSI {len(vhsi)} 天（{min(vhsi)} 至 {max(vhsi)}）；期貨 {len(days)} 個交易日；{len(weeks)} 週")
    print(text)
    if a.out:
        json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
