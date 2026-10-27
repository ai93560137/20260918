"""[IDEAS #143] V3（200 日均線，好／空倉）紙上前向測試：每個美股交易日收市後跑一次。

規則同 daily_trend_check.py 一樣：每隻收市高過 200 日均線就揸（等權），低過就唔揸；用上日收市訊號，今日先執行；
每單位轉倉成本 0.05%。由 2026-10-28 起累計，對照等權買入持有。只係紙上，唔落單。
輸出 GCS longfei/daily_trend/forward.json（每日倉位、組合回報、累計、最大回撤）。

用法：python3 research/longfei_rulesim/daily_trend_forward.py [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulesim import US  # noqa: E402

START = "2026-10-28"
COST = 0.0005
OBJ = "longfei/daily_trend/forward.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    df = yf.download(US, period="2y", interval="1d", progress=False, auto_adjust=True, group_by="ticker")
    closes = {}
    for p in US:
        try:
            s = df[p]["Close"].dropna()
        except KeyError:
            continue
        closes[p] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
    days = sorted({d for c in closes.values() for d in c})

    def signal(p, d):
        ks = [k for k in sorted(closes[p]) if k <= d]
        if len(ks) < 201:
            return 0.0
        sma = sum(closes[p][k] for k in ks[-201:-1]) / 200
        return 1.0 if closes[p][ks[-1]] > sma else 0.0

    rows, prev = [], {}
    eq = bh = 1.0
    peak, dd = 1.0, 0.0
    run_days = [d for d in days if d >= START]
    for d1 in run_days:
        i = days.index(d1)
        d0 = days[i - 1]
        r_s = r_b = 0.0
        n = 0
        pos = {}
        for p, c in closes.items():
            if d0 in c and d1 in c:
                w = signal(p, d0)
                pos[p] = w
                ret = c[d1] / c[d0] - 1
                r_s += w * ret - abs(w - prev.get(p, w)) * COST
                r_b += ret
                n += 1
        prev = pos
        r_s, r_b = (r_s / n, r_b / n) if n else (0.0, 0.0)
        eq *= 1 + r_s
        bh *= 1 + r_b
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
        rows.append({"date": d1, "ret": round(r_s, 5), "bh_ret": round(r_b, 5), "held": sum(1 for v in pos.values() if v > 0)})
    today = {p: signal(p, days[-1]) for p in closes}
    doc = {"updated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "start": START, "rule": "IDEAS #143 V3",
           "days": len(rows), "cum": round(eq - 1, 4), "bh_cum": round(bh - 1, 4), "max_dd": round(dd, 4),
           "next_positions": sorted(p for p, v in today.items() if v > 0), "rows": rows[-60:]}
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}, ensure_ascii=False))
    if not a.dry_run:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob(OBJ).upload_from_string(
            json.dumps(doc, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
