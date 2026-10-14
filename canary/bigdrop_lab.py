#!/usr/bin/env python3
"""大跌日價格軸考核室(2026-10-14,IDEAS.md #104,使用者 10-14 指示「登記入 IDEAS.md,再開始考核」)

來源:形態研究工作階段(分支 claude/pattern-research,PR #124,research/pattern_scan/PATTERN_FILTERS.md)
發現 K 線形態名冇方向預測力,波動上真正有用嘅係「大跌日」:期貨 12 隻「大跌日(日報酬 < −1.5 × 之前
20 日標準差)但唔係區間下破／錘頭」之後 5 日波動 +11%(t 7.3,≤2016)／+12%(t 4.5,2017+)。
**注意**:定義同門檻 1.5σ 係形態研究喺期貨樣本睇過結果後揀嘅,ES 已包含在內,所以對 SPX 唔係完全樣本外,證據打折。

問題:「大跌日」可唔可以做金絲雀第四條**價格軸**,同 VIX 期限結構互補?金絲雀只預測波動、唔預測方向。

候選**預先登記、閾值固定**(看結果前寫死,只測一次):
  B1 大跌日σ(主)   SPX 當日 log 報酬 < −1.5 × 之前 20 個交易日 log 報酬標準差(不含當日)
  B2 大跌日2%       SPX 當日 log 報酬 < −2%(固定門檻對照,與 §3「−2% 單日」同一把尺)
  B3 恒指大跌日σ    HSI 自身用 B1 定義,只對 HSI 考核(自家指數,lag=1)
燈只亮訊號當日一日(事件燈,唔延續);lag=1:T 日收盤亮,只對 T+1..T+5 負責。
B1、B2 對 HSI 用美訊號前一日先導(與其他美鳥同口徑)。

樣本:SPX 自 1990-01-02(VIX 起點)起;增量門檻用各現役燈有值的日子(紅自 2011、深紅自 2006、黃各鳥 252 日後)。
口徑全部用 lab_common.py(與 yellow_lab.py / red_lab.py、雲垂陣 canary_lab.py 一致)。

**晉升門檻(預先登記,不事後調整)**:B1、B2 要升為試用欄位須**全部**滿足
  (a) SPX 5 日 RV 倍率 ≥ 1.5 且 t ≥ 3
  (b) SPX 誤報率 ≤ 現役紅(同樣本 2011 起)
  (c) 綠燈下倍率(VIX9D 未倒掛時)≥ 1.2
  (d) **控制全部現役燈**:紅、深紅、黃三者皆滅的日子內,大跌日 vs 非大跌日 5 日 RV 倍率 ≥ 1.2 且 t ≥ 3
  (e) 與紅、深紅、黃(任一)Jaccard 均 < 0.85(否則換皮)
  (f) 亮燈日 ≥ 100
  (g) HSI 方向一致:美訊號 lag=1 對 HSI 5 日 RV 倍率 > 1
  (h) 穩健:SPX ≤2016 與 2017+ 兩段 5 日 RV 倍率都 ≥ 1.2
  B3 只看 HSI:5 日 RV 倍率 ≥ 1.5 且 t ≥ 3、亮燈日 ≥ 100、≤2016 與 2017+ 兩段都 ≥ 1.2;另報與 VHSI p90 的 Jaccard。
通過者以 trial_* 欄位進燈色表,**試用期、無警報權**;B1、B2 都過則只留 (d) 較強者。未過者入淘汰名單,勿重測。

用法(需 pandas + tabulate):python3 canary/bigdrop_lab.py  → 印表 + 寫 canary/BIGDROP_LAB.md
"""
import os
from datetime import date

import numpy as np
import pandas as pd

from lab_common import HERE, disasters, evaluate, fmt_table, fwd, hi, s, welch_t

OUT_MD = os.path.join(HERE, "BIGDROP_LAB.md")
MIN_N, K_SIGMA, LOOKBACK = 100, 1.5, 20
SPLIT = pd.Timestamp("2017-01-01")

