"""[R286] 使用者 34 單「順勢沽空」歸納出嚟嘅方法（刻意貼合，唔怕過度擬合），之後用新數據前向測試。

使用者 10-23：「將我賺錢嘅交易 34 單歸納出一個方法；如果我有指示能否做到正期望值？唔使擔心過度擬合，我哋前向測試。」
34 單其實係大約 11 個決定（同一刻分幾張落）。共通點（R285 研究，成交時區已更正）：
- 日線跌勢（昨日收市低過 20 日均線）；
- 入場時價位已經低過今日開市價（中位數 0.65 個 ATR），而且貼近或跌穿昨日低位；
- 喺下午或者夜市入場（13:00–23:30）；
- 輸單約 100 點（≈ 0.35 ATR）就走；贏單揸過夜，平均揸 17–73 個鐘，賺 250–970 點。

方法 A（全自動，規則寫死，2026-10-23 起凍結）：
- 時段：日市 13:00–16:00、夜市 17:15–23:30（按 5 分鐘收市價判斷）；每個交易日最多一次，有倉唔開。
- 條件：日線跌勢；價 ≤ 今日日市開市價 − 0.30 ATR；價 ≤ 昨日日市低位 + 0.25 ATR → 沽空。
- 止蝕：入場 + 0.35 ATR。浮賺去到 0.5 ATR 之後，止蝕改為「最低位 + 0.5 ATR」同開倉價較低者（只收緊）。
- 最多揸到第 3 個交易日日市收市。每邊成本 2 點。
方法 B（使用者指示 + 系統管理）：用使用者自己嘅入場時間、價位、方向，出場改用方法 A 嘅止蝕／移動止蝕／3 日上限，
同使用者實際平倉比較：答「如果你畀指示，系統管理出場，期望值係咪正」。

ATR＝最近 14 個交易日日市（高 − 低）平均。數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，含夜市）。
用法：python3 research/longfei_lessons/user_method.py --bars hsi_1m.json [--pnl futu_pnl.json] [--since 2026-10-23] [--out 報告.md] [--json 結果.json]
前向測試（每日 workflow longfei_user_method.yml）：python3 research/longfei_lessons/user_method.py --gcs --since 2026-10-23
  → GCS ops/longfei/user_method/forward.md／forward.json（私人）
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COST = 2.0
ENTRY_OPEN_ATR = 0.30
ENTRY_PDL_ATR = 0.25
STOP_ATR = 0.35
TRAIL_START_ATR = 0.5
TRAIL_ATR = 0.5
MAX_DAYS = 3
WINDOWS = ((time(13, 0), time(16, 0)), (time(17, 15), time(23, 30)))
FROZEN = "2026-10-23"


def session_date(t):
    """港期：00:00–03:00 夜市屬前一日；其餘屬當日。"""
    return (t - timedelta(days=1)).date() if t.hour < 9 else t.date()


def load(raw):
    """{日期: [{time_key, open, high, low, close}]} → 按時間排序嘅 [(datetime, o, h, l, c)]（去重）。"""
    seen, out = set(), []
    for rows in raw.values():
        for r in rows:
            k = r["time_key"]
            if k in seen:
                continue
            seen.add(k)
            out.append((datetime.strptime(k, "%Y-%m-%d %H:%M:%S"), r["open"], r["high"], r["low"], r["close"]))
    return sorted(out)


def daily(bars):
    """交易日 → 日市開、高、低、收（09:15–16:30）。"""
    d = {}
    for t, o, h, lo, c in bars:
        if not (time(9, 15) <= t.time() < time(16, 30)):
            continue
        x = d.setdefault(t.date(), {"open": o, "high": h, "low": lo, "close": c})
        x["high"], x["low"], x["close"] = max(x["high"], h), min(x["low"], lo), c
    keys = sorted(d)
    ctx = {}
    for i, k in enumerate(keys):
        if i < 20:
            continue
        prev = [d[j] for j in keys[i - 20:i]]
        ctx[k] = {"open": d[k]["open"], "pdl": prev[-1]["low"], "pdc": prev[-1]["close"],
                  "sma": sum(p["close"] for p in prev) / 20,
                  "atr": sum(p["high"] - p["low"] for p in prev[-14:]) / 14}
    return keys, ctx


def manage(bars, start, side, entry, atr, keys):
    """由 bars[start] 之後開始管理；回傳 (出場價, 出場時間)。"""
    stop = entry - side * STOP_ATR * atr
    best = entry
    d0 = session_date(bars[start][0])
    idx = keys.index(d0) if d0 in keys else None
    last_day = keys[min(len(keys) - 1, idx + MAX_DAYS - 1)] if idx is not None else d0
    for t, o, h, lo, c in bars[start + 1:]:
        if (side < 0 and h >= stop) or (side > 0 and lo <= stop):
            return (max(stop, o) if side < 0 else min(stop, o)), t
        best = min(best, lo) if side < 0 else max(best, h)
        if (best - entry) * side >= TRAIL_START_ATR * atr:              # 浮賺夠 0.5 ATR 先開始移動止蝕
            trail = best - side * TRAIL_ATR * atr
            trail = min(trail, entry) if side < 0 else max(trail, entry)
            stop = min(stop, trail) if side < 0 else max(stop, trail)
        if session_date(t) >= last_day and time(16, 29) <= t.time() < time(17, 0):   # 第 3 日日市收市平
            return c, t
    return bars[-1][4], bars[-1][0]


def method_a(bars, keys, ctx, since=None):
    trades, busy_until, done = [], None, set()
    for i, (t, o, h, lo, c) in enumerate(bars):
        if t.minute % 5 != 4:                       # 5 分鐘收市（第 5 支 1 分鐘）
            continue
        if not any(a <= t.time() < b for a, b in WINDOWS):
            continue
        sd = session_date(t)
        x = ctx.get(sd)
        if not x or sd in done or (busy_until and t <= busy_until) or (since and sd.isoformat() < since):
            continue
        if not (x["pdc"] < x["sma"] and c <= x["open"] - ENTRY_OPEN_ATR * x["atr"] and c <= x["pdl"] + ENTRY_PDL_ATR * x["atr"]):
            continue
        done.add(sd)
        px, t_out = manage(bars, i, -1, c, x["atr"], keys)
        busy_until = t_out
        pts = (c - px) - 2 * COST
        trades.append({"entry_t": t.strftime("%Y-%m-%d %H:%M"), "exit_t": t_out.strftime("%Y-%m-%d %H:%M"), "side": -1,
                       "entry": c, "exit": px, "pts": round(pts, 1), "r": round(pts / (STOP_ATR * x["atr"]), 3),
                       "hkd_per_hsi": round(pts * 50)})
    return trades


def method_b(bars, keys, ctx, pnl_doc, since=None):
    """使用者每個 HSI／MHI 期貨入場決定（同一分鐘同方向當一個），出場改用方法 A 規則。"""
    from user_trades import round_trips
    seen, out = set(), []
    idx = {b[0]: i for i, b in enumerate(bars)}
    for tr in round_trips(pnl_doc):
        if not re.match(r"^HK\.(HSI|MHI)\d{4}$", tr["code"]):          # 只計期貨，唔計期權
            continue
        key = (tr["open_t"].strftime("%Y-%m-%d %H:%M"), tr["side"])
        if key in seen or (since and session_date(tr["open_t"]).isoformat() < since):
            continue
        seen.add(key)
        t = tr["open_t"].replace(second=0, microsecond=0)
        x = ctx.get(session_date(t))
        if t not in idx or not x:
            continue
        px, t_out = manage(bars, idx[t], tr["side"], tr["open_px"], x["atr"], keys)
        managed = (px - tr["open_px"]) * tr["side"] - 2 * COST
        out.append({"entry_t": key[0], "side": tr["side"], "actual_pts": round(tr["pts"] - 2 * COST, 1),
                    "managed_pts": round(managed, 1), "exit_t": t_out.strftime("%Y-%m-%d %H:%M")})
    return out


def stats(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in xs) / (n - 1))
    w, l = [v for v in xs if v > 0], [-v for v in xs if v < 0]
    return {"n": n, "avg": m, "sum": sum(xs), "win": len(w) / n, "pf": (sum(w) / sum(l)) if l else None,
            "t": (m / (sd / math.sqrt(n))) if sd else None}


def line(name, xs, unit="點"):
    s = stats(xs)
    if not s:
        return f"| {name} | {len(xs)} | — | — | — | — | — |"
    pf = "—" if s["pf"] is None else f"{s['pf']:.2f}"
    t = "—" if s["t"] is None else f"{s['t']:.2f}"
    return f"| {name} | {s['n']} | {s['win']:.0%} | {s['avg']:+.1f} {unit} | {s['sum']:+,.0f} {unit} | {pf} | {t} |"


def report(a, b, first, last, since):
    L = [f"# 🐉 使用者方法（R286）{'前向測試（' + since + ' 起）' if since else '貼合檢查'}：{first} 至 {last}\n",
         "恒指期貨 1 分鐘 K 線（含夜市）；每邊成本 2 點；點數係每張扣成本後。方法 A 規則見腳本檔頭，2026-10-23 凍結。\n",
         "| 版本 | 筆數 | 勝率 | 每筆平均 | 合計 | 獲利因子 | t 值 |", "|---|---:|---:|---:|---:|---:|---:|",
         line("方法 A：全自動順勢沽空", [x["pts"] for x in a])]
    if b:
        L += [line("方法 B：使用者入場＋系統管理出場", [x["managed_pts"] for x in b]),
              line("對照：使用者入場＋使用者自己平倉", [x["actual_pts"] for x in b]),
              line("方法 B 只計做淡", [x["managed_pts"] for x in b if x["side"] < 0]),
              line("方法 B 只計做好", [x["managed_pts"] for x in b if x["side"] > 0])]
    if a:
        L += ["\n## 方法 A 逐筆\n", "| 入場 | 出場 | 入場價 | 出場價 | 點數 | R |", "|---|---|---:|---:|---:|---:|"]
        L += [f"| {x['entry_t']} | {x['exit_t']} | {x['entry']:.0f} | {x['exit']:.0f} | {x['pts']:+.0f} | {x['r']:+.2f} |" for x in a]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", default="", help="本機 1 分鐘 K 線 JSON；用 --gcs 就唔使")
    ap.add_argument("--pnl", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--gcs", action="store_true", help="由 GCS 讀 1 分鐘 K 線同使用者成交，結果寫返 GCS（每日 workflow 用）")
    a = ap.parse_args()
    if a.gcs:
        raw, pnl = gcs_load()
    elif not a.bars:
        ap.error("要 --bars 或者 --gcs")
    else:
        raw, pnl = json.load(open(a.bars)), (json.load(open(a.pnl)) if a.pnl else None)
    bars = load(raw)
    keys, ctx = daily(bars)
    ta = method_a(bars, keys, ctx, a.since or None)
    tb = method_b(bars, keys, ctx, pnl, a.since or None) if pnl else []
    text = report(ta, tb, bars[0][0].date(), bars[-1][0].date(), a.since)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
    doc = {"frozen": FROZEN, "since": a.since, "last_bar": bars[-1][0].strftime("%Y-%m-%d %H:%M"),
           "method_a": ta, "summary_a": stats([x["pts"] for x in ta]),
           "method_b": tb, "summary_b": stats([x["managed_pts"] for x in tb]),
           "summary_b_actual": stats([x["actual_pts"] for x in tb])}
    if a.json:
        json.dump(doc, open(a.json, "w"), ensure_ascii=False, indent=1)
    if a.gcs:
        gcs_save(text, doc)
    print(text)


GCS_BUCKET = "zhuge-risk-manager-bucket"
GCS_BARS = "archive/futu_k_1m/HK.HSI_FRONT/"
GCS_OUT = "ops/longfei/user_method/"          # 私人（方法 B 有使用者成交點數）


def gcs_load():
    from google.cloud import storage
    b = storage.Client().bucket(GCS_BUCKET)
    raw = {x.name.rsplit("/", 1)[1][:10]: json.loads(x.download_as_bytes()) for x in b.list_blobs(prefix=GCS_BARS)}
    pnl = json.loads(b.blob("futu/pnl/latest.json").download_as_bytes())
    return raw, pnl


def gcs_save(text, doc):
    from google.cloud import storage
    b = storage.Client().bucket(GCS_BUCKET)
    b.blob(GCS_OUT + "forward.md").upload_from_string(text, content_type="text/markdown; charset=utf-8")
    b.blob(GCS_OUT + "forward.json").upload_from_string(json.dumps(doc, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
