"""[R268] 龍飛陣教學研究：使用者富途成交（futu/pnl/latest.json 嘅 deals）FIFO 配對成一筆筆平倉，搵賺錢單有咩共通點。

用 main.py 同一套配對（按合約 FIFO）；成交時間：期貨戶口已經係香港時間、證券戶口美股係美東時間（10-22 更正，之前錯當 UTC +8）同產品每點價值（main.FUTU_PRODUCTS）。
每筆記：產品、方向、開／平倉時間、持倉時間、點數、盈虧（港幣，美元 × 7.8，未扣費）。
再用 15 分鐘 K 線（HSI 富途存檔、標普／納指 Dukascopy）睇開倉嗰刻係咪順當日走勢（價 vs 當日開市價）。

報告含真金額，只存私人 GCS（ops/longfei/research/），唔 commit 入公開 repo。

用法：python3 research/longfei_lessons/user_trades.py --pnl futu_pnl.json [--hsi hsi_15m.json --spx … --ndx …] --out 報告.md
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bars import ET, load_dukascopy, load_hsi  # noqa: E402

HKT = ZoneInfo("Asia/Hong_Kong")
USD_HKD = 7.8
PRODUCTS = (   # 同 main.py FUTU_PRODUCTS（呢度唔 import main，免得要齊 Cloud Run 套件）
    (r"^HK\.MHI\d{4}$", "MHI 小型恒指期貨", 10, "HSI"),
    (r"^HK\.HSI\d{4}$", "HSI 恒指期貨", 50, "HSI"),
    (r"^HK\.MHI\d{6}[CP]\d+$", "MHI 小型恒指期權", 10, None),
    (r"^HK\.HSI\d{6}[CP]\d+$", "HSI 恒指期權", 50, None),
    (r"^US\.EX\d{5}[CP]\d+x\d$", "MES 微型標普週期權", 5, None),
    (r"^US\.EW\d{4}[CP]\d+x\d$", "ES 標普月底期權", 50, None),
    (r"^US\.MES\d{4}$", "MES 微型標普期貨", 5, "SPX"),
    (r"^US\.ES\d{4}$", "ES 標普期貨", 50, "SPX"),
    (r"^US\.MNQ\d{4}$", "MNQ 微型納指期貨", 2, "NDX"),
    (r"^US\.NQ\d{4}$", "NQ 納指期貨", 20, "NDX"),
    (r"^US\.[A-Z]+\d{6}[CP]\d+$", "美股期權", 100, None),
    (r"^US\.[A-Z.]+$", "美股", 1, None),
)


def product(code):
    for rx, name, mult, idx in PRODUCTS:
        if re.match(rx, code):
            return name, mult, idx
    return "其他", 1, None


def deal_time_hkt(d):
    """富途成交時間：期貨戶口已經係香港時間；證券戶口嘅美股係美東時間（10-22 對過：HSI 夜市 00:21、SPY 09:50＝香港 21:50）。"""
    t = datetime.strptime(str(d["time"])[:19], "%Y-%m-%d %H:%M:%S")
    if "證券" in str(d.get("account", "")) and str(d.get("code", "")).startswith("US."):
        return t.replace(tzinfo=ET).astimezone(HKT).replace(tzinfo=None)
    return t


def round_trips(doc):
    deals = []
    for d in doc.get("deals") or []:
        try:
            t = deal_time_hkt(d)
            q, px = abs(float(d["qty"])), float(d["price"])
        except (KeyError, ValueError, TypeError):
            continue
        sign = 1 if str(d.get("side", "")).upper() in ("BUY", "BUY_BACK") else -1
        deals.append((t, str(d["code"]), sign, q, px))
    deals.sort()
    lots, out = {}, []
    for t, code, sign, q, px in deals:
        book = lots.setdefault(code, [])
        while q > 1e-9 and book and book[0][0] == -sign:
            lot = book[0]
            take = min(q, lot[1])
            name, mult, idx = product(code)
            pts = (px - lot[2]) * lot[0]
            hkd = pts * take * mult * (USD_HKD if code.startswith("US.") else 1)
            out.append({"code": code, "product": name, "index": idx, "side": lot[0], "qty": take,
                        "open_t": lot[3], "close_t": t, "open_px": lot[2], "close_px": px, "pts": pts, "hkd": hkd,
                        "hold_min": (t - lot[3]).total_seconds() / 60})
            lot[1] -= take
            q -= take
            if lot[1] <= 1e-9:
                book.pop(0)
        if q > 1e-9:
            book.append([sign, q, px, t])
    return out


def add_context(trips, days_by_index):
    """開倉嗰刻：價 vs 當日開市價（順／逆當日走勢）、日線方向（昨收 vs 20 日均線）。冇 K 線就留空。"""
    for tr in trips:
        days = days_by_index.get(tr["index"])
        tr["intraday"] = tr["daily"] = None
        if not days:
            continue
        t = tr["open_t"]
        local = t if tr["index"] == "HSI" else t.replace(tzinfo=HKT).astimezone(ET).replace(tzinfo=None)   # 美股用美東
        key = local.date().isoformat()
        bars = days.get(key)
        keys = sorted(days)
        if not bars or keys.index(key) < 20:
            continue
        before = [b for b in bars if b[0] <= local]
        if not before:
            continue
        px = before[-1][4]
        tr["intraday"] = 1 if px > bars[0][1] else -1
        i = keys.index(key)
        closes = [days[k][-1][4] for k in keys[i - 20:i]]
        tr["daily"] = 1 if closes[-1] > sum(closes) / 20 else -1


def stats(xs):
    n = len(xs)
    if not n:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0
    w, lo = [x for x in xs if x > 0], [-x for x in xs if x < 0]
    return {"n": n, "sum": sum(xs), "avg": m, "win": len(w) / n, "pf": sum(w) / sum(lo) if lo else None,
            "t": m / (sd / math.sqrt(n)) if sd else None,
            "avg_win": sum(w) / len(w) if w else None, "avg_loss": -sum(lo) / len(lo) if lo else None}


def table(title, groups):
    L = [f"\n### {title}\n", "| 分組 | 筆數 | 勝率 | 合計 HK$ | 每筆 HK$ | 平均贏 | 平均輸 | 獲利因子 | t |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, xs in groups:
        s = stats(xs)
        if not s:
            continue
        aw = "—" if s["avg_win"] is None else f"{s['avg_win']:,.0f}"
        al = "—" if s["avg_loss"] is None else f"{s['avg_loss']:,.0f}"
        pf = "—" if s["pf"] is None else f"{s['pf']:.2f}"
        t = "—" if s["t"] is None else f"{s['t']:.2f}"
        L.append(f"| {name} | {s['n']} | {s['win']:.0%} | {s['sum']:+,.0f} | {s['avg']:+,.0f} | {aw} | {al} | {pf} | {t} |")
    return L


def hold_bucket(m):
    return "≤ 15 分鐘" if m <= 15 else "15–60 分鐘" if m <= 60 else "1–4 小時" if m <= 240 else "4 小時–1 日" if m <= 1440 else "> 1 日"


def session(tr):
    h = tr["open_t"].hour + tr["open_t"].minute / 60
    if tr["code"].startswith("HK."):
        return "港期日市上午" if 9.25 <= h < 12 else "港期日市下午" if 13 <= h < 16.5 else "港期夜市"
    return "美股開市後 2 小時" if 21.5 <= h < 23.5 else "美股其餘正常時段" if (h >= 23.5 or h < 4) else "美股盤前／盤後"


def report(trips):
    fut = [t for t in trips if t["index"]]
    L = ["# 🐉 使用者富途成交分析（私人，R268）\n",
         f"FIFO 配對 {len(trips)} 筆平倉（{min(t['close_t'] for t in trips):%Y-%m-%d} 至 {max(t['close_t'] for t in trips):%Y-%m-%d}），"
         "盈虧未扣費、美元 × 7.8。期權同期貨分開睇；「順／逆當日走勢」只計有 K 線嘅期貨（K 線到 10-03）。\n"]
    L += table("按產品", sorted(((p, [t["hkd"] for t in trips if t["product"] == p]) for p in {t["product"] for t in trips}),
                                key=lambda g: -len(g[1])))
    L += table("期貨：方向", [("做好", [t["hkd"] for t in fut if t["side"] > 0]), ("做淡", [t["hkd"] for t in fut if t["side"] < 0])])
    L += table("期貨：持倉時間", [(b, [t["hkd"] for t in fut if hold_bucket(t["hold_min"]) == b])
                              for b in ("≤ 15 分鐘", "15–60 分鐘", "1–4 小時", "4 小時–1 日", "> 1 日")])
    L += table("期貨：開倉時段（香港時間）", [(s, [t["hkd"] for t in fut if session(t) == s])
                                       for s in ("港期日市上午", "港期日市下午", "港期夜市", "美股開市後 2 小時", "美股其餘正常時段", "美股盤前／盤後")])
    ctx = [t for t in fut if t["intraday"] is not None]
    L += table(f"期貨：開倉嗰刻順／逆當日走勢（有 K 線嘅 {len(ctx)} 筆）",
               [("順當日走勢", [t["hkd"] for t in ctx if t["side"] == t["intraday"]]),
                ("逆當日走勢", [t["hkd"] for t in ctx if t["side"] != t["intraday"]]),
                ("順日線方向", [t["hkd"] for t in ctx if t["side"] == t["daily"]]),
                ("逆日線方向", [t["hkd"] for t in ctx if t["side"] != t["daily"]]),
                ("做淡・逆當日走勢", [t["hkd"] for t in ctx if t["side"] < 0 and t["intraday"] > 0]),
                ("做淡・順當日走勢", [t["hkd"] for t in ctx if t["side"] < 0 and t["intraday"] < 0])])
    best = sorted(trips, key=lambda t: -t["hkd"])[:10]
    L += ["\n### 賺得最多 10 筆\n", "| 產品 | 方向 | 開倉（香港） | 持倉 | 點數 | HK$ |", "|---|---|---|---:|---:|---:|"]
    L += [f"| {t['product']} | {'好' if t['side'] > 0 else '淡'} | {t['open_t']:%m-%d %H:%M} | {t['hold_min']:.0f} 分鐘 | "
          f"{t['pts']:+.2f} | {t['hkd']:+,.0f} |" for t in best]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pnl", required=True)
    ap.add_argument("--hsi")
    ap.add_argument("--spx")
    ap.add_argument("--ndx")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    trips = round_trips(json.load(open(a.pnl)))
    days = {}
    if a.hsi:
        days["HSI"] = load_hsi(a.hsi)
    if a.spx:
        days["SPX"] = load_dukascopy(a.spx)
    if a.ndx:
        days["NDX"] = load_dukascopy(a.ndx)
    add_context(trips, days)
    text = report(trips)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
