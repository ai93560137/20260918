"""核實使用者 11-03 ES 筆記嘅季節性統計：「2010–2025，ES 12 月合約（ESZ）做主力期間（約 9/12–12/11）
16 年升 13 年（81%），平均 +3.5%；10 月中低位到 12 月中高位只有 2018 冇出現」。

主力期間：9 月換月日（9 月第 3 個星期五前 8 日嘅星期四）收市 → 12 月換月日（12 月第 3 個星期五前 8 日嘅星期四）收市。
數據（yfinance 日線）：^GSPC（現貨，冇換約跳空）為主；ES=F（連續期貨，未調整）同 SPY（含息）做對照。
「10 月中低位 → 12 月中高位」：10/1–11/15 最低收市，之後到 12 月換月日最高收市嘅升幅；< +3% 當「冇出現呢段反彈」。

用法：python3 research/longfei_analyst/seasonality/esz_seasonality.py [--no-upload]
"""
import argparse
import json
from datetime import date, timedelta


def third_friday(y, m):
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def roll_day(y, m):
    return third_friday(y, m) - timedelta(days=8)       # 星期四


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf
    out = {"years": {}, "summary": {}}
    for tk in ("^GSPC", "ES=F", "SPY"):
        df = yf.download(tk, start="2009-12-01", end="2026-01-15", interval="1d", progress=False,
                         auto_adjust=(tk == "SPY"))
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        s = {d.date(): float(v) for d, v in close.dropna().items()}
        ks = sorted(s)

        def on_or_before(d):
            c = [k for k in ks if k <= d]
            return c[-1] if c else None

        rets, rebounds = [], []
        for y in range(2010, 2026):
            d0, d1 = on_or_before(roll_day(y, 9)), on_or_before(roll_day(y, 12))
            if not d0 or not d1:
                continue
            r = s[d1] / s[d0] - 1
            win = [k for k in ks if date(y, 10, 1) <= k <= date(y, 11, 15)]
            lo = min(win, key=lambda k: s[k])
            after = [k for k in ks if lo < k <= d1]
            hi = max(after, key=lambda k: s[k]) if after else lo
            rb = s[hi] / s[lo] - 1
            rets.append(r)
            rebounds.append(rb)
            out["years"].setdefault(str(y), {})[tk] = {"from": str(d0), "to": str(d1), "ret_pct": round(r * 100, 2),
                                                       "oct_low": str(lo), "rebound_to": str(hi), "rebound_pct": round(rb * 100, 2)}
        out["summary"][tk] = {"n": len(rets), "up": sum(r > 0 for r in rets), "avg_ret_pct": round(sum(rets) / len(rets) * 100, 2),
                              "median_ret_pct": round(sorted(rets)[len(rets) // 2] * 100, 2),
                              "no_rebound_years_lt3pct": [str(2010 + i) for i, x in enumerate(rebounds) if x < 0.03]}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("ops/longfei/analyst/research/esz_seasonality.json").upload_from_string(
            text, content_type="application/json")


if __name__ == "__main__":
    main()
