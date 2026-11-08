"""[IDEAS #1023–#1026] 第三批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1023 D1 趨勢內回調（收市高過 SMA50 而且連跌 3 日 → 做多；反之做空）；#1024 D1 NR7 突破（M1 判先後）；
#1025 H4 EMA20／EMA50 交叉順勢；#1026 月尾做多（每月最後一個交易日收市買、持 3 個交易日）。
合成 K 線同出場規則同 batch_1019（同一根掂 SL 同 TP 當 SL）；每張扣 0.5 美元；一次一張。
成功（每條獨立）：① Duka 張數 ≥ N1、平均 ≥ +0.10R、PF ≥ 1.15；② Duka 有交易年份 ≥ 5／8 正數；③ MT5 張數 ≥ N2、平均 ≥ +0.05R、PF ≥ 1.10。
N1／N2：#1023 60／30；#1024 150／60；#1025 100／40；#1026 60／30。
用法：python3 research/strategy_search/batch_1023.py → research/strategy_search/BATCH_1023.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402

A = B.A
COST = 0.5


def ema(x, n):
    out = np.empty(len(x)); k = 2 / (n + 1); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + k * (x[i] - out[i - 1])
    return out


def r1023(d):
    b = B.resample(d, 86400); c = b["c"]; a = B.atr(b); s50 = B.sma(c, 50)
    out, busy = [], -1
    for i in range(53, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or np.isnan(s50[i]):
            continue
        dn3 = c[i] < c[i - 1] < c[i - 2] < c[i - 3]
        up3 = c[i] > c[i - 1] > c[i - 2] > c[i - 3]
        sg = 1 if (dn3 and c[i] > s50[i]) else (-1 if (up3 and c[i] < s50[i]) else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; risk = 1.5 * a[i]
        if risk <= 0:
            continue
        sl = en - sg * risk; tp = en + sg * 1.5 * a[i]
        ex = B.walk(b, ei, sg, en, sl, tp, 5)
        busy = ei + 4
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1024(d):
    b = B.resample(d, 86400); h, l = b["h"], b["l"]; rng = h - l
    t = d["t"]; out = []
    for i in range(7, len(h) - 1):
        if rng[i] <= 0 or rng[i] > rng[i - 6:i].min():
            continue
        hi, lo = h[i] + 0.2, l[i] - 0.2; risk = hi - lo
        s = int(np.searchsorted(t, b["t"][i + 1])); e = int(np.searchsorted(t, b["t"][i + 1] + 86400))
        sg = en = None
        for j in range(s, e):
            up, dn = d["h"][j] >= hi, d["l"][j] <= lo
            if up and dn:
                break
            if up or dn:
                sg = 1 if up else -1
                en = max(hi, d["o"][j]) if up else min(lo, d["o"][j])
                k0 = j; break
        if sg is None:
            continue
        sl = lo if sg > 0 else hi; risk = (en - sl) * sg; tp = en + sg * 2 * risk; ex = None
        for j in range(k0, e):
            if (d["l"][j] <= sl) if sg > 0 else (d["h"][j] >= sl):
                ex = sl; break
            if j > k0 and ((d["h"][j] >= tp) if sg > 0 else (d["l"][j] <= tp)):
                ex = tp; break
        if ex is None:
            ex = d["c"][e - 1]
        out.append((int(t[k0]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1025(d):
    b = B.resample(d, 4 * 3600); c = b["c"]; a = B.atr(b)
    f, s = ema(c, 20), ema(c, 50)
    out, i = [], 51
    while i < len(c) - 1:
        cu = f[i] > s[i] and f[i - 1] <= s[i - 1]
        cd = f[i] < s[i] and f[i - 1] >= s[i - 1]
        if not (cu or cd) or np.isnan(a[i]):
            i += 1; continue
        sg = 1 if cu else -1
        ei = i + 1; en = b["o"][ei]; risk = 2 * a[i]
        if risk <= 0:
            i += 1; continue
        sl = en - sg * risk; tp = en + sg * 2 * risk          # TP 2R（4×ATR）
        ex, j = None, ei
        while j < min(len(c), ei + 60):                         # 最多 60 根 H4（約 10 日）
            if (b["l"][j] <= sl) if sg > 0 else (b["h"][j] >= sl):
                ex = sl; break
            if (b["h"][j] >= tp) if sg > 0 else (b["l"][j] <= tp):
                ex = tp; break
            if (f[j] < s[j]) if sg > 0 else (f[j] > s[j]):    # 反向交叉收市走
                ex = c[j]; break
            j += 1
        if ex is None:
            j = min(len(c), ei + 60) - 1; ex = c[j]
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
        i = j + 1
    return out


def r1026(d):
    b = B.resample(d, 86400); c = b["c"]; a = B.atr(b)
    mon = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month for x in b["t"]])
    out = []
    for i in range(15, len(c) - 4):
        if mon[i] == mon[i + 1] or np.isnan(a[i]):
            continue
        en = c[i]; risk = 1.5 * a[i]; sl = en - risk; ex = None
        for j in range(i + 1, i + 4):
            if b["l"][j] <= sl:
                ex = sl; break
        if ex is None:
            ex = c[i + 3]
        out.append((int(b["t"][i]), 1, (ex - en - COST) / risk))
    return out


RULES = [("#1023 D1 趨勢內回調（SMA50 方向、連 3 日反向收市；SL 1.5×ATR、TP 1.5×ATR、5 日）", r1023, 60, 30),
         ("#1024 D1 NR7 突破（翌日穿高／低 0.2；SL 另一邊；TP 2R；當日收市走）", r1024, 150, 60),
         ("#1025 H4 EMA20／50 交叉順勢（SL 2×ATR；TP 2R；反向交叉或 60 根走）", r1025, 100, 40),
         ("#1026 月尾做多（月尾收市買、3 個交易日收市走；SL 1.5×ATR）", r1026, 60, 30)]


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第三批四條規則（IDEAS #1023–#1026）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in RULES:
        td, tm = fn(duka), fn(mt5)
        sd, sm = A.stats([x[2] for x in td]), A.stats([x[2] for x in tm])
        yd = A.by_year(td)
        pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
        ok = {f"①Duka n≥{n1}、平均≥+0.10R、PF≥1.15": sd["n"] >= n1 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
              "②Duka 有交易年份 ≥5／8 正數": pos >= 5,
              f"③MT5 n≥{n2}、平均≥+0.05R、PF≥1.10": sm["n"] >= n2 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
        out += [f"## {name}", "", f"- Dukascopy 2015–2022：{A.fmt(sd)}", f"- MT5 2023-01→2026-10：{A.fmt(sm)}",
                f"- 做多／做空（Duka）：{A.fmt(A.stats([x[2] for x in td if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in td if x[1] < 0]))}",
                f"- 做多／做空（MT5）：{A.fmt(A.stats([x[2] for x in tm if x[1] > 0]))}／{A.fmt(A.stats([x[2] for x in tm if x[1] < 0]))}",
                "- 每年：" + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in {**yd, **A.by_year(tm)}.items() if v["n"]),
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1023.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