vix, v9, v3 = s("vix_daily.csv"), s("vix9d_daily.csv"), s("vix3m_daily.csv")
vvix, move, axvi = s("vvix_daily.csv"), s("move_daily.csv"), s("axvi_daily.csv")
spx, hsi, vhsi = s("spx_daily.csv"), s("hsi_daily.csv"), s("vhsi_daily.csv")
spx = spx[spx.index >= vix.index.min()]


def big_drop_sigma(px):
    r = np.log(px).diff()
    sd = r.rolling(LOOKBACK).std().shift(1)
    ok = sd.notna() & r.notna()
    return (r < -K_SIGMA * sd)[ok]


def big_drop_abs(px, thr=-0.02):
    r = np.log(px).diff().dropna()
    return r < thr


B1, B2, B3 = big_drop_sigma(spx), big_drop_abs(spx), big_drop_sigma(hsi)

slope9, slope3 = (v9 - vix).dropna(), (vix - v3).dropna()
red, deep = slope9 > 0, slope3 > 0
yl = pd.concat([hi(vvix), hi(move), hi(axvi)], axis=1, sort=True)
# 各鳥在自己日曆算分位,對齊到 VIX 日曆後任一亮即亮;三鳥分位都有值之後才計
yellow = (yl.reindex(vix.index).fillna(False).astype(bool).any(axis=1))
yellow = yellow[yellow.index >= max(x.dropna().index.min() for x in
                                    (vvix.rolling(252).quantile(0.9), move.rolling(252).quantile(0.9),
                                     axvi.rolling(252).quantile(0.9)))]
green = slope9 <= 0

sigs = {
    "紅(9D倒掛,現役)": red,
    "深紅(3M倒掛,現役)": deep,
    "黃(任一,現役)": yellow,
    "B1 大跌日σ": B1,
    "B2 大跌日2%": B2,
}
dis_spx, dis_hsi = disasters(vix, spx), disasters(vhsi, hsi)
spx_t = evaluate(sigs, spx, green, dis_spx, extra_h=10)
spx_red11 = evaluate({"紅(9D倒掛,現役)": red, "B1 大跌日σ": B1[B1.index >= slope9.index.min()],
                      "B2 大跌日2%": B2[B2.index >= slope9.index.min()]}, spx, green, dis_spx)
hsi_t = evaluate({k: v for k, v in sigs.items()}, hsi, green, dis_hsi, lag_us_for_hsi=True, extra_h=10)
hsi_own = evaluate({"B3 恒指大跌日σ": B3, "黃VHSI p90(試用,對照)": hi(vhsi)}, hsi, green, dis_hsi, extra_h=10)

rv5 = fwd(spx, 5)[0]
rv5h = fwd(hsi, 5)[0]


def ratio_t(sig, rv, idx):
    idx = idx.intersection(rv.dropna().index).intersection(sig.index)
    g = sig.reindex(idx).fillna(False).astype(bool)
    on, off = rv[idx][g], rv[idx][~g]
    if len(on) < 10:
        return np.nan, np.nan, len(on)
    return on.mean() / off.mean(), welch_t(on, off), len(on)


def jaccard(a, b):
    idx = a.index.intersection(b.index)
    a, b = a.reindex(idx).astype(bool), b.reindex(idx).astype(bool)
    u = (a | b).sum()
    return (a & b).sum() / u if u else np.nan


# (d) 全部現役燈皆滅的日子
common = red.index.intersection(deep.index).intersection(yellow.index)
all_off_idx = common[~(red.reindex(common) | deep.reindex(common) | yellow.reindex(common))]

