# 股票研究：策略、數據、執行（stock_research/README.md）

本分支（`claude/gifted-carson-v2tvhw`）2026-09 股票研究的**策略定義、數據、執行方法**都集中在這個資料夾；**判決另放在 VERDICTS.md**。
2026-09-24 從 RESEARCH_HANDBOOK.md 第四節（工具索引）和第七節抽出，共用手冊只留一行指引，避免影響其他分支。
**程式檔路徑不變**（仍在倉庫根目錄和 `scripts/`），因為每日工作流程、Actions 和其他分支都按原路徑讀取。

## 1. 文件

| 文件 | 內容 |
|---|---|
| `NEW_SESSION_PROMPT.md` | **新 session 開場指示**（整段複製貼上即可接手） |
| `STOCK_RESEARCH_HANDOFF.md` | **交接總結**：一句話結論、Minervini 狀態、方法論教訓、下一步選項（新 session 先讀） |
| `VERDICTS.md` | 全部判決、策略 × 市場矩陣、多重測試帳本 |
| `MARKET_DATA_CATALOG.md` | 9 個市場數據目錄、注意事項、一鍵下載 |
| `NEWHIGH_BACKTEST.md` | 新高連續天數入場（H4／H5a／H5b）預先登記與結果 |
| `VCP_BACKTEST.md` | VCP 定義（v1／v2）與指數成分股版 |
| `VCP_FULLMARKET_BACKTEST.md` | VCP 全市場：品質檢查、XV、五日 EMA、Minervini 忠實版 |
| `AIBA_PPP_BACKTEST.md` | 相場師朗 PPP 中的下半身（逆下半身／五日 EMA 出場） |
| `OOS_VALIDATION.md` | 樣本外兩輪：台韓澳、加印新 |
| `EXPECTANCY_REVIEW.md` | 期望值／RRR／總回報覆核（描述性） |
| `DISCIPLINE_BACKTEST.md` | 「紀律本身」：剛進入趨勢模板＋大市過濾＋Minervini 出場（不看 VCP 形態），9 國一次的預先登記與結果 |
| `DISCIPLINE_RULES.md` | 上述回測用到的全部規則一覽（宇宙、趨勢模板、大市過濾、出場紀律、六個組合、鄰域、合併檢定、門檻、程序規則、程式對應；不含結果） |

## 2. 程式與輸出（路徑不變）

| 資產 | 用途 |
|---|---|
| `scripts/daily_topdown.py` → `analysis/` | **每日由上而下分析**（描述性篩選，規則寫死）：三地指數 ETF 動能排名（不篩選）→ 成分股昨天收市在 200 日線上 → 3/6/9/12 個月新高 → 按板塊統計檔數；每天名單記入 `analysis/topdown_log.csv` 做樣本外追蹤；`daily_topdown.yml` 美股數據更新後自動跑 + Telegram（約 08:00-09:30 HKT）|
| `newhigh_backtest.py` → `research/newhigh/` | 新高連續天數入場回測引擎（港／美／日 PIT、日曆時間等權、X1/X2/X3 出場、同日隨機對照；`--validate` 跟每日名單逐檔比對訊號）|
| `vcp.py` + `vcp_backtest.py` → `research/vcp/` | VCP 偵測（趨勢模板、碎形擺動點、收縮、量縮、樞紐點；每日篩選共用）與回測（同新高那套組合／門檻；隨機對照 = 同日趨勢模板股、同停損距離）|
| `vcp_minervini.py` + `scripts/{build_full_pools,fetch_full_market,qc_full_market,verify_trades}.py` → `research/vcp_full/` | 全市場（成交額前 N）版：候選池、yfinance 全市場日線（不進 git，Actions 快取 + Release 備份）、4 層品質檢查、逐筆交易核對；Minervini 忠實版（樞紐點盤中成交、大市過濾、固定止損／保本／50 日線出場）|
| `aiba_ppp.py` + `.github/workflows/aiba_verify.yml` → `research/aiba_ppp/` | 相場流 PPP／下半身／逆下半身（還原 K 線、SMA）全市場回測；`--trades-only` 先出逐筆明細不看績效、抽樣交給 Actions 核對第二來源 |
| `discipline_backtest.py` → `research/discipline/` | 「紀律本身」回測（D0 剛進入趨勢模板＋大市過濾＋Minervini 出場；R 隨機 200 日線上非模板股對照；D1 無大市過濾、D2 只持 252 日、D3 X2 出場；M Minervini 重跑並列；`--check-sim` 向量化出場逐筆比對、`--pool` 9 市場合併檢定）|
| `scripts/expectancy_report.py` → `research/expectancy/` | 已判決策略預設格的期望值、RRR、獲利因子、累計／年化／MDD vs ETF（一個市場一次重建數據，全部策略共用）|
| `scripts/get_market_data.py` + `MARKET_DATA_CATALOG.md` | 一鍵下載 9 個市場日線並重建品質排除檔；數據目錄、注意事項、策略×市場已驗證矩陣 |
| `oos_backtest.py` + `scripts/build_oos_pools.py` + `.github/workflows/oos_fullmarket.yml` → `research/oos/` | 樣本外新市場（台 .TW/.TWO、韓 .KS/.KQ、澳 .AX）候選池、抓數據（Release `oos-data`）、凍結規格回測、漲停鎖死跳過、三市場合併 alpha 檢定 |

