#!/usr/bin/env python3
# =============================================================================
# 金絲雀燈色表 — 由六隻鳥日線產出每日燈色 CSV
# -----------------------------------------------------------------------------
# 依 CANARY_PLAYBOOK.md §2 的現役編制,固定規則、不調參:
#   🔴 紅      VIX9D − VIX > 0                     (週/月倒掛)
#   🟣 深紅    VIX − VIX3M > 0                     (月/季倒掛)
#   ⚪ 走平    −0.5 < VIX9D − VIX ≤ 0              (綠轉紅過渡帶)
#   🟡 黃      VVIX / MOVE / AXVI 任一 > 自身滾動 252 日 90 分位
#   🟢 綠      以上皆無
#
# 口徑與雲垂陣 tradingview/canary_lab.py 一致:
#   * 滾動 252 日 90 分位 = pandas `x.rolling(252).quantile(0.9)`,窗口**含當日**,
#     線性插值;不足 252 筆的日子為空值。這裡用純標準庫重現,不需安裝 pandas。
#   * 每隻鳥在自己的交易日曆上算分位,再對齊到 VIX 日曆(美股交易日)。
#   * 表中每一列是「以該日收盤算出」的燈色。**用家必須自己套 lag=1**:
#     T 日的燈色只能用在 T 之後的交易日,不能用在 T 日本身(§7 口徑紀律)。
#
# 輸入:canary/data_external/{vix9d,vix,vix3m,vvix,move,axvi}_daily.csv
#       (欄位 Date,Open,High,Low,Close;快照自雲垂陣分支 tradingview/data_external/)
# 輸出:canary/canary_daily.csv
#
# 用法:
#   python3 canary/build_canary_table.py                # 用現有快照產表
#   python3 canary/build_canary_table.py --refresh      # 先從雲垂陣分支拉最新日線再產表
#   python3 canary/build_canary_table.py --start 2011-01-01
# =============================================================================
import argparse
import csv
import math
import os
import subprocess
import sys
from bisect import bisect_left, insort
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data_external")
OUT_FILE = os.path.join(HERE, "canary_daily.csv")

SOURCE_BRANCH = "claude/dazzling-curie-f3xzb8"
SOURCE_PATH = "tradingview/data_external"
BIRDS = ["vix9d", "vix", "vix3m", "vvix", "move", "axvi"]
PCT_BIRDS = ["vvix", "move", "axvi"]   # 黃燈三隻:滾動分位

WINDOW = 252
QUANTILE = 0.9
FLAT_LOWER = -0.5

# 紅燈或深紅亮起時一併展示(CANARY_PLAYBOOK.md §3 註,2026-09-26 增補)
RED_NOTE = (
    "註:紅與深紅的分工。Lim(2026,SSRN 6752518)發現含 VIX9D 的期限結構量度,\n"
    "    對未來 5–10 個交易日實現波動率的預測力在所有期限上勝過傳統 VIX−VIX3M 量度\n"
    "    (通過 2019–2026 樣本外檢驗),紅燈的學理地位高於手冊 §3 表所示。\n"
    "    但該文預測的是短期實現波動;深紅的王牌地位來自「災難月事前預警」,\n"
    "    兩者目標不同,不衝突:看未來一兩週的對沖負載看紅,看災難風險看深紅。"
)


# -----------------------------------------------------------------------------
# 讀檔
# -----------------------------------------------------------------------------
def load_close(path):
    """讀 Date,Close → [(date, close)],依日期排序、去重(同日取最後一筆)。"""
    rows = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            d, c = r.get("Date", "").strip(), r.get("Close", "").strip()
            if not d or not c:
                continue
            try:
                rows[date.fromisoformat(d[:10])] = float(c)
            except ValueError:
                continue
    return sorted(rows.items())