cand = {"B1 大跌日σ": B1, "B2 大跌日2%": B2}
red11_base = spx_red11.loc["紅(9D倒掛,現役)"]
verdict, detail = {}, {}
for name, sig in cand.items():
    row, h = spx_t.loc[name], hsi_t.loc[name]
    r11 = spx_red11.loc[name]
    d_r, d_t, d_n = ratio_t(sig, rv5, all_off_idx)
    pre_r, pre_t, _ = ratio_t(sig, rv5, sig.index[sig.index < SPLIT])
    post_r, post_t, _ = ratio_t(sig, rv5, sig.index[sig.index >= SPLIT])
    jr, jd, jy = jaccard(sig, red), jaccard(sig, deep), jaccard(sig, yellow)
    fails = []
    if not (row["RV倍率"] >= 1.5 and row["t"] >= 3):
        fails.append(f"(a) RV 倍率 {row['RV倍率']:.2f}(t={row['t']:.1f})")
    if not (r11["誤報"] <= red11_base["誤報"]):
        fails.append(f"(b) 誤報 {r11['誤報']:.0f}% > 紅 {red11_base['誤報']:.0f}%(2011 起同樣本)")
    if not (row["綠燈下倍率"] >= 1.2):
        fails.append(f"(c) 綠燈下倍率 {row['綠燈下倍率']:.2f}" if pd.notna(row["綠燈下倍率"])
                     else "(c) 綠燈下亮燈 ≤ 30 日,算不出(大跌日多數當日已亮紅燈)")
    if not (d_r >= 1.2 and d_t >= 3):
        fails.append(f"(d) 現役燈皆滅時倍率 {d_r:.2f}(t={d_t:.1f},亮 {d_n} 日)" if pd.notna(d_r)
                     else f"(d) 現役燈皆滅時只亮 {d_n} 日,算不出(冇獨立資訊)")
    if max(jr, jd, jy) >= 0.85:
        fails.append(f"(e) Jaccard 紅 {jr:.2f}/深紅 {jd:.2f}/黃 {jy:.2f}")
    if row["亮燈日"] < MIN_N:
        fails.append(f"(f) 亮燈日 {row['亮燈日']}")
    if not (h["RV倍率"] > 1):
        fails.append(f"(g) HSI 倍率 {h['RV倍率']:.2f}")
    if not (pre_r >= 1.2 and post_r >= 1.2):
        fails.append(f"(h) ≤2016 {pre_r:.2f}/2017+ {post_r:.2f}")
    verdict[name] = "✅ 通過" if not fails else "❌ 未過"
    detail[name] = dict(fails=fails, d=(d_r, d_t, d_n), pre=(pre_r, pre_t), post=(post_r, post_t),
                        jac=(jr, jd, jy), r11=r11)

if all(v.startswith("✅") for v in verdict.values()):
    weaker = min(cand, key=lambda k: detail[k]["d"][0])
    verdict[weaker] = "⚠️ 通過但併入"

# B3
b3 = hsi_own.loc["B3 恒指大跌日σ"]
b3_pre = ratio_t(B3, rv5h, B3.index[B3.index < SPLIT])
b3_post = ratio_t(B3, rv5h, B3.index[B3.index >= SPLIT])
b3_j = jaccard(B3, hi(vhsi))
b3_f = []
if not (b3["RV倍率"] >= 1.5 and b3["t"] >= 3):
    b3_f.append(f"RV 倍率 {b3['RV倍率']:.2f}(t={b3['t']:.1f})")
if b3["亮燈日"] < MIN_N:
    b3_f.append(f"亮燈日 {b3['亮燈日']}")
if not (b3_pre[0] >= 1.2 and b3_post[0] >= 1.2):
    b3_f.append(f"≤2016 {b3_pre[0]:.2f}/2017+ {b3_post[0]:.2f}")
verdict["B3 恒指大跌日σ"] = "✅ 通過" if not b3_f else "❌ 未過"

