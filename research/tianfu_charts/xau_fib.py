"""🌌 天覆陣 XAUUSD 斐波那契回撤圖（月線／週線／日線／4 小時線），參考龍飛陣 research/longfei_lessons/hsi_fib.py。

使用者 11-05（天覆陣新二）：「參考龍飛陣，用斐波那契回撤分析圖在月、週、日、H4」「加在斐波那契回撤分析圖網頁」。
資料：H1 CSV（t_utc,o,h,l,c；由 scripts/charts_publish.py 用 GCS xau/sig/duka_h1/＋經紀 M1 xau/sig/bars/ 砌）。
K 線用 MT5 伺服器時間（紐約時間 +7 小時，即紐約 17:00 換日＝伺服器 00:00），同 MT5 圖一致。
波段：回望期內最高點同最低點；高點喺後＝升浪（由高點向下量回撤），低點喺後＝跌浪（由低點向上量反彈）。
用法：python3 research/tianfu_charts/xau_fib.py <h1.csv> <輸出.png> <M|W|D|H4>；stdout 印 JSON。
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

NY = ZoneInfo("America/New_York")
# 每個時間框：回望（根數）、標題、顯示根數上限
TFS = {"M": (120, "月線", 150), "W": (104, "週線", 160), "D": (180, "日線", 220), "H4": (180, "4 小時線", 260)}
LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1]
PAL = {0: "#9e9e9e", 0.236: "#e53935", 0.382: "#66bb6a", 0.5: "#66bb6a", 0.618: "#26a69a",
       0.786: "#42a5f5", 0.886: "#42a5f5", 1: "#9e9e9e"}


def server_time(ts):
    """UTC 秒 → MT5 伺服器時間（紐約 +7，冇時區）。"""
    return (datetime.fromtimestamp(ts, timezone.utc).astimezone(NY) + timedelta(hours=7)).replace(tzinfo=None)


def bucket_key(t, tf):
    if tf == "H4":
        return t.replace(hour=t.hour // 4 * 4, minute=0, second=0, microsecond=0)
    d = datetime(t.year, t.month, t.day)
    if tf == "D":
        return d
    if tf == "W":
        return d - timedelta(days=d.weekday())
    return datetime(t.year, t.month, 1)


def load(path, tf):
    bars, last = {}, None
    with open(path) as f:
        for row in csv.reader(f):
            ts, o, h, l, c = int(row[0]), *map(float, row[1:5])
            st = server_time(ts)
            last = st if last is None or st > last else last
            k = bucket_key(st, tf)
            b = bars.get(k)
            bars[k] = [o, h, l, c] if b is None else [b[0], max(b[1], h), min(b[2], l), c]
    return bars, last + timedelta(hours=1)        # H1 收市時間


def swing(H, L, look):
    n = len(H)
    rng = range(max(0, n - look), n)
    hi_i, lo_i = max(rng, key=lambda i: H[i]), min(rng, key=lambda i: L[i])
    up = hi_i > lo_i
    hi, lo = H[hi_i], L[lo_i]
    # 升浪：0＝高點、1＝低點（向下回撤）；跌浪：0＝低點、1＝高點（向上反彈）
    price = {r: (hi - (hi - lo) * r) if up else (lo + (hi - lo) * r) for r in LEVELS}
    return hi_i, lo_i, up, price


def main():
    src, out, tf = sys.argv[1], sys.argv[2], sys.argv[3]
    look, name, show = TFS[tf]
    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        if os.path.exists(f):
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
            break
    bars, asof = load(src, tf)
    keys = sorted(bars)
    H, L, C = [bars[k][1] for k in keys], [bars[k][2] for k in keys], [bars[k][3] for k in keys]
    hi_i, lo_i, up, price = swing(H, L, look)

    def sma(n):
        return [sum(C[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(len(C))]

    first = max(0, len(keys) - show, min(hi_i, lo_i) - 15)
    fig, ax = plt.subplots(figsize=(15, 8), dpi=110)
    fig.patch.set_facecolor("#131722")
    ax.set_facecolor("#131722")
    wid = 2.6 if len(keys) - first < 180 else 1.8
    for i in range(first, len(keys)):
        o, h, l, c = bars[keys[i]]
        col = "#26a69a" if c >= o else "#ef5350"
        ax.vlines(i, l, h, color=col, linewidth=0.7)
        ax.vlines(i, min(o, c), max(o, c), color=col, linewidth=wid)
    XL = max(6, (len(keys) - first) // 14)
    labels = []
    smas = {}
    for n, col in ((50, "#f5c542"), (100, "#4caf50"), (200, "#e53935")):
        s = sma(n)
        smas[n] = round(s[-1], 2) if s[-1] else None
        xs = [i for i in range(first, len(s)) if s[i]]
        if xs:
            ax.plot(xs, [s[i] for i in xs], color=col, linewidth=1, label=f"SMA {n}")
            labels.append((s[-1], f"SMA{n}  {s[-1]:,.1f}", dict(facecolor=col, edgecolor="none", alpha=0.6)))
    a = min(hi_i, lo_i)
    for r in LEVELS:
        ax.hlines(price[r], a, len(keys) + XL - 1, color=PAL[r], linewidth=1.1)
        labels.append((price[r], f"{r:g}  {price[r]:,.1f}", dict(facecolor="#131722", edgecolor=PAL[r], linewidth=1.2)))
    ax.plot([lo_i, hi_i], [L[lo_i], H[hi_i]], ls="--", color="#bbbbbb", linewidth=0.8)
    fmt = "%Y/%m" if tf in ("M", "W") else "%m/%d"
    ax.annotate(keys[lo_i].strftime(fmt), (lo_i, L[lo_i]), xytext=(0, -18), textcoords="offset points", color="#ffd54f", ha="center")
    ax.annotate(keys[hi_i].strftime(fmt), (hi_i, H[hi_i]), xytext=(0, 10), textcoords="offset points", color="#ffd54f", ha="center")
    ax.axhline(C[-1], color="#2962ff", ls=":", linewidth=0.8)
    labels.append((C[-1], f"現價  {C[-1]:,.1f}", dict(facecolor="#2962ff", edgecolor="none")))
    if tf == "M":
        ticks = [i for i in range(first, len(keys)) if keys[i].month == 1]
    elif tf == "W":
        ticks = [i for i in range(first, len(keys)) if i == first or keys[i].month != keys[i - 1].month and keys[i].month % 3 == 1]
    elif tf == "D":
        ticks = [i for i in range(first, len(keys)) if i == first or keys[i].month != keys[i - 1].month]
    else:
        ticks = [i for i in range(first, len(keys)) if keys[i].hour == 0 and keys[i].weekday() == 0]
    tfmt = "%Y" if tf == "M" else ("%Y/%m" if tf == "W" else "%m/%d")
    ax.set_xticks(ticks)
    ax.set_xticklabels([keys[i].strftime(tfmt) for i in ticks], color="#bbbbbb", fontsize=8)
    ax.tick_params(axis="y", colors="#dddddd", labelsize=10)
    ax.set_xlim(first - 2, len(keys) + XL * 3)
    lo_v, hi_v = min(L[first:]), max(H[first:])
    pad = (hi_v - lo_v) * 0.04
    ax.set_ylim(lo_v - pad, hi_v + pad)
    y0, y1 = ax.get_ylim()
    gap = (y1 - y0) * 0.034
    placed = []
    for y, txt, box in sorted(labels, key=lambda t: t[0]):
        ty = max(y, placed[-1] + gap) if placed else y
        placed.append(ty)
        if abs(ty - y) > (y1 - y0) * 0.002:
            ax.plot([len(keys) + XL - 1, len(keys) + XL], [y, ty], color="#888888", linewidth=0.6)
        ax.text(len(keys) + XL, ty, txt, color="#ffffff", va="center", fontsize=12, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", **box))
    ax.grid(color="#2a2e39", linewidth=0.5)
    for s in ax.spines.values():
        s.set_color("#2a2e39")
    ax.legend(loc="best", facecolor="#131722", labelcolor="#dddddd", fontsize=9)
    kind = "升浪回撤" if up else "跌浪反彈"
    a_i, b_i = (lo_i, hi_i) if up else (hi_i, lo_i)
    av, bv = (L[lo_i], H[hi_i]) if up else (H[hi_i], L[lo_i])
    ax.set_title(f"XAUUSD 黃金 {name}（MT5 伺服器時間）　斐波那契{kind}：{keys[a_i].strftime(fmt)} {av:,.1f} → "
                 f"{keys[b_i].strftime(fmt)} {bv:,.1f}　截至 {asof:%Y-%m-%d %H:%M}", color="#eeeeee", fontsize=12)
    plt.tight_layout()
    plt.savefig(out, facecolor=fig.get_facecolor())
    print(json.dumps({"tf": tf, "kind": kind, "hi": [str(keys[hi_i]), H[hi_i]], "lo": [str(keys[lo_i]), L[lo_i]],
                      "last": C[-1], "asof": str(asof), "levels": {f"{r:g}": round(price[r], 2) for r in LEVELS},
                      **{f"sma{n}": v for n, v in smas.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
