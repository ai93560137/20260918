"""[R345] 🌌 天覆陣 EURUSD 即日回測（規則版，唔叫 AI）。方案：xau/EURUSD_SIM_PLAN.md（使用者 10-27 批「EURUSD 即日回測」；IDEAS #139）。

使用者 10-27：「EURUSD 暫停 API CALL，暫時只做即日回測模擬」。922 空倉唔再問 Claude（XAU_ACTIVE_HOURS_UTC=00-00）；
呢度每日收市（17:00 UTC）後用當日 1 分鐘 K 線，按 R295 外匯版「倫敦開市區間突破」機械規則回測，令學習樣本唔斷。只係紙上，唔落單。

規則（一次過寫死；改規則要登記 IDEAS）：
1. 開市區間（OR）＝ 07:00–07:30 UTC 高低位（倫敦開市）。
2. 之後第一支 5 分鐘 K 線收市突破 OR 先入場；每日最多 1 張；15:00 UTC 之後唔開新倉。
3. 只順日線方向：昨收 > 20 日均線只做好，< 只做淡（yfinance EURUSD=X 日線）。
4. 止蝕＝OR 另一邊，最少 7 pip（經紀 stops level ≥6＋緩衝＝R340 MODIFY_MIN_DIST）；OR 闊過 25 pip 唔做（區間日）。
5. 浮賺 ≥ 1R 之後止蝕移到開倉價，再跟最近 3 支 5 分鐘 K 線低／高位收緊（只准收緊）。
6. 17:00 UTC 收市平倉；同一支 K 線掂止蝕當止蝕（保守）。
7. 成本每張 1.0 pip（PRODUCT spread_pips）。注碼 0.01 手：1 pip ＝ US$0.10 ≈ HK$0.78。
變體（只記錄）：B＝OR 60 分鐘；C＝OR 闊度 ≥ 前 20 日中位數先做；D＝冇日線過濾（兩邊都可以突破）。

數據：GCS fx/eurusd/bars/<UTC 日>.jsonl（zhuge-eurusd 心跳每根新 M1 存，R345 A1；bar 有 utc 欄）；
冇經紀 K 線嘅日子用 yfinance EURUSD=X 1 分鐘補（--backfill-yf，只回 7 日；寫 fx/eurusd/bars_est/<日>.jsonl，結果標 source=yfinance 估算）。
輸出：fx/eurusd/rulesim/<日>.json、fx/eurusd/rulesim/summary.json。

用法：python3 research/eurusd_rulesim/rulesim.py [--days 7] [--since 2026-10-20] [--backfill-yf] [--dry-run]
"""
import argparse
import json
import math
import statistics
from datetime import date, datetime, time, timedelta, timezone

BUCKET = "zhuge-risk-manager-bucket"
PREFIX = "fx/eurusd/"
PIP = 0.0001
SPEC = {
    "open": time(7, 0), "or_end": time(7, 30), "last_entry": time(15, 0), "close": time(17, 0),
    "cost": 1.0 * PIP,                 # 每張 1 pip（來回合計）
    "min_risk": 7 * PIP, "max_or": 25 * PIP,
    "hkd": lambda pts: pts / PIP * 0.10 * 7.8,   # 0.01 手：1 pip = US$0.10
}
RULES_VERSION = "R345 v1"


