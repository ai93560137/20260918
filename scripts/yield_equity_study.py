#!/usr/bin/env python3
# =============================================================================
# 美國 10 年期公債殖利率 vs 美股（S&P 500）歷史驗證
# -----------------------------------------------------------------------------
# 要驗證的說法：「10 年期殖利率超過 5.1%，上一次是 19 年前（2007）金融海嘯前夕」
# 以及延伸問題：殖利率高 / 急升，之後股市是不是比較容易跌？
#
# 資料（皆為月資料，GitHub 上的公開資料集，來源分別是 FRED 與 Shiller）：
#   10Y  datasets/bond-yields-us-10y  → FRED GS10（月平均殖利率，1953-04 起）
#   SPX  datasets/s-and-p-500         → Shiller S&P 綜合指數（月平均價，1871 起）
# 月平均會把單日高點磨平（例：2023-10-19 盤中碰 5.0%，但當月平均 4.80%），
# 所以「單日是否破 5.1%」要看日資料；這裡回答的是「水位 / 趨勢 vs 之後的股市報酬」。
#
# 分析：
#   1. 說法查核：月平均殖利率最後一次 ≥ 5.0% / 5.1% 是何時，之後 S&P 走勢
#   2. 突破事件：殖利率「由下往上」穿越 5%（前 12 個月都在 5% 以下）後的 S&P 表現
#   3. 條件報酬：依「殖利率水位」與「12 個月變動」分組，看未來 12 個月 S&P 報酬
#   4. 股債相關性：每月 S&P 報酬 vs 殖利率變動，分年代的相關係數
#   5. 經典案例：1987、1994、2000、2007、2018、2022、2023
#   6. 殖利率曲線：10Y−3M（1953 起）、10Y−2Y（1976 起）倒掛 / 解除倒掛 → 衰退與 S&P
#   7. 股債相對價值：S&P 盈餘殖利率（E/P，近 12 個月盈餘）− 10Y，分組看未來報酬
#
# 6、7 需要 FRED（GS2、TB3MS、DGS 日線）與 multpl（近期 EPS）；這兩站連不上時
# （例如沙箱只放行 GitHub）10Y 改用上面的鏡像、盈餘只到鏡像的 2023-06，
# 殖利率曲線整段跳過。GitHub Actions（yield_equity_study.yml）每月跑一次完整版。
#
# 用法：python3 scripts/yield_equity_study.py [--out data/macro/yield_equity] [--eps 250]
#       --eps：手動指定最新的近 12 個月 EPS（multpl 抓不到時用）
# 輸出：README.md、summary.json、yield_spx.svg、curve_gap.svg
# =============================================================================
import argparse
import csv
import io
import json
import math
import os
import re
import time
from datetime import date, datetime

import requests

URL_10Y = "https://raw.githubusercontent.com/datasets/bond-yields-us-10y/main/data/monthly.csv"
URL_SPX = "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"
URL_FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
URL_EPS = "https://www.multpl.com/s-p-500-earnings/table/by-month"
UA = {"User-Agent": "Mozilla/5.0 (research script; yield_equity_study.py)"}

# NBER 衰退期（景氣高點月, 谷底月）
RECESSIONS = [(date(1953, 7, 1), date(1954, 5, 1)), (date(1957, 8, 1), date(1958, 4, 1)),
              (date(1960, 4, 1), date(1961, 2, 1)), (date(1969, 12, 1), date(1970, 11, 1)),
              (date(1973, 11, 1), date(1975, 3, 1)), (date(1980, 1, 1), date(1980, 7, 1)),
              (date(1981, 7, 1), date(1982, 11, 1)), (date(1990, 7, 1), date(1991, 3, 1)),
              (date(2001, 3, 1), date(2001, 11, 1)), (date(2007, 12, 1), date(2009, 6, 1)),
              (date(2020, 2, 1), date(2020, 4, 1))]

