#!/usr/bin/env python3
"""外匯歷史數據（Dukascopy 免費歷史行情）→ data_forex/<PAIR>/（不進 git，存 GitHub Release「forex-data」）。

    python3 scripts/fetch_forex.py --group majors --budget-min 300     # 七大主要貨幣對
    python3 scripts/fetch_forex.py --pair EURUSD USDJPY                  # 指定幾個
    python3 scripts/fetch_forex.py --list                                # 列出全部商品與分組

每個商品：
- D1（買價 bid 與賣價 ask）：Dukascopy 每年一檔 → <PAIR>_D1.csv.gz、<PAIR>_D1_ask.csv.gz
- H1（bid 與 ask）：每月一檔 → <PAIR>_H1.csv.gz、<PAIR>_H1_ask.csv.gz
- M1（bid）：每日一檔 → <PAIR>_M1_<YYYY>.csv.gz（與 data/ 目錄的 MT5 匯出同一命名，backtest.py 載入器直接讀）
- 第二來源（--refs，預設開）：Yahoo 日線（<PAIR>=X）→ _ref_yahoo.csv.gz；FRED H.10 紐約中午匯率 → _ref_fred.csv.gz
- 欄位 Time,Open,High,Low,Close,Volume；**時間一律 UTC**（回測 --broker-offset 0）；Volume 是 Dukascopy 自己的成交量單位
- 可中斷續抓：已完成的年／月記在 _done.json；當年／當月每次重抓；只保留今天（UTC）以前的完整日

Dukascopy 檔案格式（bi5 = LZMA；每筆 24 bytes 大端 int×5 + float：時間偏移秒、開、收、低、高、量；價格整數要除以 10^小數位）
沙盒連不到 datafeed.dukascopy.com，這個程式在 GitHub Actions（fetch_forex.yml）跑；本機用 scripts/get_forex_data.py 拿 Release。
"""
import argparse
import gzip
import io
import json
import lzma
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "data_forex"
BASE = "https://datafeed.dukascopy.com/datafeed"
FIRST_YEAR = 2000
HEADER = "Time,Open,High,Low,Close,Volume\n"

# 商品：Dukascopy 路徑、小數位（JPY 交叉盤與貴金屬 3 位，其餘 5 位）、分組、Yahoo 代號、FRED H.10 系列（None = 沒有）
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
    # 主要交叉盤
    "EURJPY": ("EURJPY", 3, "crosses", "EURJPY=X", [("DEXUSEU", 1), ("DEXJPUS", 1)]),
    "GBPJPY": ("GBPJPY", 3, "crosses", "GBPJPY=X", [("DEXUSUK", 1), ("DEXJPUS", 1)]),
    "AUDJPY": ("AUDJPY", 3, "crosses", "AUDJPY=X", [("DEXUSAL", 1), ("DEXJPUS", 1)]),
    "NZDJPY": ("NZDJPY", 3, "crosses", "NZDJPY=X", [("DEXUSNZ", 1), ("DEXJPUS", 1)]),
    "CADJPY": ("CADJPY", 3, "crosses", "CADJPY=X", [("DEXJPUS", 1), ("DEXCAUS", -1)]),
    "CHFJPY": ("CHFJPY", 3, "crosses", "CHFJPY=X", [("DEXJPUS", 1), ("DEXSZUS", -1)]),
    "EURGBP": ("EURGBP", 5, "crosses", "EURGBP=X", [("DEXUSEU", 1), ("DEXUSUK", -1)]),
    "EURCHF": ("EURCHF", 5, "crosses", "EURCHF=X", [("DEXUSEU", 1), ("DEXSZUS", 1)]),
    "EURAUD": ("EURAUD", 5, "crosses", "EURAUD=X", [("DEXUSEU", 1), ("DEXUSAL", -1)]),
    "EURCAD": ("EURCAD", 5, "crosses", "EURCAD=X", [("DEXUSEU", 1), ("DEXCAUS", 1)]),
    "GBPCHF": ("GBPCHF", 5, "crosses", "GBPCHF=X", [("DEXUSUK", 1), ("DEXSZUS", 1)]),
    "GBPAUD": ("GBPAUD", 5, "crosses", "GBPAUD=X", [("DEXUSUK", 1), ("DEXUSAL", -1)]),
    "AUDNZD": ("AUDNZD", 5, "crosses", "AUDNZD=X", [("DEXUSAL", 1), ("DEXUSNZ", -1)]),
    "AUDCAD": ("AUDCAD", 5, "crosses", "AUDCAD=X", [("DEXUSAL", 1), ("DEXCAUS", 1)]),
    # 亞洲（港元、離岸人民幣、新加坡元）
    "USDHKD": ("USDHKD", 5, "asia", "HKD=X", [("DEXHKUS", 1)]),
    "USDCNH": ("USDCNH", 5, "asia", "CNH=X", [("DEXCHUS", 1)]),          # FRED 只有在岸 CNY，差距屬正常
    "USDSGD": ("USDSGD", 5, "asia", "SGD=X", [("DEXSIUS", 1)]),
    # 貴金屬現貨（XAUUSD 另有券商 MT5 M1 在 data/，2022-08 起；這裡可以回到 2003）
    "XAUUSD": ("XAUUSD", 3, "metals", "XAUUSD=X", []),
    "XAGUSD": ("XAGUSD", 3, "metals", "XAGUSD=X", []),
}
GROUPS = sorted({v[2] for v in INSTRUMENTS.values()})
REC = struct.Struct(">iiiiif")           # 時間偏移秒、開、收、低、高、量


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- Dukascopy
class Feed:
    def __init__(self, workers: int = 6):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Mozilla/5.0 (research data fetch; github.com/ai93560137/20260918)"
        self.workers = workers
        self.n_req = 0
        self.n_404 = 0

    def get(self, path: str) -> bytes | None:
        """回傳 bi5 原始位元組；404／空檔 → None；其他錯誤重試後拋出。"""
        url = f"{BASE}/{path}"
        for attempt in range(5):
            try:
                r = self.s.get(url, timeout=60)
            except requests.RequestException as exc:
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
                continue
            self.n_req += 1
            if r.status_code == 404:
                self.n_404 += 1
                return None
            if r.status_code == 200:
                return r.content or None
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
        raise RuntimeError(f"{url}: 重試 5 次仍失敗")

    def candles(self, path: str, base: datetime, scale: float) -> list[tuple]:
        raw = self.get(path)
        if not raw:
            return []
        return decode(raw, base, scale)


