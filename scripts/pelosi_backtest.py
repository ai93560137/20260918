#!/usr/bin/env python3
# =============================================================================
# 佩洛西跟單回測（方案 B：申報日跟單）
# -----------------------------------------------------------------------------
# 輸入：data/pelosi/transactions.json（scripts/pelosi_tracker.py 產生）
# 價格：優先讀本地美股日線（gifted-carson 分支 data/equities/us，已拆股調整，
#       這裡再用 actions.csv 的股息還原成含息總報酬）；本地沒有的代號才抓 Yahoo 還原日線。
#
# 規則（不偷看未來）：
#   * 進場：申報日「之後」第一個交易日的開盤價。申報可能在收盤後才公開，
#     所以不用申報日當天。交易日只拿來算「延遲成本」對照，不當策略結果。
#   * 訊號：股票/ETF 買入 → 做多；買 Call → 改買正股做多（期權歷史價難取得、槓桿也不複製）。
#     賣出股票/Call、Call 到期作廢 → 賣出訊號。行使 Call 只是延續部位，不算新訊號。
#     Put、交換（E）、無代號資產略過。修正申報的重複交易只算最早那份。
#   * 出場（兩類，分別回測）：
#       sell  她申報賣出同一代號 → 該申報後第一個交易日開盤全數平倉
#       hNm   固定持有 N 個月（1/3/6/12）→ 到期後第一個交易日開盤平倉
#     資料結束時仍持有 → 以最後收盤市值計（標記為未平倉）。
#   * 倉位（兩種）：equal 每筆同額；amount 按申報金額區間中位數加權。
#   * 組合：只持有「目前未平倉的部位」、依市值加權（像追蹤指數），空倉時現金 0 報酬。
#   * 基準：同期間 SPY、QQQ 買入持有；另附 NANC（民主黨議員交易 ETF，2023 年起）。
#
# 用法：
#   python3 scripts/pelosi_backtest.py
#   python3 scripts/pelosi_backtest.py --start 2018-01-01 --exits sell h3m h12m
#   python3 scripts/pelosi_backtest.py --equities path/to/data/equities/us
# 輸出：data/pelosi/backtest/README.md、trades.csv、summary.json、equity.svg
# =============================================================================
import argparse
import csv
import json
import math
import os
import sys
import time
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TX_FILE = os.path.join(ROOT, "data", "pelosi", "transactions.json")
OUT_DIR = os.path.join(ROOT, "data", "pelosi", "backtest")
# workflow 把 gifted-carson 分支的美股資料 sparse checkout 到 _equities/
DEFAULT_EQUITIES = os.path.join(ROOT, "_equities", "data", "equities", "us")
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
UA = {"User-Agent": "Mozilla/5.0 (pelosi-backtest; +github actions)"}
BENCHMARKS = ["SPY", "QQQ"]
EXTRA_BENCH = ["NANC"]  # 2023 年上市，只在有資料的期間比較
ALL_EXITS = ["sell", "h1m", "h3m", "h6m", "h12m"]
WEIGHTS = ["equal", "amount"]
# 改名的代號：申報上寫舊代號，價格用新代號查（拆股/還原已在同一條歷史裡）
MAX_ENTRY_GAP_DAYS = 7  # 申報後這麼多天內沒有成交價，視為無法跟單
TICKER_ALIASES = {"SQ": "XYZ", "FB": "META"}


# -----------------------------------------------------------------------------
# 價格
# -----------------------------------------------------------------------------
class Prices:
    """單一代號的日線：days（遞增）、open、close（皆已還原）。"""

    def __init__(self, days, opens, closes):
        self.days, self.open, self.close = days, opens, closes
        self.idx = {d: i for i, d in enumerate(days)}

    def first_index_after(self, d):
        """d 之後（不含 d）第一個交易日的索引；沒有則 None。"""
        i = bisect_right(self.days, d)
        return i if i < len(self.days) else None

    def first_index_on_or_after(self, d):
        i = bisect_right(self.days, d - timedelta(days=1))
        return i if i < len(self.days) else None