# ---------------------------------------------------------------- 印表
pd.set_option("display.width", 200)
print("=== SPX(1990 起;紅自 2011、深紅自 2006)===")
print(fmt_table(spx_t).to_string())
print("\n=== HSI(美訊號 lag=1)===")
print(fmt_table(hsi_t).to_string())
print("\n=== HSI 自身(lag=1)===")
print(fmt_table(hsi_own).to_string())
for k in cand:
    d = detail[k]
    print(f"\n{k}: {verdict[k]}  現役燈皆滅時 {d['d'][0]:.2f}(t={d['d'][1]:.1f},n={d['d'][2]})"
          f"  ≤2016 {d['pre'][0]:.2f}(t={d['pre'][1]:.1f})  2017+ {d['post'][0]:.2f}(t={d['post'][1]:.1f})"
          f"  Jaccard 紅/深紅/黃 {d['jac'][0]:.2f}/{d['jac'][1]:.2f}/{d['jac'][2]:.2f}  {d['fails']}")
print(f"\nB3: {verdict['B3 恒指大跌日σ']}  ≤2016 {b3_pre[0]:.2f}(t={b3_pre[1]:.1f}) 2017+ {b3_post[0]:.2f}"
      f"(t={b3_post[1]:.1f})  Jaccard vs 黃VHSI {b3_j:.2f}  {b3_f}")

# ---------------------------------------------------------------- 寫 MD
md = [f"# 大跌日價格軸考核(IDEAS.md #104)\n\n產生:`python3 canary/bigdrop_lab.py`,{date.today().isoformat()}。"
      "候選與門檻預先登記於腳本檔頭(本檔數字由腳本產生,勿手改)。\n",
      f"數據:SPX {spx.index.min().date()}→{spx.index.max().date()};HSI {hsi.index.min().date()}→{hsi.index.max().date()}。"
      "口徑 `lab_common.py`(5 日 RV 倍率、Welch t、−2% 單日提升、誤報 = 亮燈但其後 RV 低於中位、綠燈下倍率 = VIX9D 未倒掛時、"
      "災難月 = 月度對沖短跨式虧損 > 1× 權利金,進場前 6 個交易日內亮過即算覆蓋)。lag=1。\n",
      "**證據打折**:B1 的 1.5σ／20 日定義來自形態研究喺期貨(含 ES)睇過結果後揀,對 SPX 唔係完全樣本外。\n",
      "## 判決\n", "| 候選 | 判決 | 未過門檻 |\n|---|---|---|"]
for k in cand:
    md.append(f"| {k} | {verdict[k]} | {';'.join(detail[k]['fails']) or '—'} |")
md.append(f"| B3 恒指大跌日σ | {verdict['B3 恒指大跌日σ']} | {';'.join(b3_f) or '—'} |")
md += ["\n## SPX(5 日;另附 10 日 RV 倍率)\n", fmt_table(spx_t).to_markdown(),
       "\n紅自 2011、深紅自 2006,樣本期不同;(b) 用 2011 起同樣本比:\n", fmt_table(spx_red11).to_markdown(),
       "\n## HSI(美訊號前一日先導)\n", fmt_table(hsi_t).to_markdown(),
       "\n## HSI 自身大跌日(lag=1)\n", fmt_table(hsi_own).to_markdown(),
       "\n## 增量、穩健、重疊(SPX 5 日)\n",
       "| 候選 | (d) 現役燈皆滅時倍率 | t | 亮燈日 | ≤2016 倍率 | 2017+ 倍率 | Jaccard 紅 | 深紅 | 黃 |\n|---|---|---|---|---|---|---|---|---|"]
for k in cand:
    d = detail[k]
    md.append(f"| {k} | {d['d'][0]:.2f} | {d['d'][1]:.1f} | {d['d'][2]} | {d['pre'][0]:.2f}(t={d['pre'][1]:.1f}) | "
              f"{d['post'][0]:.2f}(t={d['post'][1]:.1f}) | {d['jac'][0]:.2f} | {d['jac'][1]:.2f} | {d['jac'][2]:.2f} |")
md.append(f"\nB3 恒指:≤2016 {b3_pre[0]:.2f}(t={b3_pre[1]:.1f})、2017+ {b3_post[0]:.2f}(t={b3_post[1]:.1f});"
          f"與黃VHSI p90 Jaccard {b3_j:.2f}。\n")
open(OUT_MD, "w").write("\n".join(md) + "\n")
print(f"\n寫入 {OUT_MD}")
