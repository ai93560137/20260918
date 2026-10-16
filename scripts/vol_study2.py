#!/usr/bin/env python3
# =============================================================================
# MOVE / VIX 特徵：顯著性檢定、分級降槓桿部位回測、黃金 + 實質利率方向
# -----------------------------------------------------------------------------
# 接在 scripts/vol_study.py 後面（同一組特徵，資料在 data/vol/*.csv）。
#
# 1. 顯著性：「觸發日」與「非觸發日」的未來報酬 / 未來 20 日已實現波動差異，
#    用 Newey-West（落後期 = 2 × 期間）處理重疊；另算「獨立事件」（相隔 ≥ 20 個交易日）
#    的平均報酬對全樣本平均的 t 值。一次檢定 6 條規則 × 4 標的 × 3 個統計量，
#    純靠運氣也會出現幾個 |t| > 2，所以 |t| ≥ 3 才算比較可信。
# 2. 部位回測（QQQ、SPY 買進持有 vs 依訊號調整曝險）：
#    - 分級降槓桿：4 個條件觸發幾個 → 曝險 100 / 75 / 50 / 25%
#    - 單一規則減半、原始斷路器（C 觸發即空手）
#    - 對照組：同平均曝險的固定曝險、只看資產自己波動的波動率目標
#    含成本（每單位換手 5bp）、現金報酬 0（對降曝險策略偏保守）。
#    另附前 / 後半段（2020 年前後）與門檻敏感度，避免單一參數與單一時期。
# 3. 黃金：MOVE 急升時，依 10 年期實質利率（TIPS）5 日變化方向分組，
#    看 GLD 未來報酬；再用「50 日突破做多」當底層策略，測「放大 / 縮小部位」有沒有用。
#    需要 data/vol/real_yield.csv（scripts/fetch_real_yield.py，由 Actions 產生）。
#
# 時間對齊（相對第一版修正）：訊號以「當天收盤已知」的資料計算，報酬從「當天收盤」起算；
# 第一版 vol_study.py 的觸發後報酬多延遲了一天。部位回測中，第 t 日報酬用 t−1 收盤的訊號。
#
# 用法：python3 scripts/vol_study2.py → data/vol/study/README_v2.md
# =============================================================================
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vol_study import OUT, VOL, build, load  # noqa: E402

COST = 0.0005          # 每單位換手成本（5bp）
SPLIT = "2020-01-01"   # 前 / 後半段
TARGETS = [("qqq", "QQQ（對應 MNQ）"), ("spy", "SPY"), ("tlt", "TLT"), ("gld", "GLD（黃金）")]


# ---------------------------------------------------------------- 工具
def nw_diff(y, d, lag):
    """y = a + b·d 的 b 與 Newey-West t 值。y、d 為對齊、無缺值的 Series。"""
    X = np.column_stack([np.ones(len(d)), d.astype(float).values])
    beta = np.linalg.lstsq(X, y.values, rcond=None)[0]
    u = y.values - X @ beta
    n = len(y)
    Xu = X * u[:, None]
    S = Xu.T @ Xu / n
    for k in range(1, lag + 1):
        G = Xu[k:].T @ Xu[:-k] / n
        S += (1 - k / (lag + 1)) * (G + G.T)
    bread = np.linalg.inv(X.T @ X / n)
    V = bread @ S @ bread / n
    return beta[1], beta[1] / np.sqrt(V[1, 1])


def episodes_mask(mask, gap=20):
    """每群觸發的第一天（與前一次觸發相隔 ≥ gap 個交易日）。"""
    idx = np.flatnonzero(mask.values)
    keep = [i for j, i in enumerate(idx) if j == 0 or i - idx[j - 1] >= gap]
    out = pd.Series(False, index=mask.index)
    out.iloc[keep] = True
    return out


def star(t):
    return "**" if abs(t) >= 3 else ("*" if abs(t) >= 2 else "")


