"""[R295] 龍飛陣即日回測（規則版，唔用 AI）。

使用者 10-26：「模擬唔再用 api call，改為即日回測」（經總指揮轉達，使用者批「做」）。
24 隻模擬產品停叫 Claude（VM LONGFEI_SIM_AI=0），改為每日收市後用當日 1 分鐘 K 線，按教學簿規則嘅機械版回測，令學習樣本唔斷。

規則（教學簿機械版，一次過寫死；改規則要登記 IDEAS）：
1. 開市區間（OR）＝ 頭 30 分鐘高低位（美股 09:30–10:00 美東；HSI 日市 09:15–09:45 香港）。
2. 之後第一支 5 分鐘 K 線收市突破 OR 先入場，每日每隻最多 1 張。
3. 只順日線方向做：昨收 > 20 日均線只做好，< 只做淡（R280 美股日線升勢唔沽空、R293 恒指日線跌勢唔做好）。
4. 美股 15:30 美東之後、HSI 16:00 香港之後唔開新倉（R246：尾段唔追）。
5. 止蝕＝OR 另一邊，最少 HSI 30 點／美股 0.15%；浮賺 ≥ 1R 之後止蝕移到開倉價，再跟最近 3 支 5 分鐘 K 線高／低位收緊（只准收緊，R269）。
6. 收市平倉（美股 15:59、HSI 16:29），HSI 夜市唔計。同一支 K 線掂止蝕當止蝕（保守）。
7. 成本每邊：HSI 2 點、美股 0.015%。

數據：美股 1 分鐘 K 線 GCS longfei/bars/<產品>/<日>.json（VM bars_archive.py 每日 08:10 HKT 上載，美東時間）；
HSI 用 archive/futu_k_1m/HK.HSI_FRONT/<日>.json（香港時間）。日線趨勢：美股 yfinance 日線；HSI 由 1 分鐘存檔日市收市計。
輸出：GCS longfei/rulesim/<產品>/<日>.json（當日結果）同 longfei/rulesim/summary.json（累計）。只係紙上回測，唔落單。

用法：python3 research/longfei_rulesim/rulesim.py [--days 7] [--since 2026-10-14] [--dry-run]
"""
import argparse
import json
import math
from datetime import date, datetime, time, timedelta

BUCKET = "zhuge-risk-manager-bucket"
US = ["SPY", "QQQ", "DIA", "TLT", "HYG", "GLD", "USO", "IWM", "EWJ", "FXI", "EWT", "INDA", "EZU", "EWU", "EWZ",
      "EWC", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]
SPEC = {
    "US": {"open": time(9, 30), "or_end": time(10, 0), "last_entry": time(15, 30), "close": time(15, 59),
           "cost": lambda px: px * 0.00015, "min_risk": lambda px: px * 0.0015,
           "hkd": lambda pts, px: pts / px * 100_000 * 7.8},          # 名義 US$100,000（模擬原本注碼）
    "HSI": {"open": time(9, 15), "or_end": time(9, 45), "last_entry": time(16, 0), "close": time(16, 29),
            "cost": lambda px: 2.0, "min_risk": lambda px: 30.0,
            "hkd": lambda pts, px: pts * 50},                          # 1 張大期
}
LUNCH = (time(12, 0), time(13, 0))


