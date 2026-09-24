"""多市場股票數據層（港股/美股/日股共用）——所有回測/監測工具讀價格都經過這裡。

兩種儲存格式，載入時自動判斷：

**v2（data/equities/<market>/<TICKER>/，港股/美股/日股都用這個；港股 2026-09-23 遷移）**
    prices_<YYYY>.csv   Date,Open,High,Low,Close,Volume（原始價；Close 已按拆股還原、未按股息還原）
    actions.csv         Date,Dividend,Split（yfinance actions；股息已按拆股還原）
    shares.csv          Date,Shares
  AdjClose 不存，載入時用股息重算（Yahoo/CRSP 法：除淨日之前的價格乘
  1 − 股息 / 除淨前一日收市）。好處：每天只有「今年那個檔」多一行，舊年份
  不動，git 只存幾 KB 的差異。
  （舊格式整檔 .csv.gz 每天重寫，股息一回溯全部價格都變，二進位檔在 git 裡
  沒法做差異壓縮——8 輪就長了 64MB，照這速度港股一年 4GB，見 README。）

**legacy（data/stocks/<TICKER>.csv.gz，已停用；只為了還拿著舊數據的其他分支保留讀取）**
    Date,Open,High,Low,Close,AdjClose,Volume  + <TICKER>.shares.csv.gz

市場由代碼後綴判斷：.HK 港股、.T 日股、其他美股（指數代碼 ^ 換 _ 存檔）。
"""
import bisect
import csv
import gzip
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEGACY_DIR = ROOT / "data" / "stocks"
V2_DIR = ROOT / "data" / "equities"


# 指數代碼沒有交易所後綴，要明列市場（其餘 ^ 開頭的當美股指數）
INDEX_MARKET = {"^N225": "jp", "^TOPX": "jp", "^HSI": "hk", "^HSCE": "hk"}


def market_of(ticker: str) -> str:
    if ticker in INDEX_MARKET:
        return INDEX_MARKET[ticker]
    if ticker.endswith(".HK"):
        return "hk"
    if ticker.endswith(".T"):
        return "jp"
    return "us"


def safe_name(ticker: str) -> str:
    return ticker.replace("^", "_")


def v2_dir(ticker: str) -> Path:
    return V2_DIR / market_of(ticker) / safe_name(ticker)


def has_v2(ticker: str) -> bool:
    return any(v2_dir(ticker).glob("prices_*.csv"))


def has_data(ticker: str) -> bool:
    return has_v2(ticker) or (LEGACY_DIR / (safe_name(ticker) + ".csv.gz")).exists()


def _num(s: str) -> float | None:
    try:
        return float(s) if s != "" else None
    except ValueError:
        return None


