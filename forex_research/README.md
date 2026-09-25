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
| `VERDICTS.md` | 外匯策略判決（格式同 RESEARCH_HANDBOOK.md 第二節）；不要再寫進共用手冊 |
| `FX_COST_MODEL.md` | 外匯 swap 加價與點差的公開證據（IBKR 分層、Saxo 等級、CME 期貨路徑）與各口徑對策略的影響；之後登記的成本從這裡取 |
| `IBKR_DATA_REQUEST.md` | 給雲垂分支（GCP VM 上的 IB Gateway）的數據需求：CME 外匯期貨隱含波動歷史（波動溢價用）、IDEALPRO 5 分鐘 BID_ASK（日內點差用）；腳本 `scripts/ib_fx_history.py` |
| `FX_COT_OOS_BACKTEST.md` | CFTC 持倉反向再登記：F1 1990–2003 樣本外（FRED 價格）t −1.52、F3 週頻 1.41 → **☠️ 路線關閉** |
| `FX_NEW_INFO_BACKTEST.md` | 路線 B 新資訊：央行利率路徑、VIX>25 過濾利差、CFTC 持倉反向（G7、機構／零售並列）——**全部 ☠️**（t −1.0／0.21／0.77） |
| `FX_EM_UNIVERSE_BACKTEST.md` | 路線 A 新宇宙：G7＋MXN ZAR TRY PLN SEK HUF NOK（機械剔除規則、動態 k_t、兩級 swap 加價）利差／價值／三因子——**全部 ☠️**（機構 t −0.51／−0.82／−1.30；TRY 一個貨幣 −49%） |
| `FX_THREE_FACTOR_BACKTEST.md` | 三因子籃子（利差＋BIS 實質有效匯率價值＋橫截面動量）：預先登記、機構 0.25%／零售 1.25% 兩個口徑並列、隨機排序對照、**全部 ☠️**（機構 t 1.09、零售 0.04；價值單獨 0.04） |
| `FX_TREND_CARRY_BACKTEST.md` | 外匯長週期趨勢（TSMOM、海龜）與利差（G7 排序、利差+趨勢過濾）籃子：預先登記、四個主檢定全 ☠️、swap 加價是生死關鍵 |
| `SNAKE_COIL_FOREX_BACKTEST.md` | 蛇蟠陣 on 外匯：成本入場券（26 商品）、USDJPY 測試、XAUUSD 2009–2022 樣本外、引擎點差 bug 揭露與前後數字 |

## 2. 程式

| 檔案 | 用途 |
|---|---|
| `scripts/fetch_forex.py` | HistData M1 zip + Dukascopy bi5（D1／H1 買賣價、近期 M1）→ CSV（UTC、可續抓、去填充）+ Yahoo／FRED 第二來源；`--selftest` 不用外網 |
| `scripts/qc_forex.py` | 品質檢查（結構、尖刺、缺口、D1 vs M1 聚合、HistData vs Dukascopy 交叉核對、點差、第二來源、XAUUSD 對券商 MT5）→ `data_qc/`、`DATA_QC.md` |
| `scripts/fetch_fx_rates.py` | Actions（`fetch_fx_rates.yml`）抓 FRED：24 個貨幣的三個月利率 → `data_forex_rates/`、BIS REER → `reer/`、OECD 十年期殖利率／美國 2 年 10 年／VIX EVZ VXEEM → `info/`（小檔，進 git） |
| `scripts/fetch_cot.py` | 同一工作流程抓 CFTC legacy COT（1986 起）貨幣期貨 → `data_forex_rates/cot/cot_currencies.csv` |
| `scripts/fx_forward_signals.py` + `fx_forward.yml` | 路線 C 前向記錄：每月 2 日補七大數據、記錄上月底訊號（利差 top2／top3、三因子）、上月模型損益、CME 期貨基差 vs 模型利差 → `forex_research/forward/` |
| `fx_basket_backtest.py` | 日線籃子引擎：TSMOM、海龜、利差、`factor`（三因子橫截面、`--random` 隨機排序對照）；`--inspect` 只看機制 |
| `scripts/get_forex_data.py` | 本機一鍵下載 Release `forex-data`；`--merge-m1` 合併 M1 給 `donchian_backtest.py`／`zgl_backtest.py` |
| `.github/workflows/fetch_forex.yml` | Actions：從 Release 還原 → 抓 → 上傳 Release → 品質檢查 → commit 報告（分組並行；只 add 本分組的檔） |
| `donchian_backtest.py`、`zgl_backtest.py` | 現有 M1 引擎（八陣圖通道突破、ZGL），`--broker-offset 0` 直接讀外匯 M1 |

