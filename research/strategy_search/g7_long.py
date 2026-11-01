"""[IDEAS #164] 934 H1 回調（G7，TH35 K1.5 R2 T72）長期回測：Dukascopy XAUUSD H1 2005→2026。
H1 引擎：訊號同 xau/g7_live.signal（H4 由 H1 合成、22:00 對齊；H4 EMA50 斜率＋H1 RSI(14) 啱啱穿 35／65）；
入場＝訊號後下一根 H1 開盤；SL＝1.5×H1 ATR(14)、TP＝2R；同一根 SL／TP 都掂當 SL、跳空過 SL 用開盤；72 小時時間止蝕；扣 0.5 美元；一次一張。
先用券商 MT5（M1→H1）2022-10→2026-10 對比 M5 引擎（search2）同參數結果，再跑長期。資金曲線：本金 10,000 HKD／10,000 USD。
用法：python3 research/strategy_search/g7_long.py"""
import datetime as dt
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))

TH, K, RR, T_H = 35.0, 1.5, 2.0, 72
COST = 0.5
HKD = 7.8
OZ = 100


def ema(x, n):
    a = 2 / (n + 1); out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    au, ad = ema(np.clip(d, 0, None), 2 * n - 1), ema(np.clip(-d, 0, None), 2 * n - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + au / ad)


def h4_from_h1(t, o, h, l, c):
    key = (t - 7200) // 14400 * 14400 + 7200
    ks, first = np.unique(key, return_index=True)
    last = np.r_[first[1:], len(t)] - 1
    return ks, c[last]


def backtest(t, o, h, l, c):
    """回傳成交 list：(入場 UTC, 方向, sl 距離美元, R, 出場方式)。"""
    n = len(t)
    r14 = rsi(c, 14)
    tr = np.r_[h[0] - l[0], np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])]
    cs = np.r_[0, np.cumsum(tr)]
    atr = np.full(n, np.nan); atr[13:] = (cs[14:] - cs[:-14]) / 14
    k4, c4 = h4_from_h1(t, o, h, l, c)
    e4 = ema(c4, 50)
    h4j = np.searchsorted(k4, t + 3600 - 14400, side="right") - 1      # H1 收盤時已收盤嘅最後一根 H4
    slope = np.where(h4j >= 50, e4[np.clip(h4j, 0, None)] - e4[np.clip(h4j - 1, 0, None)], 0.0)
    below = r14 <= TH; above = r14 >= 100 - TH
    buy = below & ~np.r_[False, below[:-1]] & (slope > 0)
    sell = above & ~np.r_[False, above[:-1]] & (slope < 0)
    trades, busy_until = [], -1
    for i in range(20, n - 1):
        if not (buy[i] or sell[i]) or i + 1 <= busy_until or math.isnan(atr[i]):
            continue
        s = 1 if buy[i] else -1
        a = i + 1; px = o[a]; d = K * atr[i]
        sl = px - s * d; tp = px + s * RR * d
        ex, how, j_end = None, None, a
        for j in range(a, n):
            if t[j] - t[a] >= T_H * 3600:                       # 時間止蝕：上一根收市
                ex, how, j_end = c[j - 1], "時間", j - 1
                break
            if j > a and (o[j] - sl) * s <= 0:                  # 跳空過 SL
                ex, how, j_end = o[j], "SL", j
                break
            if (l[j] - sl) * s <= 0 if s > 0 else (h[j] - sl) * s <= 0:
                ex, how, j_end = sl, "SL", j
                break
            if (h[j] - tp) * s >= 0 if s > 0 else (l[j] - tp) * s >= 0:
                ex, how, j_end = tp, "TP", j
                break
        if ex is None:
            break                                                # 數據尾未完
        r = (s * (ex - px) - COST) / d
        trades.append((int(t[a]), s, float(d), float(r), how))
        busy_until = j_end
    return trades