def refresh_snapshot():
    """從雲垂陣分支重新拉六隻鳥日線到 data_external/。"""
    ref = f"origin/{SOURCE_BRANCH}"
    subprocess.run(["git", "fetch", "-q", "origin", SOURCE_BRANCH], check=True, cwd=HERE)
    os.makedirs(DATA_DIR, exist_ok=True)
    for b in BIRDS:
        src = f"{ref}:{SOURCE_PATH}/{b}_daily.csv"
        out = subprocess.run(["git", "show", src], check=True, cwd=HERE,
                             capture_output=True, text=True).stdout
        with open(os.path.join(DATA_DIR, f"{b}_daily.csv"), "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"  ↻ {b}_daily.csv  {out.count(chr(10)) - 1} 列", flush=True)


# -----------------------------------------------------------------------------
# 滾動分位(重現 pandas rolling(WINDOW).quantile(QUANTILE),線性插值、窗口含當日)
# -----------------------------------------------------------------------------
def rolling_quantile(values, window=WINDOW, q=QUANTILE):
    """values: list[float];回傳等長 list,前 window-1 個為 None。"""
    out = [None] * len(values)
    buf = []                        # 排序後的窗口
    pos = q * (window - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, window - 1)
    frac = pos - lo
    for i, v in enumerate(values):
        insort(buf, v)
        if len(buf) > window:
            del buf[bisect_left(buf, values[i - window])]
        if len(buf) == window:
            out[i] = buf[lo] + frac * (buf[hi] - buf[lo])
    return out


# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
def fmt(x, nd=4):
    return "" if x is None else f"{x:.{nd}f}"


def flag(b):
    return "" if b is None else ("1" if b else "0")


def build(start=None):
    series = {}
    for b in BIRDS:
        p = os.path.join(DATA_DIR, f"{b}_daily.csv")
        if not os.path.exists(p):
            sys.exit(f"缺少 {p};先執行 --refresh 或手動放入快照。")
        series[b] = load_close(p)
        if not series[b]:
            sys.exit(f"{p} 讀不到任何資料。")

    close = {b: dict(series[b]) for b in BIRDS}

    # 黃燈三隻:在各自日曆上算分位
    p90 = {}
    for b in PCT_BIRDS:
        dates = [d for d, _ in series[b]]
        vals = [v for _, v in series[b]]
        p90[b] = dict(zip(dates, rolling_quantile(vals)))

    # 日曆:VIX 交易日,自 VIX3M 起算(深紅可算的第一天)
    first = series["vix3m"][0][0]
    if start:
        first = max(first, date.fromisoformat(start))
    calendar = [d for d, _ in series["vix"] if d >= first]

    rows = []
    for d in calendar:
        vix = close["vix"].get(d)
        v9 = close["vix9d"].get(d)
        v3 = close["vix3m"].get(d)
        s9 = (v9 - vix) if (v9 is not None and vix is not None) else None
        s3 = (vix - v3) if (v3 is not None and vix is not None) else None

        red = None if s9 is None else s9 > 0
        deep = None if s3 is None else s3 > 0
        flat = None if s9 is None else (FLAT_LOWER < s9 <= 0)

        yellow_parts = {}
        for b in PCT_BIRDS:
            v, thr = close[b].get(d), p90[b].get(d)
            yellow_parts[b] = None if (v is None or thr is None) else v > thr
        known = [x for x in yellow_parts.values() if x is not None]
        yellow = None if not known else any(known)

        # 單欄燈色(斜率燈互斥;黃燈另欄獨立標示)
        if deep:
            light = "深紅"
        elif red:
            light = "紅"
        elif flat:
            light = "走平"
        elif red is None and deep is None:
            light = ""
        else:
            light = "綠"

        rows.append({
            "date": d.isoformat(),
            "vix9d": fmt(v9, 2), "vix": fmt(vix, 2), "vix3m": fmt(v3, 2),
            "vvix": fmt(close["vvix"].get(d), 2),
            "move": fmt(close["move"].get(d), 2),
            "axvi": fmt(close["axvi"].get(d), 2),
            "slope_9d": fmt(s9, 2), "slope_3m": fmt(s3, 2),
            "vvix_p90": fmt(p90["vvix"].get(d), 2),
            "move_p90": fmt(p90["move"].get(d), 2),
            "axvi_p90": fmt(p90["axvi"].get(d), 2),
            "red": flag(red), "deep_red": flag(deep), "flat": flag(flat),
            "yellow_vvix": flag(yellow_parts["vvix"]),
            "yellow_move": flag(yellow_parts["move"]),
            "yellow_axvi": flag(yellow_parts["axvi"]),
            "yellow": flag(yellow),
            "light": light,
        })
    return rows


def summarize(rows):
    def share(key):
        vals = [r[key] for r in rows if r[key] != ""]
        return (sum(v == "1" for v in vals), len(vals))

    last = rows[-1]
    print(f"\n燈色表 {rows[0]['date']} → {last['date']},共 {len(rows)} 個交易日")
    for key, label in [("red", "紅"), ("deep_red", "深紅"), ("flat", "走平"), ("yellow", "黃")]:
        n, tot = share(key)
        print(f"  {label:<3} {n:>5} / {tot} 日  ({n / tot * 100 if tot else 0:.1f}%)")
    yparts = "/".join(f"{b}={last['yellow_' + b] or '-'}" for b in PCT_BIRDS)
    print(f"\n最新 {last['date']}:{last['light'] or '(無資料)'}"
          f"  slope_9d={last['slope_9d']}  slope_3m={last['slope_3m']}"
          f"  黃={last['yellow'] or '-'} ({yparts})")
    print("提醒:此燈色只能用於下一個交易日起(lag=1)。")
    if last["light"] in ("紅", "深紅"):
        print("\n" + RED_NOTE)


def main():
    ap = argparse.ArgumentParser(description="金絲雀燈色表產生器")
    ap.add_argument("--refresh", action="store_true", help="先從雲垂陣分支拉最新日線")
    ap.add_argument("--start", default=None, help="起算日(YYYY-MM-DD),預設 VIX3M 首日")
    ap.add_argument("--out", default=OUT_FILE)
    args = ap.parse_args()

    if args.refresh:
        print(f"從 origin/{SOURCE_BRANCH} 更新快照…", flush=True)
        refresh_snapshot()

    rows = build(args.start)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"已寫入 {os.path.relpath(args.out)}")
    summarize(rows)


if __name__ == "__main__":
    main()
