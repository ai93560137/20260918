"""[IDEAS #1075–#1078] 喺 2015–2026 明顯蝕錢嘅規則，反方向版本**只用 Dukascopy 2010–2014（未見數據）判**。
2015–2026 嘅反向結果係已知（睇過原版先諗出嚟），只作描述，唔計入判決。規格、成功標準以 IDEAS 預先登記為準（數據到之前 commit）。
#1075 H1 連 3 根更高高位＋收市 → 順勢做多（#1068 反向；SL＝TP＝入場到「第 3 根極端外 0.5」嘅距離；6 根）；
#1076 M15 大燭 → 反向（#1035 反向；SL 大燭極端外 0.3；TP 1R；8 根）；
#1077 H1 假突破 → 順返原突破方向（#1055 反向；SL＝TP＝入場到「訊號根極端外 0.5」嘅距離；12 根）；
#1078 倫敦下午定盤前走勢 → 定盤時順勢（#1063 反向；SL＝TP＝0.5×走幅；3 個鐘）；
#1082 亞洲趨勢 → 倫敦開市順勢（#1052 反向；SL＝TP＝0.5×走幅；12:00 收；11-08 18:3x 加入，數據仍未到）。
成功（每條獨立，只計 2010–2014）：張數 ≥ 100、平均 R ≥ +0.10、PF ≥ 1.15、5 年 ≥ 3 年正數。
用法：python3 research/strategy_search/oos_rev_1075.py → research/strategy_search/OOS_REV_1075.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1037 as B37        # noqa: E402
import batch_1051 as B51        # noqa: E402
import batch_1063 as B63        # noqa: E402

A = B.A
COST = 0.5


def r1075(d):
    b = B.resample(d, 3600); o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    out, busy = [], -1
    for i in range(4, len(c) - 1):
        if i <= busy:
            continue
        up = all(h[i - k] > h[i - k - 1] and c[i - k] > c[i - k - 1] for k in range(3))
        dn = all(l[i - k] < l[i - k - 1] and c[i - k] < c[i - k - 1] for k in range(3))
        sg = 1 if up else (-1 if dn else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; ext = (h[i] + 0.5) if sg > 0 else (l[i] - 0.5); risk = (ext - en) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, en - sg * risk, en + sg * risk, 6)
        busy = ei + 5
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1076(d):
    b = B.resample(d, 900); o, h, l, c = b["o"], b["h"], b["l"], b["c"]; a = B.atr(b)
    out, busy = [], -1
    for i in range(15, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        rg = h[i] - l[i]; body = c[i] - o[i]
        if rg < 2.5 * a[i] or abs(body) < 0.7 * rg:
            continue
        sg = -1 if body > 0 else 1
        ei = i + 1; en = o[ei]; sl = (h[i] + 0.3) if sg < 0 else (l[i] - 0.3); risk = (en - sl) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, sl, en + sg * risk, 8)
        busy = ei + 7
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1077(d):
    b = B.resample(d, 3600); o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    out, busy = [], -1
    for i in range(25, len(c) - 1):
        if i <= busy:
            continue
        ph, pl = h[i - 24:i].max(), l[i - 24:i].min()
        sg = 1 if (h[i] > ph and c[i] < ph) else (-1 if (l[i] < pl and c[i] > pl) else 0)
        if not sg:
            continue
        ei = i + 1; en = o[ei]; ext = (h[i] + 0.5) if sg > 0 else (l[i] - 0.5); risk = (ext - en) * sg
        if risk <= 0.5:
            continue
        ex = B.walk(b, ei, sg, en, en - sg * risk, en + sg * risk, 12)
        busy = ei + 11
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1078(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        day = dt.datetime.fromtimestamp(int(t[s]), dt.timezone.utc).date()
        fx = (14 if B63.uk_dst(day) else 15) * 3600
        g = B51.idx_at(sod, s, e, fx); a = B51.idx_at(sod, s, e, fx - 3600)
        if g is None or a is None:
            continue
        mv = c[g - 1] - o[a]
        if abs(mv) < 4:
            continue
        sg = 1 if mv > 0 else -1; en = o[g]; dist = 0.5 * abs(mv)
        ex = B51.run_exit(d, g, e, sg, en, en - sg * dist, en + sg * dist, fx + 3 * 3600)
        out.append((int(t[g]), sg, (sg * (ex - en) - COST) / dist))
    return out


def r1082(d):
    t, o, c = d["t"], d["o"], d["c"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        if sod[s] >= 300:
            continue
        g = B51.idx_at(sod, s, e, 7 * 3600)
        if g is None:
            continue
        mv = c[g - 1] - o[s]
        if abs(mv) < 8:
            continue
        sg = 1 if mv > 0 else -1; en = o[g]; dist = 0.5 * abs(mv)
        ex = B51.run_exit(d, g, e, sg, en, en - sg * dist, en + sg * dist, 12 * 3600)
        out.append((int(t[g]), sg, (sg * (ex - en) - COST) / dist))
    return out


RULES = [("#1075 H1 連 3 根更高高位 → 順勢（#1068 反向）", r1075), ("#1076 M15 大燭 → 反向（#1035 反向）", r1076),
         ("#1077 H1 假突破 → 順原方向（#1055 反向）", r1077), ("#1078 倫敦定盤前走勢 → 順勢（#1063 反向）", r1078),
         ("#1082 亞洲趨勢 → 倫敦開市順勢（#1052 反向）", r1082)]


def main():
    oos = A.load("duka", "2010-01-01", "2014-12-31")
    seen = [("Dukascopy 2015–2022（已知，只描述）", A.load("duka", "2015-01-01", "2022-12-31")), ("MT5 2023–2026（已知，只描述）", A.load("mt5", "2023-01-01", "2026-10-30"))]
    out = ["# 蝕錢規則反向版：只用 2010–2014 未見數據判（IDEAS #1075–#1078）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元", ""]
    for name, fn in RULES:
        tr = fn(oos); st = A.stats([x[2] for x in tr]); yd = A.by_year(tr)
        pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
        ok = st["n"] >= 100 and st["avg"] >= 0.10 and st["pf"] >= 1.15 and pos >= 3
        out += [f"## {name}", "", f"- **2010–2014（判）**：{A.fmt(st)}；每年 " + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in yd.items() if v["n"]),
                *[f"- {nm}：{A.fmt(A.stats([x[2] for x in fn(d)]))}" for nm, d in seen],
                f"- **判：{'✅ 達標 → 只提案影子前向（唔落單）' if ok else '❌ 唔達'}**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "OOS_REV_1075.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