def fetch_prices(ticker, start, retries=4):
    t = ticker.replace(".", "-").replace("/", "-")
    p1 = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())
    url = (YAHOO_URL.format(ticker=t)
           + f"?period1={p1}&period2={int(time.time())}&interval=1d&events=div,split")
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                raise requests.RequestException("429 rate limited")
            r.raise_for_status()
            res = (r.json().get("chart") or {}).get("result")
            if not res:
                return None
            res = res[0]
            q = res["indicators"]["quote"][0]
            adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
            days, opens, closes = [], [], []
            for ts, o, c, a in zip(res.get("timestamp") or [], q["open"], q["close"], adj):
                if None in (o, c, a) or c <= 0:
                    continue
                f = a / c  # 還原因子：開盤也按同一比例調整
                d = datetime.fromtimestamp(ts + res["meta"].get("gmtoffset", 0), timezone.utc).date()
                if days and d == days[-1]:
                    continue
                days.append(d)
                opens.append(o * f)
                closes.append(a)
            return Prices(days, opens, closes) if days else None
        except (requests.RequestException, ValueError, KeyError) as e:
            if i == retries - 1:
                print(f"  價格 {ticker} 失敗：{e}")
                return None
            time.sleep(2 ** (i + 1))


def _read_csv_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_local_prices(equities_dir, ticker, start):
    """讀本地日線（已拆股調整），用股息往回乘還原因子得到含息總報酬價。
    做法同 Yahoo adjclose：除息日之前的價格 × (1 − 股息 ÷ 除息前一日收盤)。"""
    folder = os.path.join(equities_dir, ticker.replace(".", "-").replace("/", "-"))
    if not os.path.isdir(folder):
        return None
    rows = []
    for name in sorted(os.listdir(folder)):
        if not (name.startswith("prices_") and name.endswith(".csv")):
            continue
        try:
            year = int(name[7:11])
        except ValueError:
            continue
        if year < start.year:
            continue
        for r in _read_csv_rows(os.path.join(folder, name)):
            try:
                d = date.fromisoformat(r["Date"])
                o, c = float(r["Open"]), float(r["Close"])
            except (KeyError, ValueError):
                continue
            if o > 0 and c > 0 and d >= start:
                rows.append((d, o, c))
    rows.sort()
    rows = [r for i, r in enumerate(rows) if i == 0 or r[0] != rows[i - 1][0]]
    if not rows:
        return None
    divs = {}
    act = os.path.join(folder, "actions.csv")
    if os.path.exists(act):
        for r in _read_csv_rows(act):
            try:
                if r.get("Dividend"):
                    d = date.fromisoformat(r["Date"])
                    divs[d] = divs.get(d, 0.0) + float(r["Dividend"])
            except ValueError:
                continue
    days = [r[0] for r in rows]
    # 股息對到除息日當天或之後第一個交易日
    div_at = {}
    for d, amt in divs.items():
        i = bisect_right(days, d - timedelta(days=1))
        if 0 < i < len(days):
            div_at[i] = div_at.get(i, 0.0) + amt
    factor, f = [1.0] * len(rows), 1.0
    for i in range(len(rows) - 1, -1, -1):
        factor[i] = f
        if i in div_at:
            prev_close = rows[i - 1][2]
            f *= max(1 - div_at[i] / prev_close, 0.5)  # 防呆：異常股息不讓價格歸零
    return Prices(days, [r[1] * k for r, k in zip(rows, factor)], [r[2] * k for r, k in zip(rows, factor)])


