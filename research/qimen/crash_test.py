"""大股災測試（IDEAS #10004，2026-11-14 預先登記；只跑一次）。

用評分表 v1 總分做「凶度」（總分愈低愈凶；伏吟局唔棄權，時干甲用旬首儀），睇立春年局同節氣局
分唔分得出股災年／股災節氣。盤同標籤由 jieqi_ju.py、crash_events.py 機械產生（北京時間）。

用法：python3 research/qimen/crash_test.py --kb kb.json   （要 pip install ephem）
"""
import argparse
import csv
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jieqi_ju import TZ, terms
from qiju import qiju
from score import load_kb, score

HERE = os.path.dirname(os.path.abspath(__file__))
SEED, PERM = 20261114, 10000


def auc(pos, neg):
    """P(股災盤總分 < 平常盤總分)＋0.5×P(相等)；0.5＝冇分別，愈高＝股災盤愈凶。"""
    w = sum((p < n) + 0.5 * (p == n) for p in pos for n in neg)
    return w / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True)
    a = ap.parse_args()
    kb = load_kb(a.kb)
    lab = {r["beijing"]: r for r in csv.DictReader(open(os.path.join(HERE, "crash_labels.csv"), encoding="utf-8"))}
    rows = []
    from datetime import timedelta
    for t, name, lam in terms(1987, 2026):
        q = qiju(t, 0, lam=lam, clock_offset_hours=TZ)
        bj = (t.replace(tzinfo=None) + timedelta(hours=TZ)).strftime("%Y-%m-%d %H:%M:%S")
        s = score(q["盤"], q["時柱"], q["月支"], kb, fuyin_abstain=False)
        rows.append({"beijing": bj, "jieqi": name, "ganzhi": q["四柱"], "ju": q["局"], "score": s["總分"],
                     "overlap": int(lab[bj]["crash_overlap_term"]), "start": int(lab[bj]["crash_start_term"]),
                     "crash_year": lab[bj]["lichun_crash_year"]})
    with open(os.path.join(HERE, "crash_test_scores.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    rng = random.Random(SEED)
    L = ["# 大股災測試（IDEAS #10004）", "", "預先登記見 `research/qimen/PREREG.md`；只跑一次。凶度＝評分表 v1 總分（愈低愈凶）。", ""]

    # ① 立春年局
    yr = [r for r in rows if r["jieqi"] == "立春"]
    pos = [r["score"] for r in yr if r["crash_year"] == "1"]
    neg = [r["score"] for r in yr if r["crash_year"] == "0"]
    a1 = auc(pos, neg)
    sc, lb = [r["score"] for r in yr], [r["crash_year"] == "1" for r in yr]
    ge = 0
    for _ in range(PERM):
        rng.shuffle(lb)
        ge += auc([s for s, l in zip(sc, lb) if l], [s for s, l in zip(sc, lb) if not l]) >= a1
    p1 = (ge + 1) / (PERM + 1)
    k = len(pos)
    top = sorted(yr, key=lambda r: (r["score"], r["beijing"]))[:k]
    hits = sum(r["crash_year"] == "1" for r in top)
    n = len(yr)
    ph = sum(math.comb(k, i) * math.comb(n - k, k - i) for i in range(hits, k + 1)) / math.comb(n, k)
    L += ["## ① 立春年局（40 個，股災年 13 個）", "",
          f"- AUC＝**{a1:.3f}**（0.5＝冇分別）；置換 p＝{p1:.4f}（{PERM} 次）。",
          f"- 總分最低（最凶）嘅 {k} 年入面，股災年有 **{hits}** 個（純靠估平均 {k * k / n:.1f}；超幾何 p＝{ph:.4f}）。",
          f"- 股災年平均總分 {sum(pos) / len(pos):+.2f}；平常年 {sum(neg) / len(neg):+.2f}。", "",
          "| 年 | 四柱 | 局 | 總分 | 股災年 | 入最凶 13 |", "|---|---|---|---|---|---|"]
    tops = {r["beijing"] for r in top}
    for r in yr:
        L.append(f"| {r['beijing'][:4]} | {r['ganzhi']} | {r['ju']} | {r['score']:+.1f} | {'是' if r['crash_year'] == '1' else ''} | {'✓' if r['beijing'] in tops else ''} |")

    # ② 節氣局：循環平移檢定（保留股災節氣連續出現嘅結構）
    sc = [r["score"] for r in rows]
    lb = [r["overlap"] for r in rows]
    a2 = auc([s for s, l in zip(sc, lb) if l], [s for s, l in zip(sc, lb) if not l])
    m = len(rows)
    ge = sum(auc([sc[i] for i in range(m) if lb[(i + sh) % m]], [sc[i] for i in range(m) if not lb[(i + sh) % m]]) >= a2 for sh in range(m))
    p2 = ge / m
    st = [r["score"] for r in rows if r["start"]]
    a3 = auc(st, [r["score"] for r in rows if not r["start"]])
    L += ["", "## ② 節氣局（958 個，股災節氣 70 個）", "",
          f"- AUC＝**{a2:.3f}**；循環平移 p＝{p2:.4f}（{m} 個平移，包括原位）。",
          f"- 股災節氣平均總分 {sum(s for s, l in zip(sc, lb) if l) / sum(lb):+.2f}；其餘 {sum(s for s, l in zip(sc, lb) if not l) / (m - sum(lb)):+.2f}。",
          f"- 只作描述：急跌開始嗰 14 個節氣 AUC＝{a3:.3f}。", "",
          "## 判決", "",
          f"合格＝兩個測試各自 p < 0.025（Bonferroni）。① p＝{p1:.4f} {'✅' if p1 < 0.025 else '❌'}；② p＝{p2:.4f} {'✅' if p2 < 0.025 else '❌'}。"]
    open(os.path.join(HERE, "CRASH_TEST.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:9] + L[-8:]))


if __name__ == "__main__":
    main()
