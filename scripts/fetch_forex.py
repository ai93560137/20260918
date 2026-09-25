#!/usr/bin/env python3
"""外匯歷史數據 → data_forex/<PAIR>/（不進 git，存 GitHub Release「forex-data」）。

    python3 scripts/fetch_forex.py --group majors --budget-min 300     # 七大主要貨幣對
    python3 scripts/fetch_forex.py --pair EURUSD USDJPY                  # 指定幾個
    python3 scripts/fetch_forex.py --list                                # 列出全部商品與分組

兩個來源分工（Dukascopy 對 GitHub Actions 的 IP 限流很兇，M1 每日一檔的抓法行不通）：
- **HistData**（histdata.com，免費 M1，每年／每月一個 zip，一個商品約 35 個請求）→ M1 主來源：
  <PAIR>_M1_<YYYY>.csv.gz（欄位 Time,Open,High,Low,Close；**沒有成交量**；原檔是**紐約當地時間（含夏令）**——網站寫「EST 無夏令」
  但實測每週開盤全年都在當地 17:00、對 Dukascopy 的差只有按 America/New_York 轉才最小——已轉 UTC；相對 7 根中位數偏離 > 5% 的壞 tick 已丟）
  當年只有已完成的月份（HistData 月初幾天後才放上月）；USDCNH HistData 沒有
- **Dukascopy**（瑞士銀行，2003 起，UTC）→ 往年 D1 每年一檔、每個已完成月份的 H1 每月一檔（買價 bid 與賣價 ask，算點差用），
  以及**近 62 天／HistData 之後**的 M1（bid + ask，每日一檔）：<PAIR>_M1_recent.csv.gz、<PAIR>_M1_recent_ask.csv.gz
  當月 H1 由近期 M1 聚合、當年 D1 由 H1 聚合（Dukascopy D1 的日界實測就是 UTC）
- 第二來源：Yahoo 日線（<PAIR>=X）→ _ref_yahoo.csv.gz；FRED H.10 紐約中午匯率 → _ref_fred.csv.gz
- 所有檔案欄位 Time,Open,High,Low,Close[,Volume]；**時間一律 UTC**（回測 --broker-offset 0）；與 data/ 的 MT5 匯出同一命名，
  backtest.py 載入器直接讀
- **Dukascopy 的檔案把週末、假期、上市前的時段用「平價、零量」K 線填滿**——一律丟掉 Volume = 0 且 High = Low 的 K 線
  （實測真數據沒有這種組合；HistData 檔沒有成交量欄，不受影響）
- 可中斷續抓：已完成的年／月記在 _done.json；只保留今天（UTC）以前的完整日
- Dukascopy 限流（503、連線重設）：全域限速（預設每秒 1.5 個請求）、指數退避；仍失敗就先存檔、回傳碼 3 等下輪續抓

bi5 = LZMA；每筆 24 bytes 大端 int×5 + float：時間偏移秒、開、收、低、高、量；價格整數要除以 10^小數位。
沙盒連不到這些網站，這個程式在 GitHub Actions（fetch_forex.yml）跑；本機用 scripts/get_forex_data.py 拿 Release。
"""
import argparse
import gzip
import io
import json
import lzma
import re
import struct
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "data_forex"
BASE = "https://datafeed.dukascopy.com/datafeed"
HD_BASE = "https://www.histdata.com"
HD_TZ = "America/New_York"                # HistData 原檔時區（實測含夏令）；改動這裡會讓舊檔全部重抓
NY = ZoneInfo(HD_TZ)
SPIKE_PCT = 5.0                           # M1 開高低收相對前後 7 根收市中位數偏離超過此 % → 壞 tick，丟掉
FIRST_YEAR = 2000
RECENT_DAYS = 62                          # Dukascopy 近期 M1 最多回抓幾天（HistData 上月檔通常月初幾天後才有）
HEADER = "Time,Open,High,Low,Close,Volume\n"
UA = "Mozilla/5.0 (research data fetch; github.com/ai93560137/20260918)"