def stats(rs):
    rs = np.asarray(rs, float)
    if not len(rs):
        return "n=0"
    w, ls = rs[rs > 0].sum(), -rs[rs < 0].sum()
    s = mx = 0
    for x in rs:
        s = s + 1 if x < 0 else 0; mx = max(mx, s)
    return f"n={len(rs)} 平均 {rs.mean():+.3f}R PF {w / ls if ls else float('inf'):.2f} 最大連敗 {mx}"


def equity(trades, start_hkd, mode, val):
    """mode fixed（val＝手數）／risk（val＝%）。回傳 (最終, 最大回撤%, 開咗幾張, 最低)。"""
    eq = peak = start_hkd; mdd = 0.0; opened = 0; low = eq
    for ts, s, d, r, how in trades:
        per_lot = d * OZ * HKD
        if mode == "fixed":
            lots = val
        else:
            lots = math.floor(eq * val / 100 / per_lot / 0.01 + 1e-9) * 0.01
            lots = min(lots, 1.0)
            if lots < 0.01:
                continue
        eq += r * d * OZ * HKD * lots
        opened += 1
        peak = max(peak, eq); low = min(low, eq)
        mdd = min(mdd, eq / peak - 1)
        if eq <= 0:
            return eq, -1.0, opened, low
    return eq, mdd, opened, low


def load_h1_duka():
    import gb_rulesim as gb
    g = gb.Gcs()
    rows = {}
    for nm in sorted(g.list("xau/sig/duka_h1/")):
        for r in g.read_json(nm) or []:
            rows[int(r[0])] = r
    ks = sorted(rows)
    a = np.array([rows[k] for k in ks], float)
    t, o, h, l, c = a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    flat = (h == l) & (np.r_[np.nan, c[:-1]] == c)
    return t[~flat], o[~flat], h[~flat], l[~flat], c[~flat]


def h1_from_m1(m1):
    key = m1["t"] // 3600 * 3600
    ks, first = np.unique(key, return_index=True)
    last = np.r_[first[1:], len(key)] - 1
    return ks, m1["o"][first], np.maximum.reduceat(m1["h"], first), np.minimum.reduceat(m1["l"], first), m1["c"][last]


