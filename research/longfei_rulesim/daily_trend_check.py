"""[IDEAS #143] 美股日線順勢（時間序列動量）長歷史驗證（使用者 10-27 揀 B）。

學術來源：Moskowitz, Ooi, Pedersen (2012)「Time Series Momentum」（JFE）；Faber (2007) 10 個月均線擇時；
Hurst, Ooi, Pedersen (2017)「A Century of Evidence on Trend-Following Investing」。
美股即日四個方法（#130 #131 #141 #142）都冇優勢，所以改揸幾星期至幾個月嘅日線級別。

數據：yfinance 日線（2010-01 起），rulesim 嘅 23 隻美股 ETF／股票，等權組合。
變體（10-28 預先登記，唔再調參數）：
  V1  12 個月動量，好／淡：每月尾睇過去 252 日回報，正就做好、負就沽空，揸一個月
  V2  12 個月動量，好／空倉：正就做好、負就唔揸
  V3  200 日均線，好／空倉：每日收市高過 200 日均線就揸，低過就唔揸（第二日先執行）
對照 B&H：等權買入持有。
成本：倉位每變動 1 單位扣 0.05%。

成功標準（預先登記）：
  樣本內 2010–2019、樣本外 2020–2026-10 分開計；某個變體要兩段都年化回報 > 0，而且樣本外：
  夏普 ≥ 0.5，同埋（夏普 ≥ B&H 夏普，或者最大回撤 ≤ B&H 嘅 0.6 倍而夏普 ≥ B&H 嘅 0.8 倍）。
過咗先加入模擬做紙上前向測試（日線、每日收市後執行）；唔過就棄用。只係研究，唔落單。

用法：python3 research/longfei_rulesim/daily_trend_check.py [--no-upload]
"""
import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rulesim import US  # noqa: E402

COST = 0.0005
SPLIT = "2020-01-01"


def perf(rets, dates):
    if len(rets) < 50:
        return {"n": len(rets)}
    eq, peak, dd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1)
    years = len(rets) / 252
    m = sum(rets) / len(rets)
    sd = (sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
    return {"from": dates[0], "to": dates[-1], "cagr": round(eq ** (1 / years) - 1, 4),
            "sharpe": round(m / sd * math.sqrt(252), 2) if sd else None, "max_dd": round(dd, 4),
            "vol": round(sd * math.sqrt(252), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    df = yf.download(US, start="2009-01-01", interval="1d", progress=False, auto_adjust=True, group_by="ticker")
    closes = {}
    for p in US:
        try:
            s = df[p]["Close"].dropna()
        except KeyError:
            continue
        closes[p] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
    dates = sorted({d for c in closes.values() for d in c if d >= "2010-01-01"})
    alld = sorted({d for c in closes.values() for d in c})

    def pos_series(p, kind):
        c = closes[p]
        ks = [d for d in alld if d in c]
        out, cur, month = {}, 0.0, None
        for i, d in enumerate(ks):
            if kind == "V3":
                if i >= 200:
                    sma = sum(c[k] for k in ks[i - 200:i]) / 200
                    cur = 1.0 if c[d] > sma else 0.0
            else:
                m = d[:7]
                if m != month and i >= 252:                     # 每月第一個交易日用上日資料調倉
                    r = c[ks[i - 1]] / c[ks[i - 253]] - 1
                    cur = (1.0 if r > 0 else (-1.0 if kind == "V1" else 0.0))
                month = m
            out[d] = cur
        return out

    results = {}
    for kind in ("V1", "V2", "V3", "BH"):
        pos = {p: ({d: 1.0 for d in closes[p]} if kind == "BH" else pos_series(p, kind)) for p in closes}
        port, prev_pos = [], {}
        for i in range(1, len(dates)):
            d0, d1 = dates[i - 1], dates[i]
            rs, n = 0.0, 0
            for p, c in closes.items():
                if d0 in c and d1 in c:
                    w = pos[p].get(d0, 0.0)                       # 用上日收市嘅訊號，今日先執行
                    cost = abs(w - prev_pos.get(p, 0.0)) * COST
                    rs += w * (c[d1] / c[d0] - 1) - cost
                    prev_pos[p] = w
                    n += 1
            port.append((d1, rs / n if n else 0.0))
        ins = [(d, r) for d, r in port if d < SPLIT]
        oos = [(d, r) for d, r in port if d >= SPLIT]
        results[kind] = {"in": perf([r for _, r in ins], [d for d, _ in ins]),
                         "oos": perf([r for _, r in oos], [d for d, _ in oos])}
        print(kind, results[kind], flush=True)

    bh = results["BH"]["oos"]
    for k in ("V1", "V2", "V3"):
        r = results[k]
        o = r["oos"]
        ok = (r["in"].get("cagr", -1) > 0 and o.get("cagr", -1) > 0 and (o.get("sharpe") or 0) >= 0.5 and
              ((o["sharpe"] >= bh["sharpe"]) or (o["max_dd"] >= 0.6 * bh["max_dd"] and o["sharpe"] >= 0.8 * bh["sharpe"])))
        r["pass"] = bool(ok)
    rep = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "split": SPLIT,
           "tickers": sorted(closes), "rule": "IDEAS #143 預先登記（見檔頭）", "results": results}
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/rulesim_oos/daily_trend_report.json").upload_from_string(
            json.dumps(rep, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