def load_all_prices(tickers, start, cache_dir=None, equities_dir=None, sources=None, yahoo=True):
    out = {}
    sources = sources if sources is not None else {}
    for n, tk in enumerate(sorted(tickers), 1):
        src = TICKER_ALIASES.get(tk, tk)
        if equities_dir:
            p = load_local_prices(equities_dir, src, start) or (
                load_local_prices(equities_dir, tk, start) if src != tk else None)
            if p:
                out[tk] = p
                sources[tk] = "local"
                continue
        if not yahoo:
            continue
        cache = os.path.join(cache_dir, f"{tk}.json") if cache_dir else None
        if cache and os.path.exists(cache):
            with open(cache) as f:
                raw = json.load(f)
            out[tk] = Prices([date.fromisoformat(d) for d in raw["d"]], raw["o"], raw["c"])
            continue
        p = fetch_prices(src, start)
        if p:
            out[tk] = p
            sources[tk] = "yahoo"
            if cache:
                with open(cache, "w") as f:
                    json.dump({"d": [d.isoformat() for d in p.days], "o": p.open, "c": p.close}, f)
        print(f"  [{n}/{len(tickers)}] {tk}：{len(p.days) if p else 0} 天")
        time.sleep(0.25)
    return out


# -----------------------------------------------------------------------------
# 訊號
# -----------------------------------------------------------------------------
def amount_mid(r):
    lo, hi = r.get("amount_min"), r.get("amount_max")
    if lo and hi:
        return (lo + hi) / 2
    return float(lo or 15000)


def classify(r):
    """回傳 'buy' / 'sell' / None。"""
    tk, at, tp = r.get("ticker"), r.get("asset_type"), r.get("type", "")
    if not tk or at not in ("ST", "OP", "EF"):
        return None
    if "exercis" in (r.get("description") or "").lower():
        return None  # 行使早已買入的 Call：部位延續，不是新訊號（買 Call 時已進場）
    if at == "OP":
        opt = r.get("option") or {}
        if opt.get("kind") == "put":
            return None  # Put 方向與意圖不明，略過
        # kind 為 None：2014 年版只寫「Purchase of N Options」，她幾乎只買 Call，視為看多
        if opt.get("action") == "expired":
            return "sell"  # Call 到期作廢，部位消失
        if opt.get("action") == "sold" or tp.startswith("S"):
            return "sell"
        if opt.get("action") == "purchased" or tp == "P":
            return "buy"
        return None
    if tp == "P":
        return "buy"
    if tp.startswith("S"):
        return "sell"
    return None


def build_signals(filings, start=None):
    """修正申報（Amended）會把同一筆交易再報一次：跨申報的重複只保留最早公開的那份。"""
    sig, seen = [], {}
    for f in sorted(filings, key=lambda x: x["filing_date"]):
        fd = date.fromisoformat(f["filing_date"])
        if start and fd < start:
            continue
        for r in f.get("transactions", []):
            side = classify(r)
            if not side:
                continue
            try:
                td = date.fromisoformat(r["date"])
            except ValueError:
                continue
            key = (r["ticker"].upper(), side, td, r.get("amount"))
            if seen.get(key, f["doc_id"]) != f["doc_id"]:
                continue
            seen[key] = f["doc_id"]
            sig.append({
                "ticker": r["ticker"].upper(), "side": side, "trade_date": td, "filing_date": fd,
                "lag_days": (fd - td).days, "weight_amount": amount_mid(r),
                "asset": r.get("asset", ""), "doc_id": f.get("doc_id", ""),
            })
    sig.sort(key=lambda s: (s["filing_date"], s["ticker"]))
    return sig


# -----------------------------------------------------------------------------
# 部位（lot）
# -----------------------------------------------------------------------------
def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue


