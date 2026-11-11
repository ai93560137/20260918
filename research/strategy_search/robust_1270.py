"""[IDEAS #1270] 穩健度檢查（描述，唔揀參數）：#1268／#1269 嘅鄰近參數係咪都得（平台）定係只得登記嗰組得（尖峰＝撞彩）；另加 6 條「方向一致」規則嘅相關度同組合回落。
使用者 11-11「繼續研究」。規格以 IDEAS #1270 預先登記為準（跑之前 commit）。**登記參數（SMA200／20 日）唔會因為呢個結果而改**；呢度只係睇結果穩唔穩。
數據：stooq 日線黃金 1975–2026（日線成交模擬、成本 0.05%，同 #1260）；分 1975–2004（舊，揀規則時未見過）同 2005–2026（新）。
用法：python3 research/strategy_search/robust_1270.py → research/strategy_search/ROBUST_1270.md"""
import csv
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import fade_strict_1136 as F2   # noqa: E402
import gate_c_1240 as GC        # noqa: E402
import h1_lab8 as H8            # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import momo_strict_1164 as MS3  # noqa: E402
import momo_strict_1178 as MS5  # noqa: E402
import oldgold2_1261 as O2      # noqa: E402
import oldgold_1260 as OG       # noqa: E402

OUT = os.path.join(HERE, "ROBUST_1270.md")
DIRS = (100, 150, 200, 250, 300)
ENTS = (10, 20, 30, 40)


def load():
    t, o, h, l, c = [], [], [], [], []
    with open(os.path.join(OG.MD, "stooq_xauusd_d.csv")) as fh:
        r = csv.reader(fh); next(r)
        for row in r:
            if row[0] < "1973-01-01" or row[0] > "2026-10-30":
                continue
            t.append(OG.ts(row[0])); o.append(float(row[1])); h.append(float(row[2])); l.append(float(row[3])); c.append(float(row[4]))
    return {"t": np.array(t, np.int64), "o": np.array(o), "h": np.array(h), "l": np.array(l), "c": np.array(c)}


def topdown(d, kind, nd, ne):
    """kind 'pb'＝#1268（回調後重拾 SMA ne；出場＝跌穿之前 ne 日最低收市）；'bo'＝#1269（破 ne 日最高收市；出場＝跌穿之前 ne//2 日最低收市）。方向＝收市對 SMA nd。"""
    cx = M3.d1ctx(d); c = cx.b["c"]; n = len(c); md = F2.sma(c, nd); me = F2.sma(c, ne); s = np.zeros(n); cur = 0; nx = ne if kind == "pb" else max(2, ne // 2)
    for i in range(max(nd, ne) + 1, n):
        up, dn = c[i] > md[i], c[i] < md[i]
        if cur > 0 and (not up or c[i] < c[i - nx:i].min()):
            cur = 0
        elif cur < 0 and (not dn or c[i] > c[i - nx:i].max()):
            cur = 0
        if cur == 0:
            if kind == "pb":
                if up and c[i] > me[i] and c[i - 1] <= me[i - 1]:
                    cur = 1
                elif dn and c[i] < me[i] and c[i - 1] >= me[i - 1]:
                    cur = -1
            else:
                if up and c[i] > c[i - ne:i].max():
                    cur = 1
                elif dn and c[i] < c[i - ne:i].min():
                    cur = -1
        s[i] = cur
    return [(int(a), int(b), float(r)) for a, b, r in GC.edge_sigs(cx, s, 3.0, 250, lambda k, sg: s[k] != sg)]


def seg(tr, y0, y1):
    return [x for x in tr if y0 <= OG.year(x[0]) <= y1]


def cell(tr):
    n, avg, pf = OG.stats(tr)
    return f"{avg:+.2f}／{pf:.2f}（{n}）"


def monthly(tr, y0, y1):
    out = np.zeros((y1 - y0 + 1) * 12)
    for t_, _, r in tr:
        x = dt.datetime.fromtimestamp(int(t_), dt.timezone.utc)
        if y0 <= x.year <= y1:
            out[(x.year - y0) * 12 + x.month - 1] += r
    return out


def maxdd(x):
    eq = np.cumsum(x); return float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())


