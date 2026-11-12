"""[IDEAS #1437 起] 下載 Yahoo Finance 公開日線（chart v8，唔使帳號；請求唔帶任何個人資料）入研究快取。
使用者 11-12「授權天覆陣下載數據」＋「放行其他公開來源」（Dukascopy 限流太緊，改用 Yahoo）。
輸出：GCS xau/sig/cache/yahood/<名>_d.npz（t＝UTC 日 00:00 秒、o／h／l／c）；清單 research/strategy_search/YAHOO_DAILY.md。
注意：期貨係 Yahoo 連續合約（自動轉月、冇價差調整，原油／天然氣轉月跳空大）；ETF 係未除息價；外匯早年有壞 tick。
用法：python3 research/strategy_search/fetch_yahoo_daily.py [--force]"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import data_cache as DC  # noqa: E402

SYMS = [("外匯", "EURUSD", "EURUSD=X"), ("外匯", "GBPUSD", "GBPUSD=X"), ("外匯", "USDJPY", "JPY=X"), ("外匯", "USDCHF", "CHF=X"), ("外匯", "USDCAD", "CAD=X"),
        ("外匯", "AUDUSD", "AUDUSD=X"), ("外匯", "NZDUSD", "NZDUSD=X"), ("外匯", "EURJPY", "EURJPY=X"), ("外匯", "GBPJPY", "GBPJPY=X"),
        ("貴金屬", "SI_F", "SI=F"), ("貴金屬", "PL_F", "PL=F"), ("貴金屬", "PA_F", "PA=F"), ("貴金屬", "GC_F", "GC=F"),
        ("利率", "ZN_F", "ZN=F"), ("利率", "ZB_F", "ZB=F"), ("利率", "TLT", "TLT"), ("利率", "IEF", "IEF"),
        ("能源", "CL_F", "CL=F"), ("能源", "BZ_F", "BZ=F"), ("能源", "NG_F", "NG=F")]


def fetch(ticker):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?period1=0&period2=9999999999&interval=1d&events=history"
    for k in range(5):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read()); break
        except Exception:
            time.sleep(3 + 3 * k)
    else:
        return None
    r = j["chart"]["result"][0]; q = r["indicators"]["quote"][0]; rows = {}
    for t, o, h, l, c in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c) or min(o, h, l, c) <= 0:
            continue
        day = (int(t) + int(r["meta"].get("gmtoffset", 0))) // 86400            # 交易所當地日期
        rows[day] = (day * 86400, o, max(o, h, l, c), min(o, h, l, c), c)
    a = np.array([rows[k] for k in sorted(rows)], float)
    return {"t": a[:, 0].astype(np.int64), "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4]}


def main():
    force = "--force" in sys.argv; f = lambda x: dt.datetime.fromtimestamp(int(x), dt.timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    L = ["# Yahoo Finance 公開日線清單（研究快取 GCS `xau/sig/cache/yahood/<名>_d.npz`）", "",
         f"- 下載 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d} UTC；來源 query1.finance.yahoo.com chart v8；使用者 11-12 授權＋放行",
         "- 讀法：`data_cache.get('yahood/EURUSD_d.npz')`。期貨＝連續合約冇價差調整；ETF＝未除息價；「高低相同」嘅日子（壞 tick／冇成交）研究時剔走",
         "", "| 類別 | 名 | Yahoo 代號 | 日數 | 由 | 到 | 高低相同日數 | 單日收市變動 > 15% 次數 | 最長缺口（日曆日） |", "|---|---|---|---|---|---|---|---|---|"]
    for cat, name, tk in SYMS:
        key = f"yahood/{name}_d.npz"; d = None if force else DC.get(key)
        if d is None:
            d = fetch(tk); time.sleep(1.0)
            if d is None:
                L.append(f"| {cat} | {name} | {tk} | 下載失敗 | | | | | |"); print(name, "FAIL", flush=True); continue
            DC.put(key, d)
        flat = int((d["h"] == d["l"]).sum()); jump = int((np.abs(np.diff(d["c"]) / d["c"][:-1]) > 0.15).sum()); gap = int(np.diff(d["t"]).max() // 86400)
        L.append(f"| {cat} | {name} | {tk} | {len(d['t']):,} | {f(d['t'][0])} | {f(d['t'][-1])} | {flat} | {jump} | {gap} |"); print(name, len(d["t"]), flat, jump, flush=True)
    open(os.path.join(HERE, "YAHOO_DAILY.md"), "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