def fwd_ret(px, h):
    return np.log(px.shift(-h) / px)


def fwd_vol(px, h=20):
    r = np.log(px).diff()
    return r[::-1].rolling(h).std()[::-1].shift(-1) * np.sqrt(252)


def signals(F):
    """F：當天收盤已知的特徵（不延遲）。"""
    return {
        "A：MOVE z20 > 1.5": F.move_z20 > 1.5,
        "A'：252日百分位 > 0.9": F.move_pct252 > 0.9,
        "B：5日變化 > +20%": F.move_roc5 > np.log(1.2),
        "C：corr20 > 0.6 且 z20 都 > 1": (F.corr20 > 0.6) & (F.move_z20 > 1) & (F.vix_z20 > 1),
        "C'：corr60 > 0.5 且 z60 都 > 1": (F.corr60 > 0.5) & (F.move_z60 > 1) & (F.vix_z60 > 1),
        "VIX 期限倒掛": F.vix_ts > 1,
    }


# ---------------------------------------------------------------- 1. 顯著性
def significance(F, sig, start):
    L = ["## 1. 顯著性檢定", "",
         "差異 = 觸發日平均 − 非觸發日平均（報酬單位 %，波動單位 個百分點）；括號是 Newey-West t 值；"
         "`*` |t|≥2、`**` |t|≥3。「獨立事件」欄 = 每群觸發第一天的未來 20 日報酬相對全樣本的 t 值（事件數 n）。", ""]
    for tgt, label in TARGETS:
        px = load(tgt)
        if px is None:
            continue
        px = px[px.index >= start]
        L += [f"### {label}（{px.index[0]:%Y-%m} ～ {px.index[-1]:%Y-%m}）", "",
              "| 規則 | 觸發天數 | 未來 5 日報酬差 | 未來 20 日報酬差 | 未來 20 日波動差 | 獨立事件 20 日報酬 |",
              "|---|---|---|---|---|---|"]
        y5, y20, v20 = fwd_ret(px, 5), fwd_ret(px, 20), fwd_vol(px)
        for name, m in sig.items():
            m = m.reindex(px.index).fillna(False).astype(bool)
            if m.sum() < 20:
                continue
            cells = []
            for y, lag, scale in ((y5, 10, 100), (y20, 40, 100), (v20, 40, 100)):
                ok = y.notna()
                b, t = nw_diff(y[ok], m[ok], lag)
                cells.append(f"{b * scale:+.2f}（{t:+.1f}）{star(t)}")
            ev = episodes_mask(m)
            r = y20[ev & y20.notna()]
            mu = y20.mean()
            et = (r.mean() - mu) / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 else float("nan")
            L.append(f"| {name} | {int(m.sum())} | " + " | ".join(cells)
                     + f" | {r.mean() * 100:+.2f}% vs {mu * 100:+.2f}%（t={et:+.1f}，n={len(r)}）{star(et)} |")
        L.append("")
    return L


# ---------------------------------------------------------------- 2. 部位回測
def backtest(ret, expo, cost=COST):
    expo = expo.reindex(ret.index).fillna(1.0)
    turn = expo.diff().abs().fillna(0.0)
    return expo * ret - turn * cost, expo, turn


def metrics(net, expo, turn):
    eq = (1 + net).cumprod()
    yrs = len(net) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    sd = net.std() * np.sqrt(252)
    return {"cagr": cagr, "vol": sd, "sharpe": net.mean() / net.std() * np.sqrt(252),
            "maxdd": dd, "calmar": cagr / abs(dd) if dd else float("nan"),
            "expo": expo.mean(), "turn": turn.sum() / yrs}


