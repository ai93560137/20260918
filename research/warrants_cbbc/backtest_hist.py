"""歷史回測：恒指窩輪／牛熊證收市價 × 恒指期權官方結算價（同日、同到期、同行使價）→ 每天每隻的溢價／折讓分佈。

資料：
  tradingview/out/warrant_hist/universe.csv      futu/warrant_hist_pull.py 的清單（條款：類型、行使價、收回價、換股比率、到期日）
  tradingview/out/warrant_hist/kline_<code>.csv  每隻日線（Futu）
  data/hkex_options/series/hsio_<年>.csv.gz      恒指期權官方結算價（O.Q.P.，收市 16:30 定價）
  canary/data_external/hsi_daily.csv             恒指收市（牛熊證內在值用）

    python3 research/warrants_cbbc/backtest_hist.py --demo
    python3 research/warrants_cbbc/backtest_hist.py [--dir tradingview/out/warrant_hist] [--out research/warrants_cbbc/backtest_hist.csv]

窩輪：公平價 ＝ 同到期月、同行使價的期權結算價（沒有同行使價 → 相鄰兩個行使價結算價線性插值）÷ 換股比率。
      溢價% ＝ 窩輪收市 ÷ 公平價 − 1。只看到期日落在期權到期月的窩輪（恒指窩輪到期日＝期貨結算日，兩邊同日 EAS 結算）。
牛熊證：折讓（點）＝ 內在值（恒指收市 − 行使價，熊證反向）− 收市 × 換股比率；距收回價% ＝ |恒指 − 收回價| ÷ 恒指。
注意：窩輪收市價是最後一口成交，不是收市時的賣價；期權結算價是中價性質。差價成本另計（第三節）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import gzip
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES_DIR = ROOT / "data" / "hkex_options" / "series"
HSI_DAILY = ROOT / "canary" / "data_external" / "hsi_daily.csv"


def load_option_settle() -> dict[tuple[str, str], dict[tuple[int, str], float]]:
    """(date, expiry_month) → {(strike, 'C'/'P'): oqp}"""
    out: dict = defaultdict(dict)
    for path in sorted(SERIES_DIR.glob("hsio_*.csv.gz")):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if len(r["expiry"]) != 7:
                    continue
                try:
                    out[(r["date"], r["expiry"])][(int(r["strike"]), r["cp"])] = float(r["oqp"])
                except ValueError:
                    continue
    return out


def load_hsi() -> dict[str, float]:
    out = {}
    if HSI_DAILY.exists():
        with open(HSI_DAILY, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    out[r["Date"][:10]] = float(r["Close"])
                except ValueError:
                    pass
    return out


def option_fair(chain: dict[tuple[int, str], float], k: float, cp: str) -> tuple[float | None, str]:
    key = (int(round(k)), cp)
    if key in chain and chain[key] > 0:
        return chain[key], "同行使價"
    ks = sorted(s for (s, c) in chain if c == cp and chain[(s, c)] > 0)
    lo = [s for s in ks if s < k]
    hi = [s for s in ks if s > k]
    if not lo or not hi:
        return None, "超出範圍"
    a, b = lo[-1], hi[0]
    if b - a > 400:
        return None, "格距太大"
    w = (k - a) / (b - a)
    return chain[(a, cp)] * (1 - w) + chain[(b, cp)] * w, "插值"


def load_universe(d: Path) -> list[dict]:
    with open(d / "universe.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_kline(d: Path, code: str) -> list[dict]:
    p = d / f"kline_{code.replace('.', '_')}.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(d: Path) -> list[dict]:
    settle = load_option_settle()
    hsi = load_hsi()
    rows = []
    for u in load_universe(d):
        code, typ = str(u["stock"]), str(u["type"]).upper()
        try:
            K = float(u["strike_price"]); R = float(u["conversion_ratio"]); mat = str(u["maturity_time"])[:10]
            call_lv = float(u.get("recovery_price") or 0)
        except (ValueError, TypeError):
            continue
        month = mat[:7]
        for k in load_kline(d, code):
            day = str(k["time_key"])[:10]
            try:
                close = float(k["close"])
            except (ValueError, TypeError):
                continue
            if close <= 0:
                continue
            base = {"date": day, "code": code, "type": typ, "issuer": u.get("issuer", ""), "strike": K, "ratio": R, "expiry": mat,
                    "close": close, "days": (dt.date.fromisoformat(mat) - dt.date.fromisoformat(day)).days}
            if base["days"] <= 0:
                continue
            if typ in ("CALL", "PUT"):
                chain = settle.get((day, month))
                if not chain:
                    rows.append({**base, "note": "當日無期權結算價"})
                    continue
                fair_pts, src = option_fair(chain, K, "C" if typ == "CALL" else "P")
                if fair_pts is None or fair_pts <= 0:
                    rows.append({**base, "note": src})
                    continue
                rows.append({**base, "fair_pts": fair_pts, "fair_price": fair_pts / R, "premium_pct": (close * R / fair_pts - 1) * 100,
                             "fair_src": src, "note": ""})
            elif typ in ("BULL", "BEAR"):
                S = hsi.get(day)
                if not S:
                    rows.append({**base, "note": "當日無恒指收市"})
                    continue
                intrinsic = (S - K) if typ == "BULL" else (K - S)
                rows.append({**base, "hsi": S, "call_level": call_lv, "intrinsic_pts": intrinsic, "discount_pts": intrinsic - close * R,
                             "discount_pct": (intrinsic - close * R) / intrinsic * 100 if intrinsic > 0 else None,
                             "dist_call_pct": abs(S - call_lv) / S * 100 if call_lv else None, "note": ""})
    return rows


def q(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else None


def summarize(rows: list[dict]) -> str:
    out = []
    w = [r for r in rows if r.get("note") == "" and r["type"] in ("CALL", "PUT")]
    c = [r for r in rows if r.get("note") == "" and r["type"] in ("BULL", "BEAR")]
    if w:
        prem = [r["premium_pct"] for r in w]
        out.append(f"[窩輪] {len(w)} 個日×證（{len({r['code'] for r in w})} 隻，{len({r['date'] for r in w})} 天）："
                   f"收市價相對期權公平價溢價 中位 {q(prem, .5):+.1f}%，10% {q(prem, .1):+.1f}%，90% {q(prem, .9):+.1f}%；負溢價佔 {sum(1 for p in prem if p < 0) / len(prem):.1%}")
        for bucket, lo_, hi_ in (("≤10 日", 0, 10), ("11–30 日", 11, 30), ("31–90 日", 31, 90), (">90 日", 91, 10_000)):
            sub = [r["premium_pct"] for r in w if lo_ <= r["days"] <= hi_]
            if sub:
                out.append(f"   到期 {bucket}: {len(sub)} 個，溢價中位 {q(sub, .5):+.1f}%，負溢價 {sum(1 for p in sub if p < 0) / len(sub):.1%}")
        for iss in sorted({r["issuer"] for r in w}):
            sub = [r["premium_pct"] for r in w if r["issuer"] == iss]
            if len(sub) >= 30:
                out.append(f"   發行商 {iss}: {len(sub)} 個，溢價中位 {q(sub, .5):+.1f}%")
    if c:
        far = [r for r in c if r.get("dist_call_pct") is not None and r["dist_call_pct"] >= 3 and r["intrinsic_pts"] > 0]
        near = [r for r in c if r.get("dist_call_pct") is not None and r["dist_call_pct"] < 3 and r["intrinsic_pts"] > 0]
        out.append(f"[牛熊證] {len(c)} 個日×證（{len({r['code'] for r in c})} 隻）")
        for label, sub in (("距收回價 ≥3%", far), ("距收回價 <3%", near)):
            if sub:
                dsc = [r["discount_pts"] for r in sub]
                out.append(f"   {label}: {len(sub)} 個，折讓中位 {q(dsc, .5):+.0f} 點，90% {q(dsc, .9):+.0f} 點，折讓 >10 點佔 {sum(1 for x in dsc if x > 10) / len(dsc):.1%}，>30 點佔 {sum(1 for x in dsc if x > 30) / len(dsc):.1%}")
    skipped = defaultdict(int)
    for r in rows:
        if r.get("note"):
            skipped[r["note"]] += 1
    if skipped:
        out.append(f"略過：{dict(skipped)}")
    return "\n".join(out) if out else "沒有可算的列（universe.csv／kline_*.csv／期權結算價三者至少一樣缺）"


def demo() -> None:
    chain = {(24_000, "C"): 461.0, (24_200, "C"): 352.0, (24_400, "C"): 257.0, (24_000, "P"): 272.0}
    assert option_fair(chain, 24_200, "C") == (352.0, "同行使價")
    v, s = option_fair(chain, 24_100, "C"); assert s == "插值" and abs(v - 406.5) < 1e-9
    assert option_fair(chain, 25_000, "C")[0] is None
    rows = [{"note": "", "type": "CALL", "code": "A", "date": "d", "days": 20, "issuer": "X", "premium_pct": 25.0},
            {"note": "", "type": "BULL", "code": "B", "dist_call_pct": 5.0, "intrinsic_pts": 1000, "discount_pts": 12.0}]
    print("自我檢查通過。")
    print(summarize(rows))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--dir", default=str(ROOT / "tradingview" / "out" / "warrant_hist"))
    ap.add_argument("--out", default=str(ROOT / "research" / "warrants_cbbc" / "backtest_hist.csv"))
    a = ap.parse_args()
    if a.demo:
        demo()
        return
    d = Path(a.dir)
    if not (d / "universe.csv").exists():
        raise SystemExit(f"找不到 {d / 'universe.csv'}：先在 OpenD 電腦跑 python futu\\warrant_hist_pull.py --limit N")
    rows = run(d)
    print(summarize(rows))
    keys = sorted({k for r in rows for k in r})
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"已寫入 {a.out}（{len(rows)} 列）")


if __name__ == "__main__":
    main()