# 商品：Dukascopy 路徑、小數位（JPY 交叉盤與貴金屬 3 位，其餘 5 位）、分組、Yahoo 代號、FRED H.10 系列（[] = 沒有）
# FRED 方向已核對：DEXUSEU = 每歐元美元（= EURUSD）、DEXJPUS = 每美元日圓（= USDJPY）…；交叉盤由主要貨幣對相乘／相除推算
INSTRUMENTS = {
    # 七大主要貨幣對
    "EURUSD": ("EURUSD", 5, "majors", "EURUSD=X", [("DEXUSEU", 1)]),
    "USDJPY": ("USDJPY", 3, "majors", "JPY=X", [("DEXJPUS", 1)]),
    "GBPUSD": ("GBPUSD", 5, "majors", "GBPUSD=X", [("DEXUSUK", 1)]),
    "USDCHF": ("USDCHF", 5, "majors", "CHF=X", [("DEXSZUS", 1)]),
    "AUDUSD": ("AUDUSD", 5, "majors", "AUDUSD=X", [("DEXUSAL", 1)]),
    "USDCAD": ("USDCAD", 5, "majors", "CAD=X", [("DEXCAUS", 1)]),
    "NZDUSD": ("NZDUSD", 5, "majors", "NZDUSD=X", [("DEXUSNZ", 1)]),
    # 日圓交叉盤
    "EURJPY": ("EURJPY", 3, "jpy", "EURJPY=X", [("DEXUSEU", 1), ("DEXJPUS", 1)]),
    "GBPJPY": ("GBPJPY", 3, "jpy", "GBPJPY=X", [("DEXUSUK", 1), ("DEXJPUS", 1)]),
    "AUDJPY": ("AUDJPY", 3, "jpy", "AUDJPY=X", [("DEXUSAL", 1), ("DEXJPUS", 1)]),
    "NZDJPY": ("NZDJPY", 3, "jpy", "NZDJPY=X", [("DEXUSNZ", 1), ("DEXJPUS", 1)]),
    "CADJPY": ("CADJPY", 3, "jpy", "CADJPY=X", [("DEXJPUS", 1), ("DEXCAUS", -1)]),
    "CHFJPY": ("CHFJPY", 3, "jpy", "CHFJPY=X", [("DEXJPUS", 1), ("DEXSZUS", -1)]),
    # 歐元／英鎊交叉盤
    "EURGBP": ("EURGBP", 5, "eur", "EURGBP=X", [("DEXUSEU", 1), ("DEXUSUK", -1)]),
    "EURCHF": ("EURCHF", 5, "eur", "EURCHF=X", [("DEXUSEU", 1), ("DEXSZUS", 1)]),
    "EURAUD": ("EURAUD", 5, "eur", "EURAUD=X", [("DEXUSEU", 1), ("DEXUSAL", -1)]),
    "EURCAD": ("EURCAD", 5, "eur", "EURCAD=X", [("DEXUSEU", 1), ("DEXCAUS", 1)]),
    "GBPCHF": ("GBPCHF", 5, "eur", "GBPCHF=X", [("DEXUSUK", 1), ("DEXSZUS", 1)]),
    "GBPAUD": ("GBPAUD", 5, "eur", "GBPAUD=X", [("DEXUSUK", 1), ("DEXUSAL", -1)]),
    # 其他：澳紐加交叉、亞洲（港元、離岸人民幣、新加坡元）
    "AUDNZD": ("AUDNZD", 5, "other", "AUDNZD=X", [("DEXUSAL", 1), ("DEXUSNZ", -1)]),
    "AUDCAD": ("AUDCAD", 5, "other", "AUDCAD=X", [("DEXUSAL", 1), ("DEXCAUS", 1)]),
    "USDHKD": ("USDHKD", 5, "other", "HKD=X", [("DEXHKUS", 1)]),
    "USDCNH": ("USDCNH", 5, "other", "CNH=X", [("DEXCHUS", 1)]),          # FRED 只有在岸 CNY，差距屬正常
    "USDSGD": ("USDSGD", 5, "other", "SGD=X", [("DEXSIUS", 1)]),
    # 貴金屬現貨（XAUUSD 另有券商 MT5 M1 在 data/，2022-08 起）
    "XAUUSD": ("XAUUSD", 3, "metals", "XAUUSD=X", []),
    "XAGUSD": ("XAGUSD", 3, "metals", "XAGUSD=X", []),
    # 新興市場／其他 G10（外匯基金新宇宙，分 em1／em2 兩組並行；只要 Dukascopy D1／H1，不抓 HistData M1；小數位 None = 首次抓時按價位自動判定）
    "USDMXN": ("USDMXN", None, "em1", "MXN=X", [("DEXMXUS", 1)]),
    "USDZAR": ("USDZAR", None, "em1", "ZAR=X", [("DEXSFUS", 1)]),
    "USDTRY": ("USDTRY", None, "em1", "TRY=X", []),
    "USDPLN": ("USDPLN", None, "em1", "PLN=X", []),
    "USDHUF": ("USDHUF", None, "em1", "HUF=X", []),
    "USDCZK": ("USDCZK", None, "em1", "CZK=X", []),
    "USDSEK": ("USDSEK", None, "em1", "SEK=X", [("DEXSDUS", 1)]),
    "USDNOK": ("USDNOK", None, "em1", "NOK=X", [("DEXNOUS", 1)]),
    "USDDKK": ("USDDKK", None, "em2", "DKK=X", [("DEXDNUS", 1)]),
    "USDRON": ("USDRON", None, "em2", "RON=X", []),
    "USDILS": ("USDILS", None, "em2", "ILS=X", []),
    "USDTHB": ("USDTHB", None, "em2", "THB=X", [("DEXTHUS", 1)]),
    "USDBRL": ("USDBRL", None, "em2", "BRL=X", [("DEXBZUS", 1)]),
    "USDINR": ("USDINR", None, "em2", "INR=X", [("DEXINUS", 1)]),
    "USDKRW": ("USDKRW", None, "em2", "KRW=X", [("DEXKOUS", 1)]),
}
# 自動判定小數位用的大約價位（2025 年水平；bi5 的整數價 ÷ 10^小數位 應落在這附近，差 10 倍就是小數位錯）
REF_LEVEL = {"USDMXN": 19, "USDZAR": 18, "USDTRY": 38, "USDPLN": 3.9, "USDHUF": 360, "USDCZK": 22, "USDSEK": 10, "USDNOK": 10.5,
             "USDDKK": 6.9, "USDRON": 4.5, "USDILS": 3.6, "USDTHB": 33, "USDBRL": 5.5, "USDINR": 85, "USDKRW": 1400}
