"""[IDEAS #1041–#1044] 第七批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1041 紐約時段做空（14:00 開市價沽、19:59 收市走；SL 8 美元）；#1042 前日收市價回測 → E6S4 返原方向（同 #1039 一樣，只係用前日收市）；
#1043 週開市價回測 → E6S4 返原方向（離開 ≥ 20 美元後第一次返嚟；每週一次）；
#1044 D1 強勢收市延續：收市喺當日幅頂 10%（或底 10%）而幅 ≥ 1.5×ATR → 下一日開市順勢，SL 1×ATR，當日收市走。
成本每張 0.5 美元；一次一張。
用法：python3 research/strategy_search/batch_1041.py → research/strategy_search/BATCH_1041.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1033 as B33        # noqa: E402
import batch_1037 as B37        # noqa: E402
import ai_entry_forward as af   # noqa: E402

A = B.A
COST = 0.5


def r1041(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    sod = t % 86400; out = []
    for s, e in B37.days(t):
        a = np.nonzero(sod[s:e] == 14 * 3600)[0]
        if not len(a):
            continue
        i0 = a[0] + s; en = o[i0]; sl = en + 8.0; ex = None; last = i0
        for j in range(i0, e):
            if sod[j] >= 20 * 3600:
                break
            last = j
            if h[j] >= sl:
                ex = sl; break
        if ex is None:
            ex = c[last]
        out.append((int(t[i0]), -1, (en - ex - COST) / 8.0))
    return out


def revisit(d, s, e, lvl, away_usd, start_i):
    """由 start_i 起：收市離開 lvl ≥ away_usd 之後第一次返到 lvl → E6S4 返原方向；回傳 (ts, sg, r) 或 None。"""
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    away = 0
    for i in range(start_i, e):
        if away == 0:
            away = 1 if c[i] >= lvl + away_usd else (-1 if c[i] <= lvl - away_usd else 0)
            continue
        if (l[i] <= lvl) if away > 0 else (h[i] >= lvl):
            sg = away; mid = lvl - sg * 6.0
            r = af.sim(d, int(t[i]) + 60, "BUY" if sg > 0 else "SELL", mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
            return None if r is None else (int(t[i]), sg, r)
    return None


def r1042(d):
    out = []; ds = B37.days(d["t"])
    for (ps, pe), (s, e) in zip(ds[:-1], ds[1:]):
        x = revisit(d, s, e, d["c"][pe - 1], 10.0, s)
        if x:
            out.append(x)
    return out


def r1043(d):
    t = d["t"]; wk = (t // 86400 + 3) // 7
    st = np.r_[0, np.nonzero(np.diff(wk))[0] + 1, len(t)]
    out = []
    for s, e in zip(st[:-1], st[1:]):
        x = revisit(d, s, e, d["o"][s], 20.0, s + 1)
        if x:
            out.append(x)
    return out


def r1044(d):
    b = B.resample(d, 86400); o, h, l, c = b["o"], b["h"], b["l"], b["c"]; a = B.atr(b)
    out = []
    for i in range(15, len(c) - 1):
        if np.isnan(a[i]) or a[i] <= 0:
            continue
        rg = h[i] - l[i]
        if rg < 1.5 * a[i]:
            continue
        pos = (c[i] - l[i]) / rg
        sg = 1 if pos >= 0.9 else (-1 if pos <= 0.1 else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; risk = a[i]; sl = en - sg * risk
        ex = sl if ((l[ei] <= sl) if sg > 0 else (h[ei] >= sl)) else c[ei]
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第七批四條規則（IDEAS #1041–#1044）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1041 紐約時段做空（14:00→19:59，SL 8）", r1041, 300, 150),
                             ("#1042 前日收市價回測 → E6S4 返原方向", r1042, 200, 100),
                             ("#1043 週開市價回測 → E6S4 返原方向", r1043, 80, 40),
                             ("#1044 D1 強勢收市延續（幅頂／底 10%、幅 ≥ 1.5×ATR；SL 1×ATR；當日收市）", r1044, 100, 50)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1041.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
