"""波幅開閘深挖（2026-10-04，用戶：「這個方向繼續」）：蛇蟠陣／🅱️ 的利潤集中在「預測波幅高」的日子入市——這個發現有多穩？

檢查：
  1. 門檻與回看期：R̂ ÷ 過去 N 日中位 的門檻 1.0–2.0、N = 120／250／500，期望值是否隨門檻單調上升（不是某個值碰巧好）。
  2. 其他開閘定義：R̂ 在過去一年的分位；R̂ ÷ 20 日實際平均波幅；R̂ 比 5 日前升了多少；只用昨日實際波幅（不用 HAR）——
     看 HAR 預測有沒有比「昨天很波動」多一點東西。
  3. 機制：高 R̂ 日入市的交易，持倉多久、走多遠？把盈虧除以入市日 R̂（以 R̂ 為單位）之後，高低兩組還有沒有分別？
     有 → 真正的「狀態」效應；沒有 → 只是「利潤跟波幅成正比、成本不變」。
  4. 36 年恒指日線：蛇蟠陣（N=3 日通道）用 20 日波幅 ÷ 250 日波幅 ≥ 門檻 開閘，按年代看高低兩組。
數據：Futu 15 分 K（2024-06 起）、HK50 差價合約（2022-08 起）、恒指日線 1990 起。成本 3 點（日線 2bp）。
2026-10-04 修正：蛇的分組日改為入市日（原本誤用出場日），蛇那幾節的數字因此改變；🅱️🅰️ 一直都是按入市日。
用法：python3 research/hsi_futures_range/vol_gate.py --json 15 分 K 快取 --hsi hsi.csv
輸出：research/hsi_futures_range/vol_gate/REPORT.md
"""
import argparse, csv, json, math, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import snake_band as sb                                  # noqa: E402
import hk50_cfd                                          # noqa: E402

OUT = HERE / "vol_gate"
COST = 3.0


def prep(bars, daily):
    days = hl.build_days(bars, daily)
    rh = np.array([d["rhat"] for d in days])
    for i, d in enumerate(days):
        d["rng"] = max(b["high"] for b in d["bars"]) - min(b["low"] for b in d["bars"])
        for n in (120, 250, 500):
            past = rh[max(0, i - n):i]
            d[f"med{n}"] = float(np.median(past)) if len(past) >= 60 else None
        past = rh[max(0, i - 250):i]
        d["pct250"] = float((past < d["rhat"]).mean()) if len(past) >= 60 else None
        d["rv20"] = float(np.mean([x["rng"] for x in days[max(0, i - 20):i]])) if i >= 20 else None
        d["r5"] = days[i - 5]["rhat"] if i >= 5 else None
        d["prev_rng"] = days[i - 1]["rng"] if i >= 1 else None
        d["prev_med250"] = float(np.median([x["rng"] for x in days[max(0, i - 250):i]])) if i >= 60 else None
    return days


def snake_trades(days):
    """蛇的每筆按**入市日**分組。snake_run 記的日期是反手（出場）那天，入市日 = 上一筆的出場日；第一筆沒有入市日不計。
    （2026-10-04 修正：原本用紀錄的日期即出場日分組，令「開閘」看起來對蛇很有效；見 gate_tilt.py 的核對。）"""
    _, _, tr = sb.snake_run(sb.snake_days(days), COST)
    by = {d["date"]: d for d in days}
    out = []
    for i in range(1, len(tr)):
        d, (_, side, pnl) = tr[i - 1][0], tr[i]
        if d not in by:
            continue
        out.append({"date": d, "side": side, "net": pnl, "day": by[d], "exit_date": tr[i][0]})
    return out


def ledger_trades(path, days):
    by = {d["date"]: d for d in days}
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r["entry_date"] in by:
            out.append({"date": r["entry_date"], "net": float(r["net"]), "day": by[r["entry_date"]],
                        "sessions": int(r["sessions"]) if r.get("sessions") else None})
    return out


def st(x):
    x = np.array(x, dtype=float)
    if len(x) < 3:
        return None
    return {"n": len(x), "mean": x.mean(), "win": (x > 0).mean(), "t": x.mean() / x.std(ddof=1) * math.sqrt(len(x)), "total": x.sum()}


