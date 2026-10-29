"""[IDEAS #148] Gold Brother（0342）跟單規則回測：F11（10-29 BUY 追價止損 −1R）之後，使用者問「F11 如何避免？同我回測」。

資料：
  訊號：GCS xau/sig/history/2249680342_*.json（頻道歷史 7–10 月，已解析 new_signal：方向、入場區、SL、TP1–4）＋ xau/sig/signals/recent.json。
  價格：yfinance GC=F（COMEX 黃金期貨）5 分鐘（只回 60 日）或 1 分鐘（只回 7 日）。期貨同 CFD 現貨有基差，所以**每張訊號各自校正**：
        offset＝訊號所在 K 線開盤 − 入場區中位，之後 SL／TP 全部加 offset 再對期貨 K 線計。即係假設訊號時現價＝入場中位（0342 訊號幾乎全部「現價入場」），
        只量度訊號之後嘅路徑；基差日內漂移 1–2 美元係噪音（SL 20、TP 步距 5）。
  規則同 xau/follower.py 一致：市價成交、伺服器 SL／TP4、每根 K 線收市價到 TP(k) 就鎖（TP1→保本、TP2→鎖 TP1…），SL／TP4 用影線；同一根 K 線先當 SL（保守，同 signals.evaluate 一致）。
變體（預先登記喺 IDEAS #148）：V0 基準；V1 SL 上限；V2 唔追（訊號前 30 分鐘順向先行 ≥X 略過）；V3 時間止損；V4 鎖晚一級；V5 唔鎖 TP2 全平；V6 TP1 全平；V7 回調限價；V8 MAE 止損；V9 V4＋V8。
輸出：GCS xau/sig/gb_rulesim/<run_utc>.json ＋ latest.json ＋ latest.md（Actions 日誌亦印）。純函數部分有 tests/test_gb_rulesim.py。只係紙上研究，唔落單。"""
import argparse
import datetime as dt
import json
import time

BUCKET = "zhuge-risk-manager-bucket"
HIST_PREFIX = "xau/sig/history/2249680342_"
RECENT = "xau/sig/signals/recent.json"
OUT_PREFIX = "xau/sig/gb_rulesim/"
CH = "0342"
DEFAULT_CHANNEL = "2249680342"     # [使用者 10-29「黃金戰鬥機做回測同 gold brother 一樣」] --channel 1473735117＝黃金戰鬥機（5117）
MAX_HOLD_MIN = 24 * 60
FILL_TTL_MIN = 30

