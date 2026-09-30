#!/usr/bin/env python3
# =============================================================================
# MOVE / VIX 波動率特徵：建構與回測（讀 data/vol/*.csv，資料由 scripts/ibkr_vol_export.py 產生）
# -----------------------------------------------------------------------------
# IBKR 沒有 MOVE 指數，改用美債 ETF 選擇權隱含波動率換算成「bp 殖利率波動」當替代：
#   MOVE_proxy ≈ ETF 價格隱含波動率 ÷ 修正存續期間 × 10000
#   （IEF 存續期間取 7.5、TLT 取 16.5，兩者平均）。和 MOVE 同單位：年化 bp。
#
# 特徵（全部用「前一日收盤」可得的資訊，shift(1) 避免偷看未來）：
#   z20 / z60        log(MOVE_proxy) 的 20 / 60 日 Z 分數（原始規則用 20 日）
#   pct252           252 日百分位（不假設常態分布）
#   roc5             5 日對數變化率
#   corr20 / corr60  MOVE_proxy 與 VIX「日對數變化」的滾動相關
#   move_norm        MOVE_proxy ÷（10Y 殖利率 × 100）：以利率水位正規化
#   vix_ts           VIX ÷ VIX3M（> 1 = 期限結構倒掛，股市急性恐慌）
#
# 檢驗的規則（使用者提出的原始版）：
#   A  MOVE z20 > 1.5                           → 降 MNQ 部位 / 暫停均值回歸
#   B  MOVE roc5 > +20%                          → 放大黃金突破部位
#   C  corr20 > 0.6 且 MOVE、VIX 的 z20 都 > 1   → 全局斷路器
# 看觸發後標的的未來報酬、未來已實現波動、最大跌幅，並和全樣本比較；
# 觸發日會連續出現（波動率叢聚），所以另外計算「獨立事件數」（間隔 ≥ 20 個交易日才算新事件）。
#
# 用法：python3 scripts/vol_study.py   → data/vol/study/README.md、features.csv
# 需要 pandas、numpy。
# =============================================================================
import os

import numpy as np
import pandas as pd

VOL = "data/vol"
OUT = "data/vol/study"
DUR = {"ief_iv": 7.5, "tlt_iv": 16.5}
# 回測標的（檔案存在才用）：(檔名, 顯示名稱)
TARGETS = [("tlt", "TLT"), ("qqq", "QQQ（對應 MNQ）"), ("spy", "SPY"), ("gld", "GLD（對應黃金）")]
HORIZONS = [1, 5, 20]


def load(name):
    path = os.path.join(VOL, f"{name}.csv")
    if not os.path.exists(path):
        return None
    s = pd.read_csv(path, parse_dates=["date"]).set_index("date")["close"]
    return s[~s.index.duplicated()].sort_index()


def build():
    iv = pd.concat({k: load(k) / d * 1e4 for k, d in DUR.items()}, axis=1, sort=True)
    move = iv.mean(axis=1).dropna()
    move = move[move.index >= "2012-10-01"]  # IBKR 的 IV 在 2006–2012 有 6 年空窗
    vix, vix3m, tnx = load("vix"), load("vix3m"), load("tnx")
    df = pd.DataFrame({"move": move}).join(
        pd.DataFrame({"vix": vix, "vix3m": vix3m, "y10": tnx / 10}), how="left").ffill()

    lm, lv = np.log(df.move), np.log(df.vix)
    f = pd.DataFrame(index=df.index)
    for w in (20, 60):
        f[f"move_z{w}"] = (lm - lm.rolling(w).mean()) / lm.rolling(w).std()
        f[f"vix_z{w}"] = (lv - lv.rolling(w).mean()) / lv.rolling(w).std()
    f["move_pct252"] = df.move.rolling(252).rank(pct=True)
    f["move_roc5"] = lm.diff(5)
    dm, dv = lm.diff(), lv.diff()
    f["corr20"] = dm.rolling(20).corr(dv)
    f["corr60"] = dm.rolling(60).corr(dv)
    f["move_norm"] = df.move / (df.y10 * 100)
    f["move_norm_pct252"] = f.move_norm.rolling(252).rank(pct=True)
    f["vix_ts"] = df.vix / df.vix3m
    raw = df.copy()
    return raw, f.shift(1)  # 今天的決策只能用昨天收盤的特徵


def episodes(mask, gap=20):
    """觸發日 → 獨立事件數（兩次觸發間隔 ≥ gap 個交易日才算新事件）。"""
    idx = np.flatnonzero(mask.values)
    return int((np.diff(idx) >= gap).sum() + 1) if len(idx) else 0