def cell(s, dec=0):
    return f"{s['n']} 筆 {s['mean']:+.{dec}f}（t {s['t']:+.1f}）" if s else "—"


def split(trades, key_fn):
    vals = [(t, key_fn(t["day"])) for t in trades]
    hi = [t["net"] for t, v in vals if v is not None and bool(v)]
    lo = [t["net"] for t, v in vals if v is not None and not bool(v)]
    return st(hi), st(lo)


def section_sweep(name, trades):
    L = [f"### {name}", "", "| 門檻 | 回看 120 日 高／低 | 回看 250 日 高／低 | 回看 500 日 高／低 |", "|---|---|---|---|"]
    for th in (1.0, 1.1, 1.2, 1.3, 1.5, 2.0):
        cells = []
        for n in (120, 250, 500):
            hi, lo = split(trades, lambda d, n=n, th=th: None if d[f"med{n}"] is None else d["rhat"] / d[f"med{n}"] >= th)
            cells.append(f"{cell(hi)} ／ {cell(lo)}")
        L.append(f"| R̂ ≥ {th}×中位 | " + " | ".join(cells) + " |")
    L += ["", "| 其他開閘定義 | 開 | 關 |", "|---|---|---|"]
    alts = [("R̂ 在過去一年分位 ≥ 80%", lambda d: None if d["pct250"] is None else d["pct250"] >= 0.8),
            ("R̂ 在過去一年分位 ≥ 90%", lambda d: None if d["pct250"] is None else d["pct250"] >= 0.9),
            ("R̂ ≥ 1.2 × 過去 20 日實際平均波幅", lambda d: None if d["rv20"] is None else d["rhat"] >= 1.2 * d["rv20"]),
            ("R̂ 比 5 日前升 ≥ 20%", lambda d: None if d["r5"] is None else d["rhat"] >= 1.2 * d["r5"]),
            ("只看昨日實際波幅 ≥ 1.2 × 250 日中位（不用 HAR）", lambda d: None if d["prev_med250"] is None or d["prev_rng"] is None else d["prev_rng"] >= 1.2 * d["prev_med250"]),
            ("只看昨日實際波幅 ≥ 1.5 × 250 日中位", lambda d: None if d["prev_med250"] is None or d["prev_rng"] is None else d["prev_rng"] >= 1.5 * d["prev_med250"]),
            ("HAR 開（1.2）但昨日實際沒開（1.2）", lambda d: None if d["med250"] is None or d["prev_med250"] is None else (d["rhat"] / d["med250"] >= 1.2 and d["prev_rng"] < 1.2 * d["prev_med250"])),
            ("昨日實際開（1.2）但 HAR 沒開", lambda d: None if d["med250"] is None or d["prev_med250"] is None else (d["prev_rng"] >= 1.2 * d["prev_med250"] and d["rhat"] / d["med250"] < 1.2))]
    for lab, fn in alts:
        hi, lo = split(trades, fn)
        L.append(f"| {lab} | {cell(hi)} | {cell(lo)} |")
    # 機制：以 R̂ 為單位
    hi = [t for t in trades if t["day"]["med250"] and t["day"]["rhat"] / t["day"]["med250"] >= 1.2]
    lo = [t for t in trades if t["day"]["med250"] and t["day"]["rhat"] / t["day"]["med250"] < 1.2]
    def r_unit(ts):
        return st([t["net"] / t["day"]["rhat"] for t in ts])
    L += ["", "| 機制（門檻 1.2、回看 250） | 開 | 關 |", "|---|---|---|",
          f"| 入市日 R̂ 平均（點） | {np.mean([t['day']['rhat'] for t in hi]):.0f} | {np.mean([t['day']['rhat'] for t in lo]):.0f} |",
          f"| 每筆淨利 ÷ 入市日 R̂（以 R̂ 為單位） | {cell(r_unit(hi), 2)} | {cell(r_unit(lo), 2)} |"]
    if hi and hi[0].get("sessions") is not None:
        L.append(f"| 平均持倉交易日 | {np.mean([t['sessions'] for t in hi]):.1f} | {np.mean([t['sessions'] for t in lo]):.1f} |")
    L.append("")
    return L


