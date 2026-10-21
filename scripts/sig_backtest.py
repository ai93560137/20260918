"""📜 天覆陣訊號書：用 MT5 匯出嘅歷史 M1 計各頻道舊訊號嘅成績（使用者 10-21：讀返 90 日、用 MT5 匯出）。

輸入（本機檔案，唔連線）：
  --csv     MT5 腳本 xau/mt5/ExportM1.mq5 匯出嘅 CSV（time 係伺服器時間；最後一欄 server_minus_utc_sec）
  --signals 一個資料夾，入面係 GCS xau/sig/history/*.json（gcp_agent.py cat 落嚟）
輸出：每個頻道嘅成交率、TP1 先到、SL 先到、平均去到第幾個 TP、TP1 走平均 R；同埋逐條明細（--detail）。
計法同即時訊號書一樣（xau/signals.py evaluate）：市價單即時成交、限價入場區容許一個點差、同一根 K 線碰 SL 同 TP 當 SL、24 小時未完當平手。
頻道自稱成績一律唔用。報告含訊號內容，唔好 commit 入公開 repo。
"""
import argparse
import csv
import glob
import json
import os
import sys
import types

os.environ.setdefault("XAU_BOOK", "signal")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
try:
    import anthropic  # noqa: F401
except ImportError:                                   # 只用 evaluate，唔使 SDK
    _an = types.ModuleType("anthropic")
    _an.Anthropic = lambda *a, **k: None
    _an.BadRequestError = Exception
    sys.modules["anthropic"] = _an
import signals  # noqa: E402

NAMES = {"7117": "黄金战斗机", "5231": "CTC VIP", "7713": "DAN VIP", "0342": "高巴打"}


def load_bars(path):
    bars, offset = [], 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            bars.append({"time": int(row["time"]), "open": float(row["open"]), "high": float(row["high"]),
                         "low": float(row["low"]), "close": float(row["close"])})
            offset = int(float(row.get("server_minus_utc_sec") or offset))
    bars.sort(key=lambda b: b["time"])
    return bars, offset


def window(bars, offset, start_utc, hours=24):
    """二分搵 msg 之後 24 小時嘅 K 線（evaluate 只需要呢段）。"""
    import bisect
    keys = [b["time"] - offset for b in bars]
    i = bisect.bisect_left(keys, start_utc - 60)
    j = bisect.bisect_right(keys, start_utc + hours * 3600)
    return bars[i:j]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args(argv)
    bars, offset = load_bars(a.csv)
    if not bars:
        sys.exit("CSV 冇 K 線")
    first, last = bars[0]["time"] - offset, bars[-1]["time"] - offset
    stats, rows, skipped = {}, [], 0
    for path in sorted(glob.glob(os.path.join(a.signals, "*.json"))):
        rec = json.load(open(path, encoding="utf-8"))
        sig = rec.get("signal") or {}
        if sig.get("kind") != "new_signal" or rec.get("status") != "history":
            continue
        ms = rec.get("msg_ts") or 0
        if ms < first or ms > last - 3600:
            skipped += 1
            continue
        view = {**sig, "msg_ts": ms}
        o = signals.evaluate(view, window(bars, offset, ms), offset, now=ms + 25 * 3600)
        if not o.get("final"):
            o["final"] = "timeout"
        r = signals.r_multiple(view, o)
        ch = str(rec.get("channel_id") or rec["sid"].split("_")[0])[-4:]
        c = stats.setdefault(ch, {"n": 0, "filled": 0, "tp1": 0, "sl": 0, "max_tp_sum": 0, "r": []})
        c["n"] += 1
        if o.get("filled_ts"):
            c["filled"] += 1
            c["tp1"] += o.get("max_tp", 0) >= 1
            c["sl"] += bool(o.get("sl_hit")) and o.get("max_tp", 0) == 0
            c["max_tp_sum"] += o.get("max_tp", 0)
            if r is not None:
                c["r"].append(r)
        rows.append((rec.get("msg_utc"), ch, sig, o, r))
    print(f"K 線 {len(bars)} 根（UTC {signals.market.fmt_utc(first)} → {signals.market.fmt_utc(last)}，時差 {offset} 秒）；範圍外略過 {skipped} 條")
    print("| 頻道 | 入場訊號 | 成交率 | TP1 先到 | SL 先到 | 平均去到第幾個 TP | TP1 走平均 R |")
    print("|---|---|---|---|---|---|---|")
    pct = lambda x, y: "—" if not y else f"{x / y:.0%}"  # noqa: E731
    for ch, c in sorted(stats.items()):
        avg_r = "—" if not c["r"] else f"{sum(c['r']) / len(c['r']):+.2f}"
        avg_tp = "—" if not c["filled"] else f"{c['max_tp_sum'] / c['filled']:.1f}"
        print(f"| {NAMES.get(ch, '…' + ch)} | {c['n']} | {pct(c['filled'], c['n'])} | {pct(c['tp1'], c['filled'])} | "
              f"{pct(c['sl'], c['filled'])} | {avg_tp} | {avg_r} |")
    if a.detail:
        print("\n| 時間 UTC | 頻道 | 方向 | 入場 | SL | TP | 結果 | 最高 TP | R |\n|---|---|---|---|---|---|---|---|---|")
        for t, ch, sig, o, r in rows:
            print(f"| {t} | {NAMES.get(ch, ch)} | {sig.get('side')} | {sig.get('entry_low'):g}–{sig.get('entry_high'):g} | {sig.get('sl'):g} | "
                  f"{'/'.join(f'{x:g}' for x in sig.get('tp') or [])} | {o.get('final')} | {o.get('max_tp', 0)} | {r} |")


if __name__ == "__main__":
    main()
