#!/usr/bin/env python3
"""黃燈升級考核室(2026-09-26,本分支)

現役黃燈 = VVIX / MOVE / AXVI 任一 > 自身滾動 252 日 p90(只看「水準」)。
升級方向(文獻:Yoon-Ruan-Zhang 2022 指出 vol-of-vol 的資訊不只在水準也在斜率;
Park 2015 / Huang et al. 2019 指出 VVIX 獨立於 VIX 被定價),候選**預先登記、閾值固定**:

  強度類
    黃×2        三隻黃鳥至少兩隻同時亮
    黃×3        三隻同時亮
    深黃VVIX    VVIX > 滾動 252 日 p95(比現役 p90 更嚴一級,對應紅→深紅的分層)
  斜率類(時間斜率,不是行權價斜率;我們沒有 VIX 期權曲面)
    VVIX斜率    VVIX 5 日變化 > 該變化的滾動 252 日 p90
    MOVE斜率    MOVE 5 日變化 > 該變化的滾動 252 日 p90
  相對類
    VVIX/VIX    VVIX ÷ VIX > 該比率的滾動 252 日 p90(「對恐懼的恐懼」相對於恐懼本身)

考核口徑與雲垂陣 tradingview/canary_lab.py 完全一致(共用 lab_common.py;對 SPX 與 HSI 各一份):
  1. 亮燈日未來 5 天 RV vs 不亮燈(倍率)+ Welch t 值
  2. 亮燈日 5 天內見 −2% 單日機率 vs 無條件(提升)+ 誤報率(亮燈但未來 RV 低於中位)
  3. 增量:VIX9D 未倒掛(綠)時亮燈,是否仍有預測力
  4. 災難月覆蓋:進場前 6 個交易日內曾亮燈幾個(災難月 = 月度對沖短跨式虧損 > 1× 權利金)
  訊號一律 lag=1:T 日收盤算出的燈,只對 T+1 起的 5 天負責。HSI 用美訊號前一日先導。

**晉升門檻(預先登記,不事後調整)**:同時滿足
  (a) SPX 的 RV 倍率 ≥ 現役黃(任一)的 RV 倍率,且 t ≥ 3
  (b) SPX 誤報率 ≤ 現役黃
  (c) SPX 綠燈下 RV 倍率 ≥ 1.2(要有紅燈以外的獨立資訊)
  (d) 樣本 ≥ 100 個亮燈日
  (e) HSI 方向一致(RV 倍率 > 1)
通過者進入「試用期」欄位(trial_*),**無警報權**,待雲垂陣採納才升為正式黃燈分層。

用法(需 pandas):python3 canary/yellow_lab.py  → 印表 + 寫 canary/YELLOW_UPGRADE.md
"""
import os
from datetime import date

import pandas as pd

from lab_common import HERE, disasters, evaluate, fmt_table, hi, s

OUT_MD = os.path.join(HERE, "YELLOW_UPGRADE.md")
Q_DEEP, MIN_N = 0.95, 100

# ---------------------------------------------------------------- 資料與候選
vix, v9, v3 = s("vix_daily.csv"), s("vix9d_daily.csv"), s("vix3m_daily.csv")
vvix, move, axvi = s("vvix_daily.csv"), s("move_daily.csv"), s("axvi_daily.csv")
spx, hsi, vhsi = s("spx_daily.csv"), s("hsi_daily.csv"), s("vhsi_daily.csv")

y_vvix, y_move, y_axvi = hi(vvix), hi(move), hi(axvi)
ycount = (pd.concat([y_vvix, y_move, y_axvi], axis=1, sort=True).astype(float)
          .reindex(vix.index).sum(axis=1, min_count=1))

sigs = {
    # 現役(對照)
    "紅(9D倒掛)": (v9 - vix).dropna() > 0,
    "深紅(3M倒掛)": (vix - v3).dropna() > 0,
    "黃VVIX(現役)": y_vvix,
    "黃MOVE(現役)": y_move,
    "黃AXVI(現役)": y_axvi,
    "黃任一(現役)": ycount >= 1,
    # 候選:強度
    "黃×2": ycount >= 2,
    "黃×3": ycount >= 3,
    "深黃VVIX p95": hi(vvix, Q_DEEP),
    # 候選:斜率
    "VVIX斜率5日": hi(vvix.diff(5)),
    "MOVE斜率5日": hi(move.diff(5)),
    # 候選:相對
    "VVIX/VIX比": hi((vvix / vix).dropna()),
}
CANDIDATES = ["黃×2", "黃×3", "深黃VVIX p95", "VVIX斜率5日", "MOVE斜率5日", "VVIX/VIX比"]
green = (v9 - vix).dropna() <= 0