def strategies(f, ret):
    """f：延遲一天的特徵（第 t 日用 t−1 收盤資訊）。回傳 {名稱: 曝險 Series}。"""
    a = f.move_pct252 > 0.9
    b = f.move_roc5 > np.log(1.2)
    c = (f.corr20 > 0.6) & (f.move_z20 > 1) & (f.vix_z20 > 1)
    v = f.vix_ts > 1
    score = a.astype(int) + b.astype(int) + c.astype(int) + v.astype(int)
    graded = score.map({0: 1.0, 1: 0.75, 2: 0.5, 3: 0.25, 4: 0.25})
    vt = (0.15 / (ret.rolling(20).std().shift(1) * np.sqrt(252))).clip(upper=1.0).fillna(1.0)
    return {
        "買進持有": pd.Series(1.0, index=f.index),
        "分級降槓桿（4 條件，100/75/50/25%）": graded,
        "A' 觸發 → 減半": a.map({True: 0.5, False: 1.0}),
        "原始斷路器（C 觸發 → 空手）": c.map({True: 0.0, False: 1.0}),
        "波動率目標 15%（只看自身波動，對照）": vt,
    }


def sizing(f, start):
    L = ["## 2. 分級降槓桿的部位回測", "",
         f"成本每單位換手 {COST * 1e4:.0f}bp；閒置現金報酬 0（對降曝險策略偏保守）；訊號用前一日收盤。", ""]
    for tgt, label in TARGETS[:2]:
        px = load(tgt)
        px = px[px.index >= start]
        ret = px.pct_change().dropna()
        ff = f.reindex(ret.index)
        strat = strategies(ff, ret)
        res, nets = {}, {}
        for name, e in strat.items():
            net, ex, tu = backtest(ret, e)
            res[name], nets[name] = metrics(net, ex, tu), net
        g_expo = res["分級降槓桿（4 條件，100/75/50/25%）"]["expo"]
        cnet, cex, ctu = backtest(ret, pd.Series(g_expo, index=ret.index))
        res[f"固定曝險 {g_expo * 100:.0f}%（對照：與分級策略同平均曝險）"] = metrics(cnet, cex, ctu)
        nets[f"固定曝險 {g_expo * 100:.0f}%（對照：與分級策略同平均曝險）"] = cnet
        L += [f"### {label}（{ret.index[0]:%Y-%m} ～ {ret.index[-1]:%Y-%m}）", "",
              "| 策略 | 年化報酬 | 年化波動 | 夏普 | 最大回撤 | Calmar | 平均曝險 | 年換手 |",
              "|---|---|---|---|---|---|---|---|"]
        for name, m in res.items():
            L.append(f"| {name} | {m['cagr'] * 100:+.1f}% | {m['vol'] * 100:.1f}% | {m['sharpe']:.2f} | "
                     f"{m['maxdd'] * 100:.1f}% | {m['calmar']:.2f} | {m['expo'] * 100:.0f}% | {m['turn']:.1f} |")
        # 前 / 後半段夏普與最大回撤
        L += ["", f"前 / 後半段（{SPLIT[:4]} 年前後）夏普與最大回撤：", "",
              "| 策略 | 前半 夏普 | 前半 最大回撤 | 後半 夏普 | 後半 最大回撤 |", "|---|---|---|---|---|"]
        for name, net in nets.items():
            cells = []
            for part in (net[net.index < SPLIT], net[net.index >= SPLIT]):
                eq = (1 + part).cumprod()
                cells += [f"{part.mean() / part.std() * np.sqrt(252):.2f}", f"{(eq / eq.cummax() - 1).min() * 100:.1f}%"]
            L.append(f"| {name} | " + " | ".join(cells) + " |")
        L.append("")
        if tgt == "qqq":
            L += ["門檻敏感度（QQQ，「百分位 > 門檻 → 曝險降到 X」相對買進持有）：", "",
                  "| 百分位門檻 | 降到 | 夏普 | 最大回撤 | 年化報酬 |", "|---|---|---|---|---|"]
            base = res["買進持有"]
            L.append(f"| （買進持有） | 100% | {base['sharpe']:.2f} | {base['maxdd'] * 100:.1f}% | {base['cagr'] * 100:+.1f}% |")
            for th in (0.8, 0.85, 0.9, 0.95):
                for lvl in (0.75, 0.5):
                    e = (ff.move_pct252 > th).map({True: lvl, False: 1.0})
                    m = metrics(*backtest(ret, e))
                    L.append(f"| {th} | {lvl * 100:.0f}% | {m['sharpe']:.2f} | {m['maxdd'] * 100:.1f}% | {m['cagr'] * 100:+.1f}% |")
            L.append("")
    return L