def main():
    d = load(); restore = OG.patch("gold")
    try:
        grid = {(k, nd, ne): topdown(d, k, nd, ne) for k in ("pb", "bo") for nd in DIRS for ne in ENTS}
        members = [("#1114", OG.tup(H8.r1114)(d)), ("#1165", OG.tup(MS3.r1165)(d)), ("#1178", OG.tup(MS5.r1178)(d)),
                   ("#1263", [(a, b, r * 3) for a, b, r in O2.r1263(d)]), ("#1268", grid[("pb", 200, 20)]), ("#1269", grid[("bo", 200, 20)])]
    finally:
        restore()
    L = ["# 穩健度檢查：鄰近參數＋相關度（IDEAS #1270；描述，唔揀參數）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；stooq 日線黃金，日線成交模擬、成本 0.05%；格＝每張平均 R／PF（張數）；**粗體**＝登記參數", ""]
    for kind, nm in (("pb", "#1268 方向＋回調後重拾均線"), ("bo", "#1269 方向＋突破")):
        for (y0, y1, lab) in ((1975, 2004, "舊黃金 1975–2004"), (2005, 2026, "新黃金 2005–2026")):
            L += [f"## {nm}：{lab}", "", "| 方向均線＼入場日數 | " + " | ".join(str(e) for e in ENTS) + " |", "|---|" + "---|" * len(ENTS)]
            for nd in DIRS:
                L.append(f"| SMA{nd} | " + " | ".join((f"**{cell(seg(grid[(kind, nd, ne)], y0, y1))}**" if (nd, ne) == (200, 20) else cell(seg(grid[(kind, nd, ne)], y0, y1))) for ne in ENTS) + " |")
            L.append("")
        both = sum(1 for nd in DIRS for ne in ENTS if OG.stats(seg(grid[(kind, nd, ne)], 1975, 2004))[1] > 0 and OG.stats(seg(grid[(kind, nd, ne)], 2005, 2026))[1] > 0)
        pfok = sum(1 for nd in DIRS for ne in ENTS if OG.stats(seg(grid[(kind, nd, ne)], 1975, 2004))[2] >= 1.15 and OG.stats(seg(grid[(kind, nd, ne)], 2005, 2026))[2] >= 1.15)
        half = sum(1 for nd in DIRS for ne in ENTS if OG.stats(seg(grid[(kind, nd, ne)], 1990, 2004))[1] > 0)
        L += [f"- {nm}：20 組參數入面，兩段每張平均都 > 0 嘅有 **{both}／20**；兩段 PF 都 ≥ 1.15 嘅有 **{pfok}／20**；1990–2004（最弱嗰段）每張平均 > 0 嘅有 {half}／20", ""]
    L += ["## 6 條「方向一致」規則：每月 R 相關度（1975–2026）", "", "| | " + " | ".join(k for k, _ in members) + " |", "|---|" + "---|" * len(members)]
    mon = {k: monthly(tr, 1975, 2026) for k, tr in members}
    for k, _ in members:
        L.append(f"| {k} | " + " | ".join(f"{np.corrcoef(mon[k], mon[j])[0, 1]:+.2f}" for j, _ in members) + " |")
    L += ["", "## 單條同組合（每個倉 1R；1975–2026 每月 R）", "", "| 組合 | 每年平均 R | 最大回落 R | 最差一年 R | 正數年 | 平均／回落 |", "|---|---|---|---|---|---|"]
    sets = [(k, [k]) for k, _ in members] + [("真倉三條 #1114＋#1165＋#1178", ["#1114", "#1165", "#1178"]), ("影子三條 #1263＋#1268＋#1269", ["#1263", "#1268", "#1269"]), ("六條", [k for k, _ in members])]
    for nm, ks in sets:
        x = np.sum([mon[k] for k in ks], axis=0); yr = x.reshape(-1, 12).sum(axis=1); dd = maxdd(x)
        L.append(f"| {nm} | {yr.mean():+.2f} | {dd:.1f} | {yr.min():+.1f} | {int((yr > 0).sum())}／{len(yr)} | {yr.mean() / dd if dd else 0:.2f} |")
    L += ["", "- ⚠ #1114／#1165／#1178 係用 2005 年後黃金揀出嚟，2005–2026 嗰部分有選擇偏差；#1263 每筆已乘返 3（每個子倉 1R）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