## 3. 數據怎樣來（沙盒連不到外網）

```
GitHub Actions（fetch_forex.yml）抓 HistData／Dukascopy／Yahoo／FRED → 上傳 Release forex-data（每商品一個 tar）
                                                          → commit forex_research/data_qc/ 與 DATA_QC.md
本機／沙盒：python3 scripts/get_forex_data.py  → data_forex/<PAIR>/（.gitignore 已排除）
```
- 每商品約 35 個 HistData zip + 約 650 個 Dukascopy 請求；五組、同時最多兩組，每組上限 300 分鐘，抓不完會先上傳、下次續抓（`_done.json`）
- 手動觸發：Actions → Forex data → group（majors／jpy／eur／other／metals／all）
- 踩過的坑（2026-09-24）：Dukascopy 對 Actions 的 IP 限流很兇（M1 每日一檔 15 萬個請求的抓法放棄，M1 改 HistData）；
  Dukascopy 原檔的週末／假期／上市前是平價零量的填充 K 線（已過濾）；Dukascopy 沒有當年 D1／當月 H1 檔（改聚合）；
  進行中的 Actions job 讀不到日誌，要等它結束；HistData 網站說時間是 EST 無夏令，實測是紐約當地時間含夏令（交叉核對抓出來的）

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
| 2026-09-25（七） | **路線 A 寬宇宙全部 ☠️**：14 個貨幣利差 t −0.51、價值 −0.82、三因子 −1.30（機構口徑），零售更差，加價 0% 仍負；只含新增貨幣、剔除 TRY 都救不回。Dukascopy 新興市場數據：BRL INR KRW 沒有、CZK RON ILS THB 2016 起、ZAR 2003 整段錯、限流要抓三次。**三條路走完：A、B 全 ☠️，C 只是前向記錄** |
| 2026-09-25（六） | 使用者批准 COT 反向再登記：獨立樣本 1990–2003（FRED H.10 價格、G7＋MXN）**t −1.52**、週頻 2003–2026 週報酬 t 1.41 → 合併 ☠️，COT 路線關閉。發現並修正 COT 載入的合約對齊問題（E3 0.77 → 0.78）。引擎新增 FRED 單一價來源、日曆窗 z、週頻調倉。em1 組六個商品被 Dukascopy 限流誤判為無數據，探測已改為分清 404 與限流，重抓中 |
| 2026-09-25（五） | 使用者要求三條路都做。**路線 B 新資訊三檢定全部 ☠️**（利率 6 個月變動 t −1.0、VIX>25 過濾利差 0.21〔不過濾 0.81〕、COT 156 週 z 反向 0.77）；帳本第 6 次，下一個假設必須是新宇宙或新頻率。路線 A 已登記（`FX_EM_UNIVERSE_BACKTEST.md`），15 個新興市場／其他 G10 對由 Actions 抓 Dukascopy D1／H1 中；路線 C 前向記錄工作流程上線（每月 2 日）。數據管線擴充：24 個貨幣利率、REER、殖利率、VIX、COT |
| 2026-09-25（四） | **三因子籃子（利差＋BIS REER 價值＋12 個月橫截面動量，G7 對美元，2003–2026）全部 ☠️**：機構口徑（加價 0.25%）t 1.09、零售口徑（1.25%）0.04、價值單獨 0.04／−1.0、橫截面動量單獨 −1.21／−2.2；隨機排序對照 500 次的 97.5 百分位 1.17，主檢定沒過；加價 0% 也只有 1.35。REER 數據由 Actions 抓（`data_forex_rates/reer/`）。**G7 對美元月頻橫截面路線到此用盡**，帳本門檻升到 t ≥ 3 |
| 2026-09-25（三） | 長週期趨勢與利差籃子（四個主檢定，21 對／G7，2003–2026）**全部 ☠️**：TSMOM t −0.69、海龜 −1.61、利差 0.11、利差+趨勢 −0.22；純價格動量 t 0.02；點差 1–3 倍不影響、swap 加價 0→2% 決定生死。新工具 `fx_basket_backtest.py`、利率數據 `data_forex_rates/`（Actions 抓 FRED） |
| 2026-09-25（續） | 使用者要求續測其餘外匯：23 個商品同規格批次掃描 **全部 ☠️**（0 個達 t ≥ 2.5，合併 t −1.55），入場券結論成立；發現並修正引擎第二個 bug（`--trades` 明細兩位小數令 5 位報價外匯逐筆統計失真）；兩個引擎修正與更正後的數字已推回 `claude/gifted-carson-v2tvhw`（規格書第四節、DONCHIAN_BACKTEST.md） |
| 2026-09-25 | 蛇蟠陣外匯測試：入場券 26 商品只有 USDJPY 勉強過（零佣金 ≤ 1.2 pip）；USDJPY ☠️（t 1.07）；XAUUSD 樣本外 13.4 年 t 1.36 → 雙向版由 ✅ 降 🔍，只做多變體 🔍（t 1.70／全期 2.75）；**發現並修正 `donchian_backtest.py` 空單回補點差方向 bug**（原本整段回測幾乎沒扣點差），前後數字見登記文件 |
| 2026-09-24 | 建立數據管線（抓取、品質檢查、Release、一鍵下載）與目錄文件；首輪 Dukascopy 全 M1 抓法被限流，改為 HistData M1 + Dukascopy D1／H1；交叉核對抓出 HistData 時區是紐約當地時間含夏令、2004 年壞 tick，已修；**26 個商品首次全抓完成、Release `forex-data` 可用**（沙盒實測 `get_forex_data.py --pair EURUSD --merge-m1` 後 `backtest.load_bars` 可直接讀） |