def decode(raw: bytes, base: datetime, scale: float) -> list[tuple]:
    """bi5 → [(Time 'YYYY-MM-DD HH:MM:SS', open, high, low, close, volume)]。"""
    data = lzma.decompress(raw)
    if len(data) % REC.size:
        raise ValueError(f"bi5 長度 {len(data)} 不是 {REC.size} 的倍數")
    out = []
    for t, o, c, lo, hi, v in REC.iter_unpack(data):
        ts = base + timedelta(seconds=t)
        out.append((ts.strftime("%Y-%m-%d %H:%M:%S"), o / scale, hi / scale, lo / scale, c / scale, v))
    return out


def fmt(rows: list[tuple], decimals: int) -> str:
    p = decimals
    return "".join(f"{t},{o:.{p}f},{h:.{p}f},{l:.{p}f},{c:.{p}f},{v:g}\n" for t, o, h, l, c, v in rows)


def read_gz(path: Path) -> dict[str, str]:
    """已有檔 → {Time: 整行}（用 dict 去重、合併後排序）。"""
    if not path.exists():
        return {}
    rows = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Time") or not line.strip():
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


def merge_write(path: Path, new_rows: list[tuple], decimals: int, cutoff: str) -> int:
    rows = read_gz(path)
    for line in fmt(new_rows, decimals).splitlines(keepends=True):
        rows[line.split(",", 1)[0]] = line
    rows = {k: v for k, v in rows.items() if k < cutoff}
    write_gz(path, rows)
    return len(rows)