def long_run(hsi_path):
    rows = [r for r in csv.DictReader(open(hsi_path, encoding="utf-8")) if float(r["High"]) != float(r["Low"]) and r["Date"] >= "1990-01-01"]
    d = [r["Date"] for r in rows]; O = np.array([float(r["Open"]) for r in rows]); H = np.array([float(r["High"]) for r in rows])
    Lo = np.array([float(r["Low"]) for r in rows]); C = np.array([float(r["Close"]) for r in rows])
    rng = (H - Lo) / C
    m20 = np.array([np.mean(rng[max(0, i - 20):i]) if i >= 20 else np.nan for i in range(len(C))])
    m250 = np.array([np.median(rng[max(0, i - 250):i]) if i >= 60 else np.nan for i in range(len(C))])
    N, cost = 3, 2e-4
    pos, px, ent = 0, None, None
    tr = []
    for k in range(N, len(C)):
        up, lo = H[k - N:k].max(), Lo[k - N:k].min()
        hits = []
        if H[k] >= up and pos <= 0: hits.append(("up", max(up, O[k])))
        if Lo[k] <= lo and pos >= 0: hits.append(("dn", min(lo, O[k])))
        hits.sort(key=lambda h: abs(h[1] - O[k]))
        for side, f in hits:
            if side == "up" and pos <= 0:
                if pos < 0: tr.append((ent, (px - f) / px - cost))
                pos, px, ent = 1, f, k
            elif side == "dn" and pos >= 0:
                if pos > 0: tr.append((ent, (f - px) / px - cost))
                pos, px, ent = -1, f, k
    L = ["## 四、恒指日線 36 年：蛇蟠陣（3 日通道）× 波幅開閘（入市日 20 日平均波幅 ÷ 250 日中位波幅）", "",
         "| 年代 | 門檻 | 開：筆數、每筆（基點）、t | 關：筆數、每筆、t |", "|---|---|---|---|"]
    for a, b in (("1990", "2000"), ("2000", "2010"), ("2010", "2020"), ("2020", "2027"), ("1990", "2027")):
        for th in (1.2, 1.5):
            hi = [p * 1e4 for e, p in tr if a <= d[e][:4] < b and not np.isnan(m250[e]) and m20[e] / m250[e] >= th]
            lo = [p * 1e4 for e, p in tr if a <= d[e][:4] < b and not np.isnan(m250[e]) and m20[e] / m250[e] < th]
            sh, sl = st(hi), st(lo)
            L.append(f"| {a}s | {th} | {cell(sh)} | {cell(sl)} |")
    return L


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--json", required=True); ap.add_argument("--hsi", required=True); a = ap.parse_args()
    cache = json.load(open(a.json))
    fu = prep(cache["bars"], cache["daily"])
    hb, hd = hk50_cfd.load(); hk = prep(hb, hd)
    L = ["# 波幅開閘深挖（vol_gate.py）", "", "每格 = 筆數、每筆淨利（點）、t；「高／低」= 開閘日入市 ／ 其餘日入市。", "",
         "## 一、門檻與回看期（期望值應隨門檻單調上升）", ""]
    L += section_sweep("Futu 🐍 蛇蟠陣（2024-06 起）", snake_trades(fu))
    L += section_sweep("HK50 🐍 蛇蟠陣（2022-08 起）", snake_trades(hk))
    L += ["## 二、🅱️＋跟蛇＋3R", ""]
    L += section_sweep("Futu 🅱️＋跟蛇＋3R", ledger_trades(HERE / "r_sweep" / "futu" / "trades" / "B_S_R3.csv", fu))
    L += section_sweep("HK50 🅱️＋跟蛇＋3R", ledger_trades(HERE / "r_sweep" / "hk50" / "trades" / "B_S_R3.csv", hk))
    L += ["## 三、🅰️＋跟蛇＋2R", ""]
    L += section_sweep("Futu 🅰️＋跟蛇＋2R", ledger_trades(HERE / "r_sweep" / "futu" / "trades" / "A_S_R2.csv", fu))
    L += section_sweep("HK50 🅰️＋跟蛇＋2R", ledger_trades(HERE / "r_sweep" / "hk50" / "trades" / "A_S_R2.csv", hk))
    L += long_run(a.hsi)
    OUT.mkdir(exist_ok=True)
    text = "\n".join(L) + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