## 3. 怎樣拿到數據（雲端 session／其他分支）

**最簡單**：`python3 scripts/get_market_data.py`（9 國一鍵下載＋重建品質排除檔，見 MARKET_DATA_CATALOG.md）。以下是手動做法：
```bash
git fetch origin claude/gifted-carson-v2tvhw
git merge --no-edit origin/claude/gifted-carson-v2tvhw      # 或只 checkout 需要的檔（見 7.3）
for m in hk jp us; do
  curl -sL -o /tmp/$m.tar https://github.com/ai93560137/20260918/releases/download/fullmarket-data/$m.tar
  tar -xf /tmp/$m.tar                                       # → data_full/<m>/
  python3 scripts/qc_full_market.py --market $m --no-network   # 重建 _qc_exclude.txt／_qc_zombie.json（已驗證與原版逐字相同）
done
git checkout -- research/vcp_full/                          # 上一步會改寫 <m>_qc.md，還原成已 commit 版
```
- Release 的 tar **不含**品質排除檔，一定要跑上面的 `qc_full_market.py --no-network`（結構檢查，不用外網）
- **Actions 快取按分支隔離，其他分支拿不到**；GitHub Actions 裡用 `gh release download fullmarket-data -p "$M.tar"`
- 更新數據：手動觸發 `vcp_fullmarket.yml`（`backtest=false`），會補抓、重傳 Release（該 workflow 固定 checkout 本分支）
- 已確認雲端沙盒可以直接下載 Release（2026-09-23 實測 hk.tar 100 MB 成功）


## 4. 工具（程式都在本分支）
| 檔案 | 用途 |
|---|---|
| `newhigh_backtest.py` | 引擎：`MarketData(m, pool=..., loader=load_full(m), top_n=N, cost=c)` → 日曆 × 股票矩陣（`adj`、`aopen`、`member` 每日成交額前 N 宇宙、`next_px`）；`trades_from_events(ev, rule)`、`exit_index`、`portfolio`（日曆時間等權）、`evaluate`（CAPM alpha t vs ETF、相對等權 t、前後段、年化、MDD、按年）|
| `vcp_backtest.py` | `FULL_TOP_N`（港 500／日 1000／美 1500）、`FULL_COST`（每邊 港 25／日 15／美 10 bps）；`VCPData`（趨勢模板 + RS 百分位矩陣 `tt`）|
| `vcp.py` | 趨勢模板、碎形擺動點、VCP 收縮／樞紐點（每日篩選共用）|
| `vcp_minervini.py` | 樞紐點盤中成交、大市 50/200 日線過濾、固定止損／保本／50 日線出場的模擬器（逐日 K 線）|
| `aiba_ppp.py` | 相場流 `features()`：PPP（20／60／100）、下半身（比例可調）、逆下半身、跌破 60 日線；自訂出場規則掛進引擎的範例（`m.exitc[...]`、`m.next_exit[...]`）|
| `scripts/build_full_pools.py`、`fetch_full_market.py` | 候選池、yfinance 抓取（收市 + 30 分鐘前的半根會丟掉）|
| `scripts/qc_full_market.py` | 結構檢查（重複、還原比例、高低價矛盾、尖刺、殭屍段）+ 對指數版 + 最新一日第二來源 |
| `scripts/verify_trades.py` | 逐筆交易對第二來源：`--src <明細.json> --sample 300 --split-ok --out-dir <資料夾>` |
| `.github/workflows/vcp_fullmarket.yml`、`aiba_verify.yml` | 抓數據＋回測全流程；只做外網核對的輕量版（push 抽樣明細就自動跑）|


## 5. 新假設的標準流程（照做，兩輪已驗證可行）
1. 讀第二節判決庫 → 寫 `<名稱>_BACKTEST.md` 預先登記（定義、鄰域 3×3、隨機對照、門檻、已看過甚麼）→ **先 commit**
2. 寫程式；用 `--inspect`／`--trades-only` 只看交易機制、手算一兩筆，**不看績效**
3. 預設格抽 300 筆逐筆核對：港股本機（內部一致性）；**日美要外網 → 在 Actions 跑**（雲端沙盒連不到 Nasdaq／Yahoo!ファイナンス）
4. 三地各正式跑一次（`--random 200`）→ 結果寫回文件、判決追加到第二節


## 6. 已踩過的坑
- `pgrep -f "<腳本名>"` 會配對到自己的等待迴圈 → 用 `pgrep -f "^python3 <腳本>"` 或記 PID
- 日股第二來源（Yahoo!ファイナンス）歷史價**不按拆股還原** → 三個比例差整數倍不是錯誤（`--split-ok`）；GungHo 3765.T 曾因此被誤剔
- 股票偶有日曆沒有的交易日（港股 2016-10-21）→ 出場日要對到下一個日曆日
- 樣本最後一天停牌的持倉沒有收市價 → 逐筆統計要去 NaN（組合報酬不受影響）
- Actions 多市場並行 commit 只 add 本市場的檔，否則會把別的市場檔案改回舊版
- 美股開市中抓到的是未收市半根 → `fetch_full_market.py` 已按當地收市 + 30 分鐘截斷