VARIANTS = {
    "V0": {"name": "基準（市價、TP1→保本、逐級鎖）", "kw": {}},
    "V1": {"name": "SL 上限 10 美元", "kw": {"sl_cap": 10}},
    "V2": {"name": "唔追：訊號前 30 分鐘順向先行 ≥15 略過", "kw": {"chase": 15}},
    "V3": {"name": "時間止損：30 分鐘未到 TP1 且浮虧→走", "kw": {"time_stop": 30}},
    "V4": {"name": "鎖晚一級：TP2 先保本、TP3 鎖 TP1", "kw": {"lock": "tp2_be"}},
    "V5": {"name": "唔鎖、TP2 全平", "kw": {"lock": "tp2_flat"}},
    "V6": {"name": "TP1 全平（CTC 式）", "kw": {"lock": "tp1_flat"}},
    "V7": {"name": "回調限價：等入場區好邊，30 分鐘未到略過", "kw": {"entry": "pullback"}},
    "V8": {"name": "MAE 止損：浮虧 ≥10 即走", "kw": {"mae_stop": 10}},
    "V9": {"name": "V4＋V8", "kw": {"lock": "tp2_be", "mae_stop": 10}},
    # 網格（次要）
    "V2b": {"name": "唔追 ≥10", "kw": {"chase": 10}}, "V2c": {"name": "唔追 ≥20", "kw": {"chase": 20}}, "V2d": {"name": "唔追 ≥25", "kw": {"chase": 25}},
    "V1b": {"name": "SL 上限 8", "kw": {"sl_cap": 8}}, "V1c": {"name": "SL 上限 12", "kw": {"sl_cap": 12}}, "V1d": {"name": "SL 上限 15", "kw": {"sl_cap": 15}},
    "V8b": {"name": "MAE 止損 8", "kw": {"mae_stop": 8}}, "V8c": {"name": "MAE 止損 12", "kw": {"mae_stop": 12}},
    "V3b": {"name": "時間止損 20 分鐘", "kw": {"time_stop": 20}}, "V3c": {"name": "時間止損 45 分鐘", "kw": {"time_stop": 45}},
    "V10": {"name": "V2（唔追 15）＋V1（SL 上限 10）", "kw": {"chase": 15, "sl_cap": 10}},
    # 「學佢入場、改善佢」候選（使用者 10-29）：GB 入場方向／時機不變，SL 上限 10，TP 唔用佢嘅 4／5 步距而按 R 重定（tp_set＝成交價 ± 距離）
    "V11": {"name": "GB 入場、SL 10、TP 5/10/15/20 逐級鎖", "kw": {"sl_cap": 10, "tp_set": [5, 10, 15, 20]}},
    "V12": {"name": "GB 入場、SL 10、TP 10/20 兩級（TP1→保本）", "kw": {"sl_cap": 10, "tp_set": [10, 20]}},
    "V13": {"name": "GB 入場、SL 10、TP 10 全平（1:1）", "kw": {"sl_cap": 10, "tp_set": [10], "lock": "tp1_flat"}},
    "V14": {"name": "GB 入場、SL 10、TP 5/10/15/20、MAE 止損 6", "kw": {"sl_cap": 10, "tp_set": [5, 10, 15, 20], "mae_stop": 6}},
}
PRIMARY = ("V0", "V1", "V2", "V3", "V8", "V10", "V11", "V12", "V13", "V14")


# ---------- 純函數 ----------
def first_index(bars, ts):
    """第一根開盤時間 ≥ 訊號分鐘（向下取整到 K 線）嘅 K 線索引；冇就 None。"""
    for i, b in enumerate(bars):
        if b["utc"] + bar_len(bars) > ts:
            return i
    return None


def bar_len(bars):
    if len(bars) >= 2:
        d = bars[1]["utc"] - bars[0]["utc"]
        if d > 0:
            return d
    return 60


def pre_move(bars, ts, minutes=30):
    """訊號前 N 分鐘價格變動（訊號 K 線開盤 − N 分鐘前 K 線開盤）；K 線唔夠就 None。"""
    i = first_index(bars, ts)
    n = max(1, int(round(minutes * 60 / bar_len(bars))))
    if i is None or i < n:
        return None
    return bars[i]["open"] - bars[i - n]["open"]