# 經典案例：(標籤, 起始月, 說明)
CASES = [
    ("1987 股災", date(1987, 8, 1), "殖利率 1 月 7.1% → 8 月 8.8%（9 月 9.4%），10 月黑色星期一"),
    ("1994 債災", date(1994, 1, 1), "Fed 突然升息，殖利率 5.8% → 7.8%"),
    ("2000 網路泡沫", date(2000, 1, 1), "殖利率 6.6%（1 月高點），之後泡沫破裂"),
    ("2006 突破 5%", date(2006, 5, 1), "殖利率月均 5.11%，本輪第一次站上 5%"),
    ("2007 金融海嘯前", date(2007, 6, 1), "殖利率月均 5.10%，貼文所說的『上一次』"),
    ("2018 Q4 修正", date(2018, 10, 1), "殖利率 3.15%（7 年高點），Q4 大跌"),
    ("2022 升息", date(2022, 1, 1), "殖利率 1.76% → 年底 3.9%，股債雙殺"),
    ("2023 碰 5%", date(2023, 10, 1), "10/19 盤中 5.0%（月均 4.80%），之後 AI 行情"),
]


def fetch_text(url, retries=4):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=30, headers=UA)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def fetch_csv(url):
    return list(csv.DictReader(io.StringIO(fetch_text(url))))


def fred(series):
    """FRED 單一序列 → {date: float}；連不上回 None。"""
    try:
        rows = fetch_csv(URL_FRED.format(series))
    except requests.RequestException as e:
        print(f"FRED {series} 無法取得：{e}")
        return None
    out = {}
    for r in rows:
        d = r.get("observation_date") or r.get("DATE")
        v = r.get(series)
        if d and v not in (None, "", "."):
            out[date.fromisoformat(d)] = float(v)
    return out or None


def multpl_eps():
    """multpl 的 S&P 500 近 12 個月盈餘（月表）→ {月初: EPS}；抓不到回 {}。"""
    try:
        html = fetch_text(URL_EPS)
    except requests.RequestException as e:
        print(f"multpl EPS 無法取得：{e}")
        return {}
    out = {}
    for m in re.finditer(r"<td>\s*([A-Z][a-z]{2}) (\d{1,2}), (\d{4})\s*</td>\s*<td[^>]*>(.*?)</td>", html, re.S):
        num = re.sub(r"<[^>]+>|&[#\w]+;|[^0-9.]", "", m.group(4))
        if not num:
            continue
        d = datetime.strptime(f"{m.group(1)} {m.group(3)}", "%b %Y").date()
        out[d] = float(num)
    return out


def load(eps_override=None):
    shiller = [r for r in fetch_csv(URL_SPX) if float(r["SP500"]) > 0]
    s = {date.fromisoformat(r["Date"]): float(r["SP500"]) for r in shiller}
    eps = {date.fromisoformat(r["Date"]): float(r["Earnings"]) for r in shiller if float(r["Earnings"]) > 0}
    src = {"10y": "FRED GS10", "eps": "Shiller（鏡像）"}
    y = fred("GS10")
    if y is None:
        y = {date.fromisoformat(r["Date"]): float(r["Rate"]) for r in fetch_csv(URL_10Y)}
        src["10y"] = "FRED GS10（GitHub 鏡像）"
    recent = {d: v for d, v in multpl_eps().items() if d > max(eps)}
    if recent:
        eps.update(recent)
        src["eps"] = f"Shiller（鏡像）+ multpl（{min(recent):%Y-%m} 起）"
    if eps_override:
        last = max(s)
        eps[last] = eps_override
        src["eps"] += f"；{last:%Y-%m} 用手動 EPS {eps_override:g}"
    months = sorted(set(y) & set(s))
    extra = {"gs2": fred("GS2"), "tb3": fred("TB3MS"),
             "d10": fred("DGS10"), "d2": fred("DGS2"), "d3m": fred("DGS3MO")}
    return months, y, s, eps, extra, src


def add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def fwd(s, d, n):
    """d 月之後 n 個月的 S&P 報酬（月平均價對月平均價）；資料不足回 None。"""
    e = add_months(d, n)
    return s[e] / s[d] - 1 if e in s and d in s else None


def max_dd(s, d, n):
    """d 月起 n 個月內，相對 d 月價位的最大跌幅（≤ 0）。"""
    lo, k = 0.0, 0
    for k in range(1, n + 1):
        e = add_months(d, k)
        if e not in s:
            break
        lo = min(lo, s[e] / s[d] - 1)
    return lo if k > 0 else None


def pct(x, digits=1):
    return "—" if x is None else f"{x * 100:+.{digits}f}%"


