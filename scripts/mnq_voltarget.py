#!/usr/bin/env python3
# =============================================================================
# MNQ 部位規則 × 波動率目標（Volatility Targeting）回測
# -----------------------------------------------------------------------------
# 為什麼用 QQQ：repo 內沒有 MNQ 的長歷史（nq.csv 只有 2024-03 起）。QQQ 與 NQ 期貨在重疊期
# （2024-03 ～ 2026-09，633 日）日報酬相關 0.998、年化波動 21.2% vs 21.0%，用 QQQ 還原價代表
# NQ/MNQ 的價格路徑是合理的（1999 年起，涵蓋 2000–02、2008、2020、2022）。
# 還原價含股息；期貨沒有股息但現金可賺利息，兩者大致相抵，這裡閒置現金報酬記 0（對降曝險策略保守）。
#
# 沒有找到你現行的 MNQ 部位規則，所以疊在三種簡單的底層規則上，看波動率目標有沒有「額外」價值：
#   B0  永遠做多（曝險 100%）
#   B1  趨勢：收盤 > 200 日均線才做多
#   B2  突破：收盤創 50 日新高進場、跌破 20 日低點出場（和黃金 v12 同型）
# 波動率目標：曝險 = min(上限, 目標波動 ÷ 預估波動)，預估波動只用「前一日收盤」以前的資料。
#   估計器：rv20（20 日已實現）、ewma（λ=0.94）、max(rv20, rv60)、VIX 隱含（VIX ÷ 100 × 歷史中位比值）
# 對照組（避免「只是降低曝險」的假象）：
#   固定曝險 = 與波動率目標策略「同平均曝險」的固定部位（同一底層規則下）
# 另外檢驗：
#   * 再平衡規則（每日 / 每週 / 偏離 25% 才調）與成本（1 / 3 / 10bp 每單位換手）
#   * 合約整數限制：1 張 MNQ = NAV 的 k%（k=20/40/60/100%），曝險只能是 k 的整數倍
#     （repo 的 US_VRP_NOTES：NAV 約 HK$80 萬，1 張 MNQ ≈ 60% NAV）
#   * 分階段與危機期間表現、參數網格的穩健性、配對區塊自助法（ΔSharpe、ΔMaxDD 信賴區間）
#
# 用法：python3 scripts/mnq_voltarget.py → data/vol/study/MNQ_VOLTARGET.md
# =============================================================================
import itertools
import os

import numpy as np
import pandas as pd

VOL = "data/vol"
OUT = "data/vol/study"
COST = 0.0003          # 預設每單位換手成本 3bp
ANN = 252
RNG = np.random.default_rng(7)


# ---------------------------------------------------------------- 資料與估計器
def load(name):
    return pd.read_csv(os.path.join(VOL, f"{name}.csv"), parse_dates=["date"]).set_index("date")["close"]


def sigma_estimators(px, vix):
    r = px.pct_change()
    rv20 = r.rolling(20).std() * np.sqrt(ANN)
    rv60 = r.rolling(60).std() * np.sqrt(ANN)
    ewma = np.sqrt((r ** 2).ewm(alpha=0.06, adjust=False, min_periods=20).mean() * ANN)
    vx = vix.reindex(px.index).ffill() / 100
    ratio = (rv20 / vx).expanding(250).median().shift(1)     # 已實現 ÷ VIX 的歷史中位比值（只用過去）
    return r, {
        "rv20": rv20,
        "ewma": ewma,
        "max(rv20,rv60)": np.maximum(rv20, rv60),
        "VIX隱含": vx * ratio,
    }


def base_filters(px):
    sma200 = px.rolling(200).mean()
    hi50, lo20 = px.shift(1).rolling(50).max(), px.shift(1).rolling(20).min()
    b1 = (px > sma200).astype(float).where(sma200.notna())
    state, out = 0.0, []
    for p, h, l in zip(px.values, hi50.values, lo20.values):
        if state == 0.0 and not np.isnan(h) and p > h:
            state = 1.0
        elif state == 1.0 and not np.isnan(l) and p < l:
            state = 0.0
        out.append(state)
    b2 = pd.Series(out, index=px.index)
    return {"B0 永遠做多": pd.Series(1.0, index=px.index), "B1 趨勢（200日線）": b1, "B2 突破（50日高/20日低）": b2}