def make_lots(signals, prices, exit_rule, weight_mode, entry_on="filing"):
    """entry_on='filing' 為策略；'trade' 為交易日對照（偷看未來，只算延遲成本）。"""
    lots, skipped = [], []
    sells = {}
    key = "filing_date" if entry_on == "filing" else "trade_date"
    for s in signals:
        if s["side"] == "sell":
            sells.setdefault(s["ticker"], []).append(s[key])
    for s in signals:
        if s["side"] != "buy":
            continue
        p = prices.get(s["ticker"])
        if not p:
            skipped.append((s, "無價格"))
            continue
        ref = s["filing_date"] if entry_on == "filing" else s["trade_date"]
        ei = p.first_index_after(ref) if entry_on == "filing" else p.first_index_on_or_after(ref)
        if ei is None:
            skipped.append((s, "進場日無資料"))
            continue
        if (p.days[ei] - ref).days > MAX_ENTRY_GAP_DAYS:
            # 例：舊 Hertz 2020 年破產，Yahoo 的 HTZ 從 2021 年新上市才有資料——不能拿 2021 價格當 2014 進場
            skipped.append((s, f"申報後 {MAX_ENTRY_GAP_DAYS} 天內無價格（已下市或代號被重用）"))
            continue
        xi, reason = None, "未平倉"
        if exit_rule == "sell":
            later = [d for d in sells.get(s["ticker"], []) if d >= p.days[ei]]
            if later:
                xi = p.first_index_after(min(later))
                reason = "跟賣"
        else:
            months = int(exit_rule[1:-1])
            xi = p.first_index_on_or_after(add_months(p.days[ei], months))
            reason = f"持有{months}個月"
        if xi is not None and xi <= ei:
            xi = ei + 1 if ei + 1 < len(p.days) else None
        if xi is None:
            reason = "未平倉"
        entry_px = p.open[ei]
        exit_px = p.open[xi] if xi is not None else p.close[-1]
        w = 1.0 if weight_mode == "equal" else s["weight_amount"]
        lots.append({**s, "ei": ei, "xi": xi, "entry_day": p.days[ei],
                     "exit_day": p.days[xi] if xi is not None else p.days[-1],
                     "entry_px": entry_px, "exit_px": exit_px, "ret": exit_px / entry_px - 1,
                     "open": xi is None, "exit_reason": reason, "w": w})
    return lots, skipped


def bench_return(p, d0, d1, exit_open):
    """基準同期報酬：d0 開盤進、d1 開盤（或收盤）出。"""
    if not p:
        return None
    i0 = p.first_index_on_or_after(d0)
    i1 = p.first_index_on_or_after(d1)
    if i0 is None or i1 is None or p.days[i0] > d1:
        return None
    px1 = p.open[i1] if exit_open else p.close[i1]
    return px1 / p.open[i0] - 1


# -----------------------------------------------------------------------------
# 組合淨值
# -----------------------------------------------------------------------------
def portfolio_curve(lots, prices, calendar):
    """calendar：交易日序列（用 SPY）。回傳 [(day, nav, invested_flag)]。
    每個 lot 每日貢獻：進場日 開→收；持有日 收→收；出場日 前收→開（之後移除）。"""
    pending = sorted(lots, key=lambda x: x["entry_day"])
    k = 0
    active = []  # [lot, value, last_px]
    nav, out = 1.0, []
    for d in calendar:
        # 用 <= 而非 ==：個股交易日不在 SPY 日曆上時，順延到下一個日曆日加入
        while k < len(pending) and pending[k]["entry_day"] <= d:
            lot = pending[k]
            k += 1
            if lot["open"] or lot["exit_day"] > d:
                active.append([lot, lot["w"], lot["entry_px"]])
        if not active:
            out.append((d, nav, False))
            continue
        base = sum(a[1] for a in active)
        gain, keep = 0.0, []
        for a in active:
            lot, val, last = a
            p = prices[lot["ticker"]]
            i = p.idx.get(d)
            if i is None:  # 該股當天無交易（停牌等），價值不變
                keep.append(a)
                continue
            exiting = not lot["open"] and d >= lot["exit_day"]
            px = p.open[i] if exiting else p.close[i]
            gain += val * (px / last - 1)
            if not exiting:
                keep.append([lot, val * px / last, px])
        nav *= 1 + gain / base
        active = keep
        out.append((d, nav, True))
    return out


