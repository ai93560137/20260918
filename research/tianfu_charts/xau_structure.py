"""🌌 XAUUSD 週線市場結構（HH／HL／LH／LL）揀斐波那契區間（只畫圖，唔回測）。

使用者 11-05：「市場結構：高點低點一路升（HH＋HL）＝升勢，一路跌（LH＋LL）＝跌勢；用呢個方法揀區間；週線圖，可能揀多兩三個區間；先畫出嚟先唔好做回測住」。
- 擺動點＝分形（高位高過左邊 K 根、唔低過右邊 K 根；低點相反），高低交替（連續同類只留最極端）。
- 標 HH／LH（同上一個擺動高比）、HL／LL（同上一個擺動低比）。
- 一段升勢：由起步低點開始，一路 HH＋HL；出現 LL（跌穿最近 HL）＝結構破壞，升段完結喺之前最高點，跌段由嗰度開始。跌段反過嚟（出現 HH 升穿最近 LH）。
- 畫最近 N 段（包括而家未完嗰段）嘅斐波那契：升段由頂向下量回撤、跌段由底向上量反彈。
使用者 11-06：「週線結構圖放上網頁，你理解無錯。日、月、H4、H1 都係咁做」。
用法：python3 research/tianfu_charts/xau_structure.py <h1.csv> <輸出.png> <M|W|D|H4|H1> [段數=3] [K=2]
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xau_fib as XF  # noqa: E402

RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
NAMES = {"M": "月線", "W": "週線", "D": "日線", "H4": "4 小時線", "H1": "1 小時線"}
LEG_COLORS = ("#ffb74d", "#4dd0e1", "#ba68c8", "#81c784")


def pivots(H, L, k):
    raw = []
    for i in range(k, len(H) - k):
        if H[i] > max(H[i - k:i]) and H[i] >= max(H[i + 1:i + k + 1]):
            raw.append([i, "H", H[i]])
        if L[i] < min(L[i - k:i]) and L[i] <= min(L[i + 1:i + k + 1]):
            raw.append([i, "L", L[i]])
    out = []
    for p in raw:                                  # 高低交替：連續同類留最極端
        if out and out[-1][1] == p[1]:
            if (p[1] == "H" and p[2] > out[-1][2]) or (p[1] == "L" and p[2] < out[-1][2]):
                out[-1] = p
        else:
            out.append(p)
    lastH = lastL = None
    for p in out:
        if p[1] == "H":
            p.append("" if lastH is None else ("HH" if p[2] > lastH else "LH")); lastH = p[2]
        else:
            p.append("" if lastL is None else ("HL" if p[2] > lastL else "LL")); lastL = p[2]
    return out


def legs(piv, H, L):
    """結構段：[(start_i, end_i, up)]；最後一段 end_i＝之後最極端嗰根（未完）。"""
    if len(piv) < 3:
        return []
    res = []
    up = piv[1][1] == "H"                          # 第一個係低點跟住高點＝升段起步
    start = piv[0][0] if piv[0][1] == ("L" if up else "H") else piv[1][0]
    ext = start
    guard = None                                   # 升段：最近 HL；跌段：最近 LH
    for i, typ, price, _ in piv:
        if up:
            if typ == "H" and H[i] >= H[ext]:
                ext = i
            if typ == "L":
                if guard is not None and price < guard:      # 同一根 K 可以又係擺動高又係擺動低（外包線），唔可以要求 ext≠start，否則會卡死
                    if ext != start:
                        res.append((start, ext, True))
                    start, up = ext, False
                    ext = i; guard = None
                    continue
                guard = price
        else:
            if typ == "L" and L[i] <= L[ext]:
                ext = i
            if typ == "H":
                if guard is not None and price > guard:
                    if ext != start:
                        res.append((start, ext, False))
                    start, up = ext, True
                    ext = i; guard = None
                    continue
                guard = price
    n = len(H)                                     # 未完嗰段：極端用到最後一根
    if up:
        ext = max(range(start, n), key=lambda x: H[x])
    else:
        ext = min(range(start, n), key=lambda x: L[x])
    if ext != start:
        res.append((start, ext, up))
    return res


def main():
    src, out = sys.argv[1], sys.argv[2]
    tf = sys.argv[3] if len(sys.argv) > 3 else "W"
    nlegs = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    k = int(sys.argv[5]) if len(sys.argv) > 5 else 2
    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        if os.path.exists(f):
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
            break
    bars, asof = XF.load(src, tf)
    keys = sorted(bars)
    O = [bars[x][0] for x in keys]; H = [bars[x][1] for x in keys]; L = [bars[x][2] for x in keys]; C = [bars[x][3] for x in keys]
    piv = pivots(H, L, k)
    allg = legs(piv, H, L)
    # 大段：幅度 ≥ 段尾價 12%（濾走一兩週嘅細段），取最近 nlegs-1 段；再加「最近一浪」＝而家呢段入面最後一個反向擺動點 → 而家極端
    # 大段門檻＝3 × ATR(14)（各時間框通用；週線約等於幅度 12%）
    trs = [max(H[i], C[i - 1]) - min(L[i], C[i - 1]) for i in range(max(1, len(C) - 14), len(C))]
    atr = sum(trs) / len(trs)
    big = [g for g in allg if abs((H[g[1]] - L[g[0]]) if g[2] else (H[g[0]] - L[g[1]])) >= 3 * atr]
    lg = big[-(nlegs - 1):] if nlegs > 1 else big[-1:]
    if allg:
        a, b, up = allg[-1]
        inner = [p for p in piv if a < p[0] < b and p[1] == ("L" if up else "H")]
        if inner and inner[-1][0] != a:
            lg.append((inner[-1][0], b, up))
    first = max(0, min(lg[0][0], lg[0][1]) - 12) if lg else max(0, len(keys) - 160)
    n = len(keys)
    fig, ax = plt.subplots(figsize=(16, 9), dpi=110)
    fig.patch.set_facecolor("#131722"); ax.set_facecolor("#131722")
    for i in range(first, n):
        col = "#26a69a" if C[i] >= O[i] else "#ef5350"
        ax.vlines(i, L[i], H[i], color=col, linewidth=0.7)
        ax.vlines(i, min(O[i], C[i]), max(O[i], C[i]), color=col, linewidth=2.2)
    zz = [p for p in piv if p[0] >= first]         # 結構標籤同之字線
    if zz:
        ax.plot([p[0] for p in zz], [p[2] for p in zz], color="#777777", linewidth=0.7, ls=":")
    for i, typ, price, lab in zz:
        if lab:
            good = lab in ("HH", "HL")
            ax.annotate(lab, (i, price), xytext=(0, 9 if typ == "H" else -15), textcoords="offset points", ha="center",
                        fontsize=9, fontweight="bold", color="#66bb6a" if good else "#ef5350")
    XL = max(6, (n - first) // 14)
    labels, info = [], []
    for li, (a, b, up) in enumerate(lg):
        col = LEG_COLORS[li % len(LEG_COLORS)]
        hi_i, lo_i = (b, a) if up else (a, b)
        hi, lo = H[hi_i], L[lo_i]
        x0 = min(a, b)
        ax.plot([a, b], [L[a] if up else H[a], H[b] if up else L[b]], color=col, linewidth=2.2, alpha=0.9)
        lvl = {r: (hi - (hi - lo) * r) if up else (lo + (hi - lo) * r) for r in RATIOS}
        for r, p in lvl.items():
            ax.hlines(p, x0, n + XL - 1, color=col, linewidth=1.0 if r in (0.382, 0.5, 0.618) else 0.6,
                      ls="-" if r in (0.382, 0.5, 0.618) else "--", alpha=0.85)
            labels.append((p, f"區間{li + 1} {r:g}  {p:,.0f}", dict(facecolor="#131722", edgecolor=col, linewidth=1.2)))
        kind = "升段回撤" if up else "跌段反彈"
        tag = "（最近一浪）" if li == len(lg) - 1 and len(lg) > 1 and a != lg[-2][0] and b == lg[-2][1] else ("（未完）" if b == n - 1 or b == lg[-1][1] else "")
        info.append({"leg": li + 1, "kind": kind + tag, "from": [keys[a].strftime("%Y-%m-%d %H:%M"), L[a] if up else H[a]],
                     "to": [keys[b].strftime("%Y-%m-%d %H:%M"), H[b] if up else L[b]], "levels": {f"{r:g}": round(p, 1) for r, p in lvl.items()}})
        ax.annotate(f"區間{li + 1}：{kind}{tag}", ((a + b) / 2, (H[b] + L[a]) / 2 if up else (H[a] + L[b]) / 2),
                    color=col, fontsize=11, fontweight="bold", ha="center")
    ax.axhline(C[-1], color="#2962ff", ls=":", linewidth=0.8)
    labels.append((C[-1], f"現價  {C[-1]:,.0f}", dict(facecolor="#2962ff", edgecolor="none")))
    if tf == "M":
        ticks, tfmt = [i for i in range(first, n) if keys[i].month == 1], "%Y"
    elif tf == "W":
        ticks, tfmt = [i for i in range(first, n) if i == first or (keys[i].month != keys[i - 1].month and keys[i].month % 3 == 1)], "%Y/%m"
    elif tf == "D":
        ticks, tfmt = [i for i in range(first, n) if i == first or keys[i].month != keys[i - 1].month], "%Y/%m"
    elif tf == "H4":
        ticks, tfmt = [i for i in range(first, n) if keys[i].hour == 0 and keys[i].weekday() == 0], "%m/%d"
    else:
        ticks, tfmt = [i for i in range(first, n) if keys[i].hour == 0], "%m/%d"
    ax.set_xticks(ticks); ax.set_xticklabels([keys[i].strftime(tfmt) for i in ticks], color="#bbbbbb", fontsize=8)
    ax.tick_params(axis="y", colors="#dddddd", labelsize=10)
    ax.set_xlim(first - 2, n + XL * 4)
    lo_v, hi_v = min(L[first:]), max(H[first:]); pad = (hi_v - lo_v) * 0.04
    ax.set_ylim(lo_v - pad, hi_v + pad)
    y0, y1 = ax.get_ylim(); gap = (y1 - y0) * 0.026
    placed = []
    for y, txt, box in sorted(labels, key=lambda t: t[0]):
        ty = max(y, placed[-1] + gap) if placed else y
        placed.append(ty)
        if abs(ty - y) > (y1 - y0) * 0.002:
            ax.plot([n + XL - 1, n + XL], [y, ty], color="#888888", linewidth=0.5)
        ax.text(n + XL, ty, txt, color="#ffffff", va="center", fontsize=9, fontweight="bold", bbox=dict(boxstyle="round,pad=0.2", **box))
    ax.grid(color="#2a2e39", linewidth=0.5)
    for s in ax.spines.values():
        s.set_color("#2a2e39")
    ax.set_title(f"XAUUSD 黃金 {NAMES[tf]}・市場結構（HH／HL／LH／LL，分形 {k} 根）揀斐波那契區間（{len(lg)} 個區間）　截至 {asof:%Y-%m-%d %H:%M}（MT5 伺服器時間）",
                 color="#eeeeee", fontsize=12)
    plt.tight_layout()
    plt.savefig(out, facecolor=fig.get_facecolor())
    print(json.dumps({"tf": tf, "legs": info, "last": C[-1], "asof": str(asof)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