# ---------------------------------------------------------------- 曝險與回測
def exposure(base, sig, target, cap, rebal="daily", band=0.25, k=None):
    """base：底層規則（收盤已知，0/1）；sig：估計波動（收盤已知）。兩者都延遲一日使用。
    k：1 張合約占 NAV 的比例（None = 連續）。回傳「第 t 日持有的曝險」。"""
    b, s = base.shift(1), sig.shift(1)
    tgt = (target / s).clip(upper=cap)
    idx = base.index
    out = np.zeros(len(idx))
    cur = 0.0
    for i in range(len(idx)):
        bi, ti = b.iloc[i], tgt.iloc[i]
        if np.isnan(bi) or (np.isnan(ti) and target is not None):
            out[i] = 0.0 if np.isnan(bi) else cur
            cur = out[i]
            continue
        want = bi * ti
        if want == 0.0 or cur == 0.0:
            new = want                               # 出場或進場一律立即執行
        elif rebal == "daily":
            new = want
        elif rebal == "weekly":
            new = want if idx[i].weekday() == 0 else cur
        else:                                        # band：偏離超過 band 才調
            new = want if abs(want - cur) / cur > band else cur
        if k:
            new = np.floor(new / k + 1e-9) * k       # 整數張，向下取整：不超過目標風險與曝險上限
        out[i] = cur = new
    return pd.Series(out, index=idx)


def fixed_exposure(base, level):
    return base.shift(1).fillna(0.0) * level


def run(ret, expo, cost=COST):
    turn = expo.diff().abs().fillna(expo.abs())
    net = expo * ret - turn * cost
    return net, turn


def metrics(net, expo, turn):
    net = net.dropna()
    eq = (1 + net).cumprod()
    yrs = len(net) / ANN
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    m20 = (1 + net).rolling(20).apply(np.prod, raw=True).min() - 1
    return {"cagr": cagr, "vol": net.std() * np.sqrt(ANN), "sharpe": net.mean() / net.std() * np.sqrt(ANN),
            "maxdd": dd, "calmar": cagr / abs(dd) if dd else np.nan, "worst20": m20,
            "expo": expo.reindex(net.index).mean(), "turn": turn.reindex(net.index).sum() / yrs}


def row(name, m):
    return (f"| {name} | {m['cagr'] * 100:+.1f}% | {m['vol'] * 100:.1f}% | {m['sharpe']:.2f} | {m['maxdd'] * 100:.1f}% | "
            f"{m['calmar']:.2f} | {m['worst20'] * 100:.1f}% | {m['expo'] * 100:.0f}% | {m['turn']:.1f} |")


HEAD = ["| 版本 | 年化報酬 | 年化波動 | 夏普 | 最大回撤 | Calmar | 最差 20 日 | 平均曝險 | 年換手 |",
        "|---|---|---|---|---|---|---|---|---|"]


def trio(ret, base, sig, target, cap, rebal="band", cost=COST):
    """回傳 (底層規則, 波動率目標, 同平均曝險固定部位) 三組 (net, expo, turn)。"""
    e_base = fixed_exposure(base, 1.0)
    e_vt = exposure(base, sig, target, cap, rebal)
    on = base.shift(1).fillna(0.0) > 0
    avg_on = e_vt[on].mean() if on.any() else 1.0
    e_fix = fixed_exposure(base, avg_on)
    res = []
    for e in (e_base, e_vt, e_fix):
        net, tu = run(ret, e, cost)
        res.append((net, e, tu))
    return res, avg_on