NO_HISTDATA = {"USDCNH"} | {p for p, v in INSTRUMENTS.items() if v[2] in ("em1", "em2")}   # HistData 沒有／不抓的商品：M1 只有 Dukascopy 近 62 天
GROUPS = list(dict.fromkeys(v[2] for v in INSTRUMENTS.values()))
REC = struct.Struct(">iiiiif")           # 時間偏移秒、開、收、低、高、量


def log(msg: str) -> None:
    print(msg, flush=True)


class Throttled(Exception):
    """限流：退避後仍拿不到，先停止這輪（已抓的會存檔）。"""


# ---------------------------------------------------------------- Dukascopy
class Feed:
    def __init__(self, workers: int = 3, rate: float = 1.5):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.workers = workers
        self.interval = 1.0 / rate
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.n_req = 0
        self.n_404 = 0
        self.n_retry = 0

    def _pace(self) -> None:
        with self.lock:
            now = time.monotonic()
            wait = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str) -> bytes | None:
        """回傳 bi5 原始位元組；404／空檔 → None；限流退避 6 次仍失敗 → Throttled。"""
        url = f"{BASE}/{path}"
        for attempt in range(7):
            self._pace()
            try:
                r = self.s.get(url, timeout=60)
            except requests.RequestException as exc:
                r = None
                err = repr(exc)
            with self.lock:
                self.n_req += 1
            if r is not None:
                if r.status_code == 404:
                    with self.lock:
                        self.n_404 += 1
                    return None
                if r.status_code == 200:
                    return r.content or None
                if r.status_code not in (429, 500, 502, 503, 504):
                    r.raise_for_status()
                err = f"HTTP {r.status_code}"
            if attempt == 6:
                raise Throttled(f"{url}: {err}")
            back = 5 * 2 ** attempt                        # 5、10、20、40、80、160 秒
            with self.lock:
                self.n_retry += 1
                self.next_at = max(self.next_at, time.monotonic() + back)   # 全部執行緒一起等
            log(f"    限流／錯誤（{err}），{back} 秒後重試 {path}")
            time.sleep(back)
        return None

    def candles(self, path: str, base: datetime, scale: float) -> list[tuple]:
        raw = self.get(path)
        if not raw:
            return []
        return decode(raw, base, scale)


def decode(raw: bytes, base: datetime, scale: float) -> list[tuple]:
    """bi5 → [(Time 'YYYY-MM-DD HH:MM:SS', open, high, low, close, volume)]，已丟掉填充 K 線（零量且平價）。"""
    data = lzma.decompress(raw)
    if len(data) % REC.size:
        raise ValueError(f"bi5 長度 {len(data)} 不是 {REC.size} 的倍數")
    out = []
    for t, o, c, lo, hi, v in REC.iter_unpack(data):
        if v == 0 and hi == lo:
            continue
        ts = base + timedelta(seconds=t)
        out.append((ts.strftime("%Y-%m-%d %H:%M:%S"), o / scale, hi / scale, lo / scale, c / scale, v))
    return out


# ---------------------------------------------------------------- HistData
class HistData:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.n_req = 0

    def download(self, pair: str, year: int, month: int | None = None) -> list[tuple] | None:
        """HistData 的 M1 zip → [(Time UTC, open, high, low, close)]；沒有這個年／月 → None。"""
        slug = (f"/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair.lower()}/{year}"
                + (f"/{month}" if month else ""))
        for attempt in range(4):
            try:
                page = self.s.get(HD_BASE + slug, timeout=60)
                self.n_req += 1
                if page.status_code == 404:
                    return None
                page.raise_for_status()
                fields = {}
                for k in ("tk", "date", "datemonth", "platform", "timeframe", "fxpair"):
                    m = re.search(rf'<input[^>]*name="{k}"[^>]*value="([^"]*)"', page.text)
                    if m:
                        fields[k] = m.group(1)
                if "tk" not in fields:
                    return None
                r = self.s.post(HD_BASE + "/get.php", data=fields, timeout=300,
                                headers={"Referer": HD_BASE + slug, "Origin": HD_BASE})
                self.n_req += 1
                r.raise_for_status()
                if not r.content.startswith(b"PK"):
                    return None
                return parse_histdata_zip(r.content)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise
                log(f"    HistData 錯誤（{exc!r}），{10 * (attempt + 1)} 秒後重試 {slug}")
                time.sleep(10 * (attempt + 1))
        return None


def parse_histdata_zip(data: bytes) -> list[tuple]:
    """DAT_ASCII_<PAIR>_M1_<期間>.csv：'YYYYMMDD HHMMSS;開;高;低;收;量'，紐約當地時間（含夏令）→ UTC。"""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            for line in zf.read(name).decode("utf-8", "replace").splitlines():
                f = line.strip().split(";")
                if len(f) < 5:
                    continue
                try:
                    ts = datetime.strptime(f[0], "%Y%m%d %H%M%S").replace(tzinfo=NY).astimezone(timezone.utc)
                    out.append((ts.strftime("%Y-%m-%d %H:%M:%S"), float(f[1]), float(f[2]), float(f[3]), float(f[4])))
                except ValueError:
                    continue
    return out


