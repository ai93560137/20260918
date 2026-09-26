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
# 試用期欄位(2026-09-26 黃燈升級考核通過,見 YELLOW_UPGRADE.md;**無警報權**):
#   yellow_count        三隻黃鳥同時亮的數目 0–3(描述欄位)
#   trial_yellow2       🟡🟡 黃×2:至少兩隻黃鳥同時亮
#   trial_deep_yellow   🟡 深黃:VVIX > 自身滾動 252 日 95 分位
#
# 雙軸欄位(2026-09-26 紅燈提位,見 RED_UPGRADE.md):
#   axis_short          短期軸(VIX9D 系):紅 / 走平 / 綠      看未來一兩週對沖負載
#   axis_disaster       災難軸(VIX3M 系):深紅 / 綠           看災難風險
#   trial_red_deep      🔴 紅相對深度(試用,無警報權):slope_9d > 自身滾動 252 日 p90
#   trial_red_9d3m      🔴 9D對3M倒掛(試用,無警報權):VIX9D − VIX3M > 0,紅與深紅之間的中間層
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
LAB_FILES = ["spx", "hsi", "vhsi"]     # 考核用(yellow_lab.py):標的與 VHSI

WINDOW = 252
QUANTILE = 0.9
QUANTILE_DEEP = 0.95   # 深黃(試用)
FLAT_LOWER = -0.5

# 紅燈或深紅亮起時一併展示(CANARY_PLAYBOOK.md §3 註,2026-09-26 增補)
RED_NOTE = (
    "註:紅與深紅的分工。Lim(2026,SSRN 6752518)發現含 VIX9D 的量度在控制 VIX 水準後,\n"
    "    對未來 5–10 日實現波動有增量預測力(R² 額外 +2.4~6.9 個百分點,通過樣本外檢驗)。\n"
    "    但在手冊 §3 口徑(無條件亮燈日 RV 倍率、同樣本 2011 起)深紅仍勝紅:SPX 5 日 2.56 對 1.79。\n"
    "    兩者不矛盾:紅的價值在覆蓋面(亮燈最多、災難月覆蓋 4/4),是「別進場」的早期雷達;\n"
    "    深紅的價值在精度(誤報 10%)。看未來一兩週的對沖負載看紅(短期軸),看災難風險看深紅(災難軸)。"
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
    for b in BIRDS + LAB_FILES:
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
    vv_dates = [d for d, _ in series["vvix"]]
    vv_vals = [v for _, v in series["vvix"]]
    vvix_p95 = dict(zip(vv_dates, rolling_quantile(vv_vals, q=QUANTILE_DEEP)))
    s9_dates = [d for d, _ in series["vix9d"] if d in close["vix"]]
    s9_vals = [close["vix9d"][d] - close["vix"][d] for d in s9_dates]
    slope9_p90 = dict(zip(s9_dates, rolling_quantile(s9_vals)))

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
        ycount = None if not known else sum(1 for x in known if x)
        yellow2 = None if ycount is None else ycount >= 2
        vv, vthr = close["vvix"].get(d), vvix_p95.get(d)
        deep_yellow = None if (vv is None or vthr is None) else vv > vthr

        # 雙軸(紅燈提位):短期軸看 VIX9D,災難軸看 VIX3M,互不遮蔽
        axis_short = "" if red is None else ("紅" if red else ("走平" if flat else "綠"))
        axis_disaster = "" if deep is None else ("深紅" if deep else "綠")
        thr9 = slope9_p90.get(d)
        red_deep = None if (s9 is None or thr9 is None) else s9 > thr9
        red_9d3m = None if (v9 is None or v3 is None) else (v9 - v3) > 0

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
            "yellow_count": "" if ycount is None else str(ycount),
            "trial_yellow2": flag(yellow2),
            "vvix_p95": fmt(vvix_p95.get(d), 2),
            "trial_deep_yellow": flag(deep_yellow),
            "axis_short": axis_short,
            "axis_disaster": axis_disaster,
            "slope9_p90": fmt(thr9, 2),
            "trial_red_deep": flag(red_deep),
            "trial_red_9d3m": flag(red_9d3m),
        })
    return rows


def summarize(rows):
    def share(key):
        vals = [r[key] for r in rows if r[key] != ""]
        return (sum(v == "1" for v in vals), len(vals))

    last = rows[-1]
    print(f"\n燈色表 {rows[0]['date']} → {last['date']},共 {len(rows)} 個交易日")
    for key, label in [("red", "紅"), ("deep_red", "深紅"), ("flat", "走平"), ("yellow", "黃"),
                       ("trial_yellow2", "黃×2(試用)"), ("trial_deep_yellow", "深黃(試用)"),
                       ("trial_red_deep", "紅相對深度(試用)"), ("trial_red_9d3m", "9D對3M倒掛(試用)")]:
        n, tot = share(key)
        print(f"  {label:<3} {n:>5} / {tot} 日  ({n / tot * 100 if tot else 0:.1f}%)")
    yparts = "/".join(f"{b}={last['yellow_' + b] or '-'}" for b in PCT_BIRDS)
    print(f"\n最新 {last['date']}:{last['light'] or '(無資料)'}"
          f"  slope_9d={last['slope_9d']}  slope_3m={last['slope_3m']}"
          f"  黃={last['yellow'] or '-'} ({yparts})")
    print(f"雙軸:短期軸={last['axis_short'] or '-'}  災難軸={last['axis_disaster'] or '-'}")
    print(f"試用(無警報權):yellow_count={last['yellow_count'] or '-'}"
          f"  黃×2={last['trial_yellow2'] or '-'}  深黃VVIX p95={last['trial_deep_yellow'] or '-'}"
          f"  紅相對深度p90={last['trial_red_deep'] or '-'}  9D對3M倒掛={last['trial_red_9d3m'] or '-'}")
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
