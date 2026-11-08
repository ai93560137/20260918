"""[IDEAS #1059–#1062] 第十一批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1059 日線樞軸點（前日 P、R1、S1、R2、S2）第一次觸及 → E6S4 反向（每價位每日一次，01–19:59 UTC）；
#1060 50 美元關口突破後回測（收市穿過關口 ≥ 5 美元，4 個鐘內第一次返到關口 → 順突破方向，入場區關口 ±2、SL 再過 4、TP 1R、30 分鐘）；
#1061 rev240：前 240 根 M1 走幅 ≥ 20 美元 → 反向 E6S4（冷卻 240 分鐘）；
#1062 週樞軸點 P（上星期 (H+L+C)/3）第一次觸及 → E6S4 反向（每週一次）。
成本每張 0.5 美元。
用法：python3 research/strategy_search/batch_1059.py → research/strategy_search/BATCH_1059.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1033 as B33        # noqa: E402
import batch_1037 as B37        # noqa: E402
import ai_entry_forward as af   # noqa: E402

A = B33.A
fr = af.fr


def fade(d, i, sg, lvl):
    mid = lvl - sg * 6.0
    return af.sim(d, int(d["t"][i]) + 60, "BUY" if sg > 0 else "SELL", mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)


def r1059(d):
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]; hour = (t // 3600) % 24
    out = []; ds = B37.days(t)
    for (ps, pe), (s, e) in zip(ds[:-1], ds[1:]):
        H, L, C = h[ps:pe].max(), l[ps:pe].min(), c[pe - 1]
        P = (H + L + C) / 3
        lv = [P, 2 * P - L, 2 * P - H, P + (H - L), P - (H - L)]
        used = set()
        for i in range(s + 1, e):
            if not (1 <= hour[i] < 20):
                continue
            pc = c[i - 1]
            for k, x in enumerate(lv):
                if k in used:
                    continue
                if pc < x <= h[i]:
                    sg = -1
                elif pc > x >= l[i]:
                    sg = 1
                else:
                    continue
                used.add(k)
                r = fade(d, i, sg, x)
                if r is not None:
                    out.append((int(t[i]), sg, r))
    return out


def r1060(d):
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    out = []; i = 1; n = len(t)
    while i < n:
        lvl_up = np.floor((c[i] - 5) / 50) * 50            # 收市高過關口 ≥ 5
        lvl_dn = np.ceil((c[i] + 5) / 50) * 50
        brk = None
        if c[i - 1] < lvl_up + 5 <= c[i] and c[i - 1] < lvl_up + 50:
            brk = (1, lvl_up)
        elif c[i - 1] > lvl_dn - 5 >= c[i]:
            brk = (-1, lvl_dn)
        if brk is None:
            i += 1; continue
        sg, lvl = brk; done = False
        for j in range(i + 1, n):
            if t[j] - t[i] > 4 * 3600:
                break
            if (l[j] <= lvl + 2 + fr.TOL) if sg > 0 else (h[j] >= lvl - 2 - fr.TOL):
                r = af.sim(d, int(t[j - 1]) + 60, "BUY" if sg > 0 else "SELL", lvl, lvl - sg * 4.0, lvl + sg * 4.0, lo=lvl - 2.0, hi=lvl + 2.0)
                if r is not None:
                    out.append((int(t[j]), sg, r))
                i = j + 1; done = True; break
        if not done:
            i += 1
    return out


def r1061(d):
    t, o, c = d["t"], d["o"], d["c"]; n = len(t)
    mv = np.full(n, np.nan); mv[240:] = c[240:] - o[:-240]
    ok = (np.abs(mv) >= 20.0) & (np.arange(n) >= 254)
    raw = [(int(i), "BUY" if mv[i] < 0 else "SELL") for i in np.nonzero(ok)[0]]
    sigs = fr.cooldown(raw, t, 240, int(t[0]), int(t[-1]) + 60)
    r = fr.simulate(fr.future_mats(d, sigs), 6.0, 2.0, 4.0, 1.0)
    return [(int(t[i]) + 60, 1 if s == "BUY" else -1, float(x)) for (i, s), x in zip(sigs, r) if not np.isnan(x)]


def r1062(d):
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    wk = (t // 86400 + 3) // 7
    st = np.r_[0, np.nonzero(np.diff(wk))[0] + 1, len(t)]
    out = []
    for (ps, pe), (s, e) in zip(zip(st[:-2], st[1:-1]), zip(st[1:-1], st[2:])):
        P = (h[ps:pe].max() + l[ps:pe].min() + c[pe - 1]) / 3
        for i in range(s + 1, e):
            pc = c[i - 1]
            sg = -1 if pc < P <= h[i] else (1 if pc > P >= l[i] else 0)
            if sg:
                r = fade(d, i, sg, P)
                if r is not None:
                    out.append((int(t[i]), sg, r))
                break
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第十一批四條規則（IDEAS #1059–#1062）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1059 日線樞軸點（P／R1／S1／R2／S2）觸及 → E6S4 反向", r1059, 300, 150),
                             ("#1060 50 美元關口突破後回測 → 順突破方向", r1060, 200, 100),
                             ("#1061 rev240（4 個鐘走 ≥ 20 美元反向 E6S4）", r1061, 200, 100),
                             ("#1062 週樞軸點 P 觸及 → E6S4 反向", r1062, 100, 50)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1059.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