def to5(bars):
    """1 分鐘 [(datetime, o, h, l, c)] → 5 分鐘（以開始時間分組）。"""
    out = {}
    for t, o, h, l, c in bars:
        k = t.replace(minute=t.minute // 5 * 5, second=0, microsecond=0)
        x = out.get(k)
        out[k] = [k, o, h, l, c] if x is None else [k, x[1], max(x[2], h), min(x[3], l), c]
    return [tuple(out[k]) for k in sorted(out)]


def run_day(bars1, trend, sp=SPEC, min_or_bars=20, min_or_width=None, allow_both=False):
    """bars1：當日 1 分鐘 K 線 [(datetime UTC, o, h, l, c)]。trend：+1／−1／0。
    回傳 (trade dict 或 None, 原因)。allow_both（變體 D）：trend=0 時兩邊都可以突破，方向跟突破邊。"""
    if not trend and not allow_both:
        return None, "冇日線趨勢數據"
    orb = [b for b in bars1 if sp["open"] <= b[0].time() < sp["or_end"]]
    if len(orb) < min_or_bars:
        return None, "開市區間 K 線唔夠"
    hi, lo = max(b[2] for b in orb), min(b[3] for b in orb)
    if hi - lo > sp["max_or"]:
        return None, f"開市區間太闊（{(hi - lo) / PIP:.1f} pip > {sp['max_or'] / PIP:g}）"
    if min_or_width is not None and hi - lo < min_or_width:
        return None, "開市區間太窄"
    b5 = [b for b in to5([b for b in bars1 if b[0].time() >= sp["or_end"]]) if b[0].time() < sp["close"]]
    entry_i, side = None, 0
    for i, b in enumerate(b5):
        if b[0].time() >= sp["last_entry"]:
            break
        if b[4] > hi and (trend > 0 or (allow_both and trend == 0)):
            entry_i, side = i, 1
            break
        if b[4] < lo and (trend < 0 or (allow_both and trend == 0)):
            entry_i, side = i, -1
            break
    if entry_i is None:
        return None, "冇順日線方向突破"
    entry = b5[entry_i][4]
    stop = lo if side > 0 else hi
    if abs(entry - stop) < sp["min_risk"]:
        stop = entry - side * sp["min_risk"]
    risk = abs(entry - stop)
    exit_px, why, mfe = None, "收市平倉", 0.0
    for j in range(entry_i + 1, len(b5)):
        _, o, h, l, c = b5[j]
        if (side > 0 and l <= stop) or (side < 0 and h >= stop):
            exit_px = min(stop, o) if side > 0 else max(stop, o)          # 跳空過止蝕用開市價
            why = "止蝕" if (stop - entry) * side < 0 else ("保本" if abs(stop - entry) < PIP / 2 else "移動止蝕")
            break
        mfe = max(mfe, ((h - entry) if side > 0 else (entry - l)) / risk)
        if (c - entry) * side >= risk:                                     # 1R 之後先移
            recent = b5[max(entry_i + 1, j - 2):j + 1]
            trail = min(x[3] for x in recent) if side > 0 else max(x[2] for x in recent)
            new = max(trail, entry) if side > 0 else min(trail, entry)
            stop = max(stop, new) if side > 0 else min(stop, new)          # 只准收緊
    if exit_px is None:
        exit_px = b5[-1][4]
    pts = (exit_px - entry) * side - sp["cost"]
    return {"side": side, "entry_t": b5[entry_i][0].strftime("%H:%M"), "entry": round(entry, 5), "exit": round(exit_px, 5),
            "exit_reason": why, "or_hi": round(hi, 5), "or_lo": round(lo, 5), "or_pips": round((hi - lo) / PIP, 1),
            "risk_pips": round(risk / PIP, 1), "pips": round(pts / PIP, 1), "r": round(pts / risk, 3), "mfe_r": round(mfe, 2),
            "hkd": round(sp["hkd"](pts), 2)}, None


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
            "t": round(m / (sd / math.sqrt(n)), 2) if sd else None, "pips": round(sum(x["pips"] for x in rows), 1),
            "hkd": round(sum(x["hkd"] for x in rows), 2), "max_dd_hkd": round(dd, 2), "days": len({x["date"] for x in rows})}


def trend_of(closes, day):
    """closes：{日期: 收市}。昨收 vs 之前 20 日均線（只用 day 之前嘅數據）。"""
    prev = [closes[d] for d in sorted(closes) if d < day][-20:]
    if len(prev) < 20:
        return 0
    return 1 if prev[-1] > sum(prev) / 20 else -1


def or_width(bars1, sp=SPEC):
    orb = [b for b in bars1 if sp["open"] <= b[0].time() < sp["or_end"]]
    return (max(b[2] for b in orb) - min(b[3] for b in orb)) if len(orb) >= 20 else None


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


def broker_bars(store, day):
    """fx/eurusd/bars/<日>.jsonl：list of {time(伺服器), utc, open, high, low, close}。回傳 [(datetime UTC, o, h, l, c)]。"""
    rows = store.get(f"{PREFIX}bars/{day}.jsonl")
    out = []
    for b in rows or []:
        if not isinstance(b, dict) or b.get("utc") is None:
            continue
        t = datetime.fromtimestamp(float(b["utc"]), tz=timezone.utc).replace(tzinfo=None)
        if t.date().isoformat() == day:
            out.append((t, float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])))
    return sorted(out)


def est_bars(store, day):
    rows = store.get(f"{PREFIX}bars_est/{day}.jsonl")
    return sorted((datetime.fromisoformat(b["t"]), b["o"], b["h"], b["l"], b["c"]) for b in rows or [])