# ---------------------------------------------------------------- 3. 黃金
def gold(F, start):
    L = ["## 3. 黃金：MOVE 急升 × 實質利率方向", ""]
    path = os.path.join(VOL, "real_yield.csv")
    if not os.path.exists(path):
        return L + ["尚無 `data/vol/real_yield.csv`（需由 Actions 執行 `scripts/fetch_real_yield.py`），本段略過。", ""]
    ry = pd.read_csv(path, parse_dates=["date"]).set_index("date")
    px = load("gld")
    px = px[px.index >= start]
    real = ry.real10.reindex(px.index.union(ry.index)).ffill().reindex(px.index)
    dreal = real.diff(5)
    Fg = F.reindex(px.index)
    B = Fg.move_roc5 > np.log(1.2)
    A = Fg.move_pct252 > 0.9
    hi = px.shift(1).rolling(50).max()
    brk = px > hi  # 當日收盤突破過去 50 日高點
    y1, y5, y20 = fwd_ret(px, 1), fwd_ret(px, 5), fwd_ret(px, 20)
    sets = {
        "全部日子（基準）": pd.Series(True, index=px.index),
        "實質利率 5 日下降": dreal < 0,
        "實質利率 5 日上升": dreal > 0,
        "B：MOVE 5 日 > +20%": B,
        "B 且 實質利率下降": B & (dreal < 0),
        "B 且 實質利率上升": B & (dreal > 0),
        "A'：MOVE 百分位 > 0.9 且 實質利率下降": A & (dreal < 0),
        "A'：MOVE 百分位 > 0.9 且 實質利率上升": A & (dreal > 0),
        "GLD 突破 50 日高點": brk,
        "突破 且 B 且 實質利率下降": brk & B & (dreal < 0),
        "突破 且 B 且 實質利率上升": brk & B & (dreal > 0),
    }
    L += [f"樣本 {px.index[0]:%Y-%m-%d} ～ {px.index[-1]:%Y-%m-%d}；實質利率 = 10 年期 TIPS 殖利率（財政部）。"
          "括號為相對「其他日子」的 Newey-West t 值。", "",
          "| 條件 | 天數 / 事件 | 未來 1 日 | 未來 5 日 | 未來 20 日 | 未來 20 日波動 |", "|---|---|---|---|---|---|"]
    v20 = fwd_vol(px)
    for name, m in sets.items():
        m = m.fillna(False).astype(bool)
        if m.sum() < 15:
            L.append(f"| {name} | {int(m.sum())} | 樣本太少 | | | |")
            continue
        cells = []
        for y, lag in ((y1, 5), (y5, 10), (y20, 40), (v20, 40)):
            ok = y.notna()
            if name.startswith("全部"):
                cells.append(f"{y[ok].mean() * 100:+.2f}%" if y is not v20 else f"{y[ok].mean() * 100:.1f}%")
                continue
            b, t = nw_diff(y[ok], m[ok], lag)
            mean = y[ok & m].mean() * 100
            cells.append(f"{mean:+.2f}%（{t:+.1f}）{star(t)}" if y is not v20 else f"{mean:.1f}%（{t:+.1f}）{star(t)}")
        state = name.startswith(("全部", "實質利率"))  # 持續性狀態，「事件數」沒有意義
        L.append(f"| {name} | {int(m.sum())}{'' if state else f' / {episodes_mask(m).sum()}'} | " + " | ".join(cells) + " |")
    # 底層策略：突破做多（50 日高進場、20 日低出場），比較「放大 / 縮小」規則
    ret = px.pct_change().fillna(0.0)
    state = pd.Series(0.0, index=px.index)
    lo = px.shift(1).rolling(20).min()
    cur = 0.0
    for i in range(len(px)):
        if cur == 0.0 and px.iloc[i] > (hi.iloc[i] if pd.notna(hi.iloc[i]) else np.inf):
            cur = 1.0
        elif cur == 1.0 and px.iloc[i] < (lo.iloc[i] if pd.notna(lo.iloc[i]) else -np.inf):
            cur = 0.0
        state.iloc[i] = cur
    pos = state.shift(1).fillna(0.0)   # 收盤判斷、隔天持有
    amp = B.shift(1).fillna(False) & (dreal.shift(1) < 0)
    shr = B.shift(1).fillna(False) & (dreal.shift(1) > 0)
    naive = B.shift(1).fillna(False)
    variants = {
        "底層策略：50 日突破做多（20 日低出場）": pos,
        "MOVE 急升時放大 1.5 倍（不看實質利率，原始想法）": pos * naive.map({True: 1.5, False: 1.0}),
        "MOVE 急升且實質利率下降 → 放大 1.5 倍": pos * amp.map({True: 1.5, False: 1.0}),
        "MOVE 急升且實質利率上升 → 縮小到 0.5 倍": pos * shr.map({True: 0.5, False: 1.0}),
        "上面兩條合併（放大 + 縮小）": pos * amp.map({True: 1.5, False: 1.0}) * shr.map({True: 0.5, False: 1.0}),
    }
    L += ["", "### 底層策略：GLD 50 日突破做多，測「調整部位」有沒有用", "",
          f"成本 {COST * 1e4:.0f}bp / 單位換手；出場 = 跌破 20 日低點；曝險上限不設（1.5 倍為示意）。", "",
          "| 版本 | 年化報酬 | 年化波動 | 夏普 | 最大回撤 | 平均曝險 | 被調整天數 |", "|---|---|---|---|---|---|---|"]
    for name, e in variants.items():
        net, ex, tu = backtest(ret, e)
        m = metrics(net, ex, tu)
        adj = int(((e != pos) & (pos > 0)).sum())
        L.append(f"| {name} | {m['cagr'] * 100:+.1f}% | {m['vol'] * 100:.1f}% | {m['sharpe']:.2f} | "
                 f"{m['maxdd'] * 100:.1f}% | {m['expo'] * 100:.0f}% | {adj} |")
    L.append("")
    return L


def main():
    raw, f = build()
    F = f.shift(-1)                      # 當天收盤已知的特徵
    start = f.dropna(subset=["move_z20"]).index[0]
    sig = signals(F.dropna(subset=["move_z20"]))
    L = ["# MOVE / VIX 特徵：顯著性、部位回測、黃金", "",
         f"樣本 {start:%Y-%m-%d} ～ {raw.index[-1]:%Y-%m-%d}；MOVE 為 IEF/TLT 選擇權隱含波動率換算的替代值。"
         "產生方式：`python3 scripts/vol_study2.py`。", ""]
    L += significance(F, sig, start)
    L += sizing(f, start)
    L += gold(F, start)
    L += ["## 限制", "",
          "- 14 年樣本、獨立事件 20–65 次；2012–2026 對 QQQ / SPY / GLD 都是長期上升期，條件報酬容易被牛市墊高。",
          "- 只檢定過 6 條規則、4 個標的、少數門檻；沒有做樣本外滾動驗證，門檻本身是事後決定的。",
          "- 回測用 ETF 還原價、現金報酬 0、沒有稅與滑價細節；MNQ 期貨實務上有保證金與展期成本。", ""]
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "README_v2.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