def despike(rows: list[tuple], pct: float = SPIKE_PCT) -> tuple[list[tuple], list[tuple]]:
    """丟掉開高低收任一相對前後 7 根收市中位數偏離 > pct% 的 K 線（HistData 2004 有 +100%／−50% 的壞 tick）；回傳（保留, 丟掉）。"""
    if len(rows) < 7:
        return rows, []
    import numpy as np
    import pandas as pd
    rows = sorted(rows)
    c = pd.Series([r[4] for r in rows], dtype=float)
    med = c.rolling(7, center=True, min_periods=3).median().to_numpy()
    arr = np.array([r[1:5] for r in rows], dtype=float)
    dev = np.nanmax(np.abs(arr / med[:, None] - 1), axis=1) * 100
    bad = dev > pct
    return [r for r, b in zip(rows, bad) if not b], [r for r, b in zip(rows, bad) if b]


# ---------------------------------------------------------------- 檔案
def fmt(rows: list[tuple], decimals: int) -> str:
    p = decimals
    out = []
    for r in rows:
        t, o, h, l, c = r[:5]
        out.append(f"{t},{o:.{p}f},{h:.{p}f},{l:.{p}f},{c:.{p}f}" + (f",{r[5]:g}\n" if len(r) > 5 else "\n"))
    return "".join(out)


def is_padding(line: str) -> bool:
    f = line.rstrip("\n").split(",")
    return len(f) >= 6 and f[2] == f[3] and float(f[5]) == 0


def read_gz(path: Path) -> dict[str, str]:
    """已有檔 → {Time: 整行}（dict 去重、合併後排序；順便丟掉填充 K 線）。"""
    if not path.exists():
        return {}
    rows = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Time") or not line.strip() or is_padding(line):
                continue
            rows[line.split(",", 1)[0]] = line
    return rows


def write_gz(path: Path, rows: dict[str, str]) -> None:
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        f.write(HEADER)
        for k in sorted(rows):
            f.write(rows[k])
    tmp.replace(path)


def merge_write(path: Path, new_rows: list[tuple], decimals: int, cutoff: str, drop_from: str = "") -> int:
    """合併寫入；drop_from 給了就先丟掉 >= drop_from 的舊行（當月／當年重算用）。"""
    rows = read_gz(path)
    if drop_from:
        rows = {k: v for k, v in rows.items() if k < drop_from}
    for line in fmt(new_rows, decimals).splitlines(keepends=True):
        rows[line.split(",", 1)[0]] = line
    rows = {k: v for k, v in rows.items() if k < cutoff}
    write_gz(path, rows)
    return len(rows)


def aggregate(rows: dict[str, str], freq: str) -> list[tuple]:
    """M1／H1 行 → H1（'h'）或 D1（'D'）K 線（UTC 日界；Dukascopy 的 D1 實測就是 UTC）。"""
    import pandas as pd
    if not rows:
        return []
    df = pd.read_csv(io.StringIO(HEADER + "".join(rows[k] for k in sorted(rows))), parse_dates=["Time"]).set_index("Time")
    g = df.resample(freq).agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"),
                              Volume=("Volume", "sum")).dropna(subset=["Open"])
    return [(t.strftime("%Y-%m-%d %H:%M:%S"), *map(float, r)) for t, r in zip(g.index, g.to_numpy())]


def clean_existing(out: Path, pair: str) -> None:
    """舊檔清一次填充 K 線；舊版（Dukascopy 來源、6 欄）的 M1 年檔刪掉，改由 HistData 重抓。"""
    for p in sorted(out.glob("*.csv.gz")):
        if p.name.startswith("_ref"):
            continue
        if re.fullmatch(rf"{pair}_M1_\d{{4}}(_ask)?\.csv\.gz", p.name):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                next(f, None)
                first = f.readline()
            if p.name.endswith("_ask.csv.gz") or first.count(",") >= 5:
                p.unlink()
                log(f"  刪除舊版 Dukascopy M1 年檔 {p.name}（改由 HistData 重抓）")
                continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            n_raw = sum(1 for line in f if not line.startswith("Time"))
        rows = read_gz(p)
        if len(rows) != n_raw:
            if rows:
                write_gz(p, rows)
            else:
                p.unlink()                                    # 整檔都是填充（上市前的年份）
            log(f"  清理 {p.name}：{n_raw} → {len(rows)} 根（丟掉填充 K 線）")


