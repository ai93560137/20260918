"""[R288] 恒指即月期貨 4 小時線 + 斐波那契回撤（由程式揀波段：最近 90 日最高點同佢之前嘅最低點）。

使用者 10-23：「你劃斐波那契」，之後要求由總指揮放上網頁。資料：GCS archive/futu_k_1m/HK.HSI_FRONT/<日>.json（1 分鐘，含夜市）。
用法：python3 research/longfei_lessons/hsi_fib.py <1分鐘K線資料夾> <輸出.png>；stdout 印波段、各回撤位同 50/100/200 均線（JSON）。
"""
import glob
import json
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

src, out = sys.argv[1], sys.argv[2]
for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
    if os.path.exists(f):
        font_manager.fontManager.addfont(f)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
        break

# 1 分鐘 → 4 小時（香港時間 00/04/08/12/16/20 開始）
bars = {}
for p in sorted(glob.glob(os.path.join(src, "*.json"))):
    try:
        rows = json.load(open(p))
    except ValueError:
        continue
    for b in rows if isinstance(rows, list) else []:
        t = datetime.strptime(b["time_key"], "%Y-%m-%d %H:%M:%S")
        k = t.replace(hour=t.hour // 4 * 4, minute=0, second=0)
        o = bars.get(k)
        bars[k] = [b["open"], b["high"], b["low"], b["close"]] if o is None else \
            [o[0], max(o[1], b["high"]), min(o[2], b["low"]), b["close"]]
keys = sorted(bars)
H = [bars[k][1] for k in keys]
L = [bars[k][2] for k in keys]
C = [bars[k][3] for k in keys]

# 波段：最近 90 日內最高點，再揾佢之前嘅最低點（升浪 → 回撤）
recent = [i for i, k in enumerate(keys) if (keys[-1] - k).days <= 90]
hi_i = max(recent, key=lambda i: H[i])
lo_i = min(range(max(0, hi_i - 6 * 90), hi_i + 1), key=lambda i: L[i])
hi, lo = H[hi_i], L[lo_i]
levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1]
price = {r: hi - (hi - lo) * r for r in levels}

def sma(n):
    return [sum(C[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(len(C))]

fig, ax = plt.subplots(figsize=(15, 8), dpi=110)
fig.patch.set_facecolor("#131722")
ax.set_facecolor("#131722")
for i, k in enumerate(keys):
    o, h, l, c = bars[k]
    col = "#26a69a" if c >= o else "#ef5350"
    ax.vlines(i, l, h, color=col, linewidth=0.7)
    ax.vlines(i, min(o, c), max(o, c), color=col, linewidth=2.6)
labels = []   # [R363] 右邊一欄：(價, 字, 框樣式)，最後統一排開唔重疊
for n, col in ((50, "#f5c542"), (100, "#4caf50"), (200, "#e53935")):
    s = sma(n)
    ax.plot([i for i in range(len(s)) if s[i]], [v for v in s if v], color=col, linewidth=1, label=f"SMA {n}")
    if s[-1]:   # [R363] 使用者 10-30：回撤位表唔要，數字用白色喺圖上清楚顯示（均線尾端都標數）
        labels.append((s[-1], f"SMA{n}  {s[-1]:,.0f}", dict(facecolor=col, edgecolor="none", alpha=0.6)))
pal = {0: "#9e9e9e", 0.236: "#e53935", 0.382: "#66bb6a", 0.5: "#66bb6a", 0.618: "#26a69a",
       0.786: "#42a5f5", 0.886: "#42a5f5", 1: "#9e9e9e"}
for r in levels:
    ax.hlines(price[r], lo_i, len(keys) + 12, color=pal[r], linewidth=1.1)
    labels.append((price[r], f"{r:g}  {price[r]:,.0f}", dict(facecolor="#131722", edgecolor=pal[r], linewidth=1.2)))
ax.plot([lo_i, hi_i], [lo, hi], ls="--", color="#bbbbbb", linewidth=0.8)
ax.annotate(keys[lo_i].strftime("%m/%d"), (lo_i, lo), xytext=(0, -18), textcoords="offset points", color="#ffd54f", ha="center")
ax.annotate(keys[hi_i].strftime("%m/%d"), (hi_i, hi), xytext=(0, 10), textcoords="offset points", color="#ffd54f", ha="center")
ax.axhline(C[-1], color="#2962ff", ls=":", linewidth=0.8)
labels.append((C[-1], f"現價  {C[-1]:,.0f}", dict(facecolor="#2962ff", edgecolor="none")))
ticks = [i for i in range(len(keys)) if keys[i].hour < 4 and keys[i].weekday() == 0]
ax.set_xticks(ticks)
ax.set_xticklabels([keys[i].strftime("%m/%d") for i in ticks], color="#bbbbbb", fontsize=8)
ax.tick_params(axis="y", colors="#dddddd", labelsize=10)
ax.set_xlim(max(0, lo_i - 60), len(keys) + 38)
vis = range(max(0, lo_i - 60), len(keys))
ax.set_ylim(min(L[i] for i in vis) - 200, max(H[i] for i in vis) + 200)
y0, y1 = ax.get_ylim()
gap = (y1 - y0) * 0.034                       # 一個標籤嘅高度（相對 y 範圍）
placed = []
for y, txt, box in sorted(labels, key=lambda t: t[0]):
    ty = max(y, placed[-1] + gap) if placed else y
    placed.append(ty)
    if abs(ty - y) > 1:                       # 被推開咗：劃條細線連返原本價位
        ax.plot([len(keys) + 12, len(keys) + 13], [y, ty], color="#888888", linewidth=0.6)
    ax.text(len(keys) + 13, ty, txt, color="#ffffff", va="center", fontsize=12, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.25", **box))
ax.grid(color="#2a2e39", linewidth=0.5)
for s in ax.spines.values():
    s.set_color("#2a2e39")
ax.legend(loc="upper left", facecolor="#131722", labelcolor="#dddddd", fontsize=9)
ax.set_title(f"恒指即月期貨 4 小時線（日市＋夜市，香港時間）　斐波那契：{keys[lo_i]:%m/%d} 低 {lo:,.0f} → {keys[hi_i]:%m/%d} 高 {hi:,.0f}"
             f"　截至 {keys[-1]:%m-%d %H:%M}", color="#eeeeee", fontsize=12)
plt.tight_layout()
plt.savefig(out, facecolor=fig.get_facecolor())
s50, s100, s200 = sma(50)[-1], sma(100)[-1], sma(200)[-1]
print(json.dumps({"lo": [str(keys[lo_i]), lo], "hi": [str(keys[hi_i]), hi], "last": C[-1], "asof": str(keys[-1]),
                  "levels": {f"{r:g}": round(price[r]) for r in levels},
                  "sma50": round(s50), "sma100": round(s100), "sma200": round(s200)}, ensure_ascii=False))