def to5(bars):
    """1 分鐘 [(datetime, o, h, l, c)] → 5 分鐘（以開始時間分組）。"""
    out = {}
    for t, o, h, l, c in bars:
        k = t.replace(minute=t.minute // 5 * 5, second=0)
        x = out.get(k)
        out[k] = [k, o, h, l, c] if x is None else [k, x[1], max(x[2], h), min(x[3], l), c]
    return [tuple(out[k]) for k in sorted(out)]


def run_day(bars1, trend, sp, min_or_bars=10, first_entry=None, min_or_width=None):
    """bars1：當日正常時段 1 分鐘 K 線（交易所當地時間）。trend：+1／−1／0（冇數據唔做）。回傳 trade dict 或 None 同原因。
    [IDEAS #130] 樣本外檢查用：min_or_bars（5 分鐘數據用 6）、first_entry（幾點前唔入場）、min_or_width（OR 窄過呢個唔做）。預設＝R295 v1。"""
    if not trend:
        return None, "冇日線趨勢數據"
    orb = [b for b in bars1 if sp["open"] <= b[0].time() < sp["or_end"]]
    if len(orb) < min_or_bars:
        return None, "開市區間 K 線唔夠"
    hi, lo = max(b[2] for b in orb), min(b[3] for b in orb)
    if min_or_width is not None and hi - lo < min_or_width:
        return None, "開市區間太窄"
    b5 = [b for b in to5([b for b in bars1 if b[0].time() >= sp["or_end"]]) if b[0].time() <= sp["close"]]
    entry_i = None
    for i, b in enumerate(b5):
        if b[0].time() >= sp["last_entry"]:
            break
        if first_entry and b[0].time() < first_entry:
            continue
        if (trend > 0 and b[4] > hi) or (trend < 0 and b[4] < lo):
            entry_i = i
            break
    if entry_i is None:
        return None, "冇順日線方向突破"
    side, entry = trend, b5[entry_i][4]
    stop = lo if side > 0 else hi
    if abs(entry - stop) < sp["min_risk"](entry):
        stop = entry - side * sp["min_risk"](entry)
    risk = abs(entry - stop)
    exit_px, why, mfe = None, "收市平倉", 0.0
    for j in range(entry_i + 1, len(b5)):
        _, o, h, l, c = b5[j]
        if (side > 0 and l <= stop) or (side < 0 and h >= stop):
            exit_px = min(stop, o) if side > 0 else max(stop, o)          # 跳空過止蝕用開市價
            why = "止蝕"
            break
        mfe = max(mfe, ((h - entry) if side > 0 else (entry - l)) / risk)
        if (c - entry) * side >= risk:                                     # 1R 之後先移
            recent = b5[max(entry_i + 1, j - 2):j + 1]
            trail = min(x[3] for x in recent) if side > 0 else max(x[2] for x in recent)
            new = max(trail, entry) if side > 0 else min(trail, entry)
            stop = max(stop, new) if side > 0 else min(stop, new)          # 只准收緊
    if exit_px is None:
        exit_px = b5[-1][4]
    cost = 2 * sp["cost"](entry)
    pts = (exit_px - entry) * side - cost
    return {"side": side, "entry_t": b5[entry_i][0].strftime("%H:%M"), "entry": round(entry, 4),
            "exit": round(exit_px, 4), "exit_reason": why, "or_hi": hi, "or_lo": lo, "risk": round(risk, 4),
            "pts": round(pts, 4), "r": round(pts / risk, 3), "mfe_r": round(mfe, 2),
            "hkd": round(sp["hkd"](pts, entry), 0)}, None


def stats(rows):
    rs = [x["r"] for x in rows]
    n = len(rs)
    if not n:
        return {"n": 0}
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1)) if n > 1 else 0
    w, l = [x for x in rs if x > 0], [-x for x in rs if x < 0]
    eq = peak = dd = 0.0
    for x in rows:
        eq += x["hkd"]
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"n": n, "win": round(len(w) / n, 3), "avg_r": round(m, 3), "pf": round(sum(w) / sum(l), 2) if l else None,
            "t": round(m / (sd / math.sqrt(n)), 2) if sd else None, "hkd": round(sum(x["hkd"] for x in rows)),
            "max_dd_hkd": round(dd), "days": len({x["date"] for x in rows})}


# ---------- 數據 ----------
class Store:
    def __init__(self, dry):
        from google.cloud import storage
        self.b = storage.Client().bucket(BUCKET)
        self.dry = dry

    def get(self, name):
        blob = self.b.blob(name)
        return json.loads(blob.download_as_text()) if blob.exists() else None

    def put(self, name, doc):
        if self.dry:
            print("（dry-run）", name)
            return
        self.b.blob(name).upload_from_string(json.dumps(doc, ensure_ascii=False), content_type="application/json")

    def names(self, prefix):
        return [b.name for b in self.b.list_blobs(prefix=prefix)]


