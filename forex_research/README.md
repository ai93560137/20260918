# 外匯測試（forex_research/README.md）

分支 `claude/forex-data-testing-w4q3m2`：外匯策略測試的數據、規矩、進度都集中在這個資料夾。
從股票研究分支 `claude/gifted-carson-v2tvhw` 合併而來（2026-09-24），研究手冊、股票工具、每日工作流程都在，路徑不變。

**開工先讀（按次序）**：本文件 → FOREX_DATA_CATALOG.md（數據目錄、格式、用法）→ DATA_QC.md（每個商品的品質總表）→
RESEARCH_HANDBOOK.md（方法論鐵律、已判決結論庫——外匯已有判決：八陣圖 on 歐元 ☠️、XAUUSD ✅、ZGL M1 XAUUSD ☠️、EMA／ATR 出場 ☠️）。

## 1. 文件

| 文件 | 內容 |
|---|---|
| `FOREX_DATA_CATALOG.md` | 26 個商品（七大、交叉盤、亞洲、金銀）的來源、格式、一鍵下載、回測用法、各商品注意事項 |
| `DATA_QC.md` | 品質總表（起迄、缺口、尖刺、D1 日界、點差、波幅÷點差入場券、Yahoo／FRED 差）；`data_qc/<PAIR>_qc.md` 逐商品細節 |
| `VERDICTS.md`（待建） | 外匯策略判決追加到這裡（格式同 RESEARCH_HANDBOOK.md 第二節），不要再寫進共用手冊 |

## 2. 程式

| 檔案 | 用途 |
|---|---|
| `scripts/fetch_forex.py` | Dukascopy bi5 → CSV（D1／H1 買賣價、M1 買價、可續抓）+ Yahoo／FRED 第二來源；`--selftest` 不用外網 |
| `scripts/qc_forex.py` | 品質檢查（結構、尖刺、缺口、D1 vs M1 聚合、點差、第二來源、XAUUSD 對券商 MT5）→ `data_qc/`、`DATA_QC.md` |
| `scripts/get_forex_data.py` | 本機一鍵下載 Release `forex-data`；`--merge-m1` 合併 M1 給 `donchian_backtest.py`／`zgl_backtest.py` |
| `.github/workflows/fetch_forex.yml` | Actions：從 Release 還原 → 抓 → 上傳 Release → 品質檢查 → commit 報告（分組並行；只 add 本分組的檔） |
| `donchian_backtest.py`、`zgl_backtest.py` | 現有 M1 引擎（八陣圖通道突破、ZGL），`--broker-offset 0` 直接讀外匯 M1 |

## 3. 數據怎樣來（沙盒連不到外網）

```
GitHub Actions（fetch_forex.yml）抓 Dukascopy／Yahoo／FRED → 上傳 Release forex-data（每商品一個 tar）
                                                          → commit forex_research/data_qc/ 與 DATA_QC.md
本機／沙盒：python3 scripts/get_forex_data.py  → data_forex/<PAIR>/（.gitignore 已排除）
```
- 首次全抓約 20 萬個請求（M1 每日一檔），分四組並行，每組上限 300 分鐘，抓不完會先上傳、下次續抓（`_done.json`）
- 手動觸發：Actions → Forex data → group（majors／crosses／asia／metals／all）

## 4. 外匯測試的常設規矩（沿用股票研究那套）

- 用繁體中文回覆；本分支做外匯（含金銀現貨）；不加歐洲股市
- **任何回測先寫預先登記並 commit**（定義、參數鄰域、隨機對照、門檻、已看過甚麼），才寫程式跑數；只測一次；只修程式錯誤並揭露改前改後數字
- 成本先行（鐵律 2）：先看 DATA_QC.md 的「波幅÷點差」，不及 80 倍的商品不測；回測點差按自己券商（CFD 通常比 Dukascopy 寬 2–5 倍）
- 成交方式要與實盤一致（鐵律 3）：觸價 stop 成交 vs 收盤成交要分開寫死
- 已判決不重測；判決追加到 `forex_research/VERDICTS.md`
- 不 force-push、不 rebase 別人的 commit，合併用 `git pull --no-rebase`；不開 PR 除非使用者要求；commit 不寫模型名
- Telegram token 只在 GitHub Secrets（TG_BOT_TOKEN／TG_CHAT_ID），不寫進程式或對話；不用 `.github/tg_outbox.txt`
- 改每日報告或股票 Actions 工作流程的改動要推回 `claude/gifted-carson-v2tvhw`（那些 Actions 固定 checkout 該分支）；
  `fetch_forex.yml` 則固定在本分支跑

## 5. 進度

| 日期 | 事項 |
|---|---|
| 2026-09-24 | 建立數據管線（抓取、品質檢查、Release、一鍵下載）與目錄文件；首次全抓在 Actions 進行 |
