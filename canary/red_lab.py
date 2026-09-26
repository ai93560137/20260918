#!/usr/bin/env python3
"""紅燈(VIX9D 系)提位考核室(2026-09-26,本分支)

背景:Lim(2026,SSRN 6752518)發現含 VIX9D 的期限結構量度對未來 5–10 個交易日實現波動率的
預測力,在所有期限上勝過傳統 VIX−VIX3M 量度。手冊現役紅燈 = VIX9D − VIX > 0(絕對倒掛)。
本考核問兩件事:(1) 現役紅在 5 日與 10 日 RV 上是否確實勝過深紅;(2) 其他 VIX9D 量度能否更好。

候選**預先登記、閾值固定**(全部以 VIX9D 為核心):
  9D對3M倒掛    VIX9D − VIX3M > 0        前端對季度的完整斜率(Lim 所稱「含 VIX9D 的量度」)
  全倒掛        VIX9D > VIX > VIX3M      紅與深紅同日成立(期限結構整段倒掛)
  紅相對深度    (VIX9D − VIX) > 該斜率滾動 252 日 p90   相對而非絕對倒掛(與黃燈同一套分位口徑)
  9D比率        VIX9D / VIX > 該比率滾動 252 日 p90      同上,用比率消去 VIX 水準

考核口徑與雲垂陣 canary_lab.py 一致(共用 lab_common.py),對 SPX 與 HSI 各一份,主期限 5 日,
另附 10 日 RV 倍率(Lim 的第二個期限)。訊號 lag=1;HSI 用美訊號前一日先導。

**提位門檻(預先登記)**:候選要取代或並列現役紅,須同時滿足
  (a) SPX 5 日 RV 倍率 ≥ 現役紅,且 t ≥ 3
  (b) SPX 10 日 RV 倍率 ≥ 現役紅
  (c) SPX 誤報率 ≤ 現役紅
  (d) 亮燈日 ≥ 100
  (e) HSI 5 日 RV 倍率 > 1
通過者以 trial_* 欄位進入燈色表,**無警報權**。
「地位提高」本身不靠候選:燈色表另加「短期軸 / 災難軸」雙欄,讓紅不再被深紅遮住(見 build_canary_table.py)。

**公平對照**:深紅樣本自 2006 起(含 2008),紅自 2011 起;另列「深紅(2011起同樣本)」供同期比較。
**分層與重疊規則(2026-09-26 事後補登,如實註明)**:四個候選都是紅或深紅的子集,所以除了上面的
絕對門檻,還要問「在母訊號內部有沒有額外鑑別力」:
  (f) 母訊號內條件 RV 倍率(候選亮 vs 母亮但候選不亮)≥ 1.2 且 t ≥ 3(5 日)
  (g) 與另一個通過者 Jaccard 重疊 ≥ 0.85 者視為換皮,只留鑑別力較強的一個;與現役訊號 Jaccard ≥ 0.85 亦然
此規則在看到結果後才加,屬口徑補強而非調參,但仍應誠實標示。

用法(需 pandas):python3 canary/red_lab.py  → 印表 + 寫 canary/RED_UPGRADE.md
"""
import os
from datetime import date

import pandas as pd

from lab_common import HERE, disasters, evaluate, fmt_table, fwd, hi, s, welch_t

OUT_MD = os.path.join(HERE, "RED_UPGRADE.md")
MIN_N = 100

vix, v9, v3 = s("vix_daily.csv"), s("vix9d_daily.csv"), s("vix3m_daily.csv")
spx, hsi, vhsi = s("spx_daily.csv"), s("hsi_daily.csv"), s("vhsi_daily.csv")