def corr(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    cov = sum((x - ma) * (z - mb) for x, z in zip(a, b))
    return cov / math.sqrt(va * vb) if va and vb else None


# ---------------------------------------------------------------- 分析
def claim_check(months, y, s):
    out = {}
    for th in (5.0, 5.1):
        last = max((d for d in months if y[d] >= th), default=None)
        out[str(th)] = {
            "last_month": last.isoformat() if last else None,
            "yield": y[last] if last else None,
            "spx_fwd_12m": fwd(s, last, 12) if last else None,
            "spx_fwd_24m": fwd(s, last, 24) if last else None,
            "spx_maxdd_24m": max_dd(s, last, 24) if last else None,
        }
    # 2007 之後 S&P 月均高點 / 低點，用來說明「前夕」的時間差
    peak = max((d for d in months if date(2007, 1, 1) <= d <= date(2008, 6, 1)), key=lambda d: s[d])
    trough = min((d for d in months if date(2008, 1, 1) <= d <= date(2010, 1, 1)), key=lambda d: s[d])
    out["gfc"] = {"spx_peak": peak.isoformat(), "spx_trough": trough.isoformat(),
                  "peak_to_trough": s[trough] / s[peak] - 1}
    return out


def upcross_events(months, y, s, th=5.0, lookback=12):
    """殖利率由下往上穿越 th：當月 ≥ th，且前 lookback 個月都 < th。"""
    ev = []
    for i, d in enumerate(months):
        if i < lookback or y[d] < th:
            continue
        if all(y[months[j]] < th for j in range(i - lookback, i)):
            ev.append({"month": d.isoformat(), "yield": y[d],
                       "fwd_6m": fwd(s, d, 6), "fwd_12m": fwd(s, d, 12),
                       "fwd_24m": fwd(s, d, 24), "maxdd_24m": max_dd(s, d, 24)})
    return ev


def bucket_stats(months, y, s, key, buckets, n=12):
    rows = []
    for lo, hi, label in buckets:
        rs = [fwd(s, d, n) for d in months if key(d) is not None and lo <= key(d) < hi]
        rs = [r for r in rs if r is not None]
        if not rs:
            rows.append({"bucket": label, "n": 0})
            continue
        rs.sort()
        rows.append({"bucket": label, "n": len(rs), "mean": sum(rs) / len(rs),
                     "median": rs[len(rs) // 2], "p_neg": sum(r < 0 for r in rs) / len(rs),
                     "p_crash": sum(r < -0.15 for r in rs) / len(rs)})
    return rows


def decade_corr(months, y, s):
    out = []
    eras = [(1953, 1969), (1970, 1979), (1980, 1989), (1990, 1999),
            (2000, 2009), (2010, 2019), (2020, 2021), (2022, 2026)]
    for a, b in eras:
        xs, zs = [], []
        for i in range(1, len(months)):
            d, p = months[i], months[i - 1]
            if a <= d.year <= b:
                xs.append(y[d] - y[p])
                zs.append(s[d] / s[p] - 1)
        out.append({"era": f"{a}–{b}", "n": len(xs), "corr": corr(xs, zs)})
    return out


def cases(months, y, s):
    out = []
    for label, d, note in CASES:
        if d not in s:
            continue
        out.append({"case": label, "month": d.isoformat(), "yield": y.get(d), "note": note,
                     "fwd_12m": fwd(s, d, 12), "maxdd_24m": max_dd(s, d, 24)})
    return out


def next_recession(d):
    return min((a for a, _ in RECESSIONS if a >= d), default=None)


def months_between(a, b):
    return (b.year - a.year) * 12 + b.month - a.month


def curve_events(months, spread, s, min_len=3):
    """倒掛開始（spread < 0，且前 12 個月都 ≥ 0）與解除倒掛（倒掛 ≥ min_len 個月後回到 ≥ 0）。"""
    ms = [d for d in months if d in spread]
    ev, inv_start = [], None
    for i, d in enumerate(ms):
        if spread[d] < 0 and inv_start is None and i >= 12 and all(spread[ms[j]] >= 0 for j in range(i - 12, i)):
            inv_start = d
            ev.append({"type": "倒掛", "month": d, "spread": spread[d]})
        elif spread[d] >= 0 and inv_start is not None:
            if months_between(inv_start, d) >= min_len:
                ev.append({"type": "解除倒掛", "month": d, "spread": spread[d],
                           "inverted_months": months_between(inv_start, d)})
            else:
                ev.pop()  # 太短的倒掛當雜訊
            inv_start = None
    out = []
    for e in ev:
        d = e["month"]
        rec = next_recession(d)
        lag = months_between(d, rec) if rec else None
        peak = max((m for m in months if d <= m <= add_months(d, 36)), key=lambda m: s[m], default=d)
        out.append({**e, "month": d.isoformat(),
                    "recession": rec.isoformat() if rec and lag <= 36 else None,
                    "lag_to_recession": lag if lag is not None and lag <= 36 else None,
                    "months_to_spx_peak": months_between(d, peak),
                    "fwd_12m": fwd(s, d, 12), "fwd_24m": fwd(s, d, 24), "maxdd_24m": max_dd(s, d, 24)})
    return out, (inv_start.isoformat() if inv_start else None)


def curve_study(months, y, s, extra):
    res = {}
    for key, series, label in (("10y3m", extra.get("tb3"), "10Y−3M"), ("10y2y", extra.get("gs2"), "10Y−2Y")):
        if not series:
            continue
        spread = {d: y[d] - series[d] for d in months if d in series}
        ev, open_inv = curve_events(months, spread, s)
        ms = [d for d in months if d in spread]
        res[key] = {"label": label, "start": ms[0].isoformat(), "events": ev, "open_inversion": open_inv,
                    "latest_month": ms[-1].isoformat(), "latest": spread[ms[-1]],
                    "series": {d.isoformat(): round(v, 3) for d, v in spread.items()}}
    # 日線最新值（貼文那天的狀態）
    d10, d2, d3 = extra.get("d10"), extra.get("d2"), extra.get("d3m")
    if d10:
        day = max(d10)
        res["daily"] = {"date": day.isoformat(), "10y": d10[day],
                        "2y": d2.get(day) if d2 else None, "3m": d3.get(day) if d3 else None}
    return res


def gap_study(months, y, s, eps):
    """盈餘殖利率 E/P − 10Y。月資料 E 為近 12 個月盈餘（Shiller 為季資料內插）。"""
    gap = {d: eps[d] / s[d] * 100 - y[d] for d in months if d in eps}
    if not gap:
        return None
    buckets = [(-99, -2, "< −2 個百分點"), (-2, 0, "−2 ～ 0"), (0, 2, "0 ～ 2"),
               (2, 4, "2 ～ 4"), (4, 99, "≥ 4 個百分點")]
    key = lambda d: gap.get(d)
    last = max(gap)
    lower = [d for d in gap if gap[d] <= gap[last]]
    return {
        "latest_month": last.isoformat(), "latest_gap": gap[last],
        "latest_ep": eps[last] / s[last] * 100, "latest_eps": eps[last], "latest_spx": s[last],
        "latest_10y": y[last],
        "pctile": len(lower) / len(gap),
        "last_lower": max((d.isoformat() for d in gap if gap[d] <= gap[last] and d.year < last.year - 1), default=None),
        "by_gap_12m": bucket_stats(months, y, s, key, buckets, 12),
        "by_gap_36m": bucket_stats(months, y, s, key, buckets, 36),
        "snap": [{"month": d.isoformat(), "ep": eps[d] / s[d] * 100, "y": y[d], "gap": gap[d]}
                 for d in (date(1981, 9, 1), date(1987, 8, 1), date(2000, 1, 1), date(2007, 6, 1),
                           date(2009, 3, 1), date(2012, 6, 1), date(2021, 12, 1)) if d in gap],
        "series": {d.isoformat(): round(v, 3) for d, v in gap.items()},
    }


# ---------------------------------------------------------------- 圖
def svg_chart(months, y, s, path, marks):
    """上：S&P 500（對數軸）；下：10Y 殖利率，5% 虛線。靜態 SVG，深淺色都可讀。"""
    W, L, R = 900, 56, 24
    T1, H1 = 40, 230          # 上圖
    T2, H2 = T1 + H1 + 40, 170  # 下圖
    H = T2 + H2 + 32
    d0, d1 = months[0], months[-1]
    span = (d1 - d0).days
    X = lambda d: L + (d - d0).days / span * (W - L - R)
    slo, shi = math.log(min(s[d] for d in months)), math.log(max(s[d] for d in months))
    Ys = lambda v: T1 + (shi - math.log(v)) / (shi - slo) * H1
    ylo, yhi = 0.0, 16.0
    Yy = lambda v: T2 + (yhi - v) / (yhi - ylo) * H2
    css = (
        ":root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;"
        "--s1:#2a78d6;--s2:#eb6834;--mk:#b3261e}"
        "@media (prefers-color-scheme: dark){:root{--bg:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;"
        "--grid:#3a3936;--s1:#3987e5;--s2:#d95926;--mk:#f2b8b5}}"
        "text{font:12px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;fill:var(--ink2)}"
        ".t{font-size:14px;font-weight:600;fill:var(--ink)}"
    )
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
           f"<style>{css}</style>", f'<rect width="{W}" height="{H}" fill="var(--bg)"/>',
           f'<text class="t" x="{L}" y="24">S&amp;P 500（月均，對數軸）</text>',
           f'<text class="t" x="{L}" y="{T2 - 12}">美國 10 年期公債殖利率（月均 %）</text>']
    k = 10 ** math.floor(slo / math.log(10))
    while k <= math.exp(shi):
        for m in (1, 2, 5):
            v = k * m
            if math.exp(slo) <= v <= math.exp(shi):
                out.append(f'<line x1="{L}" x2="{W - R}" y1="{Ys(v):.1f}" y2="{Ys(v):.1f}" stroke="var(--grid)"/>')
                out.append(f'<text x="{L - 6}" y="{Ys(v) + 4:.1f}" text-anchor="end">{v:g}</text>')
        k *= 10
    for v in range(0, 17, 4):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Yy(v):.1f}" y2="{Yy(v):.1f}" stroke="var(--grid)"/>')
        out.append(f'<text x="{L - 6}" y="{Yy(v) + 4:.1f}" text-anchor="end">{v}%</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Yy(5):.1f}" y2="{Yy(5):.1f}" stroke="var(--mk)" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{W - R}" y="{Yy(5) - 5:.1f}" text-anchor="end" fill="var(--mk)" style="fill:var(--mk)">5%</text>')
    for yr in range((d0.year // 10 + 1) * 10, d1.year + 1, 10):
        out.append(f'<text x="{X(date(yr, 1, 1)):.1f}" y="{H - 10}" text-anchor="middle">{yr}</text>')
    # 事件直線
    for d, label in marks:
        x = X(d)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T1}" y2="{T2 + H2}" stroke="var(--mk)" stroke-width="1" opacity="0.5"/>')
        out.append(f'<text x="{x + 3:.1f}" y="{T1 + 10}" style="fill:var(--mk);font-size:11px">{label}</text>')
    ps = " ".join(f"{'M' if i == 0 else 'L'}{X(d):.1f},{Ys(s[d]):.1f}" for i, d in enumerate(months))
    py = " ".join(f"{'M' if i == 0 else 'L'}{X(d):.1f},{Yy(y[d]):.1f}" for i, d in enumerate(months))
    out.append(f'<path d="{ps}" fill="none" stroke="var(--s1)" stroke-width="1.6"/>')
    out.append(f'<path d="{py}" fill="none" stroke="var(--s2)" stroke-width="1.6"/>')
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def svg_panels(panels, path, shade=()):
    """多個上下排列的折線面板，共用時間軸；0 線加粗，shade 為 [(起, 迄)] 灰底（衰退期）。
    panels: [(標題, {date: 值}, css_var)]"""
    W, L, R, PH, GAP = 900, 56, 24, 190, 48
    H = 40 + len(panels) * (PH + GAP)
    d0 = min(min(p[1]) for p in panels)
    d1 = max(max(p[1]) for p in panels)
    span = (d1 - d0).days
    X = lambda d: L + (d - d0).days / span * (W - L - R)
    css = (
        ":root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e4e3df;--zero:#8a8984;--sh:#ebeae6;"
        "--s1:#2a78d6;--s2:#eb6834}"
        "@media (prefers-color-scheme: dark){:root{--bg:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;"
        "--grid:#3a3936;--zero:#8a8984;--sh:#2a2a28;--s1:#3987e5;--s2:#d95926}}"
        "text{font:12px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;fill:var(--ink2)}"
        ".t{font-size:14px;font-weight:600;fill:var(--ink)}"
    )
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
           f"<style>{css}</style>", f'<rect width="{W}" height="{H}" fill="var(--bg)"/>']
    for i, (title, ser, var) in enumerate(panels):
        top = 40 + i * (PH + GAP)
        lo, hi = min(ser.values()), max(ser.values())
        lo, hi = math.floor(min(lo, 0)), math.ceil(max(hi, 0))
        Y = lambda v, top=top, lo=lo, hi=hi: top + (hi - v) / (hi - lo) * PH
        out.append(f'<text class="t" x="{L}" y="{top - 14}">{title}</text>')
        for a, b in shade:
            if b >= d0 and a <= d1:
                xa, xb = X(max(a, d0)), X(min(b, d1))
                out.append(f'<rect x="{xa:.1f}" y="{top}" width="{max(xb - xa, 1):.1f}" height="{PH}" fill="var(--sh)"/>')
        step = max(1, (hi - lo) // 5)
        for v in range(lo, hi + 1, step):
            sty = 'stroke="var(--zero)" stroke-width="1.5"' if v == 0 else 'stroke="var(--grid)"'
            out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" {sty}/>')
            out.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:+d}</text>')
        ds = sorted(ser)
        path_d = " ".join(f"{'M' if j == 0 else 'L'}{X(d):.1f},{Y(ser[d]):.1f}" for j, d in enumerate(ds))
        out.append(f'<path d="{path_d}" fill="none" stroke="var({var})" stroke-width="1.6"/>')
        out.append(f'<circle cx="{X(ds[-1]):.1f}" cy="{Y(ser[ds[-1]]):.1f}" r="3.5" fill="var({var})"/>')
    for yr in range((d0.year // 10 + 1) * 10, d1.year + 1, 10):
        out.append(f'<text x="{X(date(yr, 1, 1)):.1f}" y="{H - 14}" text-anchor="middle">{yr}</text>')
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


# ---------------------------------------------------------------- 報告
def render(res, months):
    c = res["claim"]
    L = ["# 美國 10 年期公債殖利率 vs 美股：歷史驗證", "",
         f"資料：{res['sources']['10y']} 月均殖利率 + Shiller S&P 500 月均價，盈餘 {res['sources']['eps']}，"
         f"{months[0]:%Y-%m} ～ {months[-1]:%Y-%m}（共 {len(months)} 個月）。"
         "產生方式：`python3 scripts/yield_equity_study.py`。", "",
         "![S&P 500 與 10Y 殖利率](yield_spx.svg)", "",
         "## 1. 說法查核：「上一次 5.1% 是 19 年前金融海嘯前夕」", "",
         "| 門檻 | 最後一次月均 ≥ 門檻 | 當月殖利率 | S&P 之後 12 個月 | 之後 24 個月 | 24 個月內最大跌幅 |",
         "|---|---|---|---|---|---|"]
    for th in ("5.0", "5.1"):
        r = c[th]
        L.append(f"| {th}% | {r['last_month'][:7]} | {r['yield']:.2f}% | {pct(r['spx_fwd_12m'])} "
                 f"| {pct(r['spx_fwd_24m'])} | {pct(r['spx_maxdd_24m'])} |")
    g = c["gfc"]
    L += ["", f"金融海嘯期間 S&P 月均高點在 {g['spx_peak'][:7]}，低點在 {g['spx_trough'][:7]}，"
          f"跌幅 {pct(g['peak_to_trough'])}。", ""]
    L += ["## 2. 殖利率由下往上突破 5% 之後（前 12 個月都在 5% 以下）", "",
          "| 突破月份 | 殖利率 | 6 個月 | 12 個月 | 24 個月 | 24 個月內最大跌幅 |", "|---|---|---|---|---|---|"]
    for e in res["upcross_5"]:
        L.append(f"| {e['month'][:7]} | {e['yield']:.2f}% | {pct(e['fwd_6m'])} | {pct(e['fwd_12m'])} "
                 f"| {pct(e['fwd_24m'])} | {pct(e['maxdd_24m'])} |")
    for title, key in (("3a. 依殖利率水位分組 → 未來 12 個月 S&P 報酬", "by_level"),
                       ("3b. 依殖利率 12 個月變動分組 → 未來 12 個月 S&P 報酬", "by_change")):
        L += ["", f"## {title}", "",
              "| 分組 | 月數 | 平均 | 中位數 | 下跌機率 | 跌逾 15% 機率 |", "|---|---|---|---|---|---|"]
        for r in res[key]:
            if r["n"]:
                L.append(f"| {r['bucket']} | {r['n']} | {pct(r['mean'])} | {pct(r['median'])} "
                         f"| {r['p_neg'] * 100:.0f}% | {r['p_crash'] * 100:.0f}% |")
    base = res["base_rate"]
    L += ["", f"全樣本基準：未來 12 個月平均 {pct(base['mean'])}，下跌機率 {base['p_neg'] * 100:.0f}%，"
          f"跌逾 15% 機率 {base['p_crash'] * 100:.0f}%（月資料重疊，樣本並非獨立）。", "",
          "## 4. 股債相關性（每月 S&P 報酬 vs 殖利率變動）", "",
          "負值＝殖利率升、股市跌（利率是股市的壓力）；正值＝兩者同向（成長 / 通膨預期主導）。", "",
          "| 期間 | 月數 | 相關係數 |", "|---|---|---|"]
    for r in res["decade_corr"]:
        cv = "—" if r["corr"] is None else f"{r['corr']:+.2f}"
        L.append(f"| {r['era']} | {r['n']} | {cv} |")
    L += ["", "## 5. 經典案例", "",
          "| 案例 | 起始月 | 殖利率 | 背景 | S&P 之後 12 個月 | 24 個月內最大跌幅 |", "|---|---|---|---|---|---|"]
    for r in res["cases"]:
        L.append(f"| {r['case']} | {r['month'][:7]} | {r['yield']:.2f}% | {r['note']} "
                 f"| {pct(r['fwd_12m'])} | {pct(r['maxdd_24m'])} |")
    L += render_curve(res.get("curve") or {}) + render_gap(res.get("gap"))
    L += ["", "## 限制", "",
          "- 月平均殖利率會磨平單日高點；S&P 用月均價、不含股息。",
          "- 盈餘用的是近 12 個月「公告」盈餘（GAAP），景氣谷底時盈餘暴跌會讓 E/P 失真（例：2009）。",
          "- 衰退日期取 NBER 景氣高點；判定有落後，最近的衰退不一定已經公布。",
          "- 突破 5% 的事件只有個位數，統計上說服力有限，分組結果也有月份重疊。",
          "- 1953–1980 年代通膨環境與現在差很多，高水位分組主要由那段時期構成。", ""]
    return "\n".join(L)


def render_curve(c):
    L = ["", "## 6. 殖利率曲線（長短利差）", ""]
    if not c.get("10y3m") and not c.get("10y2y"):
        return L + ["（這次執行連不上 FRED，拿不到短天期殖利率，本段略過；GitHub Actions 版會補上。）"]
    L += ["灰底為 NBER 衰退期。倒掛＝短天期殖利率高於 10 年期，市場預期未來會降息（經濟轉弱）。", "",
          "![殖利率曲線與股債利差](curve_gap.svg)", ""]
    dly = c.get("daily")
    if dly:
        parts = [f"10Y {dly['10y']:.2f}%"]
        if dly.get("2y") is not None:
            parts.append(f"2Y {dly['2y']:.2f}%（10Y−2Y {dly['10y'] - dly['2y']:+.2f}）")
        if dly.get("3m") is not None:
            parts.append(f"3M {dly['3m']:.2f}%（10Y−3M {dly['10y'] - dly['3m']:+.2f}）")
        L += [f"**最新日線（{dly['date']}）**：" + "、".join(parts), ""]
    for key in ("10y3m", "10y2y"):
        r = c.get(key)
        if not r:
            continue
        L += [f"### {r['label']}（{r['start'][:7]} 起；最新月均 {r['latest_month'][:7]}：{r['latest']:+.2f} 個百分點"
              + ("，目前仍倒掛" if r["open_inversion"] else "") + "）", "",
              "| 事件 | 月份 | 利差 | 倒掛月數 | 之後的衰退（落後月數） | S&P 36 個月內高點在幾個月後 | 12 個月 | 24 個月 | 24 個月內最大跌幅 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for e in r["events"]:
            rec = f"{e['recession'][:7]}（{e['lag_to_recession']}）" if e["recession"] else "36 個月內無"
            L.append(f"| {e['type']} | {e['month'][:7]} | {e['spread']:+.2f} | {e.get('inverted_months', '')} | {rec} "
                     f"| {e['months_to_spx_peak']} | {pct(e['fwd_12m'])} | {pct(e['fwd_24m'])} | {pct(e['maxdd_24m'])} |")
        L.append("")
    return L


def render_gap(g):
    L = ["", "## 7. 股債相對價值：S&P 盈餘殖利率 − 10Y 殖利率", ""]
    if not g:
        return L + ["（沒有盈餘資料，本段略過。）"]
    L += ["盈餘殖利率 = 近 12 個月 EPS ÷ S&P 指數，也就是本益比的倒數。減掉 10Y 殖利率，"
          "就是「買股票比買公債多拿多少」（俗稱 Fed model）。數字越低，股票相對公債越貴。", "",
          f"**有盈餘資料的最新月份（{g['latest_month'][:7]}）**：S&P {g['latest_spx']:,.0f}、EPS {g['latest_eps']:.1f}"
          f"（本益比 {100 / g['latest_ep']:.1f} 倍）→ 盈餘殖利率 {g['latest_ep']:.2f}%，"
          f"10Y {g['latest_10y']:.2f}%，利差 **{g['latest_gap']:+.2f}** 個百分點，"
          f"比歷史上 {g['pctile'] * 100:.0f}% 的月份低（或相同）。"
          + (f"上一次這麼低是 {g['last_lower'][:7]}。" if g["last_lower"] else ""), "",
          "| 時點 | 盈餘殖利率 | 10Y | 利差 |", "|---|---|---|---|"]
    for r in g["snap"]:
        L.append(f"| {r['month'][:7]} | {r['ep']:.2f}% | {r['y']:.2f}% | {r['gap']:+.2f} |")
    for title, key in (("未來 12 個月", "by_gap_12m"), ("未來 36 個月（累計）", "by_gap_36m")):
        L += ["", f"#### 依利差分組 → S&P {title}", "",
              "| 利差 | 月數 | 平均 | 中位數 | 下跌機率 | 跌逾 15% 機率 |", "|---|---|---|---|---|---|"]
        for r in g[key]:
            if r["n"]:
                L.append(f"| {r['bucket']} | {r['n']} | {pct(r['mean'])} | {pct(r['median'])} "
                         f"| {r['p_neg'] * 100:.0f}% | {r['p_crash'] * 100:.0f}% |")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/macro/yield_equity")
    ap.add_argument("--eps", type=float, help="手動指定最新月份的近 12 個月 EPS")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    months, y, s, eps, extra, src = load(args.eps)
    chg12 = {d: y[d] - y[months[i - 12]] for i, d in enumerate(months) if i >= 12}
    all_fwd = [r for r in (fwd(s, d, 12) for d in months) if r is not None]
    res = {
        "range": [months[0].isoformat(), months[-1].isoformat()],
        "claim": claim_check(months, y, s),
        "upcross_5": upcross_events(months, y, s, 5.0),
        "by_level": bucket_stats(months, y, s, lambda d: y[d], [
            (0, 3, "< 3%"), (3, 4, "3–4%"), (4, 5, "4–5%"), (5, 6, "5–6%"),
            (6, 8, "6–8%"), (8, 99, "≥ 8%")]),
        "by_change": bucket_stats(months, y, s, lambda d: chg12.get(d), [
            (-99, -1, "降逾 1 個百分點"), (-1, 0, "降 0–1 個百分點"),
            (0, 1, "升 0–1 個百分點"), (1, 2, "升 1–2 個百分點"), (2, 99, "升逾 2 個百分點")]),
        "base_rate": {"mean": sum(all_fwd) / len(all_fwd),
                      "p_neg": sum(r < 0 for r in all_fwd) / len(all_fwd),
                      "p_crash": sum(r < -0.15 for r in all_fwd) / len(all_fwd)},
        "decade_corr": decade_corr(months, y, s),
        "cases": cases(months, y, s),
        "curve": curve_study(months, y, s, extra),
        "gap": gap_study(months, y, s, eps),
        "sources": src,
    }
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    svg_chart(months, y, s, os.path.join(args.out, "yield_spx.svg"),
              [(date(1987, 10, 1), "1987"), (date(2000, 1, 1), "2000"),
               (date(2007, 6, 1), "2007"), (date(2023, 10, 1), "2023")])
    panels = [(f"{res['curve'][k]['label']} 利差（月均，百分點）", {date.fromisoformat(d): v for d, v in res["curve"][k]["series"].items()}, "--s1")
              for k in ("10y3m", "10y2y") if k in res["curve"]]
    if res["gap"]:
        panels.append(("S&P 盈餘殖利率 − 10Y（百分點）", {date.fromisoformat(d): v for d, v in res["gap"]["series"].items()}, "--s2"))
    svg_panels(panels, os.path.join(args.out, "curve_gap.svg"), RECESSIONS)
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write(render(res, months))
    print(f"輸出：{args.out}（{months[0]:%Y-%m} ～ {months[-1]:%Y-%m}）")


if __name__ == "__main__":
    main()
