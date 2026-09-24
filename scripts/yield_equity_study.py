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
#
# 用法：python3 scripts/yield_equity_study.py [--out data/macro/yield_equity]
# 輸出：README.md、summary.json、yield_spx.svg
# =============================================================================
import argparse
import csv
import io
import json
import math
import os
from datetime import date

import requests

URL_10Y = "https://raw.githubusercontent.com/datasets/bond-yields-us-10y/main/data/monthly.csv"
URL_SPX = "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"

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


def fetch_csv(url, retries=4):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return list(csv.DictReader(io.StringIO(r.text)))
        except requests.RequestException:
            if i == retries - 1:
                raise


def load():
    y = {date.fromisoformat(r["Date"]): float(r["Rate"]) for r in fetch_csv(URL_10Y)}
    s = {date.fromisoformat(r["Date"]): float(r["SP500"]) for r in fetch_csv(URL_SPX)
         if float(r["SP500"]) > 0}
    months = sorted(set(y) & set(s))
    return months, y, s


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


def bucket_stats(months, y, s, key, buckets):
    rows = []
    for lo, hi, label in buckets:
        rs = [fwd(s, d, 12) for d in months if key(d) is not None and lo <= key(d) < hi]
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


# ---------------------------------------------------------------- 報告
def render(res, months):
    c = res["claim"]
    L = ["# 美國 10 年期公債殖利率 vs 美股：歷史驗證", "",
         f"資料：FRED GS10 月均殖利率 + Shiller S&P 500 月均價，"
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
    L += ["", "## 限制", "",
          "- 月平均殖利率會磨平單日高點；S&P 用月均價、不含股息。",
          "- 突破 5% 的事件只有個位數，統計上說服力有限，分組結果也有月份重疊。",
          "- 1953–1980 年代通膨環境與現在差很多，高水位分組主要由那段時期構成。", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/macro/yield_equity")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    months, y, s = load()
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
    }
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    svg_chart(months, y, s, os.path.join(args.out, "yield_spx.svg"),
              [(date(1987, 10, 1), "1987"), (date(2000, 1, 1), "2000"),
               (date(2007, 6, 1), "2007"), (date(2023, 10, 1), "2023")])
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write(render(res, months))
    print(f"輸出：{args.out}（{months[0]:%Y-%m} ～ {months[-1]:%Y-%m}）")


if __name__ == "__main__":
    main()
