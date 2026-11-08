"""[IDEAS #1010] rev15 E6S4 按波幅縮放：觸發門檻同入場結構（E6 Z2 S4 1R）都乘「前一個 UTC 日 M1 平均波幅 ÷ 參考波幅」。
參考波幅＝MT5 2026-01-01→07-23 每日 M1 平均（高−低）嘅中位數（只用嚟校準，唔睇成績）。規格、成功標準以 IDEAS #1010 預先登記為準（跑之前 commit）。
主判 V2（觸發＋結構都縮放）；V1（只縮放觸發，結構固定美元）同固定美元版（#1001／#1002 原版）只作描述。
用法：python3 research/student_offline/rev15_atr.py → research/student_offline/REV15_ATR.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = [sys.argv[0], "--src", "mt5"]
import rev15_history as rh   # noqa: E402
fr = rh.fr

LB, TH = 15, 3.0
E, Z, S, RT = 6.0, 2.0, 4.0, 1.0


def load(src, a, b):
    rh.SRC = src
    rh.A, rh.B, rh.CACHE = a, b, f"/tmp/rev15_history_{src}_{a}_{b}.npz"
    return rh.load()


def day_range(d):
    """每根 K 線對應「前一個交易日」M1 平均（高−低）；第一日冇前日 → nan。"""
    day = d["t"] // 86400
    rng = d["h"] - d["l"]
    uniq, inv = np.unique(day, return_inverse=True)
    mean = np.bincount(inv, weights=rng) / np.bincount(inv)
    prev = np.r_[np.nan, mean[:-1]]
    return prev[inv], mean


def run(d, ref, mode):
    """mode：fixed（原版）｜v1（只縮放觸發）｜v2（觸發＋結構縮放）。回傳 (r 陣列, ts 陣列)。"""
    t, o, c = d["t"], d["o"], d["c"]
    pr, _ = day_range(d)
    f = ref / pr                                   # f>1：波幅細過參考 → 美元門檻收細（價格放大）
    n = len(t)
    mv = np.full(n, np.nan); mv[LB:] = c[LB:] - o[:-LB]
    idx = np.arange(n)
    if mode == "fixed":
        ok = (np.abs(mv) >= TH) & (idx >= 29)
    else:
        ok = (np.abs(mv) * f >= TH) & (idx >= 29) & np.isfinite(f)
    raw = [(int(i), "BUY" if mv[i] < 0 else "SELL") for i in np.nonzero(ok)[0]]
    sigs = fr.cooldown(raw, t, 60, int(t[0]), int(t[-1]) + 60)
    O, H, L, T = fr.future_mats(d, sigs)
    if mode == "v2":
        fi = np.array([f[i] for i, _ in sigs])[:, None]
        O, H, L = O * fi, H * fi, L * fi
    r = fr.simulate((O, H, L, T), E, Z, S, RT)
    if mode == "v2":                               # 成本係真美元：normalized 成本＝0.5×f
        fi = fi[:, 0]
        r = r + fr.COST / S - fr.COST * fi / S
    ts = np.array([int(t[i]) + 60 for i, _ in sigs], dtype=np.int64)
    return r, ts


def years(r, ts):
    out = {}
    for x, s in zip(r, ts):
        if not np.isnan(x):
            out.setdefault(dt.datetime.fromtimestamp(int(s), dt.timezone.utc).year, []).append(x)
    return {y: fr.stats(np.array(v)) for y, v in sorted(out.items())}


def main():
    cal = load("mt5", "2026-01-01", "2026-07-23")
    ref = float(np.nanmedian(day_range(cal)[1]))
    sets = [("Dukascopy 2015–2022", load("duka", "2015-01-01", "2022-12-31")),
            ("MT5 2023–2025", load("mt5", "2023-01-01", "2025-12-31"))]
    out = ["# rev15 E6S4 按波幅縮放（IDEAS #1010）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；參考波幅（MT5 2026-01→07-23 每日 M1 平均高低差中位數）＝{ref:.3f} 美元",
           "- 縮放系數＝參考波幅 ÷ 前一個 UTC 日 M1 平均高低差；觸發：前 15 根走幅 × 系數 ≥ 3；V2 結構（6／±2／4／1R）亦按系數；每張扣真 0.5 美元", "",
           "| 數據 | V2 觸發＋結構縮放（主判） | V1 只縮放觸發 | 固定美元（原版） |", "|---|---|---|---|"]
    res = {}
    for name, d in sets:
        row = []
        for m in ("v2", "v1", "fixed"):
            r, ts = run(d, ref, m)
            res[(name, m)] = (r, ts)
            row.append(fr.fmt(fr.stats(r)))
        out.append(f"| {name} | " + " | ".join(row) + " |")
    out += ["", "## 每年（V2 對 固定美元）", "", "| 年 | V2 | 固定美元 |", "|---|---|---|"]
    yv2, yfx = {}, {}
    for name, _ in sets:
        yv2.update(years(*res[(name, "v2")])); yfx.update(years(*res[(name, "fixed")]))
    out += [f"| {y} | {fr.fmt(yv2[y])} | {fr.fmt(yfx.get(y, {'n': 0}))} |" for y in sorted(yv2)]
    sd = fr.stats(res[(sets[0][0], "v2")][0]); sm = fr.stats(res[(sets[1][0], "v2")][0])
    pos = sum(1 for v in yv2.values() if v["n"] and v["avg"] > 0)
    worst = min((v["avg"] for v in yv2.values() if v["n"]), default=-9)
    ok = {"①Duka 平均≥+0.10R、PF≥1.15": sd["n"] > 0 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
          "②MT5 2023–25 平均≥+0.10R、PF≥1.15": sm["n"] > 0 and sm["avg"] >= 0.10 and sm["pf"] >= 1.15,
          "③11年≥9年正數": pos >= 9,
          "④最差一年≥−0.05R": worst >= -0.05}
    out += ["", "## 判（預先登記 IDEAS #1010；主判 V2）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            f"- V2 正數年份 {pos}／{len(yv2)}；最差一年 {worst:+.3f}R",
            "- " + ("✅ 達標 → 提案：933／rev15 影子改用縮放版並排前向（唔落單）" if all(ok.values())
                    else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔准改參數再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "REV15_ATR.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
