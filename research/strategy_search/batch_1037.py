"""[IDEAS #1037–#1040] 第六批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1037 波幅突破（Larry Williams）：當日 UTC 開市價 ± 0.5×前日高低幅，先穿邊邊就跟，SL＝開市價，當日收市走；
#1038 亞洲高／低（00–06:59 UTC）喺 07:00–19:59 第一次觸及 → E6S4 反向；
#1039 當日開市價（00:00 UTC）：價離開 ≥ 10 美元後第一次返到開市價 → E6S4 反向（即係由嗰邊返嚟就喺開市價再推 6 美元做返原方向）；
#1040 H1 連 3 根反向收市（順 H4 EMA50）：H4 收市高過 EMA50 而 H1 連 3 根收市下跌 → 做多（反之做空），SL 1.5×ATR(H1)、TP 1.5×ATR、12 根。
成本每張 0.5 美元；一次一張。
用法：python3 research/strategy_search/batch_1037.py → research/strategy_search/BATCH_1037.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import batch_1023 as B23        # noqa: E402
import batch_1033 as B33        # noqa: E402
import ai_entry_forward as af   # noqa: E402

A = B.A
COST = 0.5


def days(t):
    day = t // 86400
    st = np.r_[0, np.nonzero(np.diff(day))[0] + 1, len(t)]
    return list(zip(st[:-1], st[1:]))


def r1037(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    out, prev = [], None
    for s, e in days(t):
        if prev is not None and e - s >= 300:
            op = o[s]; k = 0.5 * prev
            hi, lo = op + k, op - k
            sg = None
            for j in range(s, e):
                up, dn = h[j] >= hi, l[j] <= lo
                if up and dn:
                    break
                if up or dn:
                    sg = 1 if up else -1; en = max(hi, o[j]) if up else min(lo, o[j]); k0 = j; break
            if sg is not None and k > 0.5:
                sl = op; risk = (en - sl) * sg; ex = None
                for j in range(k0, e):
                    if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                        ex = sl; break
                if ex is None:
                    ex = c[e - 1]
                out.append((int(t[k0]), sg, (sg * (ex - en) - COST) / risk))
        prev = h[s:e].max() - l[s:e].min()
    return out




def r1038(d):
    t, h, l = d["t"], d["h"], d["l"]
    hour = (t // 3600) % 24; out = []
    for s, e in days(t):
        ai = np.nonzero(hour[s:e] < 7)[0] + s
        if len(ai) < 300:
            continue
        ah, al = h[ai].max(), l[ai].min(); done = set()
        for i in range(ai[-1] + 1, e):
            if hour[i] >= 20:
                break
            for sg, lvl, ht in ((-1, ah, h[i] >= ah), (1, al, l[i] <= al)):
                if not ht or sg in done:
                    continue
                done.add(sg); mid = lvl - sg * 6.0
                r = af.sim(d, int(t[i]) + 60, "BUY" if sg > 0 else "SELL", mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
                if r is not None:
                    out.append((int(t[i]), sg, r))
    return out


def r1039(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    out = []
    for s, e in days(t):
        if t[s] % 86400 >= 300:
            continue
        op = o[s]; away = 0
        for i in range(s + 1, e):
            if away == 0:
                if c[i] >= op + 10:
                    away = 1
                elif c[i] <= op - 10:
                    away = -1
                continue
            if (l[i] <= op) if away > 0 else (h[i] >= op):
                sg = away                                        # 由上面返落嚟 → 開市價下面 6 美元做多（返原方向）
                mid = op - sg * 6.0
                r = af.sim(d, int(t[i]) + 60, "BUY" if sg > 0 else "SELL", mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
                if r is not None:
                    out.append((int(t[i]), sg, r))
                break
    return out


def r1040(d):
    b = B.resample(d, 3600); c = b["c"]; a = B.atr(b)
    b4 = B.resample(d, 4 * 3600); e50 = B23.ema(b4["c"], 50)
    t4 = b4["t"]
    out, busy = [], -1
    for i in range(20, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        k = int(np.searchsorted(t4, b["t"][i] + 3600, side="right")) - 2   # 最近一根已收嘅 H4
        if k < 50:
            continue
        up = b4["c"][k] > e50[k]
        df = np.diff(c[i - 3:i + 1])
        sg = 1 if (up and (df < 0).all()) else (-1 if (not up and (df > 0).all()) else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; risk = 1.5 * a[i]
        ex = B.walk(b, ei, sg, en, en - sg * risk, en + sg * risk, 12)
        busy = ei + 11
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第六批四條規則（IDEAS #1037–#1040）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in (("#1037 波幅突破（開市 ± 0.5×前日幅；SL 開市價；收市走）", r1037, 300, 150),
                             ("#1038 亞洲高／低第一次觸及 → E6S4 反向", r1038, 200, 100),
                             ("#1039 當日開市價回測 → E6S4 返原方向", r1039, 200, 100),
                             ("#1040 H1 連 3 根回調順 H4 EMA50（SL＝TP＝1.5×ATR；12 根）", r1040, 200, 100)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, n1, n2)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1037.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