def load_raw(ticker: str) -> list[tuple[date, float | None, float | None, float | None, float, int]]:
    """v2 原始日線 [(date, open, high, low, close, volume)]，按日期排序。"""
    rows = []
    for p in sorted(v2_dir(ticker).glob("prices_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                c = _num(r["Close"])
                if c is None:
                    continue
                rows.append((date.fromisoformat(r["Date"]), _num(r["Open"]), _num(r["High"]),
                             _num(r["Low"]), c, int(float(r["Volume"] or 0))))
    rows.sort(key=lambda x: x[0])
    return rows


def load_actions(ticker: str) -> tuple[list[tuple[date, float]], list[tuple[date, float]]]:
    """v2 (股息 [(除淨日, 每股)], 拆股 [(日期, 比例)])。"""
    divs, splits = [], []
    p = v2_dir(ticker) / "actions.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = date.fromisoformat(r["Date"])
                if _num(r.get("Dividend", "")):
                    divs.append((d, float(r["Dividend"])))
                if _num(r.get("Split", "")):
                    splits.append((d, float(r["Split"])))
    return divs, splits


def adjust_factors(dates: list[date], closes: list[float], divs: list[tuple[date, float]]) -> list[float]:
    """每一根的股息還原因子（AdjClose = Close × 因子）。
    除淨日 e、股息 D：e 之前所有價格乘 (1 − D / e 前一交易日收市)，多次除淨連乘。"""
    n = len(dates)
    step = [1.0] * n        # step[i]：第 i 根「之後」發生的除淨，對 i 及之前的價格的乘數
    for e, d_amt in divs:
        j = bisect.bisect_left(dates, e)     # 除淨日（或之後第一個交易日）
        if j <= 0 or j >= n:  # 除淨日在第一根之前、或在最後一根之後（已公布未到）：不影響
            continue
        prev_close = closes[j - 1]
        if prev_close > 0 and 0 < d_amt < prev_close:
            step[j - 1] *= 1 - d_amt / prev_close
    out = [1.0] * n
    acc = 1.0
    for i in range(n - 1, -1, -1):
        acc *= step[i]
        out[i] = acc
    return out


SPIKE_FACTOR = 5.0


def drop_spikes(rows: list) -> tuple[list, list]:
    """Yahoo 在下市日/停牌期間偶有垃圾列（8303.T 2023-09-27 收市 553 億圓、成交量 0）。
    成交量為 0 且收市價相對前一根有效收市跳 > 5 倍（或 < 1/5）的列丟掉，回傳 (保留, 丟掉)。
    原始檔不改，只在載入時濾；QC 報告列出被濾的列數。"""
    kept, dropped = [], []
    for r in rows:
        if kept and r[5] == 0 and kept[-1][4] > 0:
            ratio = r[4] / kept[-1][4]
            if ratio > SPIKE_FACTOR or ratio < 1 / SPIKE_FACTOR:
                dropped.append(r)
                continue
        kept.append(r)
    # 開頭的孤立列：成交量 0、跟下一根差 >5 倍（0300.HK 2024-07-05 的 2.49，是代碼前一任主人的殘留，
    # 美的 H 股 2024-10 才有真價格）——留著會讓「價格早於入選日」的防代碼重用檢查被騙過
    while len(kept) >= 2 and kept[0][5] == 0 and kept[0][4] > 0:
        ratio = kept[1][4] / kept[0][4]
        if 1 / SPIKE_FACTOR <= ratio <= SPIKE_FACTOR:
            break
        dropped.append(kept.pop(0))
    return kept, dropped


def load_adjustments(ticker: str) -> list[tuple[date, float]]:
    """universes/<market>/adjustments.csv（ticker,date,factor,source,note）：Yahoo 漏調的公司行動
    （分拆等），由全量歷史比對（scripts/xcheck_history.py）抓到、人工查證後登記。載入時把該日之前的
    價格與股息乘 factor（原始檔不改）。"""
    p = ROOT / "universes" / market_of(ticker) / "adjustments.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return sorted((date.fromisoformat(r["date"]), float(r["factor"]))
                      for r in csv.DictReader(f) if r["ticker"] == ticker)


def load_overrides(ticker: str) -> dict[date, float]:
    """universes/<market>/price_overrides.csv（ticker,date,close,source,note）：全量歷史比對抓到、
    人工查證的 Yahoo 單日錯價（例：5333.T 2010-10-29 收市被記成前一日低價 1486，實際 1219）。
    載入時改收市價（高低價跟著夾住），原始檔不改。"""
    p = ROOT / "universes" / market_of(ticker) / "price_overrides.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {date.fromisoformat(r["date"]): float(r["close"]) for r in csv.DictReader(f) if r["ticker"] == ticker}


def load_ohlcv(ticker: str, apply_adjustments: bool = True) -> list[dict]:
    """[{Date, Open, High, Low, Close, AdjClose, Volume}]，兩種格式同一個介面（給 QC 用）。
    新格式會先濾掉明顯的垃圾列（drop_spikes），並套用人工登記的公司行動修正（load_adjustments；
    apply_adjustments=False 給「驗證存檔忠實重建 yfinance」用）。"""
    if has_v2(ticker):
        rows, _ = drop_spikes(load_raw(ticker))
        divs, _ = load_actions(ticker)
        if apply_adjustments:
            ov = load_overrides(ticker)
            rows = [(r[0], r[1], max(r[2], ov[r[0]]) if r[2] is not None else None,
                     min(r[3], ov[r[0]]) if r[3] is not None else None, ov[r[0]], r[5]) if r[0] in ov else r
                    for r in rows]
        for e, f in (load_adjustments(ticker) if apply_adjustments else []):
            rows = [(r[0], *(x * f if x is not None else None for x in r[1:5]), r[5]) if r[0] < e else r
                    for r in rows]
            divs = [(d, a * f) if d < e else (d, a) for d, a in divs]
        fac = adjust_factors([r[0] for r in rows], [r[4] for r in rows], divs)
        return [{"Date": r[0], "Open": r[1], "High": r[2], "Low": r[3], "Close": r[4],
                 "AdjClose": r[4] * f, "Volume": r[5]} for r, f in zip(rows, fac)]
    path = LEGACY_DIR / (safe_name(ticker) + ".csv.gz")
    out = []
    with gzip.open(path, "rt", newline="") as f:
        for r in csv.DictReader(f):
            out.append({"Date": date.fromisoformat(r["Date"]), "Open": float(r["Open"]),
                        "High": float(r["High"]), "Low": float(r["Low"]), "Close": float(r["Close"]),
                        "AdjClose": float(r["AdjClose"]), "Volume": int(float(r["Volume"] or 0))})
    kept, _ = drop_spikes([(x["Date"], x["Open"], x["High"], x["Low"], x["Close"], x["Volume"]) for x in out])
    keep_dates = {x[0] for x in kept}
    return [x for x in out if x["Date"] in keep_dates]


def load_series(ticker: str) -> dict[date, tuple[float, float, float]]:
    """{date: (adj_open, adj_close, raw_close)}——回測引擎的標準輸入。
    Open=0 的髒值退回用當天 AdjClose（見 data/stocks/README.md 已知限制）。
    找不到數據丟 FileNotFoundError。"""
    out = {}
    for r in load_ohlcv(ticker):
        c, ac, o = r["Close"], r["AdjClose"], r["Open"]
        adj_open = o * (ac / c) if c and o else ac
        out[r["Date"]] = (adj_open, ac, c)
    return out


def load_shares(ticker: str) -> list[tuple[date, int]] | None:
    """流通股數歷史 [(date, shares)]（排序），沒有就 None。"""
    rows = []
    v2 = v2_dir(ticker) / "shares.csv"
    if v2.exists():
        with open(v2, newline="", encoding="utf-8") as f:
            rows = [(date.fromisoformat(r["Date"]), int(r["Shares"])) for r in csv.DictReader(f)]
    else:
        path = LEGACY_DIR / (safe_name(ticker) + ".shares.csv.gz")
        if not path.exists():
            return None
        with gzip.open(path, "rt", newline="") as f:
            rows = [(date.fromisoformat(r["Date"]), int(r["Shares"])) for r in csv.DictReader(f)]
    rows.sort()
    return rows or None
