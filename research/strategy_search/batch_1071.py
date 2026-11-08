"""[IDEAS #1071–#1074] 第十四批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1071 M1 跳價：今根開市同上一根收市相差 ≥ 1.5 美元（同一交易段、相隔 ≤ 2 分鐘）→ 反向 E6S4（以今根收市為基準），冷卻 60 分鐘；
#1072 M15 長影線拒絕：幅 ≥ 5 美元、上影線 ≥ 70% 幅 → 下一根開市做空（下影線相反做多），SL 極端外 0.3、TP 1R、4 根；
#1073 H1 雙頂／雙底：前 24 根內嘅擺動高（左右各 3 根較低）再被觸及（± 0.5 美元內第一次）→ E6S4 反向（以擺動高為價位）；
#1074 rev15 只做「靜極思動」：觸發前 60 分鐘（觸發前 15 根之前）高低幅 < 3 美元先做；要高過 rev15 全部 ≥ +0.03R。
成本每張 0.5 美元。
用法：python3 research/strategy_search/batch_1071.py → research/strategy_search/BATCH_1071.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1033 as B33        # noqa: E402
import combo_1027 as C          # noqa: E402
import ai_entry_forward as af   # noqa: E402

A = B.A
fr = af.fr
COST = 0.5


def r1071(d):
    t, o, c = d["t"], d["o"], d["c"]; n = len(t)
    gap = np.r_[0.0, o[1:] - c[:-1]]; dtm = np.r_[999, np.diff(t)]
    ok = (np.abs(gap) >= 1.5) & (dtm <= 120) & (np.arange(n) >= 30)
    raw = [(int(i), "BUY" if gap[i] < 0 else "SELL") for i in np.nonzero(ok)[0]]
    sigs = fr.cooldown(raw, t, 60, int(t[0]), int(t[-1]) + 60)
    r = fr.simulate(fr.future_mats(d, sigs), 6.0, 2.0, 4.0, 1.0)
    return [(int(t[i]) + 60, 1 if s == "BUY" else -1, float(x)) for (i, s), x in zip(sigs, r) if not np.isnan(x)]


def r1072(d):
    b = B.resample(d, 900); o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    out, busy = [], -1
    for i in range(1, len(c) - 1):
        if i <= busy:
            continue
        rg = h[i] - l[i]
        if rg < 5:
            continue
        up_w = h[i] - max(o[i], c[i]); dn_w = min(o[i], c[i]) - l[i]
        sg = -1 if up_w >= 0.7 * rg else (1 if dn_w >= 0.7 * rg else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; sl = (h[i] + 0.3) if sg < 0 else (l[i] - 0.3); risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, sl, en + sg * risk, 4)
        busy = ei + 3
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1073(d):
    b = B.resample(d, 3600); h, l = b["h"], b["l"]; bt = b["t"]
    t = d["t"]; H, L = d["h"], d["l"]
    piv = []                                               # (確認時間, 價, 類別)
    for i in range(3, len(h) - 3):
        if h[i] > h[i - 3:i].max() and h[i] > h[i + 1:i + 4].max():
            piv.append((int(bt[i + 3]) + 3600, float(h[i]), -1))
        if l[i] < l[i - 3:i].min() and l[i] < l[i + 1:i + 4].min():
            piv.append((int(bt[i + 3]) + 3600, float(l[i]), 1))
    out = []
    for ct, px, sg in piv:
        a = int(np.searchsorted(t, ct)); end = int(np.searchsorted(t, ct + 24 * 3600))
        for i in range(a, min(end, len(t))):
            touch = (H[i] >= px - 0.5) if sg < 0 else (L[i] <= px + 0.5)
            if touch:
                mid = px - sg * 6.0
                r = af.sim(d, int(t[i]) + 60, "BUY" if sg > 0 else "SELL", mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
                if r is not None:
                    out.append((int(t[i]), sg, r))
                break
    out.sort()
    ded, last = [], -10**12                                # 同一時間多個擺動點只計一張；60 分鐘冷卻
    for x in out:
        if x[0] - last >= 3600:
            ded.append(x); last = x[0]
    return ded


def r1074(d):
    tr = C.rev15(d); t, h, l = d["t"], d["h"], d["l"]
    keep = []
    for ts, sg, r in tr:
        i = int(np.searchsorted(t, ts - 60))
        a, b = i - 75, i - 15
        if a < 0:
            continue
        if h[a:b].max() - l[a:b].min() < 3.0:
            keep.append((ts, sg, r))
    return keep, tr


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第十四批四條規則（IDEAS #1071–#1074）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1071 M1 跳價 ≥ 1.5 美元反向 E6S4", r1071, 300, 150),
                             ("#1072 M15 長影線拒絕（幅 ≥ 5、影線 ≥ 70%；SL 極端外 0.3；TP 1R；4 根）", r1072, 300, 150),
                             ("#1073 H1 雙頂／雙底第二次觸及 → E6S4 反向", r1073, 300, 150)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    (fd, ad), (fm, am) = r1074(duka), r1074(mt5)
    ok, lines, sd, sm = B33.judge(fd, fm, 300, 150)
    bd, bm = A.stats([x[2] for x in ad]), A.stats([x[2] for x in am])
    ok["④Duka 高過 rev15 全部 ≥ +0.03R"] = sd["n"] > 0 and sd["avg"] - bd["avg"] >= 0.03
    ok["⑤MT5 高過 rev15 全部 ≥ +0.03R"] = sm["n"] > 0 and sm["avg"] - bm["avg"] >= 0.03
    out += ["## #1074 rev15 靜極思動（之前 60 分鐘幅 < 3 美元）", "", *lines, f"- 對照 rev15 全部：Duka {A.fmt(bd)}；MT5 {A.fmt(bm)}",
            *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1071.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