# ---------------------------------------------------------------- 區塊自助法
def stationary_bootstrap(x, n_boot=2000, mean_block=20):
    n = len(x)
    p = 1 / mean_block
    idx = np.empty((n_boot, n), dtype=np.int64)
    start = RNG.integers(0, n, size=(n_boot, n))
    newb = RNG.random((n_boot, n)) < p
    idx[:, 0] = start[:, 0]
    for t in range(1, n):
        idx[:, t] = np.where(newb[:, t], start[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def paired_boot(a, b, n_boot=2000):
    """a、b：同日期的日報酬（策略、對照）。回傳 ΔSharpe 與 ΔMaxDD 的 5/50/95 百分位與 P(Δ>0)。"""
    d = pd.concat([a, b], axis=1).dropna().values
    idx = stationary_bootstrap(d, n_boot)
    A, B = d[idx, 0], d[idx, 1]
    sh = lambda X: X.mean(1) / X.std(1) * np.sqrt(ANN)
    mdd = lambda X: ((np.cumprod(1 + X, 1) / np.maximum.accumulate(np.cumprod(1 + X, 1), 1)) - 1).min(1)
    dsh, ddd = sh(A) - sh(B), mdd(A) - mdd(B)       # ΔMaxDD > 0 = 回撤較淺
    q = lambda v: np.percentile(v, [5, 50, 95])
    return q(dsh), (dsh > 0).mean(), q(ddd), (ddd > 0).mean()


# ---------------------------------------------------------------- 主程式
def main():
    px, vix = load("qqq"), load("vix")
    ret, sigs = sigma_estimators(px, vix)
    bases = base_filters(px)
    start = px.index[300]                     # 讓所有估計器與 200 日線都有值
    ret = ret[ret.index >= start]
    bases = {k: v[v.index >= start] for k, v in bases.items()}
    sigs = {k: v[v.index >= start] for k, v in sigs.items()}
    # VIX 隱含估計器從 2005-10 才有；為了公平比較，主表所有版本用同一段樣本（2005 年後）
    common = ret.index[ret.index >= max(s.dropna().index[0] for s in sigs.values())]
    L = ["# MNQ 部位規則 × 波動率目標回測", "",
         f"標的：QQQ 還原價代表 NQ/MNQ（與 NQ 期貨 2024–2026 重疊期日報酬相關 0.998）。"
         f"主表樣本 {common[0]:%Y-%m-%d} ～ {common[-1]:%Y-%m-%d}（受 VIX 資料限制）。"
         f"成本預設每單位換手 {COST * 1e4:.0f}bp；閒置現金報酬 0；訊號與波動估計皆用前一日收盤。"
         "產生方式：`python3 scripts/mnq_voltarget.py`。", "",
         "repo 內**沒有找到現行 MNQ 部位規則**，所以疊在三種簡單底層規則上，看波動率目標的「額外」價值；"
         "「固定曝險」對照組 = 與波動率目標同平均曝險的固定部位（扣掉『只是降低曝險』的效果）。", ""]
    ret_c = ret.loc[common]
    # ---------------- 1. 主表
    L += ["## 1. 主結果（目標波動 15%，曝險上限 1.0，偏離 25% 才調整，估計器 ewma）", ""]
    boot = {}
    for bn, base in bases.items():
        b = base.loc[common]
        sig = sigs["ewma"].loc[common]
        res, avg_on = trio(ret_c, b, sig, 0.15, 1.0)
        L += [f"### {bn}", "", *HEAD]
        for name, (net, e, tu) in zip(("底層規則（曝險 100% 或 0）", "波動率目標 15%",
                                       f"固定曝險 {avg_on * 100:.0f}%（同平均曝險對照）"), res):
            L.append(row(name, metrics(net, e, tu)))
        boot[bn] = paired_boot(res[1][0], res[2][0])
        L.append("")
    # ---------------- 2. 區塊自助法
    L += ["## 2. 統計顯著性：波動率目標 vs 同平均曝險固定部位（配對區塊自助法，2000 次，平均區塊 20 日）", "",
          "ΔSharpe = 波動率目標 − 固定曝險；ΔMaxDD > 0 代表回撤較淺。括號為 5% ～ 95% 區間。", "",
          "| 底層規則 | ΔSharpe 中位數（區間） | P(ΔSharpe>0) | ΔMaxDD 中位數（區間） | P(回撤較淺) |", "|---|---|---|---|---|"]
    for bn, (qs, ps, qd, pd_) in boot.items():
        L.append(f"| {bn} | {qs[1]:+.2f}（{qs[0]:+.2f} ～ {qs[2]:+.2f}） | {ps * 100:.0f}% | "
                 f"{qd[1] * 100:+.1f}pp（{qd[0] * 100:+.1f} ～ {qd[2] * 100:+.1f}） | {pd_ * 100:.0f}% |")
    # ---------------- 3. 參數網格
    L += ["", "## 3. 參數網格：結論是否依賴特定參數？", "",
          "每格都是「波動率目標 vs 同平均曝險固定部位」；勝率 = 夏普較高的格子比例（回撤較淺同理）。", "",
          "| 底層規則 | 設定數 | 夏普較高 | 最大回撤較淺 | ΔSharpe 中位數 | ΔMaxDD 中位數 |", "|---|---|---|---|---|---|"]
    grid_rows = []
    for bn, base in bases.items():
        b = base.loc[common]
        wins_s = wins_d = n = 0
        dsh, ddd = [], []
        for est, tgt, cap, reb in itertools.product(sigs, (0.10, 0.15, 0.20, 0.25), (1.0, 1.5), ("daily", "weekly", "band")):
            res, _ = trio(ret_c, b, sigs[est].loc[common], tgt, cap, reb)
            mv, mf = metrics(*res[1]), metrics(*res[2])
            n += 1
            wins_s += mv["sharpe"] > mf["sharpe"]
            wins_d += mv["maxdd"] > mf["maxdd"]
            dsh.append(mv["sharpe"] - mf["sharpe"])
            ddd.append(mv["maxdd"] - mf["maxdd"])
        L.append(f"| {bn} | {n} | {wins_s}/{n}（{wins_s / n * 100:.0f}%） | {wins_d}/{n}（{wins_d / n * 100:.0f}%） | "
                 f"{np.median(dsh):+.2f} | {np.median(ddd) * 100:+.1f}pp |")
        grid_rows.append((bn, est))
    L += ["", "估計器比較（B0 永遠做多，目標 15%，上限 1.0，band 再平衡）：", "", *HEAD]
    b0 = bases["B0 永遠做多"].loc[common]
    for est in sigs:
        res, avg_on = trio(ret_c, b0, sigs[est].loc[common], 0.15, 1.0)
        L.append(row(f"波動率目標｜{est}", metrics(*res[1])))
    res, _ = trio(ret_c, b0, sigs["ewma"].loc[common], 0.15, 1.0)
    L.append(row("買進持有（對照）", metrics(*res[0])))
    # ---------------- 4. 目標波動與上限
    L += ["", "目標波動與曝險上限（B0 永遠做多，ewma，band 再平衡）：", "", *HEAD]
    for tgt, cap in itertools.product((0.10, 0.15, 0.20, 0.25), (1.0, 1.5)):
        res, _ = trio(ret_c, b0, sigs["ewma"].loc[common], tgt, cap)
        L.append(row(f"目標 {tgt * 100:.0f}%｜上限 {cap:.1f}", metrics(*res[1])))
    # ---------------- 5. 成本與再平衡
    L += ["", "## 4. 再平衡規則與成本（B0 永遠做多，目標 15%，上限 1.0，ewma）", "", *HEAD]
    for reb, cost in itertools.product(("daily", "weekly", "band"), (0.0001, 0.0003, 0.001)):
        res, _ = trio(ret_c, b0, sigs["ewma"].loc[common], 0.15, 1.0, reb, cost=cost)
        L.append(row(f"{ {'daily': '每日', 'weekly': '每週', 'band': '偏離25%'}[reb] }｜成本 {cost * 1e4:.0f}bp",
                     metrics(*res[1])))
    # ---------------- 6. 分階段與危機
    L += ["", "## 5. 分階段與危機期間（B0，目標 15%，上限 1.0，band，ewma；全期設定相同）", "",
          "| 期間 | 買進持有 報酬 / 最大回撤 | 波動率目標 報酬 / 最大回撤 | 同曝險固定 報酬 / 最大回撤 |", "|---|---|---|---|"]
    res, _ = trio(ret_c, b0, sigs["ewma"].loc[common], 0.15, 1.0)
    periods = [("2006–2011（含 2008）", "2006-10-01", "2011-12-31"), ("2012–2019", "2012-01-01", "2019-12-31"),
               ("2020–2026", "2020-01-01", "2026-12-31"), ("2008 金融海嘯", "2007-10-31", "2009-03-09"),
               ("2020-02 ～ 2020-03", "2020-02-19", "2020-03-23"), ("2022 升息熊市", "2021-11-19", "2022-12-28")]
    for label, a, z in periods:
        cells = []
        for net, _, _ in res:
            p = net[(net.index >= a) & (net.index <= z)]
            if len(p) < 5:
                cells.append("—")
                continue
            eq = (1 + p).cumprod()
            cells.append(f"{(eq.iloc[-1] - 1) * 100:+.1f}% / {(eq / eq.cummax() - 1).min() * 100:.1f}%")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    # ---------------- 7. 整數合約
    L += ["", "## 6. 合約整數限制（B0 永遠做多，目標 15%，上限 1.0，偏離 25% 才調，ewma）", "",
          "1 張 MNQ 名目 = NAV 的 k%（NQ ≈ 30,500 點 × US$2 ≈ US$61k；NAV 約 US$100k → k ≈ 60%）。"
          "波動率目標的張數 = 向下取整（目標曝險 ÷ k），所以不會超過目標風險或上限；"
          "對照 = 實務上你能持有的固定張數（最多不超過 100% NAV）。兩者平均曝險不同，請看夏普與 Calmar。", "", *HEAD]
    sig_e = sigs["ewma"].loc[common]
    cont = exposure(b0, sig_e, 0.15, 1.0, "band")
    L.append(row("波動率目標｜連續（可任意分割，理想情況）", metrics(*[run(ret_c, cont)[0], cont, run(ret_c, cont)[1]])))
    for k in (0.2, 0.4, 0.6, 1.0):
        e_int = exposure(b0, sig_e, 0.15, 1.0, "band", k=k)
        n_fix = max(1, int(np.floor(1.0 / k + 1e-9)))
        e_fix = fixed_exposure(b0, n_fix * k)
        for nm, e in ((f"波動率目標｜1 張 = NAV {k * 100:.0f}%（整數張）", e_int),
                      (f"固定持有 {n_fix} 張（= NAV {n_fix * k * 100:.0f}%）", e_fix)):
            net, tu = run(ret_c, e)
            L.append(row(nm, metrics(net, e, tu)))
    # 1 張 = NAV 60%（repo 筆記中的實際情況）：不同目標波動的敏感度
    L += ["", "1 張 = NAV 60% 時，波動率目標在整數限制下等同「持有 1 張，估計波動超過『目標 ÷ 60%』就空手」，各目標的敏感度：", "",
          "| 目標波動 | 空手門檻（估計波動 >） | 空手天數占比 | 年化報酬 | 年化波動 | 夏普 | 最大回撤 | Calmar | 最差 20 日 | 平均曝險 | 年換手 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for tgt in (0.10, 0.15, 0.20, 0.25):
        e = exposure(b0, sig_e, tgt, 1.0, "band", k=0.6)
        net, tu = run(ret_c, e)
        m = metrics(net, e, tu)
        L.append(f"| {tgt * 100:.0f}% | {tgt / 0.6 * 100:.0f}% | {(e == 0).mean() * 100:.0f}% | {m['cagr'] * 100:+.1f}% | "
                 f"{m['vol'] * 100:.1f}% | {m['sharpe']:.2f} | {m['maxdd'] * 100:.1f}% | {m['calmar']:.2f} | "
                 f"{m['worst20'] * 100:.1f}% | {m['expo'] * 100:.0f}% | {m['turn']:.1f} |")
    # ---------------- 8. 全樣本（含 2000–02 科技泡沫）
    full_ret = px.pct_change()
    full_ret = full_ret[full_ret.index >= px.index[30]]
    full_sig = sigma_estimators(px, vix)[1]["ewma"].reindex(full_ret.index)
    base_full = pd.Series(1.0, index=full_ret.index)
    L += ["", "## 8. 全樣本含 2000–2002 科技泡沫（只用 ewma 估計器，B0 永遠做多，上限 1.0，band 25%）", "",
          f"樣本 {full_ret.index[0]:%Y-%m-%d} ～ {full_ret.index[-1]:%Y-%m-%d}（VIX 隱含估計器要到 2006 年才有，所以這裡不用）。", "", *HEAD]
    for tgt in (0.15, 0.20):
        res, avg_on = trio(full_ret, base_full, full_sig, tgt, 1.0)
        if tgt == 0.15:
            L.append(row("買進持有", metrics(*res[0])))
        L.append(row(f"波動率目標 {tgt * 100:.0f}%", metrics(*res[1])))
        L.append(row(f"固定曝險 {avg_on * 100:.0f}%（對照 {tgt * 100:.0f}% 的同平均曝險）", metrics(*res[2])))
    res, _ = trio(full_ret, base_full, full_sig, 0.15, 1.0)
    L += ["", "| 期間 | 買進持有 | 波動率目標 15% | 同曝險固定 |", "|---|---|---|---|"]
    for label, a_, z_ in (("2000-03 ～ 2002-10 科技泡沫", "2000-03-10", "2002-10-09"),
                          ("2007-10 ～ 2009-03 金融海嘯", "2007-10-31", "2009-03-09")):
        cells = []
        for net, _, _ in res:
            p = net[(net.index >= a_) & (net.index <= z_)]
            eq = (1 + p).cumprod()
            cells.append(f"{(eq.iloc[-1] - 1) * 100:+.1f}% / 回撤 {(eq / eq.cummax() - 1).min() * 100:.1f}%")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    # 目前狀態
    s_now = sigs["ewma"].iloc[-1]
    L += ["", "## 9. 目前狀態", ""]
    for nm, s in sigs.items():
        L.append(f"- {nm}：{s.iloc[-1] * 100:.1f}% → 目標 15% 的曝險 {min(1.0, 0.15 / s.iloc[-1]) * 100:.0f}%、"
                 f"目標 20% 的曝險 {min(1.0, 0.20 / s.iloc[-1]) * 100:.0f}%")
    L += ["", f"（最近一日 {px.index[-1]:%Y-%m-%d}；NAV 約 US$100k 時，1 張 MNQ ≈ 60% NAV，"
          f"ewma 目標 15% 的曝險 {min(1.0, 0.15 / s_now) * 100:.0f}% = {min(1.0, 0.15 / s_now) / 0.6:.1f} 張，向下取整 = "
          f"{int(min(1.0, 0.15 / s_now) / 0.6 + 1e-9)} 張。）", "",
          "## 限制", "",
          "- 沒有你現行的 MNQ 規則，只能用三種簡單底層規則；若你的規則有進出場邏輯，結論需要重測。",
          "- QQQ 還原價含股息，閒置現金報酬記 0；期貨有保證金、展期與融資成本，這裡沒有逐項建模。",
          "- 網格與門檻是在同一份資料上檢視，沒有樣本外滾動驗證；網格勝率只能說明結論是否依賴單一參數。",
          "- 波動率目標降低風險的同時也降低報酬；是否划算取決於你更在乎夏普、最大回撤還是絕對報酬。", ""]
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "MNQ_VOLTARGET.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