def forward_stats(px, mask):
    r = np.log(px).diff()
    rows = {}
    for h in HORIZONS:
        fwd = np.log(px.shift(-h) / px)  # 從今天收盤到 h 天後收盤
        rows[f"報酬 {h}日"] = (fwd[mask].mean(), fwd.mean())
    rv = r[::-1].rolling(20).std()[::-1].shift(-1) * np.sqrt(252)  # 未來 20 日已實現波動
    rows["未來20日年化波動"] = (rv[mask].mean(), rv.mean())
    low = px[::-1].rolling(20).min()[::-1].shift(-1)
    dd = low / px - 1
    rows["未來20日最大跌幅"] = (dd[mask].mean(), dd.mean())
    return rows


def rule_masks(f):
    return {
        "A：MOVE z20 > 1.5": f.move_z20 > 1.5,
        "A'：MOVE 252日百分位 > 0.9": f.move_pct252 > 0.9,
        "B：MOVE 5日變化 > +20%": f.move_roc5 > np.log(1.2),
        "C：corr20 > 0.6 且 z20 都 > 1": (f.corr20 > 0.6) & (f.move_z20 > 1) & (f.vix_z20 > 1),
        "C'：corr60 > 0.5 且 z60 都 > 1": (f.corr60 > 0.5) & (f.move_z60 > 1) & (f.vix_z60 > 1),
        "VIX 期限倒掛（VIX/VIX3M > 1）": f.vix_ts > 1,
    }


def pct(x):
    return "—" if pd.isna(x) else f"{x * 100:+.2f}%"


def main():
    os.makedirs(OUT, exist_ok=True)
    raw, f = build()
    f.join(raw).to_csv(os.path.join(OUT, "features.csv"), float_format="%.6g")
    masks = rule_masks(f.dropna(subset=["move_z20"]))
    start, end = f.dropna(subset=["move_z20"]).index[[0, -1]]
    L = ["# MOVE / VIX 波動率特徵回測", "",
         f"樣本：{start:%Y-%m-%d} ～ {end:%Y-%m-%d}。MOVE 以 IEF/TLT 選擇權隱含波動率換算（IBKR 沒有 MOVE 指數）。"
         "特徵一律用前一日收盤值。產生方式：`python3 scripts/vol_study.py`。", "",
         "## 目前狀態", "",
         f"MOVE 替代值 {raw.move.iloc[-1]:.0f} bp、VIX {raw.vix.iloc[-1]:.1f}、10Y {raw.y10.iloc[-1]:.2f}%。", ""]
    last = f.join(raw.shift(1), rsuffix="_raw").iloc[-1]
    L += ["| 特徵 | 值 |", "|---|---|"]
    for k in ("move_z20", "move_z60", "move_pct252", "move_roc5", "corr20", "corr60",
              "move_norm", "move_norm_pct252", "vix_z20", "vix_ts"):
        L.append(f"| {k} | {last[k]:.2f} |")
    L += ["", "## 規則觸發頻率", "", "| 規則 | 觸發天數 | 占比 | 獨立事件數 |", "|---|---|---|---|"]
    for name, m in masks.items():
        L.append(f"| {name} | {int(m.sum())} | {m.mean() * 100:.1f}% | {episodes(m)} |")

    for tgt, label in TARGETS:
        px = load(tgt)
        if px is None:
            continue
        px = px[px.index >= start]
        if len(px) < 250:
            L += ["", f"## {label}：資料只有 {len(px)} 天，略過"]
            continue
        L += ["", f"## 標的：{label}（{px.index[0]:%Y-%m} ～ {px.index[-1]:%Y-%m}）", "",
              "觸發當天收盤後的未來表現；括號內為全樣本平均。", "",
              "| 規則 | 天數 / 事件 | " + " | ".join(f"報酬 {h}日" for h in HORIZONS)
              + " | 未來20日年化波動 | 未來20日最大跌幅 |",
              "|---|---|" + "---|" * (len(HORIZONS) + 2)]
        for name, m in masks.items():
            m = m.reindex(px.index).fillna(False).astype(bool)
            if m.sum() == 0:
                continue
            st = forward_stats(px, m)
            cells = [f"{pct(a)}（{pct(b)}）" for a, b in st.values()]
            L.append(f"| {name} | {int(m.sum())} / {episodes(m)} | " + " | ".join(cells) + " |")
    L += ["", "## 解讀注意", "",
          "- 觸發日高度重疊（波動率叢聚），真正獨立的樣本是「事件數」那一欄，通常只有十幾到幾十次。",
          "- 平均報酬的差異要和事件數一起看；只有少數事件時，一兩次極端行情就能左右結果。",
          "- 這裡只看「條件下的未來分布」，還不是含成本、含部位規則的完整策略回測。", ""]
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