# ---------------------------------------------------------------- 各時間框架
def fetch_pair(pair: str, feed: Feed, budget_end: float, do_refs: bool) -> bool:
    sym, decimals, group, ysym, fred = INSTRUMENTS[pair]
    scale = 10 ** decimals
    out = OUT_ROOT / pair
    out.mkdir(parents=True, exist_ok=True)
    done_p = out / "_done.json"
    done = json.loads(done_p.read_text()) if done_p.exists() else {"d1_years": [], "h1_months": [], "m1_years": []}
    today = datetime.now(timezone.utc).date()
    cutoff = today.strftime("%Y-%m-%d")               # 只保留 < 今天 00:00 UTC 的 K 線
    this_year = today.year

    def save_done() -> None:
        done_p.write_text(json.dumps(done, ensure_ascii=False, indent=0))

    # ---- D1：每年一檔（bid + ask），舊年份只抓一次
    for side in ("BID", "ASK"):
        key = "d1_years" if side == "BID" else "d1_years_ask"
        done.setdefault(key, [])
        rows = []
        for y in range(FIRST_YEAR, this_year + 1):
            if y in done[key]:
                continue
            base = datetime(y, 1, 1)
            got = feed.candles(f"{sym}/{y}/{side}_candles_day_1.bi5", base, scale)
            rows += got
            if y < this_year:
                done[key].append(y)
        if rows:
            n = merge_write(out / (f"{pair}_D1.csv.gz" if side == "BID" else f"{pair}_D1_ask.csv.gz"), rows, decimals, cutoff)
            log(f"  {pair} D1 {side.lower()}：新增 {len(rows)} 根，共 {n}")
    save_done()
    d1 = read_gz(out / f"{pair}_D1.csv.gz")
    if not d1:
        log(f"  {pair}：Dukascopy 沒有日線，跳過")
        (out / "_status.txt").write_text(f"{today} 沒有數據\n")
        return True
    first = date.fromisoformat(min(d1)[:10])
    log(f"  {pair}：日線 {first} → {max(d1)[:10]}（{len(d1)} 根）")

    # ---- H1：每月一檔（bid + ask）
    for side in ("BID", "ASK"):
        key = "h1_months" if side == "BID" else "h1_months_ask"
        done.setdefault(key, [])
        months = []
        y, m = first.year, first.month
        while (y, m) <= (today.year, today.month):
            tag = f"{y:04d}-{m:02d}"
            if tag not in done[key]:
                months.append((y, m))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        if months:
            def one(ym):
                yy, mm = ym
                return ym, feed.candles(f"{sym}/{yy}/{mm - 1:02d}/{side}_candles_hour_1.bi5", datetime(yy, mm, 1), scale)
            rows = []
            with ThreadPoolExecutor(feed.workers) as ex:
                for (yy, mm), got in ex.map(one, months):
                    rows += got
                    if (yy, mm) < (today.year, today.month):
                        done[key].append(f"{yy:04d}-{mm:02d}")
            n = merge_write(out / (f"{pair}_H1.csv.gz" if side == "BID" else f"{pair}_H1_ask.csv.gz"), rows, decimals, cutoff)
            log(f"  {pair} H1 {side.lower()}：抓 {len(months)} 個月、新增 {len(rows)} 根，共 {n}")
            save_done()

    # ---- M1（bid）：每日一檔，按年存；從該年檔案最後一天續抓（週六跳過：Dukascopy 週六沒有數據）
    complete = True
    for y in range(first.year, this_year + 1):
        if y in done["m1_years"]:
            continue
        if time.monotonic() > budget_end:
            complete = False
            break
        p = out / f"{pair}_M1_{y}.csv.gz"
        have = read_gz(p)
        start = max(first, date(y, 1, 1))
        if have:
            start = max(start, date.fromisoformat(max(have)[:10]))      # 最後一天重抓（可能不完整）
        end = min(date(y, 12, 31), today - timedelta(days=1))
        days = [start + timedelta(i) for i in range((end - start).days + 1)]
        days = [d for d in days if d.weekday() != 5]
        if not days:
            if y < this_year:
                done["m1_years"].append(y)
            continue

        def one_day(d: date):
            return d, feed.candles(f"{sym}/{d.year}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5",
                                   datetime(d.year, d.month, d.day), scale)

        CH = 90
        n_new = 0
        stopped = False
        for i in range(0, len(days), CH):
            if time.monotonic() > budget_end:
                stopped = True
                break
            chunk = days[i:i + CH]
            rows = []
            with ThreadPoolExecutor(feed.workers) as ex:
                for d, got in ex.map(one_day, chunk):
                    rows += got
            for line in fmt(rows, decimals).splitlines(keepends=True):
                have[line.split(",", 1)[0]] = line
            n_new += len(rows)
            have = {k: v for k, v in have.items() if k < cutoff}
            write_gz(p, have)
            log(f"  {pair} M1 {y}：{chunk[-1]}  本年 {len(have)} 根（本輪 +{n_new}，累計請求 {feed.n_req}、404 {feed.n_404}）")
        if stopped:
            complete = False
            break
        if y < this_year:
            done["m1_years"].append(y)
        save_done()
    save_done()

    if do_refs:
        try:
            fetch_refs(pair, out)
        except Exception as exc:                      # 第二來源失敗不影響主數據
            log(f"  {pair} 第二來源失敗：{exc}")
    m1 = sum(1 for _ in out.glob(f"{pair}_M1_*.csv.gz"))
    (out / "_status.txt").write_text(f"{today} D1 {len(d1)} 根（{first} 起）、M1 年檔 {m1}、"
                                     f"{'完成' if complete else '未完成（下輪續抓）'}\n")
    return complete