def us_bars(store, prod, day):
    doc = store.get(f"longfei/bars/{prod}/{day}.json")
    if not doc:
        return None
    rows = []
    for t, o, h, l, c, *_ in doc["bars"]:
        dt = datetime.combine(date.fromisoformat(day), datetime.strptime(t, "%H:%M").time())
        if SPEC["US"]["open"] <= dt.time() <= SPEC["US"]["close"]:
            rows.append((dt, o, h, l, c))
    return rows


def hsi_bars(store, day):
    raw = store.get(f"archive/futu_k_1m/HK.HSI_FRONT/{day}.json")
    if not raw:
        return None
    rows = []
    for b in raw:
        t = datetime.strptime(b["time_key"], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=1)   # time_key 係完結時間
        if t.date().isoformat() == day and SPEC["HSI"]["open"] <= t.time() <= SPEC["HSI"]["close"] \
                and not (LUNCH[0] <= t.time() < LUNCH[1]):
            rows.append((t, b["open"], b["high"], b["low"], b["close"]))
    return sorted(rows)


def us_trend(closes, day):
    """closes：{日期: 收市}。昨收 vs 之前 20 日均線（只用 day 之前嘅數據）。"""
    prev = [closes[d] for d in sorted(closes) if d < day][-20:]
    if len(prev) < 20:
        return 0
    return 1 if prev[-1] > sum(prev) / 20 else -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="檢查最近幾日有冇未回測嘅數據")
    ap.add_argument("--since", default="", help="由呢日起補回測（例如 2026-10-14）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    store = Store(a.dry_run)
    today = date.today()
    start = date.fromisoformat(a.since) if a.since else today - timedelta(days=a.days)
    days = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5]

    import yfinance as yf
    closes = {}
    hist = yf.download(US, period="6mo", interval="1d", progress=False, auto_adjust=False, group_by="ticker")
    for p in US:
        try:
            s = hist[p]["Close"].dropna()
            closes[p] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
        except KeyError:
            closes[p] = {}
    hsi_close = {}
    for d0 in [(start - timedelta(days=i)).isoformat() for i in range(1, 45)] + days:
        rows = hsi_bars(store, d0)
        if rows:
            hsi_close[d0] = rows[-1][4]

    for day in days:
        for prod in ["HSI"] + US:
            out = f"longfei/rulesim/{prod}/{day}.json"
            if store.get(out) and not a.since:
                continue
            if prod == "HSI":
                bars, sp, trend = hsi_bars(store, day), SPEC["HSI"], us_trend(hsi_close, day)
            else:
                bars, sp, trend = us_bars(store, prod, day), SPEC["US"], us_trend(closes.get(prod, {}), day)
            if not bars:
                continue
            trade, why = run_day(bars, trend, sp)
            store.put(out, {"date": day, "product": prod, "trend": trend, "trade": trade, "no_trade_reason": why,
                            "rules": "R295 v1"})
            print(day, prod, "趨勢", trend, trade and (trade["side"], trade["r"], trade["exit_reason"]) or why)

    trades = []
    for name in store.names("longfei/rulesim/"):
        if name.endswith("summary.json"):
            continue
        doc = store.get(name)
        if doc and doc.get("trade"):
            trades.append({"date": doc["date"], "product": doc["product"], **doc["trade"]})
    trades.sort(key=lambda x: (x["date"], x["product"]))
    by = {}
    for x in trades:
        by.setdefault(x["product"], []).append(x)
    summary = {"updated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "rules": "R295 v1",
               "all": stats(trades), "by_product": {p: stats(v) for p, v in sorted(by.items())},
               "recent": trades[-30:]}
    store.put("longfei/rulesim/summary.json", summary)
    print(json.dumps(summary["all"], ensure_ascii=False))


if __name__ == "__main__":
    main()
