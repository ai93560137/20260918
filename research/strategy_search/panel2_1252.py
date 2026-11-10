"""[IDEAS #1252–#1259] 方法 D 第二階段：8 條全新假設，**先喺 14 個非金屬品種揀**（t ≥ 3.0），過咗先用黃金三段＋白銀**一次過確認**。
規格以 IDEAS 預先登記為準（跑之前 commit；冇網格、冇調參）。全部用 ATR 單位；D1 收市判、下一日開市入、M1 逐根判止蝕。
#1251 顯示趨勢突破喺新品種冇優勢，所以今批主要係「順大趨勢買回調／極端反向」同日曆效應——同之前喺黃金試過嘅寫法唔同、亦唔係睇完 #1251 結果先揀參數（參數全部係教科書預設）。
用法：python3 research/strategy_search/panel2_1252.py → research/strategy_search/PANEL2_1252.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import fade_strict_1129 as F    # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import gate_c_1240 as GC        # noqa: E402
import h1_lab as HL             # noqa: E402
import indep_1235 as I1         # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import panel_1251 as P1         # noqa: E402
import pullback_1192 as P2      # noqa: E402

OUT = os.path.join(HERE, "PANEL2_1252.md")
T_MIN = 3.0


def rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(c), np.nan); ad = np.full(len(c), np.nan)
    if len(c) <= n:
        return au
    au[n] = up[1:n + 1].mean(); ad[n] = dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n; ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    return 100 - 100 / (1 + au / np.where(ad == 0, 1e-12, ad))


def ctx(d):
    cx = M3.d1ctx(d); b = cx.b
    return cx, b, b["h"], b["l"], b["c"], B.atr(b)


def r1252(d):
    """RSI(2) 回調：收市 > SMA200 而 RSI2 < 10 → 買；收市 < SMA200 而 RSI2 > 90 → 沽。收市過返 SMA5 平；SL 2.5 ATR；最多 10 日。"""
    cx, b, h, l, c, a = ctx(d); m200, m5, r2 = F2.sma(c, 200), F2.sma(c, 5), rsi(c, 2)
    cond = np.where((c > m200) & (r2 < 10), 1, np.where((c < m200) & (r2 > 90), -1, 0)); cond[np.isnan(m200) | np.isnan(r2)] = 0
    return GC.edge_sigs(cx, cond, 2.5, 10, lambda k, sg: (c[k] > m5[k]) if sg > 0 else (c[k] < m5[k]))


def r1253(d):
    """連跌三日買回調：收市 > SMA100 而連續 3 日收市下跌 → 買（反之沽）；持 3 日；SL 2 ATR。"""
    cx, b, h, l, c, a = ctx(d); m = F2.sma(c, 100); n = len(c); cond = np.zeros(n)
    for i in range(100, n):
        if c[i] > m[i] and c[i] < c[i - 1] < c[i - 2] < c[i - 3]:
            cond[i] = 1
        elif c[i] < m[i] and c[i] > c[i - 1] > c[i - 2] > c[i - 3]:
            cond[i] = -1
    return GC.edge_sigs(cx, cond, 2.0, 3)


def r1254(d):
    """冇趨勢時布林帶反向：ADX14 < 20，收市 < 下軌（20，2σ）→ 買；> 上軌 → 沽。收市返到中軌平；SL 2 ATR；最多 10 日。"""
    cx, b, h, l, c, a = ctx(d); n = len(c); mid = F2.sma(c, 20); sd = np.full(n, np.nan); adx = P2.adx(b)[0]
    for i in range(19, n):
        sd[i] = c[i - 19:i + 1].std()
    cond = np.where((adx < 20) & (c < mid - 2 * sd), 1, np.where((adx < 20) & (c > mid + 2 * sd), -1, 0)); cond[np.isnan(sd) | np.isnan(adx)] = 0
    return GC.edge_sigs(cx, cond, 2.0, 10, lambda k, sg: (c[k] >= mid[k]) if sg > 0 else (c[k] <= mid[k]))


def r1255(d):
    """假破 20 日低（turtle soup）：當日低位穿前 20 日最低但收市返上去 → 買（反之沽）；持 5 日；SL 1.5 ATR。"""
    cx, b, h, l, c, a = ctx(d); n = len(c); cond = np.zeros(n)
    for i in range(21, n):
        lo, hi = l[i - 20:i].min(), h[i - 20:i].max()
        if l[i] < lo and c[i] > lo:
            cond[i] = 1
        elif h[i] > hi and c[i] < hi:
            cond[i] = -1
    return GC.edge_sigs(cx, cond, 1.5, 5)


def r1256(d):
    """五日極端反向：5 日收市變動 ≥ 2.5×ATR14 → 反向做；持 5 日；SL 2.5 ATR。"""
    cx, b, h, l, c, a = ctx(d); n = len(c); cond = np.zeros(n)
    for i in range(20, n):
        if np.isnan(a[i]):
            continue
        mv = c[i] - c[i - 5]
        cond[i] = -1 if mv >= 2.5 * a[i] else (1 if mv <= -2.5 * a[i] else 0)
    return GC.edge_sigs(cx, cond, 2.5, 5)


def r1257(d):
    """NR7 順勢突破：當日波幅係 7 日最細，翌日唔判；以 NR7 日收市方向 = SMA50 方向入（收市 > SMA50 買、< 沽）；持 5 日；SL 2 ATR。"""
    cx, b, h, l, c, a = ctx(d); n = len(c); m = F2.sma(c, 50); rng = h - l; cond = np.zeros(n)
    for i in range(50, n):
        if rng[i] <= rng[i - 6:i].min():
            cond[i] = 1 if c[i] > m[i] else -1
    return GC.edge_sigs(cx, cond, 2.0, 5)


def r1258(d):
    """月尾反向：每月 26 號或之後第一個交易日，本月至今變動（對上月最後收市）≥ 2×ATR14 → 反向做；新月第一日收市平；SL 2.5 ATR。"""
    cx, b, h, l, c, a = ctx(d); n = len(c); t = b["t"]
    dts = [dt.datetime.fromtimestamp(int(x), dt.timezone.utc) for x in t]; mk = np.array([x.year * 12 + x.month for x in dts]); dom = np.array([x.day for x in dts])
    cond = np.zeros(n); prev_close = np.nan; done = -1
    for i in range(20, n):
        if mk[i] != mk[i - 1]:
            prev_close = c[i - 1]
        if dom[i] >= 26 and done != mk[i] and not np.isnan(prev_close) and not np.isnan(a[i]):
            done = mk[i]; mv = c[i] - prev_close
            cond[i] = -1 if mv >= 2 * a[i] else (1 if mv <= -2 * a[i] else 0)
    return GC.edge_sigs(cx, cond, 2.5, 8, lambda k, sg: mk[k] != mk[k - 1])


def r1259(d):
    """外包日順勢：當日高低包住前一日，收市喺當日上 1/4 而且 > SMA50 → 買；下 1/4 而且 < SMA50 → 沽；持 5 日；SL 2 ATR。"""
    cx, b, h, l, c, a = ctx(d); n = len(c); m = F2.sma(c, 50); cond = np.zeros(n)
    for i in range(50, n):
        rg = h[i] - l[i]
        if rg <= 0 or not (h[i] > h[i - 1] and l[i] < l[i - 1]):
            continue
        pos = (c[i] - l[i]) / rg
        cond[i] = 1 if (pos >= 0.75 and c[i] > m[i]) else (-1 if (pos <= 0.25 and c[i] < m[i]) else 0)
    return GC.edge_sigs(cx, cond, 2.0, 5)


RULES = [("#1252", "RSI(2) 順勢回調", r1252), ("#1253", "連跌三日買回調", r1253), ("#1254", "冇趨勢布林帶反向", r1254), ("#1255", "假破 20 日高低", r1255),
         ("#1256", "五日極端反向", r1256), ("#1257", "NR7 順勢", r1257), ("#1258", "月尾反向", r1258), ("#1259", "外包日順勢", r1259)]


def confirm(fn):
    """黃金三段＋2005–09＋白銀，一次過。回傳（文字, 過唔過）。過＝黃金 ①②③ 每段每張平均 > 0、三段合併 PF ≥ 1.15；白銀 2010–25 平均 > 0。"""
    cells, ok, allr = [], True, []
    for src, a, b_ in (("duka", "2015-01-01", "2022-12-31"), ("mt5", "2023-01-01", "2026-10-30"), ("duka", "2010-01-01", "2014-12-31")):
        tr = fn(A.load(src, a, b_)); n, avg, pf, _ = GC.stats(tr); ok = ok and n >= 10 and avg > 0; allr += [x[2] for x in tr]
        cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}")
    r = np.array(allr); pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum()); ok = ok and pf >= 1.15
    I1.silver_mode(True)
    try:
        tr = fn(HL.h1("xau/sig/duka_h1_xagusd/", 2010, 2025))
    finally:
        I1.silver_mode(False)
    n, avg, pfs, _ = GC.stats(tr); ok = ok and avg > 0
    return " ｜ ".join(cells) + f" ｜ 合併 PF {pf:.2f} ｜ 白銀 {n} 張 {avg:+.3f}R PF {pfs:.2f}", ok


def main():
    res = {k: {} for k, _, _ in RULES}
    for sym in P1.PANEL:
        d = P1.load(sym); _, restore = P1.inst_mode(d)
        try:
            for key, _, fn in RULES:
                res[key][sym] = P1.inwin(fn(d))
        finally:
            restore()
        print(sym, {k: len(res[k][sym]) for k in res}, flush=True)
    L = ["# 方法 D 第二階段：先喺 14 品種揀、再用黃金＋白銀確認（IDEAS #1252–#1259）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；14 品種券商 MT5 M1，入場月 2022-09→2026-10；成本 0.02×ATR 中位；最低止蝕 0.3×ATR",
         f"- 第一關（14 品種，五樣全過）：(a) 合計每月平均 > 0 而且 t ≥ {T_MIN}；(b) ≥ 9／14 品種每張平均 > 0；(c) 剔最好品種後每月平均 > 0 而且 t ≥ 2.0；(d) 外匯 9 隻合計每月平均 > 0；(e) ≥ 100 張",
         "- 第二關（只有過第一關先跑，一次過）：黃金三段每段平均 > 0（每段 ≥ 10 張）、三段合併 PF ≥ 1.15、白銀 2010–25 平均 > 0", "",
         "| IDEAS | 規則 | 張數 | 每張平均 R | (a) 每月平均／t | (b) 正品種 | (c) 剔最好品種 平均／t | (d) 外匯每月 | 多／空 每張 | 第一關 |", "|---|---|---|---|---|---|---|---|---|---|"]
    stage1 = []
    for key, name, _ in RULES:
        per = res[key]; allr = np.array([x[2] for s in P1.PANEL for x in per[s]]); n = len(allr); sg = np.array([x[1] for s in P1.PANEL for x in per[s]])
        mon = P1.monthly([per[s] for s in P1.PANEL]); t_all = P1.tstat(mon)
        pos = sum(1 for s in P1.PANEL if per[s] and np.mean([x[2] for x in per[s]]) > 0)
        best = max(P1.PANEL, key=lambda s: sum(x[2] for x in per[s]))
        loo = P1.monthly([per[s] for s in P1.PANEL if s != best]); fx = P1.monthly([per[s] for s in P1.FX])
        a = mon.mean() > 0 and t_all >= T_MIN; b = pos >= 9; c = loo.mean() > 0 and P1.tstat(loo) >= 2.0; dd = fx.mean() > 0; e = n >= 100
        ok = a and b and c and dd and e; mk = lambda v: "✅" if v else "❌"  # noqa: E731
        lo = allr[sg > 0].mean() if (sg > 0).any() else 0.0; sh = allr[sg < 0].mean() if (sg < 0).any() else 0.0
        L.append(f"| {key} | {name} | {n} {mk(e)} | {allr.mean() if n else 0:+.3f} | {mon.mean():+.2f}／{t_all:.2f} {mk(a)} | {pos}／14 {mk(b)} | "
                 f"{loo.mean():+.2f}／{P1.tstat(loo):.2f}（剔 {best}）{mk(c)} | {fx.mean():+.2f}（t {P1.tstat(fx):.2f}）{mk(dd)} | {lo:+.3f}／{sh:+.3f} | {'✅ 過' if ok else '❌'} |")
        if ok:
            stage1.append((key, name))
    L += ["", f"- 第一關過：{'、'.join(k for k, _ in stage1) if stage1 else '冇'}", ""]
    passed = []
    if stage1:
        L += ["## 第二關：黃金＋白銀確認（一次過）", "", "| IDEAS | ① Duka 2015–22 ｜ ② MT5 2023–26 ｜ ③ Duka 2010–14 ｜ 合併 ｜ 白銀 | 判 |", "|---|---|---|"]
        fns = {k: f for k, _, f in RULES}
        for key, _ in stage1:
            txt, ok = confirm(fns[key]); L.append(f"| {key} | {txt} | {'✅ 合格' if ok else '❌'} |")
            if ok:
                passed.append(key)
    L += ["", f"- **兩關都過（合格）：{'、'.join(passed) if passed else '冇'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