def simulate(bars, sig, *, sl_cap=None, lock="tp1_be", time_stop=None, entry="market", mae_stop=None, chase=None,
             tp_set=None, max_hold_min=MAX_HOLD_MIN):
    """一張訊號喺 bars（已校正到現貨價）上行一個變體。sig：ts、side、lo、hi、sl、tp（list）。回傳 dict：
    res（sl／be／lockK／all_tp／tp1_flat／tp2_flat／time_stop／mae_stop／skip_chase／not_filled／open／no_bars）、r（每 1 美元原 SL 風險）、pnl（美元/oz）、mfe、mae、k、exit_utc。"""
    side, sg, tps = sig["side"], (1 if sig["side"] == "BUY" else -1), list(sig["tp"] or [])
    if not tps or sig.get("sl") is None:
        return {"res": "skip", "r": 0.0, "pnl": 0.0, "mfe": 0.0, "mae": 0.0, "k": 0, "exit_utc": None}
    if chase is not None:
        pm = pre_move(bars, sig["ts"])
        if pm is not None and pm * sg >= chase:
            return {"res": "skip_chase", "r": 0.0, "pnl": 0.0, "mfe": 0.0, "mae": 0.0, "k": 0, "exit_utc": None, "pre_move": pm * sg}
    i0 = first_index(bars, sig["ts"])
    if i0 is None:
        return {"res": "no_bars", "r": 0.0, "pnl": 0.0, "mfe": 0.0, "mae": 0.0, "k": 0, "exit_utc": None}
    fill = fi = None
    for i in range(i0, len(bars)):
        b = bars[i]
        if b["utc"] > sig["ts"] + FILL_TTL_MIN * 60:
            break
        if entry == "market":
            fill, fi = b["open"], i
            break
        px = sig["lo"] if side == "BUY" else sig["hi"]                 # 回調限價：等價格去到入場區「好」邊
        if (side == "BUY" and b["low"] <= px) or (side == "SELL" and b["high"] >= px):
            fill, fi = px, i
            break
    if fill is None:
        return {"res": "not_filled", "r": 0.0, "pnl": 0.0, "mfe": 0.0, "mae": 0.0, "k": 0, "exit_utc": None}
    risk0 = abs(fill - sig["sl"])
    if risk0 <= 0:
        return {"res": "skip", "r": 0.0, "pnl": 0.0, "mfe": 0.0, "mae": 0.0, "k": 0, "exit_utc": None}
    sl = sig["sl"]
    if sl_cap is not None and risk0 > sl_cap:
        sl = fill - sg * sl_cap
    if tp_set:                                                         # 「學佢入場、改善佢」：TP 按成交價 ± 距離重定
        tps = [fill + sg * float(d) for d in tp_set]
    cur, k, mfe, mae = sl, 0, 0.0, 0.0

    def out(res, pnl, i, kk):
        return {"res": res, "r": round(pnl / risk0, 4), "pnl": round(pnl, 2), "mfe": round(mfe, 2), "mae": round(mae, 2), "k": kk,
                "exit_utc": dt.datetime.utcfromtimestamp(bars[i]["utc"]).strftime("%Y-%m-%d %H:%M"), "fill": fill}

    for i in range(fi, len(bars)):
        b = bars[i]
        fav = (b["high"] - fill) if side == "BUY" else (fill - b["low"])
        adv = (fill - b["low"]) if side == "BUY" else (b["high"] - fill)
        mfe, mae = max(mfe, fav), max(mae, adv)
        if (b["low"] <= cur) if side == "BUY" else (b["high"] >= cur):              # 影線掃 SL／鎖位（同根先當 SL：保守）
            return out("sl" if k == 0 else ("be" if (k == 1 and lock == "tp1_be") or (k == 2 and lock == "tp2_be") else f"lock{k}"), (cur - fill) * sg, i, k)
        if mae_stop is not None and k == 0 and adv >= mae_stop:
            return out("mae_stop", -mae_stop, i, 0)
        if (b["high"] >= tps[-1]) if side == "BUY" else (b["low"] <= tps[-1]):      # 伺服器 TP（最後一級）用影線
            return out("all_tp", (tps[-1] - fill) * sg, i, len(tps))
        while k < len(tps) - 1 and ((b["close"] >= tps[k]) if side == "BUY" else (b["close"] <= tps[k])):   # 鎖位：收市價（心跳現價）
            k += 1
            if lock == "tp1_be":
                cur = fill if k == 1 else tps[k - 2]
            elif lock == "tp2_be":
                cur = sl if k == 1 else (fill if k == 2 else tps[k - 3])
            elif lock == "tp1_flat":
                return out("tp1_flat", (tps[0] - fill) * sg, i, 1)
            elif lock == "tp2_flat" and k >= 2:
                return out("tp2_flat", (tps[1] - fill) * sg, i, 2)
        if time_stop is not None and k == 0 and b["utc"] - bars[fi]["utc"] >= time_stop * 60 and (b["close"] - fill) * sg < 0:
            return out("time_stop", (b["close"] - fill) * sg, i, 0)
        if b["utc"] - bars[fi]["utc"] >= max_hold_min * 60:
            return out("timeout", (b["close"] - fill) * sg, i, k)
    return out("open", (bars[-1]["close"] - fill) * sg, len(bars) - 1, k)