# ---------------------------------------------------------------- 各時間框架
def resolve_decimals(pair: str, feed: Feed, done: dict) -> int | None:
    """小數位：表裡寫死的 → 用；None → 用 _done.json 記住的；都沒有 → 抓去年 D1 原始整數價，
    小數位 = round(log10(中位整數價 ÷ 大約價位))，記進 _done.json。"""
    import math
    import statistics
    dec = INSTRUMENTS[pair][1]
    if dec is not None:
        return dec
    if done.get("decimals") is not None:
        return done["decimals"]
    sym = INSTRUMENTS[pair][0]
    y = datetime.now(timezone.utc).year - 1
    rows, tried = [], []
    for path, base in ((f"{sym}/{y}/BID_candles_day_1.bi5", datetime(y, 1, 1)), (f"{sym}/{y - 1}/BID_candles_day_1.bi5", datetime(y - 1, 1, 1)),
                       (f"{sym}/{y}/11/BID_candles_hour_1.bi5", datetime(y, 12, 1))):
        raw = feed.get(path)                      # None = 404（真的沒有）；限流會直接拋 Throttled，由外層當作未完成、下輪續抓
        tried.append(f"{path}:{'404' if raw is None else str(len(raw)) + 'B'}")
        if raw:
            rows = decode(raw, base, 1.0)
            if rows:
                break
    log(f"  {pair}：小數位探測 {'、'.join(tried)}")
    if not rows:
        return None
    med = statistics.median(r[4] for r in rows)
    dec = int(round(math.log10(med / REF_LEVEL[pair])))
    log(f"  {pair}：{y} 年 D1 原始整數收市中位 {med:.0f}、大約價位 {REF_LEVEL[pair]} → 小數位 {dec}")
    done["decimals"] = dec
    return dec