# ---------------------------------------------------------------- 第二來源
def fetch_refs(pair: str, out: Path) -> None:
    sym, decimals, group, ysym, fred = INSTRUMENTS[pair]
    # Yahoo 日線（收市價可靠、高低價粗糙）
    try:
        import yfinance as yf
        df = yf.download(ysym, start="2000-01-01", auto_adjust=False, progress=False, threads=False)
        if isinstance(df.columns, __import__("pandas").MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])[["Open", "High", "Low", "Close"]]
        df.index = [d.strftime("%Y-%m-%d") for d in df.index]
        df.index.name = "Date"
        df.to_csv(out / "_ref_yahoo.csv.gz", float_format=f"%.{decimals}f", compression="gzip")
        log(f"  {pair} Yahoo {ysym}：{len(df)} 天（{df.index[0]} → {df.index[-1]}）")
    except Exception as exc:
        log(f"  {pair} Yahoo {ysym} 失敗：{exc}")
    # FRED H.10（紐約中午買入價；交叉盤由主要貨幣對推算）
    if not fred:
        return
    import pandas as pd
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
    """用合成 bi5 檢查解碼、格式與合併（不用外網）。"""
    base = datetime(2024, 1, 2)
    recs = [(60 * i, 108000 + i, 108050 + i, 107950 + i, 108100 + i, 1.5) for i in range(3)]   # 時間、開、收、低、高、量
    raw = lzma.compress(b"".join(REC.pack(*r) for r in recs), format=lzma.FORMAT_ALONE)
    rows = decode(raw, base, 1000)
    assert rows[0] == ("2024-01-02 00:00:00", 108.0, 108.1, 107.95, 108.05, 1.5), rows[0]
    assert rows[2][0] == "2024-01-02 00:02:00"
    txt = fmt(rows, 3)
    assert txt.splitlines()[0] == "2024-01-02 00:00:00,108.000,108.100,107.950,108.050,1.5", txt
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.csv.gz"
        n = merge_write(p, rows, 3, "2024-01-02 00:02:00")
        assert n == 2, n
        n = merge_write(p, rows, 3, "2099-01-01")
        assert n == 3 and list(read_gz(p))[0] == "2024-01-02 00:00:00"
    # backtest.py 的載入器要能直接讀（時間格式 %Y-%m-%d %H:%M:%S，欄名 Time）
    sys.path.insert(0, str(ROOT))
    from backtest import load_bars
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(HEADER + txt)
    bars = load_bars(f.name, 0)
    assert len(bars) == 3 and bars[0]["close"] == 108.05 and bars[1]["time"] - bars[0]["time"] == 60
    print("selftest OK：bi5 解碼、CSV 格式、合併去重、backtest.load_bars 相容")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", nargs="*", choices=GROUPS + ["all"], default=[])
    ap.add_argument("--pair", nargs="*", choices=list(INSTRUMENTS), default=[])
    ap.add_argument("--budget-min", type=float, default=300)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-refs", action="store_true", help="不抓 Yahoo／FRED 第二來源")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if args.list:
        for p, (sym, dec, g, ysym, fred) in INSTRUMENTS.items():
            print(f"{p:7} {g:8} 小數 {dec}  Yahoo {ysym:10} FRED {'×'.join(s + ('⁻¹' if pw < 0 else '') for s, pw in fred) or '—'}")
        return
    groups = set(GROUPS) if "all" in args.group else set(args.group)
    pairs = [p for p, v in INSTRUMENTS.items() if v[2] in groups or p in args.pair]
    if not pairs:
        ap.error("請用 --group 或 --pair 指定商品")
    feed = Feed(args.workers)
    budget_end = time.monotonic() + args.budget_min * 60
    incomplete = []
    for p in pairs:
        log(f"== {p}")
        try:
            if not fetch_pair(p, feed, budget_end, not args.no_refs):
                incomplete.append(p)
        except Exception as exc:
            log(f"  {p} 失敗：{exc!r}")
            incomplete.append(p)
        if time.monotonic() > budget_end:
            incomplete += [q for q in pairs[pairs.index(p) + 1:]]
            log(f"超過 {args.budget_min} 分鐘，餘下 {incomplete[-1] if incomplete else ''} 等下輪續抓")
            break
    log(f"完成：{len(pairs) - len(set(incomplete))}/{len(pairs)} 個商品抓齊；請求 {feed.n_req}、404 {feed.n_404}"
        + (f"；未完成：{' '.join(dict.fromkeys(incomplete))}" if incomplete else ""))
    sys.exit(3 if incomplete else 0)


if __name__ == "__main__":
    main()