def backfill_yf(store, days):
    """yfinance EURUSD=X 1 分鐘（只回 7 日）→ fx/eurusd/bars_est/<日>.jsonl（估算，非經紀價）。只補冇經紀 K 線嘅日子。"""
    import yfinance as yf
    df = yf.download("EURUSD=X", period="7d", interval="1m", progress=False, auto_adjust=False)
    if df is None or df.empty:
        print("yfinance 1 分鐘冇數據")
        return
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df.index = df.index.tz_convert("UTC").tz_localize(None)
    for day in days:
        if len(store.get(f"{PREFIX}bars/{day}.jsonl") or []) >= 300 or store.get(f"{PREFIX}bars_est/{day}.jsonl"):
            continue                                                # [R345d] 經紀 K 線唔夠一日（例如部署日由中途開始）都補 yfinance
        sub = df[df.index.date == date.fromisoformat(day)]
        if len(sub) < 200:
            continue
        rows = [{"t": t.isoformat(), "o": float(r["Open"]), "h": float(r["High"]), "l": float(r["Low"]), "c": float(r["Close"])}
                for t, r in sub.iterrows()]
        store.put(f"{PREFIX}bars_est/{day}.jsonl", rows)
        print(day, "yfinance 補", len(rows), "根（估算）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--since", default="")
    ap.add_argument("--backfill-yf", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    store = Store(a.dry_run)
    today = date.today()
    start = date.fromisoformat(a.since) if a.since else today - timedelta(days=a.days)
    days = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]
    if a.backfill_yf:
        try:
            backfill_yf(store, days)
        except Exception as exc:  # noqa: BLE001
            print("yfinance 補數失敗：", type(exc).__name__, str(exc)[:120])

    import yfinance as yf
    closes = {}
    try:
        hist = yf.download("EURUSD=X", period="6mo", interval="1d", progress=False, auto_adjust=False)
        if hasattr(hist.columns, "levels"):
            hist.columns = [c[0] for c in hist.columns]
        closes = {d.strftime("%Y-%m-%d"): float(v) for d, v in hist["Close"].dropna().items()}
    except Exception as exc:  # noqa: BLE001
        print("yfinance 日線失敗：", type(exc).__name__, str(exc)[:120])

    widths = {}                                                     # 變體 C：前 20 日 OR 闊度中位數
    for name in store.names(f"{PREFIX}rulesim/"):
        doc = store.get(name) if not name.endswith("summary.json") else None
        if doc and doc.get("or_pips") is not None:
            widths[doc["date"]] = doc["or_pips"] * PIP

    for day in days:
        if day >= today.isoformat() and datetime.utcnow().time() < SPEC["close"]:
            continue                                                # 今日未收市唔計
        out = f"{PREFIX}rulesim/{day}.json"
        if store.get(out) and not a.since:
            continue
        bars, source = broker_bars(store, day), "broker"
        if len(bars) < 300:
            bars, source = est_bars(store, day), "yfinance（估算）"
        if len(bars) < 300:
            continue
        trend = trend_of(closes, day)
        trade, why = run_day(bars, trend)
        prev_w = [widths[d] for d in sorted(widths) if d < day][-20:]
        med = statistics.median(prev_w) if len(prev_w) >= 5 else None
        spB = {**SPEC, "or_end": time(8, 0)}
        variants = {
            "B_or60": dict(zip(("trade", "no_trade_reason"), run_day(bars, trend, spB, min_or_bars=40))),
            "C_width": dict(zip(("trade", "no_trade_reason"), run_day(bars, trend, min_or_width=med) if med is not None else (None, "前 20 日數據不足"))),
            "D_no_trend": dict(zip(("trade", "no_trade_reason"), run_day(bars, 0, allow_both=True))),
        }
        w = or_width(bars)
        doc = {"date": day, "source": source, "trend": trend, "or_pips": round(w / PIP, 1) if w is not None else None,
               "trade": trade, "no_trade_reason": why, "variants": variants, "rules": RULES_VERSION}
        store.put(out, doc)
        if w is not None:
            widths[day] = w
        print(day, source, "趨勢", trend, trade and (trade["side"], trade["pips"], trade["exit_reason"]) or why)

    main_rows, var_rows = [], {"B_or60": [], "C_width": [], "D_no_trend": []}
    for name in sorted(store.names(f"{PREFIX}rulesim/")):
        if name.endswith("summary.json"):
            continue
        doc = store.get(name)
        if not doc:
            continue
        if doc.get("trade"):
            main_rows.append({"date": doc["date"], "source": doc.get("source"), **doc["trade"]})
        for k, v in (doc.get("variants") or {}).items():
            if v.get("trade") and k in var_rows:
                var_rows[k].append({"date": doc["date"], **v["trade"]})
    summary = {"updated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "rules": RULES_VERSION,
               "all": stats(main_rows), "variants": {k: stats(v) for k, v in var_rows.items()},
               "recent": main_rows[-30:], "days_scored": len([n for n in store.names(f"{PREFIX}rulesim/") if not n.endswith("summary.json")])}
    store.put(f"{PREFIX}rulesim/summary.json", summary)
    print(json.dumps(summary["all"], ensure_ascii=False))


if __name__ == "__main__":
    main()