def fetch_pair(pair: str, feed: Feed, hd: HistData, budget_end: float, do_refs: bool) -> bool:
    sym, _dec, group, ysym, fred = INSTRUMENTS[pair]
    out = OUT_ROOT / pair
    out.mkdir(parents=True, exist_ok=True)
    clean_existing(out, pair)
    done_p = out / "_done.json"
    done = json.loads(done_p.read_text()) if done_p.exists() else {}
    decimals = resolve_decimals(pair, feed, done)
    if decimals is None:
        log(f"  {pair}：Dukascopy 沒有這個商品的日線／小時線（404），跳過")
        (out / "_status.txt").write_text(f"{datetime.now(timezone.utc).date()} 沒有數據：Dukascopy 404（去年／前年 D1、去年 12 月 H1 都沒有）\n")
        return True
    done_p.write_text(json.dumps(done, ensure_ascii=False))
    scale = 10 ** decimals
    for k in ("d1_years", "d1_years_ask", "h1_months", "h1_months_ask", "hd_years", "hd_months"):
        done.setdefault(k, [])
    if done.get("hd_tz") != HD_TZ:                    # 時區規則改了 → HistData 檔全部重抓（很快，每商品約 35 個 zip）
        for p in out.glob(f"{pair}_M1_*.csv.gz"):
            if re.fullmatch(rf"{pair}_M1_\d{{4}}\.csv\.gz", p.name):
                p.unlink()
        done["hd_years"], done["hd_months"], done["hd_tz"] = [], [], HD_TZ
        log(f"  {pair}：HistData 時區規則 {HD_TZ}，舊年檔已刪除重抓")
    today = datetime.now(timezone.utc).date()
    cutoff = today.strftime("%Y-%m-%d")               # 只保留 < 今天 00:00 UTC 的 K 線
    this_year = today.year
    year_start = f"{this_year}-01-01"
    month_start = today.replace(day=1).isoformat()
    complete = True

    def save_done() -> None:
        done_p.write_text(json.dumps(done, ensure_ascii=False))

    def over_budget() -> bool:
        return time.monotonic() > budget_end

    if do_refs:
        try:
            fetch_refs(pair, out, decimals)
        except Exception as exc:                      # 第二來源失敗不影響主數據
            log(f"  {pair} 第二來源失敗：{exc!r}")

    # ---- Dukascopy D1：往年每年一檔（bid + ask），只抓一次
    for side, key, name in (("BID", "d1_years", f"{pair}_D1.csv.gz"), ("ASK", "d1_years_ask", f"{pair}_D1_ask.csv.gz")):
        rows = []
        for y in range(FIRST_YEAR, this_year):
            if y in done[key]:
                continue
            rows += feed.candles(f"{sym}/{y}/{side}_candles_day_1.bi5", datetime(y, 1, 1), scale)
            done[key].append(y)
        if rows:
            n = merge_write(out / name, rows, decimals, cutoff)
            log(f"  {pair} D1 {side.lower()}：新增 {len(rows)} 根，共 {n}")
    save_done()
    d1 = read_gz(out / f"{pair}_D1.csv.gz")
    if not d1:
        log(f"  {pair}：Dukascopy 沒有日線，跳過")
        (out / "_status.txt").write_text(f"{today} 沒有數據\n")
        return True
    first = date.fromisoformat(min(d1)[:10])
    log(f"  {pair}：Dukascopy 日線 {first} → {max(d1)[:10]}（{len(d1)} 根，已去填充）")

    # ---- Dukascopy H1：每個已完成月份一檔（bid + ask，含當年）
    for side, key, name in (("BID", "h1_months", f"{pair}_H1.csv.gz"), ("ASK", "h1_months_ask", f"{pair}_H1_ask.csv.gz")):
        months = [(y, m) for y in range(first.year, this_year + 1) for m in range(1, 13)
                  if (first.year, first.month) <= (y, m) < (today.year, today.month) and f"{y:04d}-{m:02d}" not in done[key]]
        if not months:
            continue

        def one(ym):
            yy, mm = ym
            return ym, feed.candles(f"{sym}/{yy}/{mm - 1:02d}/{side}_candles_hour_1.bi5", datetime(yy, mm, 1), scale)
        rows = []
        try:
            with ThreadPoolExecutor(feed.workers) as ex:
                for (yy, mm), got in ex.map(one, months):
                    rows += got
                    done[key].append(f"{yy:04d}-{mm:02d}")
        except Throttled as exc:
            log(f"  {pair} H1 {side.lower()}：限流退避後仍失敗（{exc}），先存檔，下輪續抓")
            complete = False
        n = merge_write(out / name, rows, decimals, cutoff)
        log(f"  {pair} H1 {side.lower()}：抓 {len(done[key])}/{len(done[key]) + len(months) - len(rows and done[key])} 個月、新增 {len(rows)} 根，共 {n}")
        save_done()
        if not complete:
            break

    # ---- HistData M1：往年每年一檔、當年每個已完成月份一檔
    last_hd = None
    if pair not in NO_HISTDATA and complete:
        for y in range(first.year, this_year + 1):
            if y < this_year and y in done["hd_years"]:
                continue
            if over_budget():
                complete = False
                break
            p = out / f"{pair}_M1_{y}.csv.gz"
            dropped_p = out / "_dropped_m1.txt"

            def keep(rows: list[tuple], tag: str) -> list[tuple]:
                rows, bad = despike(rows)
                if bad:
                    with dropped_p.open("a", encoding="utf-8") as f:
                        f.write("".join(f"{tag},{r[0]},{r[1]},{r[2]},{r[3]},{r[4]}\n" for r in bad))
                    log(f"  {pair} HistData {tag}：丟掉 {len(bad)} 根壞 tick（相對 7 根中位數偏離 > {SPIKE_PCT:g}%），例：{bad[0]}")
                return rows
            try:
                if y < this_year:
                    rows = hd.download(pair, y)
                    if rows is None:
                        log(f"  {pair} HistData {y}：沒有（起點之前）")
                    else:
                        rows = keep(rows, str(y))
                        n = merge_write(p, rows, decimals, cutoff)
                        log(f"  {pair} HistData {y}：{len(rows)} 根，共 {n}")
                    done["hd_years"].append(y)
                else:
                    for m in range(1, today.month):
                        tag = f"{y:04d}-{m:02d}"
                        if tag in done["hd_months"]:
                            continue
                        rows = hd.download(pair, y, m)
                        if rows is None:
                            log(f"  {pair} HistData {tag}：還沒有")
                            break
                        rows = keep(rows, tag)
                        n = merge_write(p, rows, decimals, cutoff)
                        done["hd_months"].append(tag)
                        log(f"  {pair} HistData {tag}：{len(rows)} 根，本年共 {n}")
            except requests.RequestException as exc:
                log(f"  {pair} HistData {y} 失敗：{exc!r}；下輪續抓")
                complete = False
                break
            save_done()
        hd_files = sorted(p for p in out.glob(f"{pair}_M1_*.csv.gz") if re.fullmatch(rf"{pair}_M1_\d{{4}}\.csv\.gz", p.name))
        if hd_files:
            last_hd = date.fromisoformat(max(read_gz(hd_files[-1]))[:10])

    # ---- Dukascopy 近期 M1（bid + ask）：HistData 之後到昨天，最多回抓 RECENT_DAYS 天（週六跳過）
    recent_from = today - timedelta(days=RECENT_DAYS)
    if last_hd:
        recent_from = max(recent_from, last_hd + timedelta(days=1))
    for side, name in (("BID", f"{pair}_M1_recent.csv.gz"), ("ASK", f"{pair}_M1_recent_ask.csv.gz")):
        if over_budget() or not complete:
            complete = False
            break
        p = out / name
        have = {k: v for k, v in read_gz(p).items() if k >= recent_from.isoformat()}
        start = recent_from
        if have:
            start = max(start, date.fromisoformat(max(have)[:10]))      # 最後一天重抓（可能不完整）
        days = [start + timedelta(i) for i in range((today - timedelta(days=1) - start).days + 1)]
        days = [d for d in days if d.weekday() != 5]

        def one_day(d: date):
            return d, feed.candles(f"{sym}/{d.year}/{d.month - 1:02d}/{d.day:02d}/{side}_candles_min_1.bi5",
                                   datetime(d.year, d.month, d.day), scale)
        rows = []
        try:
            with ThreadPoolExecutor(feed.workers) as ex:
                for d, got in ex.map(one_day, days):
                    rows += got
        except Throttled as exc:
            log(f"  {pair} 近期 M1 {side.lower()}：限流退避後仍失敗（{exc}），先存檔，下輪續抓")
            complete = False
        for line in fmt(rows, decimals).splitlines(keepends=True):
            have[line.split(",", 1)[0]] = line
        have = {k: v for k, v in have.items() if k < cutoff}
        if have:
            write_gz(p, have)
        log(f"  {pair} 近期 M1 {side.lower()}：{recent_from} 起，{len(days)} 天、新增 {len(rows)} 根，共 {len(have)}"
            f"（Dukascopy 請求 {feed.n_req}、404 {feed.n_404}、重試 {feed.n_retry}）")

    # ---- 當月 H1 由近期 M1 聚合；當年 D1 由 H1 聚合
    for m1_name, h1_name, d1_name in ((f"{pair}_M1_recent.csv.gz", f"{pair}_H1.csv.gz", f"{pair}_D1.csv.gz"),
                                      (f"{pair}_M1_recent_ask.csv.gz", f"{pair}_H1_ask.csv.gz", f"{pair}_D1_ask.csv.gz")):
        m1 = {k: v for k, v in read_gz(out / m1_name).items() if k >= month_start}
        if m1:
            merge_write(out / h1_name, aggregate(m1, "h"), decimals, cutoff, drop_from=month_start)
        h1 = {k: v for k, v in read_gz(out / h1_name).items() if k >= year_start}
        if h1:
            n = merge_write(out / d1_name, aggregate(h1, "D"), decimals, cutoff, drop_from=year_start)
            log(f"  {pair} {d1_name}：當年由 H1 聚合，共 {n} 根（當月 H1 由近期 M1 聚合 {len(m1)} 根）")

    hd_n = len([p for p in out.glob(f"{pair}_M1_*.csv.gz") if re.fullmatch(rf"{pair}_M1_\d{{4}}\.csv\.gz", p.name)])
    (out / "_status.txt").write_text(
        f"{today} Dukascopy D1 {len(read_gz(out / f'{pair}_D1.csv.gz'))} 根（{first} 起）、HistData M1 年檔 {hd_n}"
        f"（→ {last_hd or '無'}）、Dukascopy 近期 M1 {recent_from} 起、{'完成' if complete else '未完成（下輪續抓）'}\n")
    return complete


