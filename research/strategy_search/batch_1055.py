"""[IDEAS #1055–#1058] 第十批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1055 H1 假突破（turtle soup）：H1 最高穿前 24 根最高、但收市返入去 → 下一根開市做空（低位相反），SL 嗰根極端外 0.5、TP 1R、12 根；
#1056 24 小時高／低（至少 6 個鐘冇再創）第一次觸及 → E6S4 反向；
#1057 D1 RSI(2) 回歸（Connors）：收市高過 SMA200 而 RSI2 < 10 → 下一日開市做多（低過 SMA200 而 RSI2 > 90 → 做空），收市過 SMA5（空：低過）走、最多 10 日，SL 2×ATR；
#1058 窄亞洲區間倫敦突破：亞洲 00–06:59 幅 < 0.5×ATR14(D1) 先做，07–11:59 第一根收市穿高／低 0.5 → 順勢，SL 亞洲中位、TP 2R、20:00 收（係 #1015 加窄幅濾網嘅新假說）。
成本每張 0.5 美元；一次一張。
用法：python3 research/strategy_search/batch_1055.py → research/strategy_search/BATCH_1055.md"""
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


def r1055(d):
    b = B.resample(d, 3600); o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    out, busy = [], -1
    for i in range(25, len(c) - 1):
        if i <= busy:
            continue
        ph, pl = h[i - 24:i].max(), l[i - 24:i].min()
        sg = -1 if (h[i] > ph and c[i] < ph) else (1 if (l[i] < pl and c[i] > pl) else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; sl = (h[i] + 0.5) if sg < 0 else (l[i] - 0.5); risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, sl, en + sg * risk, 12)
        busy = ei + 11
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1056(d):
    t, h, l = d["t"], d["h"], d["l"]
    n = len(t); out = []; last_fire = {1: -10**12, -1: -10**12}
    W, OLD = 1440, 360
    for i in range(W + 1, n):
        if t[i] - t[i - W] > 3 * 86400:                     # 跨週末太遠就略過
            continue
        seg_h = h[i - W:i]; seg_l = l[i - W:i]
        kh, kl = int(np.argmax(seg_h)), int(np.argmin(seg_l))
        for sg, lvl, age, ht in ((-1, seg_h[kh], W - kh, h[i] >= seg_h[kh]), (1, seg_l[kl], W - kl, l[i] <= seg_l[kl])):
            if not ht or age < OLD or t[i] - last_fire[sg] < 6 * 3600:
                continue
            last_fire[sg] = int(t[i]); mid = lvl - sg * 6.0
            r = af.sim(d, int(t[i]) + 60, "BUY" if sg > 0 else "SELL", mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
            if r is not None:
                out.append((int(t[i]), sg, r))
    return out


def rsi2(c):
    return B.rsi2(c)


def r1057(d):
    b = B.resample(d, 86400); c = b["c"]; a = B.atr(b); s200 = B.sma(c, 200); s5 = B.sma(c, 5); r = rsi2(c)
    out, i = [], 201
    while i < len(c) - 1:
        if np.isnan(a[i]) or a[i] <= 0 or np.isnan(r[i]):
            i += 1; continue
        sg = 1 if (c[i] > s200[i] and r[i] < 10) else (-1 if (c[i] < s200[i] and r[i] > 90) else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = b["o"][ei]; risk = 2 * a[i]; sl = en - sg * risk; ex = None; j = ei
        while j < min(len(c), ei + 10):
            if (b["l"][j] <= sl) if sg > 0 else (b["h"][j] >= sl):
                ex = sl; break
            if (c[j] > s5[j]) if sg > 0 else (c[j] < s5[j]):
                ex = c[j]; break
            j += 1
        if ex is None:
            j = min(len(c), ei + 10) - 1; ex = c[j]
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
        i = j + 1
    return out


def r1058(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    hour = (t // 3600) % 24
    dd = B.resample(d, 86400); a = B.atr(dd); amap = {int(x) // 86400: a[k] for k, x in enumerate(dd["t"])}
    out = []
    for s, e in B37.days(t):
        ai = np.nonzero(hour[s:e] < 7)[0] + s
        if len(ai) < 300:
            continue
        at = amap.get(int(t[s]) // 86400 - 1)
        ah, al = h[ai].max(), l[ai].min()
        if at is None or np.isnan(at) or not (ah - al < 0.5 * at) or ah - al < 1.0:
            continue
        tr = None
        for j in range(ai[-1] + 1, e - 1):
            if hour[j] >= 12:
                break
            if c[j] > ah + 0.5:
                tr = (1, j + 1); break
            if c[j] < al - 0.5:
                tr = (-1, j + 1); break
        if tr is None:
            continue
        sg, ei = tr; en = o[ei]; sl = (ah + al) / 2; risk = (en - sl) * sg
        if risk <= 0:
            continue
        tp = en + sg * 2 * risk; ex = None
        for j in range(ei, e):
            if hour[j] >= 20:
                ex = o[j]; break
            if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                ex = sl; break
            if (h[j] >= tp) if sg > 0 else (l[j] <= tp):
                ex = tp; break
        if ex is None:
            ex = c[e - 1]
        out.append((int(t[ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第十批四條規則（IDEAS #1055–#1058）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1055 H1 假突破（turtle soup；SL 極端外 0.5；TP 1R；12 根）", r1055, 200, 100),
                             ("#1056 24 小時高／低（≥ 6 個鐘冇再創）觸及 → E6S4 反向", r1056, 200, 100),
                             ("#1057 D1 RSI(2) 回歸（Connors；SMA200 方向；SL 2×ATR；過 SMA5 走、最多 10 日）", r1057, 40, 20),
                             ("#1058 窄亞洲區間倫敦突破（幅 < 0.5×ATR；SL 中位；TP 2R）", r1058, 150, 60)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1055.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