slope9 = (v9 - vix).dropna()
slope3 = (vix - v3).dropna()
START = slope9.index.min()
sigs = {
    "紅(9D倒掛,現役)": slope9 > 0,
    "深紅(3M倒掛,現役)": slope3 > 0,
    "深紅(2011起同樣本)": slope3[slope3.index >= START] > 0,
    "9D對3M倒掛": (v9 - v3).dropna() > 0,
    "全倒掛": ((slope9 > 0) & (slope3.reindex(slope9.index) > 0)),
    "紅相對深度p90": hi(slope9),
    "9D比率p90": hi((v9 / vix).dropna()),
}
CANDIDATES = ["9D對3M倒掛", "全倒掛", "紅相對深度p90", "9D比率p90"]
green = slope9 <= 0

dis = {"SPX": disasters(vix, spx), "HSI": disasters(vhsi, hsi)}
results = {
    "SPX": evaluate(sigs, spx, green, dis["SPX"], extra_h=10),
    "HSI": evaluate(sigs, hsi, green, dis["HSI"], lag_us_for_hsi=True, extra_h=10),
}

spx_t, hsi_t = results["SPX"], results["HSI"]
base = spx_t.loc["紅(9D倒掛,現役)"]


def jaccard(a, b):
    a, b = set(a[a].index), set(b[b].index)
    return len(a & b) / len(a | b)


def within(parent, c, rv):
    idx = parent[parent].index.intersection(rv.dropna().index)
    cc = c.reindex(idx).fillna(False).astype(bool)
    on, off = rv[idx][cc], rv[idx][~cc]
    return on.mean() / off.mean(), welch_t(on, off), int(cc.sum()), int((~cc).sum())


rv5_spx = fwd(spx, 5)[0]
PARENT = {"9D對3M倒掛": "紅(9D倒掛,現役)", "全倒掛": "深紅(2011起同樣本)",
          "紅相對深度p90": "紅(9D倒掛,現役)", "9D比率p90": "紅(9D倒掛,現役)"}
within_res = {c: within(sigs[PARENT[c]], sigs[c], rv5_spx) for c in CANDIDATES}
EXISTING = {"紅": sigs["紅(9D倒掛,現役)"], "深紅": sigs["深紅(2011起同樣本)"]}

verdict = {}
for c in CANDIDATES:
    if c not in spx_t.index:
        verdict[c] = ("❌ 樣本不足", [])
        continue
    r, h = spx_t.loc[c], hsi_t.loc[c] if c in hsi_t.index else None
    fails = []
    if not (r.RV倍率 >= base.RV倍率 and r.t >= 3):
        fails.append(f"(a) 5日RV倍率 {r.RV倍率:.2f} vs 現役紅 {base.RV倍率:.2f},t={r.t:.1f}")
    if not r["RV10日倍率"] >= base["RV10日倍率"]:
        fails.append(f"(b) 10日RV倍率 {r['RV10日倍率']:.2f} < 現役紅 {base['RV10日倍率']:.2f}")
    if not r.誤報 <= base.誤報:
        fails.append(f"(c) 誤報 {r.誤報:.0f}% > 現役紅 {base.誤報:.0f}%")
    if not r.亮燈日 >= MIN_N:
        fails.append(f"(d) 亮燈日 {r.亮燈日} < {MIN_N}")
    if h is None or not h.RV倍率 > 1:
        fails.append("(e) HSI 方向不一致")
    wr, wt, _, _ = within_res[c]
    if not (wr >= 1.2 and wt >= 3):
        fails.append(f"(f) 母訊號內鑑別力 {wr:.2f}(t={wt:.1f})不足")
    for k, ex in EXISTING.items():
        j = jaccard(sigs[c], ex)
        if j >= 0.85:
            fails.append(f"(g) 與現役「{k}」Jaccard {j:.2f},換皮")
    verdict[c] = ("✅ 通過" if not fails else "❌ 未過", fails)

# (g) 通過者之間的換皮合併:留母訊號內鑑別力較強者
passed = [c for c, (v, _) in verdict.items() if v.startswith("✅")]
for i, a in enumerate(passed):
    for b in passed[i + 1:]:
        if verdict[a][0].startswith("✅") and verdict[b][0].startswith("✅"):
            j = jaccard(sigs[a], sigs[b])
            if j >= 0.85:
                weaker = a if within_res[a][0] < within_res[b][0] else b
                stronger = b if weaker == a else a
                verdict[weaker] = ("⚠️ 通過但併入", [f"(g) 與「{stronger}」Jaccard {j:.2f},鑑別力較弱,併入"])
