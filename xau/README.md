# 🌌 天覆陣 — XAUUSD CFD（MT5）Claude 決策服務（R291）

龍飛陣做期貨／美股（富途），天覆陣做 CFD（MT5）。架構沿用龍飛陣 `hsi_ai_trader/`：

| 檔案 | 做咩 |
|---|---|
| `main.py` | Cloud Run 入口：EA 心跳 → 累積 K 線 → 問 Claude → 硬性規則 → 影子（紙上）或實倉（指令）→ 紀錄 |
| `brain.py` | Claude 決策（strict tool `decide`：HOLD／OPEN_LONG／OPEN_SHORT／CLOSE／UPDATE_STOP），Haiku 預篩，prompt caching |
| `rules.py` | 純邏輯：硬性規則（AI 無權改）、止損止賺觸發、最長持倉 |
| `paper.py` | 紙上模擬（影子模式嘅盈虧） |
| `page.py` | 單一頁面（取代舊服務五頁：投資人日誌、關卡開關、送單參數、錦囊執行單、錦囊九十筆） |
| `storage.py`、`market.py`、`config.py` | GCS、K 線／時段、設定 |
| `LESSONS.md` | 使用者教學簿；線上優先讀 GCS `xau/lessons.md` |

## 同舊服務嘅關係

```
MT5 EA V23 ──心跳──▶ zhuge-risk-manager（main.py，照舊：電閘、錦囊、webhooktrade）
                          └─ XAU_SHADOW_URL 設咗 → 新 M1 收盤時轉發（加權杖，2 秒逾時，唔等）──▶ zhuge-xau（本服務）
                                                                                            └─ Claude 決策 → 紙上模擬 → GCS xau/
```

- 影子階段（`XAU_EXECUTE=0`，預設）：只寫 GCS `xau/`，心跳回應 `cmd_text` 永遠空，**唔會送單**。
- **舊規則同電閘唔再係硬閘**（使用者 10-20：「將之前的規則, 電閘, 刪減, 但給該陣claude.ai 做參考」）：六關、錦囊 v4 條件、150 分鐘出場、新聞鎖整理喺
  `reference/legacy_rules.md`，放入 Claude system prompt 做參考；舊服務 `zhuge_gate_state.json` 只讀，作 `legacy_gate` 參考資料傳畀 Claude。
- **硬性風控（AI 無權改，照龍飛陣、冇硬鎖）**：日蝕 −3% PAUSE／−6% 平倉 STOP（紐約換日自動重開）；保證金 < 300% PAUSE（回升自動解）；
  累計 −25% PAUSE（當日事件，換日自動重開）；回撤 10%／20%、保證金 < 200%／150% 只發 Telegram；最大手數、止損距離、最長持倉。
  唯一開關 GCS `xau/control.json`（`mode` RUN／PAUSE／STOP、`set_by`、`auto_reset_day`、`principal_hkd` 私人）；使用者設嘅模式程式唔會自己改。見 `handoff/天覆陣.md` §5。
- 實倉階段（`XAU_EXECUTE=1`）：EA 改指向本服務，心跳回應 `cmd_text` 帶指令，EA 執行後 `cmd_ack` 回報。要先有新 EA（PR B），同埋影子達到預先登記標準（PR C）。

## 新執行器 EA（PR B，`mt5/TianfuExecutor.mq5`，v0.1 未編譯未測）

純執行器：每 60 秒心跳（帶權杖、`margin_level`、只計自己 magic 嘅持倉／今日已實現／浮動、M1／M15 K 線），執行回應 `cmd_text`，`cmd_ack` 回報。
只管 `_Symbol`＋`InpMagic`；唔接手、唔平其他 magic 嘅單；冇 SL 嘅 open 拒絕；`InpDryRun=true`（預設）只印指令唔落單；id 去重存檔案 `MQL5/Files/tianfu_seen_<symbol>.txt`。
使用者自己喺 MetaEditor 編譯、先掛 demo。線上 V23 歸 XAUUSD GCP／TV 陣，唔郁。

## 風控階梯點計（使用者 10-20：真倉同 C 戶口共用，唔用獨立戶口）

日蝕／回撤／硬止損**只計天覆陣自己嘅單**：模擬＝紙上盈虧；真倉＝EA 按 magic 回報。「自己嘅權益」= 本金（`control.json principal_hkd`）＋累計已實現＋浮動。
唔用戶口淨值（有手動單會污染）。保證金水平係戶口級，照用但當作戶口級警報。

