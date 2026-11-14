"""七步法回測（IDEAS #10007，2026-11-14 預先登記；只跑一次）。

每個節氣交節一刻（北京時間）起局，用 qibu_score.py 計總分：> 0 判升、< 0 判跌、＝0 棄權。
期初＝交節前最後一個標普收市，期末＝下個交節前最後一個收市。1987 年立春起（使用者指示唔用 1987 年之前）。

用法：python3 research/qimen/qibu_backtest.py --kb kb.json   （要 pip install ephem）
"""
import argparse
import bisect
import csv
import math
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crash_events as ce
from jieqi_ju import TZ, terms
from qibu_score import qibu
from qiju import qiju
from score import load_kb

HERE = os.path.dirname(os.path.abspath(__file__))
ALPHA = 0.025


def auc(pos, neg):
    return sum((p < n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True)
    kb = load_kb(ap.parse_args().kb)
    ce.START = "1986-12-01"
    data = {n: ce.load(p) for n, p in ce.FILES.items()}
    dates = {n: [x[0] for x in d] for n, d in data.items()}

    def last_idx(n, day):                          # day（北京日期）之前最後一個收市（當日唔計）
        return bisect.bisect_left(dates[n], day) - 1

    T = list(terms(1987, 2026))
    rows = []
    for k in range(len(T) - 1):
        t, name, lam = T[k]
        d0 = (t.replace(tzinfo=None) + timedelta(hours=TZ)).strftime("%Y-%m-%d")
        d1 = (T[k + 1][0].replace(tzinfo=None) + timedelta(hours=TZ)).strftime("%Y-%m-%d")
        if d1 > dates["標普500"][-1]:
            break
        i0, i1 = last_idx("標普500", d0), last_idx("標普500", d1)
        if i0 < 0 or i1 <= i0:
            continue
        s0, s1 = data["標普500"][i0][1], data["標普500"][i1][1]
        crash = 0
        for n in data:
            a, b = last_idx(n, d0), last_idx(n, d1)
            if a >= 0 and b > a and min(x[1] for x in data[n][a + 1:b + 1]) <= 0.9 * data[n][a][1]:
                crash = 1
        q = qiju(t, 0, lam=lam, clock_offset_hours=TZ)
        sc, d = qibu(q, kb)
        rows.append({"beijing": d0, "jieqi": name, "ganzhi": q["四柱"], "ju": q["局"], "score": sc, **{k2: v for k2, v in d.items()},
                     "call": "升" if sc > 0 else "跌" if sc < 0 else "棄權", "dir": "升" if s1 > s0 else "跌", "ret": s1 / s0 - 1, "crash": crash})
    with open(os.path.join(HERE, "qibu_backtest_calls.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    m = len(rows)
    call = [r["call"] for r in rows]
    dr = [r["dir"] for r in rows]
    act = [i for i in range(m) if call[i] != "棄權"]
    hit = sum(call[i] == dr[i] for i in act)
    rate = hit / len(act)
    up = sum(dr[i] == "升" for i in act) / len(act)
    prev = [i for i in act if i > 0]
    prev_rate = sum(dr[i - 1] == dr[i] for i in prev) / len(prev)
    # 循環平移：判斷唔郁，結果沿時間平移
    ge = sum(sum(call[i] == dr[(i + sh) % m] for i in act) >= hit for sh in range(m))
    p1 = ge / m
    ru = [rows[i]["ret"] for i in act if call[i] == "升"]
    rd = [rows[i]["ret"] for i in act if call[i] == "跌"]
    sc = [r["score"] for r in rows]
    cr = [r["crash"] for r in rows]
    a2 = auc([s for s, c in zip(sc, cr) if c], [s for s, c in zip(sc, cr) if not c])
    ge2 = sum(auc([sc[i] for i in range(m) if cr[(i + sh) % m]], [sc[i] for i in range(m) if not cr[(i + sh) % m]]) >= a2 for sh in range(m))
    p2 = ge2 / m
    ok1 = rate > up and rate > prev_rate and p1 < ALPHA
    L = ["# 七步法回測（IDEAS #10007）", "", "預先登記見 `research/qimen/PREREG.md`；只跑一次。", "",
         f"節氣局 {m} 個（{rows[0]['beijing']} → {rows[-1]['beijing']}）；總分平均 {sum(sc) / m:+.2f}、最低 {min(sc):+.1f}、最高 {max(sc):+.1f}。", "",
         "## ① 方向（標普 500，節氣期初收市 → 期末收市）", "",
         f"- 非棄權 {len(act)} 個（棄權率 {1 - len(act) / m:.1%}）；判升 {len(ru)} 個、判跌 {len(rd)} 個。",
         f"- 命中率 **{rate:.2%}**；永遠估升 {up:.2%}；前一個節氣方向 {prev_rate:.2%}；循環平移 p＝{p1:.4f}。",
         f"- 判升嘅節氣平均回報 {sum(ru) / len(ru):+.2%}；判跌嘅 {sum(rd) / len(rd):+.2%}。",
         f"- 判決：{'✅ 過' if ok1 else '❌ 唔過'}（要高過永遠估升、高過前一個節氣方向、p < {ALPHA}）。", "",
         "## ② 大跌（期內標普／納指 100／恒指任何一個收市低過期初 ≥ 10%）", "",
         f"- 大跌節氣 {sum(cr)} 個／{m}。總分愈低愈應該係大跌：AUC＝**{a2:.3f}**（0.5＝冇分別）；循環平移 p＝{p2:.4f}。",
         f"- 大跌節氣平均總分 {sum(s for s, c in zip(sc, cr) if c) / sum(cr):+.2f}；其餘 {sum(s for s, c in zip(sc, cr) if not c) / (m - sum(cr)):+.2f}。",
         f"- 判決：{'✅ 過' if p2 < ALPHA else '❌ 唔過'}（p < {ALPHA}）。", "",
         "## 各步分數同方向嘅關係（只作描述）", "", "| 步 | 分數 > 0 時標普升嘅比例 | 分數 < 0 時 | 分數＝0 時 |", "|---|---|---|---|"]
    for key in ("一年干", "二戊", "三擊刑", "四值符值使", "五三門", "六星神"):
        def pr(cond):
            g = [r for r in rows if cond(r[key])]
            return f"{sum(r['dir'] == '升' for r in g) / len(g):.0%}（{len(g)}）" if g else "—"
        L.append(f"| {key} | {pr(lambda v: v > 0)} | {pr(lambda v: v < 0)} | {pr(lambda v: v == 0)} |")
    open(os.path.join(HERE, "QIBU_BACKTEST.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