def summarize(results):
    """results：list of simulate() dict。回傳 n（有成交）、勝／平／負、ΣR、平均 R、PF、最大回撤（R）、略過數、最長連敗。"""
    traded = [r for r in results if r["res"] not in ("skip", "skip_chase", "not_filled", "no_bars")]
    wins = [r for r in traded if r["pnl"] > 0.05]
    losses = [r for r in traded if r["pnl"] < -0.05]
    flat = len(traded) - len(wins) - len(losses)
    rs = [r["r"] for r in results]
    cum = peak = dd = 0.0
    streak = worst = 0
    for x in results:
        r = x["r"]
        cum += r
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
        if x["res"] in ("skip", "skip_chase", "not_filled", "no_bars"):
            continue                                                  # 略過唔算贏輸，連敗唔重設
        streak = streak + 1 if r < -0.05 else 0
        worst = max(worst, streak)
    gp, gl = sum(r["r"] for r in wins), -sum(r["r"] for r in losses)
    return {"n": len(traded), "win": len(wins), "flat": flat, "loss": len(losses), "sum_r": round(sum(rs), 2),
            "avg_r": round(sum(rs) / len(traded), 3) if traded else None, "pf": round(gp / gl, 2) if gl > 0 else None,
            "max_dd_r": round(dd, 2), "skipped": sum(1 for r in results if r["res"] in ("skip_chase", "not_filled")),
            "max_loss_streak": worst, "sum_usd_oz": round(sum(r["pnl"] for r in results), 1)}


def calibrate(fut_bars, sig, hours=24):
    """期貨 K 線 → 現貨等值：offset＝訊號 K 線開盤 − 入場中位；回傳 (校正後嘅窗口 K 線, offset)。訊號前 60 分鐘都保留（計先行）。"""
    mid = (sig["lo"] + sig["hi"]) / 2
    i = first_index(fut_bars, sig["ts"])
    if i is None:
        return [], None
    offset = fut_bars[i]["open"] - mid
    lo_ts, hi_ts = sig["ts"] - 60 * 60, sig["ts"] + hours * 3600
    win = [{"utc": b["utc"], "open": b["open"] - offset, "high": b["high"] - offset, "low": b["low"] - offset, "close": b["close"] - offset}
           for b in fut_bars if lo_ts <= b["utc"] <= hi_ts]
    return win, round(offset, 2)


def parse_history(doc):
    """history JSON → 訊號 dict 或 None（只要 new_signal、有方向／入場區／SL／TP）。"""
    s = (doc or {}).get("signal") or {}
    if s.get("kind") != "new_signal" or s.get("side") not in ("BUY", "SELL") or s.get("sl") is None or not s.get("tp"):
        return None
    if s.get("entry_low") is None or s.get("entry_high") is None:
        return None
    return {"sid": doc.get("sid"), "ts": float(doc.get("msg_ts") or 0), "utc": doc.get("msg_utc"), "side": s["side"],
            "lo": float(s["entry_low"]), "hi": float(s["entry_high"]), "sl": float(s["sl"]), "tp": [float(x) for x in s["tp"]]}


def out_prefix(channel):
    """0342 沿用舊位置（xau/sig/gb_rulesim/）；其他頻道 xau/sig/gb_rulesim/<尾4>/。"""
    ch4 = str(channel)[-4:]
    return OUT_PREFIX if ch4 == "0342" else f"{OUT_PREFIX}{ch4}/"


def parse_recent(rec, ch=None):
    if rec.get("ch") != (ch or CH) or rec.get("kind") != "new_signal" or rec.get("side") not in ("BUY", "SELL") or rec.get("sl") is None or not rec.get("tp"):
        return None
    if rec.get("entry_low") is None or rec.get("entry_high") is None:
        return None
    return {"sid": rec.get("sid"), "ts": float(rec.get("msg_ts") or 0), "utc": rec.get("msg_utc"), "side": rec["side"],
            "lo": float(rec["entry_low"]), "hi": float(rec["entry_high"]), "sl": float(rec["sl"]), "tp": [float(x) for x in rec["tp"]]}