def stats(curve):
    if len(curve) < 2:
        return {}
    navs = [c[1] for c in curve]
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    years = (curve[-1][0] - curve[0][0]).days / 365.25
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    mu = sum(rets) / len(rets)
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / max(len(rets) - 1, 1))
    return {
        "total": navs[-1] / navs[0] - 1,
        "cagr": (navs[-1] / navs[0]) ** (1 / years) - 1 if years > 0 else None,
        "mdd": mdd,
        "vol": sd * math.sqrt(252),
        "sharpe": mu / sd * math.sqrt(252) if sd > 0 else None,
        "invested": sum(1 for c in curve if c[2]) / len(curve),
    }


def bench_curve(p, calendar):
    if not p:
        return []
    out, base = [], None
    for d in calendar:
        i = p.idx.get(d)
        if i is None:
            continue
        base = base or p.close[i]
        out.append((d, p.close[i] / base, True))
    return out


# -----------------------------------------------------------------------------
# 輸出
# -----------------------------------------------------------------------------
def pct(x, digits=1):
    return "—" if x is None else f"{x * 100:+.{digits}f}%"


def svg_chart(series, path, title):
    """靜態 SVG 折線圖（對數軸），GitHub README 直接顯示；深淺色都可讀。
    series: [(label, css_var, [(day, nav), ...])]"""
    W, H, L, R, T, B = 900, 420, 64, 120, 40, 36
    pts = [(d, v) for _, _, s in series for d, v in s]
    if not pts:
        return
    d0, d1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lo = math.log(min(p[1] for p in pts))
    hi = math.log(max(p[1] for p in pts))
    span_d = max((d1 - d0).days, 1)
    span_v = max(hi - lo, 1e-9)
    X = lambda d: L + (d - d0).days / span_d * (W - L - R)
    Y = lambda v: T + (hi - math.log(v)) / span_v * (H - T - B)
    css = (
        ":root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;"
        "--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a}"
        "@media (prefers-color-scheme: dark){:root{--bg:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;"
        "--grid:#3a3936;--s1:#3987e5;--s2:#d95926;--s3:#199e70}}"
        "text{font:12px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;fill:var(--ink2)}"
        ".t{font-size:14px;font-weight:600;fill:var(--ink)}"
        ".lbl{font-weight:600;fill:var(--ink)}"
    )
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
           f"<style>{css}</style>", f'<rect width="{W}" height="{H}" fill="var(--bg)"/>',
           f'<text class="t" x="{L}" y="22">{title}</text>']
    # 對數軸格線：1, 2, 5 倍數
    k = 10 ** math.floor(lo / math.log(10))
    while k <= math.exp(hi) * 1.001:
        for m in (1, 2, 5):
            v = k * m
            if math.exp(lo) * 0.999 <= v <= math.exp(hi) * 1.001:
                y = Y(v)
                out.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
                out.append(f'<text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{v:g}×</text>')
        k *= 10
    for yr in range(d0.year + 1, d1.year + 1):
        x = X(date(yr, 1, 1))
        out.append(f'<text x="{x:.1f}" y="{H - 12}" text-anchor="middle">{yr}</text>')
    # 直接標籤（線尾），並避免重疊
    ends = []
    for label, var, s in series:
        if not s:
            continue
        step = max(1, len(s) // 600)
        sp = s[::step] + ([s[-1]] if (len(s) - 1) % step else [])
        d = " ".join(f"{'M' if i == 0 else 'L'}{X(a):.1f},{Y(b):.1f}" for i, (a, b) in enumerate(sp))
        out.append(f'<path d="{d}" fill="none" stroke="var({var})" stroke-width="2" stroke-linejoin="round"/>')
        ends.append([Y(s[-1][1]), label, var, s[-1][1]])
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 16)
    for y, label, var, v in ends:
        out.append(f'<circle cx="{W - R + 6}" cy="{y:.1f}" r="4" fill="var({var})"/>')
        out.append(f'<text class="lbl" x="{W - R + 14}" y="{y + 4:.1f}">{label} {v:.2f}×</text>')
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def write_trades_csv(lots, path):
    cols = ["ticker", "asset", "trade_date", "filing_date", "lag_days", "entry_day", "entry_px",
            "exit_day", "exit_px", "exit_reason", "ret", "spy_ret", "qqq_ret", "excess_spy", "doc_id"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for lot in lots:
            w.writerow([lot["ticker"], lot["asset"], lot["trade_date"], lot["filing_date"], lot["lag_days"],
                        lot["entry_day"], f"{lot['entry_px']:.4f}", lot["exit_day"], f"{lot['exit_px']:.4f}",
                        lot["exit_reason"], f"{lot['ret']:.4f}",
                        "" if lot["spy"] is None else f"{lot['spy']:.4f}",
                        "" if lot["qqq"] is None else f"{lot['qqq']:.4f}",
                        "" if lot["spy"] is None else f"{lot['ret'] - lot['spy']:.4f}", lot["doc_id"]])


def trade_stats(lots):
    if not lots:
        return {}
    rets = sorted(x["ret"] for x in lots)
    ex = [x["ret"] - x["spy"] for x in lots if x["spy"] is not None]
    exq = [x["ret"] - x["qqq"] for x in lots if x["qqq"] is not None]
    return {
        "n": len(lots),
        "win": sum(1 for r in rets if r > 0) / len(rets),
        "avg": sum(rets) / len(rets),
        "median": rets[len(rets) // 2],
        "beat_spy": sum(1 for e in ex if e > 0) / len(ex) if ex else None,
        "avg_excess_spy": sum(ex) / len(ex) if ex else None,
        "avg_excess_qqq": sum(exq) / len(exq) if exq else None,
    }


# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="佩洛西申報日跟單回測")
    ap.add_argument("--transactions", default=TX_FILE)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--start", help="只用此日期（含）之後的申報，YYYY-MM-DD")
    ap.add_argument("--exits", nargs="*", default=ALL_EXITS, choices=ALL_EXITS)
    ap.add_argument("--cache", help="Yahoo 價格快取資料夾（本機反覆跑時用）")
    ap.add_argument("--equities", default=os.environ.get("PELOSI_EQUITIES", DEFAULT_EQUITIES),
                    help="本地美股日線資料夾（data/equities/us 格式）；不存在就全部用 Yahoo")
    args = ap.parse_args()

    with open(args.transactions, encoding="utf-8") as f:
        filings = json.load(f)
    start = date.fromisoformat(args.start) if args.start else None
    signals = build_signals(filings, start)
    buys = [s for s in signals if s["side"] == "buy"]
    if not buys:
        print("沒有可回測的買入訊號（先跑 scripts/pelosi_tracker.py 回補歷史）")
        return 1
    first = min(s["trade_date"] for s in signals)
    print(f"訊號 {len(signals)} 筆（買 {len(buys)}、賣 {len(signals) - len(buys)}），"
          f"最早交易 {first}")

    if args.cache:
        os.makedirs(args.cache, exist_ok=True)
    tickers = {s["ticker"] for s in signals} | set(BENCHMARKS) | set(EXTRA_BENCH)
    equities = args.equities if args.equities and os.path.isdir(args.equities) else None
    print(f"本地美股資料：{equities or '無（全部用 Yahoo）'}")
    sources = {}
    prices = load_all_prices(tickers, first - timedelta(days=10), args.cache, equities, sources)
    n_local = sum(1 for v in sources.values() if v == "local")
    src_note = f"價格來源：本地美股資料 {n_local} 檔、Yahoo {len(sources) - n_local} 檔"
    print(src_note)
    spy, qqq = prices.get("SPY"), prices.get("QQQ")
    if not spy:
        print("抓不到 SPY，無法建立交易日曆")
        return 1

    os.makedirs(args.out, exist_ok=True)
    results, best = [], None
    for exit_rule in args.exits:
        for wm in WEIGHTS:
            lots, skipped = make_lots(signals, prices, exit_rule, wm)
            if not lots:
                continue
            for lot in lots:
                exit_open = not lot["open"]
                lot["spy"] = bench_return(spy, lot["entry_day"], lot["exit_day"], exit_open)
                lot["qqq"] = bench_return(qqq, lot["entry_day"], lot["exit_day"], exit_open)
            cal0 = min(lot["entry_day"] for lot in lots)
            calendar = [d for d in spy.days if d >= cal0]
            curve = portfolio_curve(lots, prices, calendar)
            # 延遲成本：同規則但在交易日進場（偷看未來，只作對照）
            t_lots, _ = make_lots(signals, prices, exit_rule, wm, entry_on="trade")
            t_curve = portfolio_curve(t_lots, prices, [d for d in spy.days
                                                       if d >= min(x["entry_day"] for x in t_lots)])
            res = {"exit": exit_rule, "weight": wm, "lots": lots, "skipped": skipped,
                   "curve": curve, "port": stats(curve), "trade_date_port": stats(t_curve),
                   "trades": trade_stats(lots), "calendar": calendar}
            results.append(res)
            print(f"  {exit_rule:>5} / {wm:<6} 部位 {len(lots):>4}  "
                  f"CAGR {pct(res['port'].get('cagr'))}  MDD {pct(res['port'].get('mdd'))}")
            if exit_rule == "sell" and wm == "equal":
                best = res
    best = best or results[0]

    cal = best["calendar"]
    bstats = {b: stats(bench_curve(prices.get(b), cal)) for b in BENCHMARKS}
    nanc = prices.get("NANC")
    nanc_note = ""
    if nanc:
        c0 = nanc.days[0]
        sub = [c for c in best["curve"] if c[0] >= c0]
        if len(sub) > 1:
            sub = [(d, v / sub[0][1], f) for d, v, f in sub]
            nanc_note = (f"NANC 上市（{c0}）以來：跟單 {pct(stats(sub)['cagr'])}／年、"
                         f"NANC {pct(stats(bench_curve(nanc, [c[0] for c in sub]))['cagr'])}／年。")

    svg_chart([("跟單", "--s1", [(d, v) for d, v, _ in best["curve"]]),
               ("SPY", "--s2", [(d, v) for d, v, _ in bench_curve(spy, cal)]),
               ("QQQ", "--s3", [(d, v) for d, v, _ in bench_curve(qqq, cal)])],
              os.path.join(args.out, "equity.svg"),
              "淨值（對數軸）：申報日跟單・跟賣出場・等權重 vs SPY／QQQ")
    write_trades_csv(best["lots"], os.path.join(args.out, "trades.csv"))

    summary = [{k: r[k] for k in ("exit", "weight", "port", "trade_date_port", "trades")} for r in results]
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "price_sources": sources, "benchmarks": bstats, "results": summary}, f, ensure_ascii=False, indent=1, default=str)

    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write(render_report(results, best, bstats, nanc_note, signals, cal, src_note))
    print(f"報告：{os.path.relpath(os.path.join(args.out, 'README.md'), ROOT)}")
    return 0


