"""[R289] 龍飛陣每日分析欄：計數據包、劃圖、同為之前嘅分析計分。

使用者 10-23：「根據我的思路，每天在網頁上加一個我的分析欄，我看看你能否學到我」。
思路見 STYLE.md（使用者 ES／NQ 筆記：均線 50／100／200、斐波那契、支撐跌破後回測、形態量度、成交密集區）。

數據：
- NQ／ES／SPX：GCS ops/longfei/analyst/data/{NQ,ES,SPX}.json（GitHub Actions longfei_analyst_data.yml 用 yfinance 寫，美東時間）
- HSI：GCS archive/futu_k_1m/HK.HSI_FRONT/<日>.json（1 分鐘，含夜市），增量合成後存 ops/longfei/analyst/data/HSI.json
  （交易日按港交所 T+1：17:00 後嘅夜市算下一個交易日）

用法（喺 repo 根目錄）：
  python3 research/longfei_analyst/pack.py pack --work <工作資料夾>     # 數據包 → <work>/pack.json，圖 → <work>/<市場>_4h.png、_1d.png
  python3 research/longfei_analyst/pack.py score --work <工作資料夾>    # 讀 GCS 舊分析，計命中率 → <work>/scorecard.json
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENT = [sys.executable, os.path.join(ROOT, "scripts", "gcp_agent.py")]
DATA = "ops/longfei/analyst/data/"
OUT = "ops/longfei/analyst/"
HSI_1M = "archive/futu_k_1m/HK.HSI_FRONT/"
NAMES = {"NQ": "納指 100 期貨（NQ）", "ES": "標普 500 期貨（ES）", "SPX": "標普 500 現貨（SPX）", "HSI": "恒指即月期貨（HSI）",
         "VIX": "VIX 波動率指數（現貨）", "RSP": "標普 500 等權 ETF（RSP）"}
FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1]
FIB_EXT = [1.236, 1.382, 1.618]   # [R292] 延伸：跌穿起點之後嘅目標（使用者 NQ 用 1.236）


# ---------- GCS（經 gcp_agent，唔繞過佢） ----------
def gcs_cat(obj):
    r = subprocess.run(AGENT + ["cat", "--object", obj], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


def gcs_put(obj, path):
    subprocess.run(AGENT + ["put", "--object", obj, "--file", path], check=True, capture_output=True)


def gcs_list(prefix):
    r = subprocess.run(AGENT + ["bucket", "--prefix", prefix], capture_output=True, text=True)
    return [ln.split()[-1] for ln in r.stdout.splitlines() if ln.split() and ln.split()[-1].startswith(prefix)]


# ---------- HSI：1 分鐘 → 1 小時，增量 ----------
def hsi_trade_day(t):
    d = t.date() + timedelta(days=1) if t.hour >= 17 else t.date()
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def update_hsi(work):
    raw = gcs_cat(DATA + "HSI.json")
    doc = json.loads(raw) if raw else {"symbol": "HK.HSI_FRONT", "h1": [], "days_loaded": []}
    have = set(doc["days_loaded"])
    start = date.today() - timedelta(days=420)
    todo, d = [], start
    while d <= date.today():
        if d.weekday() < 5 and d.isoformat() not in have:
            todo.append(d.isoformat())
        d += timedelta(days=1)
    todo += [x for x in sorted(have)[-2:]]                    # 最近兩日重讀（當日未完）
    h1 = {r[0]: r for r in doc["h1"]}
    for day in todo:
        txt = gcs_cat(f"{HSI_1M}{day}.json")
        if not txt:
            continue
        for b in json.loads(txt):
            t = datetime.strptime(b["time_key"], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=1)   # time_key 係完結時間
            k = t.strftime("%Y-%m-%d %H:00")
            o = h1.get(k)
            h1[k] = [k, b["open"], b["high"], b["low"], b["close"]] if o is None else \
                [k, o[1], max(o[2], b["high"]), min(o[3], b["low"]), b["close"]]
        have.add(day)
    doc["h1"] = [h1[k] for k in sorted(h1)]
    doc["days_loaded"] = sorted(have)
    d1 = {}
    for k, o, h, lo, c in doc["h1"]:
        td = hsi_trade_day(datetime.strptime(k, "%Y-%m-%d %H:%M"))
        x = d1.get(td)
        d1[td] = [td, o, h, lo, c] if x is None else [td, x[1], max(x[2], h), min(x[3], lo), c]
    doc["d1"] = [d1[k] for k in sorted(d1)]
    doc["fetched_utc"] = datetime.utcnow().isoformat(timespec="seconds")
    p = os.path.join(work, "HSI.json")
    json.dump(doc, open(p, "w"), separators=(",", ":"))
    gcs_put(DATA + "HSI.json", p)
    return doc


# ---------- 指標 ----------
def h4(h1):
    """1 小時 → 4 小時（以 00/04/08/12/16/20 開始；美股用美東、恒指用香港時間）。"""
    out = {}
    for k, o, h, lo, c in h1:
        t = datetime.strptime(k, "%Y-%m-%d %H:%M")
        key = t.replace(hour=t.hour // 4 * 4).strftime("%Y-%m-%d %H:00")
        x = out.get(key)
        out[key] = [key, o, h, lo, c] if x is None else [key, x[1], max(x[2], h), min(x[3], lo), c]
    return [out[k] for k in sorted(out)]


def sma(closes, n, back=0):
    end = len(closes) - back
    return round(sum(closes[end - n:end]) / n, 2) if end >= n else None


def ma_block(bars):
    c = [b[4] for b in bars]
    blk = {}
    for n in (50, 100, 200):
        v, prev = sma(c, n), sma(c, n, 5)
        if v is not None:
            blk[f"sma{n}"] = {"value": v, "slope": "向上" if prev and v > prev else "向下" if prev and v < prev else "平",
                              "price_vs": "上" if c[-1] > v else "下"}
    s50, s200 = [sma(c, 50, i) for i in range(0, 60)], [sma(c, 200, i) for i in range(0, 60)]
    cross = None
    for i in range(59):
        if None in (s50[i], s200[i], s50[i + 1], s200[i + 1]):
            break
        if (s50[i] - s200[i]) * (s50[i + 1] - s200[i + 1]) < 0:
            cross = {"type": "金叉" if s50[i] > s200[i] else "死叉", "bar": bars[len(bars) - 1 - i][0]}
            break
    blk["cross_50_200"] = cross
    # [R290] 均線糾結（使用者 10-24 SPX 筆記）：50／100 貼近、200 走平 → 今年 3 月跌破前嘅狀態
    s50, s100, s200, s200_20 = sma(c, 50), sma(c, 100), sma(c, 200), sma(c, 200, 20)
    if None not in (s50, s100, s200, s200_20):
        blk["tangle"] = {"spread_50_100_pct": round(abs(s50 - s100) / c[-1] * 100, 2),
                         "sma200_slope_20bars_pct": round((s200 / s200_20 - 1) * 100, 2),
                         "dist_to_sma200_pct": round((c[-1] / s200 - 1) * 100, 2)}
    return blk


def open_gaps(d1, lookback=120, min_pct=0.3):
    """[R290] 日線未補缺口：跳空之後到而家都未有 K 線返入缺口範圍（使用者講「補 7/30 缺口 7,314–7,370」）。
    缺口用昨日收市計（同使用者一樣：7/29 收 7,316 → 7/30 低 7,371），細過 min_pct% 嘅唔計。"""
    gaps = []
    rows = d1[-lookback:]
    for i in range(1, len(rows)):
        prev, cur = rows[i - 1], rows[i]
        if cur[3] > prev[4] * (1 + min_pct / 100):            # 向上跳空：缺口 = 昨收 → 今低
            lo, hi, kind = prev[4], cur[3], "向上缺口（下方支撐）"
        elif cur[2] < prev[4] * (1 - min_pct / 100):          # 向下跳空：缺口 = 今高 → 昨收
            lo, hi, kind = cur[2], prev[4], "向下缺口（上方壓力）"
        else:
            continue
        after = rows[i + 1:]
        filled = any(b[3] <= lo for b in after) if kind.startswith("向上") else any(b[2] >= hi for b in after)
        if not filled:
            gaps.append({"date": cur[0], "kind": kind, "low": lo, "high": hi})
    return gaps[-6:]


def fib_block(bars4, days=90, per_day=6):
    """最近 days 日最高點，同佢之前 days 日內嘅最低點（升浪回撤；同 hsi_fib 一樣由高點往前揾）。
    使用者 10-30「日線圖波段選擇不對，沒有選圖中的最低點」：舊版只喺「最近 90 日」入面揾低點，
    低點啱啱跌出 90 日（例如 NQ 07-29）就揀咗次低點。per_day：每日幾支 K（4 小時 6、日線 1）。"""
    last = datetime.strptime(bars4[-1][0], "%Y-%m-%d %H:%M")
    idx = [i for i, b in enumerate(bars4) if (last - datetime.strptime(b[0], "%Y-%m-%d %H:%M")).days <= days]
    hi_i = max(idx, key=lambda i: bars4[i][2])
    lo_i = min(range(max(0, hi_i - per_day * days), hi_i + 1), key=lambda i: bars4[i][3])
    a, b, kind = lo_i, hi_i, "升浪回撤"
    lo, hi = bars4[a][3], bars4[b][2]
    return {"kind": kind, "low": [bars4[a][0], lo], "high": [bars4[b][0], hi],
            "levels": {f"{r:g}": round(hi - (hi - lo) * r, 2) for r in FIB},
            "ext": {f"{r:g}": round(hi - (hi - lo) * r, 2) for r in FIB_EXT}, "_idx": (a, b)}


def pivots(d1, k=3, n=6):
    """日線分形高低點（左右各 k 支），最近 n 個。"""
    hs, ls = [], []
    for i in range(k, len(d1) - k):
        if d1[i][2] == max(b[2] for b in d1[i - k:i + k + 1]):
            hs.append([d1[i][0], d1[i][2]])
        if d1[i][3] == min(b[3] for b in d1[i - k:i + k + 1]):
            ls.append([d1[i][0], d1[i][3]])
    return hs[-n:], ls[-n:]


def break_retest(d1, level, lookback=40):
    """收市跌穿 level 之後有冇反彈掂返（最高 ≥ level×0.997）但收唔返上面；同埋而家企唔企返上面。"""
    rows = d1[-lookback:]
    broke = next((i for i in range(1, len(rows)) if rows[i - 1][4] >= level > rows[i][4]), None)
    if broke is None:
        return None
    retest = next((rows[j][0] for j in range(broke + 1, len(rows))
                   if rows[j][2] >= level * 0.997 and rows[j][4] < level), None)
    return {"level": level, "broke_on": rows[broke][0], "retest_failed_on": retest, "now_above": rows[-1][4] > level}


def confluence(last, d_ma, h_ma, fib, hs, ls, gaps, tol_pct=0.4):
    """[R292] 目標要重疊（推理第 6 步）：將各種方法計出嚟嘅位放埋一齊，相距 tol_pct% 以內就歸一組；
    兩種或以上方法重疊先列出，按離現價遠近排。每個位都寫明出處，分析要引用呢度嘅計算。"""
    lv = [(f"日線 {k.upper()}", v["value"], "均線") for k, v in d_ma.items() if k.startswith("sma")]
    lv += [(f"4 小時 {k.upper()}", v["value"], "均線") for k, v in h_ma.items() if k.startswith("sma")]
    lv += [(f"斐波那契 {r}", p, "斐波那契") for r, p in fib["levels"].items() if r not in ("0", "1")]
    lv += [(f"斐波那契延伸 {r}", p, "斐波那契") for r, p in fib["ext"].items()]
    lv += [(f"波段起點 {fib['low'][0][:10]}", fib["low"][1], "擺動點"), (f"波段高點 {fib['high'][0][:10]}", fib["high"][1], "擺動點")]
    lv += [(f"日線擺動低 {d}", p, "擺動點") for d, p in ls] + [(f"日線擺動高 {d}", p, "擺動點") for d, p in hs]
    for g in gaps:
        lv += [(f"缺口 {g['date']} 下沿", g["low"], "缺口"), (f"缺口 {g['date']} 上沿", g["high"], "缺口")]
    lv.sort(key=lambda x: x[1])
    groups, cur = [], [lv[0]] if lv else []
    for x in lv[1:]:
        if (x[1] - cur[0][1]) / cur[0][1] * 100 <= tol_pct:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        kinds = {k for _, _, k in g}
        if len(kinds) < 2:
            continue
        lo, hi = min(p for _, p, _ in g), max(p for _, p, _ in g)
        mid = (lo + hi) / 2
        out.append({"zone": [round(lo, 2), round(hi, 2)], "side": "上方壓力" if mid > last else "下方支撐",
                    "dist_pct": round((mid / last - 1) * 100, 2), "methods": sorted(kinds),
                    "members": [f"{n} {p:,.2f}" for n, p, _ in g]})
    out.sort(key=lambda z: abs(z["dist_pct"]))
    return out[:8]


def market_pack(name, doc):
    d1, bars4 = doc["d1"], h4(doc["h1"])
    hs, ls = pivots(d1)
    last = d1[-1]
    d_ma, h_ma = ma_block(d1), ma_block(bars4)
    fib = fib_block(bars4)
    gaps = open_gaps(d1)
    checks = [x for x in [break_retest(d1, lv) for _, lv in ls] +
              [break_retest(d1, d_ma[k]["value"]) for k in ("sma50", "sma100") if k in d_ma] if x]
    return {"market": name, "name": NAMES[name], "last": last[4], "last_bar_1d": last[0], "last_bar_4h": bars4[-1][0],
            "prev_day": {"high": d1[-2][2], "low": d1[-2][3], "close": d1[-2][4]},
            "chg_1d_pct": round((last[4] / d1[-2][4] - 1) * 100, 2),
            "daily_ma": d_ma, "h4_ma": h_ma, "fib_4h": {k: v for k, v in fib.items() if k != "_idx"},
            "swing_highs_1d": hs, "swing_lows_1d": ls, "break_retest": checks,
            "hi_60d": max(b[2] for b in d1[-60:]), "lo_60d": min(b[3] for b in d1[-60:]),
            "open_gaps_1d": gaps,
            "confluence": confluence(last[4], d_ma, h_ma, fib, hs, ls, gaps)}, bars4, fib


# ---------- 圖 ----------
def chart(path, bars, title, fib=None, show=160, tf=""):
    """[R365] 使用者 10-30「恒指即月期貨 4 小時線・斐波那契回撤圖表樣式很好，所有圖表同一樣式」：
    照 research/longfei_lessons/hsi_fib.py（R363／R364）：底色 #131722、陰陽燭 #26a69a／#ef5350、SMA50／100／200、
    回撤線 pal 色、右邊白色粗體加框標籤一欄自動排開（均線框跟線色、現價藍底）、標題一行寫波段同截至時間、15×8 吋 110dpi。
    bars：[[時間字串, 開, 高, 低, 收], …]；tf 寫入標題（例如「240 分鐘圖（4 小時 K 線）」）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        if os.path.exists(f):
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
            break
    daily = len(bars[-1][0]) <= 10
    C = [b[4] for b in bars]
    pad_n = 40 if daily else 60
    start = max(0, len(bars) - show)
    if fib:                                   # 同 hsi_fib：由波段低點前 pad_n 支開始畫
        a = fib["_idx"][0]
        start = max(0, a - pad_n)
        # 使用者 10-30「沒有選圖中的最低點」：低點之前如果有更低嘅 K，就由佢之後先開始畫，保證波段低點係圖中最低
        lower = [i for i in range(start, a) if bars[i][3] < bars[a][3]]
        if lower:
            start = lower[-1] + 1
    n = len(bars)
    xl = 10 if daily else 13                  # 右邊標籤欄起點（離最後一根 K 幾多格）
    fig, ax = plt.subplots(figsize=(15, 8), dpi=110)
    fig.patch.set_facecolor("#131722")
    ax.set_facecolor("#131722")
    for i in range(start, n):
        _, o, h, lo, cl = bars[i]
        col = "#26a69a" if cl >= o else "#ef5350"
        ax.vlines(i, lo, h, color=col, linewidth=0.7)
        ax.vlines(i, min(o, cl), max(o, cl), color=col, linewidth=2.6)
    labels = []
    for k, col in ((50, "#f5c542"), (100, "#4caf50"), (200, "#e53935")):
        xs = list(range(max(start, k - 1), n))
        ys = [sum(C[i - k + 1:i + 1]) / k for i in xs]
        ax.plot(xs, ys, color=col, linewidth=1, label=f"SMA {k}")
        if ys:
            labels.append((ys[-1], f"SMA{k}  {ys[-1]:,.0f}", dict(facecolor=col, edgecolor="none", alpha=0.6)))
    if fib:
        pal = {"0": "#9e9e9e", "0.236": "#e53935", "0.382": "#66bb6a", "0.5": "#66bb6a", "0.618": "#26a69a",
               "0.786": "#42a5f5", "0.886": "#42a5f5", "1": "#9e9e9e"}
        lo_i, hi_i = fib["_idx"][0], fib["_idx"][1]
        for r, p in fib["levels"].items():
            ax.hlines(p, lo_i, n + xl - 1, color=pal[r], linewidth=1.1)
            labels.append((p, f"{r}  {p:,.0f}", dict(facecolor="#131722", edgecolor=pal[r], linewidth=1.2)))
        ax.plot([lo_i, hi_i], [fib["low"][1], fib["high"][1]], ls="--", color="#bbbbbb", linewidth=0.8)
        ax.annotate(fib["low"][0][5:10].replace("-", "/"), (lo_i, fib["low"][1]), xytext=(0, -18),
                    textcoords="offset points", color="#ffd54f", ha="center")
        ax.annotate(fib["high"][0][5:10].replace("-", "/"), (hi_i, fib["high"][1]), xytext=(0, 10),
                    textcoords="offset points", color="#ffd54f", ha="center")
    ax.axhline(C[-1], color="#2962ff", ls=":", linewidth=0.8)
    labels.append((C[-1], f"現價  {C[-1]:,.2f}" if C[-1] < 1000 else f"現價  {C[-1]:,.0f}", dict(facecolor="#2962ff", edgecolor="none")))
    if daily:
        ticks = [i for i in range(start, n) if i == start or bars[i][0][:7] != bars[i - 1][0][:7]]
    else:
        ticks = [i for i in range(start, n) if i == start or bars[i][0][:10] != bars[i - 1][0][:10]
                 and datetime.strptime(bars[i][0][:10], "%Y-%m-%d").weekday() == 0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([bars[i][0][5:10].replace("-", "/") for i in ticks], color="#bbbbbb", fontsize=8)
    ax.tick_params(axis="y", colors="#dddddd", labelsize=10)
    ax.set_xlim(start, n + (30 if daily else 38))
    lo_v = min(b[3] for b in bars[start:])
    hi_v = max(b[2] for b in bars[start:])
    pad = (hi_v - lo_v) * 0.05
    ax.set_ylim(lo_v - pad, hi_v + pad)
    y0, y1 = ax.get_ylim()
    gap = (y1 - y0) * 0.034                   # 一個標籤嘅高度
    labels.sort(key=lambda t: t[0])
    placed = []
    for y, _, _ in labels:                    # 由下而上推開，再由頂壓返落嚟（唔好出圖外）
        placed.append(max(y, placed[-1] + gap) if placed else max(y, y0 + gap / 2))
    for i in range(len(placed) - 1, -1, -1):
        placed[i] = min(placed[i], (y1 - gap / 2) if i == len(placed) - 1 else placed[i + 1] - gap)
    for (y, txt, box), ty in zip(labels, placed):
        if abs(ty - y) > (y1 - y0) * 0.001:   # 被推開咗：劃條細線連返原本價位
            ax.plot([n + xl - 1, n + xl], [y, ty], color="#888888", linewidth=0.6)
        ax.text(n + xl, ty, txt, color="#ffffff", va="center", fontsize=12, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", **box))
    ax.grid(color="#2a2e39", linewidth=0.5)
    for sp in ax.spines.values():
        sp.set_color("#2a2e39")
    ax.legend(loc="upper left", facecolor="#131722", labelcolor="#dddddd", fontsize=9)
    ax.set_title((f"【{tf}】" if tf else "") + f"{title}　截至 {bars[-1][0][5:16]}", color="#eeeeee", fontsize=12)
    plt.tight_layout()
    plt.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)


def cmd_pack(work):
    os.makedirs(work, exist_ok=True)
    docs = {}
    for name in ("NQ", "ES", "SPX", "VIX", "RSP"):        # [R304] VIX：使用者 10-27 筆記；RSP：10-29 板塊輪動
        raw = gcs_cat(DATA + f"{name}.json")
        if raw:
            docs[name] = json.loads(raw)
    docs["HSI"] = update_hsi(work)
    pack = {"generated": datetime.utcnow().isoformat(timespec="seconds") + "Z", "markets": {}}
    for name, doc in docs.items():
        mp, bars4, fib = market_pack(name, doc)
        if name != "HSI":
            mp["data_fetched_utc"] = doc.get("fetched_utc")
        pack["markets"][name] = mp
        tz = "香港時間" if name == "HSI" else "美東時間"
        # 使用者 10-29「每日分析附圖…回撤位不用」：分析用 _4h.png 唔畫斐波那契；_4h_fib.png 保留畀「📐 斐波那契回撤分析圖」頁
        chart(os.path.join(work, f"{name}_4h.png"), bars4, f"{NAMES[name]} 4 小時線（{tz}）",
              tf="240 分鐘圖（4 小時 K 線）")
        chart(os.path.join(work, f"{name}_4h_fib.png"), bars4,
              f"{NAMES[name]} 4 小時線（{tz}）　斐波那契：{fib['low'][0][5:10]} 低 {fib['low'][1]:,.0f} → "
              f"{fib['high'][0][5:10]} 高 {fib['high'][1]:,.0f}", fib=fib, tf="240 分鐘圖（4 小時 K 線）")
        chart(os.path.join(work, f"{name}_1d.png"), doc["d1"], f"{NAMES[name]} 日線", show=260, tf="日線圖（每支 K＝1 日）")
        # 使用者 10-29「日線圖都加回撤位，數字用白色」：日線斐波那契，畀「📐 斐波那契回撤分析圖」頁
        fib1 = fib_block([[r[0] + " 00:00", *r[1:]] for r in doc["d1"]], days=90, per_day=1)   # 同 hsi_fib：日線同 4 小時用同一個 90 日波段
        mp["fib_1d"] = {k: v for k, v in fib1.items() if k != "_idx"}
        chart(os.path.join(work, f"{name}_1d_fib.png"), doc["d1"],
              f"{NAMES[name]} 日線　斐波那契：{fib1['low'][0][5:10]} 低 {fib1['low'][1]:,.0f} → "
              f"{fib1['high'][0][5:10]} 高 {fib1['high'][1]:,.0f}", fib=fib1, show=260, tf="日線圖（每支 K＝1 日）")
    json.dump(pack, open(os.path.join(work, "pack.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(pack, ensure_ascii=False, indent=1))


# ---------- 計分 ----------
def close_on_or_after(d1, day, n):
    """day 之後第 n 個交易日收市（冇咁多日就 None）。"""
    i = next((j for j, b in enumerate(d1) if b[0] > day), None)
    return None if i is None or i + n - 1 >= len(d1) else (d1[i + n - 1][0], d1[i + n - 1][4], d1[i:i + n])


def score_call(call, d1, base_day):
    """calls 格式（每日分析 JSON 入面）：
    {"market","kind":"bias","dir":1|-1|0,"horizon":5}：horizon 日後收市方向啱唔啱（0＝橫行：變動 < 1%）
    {"market","kind":"support"|"resistance","level","horizon":5}：horizon 日內收市冇穿＝守住
    {"market","kind":"target","level","horizon":10}：horizon 日內最高／最低掂到＝達標
    """
    res = close_on_or_after(d1, base_day, call.get("horizon", 5))
    if res is None:
        return None
    end_day, end_close, path = res
    start = next(b[4] for b in reversed(d1) if b[0] <= base_day)
    k = call["kind"]
    if k == "bias":
        chg = end_close / start - 1
        got = 0 if abs(chg) < 0.01 else (1 if chg > 0 else -1)
        return {"ok": got == call["dir"], "detail": f"{base_day} {start:,.2f} → {end_day} {end_close:,.2f}（{chg:+.1%}）"}
    if k == "support":
        bad = next((b for b in path if b[4] < call["level"]), None)
        return {"ok": bad is None, "detail": "守住" if bad is None else f"{bad[0]} 收市 {bad[4]:,.2f} 跌穿"}
    if k == "resistance":
        bad = next((b for b in path if b[4] > call["level"]), None)
        return {"ok": bad is None, "detail": "企唔上" if bad is None else f"{bad[0]} 收市 {bad[4]:,.2f} 升穿"}
    if k == "target":
        down = call["level"] < start
        hit = next((b for b in path if (b[3] <= call["level"] if down else b[2] >= call["level"])), None)
        return {"ok": hit is not None, "detail": f"{hit[0]} 掂到" if hit else "未到"}
    return None


def cmd_score(work):
    os.makedirs(work, exist_ok=True)
    data = {}
    for name in ("NQ", "ES", "SPX", "HSI", "VIX", "RSP"):
        raw = gcs_cat(DATA + f"{name}.json")
        if raw:
            data[name] = json.loads(raw)["d1"]
    rows = []
    for obj in sorted(gcs_list(OUT + "daily/")):
        if not obj.endswith(".json"):
            continue
        doc = json.loads(gcs_cat(obj) or "{}")
        for call in doc.get("calls", []):
            d1 = data.get(call.get("market"))
            base = doc.get("base_days", {}).get(call.get("market"))
            if not d1 or not base:
                continue
            # 10-29 舊總指揮核對：10-23 篇美東 10:03 寫，但 NQ／ES base 記咗 10-23（當日未收市）、HSI 記咗 10-26（夜市屬下一交易日），
            # 即係用咗寫文之後先出現嘅收市價做起點。起點一律唔可以遲過「文章日期之前最後一個交易日」
            limit = max((b[0] for b in d1 if b[0] < str(doc.get("date") or "")), default=None)
            used = min(base, limit) if limit else base
            r = score_call(call, d1, used)
            rows.append({"date": doc.get("date"), **call, "base_used": used, "result": r})
    done = [r for r in rows if r["result"]]
    # 使用者 10-29「有計分結果，在網頁通知，等人入去看」：同上一份 scorecard 比，今次新到期嘅記入 new_results，
    # 網頁見到 new_at 喺 3 日內就喺導覽列同分析頁頂提示
    try:
        prev = json.loads(gcs_cat(OUT + "scorecard.json") or "{}")
    except ValueError:
        prev = {}
    key = lambda r: (r.get("date"), r.get("market"), r.get("kind"), r.get("level"), r.get("dir"))  # noqa: E731
    old_done = {key(r) for r in prev.get("calls") or [] if r.get("result")}
    new = [r for r in done if key(r) not in old_done]
    by = {}
    for r in done:
        by.setdefault(r["kind"], []).append(r["result"]["ok"])
    card = {"generated": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "summary": {k: {"n": len(v), "hit": sum(v), "rate": round(sum(v) / len(v), 3)} for k, v in by.items()},
            "pending": len(rows) - len(done), "calls": rows,
            "new_results": new or prev.get("new_results") or [],
            "new_at": (datetime.utcnow().isoformat(timespec="seconds") + "Z") if new else prev.get("new_at")}
    p = os.path.join(work, "scorecard.json")
    json.dump(card, open(p, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(card["summary"], ensure_ascii=False), f"未到期 {card['pending']}", f"新到期 {len(new)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("pack", "score"))
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    (cmd_pack if a.cmd == "pack" else cmd_score)(a.work)


if __name__ == "__main__":
    main()