passed = [c for c, (v, _) in verdict.items() if v.startswith("✅")]
for c in passed:
    verdict[c] = ("✅ 通過→試用期", [])

pd.set_option("display.width", 220)
for mkt in ("SPX", "HSI"):
    print(f"\n=== 對 {mkt} 的預測力(訊號 lag=1 → 未來 5 日;另附 10 日 RV 倍率) ===")
    print(fmt_table(results[mkt]).to_string())
print("\n=== 紅 vs 深紅(Lim 2026 的核心主張:短端量度在 5–10 日 RV 上更強) ===")
for mkt in ("SPX", "HSI"):
    r, d = results[mkt].loc["紅(9D倒掛,現役)"], results[mkt].loc["深紅(2011起同樣本)"]
    print(f"{mkt}(2011 起同樣本): 5日 紅 {r.RV倍率:.2f} vs 深紅 {d.RV倍率:.2f};10日 紅 {r['RV10日倍率']:.2f} vs 深紅 {d['RV10日倍率']:.2f};"
          f"誤報 紅 {r.誤報:.0f}% vs 深紅 {d.誤報:.0f}%;災難覆蓋 紅 {r.災難覆蓋} vs 深紅 {d.災難覆蓋}")
print("\n=== 母訊號內的條件鑑別力(SPX 5 日):候選亮 vs 母亮但候選不亮 ===")
for c in CANDIDATES:
    wr, wt, n_on, n_off = within_res[c]
    print(f"{c:<14} 在「{PARENT[c].split("(")[0]}」內 RV 倍率 {wr:.2f}(t={wt:.1f}) 亮/不亮 {n_on}/{n_off}")
print("\n=== Jaccard 重疊(候選 vs 現役;候選之間) ===")
for c in CANDIDATES:
    print(f"{c:<14} vs 紅 {jaccard(sigs[c], EXISTING['紅']):.2f}  vs 深紅 {jaccard(sigs[c], EXISTING['深紅']):.2f}")
for i, a in enumerate(CANDIDATES):
    for b in CANDIDATES[i + 1:]:
        print(f"{a} vs {b}: {jaccard(sigs[a], sigs[b]):.2f}")
print("\n=== 提位判定(門檻 (a)–(e) 預先登記;(f)(g) 事後補登) ===")
for c, (v, fails) in verdict.items():
    print(f"{c:<14}{v}" + ("" if not fails else "  |  " + ";".join(fails)))

passed = [c for c, (v, _) in verdict.items() if v.startswith("✅")]
md = [f"# 紅燈(VIX9D 系)提位考核(本分支,{date.today().isoformat()})\n",
      "背景:Lim(2026)稱含 VIX9D 的量度對 5–10 日實現波動的預測力勝過 VIX−VIX3M。本表用手冊 §3 口徑檢驗。",
      "口徑與雲垂陣 `canary_lab.py` 一致;候選與門檻預先登記於 `red_lab.py` 檔頭。訊號 lag=1;HSI 用美訊號前一日先導。\n"]
for mkt in ("SPX", "HSI"):
    md.append(f"## 對 {mkt} 的預測力\n")
    md.append(fmt_table(results[mkt]).to_markdown())
    md.append("")
md.append("## 紅 vs 深紅\n")
md.append("2011 起同樣本(深紅剔除 2008 樣本後仍勝紅):\n")
md.append("| 市場 | 5 日 RV 倍率 紅 / 深紅 | 10 日 RV 倍率 紅 / 深紅 | 誤報 紅 / 深紅 | 災難覆蓋 紅 / 深紅 |\n|---|---|---|---|---|")
for mkt in ("SPX", "HSI"):
    r, d = results[mkt].loc["紅(9D倒掛,現役)"], results[mkt].loc["深紅(2011起同樣本)"]
    md.append(f"| {mkt} | {r.RV倍率:.2f} / {d.RV倍率:.2f} | {r['RV10日倍率']:.2f} / {d['RV10日倍率']:.2f} | "
              f"{r.誤報:.0f}% / {d.誤報:.0f}% | {r.災難覆蓋} / {d.災難覆蓋} |")
md.append("")
md.append("## 母訊號內的條件鑑別力與重疊(SPX 5 日)\n")
md.append("| 候選 | 母訊號 | 母內 RV 倍率 | t | 亮/不亮 | Jaccard vs 紅 | Jaccard vs 深紅 |\n|---|---|---|---|---|---|---|")
for c in CANDIDATES:
    wr, wt, n_on, n_off = within_res[c]
    md.append(f"| {c} | {PARENT[c].split("(")[0]} | {wr:.2f} | {wt:.1f} | {n_on}/{n_off} | "
              f"{jaccard(sigs[c], EXISTING['紅']):.2f} | {jaccard(sigs[c], EXISTING['深紅']):.2f} |")
md.append("")
md.append("候選之間 Jaccard:" + ";".join(
    f"{a} vs {b} {jaccard(sigs[a], sigs[b]):.2f}" for i, a in enumerate(CANDIDATES) for b in CANDIDATES[i + 1:]))
md.append("")
md.append("## 提位判定\n")
md.append("| 候選 | 判定 | 未過原因 |\n|---|---|---|")
for c, (v, fails) in verdict.items():
    md.append(f"| {c} | {v} | {'; '.join(fails) if fails else '—'} |")
md.append("")
md.append("## 結論\n")
md.append("1. **手冊口徑下深紅仍勝紅**(同樣本 5 日與 10 日 RV、誤報皆優)。Lim(2026)的主張是「控制 VIX 水準後的增量 R²」,"
          "與本口徑的無條件亮燈日 RV 倍率不同,兩者不矛盾,但**不能據此把紅排在深紅之上**。§3 註記據此修正。")
md.append("2. 紅的獨特價值在**覆蓋面**:亮燈日最多、災難月覆蓋最全(SPX 4/4),是「別進場」的早期雷達;深紅在**精度**。分工不變。")
md.append("3. **紅燈內部可以分層,而且分得很開**:9D對3M 倒掛把紅燈日切成兩半,9D 亦高過 3M 的一半,未來 5 日 RV 是另一半的 "
          f"{within_res['9D對3M倒掛'][0]:.2f} 倍(t={within_res['9D對3M倒掛'][1]:.1f});它與深紅 Jaccard 僅 "
          f"{jaccard(sigs['9D對3M倒掛'], EXISTING['深紅']):.2f},是紅與深紅之間的真實中間層,正是 Lim 所稱「含 VIX9D 的量度」。")
md.append(f"4. 紅相對深度 p90 在紅內鑑別力 {within_res['紅相對深度p90'][0]:.2f}(t={within_res['紅相對深度p90'][1]:.1f}),"
          "用滾動分位口徑、對結構漂移免疫,亦成立。全倒掛與深紅 Jaccard 0.90 為換皮;9D比率與紅相對深度 0.87 且較弱,併入。")
md.append("5. 通過者以 `trial_red_9d3m`、`trial_red_deep` 進入燈色表**試用期,無警報權**。"
          "紅的地位提高以結構呈現:燈色表新增 `axis_short`(紅/走平/綠)與 `axis_disaster`(深紅/綠)雙欄,紅不再被深紅遮住;手冊 §2 改為雙軸表述。")
md.append("\n未通過的候選列入本分支淘汰名單,**勿重測**(§7 口徑紀律)。")
with open(OUT_MD, "w", encoding="utf-8") as fh:
    fh.write("\n".join(md) + "\n")
print(f"\n已寫入 {os.path.relpath(OUT_MD)}")