def run_all(signals, bars_for, variants=VARIANTS):
    """signals：list；bars_for(sig) → (bars, offset)。回傳 {variant: {"summary":…, "per_signal":[…]}}，同 skipped（冇 K 線／基差離譜）。"""
    prepared, dropped = [], []
    for s in signals:
        bars, off = bars_for(s)
        if not bars or off is None or abs(off) > 80:
            dropped.append({"sid": s["sid"], "utc": s["utc"], "why": "冇 K 線" if not bars else f"基差 {off} 離譜"})
            continue
        prepared.append((s, bars, off))
    out = {}
    for key, v in variants.items():
        res = []
        for s, bars, off in prepared:
            r = simulate(bars, s, **v["kw"])
            r.update({"sid": s["sid"], "utc": s["utc"], "side": s["side"], "offset": off, "risk": round(abs((s["lo"] + s["hi"]) / 2 - s["sl"]), 2)})
            res.append(r)
        out[key] = {"name": v["name"], "summary": summarize(res), "per_signal": res}
    return out, dropped


def to_markdown(result, dropped, meta):
    ch4 = str(meta.get("channel", DEFAULT_CHANNEL))[-4:]
    lines = [f"# 頻道 {ch4} 跟單規則回測（IDEAS #148／#150）", "",
             f"- 跑：{meta.get('run_utc')} UTC；訊號 {meta.get('n_signals')} 張（{meta.get('since')} 起），有 K 線 {meta.get('n_used')} 張、略過 {len(dropped)}；價格 {meta.get('price_src')}",
             "- R＝每 1 美元原 SL 風險；Σ美元/oz 係每 1 oz；0342 真倉 0.07 手＝7 oz。鎖位用 K 線收市價、SL／TP4 用影線、同根先當 SL（保守）。", "",
             "| 變體 | 說明 | 張 | 勝 | 平 | 負 | ΣR | 平均R | PF | 最大回撤R | 最長連敗 | 略過 | Σ美元/oz |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, v in result.items():
        s = v["summary"]
        lines.append(f"| {key} | {v['name']} | {s['n']} | {s['win']} | {s['flat']} | {s['loss']} | {s['sum_r']} | {s['avg_r']} | {s['pf']} | {s['max_dd_r']} | {s['max_loss_streak']} | {s['skipped']} | {s['sum_usd_oz']} |")
    if dropped:
        lines += ["", f"略過 {len(dropped)} 張：" + "、".join(f"{d['sid'][-4:]}（{d['why']}）" for d in dropped[:20]) + ("…" if len(dropped) > 20 else "")]
    return "\n".join(lines) + "\n"


# ---------- 連線部分（Actions 用） ----------
class Gcs:
    def __init__(self):
        from google.cloud import storage
        self.b = storage.Client().bucket(BUCKET)

    def read_json(self, name):
        blob = self.b.blob(name)
        return json.loads(blob.download_as_text()) if blob.exists() else None

    def read_text(self, name):
        blob = self.b.blob(name)
        return blob.download_as_text() if blob.exists() else None

    def write(self, name, text, ctype):
        self.b.blob(name).upload_from_string(text, content_type=ctype)

    def list(self, prefix):
        return [b.name for b in self.b.list_blobs(prefix=prefix)]


def load_signals(g, since, channel=DEFAULT_CHANNEL):
    sigs, seen = [], set()
    for name in g.list(f"xau/sig/history/{channel}_"):
        s = parse_history(g.read_json(name))
        if s and s["utc"] and s["utc"] >= since and s["sid"] not in seen:
            sigs.append(s)
            seen.add(s["sid"])
    for rec in g.read_json(RECENT) or []:
        s = parse_recent(rec, str(channel)[-4:])
        if s and s["utc"] and s["utc"] >= since and s["sid"] not in seen:
            sigs.append(s)
            seen.add(s["sid"])
    sigs.sort(key=lambda s: s["ts"])
    return sigs


BARS_PREFIX = "xau/sig/bars/"


def fetch_broker_bars(g, days):
    """GCS xau/sig/bars/<日>.jsonl（EA 心跳存嘅經紀 M1，一行一個 JSON 陣列）→ 最近 days 日嘅 K 線（utc 欄）。無基差。"""
    out = []
    for nm in sorted(g.list(BARS_PREFIX))[-days:]:
        for ln in (g.read_text(nm) or "").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.extend(json.loads(ln))
                except ValueError:
                    continue
    out = [{"utc": int(b["utc"]), "open": float(b["open"]), "high": float(b["high"]), "low": float(b["low"]), "close": float(b["close"])} for b in out if isinstance(b, dict) and b.get("utc") is not None]
    out.sort(key=lambda b: b["utc"])
    return out


def fetch_futures(interval, period):
    import yfinance as yf
    df = yf.download("GC=F", period=period, interval=interval, progress=False, auto_adjust=False)
    if df is None or len(df) == 0:
        return []
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    idx = df.index
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    out = []
    for t, row in zip(idx, df.itertuples(index=False)):
        d = row._asdict()
        if any(d.get(k) is None or d.get(k) != d.get(k) for k in ("Open", "High", "Low", "Close")):
            continue
        out.append({"utc": int(t.timestamp()), "open": float(d["Open"]), "high": float(d["High"]), "low": float(d["Low"]), "close": float(d["Close"])})
    out.sort(key=lambda b: b["utc"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-01")
    ap.add_argument("--channel", default=DEFAULT_CHANNEL, help="頻道 id（2249680342＝Gold Brother、1473735117＝黃金戰鬥機）")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--period", default="60d")
    ap.add_argument("--source", default="yf", choices=("yf", "broker"), help="yf＝yfinance GC=F（校正基差）；broker＝GCS xau/sig/bars 經紀 M1（無基差，只有最近幾日）")
    ap.add_argument("--days", type=int, default=7, help="--source broker 讀最近幾日 K 線")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    g = Gcs()
    sigs = load_signals(g, a.since, a.channel)
    if a.source == "broker":
        fut = fetch_broker_bars(g, a.days)
        src = f"經紀 M1（GCS {BARS_PREFIX} 最近 {a.days} 日，無基差）"
        bars_for = lambda s: ([b for b in fut if s["ts"] - 3600 <= b["utc"] <= s["ts"] + 24 * 3600], 0.0)   # noqa: E731
    else:
        fut = fetch_futures(a.interval, a.period)
        src = f"yfinance GC=F {a.interval}/{a.period}（每張訊號校正基差）"
        bars_for = lambda s: calibrate(fut, s)   # noqa: E731
    print(f"訊號 {len(sigs)} 張（{a.since} 起）；K 線 {len(fut)} 根 {src}" + (f"（{dt.datetime.utcfromtimestamp(fut[0]['utc'])} → {dt.datetime.utcfromtimestamp(fut[-1]['utc'])}）" if fut else ""))
    if not fut:
        print("冇 K 線數據，停")
        return 1
    result, dropped = run_all(sigs, bars_for)
    run_utc = dt.datetime.utcnow().strftime("%Y-%m-%dT%H%MZ")
    meta = {"run_utc": run_utc, "since": a.since, "n_signals": len(sigs), "n_used": len(sigs) - len(dropped), "price_src": src, "channel": a.channel, "variants": {k: v["kw"] for k, v in VARIANTS.items()}}
    md = to_markdown(result, dropped, meta)
    print(md)
    for key in PRIMARY:
        print(key, json.dumps(result[key]["summary"], ensure_ascii=False))
    if a.dry_run:
        print("（dry-run，唔寫 GCS）")
        return 0
    doc = {"meta": meta, "result": result, "dropped": dropped}
    g.write(out_prefix(a.channel) + run_utc + ".json", json.dumps(doc, ensure_ascii=False), "application/json")
    g.write(out_prefix(a.channel) + "latest.json", json.dumps(doc, ensure_ascii=False), "application/json")
    g.write(out_prefix(a.channel) + "latest.md", md, "text/markdown; charset=utf-8")
    print("已寫 GCS", out_prefix(a.channel) + run_utc + ".json / latest.json / latest.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
