"""大股災：探索所得假設嘅樣本外驗證（IDEAS #10005，2026-11-14 預先登記；只跑一次）。

探索（1987–2026，crash_features.py）揀出四個假設，喺從未用過嘅 1928–1986 標普 500 驗證：
  H1 立春年局：生門宮落空亡 → 股災年較多          H2 立春年局：日干宮臨凶門（死、驚、傷）→ 股災年較多
  H3 節氣局：生門宮落空亡 → 股災節氣較多          H4 節氣局：時干宮「凶門＋凶星」→ 股災節氣較少
股災名單同一條死規則（21 個交易日跌 ≥ 20%），只用標普 500。盤：北京時間節氣交節一刻（jieqi_ju.py）。

用法：python3 research/qimen/crash_validate.py   （要 pip install ephem）
"""
import math
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crash_events as ce
from crash_features import features
from jieqi_ju import TZ, terms
from qiju import qiju

HERE = os.path.dirname(os.path.abspath(__file__))
Y0, Y1, ALPHA = 1928, 1986, 0.05 / 4


def fisher_ge(a, r1, c1, n):
    """P(X >= a)，超幾何：n 個入面 c1 個有特徵，抽 r1 個股災。"""
    return sum(math.comb(c1, x) * math.comb(n - c1, r1 - x) for x in range(a, min(r1, c1) + 1)) / math.comb(n, r1)


def main():
    ce.START = "1927-12-01"
    d = [x for x in ce.load(ce.FILES["標普500"]) if x[0] <= f"{Y1 + 1}-02-10"]
    ev = ce.segments(d)
    rows = []
    for t, name, lam in terms(Y0, Y1):
        q = qiju(t, 0, lam=lam, clock_offset_hours=TZ)
        rows.append({"bj": (t.replace(tzinfo=None) + timedelta(hours=TZ)).strftime("%Y-%m-%d"), "jieqi": name, "f": features(q)})
    days = [r["bj"] for r in rows]
    m = len(rows)
    overlap = [0] * m
    crash_years = set()
    lichun = [i for i, r in enumerate(rows) if r["jieqi"] == "立春"]
    for a, b in ev:
        if a < days[0]:
            continue
        i = max(k for k in range(m) if days[k] <= a)
        j = max(k for k in range(m) if days[k] <= b)
        for k in range(i, j + 1):
            overlap[k] = 1
        crash_years.add(max(k for k in lichun if days[k] <= a))
    L = ["# 大股災假設樣本外驗證（IDEAS #10005）", "", f"數據：標普 500，{Y0}–{Y1}；預先登記見 `research/qimen/PREREG.md`；只跑一次。", "",
         f"股災事件 {sum(1 for a, b in ev if a >= days[0])} 次：" + "、".join(f"{a}→{b}" for a, b in ev if a >= days[0]), "",
         f"立春年局 {len(lichun)} 個，股災年 {len(crash_years)} 個（{'、'.join(sorted(days[k][:4] for k in crash_years))}）；節氣局 {m} 個，股災節氣 {sum(overlap)} 個。", "",
         "| 假設 | 股災 | 平常 | p | 過（p < 0.0125） |", "|---|---|---|---|---|"]
    # 立春：Fisher 單尾
    for tag, key in (("H1 立春：生門宮落空亡（股災年較多）", "生門宮：落空亡"), ("H2 立春：日干宮臨凶門（股災年較多）", "日干宮：凶門")):
        a = sum(rows[k]["f"][key] for k in crash_years)
        c = sum(rows[k]["f"][key] for k in lichun if k not in crash_years)
        r1, n = len(crash_years), len(lichun)
        p = fisher_ge(a, r1, a + c, n)
        L.append(f"| {tag} | {a}/{r1}（{a / r1:.0%}） | {c}/{n - r1}（{c / (n - r1):.0%}） | {p:.4f} | {'✅' if p < ALPHA else '❌'} |")
    # 節氣：循環平移
    for tag, key, sign in (("H3 節氣：生門宮落空亡（股災節氣較多）", "生門宮：落空亡", 1), ("H4 節氣：時干宮凶門＋凶星（股災節氣較少）", "時干宮：凶門＋凶星", -1)):
        x = [int(r["f"][key]) for r in rows]
        k1 = sum(overlap)

        def diff(sh):
            a = sum(x[i] for i in range(m) if overlap[(i + sh) % m])
            return a / k1 - (sum(x) - a) / (m - k1)
        obs = diff(0)
        p = sum(sign * diff(sh) >= sign * obs for sh in range(m)) / m
        a = sum(x[i] for i in range(m) if overlap[i])
        L.append(f"| {tag} | {a}/{k1}（{a / k1:.0%}） | {sum(x) - a}/{m - k1}（{(sum(x) - a) / (m - k1):.0%}） | {p:.4f} | {'✅' if p < ALPHA else '❌'} |")
    open(os.path.join(HERE, "CRASH_VALIDATE.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