# ---------------------------------------------------------------- 第二來源
def fetch_refs(pair: str, out: Path, decimals: int | None = None) -> None:
    sym, dec0, group, ysym, fred = INSTRUMENTS[pair]
    decimals = dec0 if decimals is None else decimals
    import pandas as pd
    # Yahoo 日線（收市價可靠、高低價粗糙）
    try:
        import yfinance as yf
        df = yf.download(ysym, start="2000-01-01", auto_adjust=False, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])[["Open", "High", "Low", "Close"]]
        df.index = [d.strftime("%Y-%m-%d") for d in df.index]
        df.index.name = "Date"
        df.to_csv(out / "_ref_yahoo.csv.gz", float_format=f"%.{decimals}f", compression="gzip")
        log(f"  {pair} Yahoo {ysym}：{len(df)} 天（{df.index[0]} → {df.index[-1]}）")
    except Exception as exc:
        log(f"  {pair} Yahoo {ysym} 失敗：{exc!r}")
    # FRED H.10（紐約中午買入價；交叉盤由主要貨幣對推算）
    if not fred:
        return
    series = {}
    for sid, _ in fred:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60)
        r.raise_for_status()
        s = pd.read_csv(io.StringIO(r.text), na_values=["."])
        s.columns = ["Date", "v"]
        series[sid] = s.dropna().set_index("Date")["v"].astype(float)
    val = None
    for sid, power in fred:
        s = series[sid] ** power
        val = s if val is None else (val * s)
    val = val.dropna()
    val.name = "Close"
    val.index.name = "Date"
    val.to_csv(out / "_ref_fred.csv.gz", float_format=f"%.{decimals}f", compression="gzip")
    log(f"  {pair} FRED {'×'.join(s for s, _ in fred)}：{len(val)} 天（{val.index[0]} → {val.index[-1]}）")


