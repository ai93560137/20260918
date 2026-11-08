"""[IDEAS #1019–#1022] 第二批四條固定規則（冇網格），規格同成功標準以 IDEAS 預先登記為準（跑之前 commit）。
全部由 M1 合成 M15／H1／D1（UTC 對齊），喺合成 K 線上計出場：同一根掂 SL 同 TP 當 SL；成本每張 0.5 美元。
#1019 H1 RSI(2) 回歸（順 H1 SMA200）；#1020 M15 保力加 2.5σ 收市出界反向；#1021 H1 內包線突破（順勢 2R）；#1022 D1 20 日收市新高／新低突破（順勢 2R）。
成功（每條獨立）：① Duka 張數 ≥ N1、平均 ≥ +0.10R、PF ≥ 1.15；② Duka 有交易年份 ≥ 5／8 正數；③ MT5 張數 ≥ N2、平均 ≥ +0.05R、PF ≥ 1.10。
N1／N2：#1019–#1021 係 200／100；#1022 係 60／30（日線張數少）。
用法：python3 research/strategy_search/batch_1019.py → research/strategy_search/BATCH_1019.md
前向（#1022）：python3 research/strategy_search/batch_1019.py --forward [2026-11-09] → D1BREAK_FORWARD.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402

COST = 0.5


def resample(d, sec):
    k = d["t"] // sec
    st = np.r_[0, np.nonzero(np.diff(k))[0] + 1]
    en = np.r_[st[1:], len(k)]
    return {"t": k[st] * sec, "o": d["o"][st], "h": np.maximum.reduceat(d["h"], st),
            "l": np.minimum.reduceat(d["l"], st), "c": d["c"][en - 1]}


def atr(b, n=14):
    pc = np.r_[b["c"][0], b["c"][:-1]]
    tr = np.maximum(b["h"] - b["l"], np.maximum(abs(b["h"] - pc), abs(b["l"] - pc)))
    out = np.full(len(tr), np.nan)
    for i in range(n, len(tr)):
        out[i] = tr[i - n + 1:i + 1].mean()
    return out


def sma(x, n):
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.r_[0, x])
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def rsi2(c):
    d = np.diff(c, prepend=c[0]); up = np.maximum(d, 0); dn = np.maximum(-d, 0)
    out = np.full(len(c), np.nan); au = ad = None
    for i in range(1, len(c)):
        if i < 2:
            continue
        if au is None:
            au, ad = up[1:3].mean(), dn[1:3].mean()
        else:
            au = (au + up[i]) / 2; ad = (ad + dn[i]) / 2
        out[i] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def walk(b, ei, sg, en, sl, tp, max_bars, exit_fn=None):
    """由第 ei 根（入場根，開市價入）行；回傳 (出場價)。"""
    for j in range(ei, min(len(b["t"]), ei + max_bars)):
        if (b["l"][j] <= sl) if sg > 0 else (b["h"][j] >= sl):
            return sl
        if tp is not None and ((b["h"][j] >= tp) if sg > 0 else (b["l"][j] <= tp)):
            return tp
        if exit_fn is not None and exit_fn(j):
            return b["c"][j]
    return b["c"][min(len(b["t"]), ei + max_bars) - 1]


def r1019(d):
    b = resample(d, 3600); c = b["c"]
    r, s200, a = rsi2(c), sma(c, 200), atr(b)
    out, busy = [], -1
    for i in range(201, len(c) - 1):
        if i <= busy or np.isnan(a[i]):
            continue
        sg = 1 if (r[i] < 5 and c[i] > s200[i]) else (-1 if (r[i] > 95 and c[i] < s200[i]) else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; risk = 2.5 * a[i]; sl = en - sg * risk
        ex_fn = (lambda j: r[j] > 70) if sg > 0 else (lambda j: r[j] < 30)
        ex = walk(b, ei, sg, en, sl, None, 10, ex_fn)
        busy = ei + 9
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


def r1020(d):
    b = resample(d, 900); c = b["c"]
    m = sma(c, 20)
    sd = np.full(len(c), np.nan)
    for i in range(19, len(c)):
        sd[i] = c[i - 19:i + 1].std()
    out, busy = [], -1
    for i in range(20, len(c) - 1):
        if i <= busy or np.isnan(sd[i]):
            continue
        sg = -1 if c[i] > m[i] + 2.5 * sd[i] else (1 if c[i] < m[i] - 2.5 * sd[i] else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; dist = (m[i] - en) * sg
        if dist < 2.0:
            continue
        tp, sl = m[i], en - sg * dist
        ex = walk(b, ei, sg, en, sl, tp, 16)
        busy = ei + 15
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / dist))
    return out


def r1021(d):
    b = resample(d, 3600); h, l = b["h"], b["l"]
    out, busy = [], -1
    for i in range(1, len(h) - 4):
        if i <= busy or not (h[i] < h[i - 1] and l[i] > l[i - 1]):
            continue
        hi, lo = h[i] + 0.2, l[i] - 0.2
        if hi - lo < 1.0:
            continue
        for j in range(i + 1, i + 4):
            up, dn = h[j] >= hi, l[j] <= lo
            if up or dn:
                if up and dn:
                    break                                   # 同一根兩邊都穿：唔知先後，唔做
                sg = 1 if up else -1
                en = hi if up else lo
                en = max(en, b["o"][j]) if sg > 0 else min(en, b["o"][j])
                sl = lo if sg > 0 else hi; risk = (en - sl) * sg
                tp = en + sg * 2 * risk
                ex = None
                if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
                    ex = sl
                else:
                    ex = walk(b, j + 1, sg, en, sl, tp, 24)
                busy = j + 24
                out.append((int(b["t"][j]), sg, (sg * (ex - en) - COST) / risk))
                break
    return out


def r1022(d):
    b = resample(d, 86400); c = b["c"]; a = atr(b)
    out, busy = [], -1
    for i in range(21, len(c) - 1):
        if i <= busy or np.isnan(a[i]):
            continue
        sg = 1 if c[i] > c[i - 20:i].max() else (-1 if c[i] < c[i - 20:i].min() else 0)
        if not sg:
            continue
        ei = i + 1; en = b["o"][ei]; risk = a[i]; sl = en - sg * risk; tp = en + sg * 2 * risk
        ex = walk(b, ei, sg, en, sl, tp, 5)
        busy = ei + 4
        out.append((int(b["t"][ei]), sg, (sg * (ex - en) - COST) / risk))
    return out


RULES = [("#1019 H1 RSI(2) 回歸（順 SMA200；SL 2.5×ATR；RSI 過 70／30 或 10 根收市走）", r1019, 200, 100),
         ("#1020 M15 保力加 2.5σ 收市出界反向（TP 中線、SL 1:1、4 小時）", r1020, 200, 100),
         ("#1021 H1 內包線突破順勢（SL 內包線另一邊、TP 2R、24 小時）", r1021, 200, 100),
         ("#1022 D1 20 日收市新高／新低突破順勢（SL 1×ATR、TP 2R、5 日）", r1022, 60, 30)]


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第二批四條規則（IDEAS #1019–#1022）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張扣 0.5 美元；各條規格見 IDEAS", ""]
    for name, fn, n1, n2 in RULES:
        td, tm = fn(duka), fn(mt5)
        sd, sm = A.stats([x[2] for x in td]), A.stats([x[2] for x in tm])
        yd = A.by_year(td)
        yrs = [v for v in yd.values() if v["n"]]
        pos = sum(1 for v in yrs if v["avg"] > 0)
        ok = {f"①Duka n≥{n1}、平均≥+0.10R、PF≥1.15": sd["n"] >= n1 and sd["avg"] >= 0.10 and sd["pf"] >= 1.15,
              "②Duka 有交易年份 ≥5／8 正數": pos >= 5,
              f"③MT5 n≥{n2}、平均≥+0.05R、PF≥1.10": sm["n"] >= n2 and sm["avg"] >= 0.05 and sm["pf"] >= 1.10}
        out += [f"## {name}", "", f"- Dukascopy 2015–2022：{A.fmt(sd)}", f"- MT5 2023-01→2026-10：{A.fmt(sm)}",
                "- 每年：" + "；".join(f"{y} {v['avg']:+.3f}R（{v['n']}）" for y, v in {**yd, **A.by_year(tm)}.items() if v["n"]),
                *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1019.md"), "w", encoding="utf-8").write(md)


FWD_START = "2026-11-09"


def forward_1022(start=FWD_START):
    """[IDEAS #1022 前向影子] 日線由 MT5 M1 存檔（2026-09-01→10-30）接券商 M1（xau/sig/bars/）合成；入場日 ≥ start 先計。唔落單、唔寫 GCS。"""
    import e6s4_forward as ef
    import fit_rules as fr
    hist = A.load("mt5", "2026-09-01", "2026-10-30")
    br = ef.broker_bars(fr.ts_of("2026-10-31"))
    m = br["t"] > hist["t"][-1]
    d = {k: np.r_[hist[k], br[k][m]] for k in ("t", "o", "h", "l", "c")}
    t0 = fr.ts_of(start)
    tr = [x for x in r1022(d) if x[0] >= t0]
    st = A.stats([x[2] for x in tr])
    ok = {"①≥30張": st["n"] >= 30, "②平均≥+0.10R且PF≥1.2": st["n"] > 0 and st["avg"] >= 0.10 and st["pf"] >= 1.2,
          "③連敗≤8": st["n"] == 0 or st["streak"] <= 8}
    out = ["# IDEAS #1022 D1 20 日突破 影子前向（MT5 存檔＋券商 M1）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；入場由 {start} 起", "",
           f"- 成績：{A.fmt(st)}", "", "## 判（預先登記 IDEAS #1022 前向）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
           "- " + ("達標 → 只出報告同提案（上實倉要 PR＋總指揮 dry-run＋使用者批）" if all(ok.values()) else ("未夠張數" if not ok["①≥30張"] else "唔達標")), "",
           "| 入場日 | 方向 | R（未完＝最新收市計） |", "|---|---|---|"]
    out += [f"| {dt.datetime.fromtimestamp(ts, dt.timezone.utc):%Y-%m-%d} | {'BUY' if sg > 0 else 'SELL'} | {r:+.2f} |" for ts, sg, r in tr[-20:][::-1]]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "D1BREAK_FORWARD.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    if "--forward" in sys.argv:
        k = sys.argv.index("--forward")
        forward_1022(sys.argv[k + 1] if len(sys.argv) > k + 1 else FWD_START)
    else:
        main()