EXIT_NAMES = {"sell": "跟賣出場", "h1m": "持有 1 個月", "h3m": "持有 3 個月",
              "h6m": "持有 6 個月", "h12m": "持有 12 個月"}
WEIGHT_NAMES = {"equal": "等權重", "amount": "金額加權"}


def render_report(results, best, bstats, nanc_note, signals, cal, src_note=""):
    lags = sorted(s["lag_days"] for s in signals)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    o = [
        "# 佩洛西跟單回測（申報日跟單）", "",
        f"更新：{now}　｜　期間 {cal[0]} ～ {cal[-1]}　｜　訊號 {len(signals)} 筆"
        f"　｜　申報延遲中位數 {lags[len(lags) // 2]} 天", "",
        "規則：申報公開後的下一個交易日**開盤**進場；Call 期權改買正股；行使 Call 不算新訊號；Put 與交換略過。"
        "組合只持有未平倉部位、依市值加權，空倉時為現金。價格為含息還原日線，未計手續費與滑價。"
        f"{src_note}。", "",
        "![淨值](equity.svg)", "",
        "## 組合績效", "",
        "| 出場 | 倉位 | 年化 | 總報酬 | 最大回撤 | 波動 | Sharpe | 持倉時間 | 交易日進場（對照） |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        p, t = r["port"], r["trade_date_port"]
        sh = "—" if p.get("sharpe") is None else f"{p['sharpe']:.2f}"
        o.append(f"| {EXIT_NAMES[r['exit']]} | {WEIGHT_NAMES[r['weight']]} | {pct(p.get('cagr'))} "
                 f"| {pct(p.get('total'), 0)} | {pct(p.get('mdd'))} | {p.get('vol', 0) * 100:.1f}% | {sh} "
                 f"| {p.get('invested', 0) * 100:.0f}% | {pct(t.get('cagr'))} |")
    for b, s in bstats.items():
        if s:
            sh = "—" if s.get("sharpe") is None else f"{s['sharpe']:.2f}"
            o.append(f"| **{b} 買入持有** | — | {pct(s['cagr'])} | {pct(s['total'], 0)} | {pct(s['mdd'])} "
                     f"| {s['vol'] * 100:.1f}% | {sh} | 100% | — |")
    o += ["", "「交易日進場」假設在她實際交易當天就知道（不可能做到），與申報日的差距 ≈ 延遲申報的成本。"]
    if nanc_note:
        o += ["", nanc_note]
    o += ["", "## 逐筆統計", "",
          "| 出場 | 倉位 | 筆數 | 勝率 | 平均報酬 | 中位數 | 贏 SPY 比例 | 平均超額 vs SPY | 平均超額 vs QQQ |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        t = r["trades"]
        if r["weight"] != "equal":
            continue  # 逐筆統計與權重無關
        beat = "—" if t.get("beat_spy") is None else f"{t['beat_spy'] * 100:.0f}%"
        o.append(f"| {EXIT_NAMES[r['exit']]} | — | {t['n']} | {t['win'] * 100:.0f}% | {pct(t['avg'])} "
                 f"| {pct(t['median'])} | {beat} | {pct(t['avg_excess_spy'])} | {pct(t['avg_excess_qqq'])} |")
    lots = sorted(best["lots"], key=lambda x: x["entry_day"], reverse=True)
    o += ["", f"## 交易明細（{EXIT_NAMES[best['exit']]}，新 → 舊；完整見 [trades.csv](trades.csv)）", "",
          "| 代號 | 交易日 | 申報日 | 延遲 | 進場 | 出場 | 原因 | 報酬 | 同期 SPY |",
          "|---|---|---|---:|---|---|---|---:|---:|"]
    for x in lots[:80]:
        o.append(f"| {x['ticker']} | {x['trade_date']} | {x['filing_date']} | {x['lag_days']}天 "
                 f"| {x['entry_day']} ${x['entry_px']:.2f} | {x['exit_day']} ${x['exit_px']:.2f} "
                 f"| {x['exit_reason']} | {pct(x['ret'])} | {pct(x['spy'])} |")
    if best["skipped"]:
        o += ["", "## 略過的訊號", ""]
        o += [f"- {s['ticker']}（{s['filing_date']}）：{why}" for s, why in best["skipped"][:50]]
    o += ["", "## 限制", "",
          "- 申報只有金額區間，沒有股數；「金額加權」用區間中位數估計。",
          "- 期權改成正股，報酬會遠低於她本人的槓桿部位。",
          "- 2014 年前多為紙本掃描申報，無法自動解析；解析失敗的申報不在樣本內。",
          "- 樣本小（每年約數十筆），結果的統計信心有限；過去績效不代表未來。", ""]
    return "\n".join(o)


if __name__ == "__main__":
    sys.exit(main())