# ---------------------------------------------------------------- 考核
dis = {"SPX": disasters(vix, spx), "HSI": disasters(vhsi, hsi)}
results = {
    "SPX": evaluate(sigs, spx, green, dis["SPX"]),
    "HSI": evaluate(sigs, hsi, green, dis["HSI"], lag_us_for_hsi=True),
}

# ---------------------------------------------------------------- 晉升判定(預先登記門檻)
spx_t, hsi_t = results["SPX"], results["HSI"]
base = spx_t.loc["黃任一(現役)"]
verdict = {}
for c in CANDIDATES:
    if c not in spx_t.index:
        verdict[c] = ("❌ 樣本不足", [])
        continue
    r, h = spx_t.loc[c], hsi_t.loc[c] if c in hsi_t.index else None
    fails = []
    if not (r.RV倍率 >= base.RV倍率 and r.t >= 3):
        fails.append(f"(a) RV倍率 {r.RV倍率:.2f} vs 現役 {base.RV倍率:.2f},t={r.t:.1f}")
    if not r.誤報 <= base.誤報:
        fails.append(f"(b) 誤報 {r.誤報:.0f}% > 現役 {base.誤報:.0f}%")
    if not (pd.notna(r.綠燈下倍率) and r.綠燈下倍率 >= 1.2):
        fails.append(f"(c) 綠燈下倍率 {r.綠燈下倍率:.2f} < 1.2")
    if not r.亮燈日 >= MIN_N:
        fails.append(f"(d) 亮燈日 {r.亮燈日} < {MIN_N}")
    if h is None or not h.RV倍率 > 1:
        fails.append("(e) HSI 方向不一致")
    verdict[c] = ("✅ 通過→試用期" if not fails else "❌ 未過", fails)

# ---------------------------------------------------------------- 輸出
pd.set_option("display.width", 200)
for mkt in ("SPX", "HSI"):
    print(f"\n=== 對 {mkt} 的預測力(訊號 lag=1 → 未來 5 個交易日) ===")
    print(fmt_table(results[mkt]).to_string())
print("\n=== 晉升判定(門檻見檔頭,預先登記) ===")
for c, (v, fails) in verdict.items():
    print(f"{c:<14}{v}" + ("" if not fails else "  |  " + ";".join(fails)))

passed = [c for c, (v, _) in verdict.items() if v.startswith("✅")]

md = [f"# 黃燈升級考核(本分支,{date.today().isoformat()})\n",
      "口徑與雲垂陣 `canary_lab.py` 一致;候選與晉升門檻預先登記於 `yellow_lab.py` 檔頭,閾值固定不調。",
      "訊號 lag=1;HSI 用美訊號前一日先導。「災難月」= 月度對沖短跨式虧損 > 1× 權利金。\n"]
for mkt in ("SPX", "HSI"):
    md.append(f"## 對 {mkt} 的預測力\n")
    md.append(fmt_table(results[mkt]).to_markdown())
    md.append("")
md.append("## 晉升判定\n")
md.append("| 候選 | 判定 | 未過原因 |\n|---|---|---|")
for c, (v, fails) in verdict.items():
    md.append(f"| {c} | {v} | {'; '.join(fails) if fails else '—'} |")
md.append("")
if passed:
    md.append("通過者以 `trial_*` 欄位進入 `canary_daily.csv` **試用期,無警報權**:" + "、".join(passed))
else:
    md.append("**無候選通過。** 黃燈維持現役定義;`yellow_count`(0–3)僅作描述欄位加入燈色表,不具警報權。")
md.append("\n未通過的候選列入本分支淘汰名單,**勿重測**(§7 口徑紀律)。")
with open(OUT_MD, "w", encoding="utf-8") as fh:
    fh.write("\n".join(md) + "\n")
print(f"\n已寫入 {os.path.relpath(OUT_MD)}")