## 指令格式（實倉）

每行一條，EA 用 `StringSplit("|")` 讀；`id` 兩邊去重，10 分鐘冇回報就作廢：
```
open|BUY|0.01|sl=4120.50|tp=4210.00|magic=921|id=a1b2c3d4
close|all|magic=921|id=…
modify|all|sl=4130.00|tp=|magic=921|id=…
```
EA 回報：`POST {"action":"cmd_ack","token":…,"id":"a1b2c3d4","ok":true,"ticket":123,"message":"…"}`。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `WEBHOOK_SECRET_TOKEN` | — | 必須；同舊服務相同。心跳同回報都要帶 |
| `ANTHROPIC_API_KEY` | — | `CLAUDE_PROVIDER=api`（預設，同龍飛陣）時必須 |
| `CLAUDE_PROVIDER` | `api` | `vertex` = 用同一 GCP 專案嘅 Vertex AI Claude（要喺 Model Garden 啟用） |
| `CLAUDE_MODEL`／`CLAUDE_EFFORT` | `claude-opus-5-5`／`low` | 影子階段量延遲同費用再調 |
| `GATE_MODEL`／`GATE_EFFORT` | `claude-haiku-5-5`／`low` | 空倉先篩；留空 = 唔篩 |
| `XAU_EXECUTE` | `0` | 1 = 實倉指令 |
| `XAU_LOTS`／`XAU_MAX_LOTS` | 0.01／0.10 | 固定手數 |
| `XAU_MIN_SL_USD`／`XAU_MAX_SL_USD` | 2／30 | 止損距離範圍（美元／盎司） |
| `XAU_MIN_CONFIDENCE` | 0.6 | 開倉最低信心 |
| `XAU_MAX_TRADES_PER_DAY` | 0 | 0 = 唔限 |
| `XAU_MAX_HOLD_MIN` | 1440 | 最長持倉，到時強制平倉 |
| `XAU_LONG_ONLY` | 0 | 影子階段兩邊都記 |
| `XAU_CALL_WHEN_LOCKED` | 0 | 空倉且電閘 LOCK 時唔問 Claude（慳錢） |
| `XAU_MAGIC` | 921 | 同新 EA `InpMagic` 一致（線上 V23 用 920） |

## 費用同延遲（影子階段要量）

M1 每日最多 1,440 次。休市／停機唔問；空倉先用 Haiku 篩。頁面顯示今日次數、費用、p95 延遲。
EA `WebRequest` 逾時 15 秒（V23）：實倉前 p95 要低過呢個數，否則改非同步（決定寫 GCS，EA 下一個心跳先取指令）。

## 部署

```bash
python3.11 -m py_compile xau/*.py && python3 tests/test_xau.py
python3 scripts/gcp_agent.py --profile xau deploy --local-only                      # 只打包＋來源檢查
python3 scripts/gcp_agent.py --profile xau deploy --set-env XAU_EXECUTE=0 CLAUDE_PROVIDER=api CLAUDE_MODEL=claude-opus-5-5 CLAUDE_EFFORT=low GATE_MODEL=claude-haiku-5-5 --copy-env TG_BOT_TOKEN TG_CHAT_ID   # dry-run：計畫＋缺少嘅權限
#   → 使用者同意後加 --yes；服務唔存在會建立（沿用 zhuge-risk-manager 嘅 baseImage／資源／服務帳戶），唔改 IAM
python3 scripts/gcp_agent.py --profile xau status / logs / env get
```
部署後使用者要喺控制台做：① 服務「安全性」→ 允許未經驗證的叫用；② 環境變數填 `WEBHOOK_SECRET_TOKEN`（同舊服務相同）同 `ANTHROPIC_API_KEY`（唔貼入對話）。
之後舊服務 `env set XAU_SHADOW_URL=<新服務網址>/ XAU_SHADOW_TOKEN=<新服務嘅權杖>`（先 dry-run，同總指揮對時間）先會開始轉發心跳。
⚠️ 舊服務線上**未設** `WEBHOOK_SECRET_TOKEN`（10-20 查到），程式用預設 `123456`；天覆陣用自己嘅權杖，唔沿用。

## 影子標準（照 IDEAS.md 慣例預先登記，達標先入 PR C）

≥ 30 筆紙上交易、期望值 > 0、最大回撤 < 設定值、冇違反硬規則嘅輸出、p95 延遲 < 15 秒。
