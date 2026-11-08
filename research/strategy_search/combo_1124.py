"""[IDEAS #1124] 兩類代表組合：急動反向（rev15 933、#1083 偏離 EMA60、#1122 離當日開市價 15）＋趨勢突破（#1096 上週突破、#1116 海龜 2）。
每張固定 1R、規則同各自回測完全一樣（冇改參數）；R 記喺入場時間；逐月／逐年 ΣR；最大回撤用按入場時間排序嘅累計 R。
**主判（預先登記）**：5 條全部（R5）對 rev15 單獨；其他組合只作描述。
成功（全部要達到）：每段數據（2010–14 Duka／2015–22 Duka／2023–26 MT5）各自 ① R5 ΣR／最大回撤 ≥ rev15；② R5 蝕錢月份比例 ≤ rev15；
③ 急動三條對趨勢兩條逐月 ΣR 相關 ≤ 0.2；17 年（2010–2026）④ R5 蝕錢年份 ≤ 1；⑤ R5 最差一年 ΣR ≥ −5R。
用法：python3 research/strategy_search/combo_1124.py → research/strategy_search/COMBO_1124.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import combo_1027 as C          # noqa: E402
import batch_1083 as B83        # noqa: E402
import batch_1120 as B120       # noqa: E402
import h1_lab3 as H3            # noqa: E402
import h1_lab8 as H8            # noqa: E402

FNS = {"rev15": C.rev15, "ema60": B83.r1083, "dopen15": B120.r1122, "wkbrk": H3.r1096, "turtle2": H8.r1116}
NAMES = {"rev15": "rev15", "ema60": "偏離均線", "dopen15": "離開市15", "wkbrk": "上週突破", "turtle2": "海龜2"}
FADE, TREND = ("rev15", "ema60", "dopen15"), ("wkbrk", "turtle2")
SETS = [("Dukascopy 2010–2014", "duka", "2010-01-01", "2014-12-31"), ("Dukascopy 2015–2022", "duka", "2015-01-01", "2022-12-31"),
        ("MT5 2023-01→2026-10", "mt5", "2023-01-01", "2026-10-30")]


def year(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).year


def section(name, tr):
    allm = sorted({C.month(x[0]) for v in tr.values() for x in v})
    m = {k: C.monthly(v, allm) for k, v in tr.items()}
    corr = float(np.corrcoef(sum(m[k] for k in FADE), sum(m[k] for k in TREND))[0, 1])
    s15, d15 = C.mdd(tr["rev15"]); neg15 = float((m["rev15"] < 0).mean())
    rows, res = [], None
    for size in range(1, 6):
        for sub in itertools.combinations(list(FNS), size):
            x = [t for k in sub for t in tr[k]]; s, dd = C.mdd(x)
            neg = float((sum(m[k] for k in sub) < 0).mean())
            rows.append((sub, len(x), s, dd, s / dd if dd else float("inf"), neg))
            if size == 5:
                res = (s, dd, neg)
    out = [f"## {name}", "", "| 組合 | 張 | ΣR | 最大回撤 R | ΣR／回撤 | 蝕錢月 |", "|---|---|---|---|---|---|"]
    out += [f"| {'⭐ ' if len(sub) == 5 else ''}{'＋'.join(NAMES[k] for k in sub)} | {n} | {s:+.1f} | {dd:.1f} | {r:.1f} | {neg:.0%} |"
            for sub, n, s, dd, r, neg in rows if len(sub) in (1, 2, 3, 5) and (len(sub) < 3 or set(sub) in (set(FADE),) or len(sub) == 5)]
    s5, d5, neg5 = res
    ok = {"①R5 ΣR／回撤 ≥ rev15": s5 / d5 >= s15 / d15, "②R5 蝕錢月 ≤ rev15": neg5 <= neg15, "③急動對趨勢逐月相關 ≤ 0.2": corr <= 0.2}
    out += ["", f"- 急動三條對趨勢兩條逐月相關 {corr:+.2f}（{len(allm)} 個月）；R5 ΣR／回撤 {s5 / d5:.1f} 對 rev15 {s15 / d15:.1f}；蝕錢月 {neg5:.0%} 對 {neg15:.0%}",
            *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], ""]
    return out, ok


def main():
    out = ["# 兩類代表組合（IDEAS #1124）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張 1R；⭐＝主判（5 條全部）；表只列單條、兩條、急動三條同 5 條", ""]
    allok, alltr = {}, {k: [] for k in FNS}
    for name, src, a, b in SETS:
        d = A.load(src, a, b)
        tr = {k: [(int(ts), int(sg), float(r)) for ts, sg, r in f(d)] for k, f in FNS.items()}
        del d
        for k in FNS:
            alltr[k] += tr[k]
        sec, ok = section(name, tr); out += sec
        allok.update({f"{name} {k}": v for k, v in ok.items()})
    yrs = list(range(2010, 2027))
    yr = {k: np.array([sum(r for ts, _, r in v if year(ts) == y) for y in yrs]) for k, v in alltr.items()}
    y5 = sum(yr.values()); yf = sum(yr[k] for k in FADE); yt = sum(yr[k] for k in TREND)
    out += ["## 逐年 ΣR（2010–2026；2026 到 10 月）", "", "| 年 | " + " | ".join(NAMES[k] for k in FNS) + " | 急動三條 | 趨勢兩條 | ⭐5 條 |", "|---" * (len(FNS) + 4) + "|"]
    out += [f"| {y} | " + " | ".join(f"{yr[k][i]:+.1f}" for k in FNS) + f" | {yf[i]:+.1f} | {yt[i]:+.1f} | **{y5[i]:+.1f}** |" for i, y in enumerate(yrs)]
    lose = {k: int((v < 0).sum()) for k, v in yr.items()}
    out += ["", "- 蝕錢年份：" + "、".join(f"{NAMES[k]} {lose[k]}" for k in FNS) + f"、急動三條 {int((yf < 0).sum())}、趨勢兩條 {int((yt < 0).sum())}、**5 條 {int((y5 < 0).sum())}**",
            f"- 5 條最差一年 {yrs[int(np.argmin(y5))]} {y5.min():+.1f}R", ""]
    allok["④17 年 R5 蝕錢年份 ≤ 1"] = int((y5 < 0).sum()) <= 1
    allok["⑤R5 最差一年 ≥ −5R"] = float(y5.min()) >= -5
    out += ["## 判（預先登記 IDEAS #1124；主判 5 條全部）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in allok.items() if k[0] in "④⑤"],
            "- " + ("✅ 達標 → 只提案：5 條一齊影子前向（已喺 #1028 影子單條），各自前向達標先逐條提案上實倉" if all(allok.values())
                    else "❌ 唔達：" + "、".join(k for k, v in allok.items() if not v) + "；唔准改標準再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "COMBO_1124.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
