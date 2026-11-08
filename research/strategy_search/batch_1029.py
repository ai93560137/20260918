"""[IDEAS #1029–#1032] 第四批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
#1029 D1 連 5 日同向收市 → 反向（SL 1.5×ATR、TP 1×ATR、5 日）；#1030 紐約開市區間（13:30–13:59 UTC）突破順勢（SL 另一邊、TP 2R、20:00 收）；
#1031 上星期高／低第一次觸及 → E6S4 反向；#1032 H4 RSI(14) < 30 而 D1 收市高過 SMA100 → 做多（> 70 而低過 → 做空），RSI 過 55／45 或 30 根走，SL 2×ATR(H4)。
合成 K 線、出場同 batch_1019；每張扣 0.5 美元；一次一張。
成功（每條獨立）：① Duka 張數 ≥ N1、平均 ≥ +0.10R、PF ≥ 1.15；② Duka 有交易年份 ≥ 5／8 正數；③ MT5 張數 ≥ N2、平均 ≥ +0.05R、PF ≥ 1.10。
N1／N2：#1029 60／30；#1030 200／100；#1031 150／80；#1032 100／40。
用法：python3 research/strategy_search/batch_1029.py → research/strategy_search/BATCH_1029.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import ai_entry_forward as af   # noqa: E402

A = B.A
COST = 0.5


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.maximum(d, 0); dn = np.maximum(-d, 0)
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    au, ad = up[1:n + 1].mean(), dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au = (au * (n - 1) + up[i]) / n; ad = (ad * (n - 1) + dn[i]) / n
        out[i] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def r1029(d):
    b = B.resample(d, 86400); c = b["c"]; a = B.atr(b)
    out, busy = [], -1
    for i in range(20, len(c) - 1):
        if i <= busy or np.isnan(a[i]) or a[i] <= 0:
            continue
        df = np.diff(c[i - 5:i + 1])
        sg = -1 if (df > 0).all() else (1 if (df < 0).all() else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; risk = 1.5 * a[i]
        ex = B.walk(b, ei, sg, en, en - sg * risk, en + sg * a[i], 5)
        busy = ei + 4
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1030(d):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    sod = t % 86400; day = t // 86400
    out = []
    st = np.r_[0, np.nonzero(np.diff(day))[0] + 1, len(t)]
    for s, e in zip(st[:-1], st[1:]):
        rng = np.nonzero((sod[s:e] >= 13 * 3600 + 1800) & (sod[s:e] < 14 * 3600))[0] + s
        if len(rng) < 25:
            continue
        hi, lo = h[rng].max(), l[rng].min()
        if hi - lo < 1.0:
            continue
        sg = None
        for j in range(rng[-1] + 1, e):
            if sod[j] >= 20 * 3600:
                break
            up, dn = h[j] > hi, l[j] < lo
            if up and dn:
                break
            if up or dn:
                sg = 1 if up else -1; en = max(hi, o[j]) if up else min(lo, o[j]); k0 = j; break
        if sg is None:
            continue
        sl = lo if sg > 0 else hi; risk = (en - sl) * sg; tp = en + sg * 2 * risk; ex = None
        for j in range(k0, e):
            if sod[j] >= 20 * 3600:
                ex = o[j]; break
            if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                ex = sl; break
            if j > k0 and ((h[j] >= tp) if sg > 0 else (l[j] <= tp)):
                ex = tp; break
        if ex is None:
            ex = c[e - 1]
        out.append((int(t[k0]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1031(d):
    t, h, l = d["t"], d["h"], d["l"]
    wk = (t // 86400 + 3) // 7                      # 星期一開始嘅週
    uw, inv = np.unique(wk, return_inverse=True)
    wh = np.maximum.reduceat(h, np.r_[0, np.nonzero(np.diff(wk))[0] + 1])
    wl = np.minimum.reduceat(l, np.r_[0, np.nonzero(np.diff(wk))[0] + 1])
    out, used = [], set()
    for i in range(1, len(t)):
        w = inv[i]
        if w == 0:
            continue
        ph, pl = wh[w - 1], wl[w - 1]
        for sg, lvl, ht in ((-1, ph, h[i] >= ph and h[i - 1] < ph), (1, pl, l[i] <= pl and l[i - 1] > pl)):
            key = (int(w), sg)
            if not ht or key in used:
                continue
            used.add(key)
            mid = lvl - sg * 6.0
            r = af.sim(d, int(t[i]) + 60, "BUY" if sg > 0 else "SELL", mid, mid - sg * 4.0, mid + sg * 4.0, lo=mid - 2.0, hi=mid + 2.0)
            if r is not None:
                out.append((int(t[i]), sg, r))
    return out


def r1032(d):
    b = B.resample(d, 4 * 3600); c = b["c"]; a = B.atr(b); r = rsi(c)
    dd = B.resample(d, 86400); s100 = B.sma(dd["c"], 100)
    dmap = {int(t) // 86400: k for k, t in enumerate(dd["t"])}
    out, i = [], 20
    while i < len(c) - 1:
        k = dmap.get(int(b["t"][i]) // 86400 - 1)              # 用前一日 D1 收市（已收）
        if k is None or np.isnan(s100[k]) or np.isnan(r[i]) or np.isnan(a[i]) or a[i] <= 0:
            i += 1; continue
        up = dd["c"][k] > s100[k]
        sg = 1 if (r[i] < 30 and up) else (-1 if (r[i] > 70 and not up) else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = b["o"][ei]; risk = 2 * a[i]
        ex_fn = (lambda j: r[j] > 55) if sg > 0 else (lambda j: r[j] < 45)
        ex = B.walk(b, ei, sg, en, en - sg * risk, None, 30, ex_fn)
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
        j = ei                                                  # 一次一張：等呢張出場先再搵
        while j < min(len(c) - 1, ei + 29) and not ((r[j] > 55) if sg > 0 else (r[j] < 45)):
            j += 1
        i = j + 1
    return out


RULES = [("#1029 D1 連 5 日同向收市反向（SL 1.5×ATR、TP 1×ATR、5 日）", r1029, 60, 30),
         ("#1030 紐約開市區間 13:30–13:59 UTC 突破順勢（SL 另一邊、TP 2R、20:00 收）", r1030, 200, 100),
         ("#1031 上星期高／低第一次觸及 → E6S4 反向", r1031, 150, 80),
         ("#1032 H4 RSI14 回調順 D1 SMA100（SL 2×ATR、RSI 過 55／45 或 30 根）", r1032, 100, 40)]


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第四批四條規則（IDEAS #1029–#1032）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
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
    open(os.path.join(HERE, "BATCH_1029.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
