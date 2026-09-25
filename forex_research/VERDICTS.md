# 外匯策略判決（forex_research/VERDICTS.md）

格式同 RESEARCH_HANDBOOK.md 第二節；外匯判決只寫這裡，不寫進共用手冊。每條附預先登記文件。

| 判決 | 內容 | 依據 |
|---|---|---|
| ☠️ | **蛇蟠陣（八陣圖 sar N=3 觸價反手）on USDJPY**，1.0 pip 零佣金、26 年 HistData M1（2000-05 → 2026-09） | t 1.07、PF 1.09、+5,810 pips／26 年、最大回撤 4,900 pips、前 10 筆佔 134%、2000–2012 t −0.19；鄰域 N=1／2／5 全正但 N=1／2 也只有 PF 1.12–1.15；1.7 pip 時 t 0.88。見 SNAKE_COIL_FOREX_BACKTEST.md 第二部分 |
| 🔍（由 ✅ 降級） | **蛇蟠陣 on XAUUSD 雙向版**：規格書 ✅ 只有 4.1 年券商樣本；獨立樣本外 2009-03 → 2022-08（13.4 年 HistData M1） | 樣本外 t 1.36、PF 1.17、+1,053、前 10 筆 134%、2019 −314；全期 17.5 年 t 2.34、PF 1.37 但空頭腿 PF 1.03 ≈ 0。重疊段與券商數據差 2%（可比）。**引擎點差 bug 修正後**（原本空單回補退點差）券商樣本 +2,659 → +2,609 |
| 🔍 有希望未證實 | **蛇蟠陣 XAUUSD 只做多變體**（規格書 1.3 節 ETF 版 = 雙向版的多頭腿） | 樣本外 t 1.70、PF 1.33、+944；全期 t 2.75、PF 1.77、+3,472、12/18 年正。次要證據（登記時非主檢定），要前向或另一段獨立樣本確認 |
| ☠️（23 個全部） | **蛇蟠陣 on 其餘 23 個外匯商品**（EURUSD 對照、GBPUSD、USDCHF、AUDUSD、USDCAD、NZDUSD、6 個日圓交叉、6 個歐鎊交叉、AUDNZD、AUDCAD、USDHKD、USDSGD、XAGUSD），同規格一次批次掃描，各用 Dukascopy 近 3 年點差 | 0 個達批次門檻（t ≥ 2.5）；最好 GBPJPY t 1.43、XAGUSD 1.28、EURJPY 1.25；t ≤ 0 的 15 個、AUDCAD t −6.1；**全體合併 t −1.55**（25,276 筆）；入場券（波幅÷點差 < 80）在跑前就已擋掉這 23 個，結果印證。見 SNAKE_COIL_FOREX_BACKTEST.md 第四部分（含逐筆明細精度 bug 揭露） |
| 不測 | USDCNH | HistData 沒有 M1（只有 Dukascopy 近 62 天），且離岸人民幣波幅÷點差 18 倍 |

## 多重測試帳本

| 樣本 | 已用次數 | 下一個假設門檻 |
|---|---|---|
| USDJPY M1 2000–2026 | 1（蛇蟠陣 sar N=3；鄰域 N=1／2／5 看過） | t ≥ 2.5 |
| XAUUSD M1 2009–2022 | 1（同上） | t ≥ 2.5 |
| 其餘 23 個商品 M1（HistData 全期） | 1（蛇蟠陣 sar N=3 批次） | t ≥ 2.5，且先過入場券 |

## 工具

- `scripts/snake_coil_run.py`：載入一次 M1、多設定連跑、逐筆明細（省記憶體載入器，900 萬根約 3.5 GB）
- `scripts/snake_coil_eval.py`：逐筆 t、按年、多空腿、集中度、連虧、`--split` 分段、`--cost-shift` 成本敏感度（引擎每筆來回恰扣一次點差，額外成本＝每筆減常數）
- `scripts/get_forex_data.py --merge-m1 <csv> --broker-time`：UTC → 紐約 17:00 日界的券商時間（八陣圖日界）