# ---------------------------------------------------------------- 自檢
def selftest() -> None:
    """用合成 bi5／HistData zip 檢查解碼、填充過濾、格式、合併、聚合（不用外網）。"""
    import tempfile
    base = datetime(2024, 1, 2)
    recs = [(60 * i, 108000 + i, 108050 + i, 107950 + i, 108100 + i, 1.5) for i in range(3)]   # 時間、開、收、低、高、量
    recs.append((180, 108100, 108100, 108100, 108100, 0.0))                                      # 填充 K 線
    recs.append((240, 108100, 108100, 108100, 108100, 2.0))                                      # 真的平價但有量
    raw = lzma.compress(b"".join(REC.pack(*r) for r in recs), format=lzma.FORMAT_ALONE)
    rows = decode(raw, base, 1000)
    assert len(rows) == 4 and rows[0] == ("2024-01-02 00:00:00", 108.0, 108.1, 107.95, 108.05, 1.5), rows
    assert rows[2][0] == "2024-01-02 00:02:00" and rows[3][0] == "2024-01-02 00:04:00"
    txt = fmt(rows, 3)
    assert txt.splitlines()[0] == "2024-01-02 00:00:00,108.000,108.100,107.950,108.050,1.5", txt
    assert is_padding("2024-01-02 00:03:00,108.100,108.100,108.100,108.100,0\n") and not is_padding(txt.splitlines()[0])
    # HistData zip：紐約當地時間 → UTC（冬令 +5、夏令 +4 小時）、5 欄、平價零量不算填充
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("DAT_ASCII_EURUSD_M1_2024.csv", "20240101 170000;1.10390;1.10400;1.10380;1.10390;0\n"
                                                    "20240101 170100;1.10390;1.10390;1.10390;1.10390;0\n"
                                                    "20240701 170000;1.07000;1.07010;1.06990;1.07000;0\n")
    hd = parse_histdata_zip(buf.getvalue())
    assert hd[0] == ("2024-01-01 22:00:00", 1.1039, 1.104, 1.1038, 1.1039) and len(hd) == 3, hd
    assert hd[2][0] == "2024-07-01 21:00:00", hd[2]
    hd = hd[:2]
    # 去尖刺：一根 +100% 的壞 tick 要丟、其餘保留
    base_rows = [(f"2024-01-02 00:{i:02d}:00", 1.1, 1.1005, 1.0995, 1.1) for i in range(9)]
    spiky = base_rows[:4] + [("2024-01-02 00:04:00", 1.1, 2.2, 1.1, 2.2)] + base_rows[5:]
    ok, bad = despike(spiky)
    assert len(ok) == 8 and len(bad) == 1 and bad[0][0] == "2024-01-02 00:04:00", (len(ok), bad)
    hd_txt = fmt(hd, 5)
    assert hd_txt.splitlines()[1] == "2024-01-01 22:01:00,1.10390,1.10390,1.10390,1.10390" and not is_padding(hd_txt.splitlines()[1])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.csv.gz"
        n = merge_write(p, rows, 3, "2024-01-02 00:02:00")
        assert n == 2, n
        n = merge_write(p, rows, 3, "2099-01-01")
        assert n == 4 and list(read_gz(p))[0] == "2024-01-02 00:00:00"
        with gzip.open(p, "at", encoding="utf-8") as f:                       # 混入填充行，clean_existing 要清掉
            f.write("2024-01-02 00:03:00,108.100,108.100,108.100,108.100,0\n")
        q = Path(td) / "EURUSD_M1_2024.csv.gz"
        merge_write(q, hd, 5, "2099-01-01")
        old = Path(td) / "EURUSD_M1_2023.csv.gz"
        merge_write(old, rows, 3, "2099-01-01")                                # 舊版 6 欄年檔要被刪
        clean_existing(Path(td), "EURUSD")
        assert len(read_gz(p)) == 4 and len(read_gz(q)) == 2 and not old.exists()
        h = aggregate(read_gz(p), "h")
        assert len(h) == 1 and h[0][1] == 108.0 and h[0][2] == 108.102 and h[0][3] == 107.95 and h[0][4] == 108.1, h
        assert aggregate(read_gz(p), "D")[0][0] == "2024-01-02 00:00:00"
        assert aggregate(read_gz(q), "h")[0][:5] == ("2024-01-01 22:00:00", 1.1039, 1.104, 1.1038, 1.1039)
        # backtest.py 的載入器要能直接讀（時間格式 %Y-%m-%d %H:%M:%S，欄名 Time；5 欄 HistData 亦可）
        sys.path.insert(0, str(ROOT))
        from backtest import load_bars
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, dir=td) as f:
            f.write(HEADER + txt + hd_txt)
        bars = load_bars(f.name, 0)
        assert len(bars) == 6 and bars[0]["close"] == 1.1039 and bars[-1]["close"] == 108.1, bars
    print("selftest OK：bi5 解碼、填充過濾、HistData zip（紐約時間含夏令）、去尖刺、CSV 格式、合併去重、舊檔清理、聚合、backtest.load_bars 相容")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", nargs="*", choices=GROUPS + ["all"], default=[])
    ap.add_argument("--pair", nargs="*", choices=list(INSTRUMENTS), default=[])
    ap.add_argument("--budget-min", type=float, default=300)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--rate", type=float, default=1.5, help="Dukascopy 每秒最多幾個請求（會限流）")
    ap.add_argument("--no-refs", action="store_true", help="不抓 Yahoo／FRED 第二來源")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if args.list:
        for p, (sym, dec, g, ysym, fred) in INSTRUMENTS.items():
            print(f"{p:7} {g:7} 小數 {dec}  HistData {'無' if p in NO_HISTDATA else '有'}  Yahoo {ysym:10} "
                  f"FRED {'×'.join(s + ('⁻¹' if pw < 0 else '') for s, pw in fred) or '—'}")
        return
    groups = set(GROUPS) if "all" in args.group else set(args.group)
    pairs = [p for p, v in INSTRUMENTS.items() if v[2] in groups or p in args.pair]
    if not pairs:
        ap.error("請用 --group 或 --pair 指定商品")
    feed = Feed(args.workers, args.rate)
    hd = HistData()
    budget_end = time.monotonic() + args.budget_min * 60
    incomplete = []
    for p in pairs:
        log(f"== {p}")
        try:
            if not fetch_pair(p, feed, hd, budget_end, not args.no_refs):
                incomplete.append(p)
        except Throttled as exc:
            log(f"  {p} 限流：{exc}；這輪到此為止，下輪續抓")
            incomplete += pairs[pairs.index(p):]
            break
        except Exception as exc:
            log(f"  {p} 失敗：{exc!r}")
            incomplete.append(p)
        if time.monotonic() > budget_end:
            incomplete += pairs[pairs.index(p) + 1:]
            log(f"超過 {args.budget_min} 分鐘，餘下的等下輪續抓")
            break
    incomplete = list(dict.fromkeys(incomplete))
    log(f"完成：{len(pairs) - len(incomplete)}/{len(pairs)} 個商品抓齊；Dukascopy 請求 {feed.n_req}、404 {feed.n_404}、"
        f"重試 {feed.n_retry}；HistData 請求 {hd.n_req}" + (f"；未完成：{' '.join(incomplete)}" if incomplete else ""))
    sys.exit(3 if incomplete else 0)


if __name__ == "__main__":
    main()
