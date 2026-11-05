"""[IDEAS #228] 921「AI 揀位、規則執行」（B 方案）重播。
樣本同 #212（xau/decisions OPEN，用放闊前 AI 原值；經紀 M1＋Dukascopy 補缺）。
B0 現行（市價、AI stop／target）；B1 市價、SL＝AI stop 外 1 美元、TP 2R；
B2（主判）限價回調 0.3×d0、30 分鐘 TTL、SL＝AI stop 外 1 美元、TP 2R；B3 同 B2 回調 0.5×d0。
保守：限價成交嗰根只查 SL；同一根 SL／TP 都掂當 SL；24 小時到鐘走；每張扣 0.5 美元。
判（預先登記）：見 IDEAS #228。用法：python3 research/strategy_search/ai_zone_921.py → AI_ZONE_921.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_921 as F  # noqa: E402

BUF = 1.0
TTL = 1800
FWD_TS = int(dt.datetime(2026, 11, 5, 14, 0, tzinfo=dt.timezone.utc).timestamp())
VARIANTS = {"B0": None, "B1": 0.0, "B2": 0.3, "B3": 0.5}   # None＝現行；數字＝限價回調比例（0＝市價）


def _exit(t, o, h, l, a, s, fill, sl, tp, skip_tp_first):
    for j in range(a, len(t)):
        if t[j] - t[a] >= 86400:
            return o[j]
        if (l[j] <= sl) if s > 0 else (h[j] >= sl):
            return sl
        if j == a and skip_tp_first:
            continue
        if (h[j] >= tp) if s > 0 else (l[j] <= tp):
            return tp
    return None


def replay(m1, decs, var):
    t, o, h, l = m1["t"], m1["o"], m1["h"], m1["l"]
    out, n_try = [], 0
    for ts, s, sl0, tp0, _ in decs:
        a = int(np.searchsorted(t, ts, side="right"))
        if a >= len(t) or t[a] - ts > 600:
            continue
        px = o[a]; d0 = (px - sl0) * s
        if d0 <= 0 or (tp0 - px) * s <= 0:
            continue
        n_try += 1
        pb = VARIANTS[var]
        if pb is None:
            fill, sl, tp, b, first = px, sl0, tp0, a, False
        else:
            sl = sl0 - s * BUF
            if pb == 0:
                fill, b, first = px, a, False
            else:
                lim = px - s * pb * d0; b = None
                for j in range(a, len(t)):
                    if t[j] - t[a] >= TTL:
                        break
                    if (l[j] <= lim) if s > 0 else (h[j] >= lim):
                        b = j; break
                if b is None:
                    continue
                fill, first = (min(lim, o[b]) if s > 0 else max(lim, o[b])), True
            tp = fill + s * 2 * (fill - sl) * s
        risk = (fill - sl) * s
        ex = _exit(t, o, h, l, b, s, fill, sl, tp, first)
        if ex is None or risk <= 0:
            continue
        out.append((int(t[b]), s, float((s * (ex - fill) - F.COST) / risk)))
    return out, n_try


def main():
    g = F.gb.Gcs()
    decs = F.load_decisions(g)
    m1 = F.EF6.broker_bars(int(decs[0][0]) - 86400)
    m1, nd = F.merge_duka(g, m1, dt.datetime.fromtimestamp(decs[0][0] - 86400, dt.timezone.utc).date().isoformat())
    mid = decs[len(decs) // 2][0]
    out = ["# 921「AI 揀位、規則執行」重播（IDEAS #228）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；決策 OPEN {len(decs)} 個（經紀 M1，缺嘅 {nd} 分鐘用 Dukascopy 補）；"
           f"前半／後半以 {dt.datetime.fromtimestamp(mid, dt.timezone.utc):%m-%d %H:%M} UTC 分", "",
           "| 組 | 成交率 | 全部 | 前半 | 後半 | 做多 | 做空 |", "|---|---|---|---|---|---|---|"]
    res = {}
    for v in VARIANTS:
        tr, n = replay(m1, decs, v)
        r = [x[2] for x in tr]
        s = F.summ(r); h1 = F.summ([x[2] for x in tr if x[0] < mid]); h2 = F.summ([x[2] for x in tr if x[0] >= mid])
        fr = len(tr) / n if n else 0
        res[v] = (s, h1, h2, fr, F.summ([x[2] for x in tr if x[0] >= FWD_TS]))
        out.append(f"| {v} | {fr:.0%}（{len(tr)}／{n}） | {F.fmt(s)} | {F.fmt(h1)} | {F.fmt(h2)} | "
                   f"{F.fmt(F.summ([x[2] for x in tr if x[1] > 0]))} | {F.fmt(F.summ([x[2] for x in tr if x[1] < 0]))} |")
        print(v, F.fmt(s), flush=True)
    b, w = res["B0"], res["B2"]
    ok = {"①平均R +0.10": w[0]["avg"] - b[0]["avg"] >= 0.10, "②PF≥1.2": w[0]["pf"] >= 1.2,
          "③前後半都高過B0": w[1]["avg"] > b[1]["avg"] and w[2]["avg"] > b[2]["avg"],
          "④成交率≥50%": w[3] >= 0.5, "⑤ΣR高過B0": w[0]["sum"] > b[0]["sum"]}
    out += ["", "## 前向（11-05 14:00 UTC 之後新決定，只作描述）", "",
            *[f"- {v}：{F.fmt(res[v][4])}" for v in VARIANTS],
            "", "## 判（預先登記 IDEAS #228；主判 B2 對 B0）", "",
            *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            f"- B2 對 B0 平均 R {w[0]['avg'] - b[0]['avg']:+.3f} → "
            + ("✅ 達標 → 提案：zhuge-xau 加影子「區＋失效位」輸出同規則執行書（唔落單），前向 60 張再判" if all(ok.values())
               else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；照登記唔做、唔准改參數再試同一批決定"),
            "- AI stop 係為市價單揀嘅，只係失效位近似；樣本只得兩星期左右、同一段市況；B1／B3 只作描述。", ""]
    open(os.path.join(HERE, "AI_ZONE_921.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