def main():
    import search as S
    import search2 as W
    out = ["# 934 H1 回調長期回測（IDEAS #164）", "", f"- 參數固定：RSI {TH:g}／{100 - TH:g}、SL {K}×H1 ATR、TP {RR}R、時間止蝕 {T_H} 小時；每張扣 {COST} 美元", ""]
    # 1) 引擎對比：MT5 2022-10→2026-10，H1 引擎 vs M5 引擎（同參數）
    m1 = S.load("mt5", "2022-08-03", "2026-10-30")
    th = backtest(*h1_from_m1(m1))
    a0 = S.ts_of("2022-10-01")
    th = [x for x in th if x[0] >= a0]
    d5 = W.to_m5(m1); ctx = W.Ctx(d5)
    sig = [(i, s) for i, s in W.signals(ctx, "G7_h1_pullback", {"TH": 35}) if d5["t"][i] >= a0]
    mats = W.trade_mats(d5, sig)
    atr = ctx.atr_at("G7_h1_pullback", np.array([i for i, _ in sig], dtype=np.int64))
    r5, ei, xi = W.simulate(K * atr, mats, RR, T_H)
    keep = S.one_at_a_time(r5, ei, xi)
    out += ["## 1. 引擎對比（券商 MT5，2022-10→2026-10，同參數）", "",
            f"- M5 引擎（search2，下一根 M5 開盤入）：{stats(r5[keep])}",
            f"- H1 引擎（呢個腳本，下一根 H1 開盤入）：{stats([x[3] for x in th])}", ""]
    # 2) 長期 Dukascopy
    t, o, h, l, c = load_h1_duka()
    tr = backtest(t, o, h, l, c)
    yr = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).year   # noqa: E731
    pre = [x for x in tr if yr(x[0]) <= 2022]
    out += [f"## 2. Dukascopy H1 長期（{dt.datetime.fromtimestamp(int(t[0]), dt.timezone.utc):%Y-%m}→{dt.datetime.fromtimestamp(int(t[-1]), dt.timezone.utc):%Y-%m}，{len(t):,} 根 H1）", "",
            f"- 全期：{stats([x[3] for x in tr])}",
            f"- 2005→2022（呢套參數從未見過）：{stats([x[3] for x in pre])} → **{'長期一致' if pre and np.mean([x[3] for x in pre]) > 0 and (lambda rs: rs[rs > 0].sum() / max(-rs[rs < 0].sum(), 1e-9))(np.array([x[3] for x in pre])) >= 1.1 else '只係近年有效'}**",
            f"- 2023→2026：{stats([x[3] for x in tr if yr(x[0]) >= 2023])}",
            f"- 做多：{stats([x[3] for x in tr if x[1] > 0])}；做空：{stats([x[3] for x in tr if x[1] < 0])}", "",
            "| 年 | 張 | 平均 R | ΣR | 止損中位（美元） |", "|---|---|---|---|---|"]
    for y in sorted({yr(x[0]) for x in tr}):
        g = [x for x in tr if yr(x[0]) == y]
        out.append(f"| {y} | {len(g)} | {np.mean([x[3] for x in g]):+.2f} | {sum(x[3] for x in g):+.1f} | {np.median([x[2] for x in g]):.1f} |")
    # 3) 資金曲線
    out += ["", "## 3. 本金 10,000 嘅資金曲線（全期，按實際次序）", "",
            "| 本金 | 做法 | 最終資金 | 年化 | 最大回撤 | 實際開咗幾多張 |", "|---|---|---|---|---|---|"]
    years = (tr[-1][0] - tr[0][0]) / (365.25 * 86400) if tr else 1
    for label, start in (("10,000 HKD", 10000.0), ("10,000 USD（78,000 HKD）", 78000.0)):
        for mode, val, name in (("fixed", 0.01, "固定 0.01 手"), ("fixed", 0.05, "固定 0.05 手"), ("risk", 1.0, "按風險 1%"), ("risk", 2.0, "按風險 2%")):
            fin, mdd, n, low = equity(tr, start, mode, val)
            cagr = (fin / start) ** (1 / years) - 1 if fin > 0 else -1
            shown = f"{fin:,.0f} HKD" + (f"（{fin / 7.8:,.0f} USD）" if start == 78000.0 else "")
            out.append(f"| {label} | {name} | {shown if fin > 0 else '💥 爆倉'} | {cagr:+.1%} | {'—' if mdd == -1 else f'{mdd:.0%}'} | {n}／{len(tr)} |")
    for start, lab in ((10000.0, "10,000 HKD"), (78000.0, "10,000 USD")):
        for y0 in (2023,):
            sub = [x for x in tr if yr(x[0]) >= y0]
            fin, mdd, n, _ = equity(sub, start, "risk", 1.0)
            out.append(f"| {lab}（只計 2023→2026） | 按風險 1% | {fin:,.0f} HKD | — | {mdd:.0%} | {n}／{len(sub)} |")
    out += ["", "## 注意",
            "- H1 引擎同 M5 引擎嘅差距見第 1 節（入場遲最多 1 小時、H1 內 SL／TP 先後只能保守當 SL）。",
            "- 2005–2010 金價低（400–1,200 美元），止損美元細，所以同一本金可以落大啲手；成本 0.5 美元喺早年佔 R 比例較大。",
            "- 冇計隔夜息、孖展要求、數據公佈極端滑價；MT5 最細 0.01 手：本金細嘅時候按風險 1% 好多張開唔到（表入面「實際開咗幾多張」）。",
            "- 策略家族係用 2022 之後數據揀出嚟，2005–2022 雖然冇用過，但唔代表將來一樣。"]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "G7_LONG.md"), "w", encoding="utf-8").write(md)
    json.dump([list(x) for x in tr], open("/tmp/g7_long_trades.json", "w"))


if __name__ == "__main__":
    main()
