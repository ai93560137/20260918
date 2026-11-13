"""奇門遁甲測市回測（IDEAS #10003，2026-11-13 預先登記；只跑一次，唔調參）。

每個交易日喺現貨開市一刻（當地時間 09:30）起局：英國真太陽時（經度 0.25°E）、時家拆補轉盤，用評分表 v1
（score.py）判升／跌／棄權，對答案＝當日收市 > 開市為升。對照：永遠估升、前一日方向、置換檢定（擲毫）。

用法：python3 research/qimen/backtest.py --kb kb.json [--out research/qimen/backtest]
"""
import argparse
import csv
import gzip
import math
import os
import random
import sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qiju import qiju
from score import load_kb, score

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MARKETS = {  # 名：（日線檔, 開市時區）
    "HSI": ("canary/data_external/hsi_daily.csv", "Asia/Hong_Kong"),
    "NDX": ("data/us_futures/IDX_NDX_daily.csv", "America/New_York"),
    "SPX": ("data/us_futures/IDX_GSPC_daily.csv", "America/New_York"),
}
START, LON, ALPHA, PERM, SEED = "2000-01-01", 0.25, 0.05 / 3, 2000, 20261113


def binom_sf(k, n):
    """P(X >= k), X ~ Bin(n, 0.5)。"""
    if n == 0:
        return float("nan")
    logs = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) - n * math.log(2) for i in range(k, n + 1)]
    m = max(logs)
    return math.exp(m) * sum(math.exp(x - m) for x in logs)


def run_market(name, path, tz, kb):
    rows = []
    prev_dir = None
    for r in csv.DictReader(open(os.path.join(ROOT, path), encoding="utf-8")):
        try:
            o, c = float(r["Open"]), float(r["Close"])
        except (ValueError, KeyError):
            continue
        d = r["Date"][:10]
        direction = "升" if c > o else "跌" if c < o else None
        if d >= START and direction:
            y, m, dd = map(int, d.split("-"))
            utc = datetime(y, m, dd, 9, 30, tzinfo=ZoneInfo(tz)).astimezone(ZoneInfo("UTC"))
            q = qiju(utc, LON)
            s = score(q["盤"], q["時柱"], q["月支"], kb)
            rows.append({"date": d, "ganzhi": q["四柱"], "ju": q["局"], "score": s["總分"], "call": s["call"],
                         "dir": direction, "ret": c / o - 1, "prev": prev_dir})
        if direction:
            prev_dir = direction
    return rows


def stats(rows):
    act = [r for r in rows if r["call"] != "棄權"]
    n = len(act)
    hit = sum(r["call"] == r["dir"] for r in act)
    up = sum(r["dir"] == "升" for r in act)
    pv = [r for r in act if r["prev"]]
    prev_hit = sum(r["prev"] == r["dir"] for r in pv)
    rng = random.Random(SEED)
    calls = [r["call"] for r in act]
    dirs = [r["dir"] for r in act]
    ge = 0
    for _ in range(PERM):
        rng.shuffle(calls)
        ge += sum(a == b for a, b in zip(calls, dirs)) >= hit
    ru = [r["ret"] for r in act if r["call"] == "升"]
    rd = [r["ret"] for r in act if r["call"] == "跌"]

    def mv(x):
        m = sum(x) / len(x)
        return m, sum((v - m) ** 2 for v in x) / (len(x) - 1)
    (mu, vu), (md, vd) = mv(ru), mv(rd)
    t = (mu - md) / math.sqrt(vu / len(ru) + vd / len(rd))
    return {"days": len(rows), "n": n, "abstain": 1 - n / len(rows), "hit": hit, "rate": hit / n, "p_binom": binom_sf(hit, n),
            "up_rate": up / n, "prev_rate": prev_hit / len(pv), "p_perm": (ge + 1) / (PERM + 1),
            "n_up": len(ru), "n_dn": len(rd), "ret_up": mu, "ret_dn": md, "t": t}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest"))
    a = ap.parse_args()
    kb = load_kb(a.kb)
    os.makedirs(a.out, exist_ok=True)
    L = ["# 奇門遁甲測市回測（IDEAS #10003）", "",
         f"跑於 {datetime.now(ZoneInfo('Asia/Hong_Kong')):%Y-%m-%d %H:%M} HKT。預先登記見 `research/qimen/PREREG.md`；只跑一次。", "",
         "## 主要結果", "",
         "| 市場 | 期間 | 交易日 | 非棄權 | 棄權率 | 命中率 | 二項 p | 永遠估升 | 前一日方向 | 置換 p | 四關 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    detail = []
    for name, (path, tz) in MARKETS.items():
        rows = run_market(name, path, tz, kb)
        with gzip.open(os.path.join(a.out, f"calls_{name}.csv.gz"), "wt", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        s = stats(rows)
        ok = [s["p_binom"] < ALPHA and s["rate"] > 0.5, s["rate"] > s["up_rate"], s["rate"] > s["prev_rate"], s["p_perm"] < ALPHA]
        L.append(f"| {name} | {rows[0]['date']}→{rows[-1]['date']} | {s['days']} | {s['n']} | {s['abstain']:.1%} | **{s['rate']:.2%}** "
                 f"| {s['p_binom']:.4f} | {s['up_rate']:.2%} | {s['prev_rate']:.2%} | {s['p_perm']:.4f} "
                 f"| {''.join('✅' if x else '❌' for x in ok)} {'通過' if all(ok) else '唔過'} |")
        detail += ["", f"## {name} 明細", "",
                   f"- 估升 {s['n_up']} 日，平均開→收回報 {s['ret_up']:+.4%}；估跌 {s['n_dn']} 日，平均 {s['ret_dn']:+.4%}；差嘅 t 值 {s['t']:+.2f}。", "",
                   "| 強弱（總分絕對值） | 日數 | 命中率 |", "|---|---|---|"]
        for lab, lo, hi in (("弱 2–4", 2, 4), ("中 4–6", 4, 6), ("強 ≥6", 6, 1e9)):
            g = [r for r in rows if r["call"] != "棄權" and lo <= abs(r["score"]) < hi]
            detail.append(f"| {lab} | {len(g)} | {(sum(r['call'] == r['dir'] for r in g) / len(g) if g else float('nan')):.2%} |")
        detail += ["", "| 年 | 非棄權 | 命中率 | 永遠估升 |", "|---|---|---|---|"]
        by = defaultdict(list)
        for r in rows:
            if r["call"] != "棄權":
                by[r["date"][:4]].append(r)
        for y in sorted(by):
            g = by[y]
            detail.append(f"| {y} | {len(g)} | {sum(r['call'] == r['dir'] for r in g) / len(g):.1%} | {sum(r['dir'] == '升' for r in g) / len(g):.1%} |")
    L += ["", f"四關（每個市場，Bonferroni α＝0.05/3＝{ALPHA:.4f}）：① 命中率 > 50% 而且單尾二項 p < α；② 高過永遠估升；③ 高過前一日方向；"
          f"④ 置換檢定 p < α（將判斷隨機打亂 {PERM} 次，即擲毫對照）。"] + detail
    open(os.path.join(a.out, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:12]))


if __name__ == "__main__":
    main()
