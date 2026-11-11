"""龍飛陣模仿使用者畫圖（使用者 11-11：「圖你自己畫出來睇吓同我差幾遠」）。

照使用者 TradingView 4 小時圖嘅畫法：深色底、紅綠 K、🟠50／🟢100／🔴200 SMA、桃紅水平關鍵位＋右邊黃色大字、
白框缺口區、白色下降壓力線、黃色虛線、低點箭嘴。數據：GCS ops/longfei/analyst/data/<代號>.json 嘅 1 小時線 → 4 小時。
冇成交量數據，所以畫唔到成交量分布（POC 只可以引用使用者數字，畫成橙色水平線）。

用法：python3 research/longfei_analyst/mimic/charts.py --spec research/longfei_analyst/mimic/spec_<日期>.json --out <資料夾> [--upload]
spec：{"<代號>": {"title":…, "show": 根數, "levels": [[價, "solid|dash", 標籤?]], "boxes": [[低, 高, 起始日期, 標籤]],
        "lines": [[價, 顏色, 標籤]], "trend": [[日期1, 日期2, 標籤]], "marks": [[日期, "low|high", 標籤]], "ylim": [低, 高]}}
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pack  # noqa: E402

BG, UP, DN = "#131722", "#26a69a", "#ef5350"
PINK, YEL = "#e91e63", "#ffd54f"
SMA_COL = ((50, "#ff9800"), (100, "#4caf50"), (200, "#e53935"))


def clean_h1(h1, d1):
    """1 小時線個別壞 tick（高低位超出當日日線高低）夾返入日線範圍。"""
    rng = {x[0]: (x[3], x[2]) for x in d1}
    out = []
    for k, o, h, lo, c in h1:
        r = rng.get(k[:10])
        if r and not k.endswith(("18:00", "19:00", "20:00", "21:00", "22:00", "23:00")):
            h, lo = min(h, r[1]), max(lo, r[0])
        out.append([k, o, max(h, o, c), min(lo, o, c), c])
    return out


def profile(doc, since, until=None, bins=60):
    """成交量分布：由 since（YYYY-MM-DD）起，每支 1 小時 K 嘅成交量平均分落佢高低位之間嘅價格格仔。
    回傳 (格仔下限列表, 格闊, 每格成交量, POC 價)；冇成交量數據回傳 None。"""
    vol = doc.get("h1_vol") or {}
    rows_ = [(o, h, lo, c, vol.get(k, 0)) for k, o, h, lo, c in doc["h1"] if k[:10] >= since and (not until or k[:10] <= until)]
    rows_ = [r for r in rows_ if r[4] > 0]
    if len(rows_) < 20:
        return None
    lo_v, hi_v = min(r[2] for r in rows_), max(r[1] for r in rows_)
    w = (hi_v - lo_v) / bins
    acc = [0.0] * bins
    for o, h, lo, c, v in rows_:
        a, b = int((lo - lo_v) / w), min(bins - 1, int((h - lo_v) / w))
        for i in range(a, b + 1):
            acc[i] += v / (b - a + 1)
    j = max(range(bins), key=lambda i: acc[i])
    return [lo_v + i * w for i in range(bins)], w, acc, lo_v + (j + 0.5) * w


def draw(name, doc, sp, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Rectangle
    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        if os.path.exists(f):
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
            break
    bars = pack.h4(clean_h1(doc["h1"], doc["d1"]))
    C = [b[4] for b in bars]
    n = len(bars)
    show = sp.get("show", 70)
    start = n - show
    right = int(show * 0.75)                      # 右邊留白放標籤
    idx = {}
    for i, b in enumerate(bars):
        idx.setdefault(b[0][:10], i)

    def day_extreme(day, kind):
        js = [i for i, b in enumerate(bars) if b[0][:10] == day]
        j = max(js, key=lambda i: bars[i][2]) if kind == "high" else min(js, key=lambda i: bars[i][3])
        return j, bars[j][2] if kind == "high" else bars[j][3]

    fig, ax = plt.subplots(figsize=(18, 10), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for lo_, hi_, since, label in sp.get("boxes", []):
        x0 = max(start, idx.get(since, start))
        x1 = n + int(right * 0.25)
        ax.add_patch(Rectangle((x0, lo_), x1 - x0, hi_ - lo_, facecolor="#ffffff", alpha=0.12, edgecolor="none"))
        ax.add_patch(Rectangle((x0, lo_), x1 - x0, hi_ - lo_, fill=False, edgecolor="#ffffff", linewidth=1.3))
        if label:
            ax.text(x1 - 0.5, hi_, label, color="#ffffff", fontsize=11, va="bottom", ha="right", style="italic")
    for since, label in sp.get("profile", []):
        pf = profile(doc, since)
        if pf:
            edges, w, acc, poc = pf
            x0 = max(start, idx.get(since, start))
            m = max(acc)
            for e, v in zip(edges, acc):
                ax.add_patch(Rectangle((x0, e), v / m * show * 0.28, w * 0.9, facecolor="#2962ff" if abs(e + w / 2 - poc) > w else "#ffb300",
                                       alpha=0.45, edgecolor="none"))
            ax.hlines(poc, x0, xr, color="#ff9800", linewidth=1.2)
            ax.text(xr - 1, poc, f"{label} POC {poc:,.2f}" if poc < 1000 else f"{label} POC {poc:,.0f}", color="#ffffff",
                    fontsize=12, va="bottom", ha="right", style="italic")
            print(name, "POC", since, round(poc, 2))
    for i in range(start, n):
        _, o, h, lo, cl = bars[i]
        col = UP if cl >= o else DN
        ax.vlines(i, lo, h, color=col, linewidth=1)
        ax.add_patch(Rectangle((i - 0.36, min(o, cl)), 0.72, max(abs(cl - o), (h - lo) * 0.002 + 1e-9), color=col))
    smas = {}
    for k, col in SMA_COL:
        xs = [i for i in range(start, n) if i >= k - 1]
        ys = [sum(C[i - k + 1:i + 1]) / k for i in xs]
        if ys:
            ax.plot(xs, ys, color=col, linewidth=1.1)
            smas[k] = ys[-1]
    xr = n + right
    for lv in sp.get("levels", []):
        p, style = lv[0], lv[1]
        label = lv[2] if len(lv) > 2 else (f"{p:,.0f}" if p >= 1000 else f"{p:,.2f}")
        ax.hlines(p, start, xr, color=PINK, linewidth=1.3, linestyles="--" if style == "dash" else "-")
        ax.text(n + right * 0.45, p, label, color=YEL, fontsize=17, va="bottom", ha="center")
    for p, col, label in sp.get("lines", []):
        ax.hlines(p, start, xr, color=col, linewidth=1.3, linestyles="--")
        ax.text(xr - 1, p, label, color="#ffffff", fontsize=12, va="top", ha="right", style="italic")
    for d1_, d2_, label in sp.get("trend", []):
        (i1, p1), (i2, p2) = day_extreme(d1_, "high"), day_extreme(d2_, "high")
        slope = (p2 - p1) / (i2 - i1)
        xa, xb = max(start, i1), n + int(right * 0.9)
        ax.plot([xa, xb], [p1 + slope * (xa - i1), p1 + slope * (xb - i1)], color="#ffffff", linewidth=1.6)
        xt = n + int(right * 0.75)
        ax.text(xt, p1 + slope * (xt - i1), label, color="#ffb74d", fontsize=12, va="bottom", ha="center", clip_on=True)
    for day, kind, label in sp.get("marks", []):
        j, p = day_extreme(day, kind)
        if j >= start:
            ax.annotate(label, (j, p), xytext=(0, -42 if kind == "low" else 30), textcoords="offset points", color="#ffffff",
                        fontsize=12, ha="center", arrowprops=dict(arrowstyle="-|>", color="#ffeb3b", lw=2))
    ax.axhline(C[-1], color="#888888", ls=":", linewidth=0.8)
    ax.text(xr, C[-1], f" {C[-1]:,.2f}", color="#ffffff", fontsize=10, va="center", ha="left",
            bbox=dict(facecolor=UP if C[-1] >= bars[-1][1] else DN, edgecolor="none", pad=2))
    ticks = [i for i in range(start, n) if i == start or bars[i][0][:10] != bars[i - 1][0][:10]]
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(int(bars[i][0][8:10])) if bars[i][0][8:10] != "01" else
                        datetime.strptime(bars[i][0][:10], "%Y-%m-%d").strftime("%b") for i in ticks], color="#bbbbbb", fontsize=9)
    ax.tick_params(axis="y", colors="#dddddd", labelsize=10)
    ax.yaxis.tick_right()
    ax.set_xlim(start - 1, xr)
    if sp.get("ylim"):
        ax.set_ylim(*sp["ylim"])
    else:
        lo_v, hi_v = min(b[3] for b in bars[start:]), max(b[2] for b in bars[start:])
        ax.set_ylim(lo_v - (hi_v - lo_v) * 0.08, hi_v + (hi_v - lo_v) * 0.08)
    ax.grid(color="#1f2430", linewidth=0.5)
    for s in ax.spines.values():
        s.set_color("#2a2e39")
    b = bars[-1]
    head = (f"{sp['title']} · 4h　O{b[1]:,.2f} H{b[2]:,.2f} L{b[3]:,.2f} C{b[4]:,.2f}\n"
            + "\n".join(f"SMA ({k}, close)  {smas[k]:,.2f}" for k, _ in SMA_COL if k in smas))
    ax.text(0.005, 0.99, head, transform=ax.transAxes, color="#dddddd", fontsize=10, va="top", ha="left", linespacing=1.5)
    for (k, col), y in zip(SMA_COL, (0.955, 0.932, 0.909)):
        ax.plot([0.001, 0.004], [y, y], transform=ax.transAxes, color=col, linewidth=3)
    ax.text(0.005, 0.012, f"龍飛陣模仿使用者畫法　截至 {b[0]}（美東，4 小時 K 開始時間）", transform=ax.transAxes,
            color="#888888", fontsize=9)
    plt.tight_layout()
    plt.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {"last": C[-1], "sma": smas, "bars": bars[-8:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    os.makedirs(a.out, exist_ok=True)
    for name, sp in spec.items():
        if name.startswith("_"):
            continue
        doc = json.loads(pack.gcs_cat(pack.DATA + f"{name}.json"))
        path = os.path.join(a.out, f"{name}_4h_user.png")
        info = draw(name, doc, sp, path)
        print(name, path, round(info["last"], 2), {k: round(v, 2) for k, v in info["sma"].items()})
        if a.upload:
            pack.gcs_put(f"{pack.OUT}charts/{spec['_date']}/{name}_4h_user.png", path)


if __name__ == "__main__":
    main()
