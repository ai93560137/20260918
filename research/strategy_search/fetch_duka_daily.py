"""[IDEAS #1427 起] 下載 Dukascopy 公開日線（BID，UTC 日；每年一個檔 /datafeed/<SYM>/<YYYY>/BID_candles_day_1.bi5）入研究快取。
使用者 11-12（經總指揮）「授權天覆陣下載數據」：長歷史、可買賣嘅日線 OHLC（外匯、白銀／鉑／鈀、債券、原油／天然氣）。公開免費、唔使帳號；請求唔帶任何個人資料。
輸出：GCS xau/sig/cache/dukad/<SYM>_d.npz（t＝UTC 日 00:00 秒、o／h／l／c、v）；已存在就跳過（--force 重下）。清單 research/strategy_search/DUKA_DAILY.md。
用法：python3 research/strategy_search/fetch_duka_daily.py [--force]"""
import datetime as dt
import lzma
import os
import struct
import sys
import time
import urllib.error
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import data_cache as DC  # noqa: E402

SYMS = {  # 代號：(類別, 價格除數)
    "EURUSD": ("外匯", 1e5), "GBPUSD": ("外匯", 1e5), "USDJPY": ("外匯", 1e3), "USDCHF": ("外匯", 1e5), "USDCAD": ("外匯", 1e5),
    "AUDUSD": ("外匯", 1e5), "NZDUSD": ("外匯", 1e5), "EURJPY": ("外匯", 1e3), "GBPJPY": ("外匯", 1e3),
    "XAUUSD": ("貴金屬", 1e3), "XAGUSD": ("貴金屬", 1e3), "XPTUSD": ("貴金屬", 1e3), "XPDUSD": ("貴金屬", 1e3),
    "LIGHTCMDUSD": ("能源", 1e3), "BRENTCMDUSD": ("能源", 1e3), "GASCMDUSD": ("能源", 1e4),
    "USTBONDTRUSD": ("利率", 1e3), "BUNDTREUR": ("利率", 1e3), "UKGILTTRGBP": ("利率", 1e3)}
Y0, Y1 = 2003, 2026


TMP = os.environ.get("DUKA_TMP", "/tmp/dukad_parts")


def year_file(sym, y):
    """每年一個檔；伺服器成日 503／斷線（限流），所以耐心重試，而且每年結果存本機暫存，重跑可以接住做。回傳 bytes；b""＝嗰年冇數據（404）；None＝今次攞唔到。"""
    os.makedirs(TMP, exist_ok=True); local = os.path.join(TMP, f"{sym}_{y}.bin")
    if os.path.exists(local):
        return open(local, "rb").read()
    url = f"https://datafeed.dukascopy.com/datafeed/{sym}/{y:04d}/BID_candles_day_1.bi5"
    for k in range(14):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read()
            data = lzma.decompress(raw) if raw else b""
            open(local, "wb").write(data); return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                open(local, "wb").write(b""); return b""
        except Exception:
            pass
        time.sleep(min(60, 5 + 5 * k))
    return None


def fetch(sym):
    div = SYMS[sym][1]; rows = []; missing = []
    for y in range(Y0, Y1 + 1):
        data = year_file(sym, y); time.sleep(1.5)
        if data is None:
            missing.append(y); continue
        base = int(dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc).timestamp())
        for i in range(len(data) // 24):
            s, o, c, l, h, v = struct.unpack(">5if", data[i * 24:(i + 1) * 24])
            if v > 0 and h > l:
                rows.append((base + s, o / div, h / div, l / div, c / div, v))
    if missing:
        raise RuntimeError(f"{sym} 仲差 {missing}")
    a = np.array(rows, float)
    return {"t": a[:, 0].astype(np.int64), "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5]} if len(rows) else None


def main():
    force = "--force" in sys.argv; L = ["# Dukascopy 公開日線清單（研究快取 GCS `xau/sig/cache/dukad/<代號>_d.npz`）", "",
                                       f"- 下載 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d} UTC；來源 datafeed.dukascopy.com 每年日線檔（BID、UTC 日；零成交量同高低相同嘅日子已剔）；使用者 11-12 授權",
                                       "- 讀法：`data_cache.get('dukad/EURUSD_d.npz')`；週日短 K 線喺研究腳本入面併入星期一", "",
                                       "| 類別 | 代號 | 日數 | 由 | 到 | 首日收市 | 尾日收市 | 最長缺口（日曆日） |", "|---|---|---|---|---|---|---|---|"]
    for sym, (cat, _) in SYMS.items():
        name = f"dukad/{sym}_d.npz"
        d = None if force else DC.get(name)
        if d is None:
            try:
                d = fetch(sym)
            except RuntimeError as e:
                L.append(f"| {cat} | {sym} | 下載失敗（{e}） | | | | | |"); print(sym, "FAIL", flush=True); continue
            if d is None:
                L.append(f"| {cat} | {sym} | 冇數據 | | | | | |"); print(sym, "none", flush=True); continue
            DC.put(name, d)
        f = lambda x: dt.datetime.fromtimestamp(int(x), dt.timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
        gap = int(np.diff(d["t"]).max() // 86400) if len(d["t"]) > 1 else 0
        L.append(f"| {cat} | {sym} | {len(d['t']):,} | {f(d['t'][0])} | {f(d['t'][-1])} | {d['c'][0]:.5g} | {d['c'][-1]:.5g} | {gap} |")
        print(sym, len(d["t"]), f(d["t"][0]), f(d["t"][-1]), flush=True)
    open(os.path.join(HERE, "DUKA_DAILY.md"), "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