## 6. 下一步（使用者未決定）

1. ~~把引擎修正合併回主分支~~（已完成：兩個修正與更正後數字都已推回，規格書 XAUUSD 已改 🔍）
1b. **原第 1 點的核對已做**（`donchian_backtest.py` 空單回補點差 bug，commit 933a3e7f），並用修正後引擎重看規格書／手冊的 HSI、HK50 CFD、NAS100 數字（黃金結論不變，指數 CFD 點差大會更差）；規格書的 XAUUSD ✅ 應按 VERDICTS.md 改為 🔍
2. **外匯月頻籃子路線全部走完**（FX_TREND_CARRY、FX_THREE_FACTOR、FX_NEW_INFO、FX_COT_OOS、FX_EM_UNIVERSE 五份登記，17 個正式檢定）：G7 與 14 貨幣宇宙、
   價格趨勢／利差／價值／動量／利率變動／期限利差／VIX／COT，機構與零售兩個口徑，**沒有一個 t ≥ 1.5**；機構口徑最好的一格是 G7 三因子 1.09 與 COT 週頻 1.41（樣本外 −1.52）。
   路線 C 前向記錄（`fx_forward.yml`）每月自動跑，24 個月後再看。若還要在外匯找，剩下的是**不同物種**：日內／高頻（要機構點差 ≤ 0.3 pip 與撮合數據，門檻先過入場券）、
   選擇權波動溢價（要外匯期權報價歷史）、或事件驅動（央行會議日）——都要新數據與新登記，帳本門檻 t ≥ 3
2b. **蛇蟠陣外匯到此為止**：25 個商品全部測過（USDJPY ☠️、XAUUSD 🔍、其餘 23 個批次 ☠️、合併 t −1.55）；要再測外匯，得換「機制」而不是換商品（例如更長通道、只做多、或加波動過濾），而且要先過入場券
3. **XAUUSD 只做多變體**是唯一有希望的形態（樣本外 t 1.70、全期 2.75）：可與主分支的 XAUUSD 前向測試（journal/）對照，記錄多頭腿與空頭腿分開的實盤損益
5. **每月更新數據**：HistData 月初幾天後才放上月檔；手動觸發 `fetch_forex.yml`（group = all）即可補齊，Dukascopy 部分只補近期
