# 交接：MHI AI 交易系統（小型恒指即月）

日期：2026-10-16　狀態：第一版完成，假券商測試通過，**未曾連過真 OpenD**

## 1. 目標

由 AI（Claude API）全權決定買賣恒指小型期貨（MHI）即月合約，經富途 OpenD 自動落盤。程式負責執行同硬性風控，AI 無權越過。

## 2. 用戶已確定嘅決定

| 項目 | 決定 |
|---|---|
| 產品 | MHI 即月，最後交易日轉下月 |
| 決策者 | Claude API（預設 `claude-sonnet-5-5`，可改 Opus） |
| 決策頻率 | 每 5 分鐘（5 分鐘 K 線收咗 3 秒後） |
| 時段 | 日市 + 夜市 |
| 倉位上限 | 1 張 |
| 每日虧損上限 | HK$10,000（含浮虧），到咗即平倉停機 |
| 券商通道 | 富途 OpenD 已打通，可以攞數據、倉位，開放權限就可以落盤 |

**我（Claude）自己加、用戶未明確確認嘅限制**（全部喺 `.env` 可改）：
- 每張單止蝕 20–150 點
- 每日最多開 20 次倉
- 收市前 10 分鐘唔開新倉
- 夜市 02:50 強制平倉（避隔夜跳空）
- 預設 `TRD_ENV=SIMULATE`。注意：用戶喺金系統（諸葛亮）明確唔要 dry-run，呢個系統要問返佢想唔想直接 REAL

## 3. 架構

```
Futu OpenD (長開) ←→ broker.py ←→ trader.py ──→ brain.py → Claude API
                                     │
                                  rules.py（純邏輯）
                                     │
                         logs/*.jsonl + state.json → report.py
```

- **風控循環**：每 5 秒 `Trader.tick()` → 對賬 → 日蝕檢查 → STOP 檔 → 夜市收市平倉 → 止蝕止賺 → 到鐘先問 AI
- **AI 輸出**（forced tool_use `decide`）：`action` ∈ HOLD/OPEN_LONG/OPEN_SHORT/CLOSE/UPDATE_STOP，`stop_price`、`target_price`、`confidence`、`reason`（繁中）
- **驗證**：`rules.validate_decision()`，唔合規一律變 HOLD 並記低原因
- **落單**：可成交限價單（買 ask+3 點，賣 bid−3 點），每秒查狀態，15 秒唔成交就取消；成交後用實際成交價重新校正止蝕距離
- **對賬**：每個 tick 以富途倉位為準。有記錄冇倉 → 記「外部平倉」；有倉冇記錄 → 接手並設 150 點緊急止蝕；超過上限 → 減倉；非即月合約 → 平倉（轉倉）

## 4. 檔案

| 檔案 | 內容 |
|---|---|
| `config.py` | 讀 `.env`，所有參數 |
| `rules.py` | 時段、交易日 key、揀即月、止蝕判斷、AI 決定驗證（冇 I/O） |
| `broker.py` | `FutuBroker`：equity / positions / list_contracts / snapshot / klines / market_order |
| `brain.py` | `ClaudeBrain.decide(context)`，system prompt 同 tool schema，出錯回傳 HOLD |
| `trader.py` | `Trader`，broker / brain / clock 注入 |
| `bot.py` | 主程式，每 5 秒 tick，每 5 分鐘記淨值 |
| `report.py` | 成績報告；`--futu` 由富途成交紀錄 FIFO 計已實現點數核對 |
| `tests/test_trader.py` | 13 個測試，用 FakeBroker / FakeBrain |

## 5. 已核實嘅 Futu API 事實（futu-api，Python 3.13）

- 安裝：新版 setuptools 會 build 失敗（`install_layout` AttributeError）。要先 `pip install "setuptools<70" wheel`，再 `pip install --no-build-isolation futu-api`
- 期貨交易：`OpenFutureTradeContext(host, port, security_firm=SecurityFirm.FUTUSECURITIES)`
- `place_order(price, qty, code, trd_side, order_type=OrderType.NORMAL, trd_env, acc_id, remark)`；取消用 `modify_order(ModifyOrderOp.CANCEL, order_id, 0, 0, trd_env=, acc_id=)`
- `OrderType` 有 MARKET、STOP、STOP_LIMIT 等，但**未驗證 HK 期貨接唔接受**，所以第一版用 NORMAL 限價
- 合約列表：`quote.get_stock_basicinfo(Market.HK, SecurityType.FUTURE)`，欄位有 `last_trade_time`、`main_contract`；月合約代號格式 `HK.MHI2610`（regex `^HK\.([A-Z]+)(\d{2})(\d{2})$`）
- 連續合約日線用 `HK.MHImain`，失敗就退返用即月合約
- 倉位欄位：`code, qty, cost_price, position_side(LONG/SHORT), unrealized_pl...`；淡倉可能係 `qty>0 + SHORT`，亦可能 `qty<0`，兩種都要處理
- 淨值：`accinfo_query(...)["total_assets"]`
- `request_history_kline` 回傳 3 個值 `(ret, df, page_req_key)`
- 訂單狀態：FILLED_ALL；失效 = CANCELLED_ALL / CANCELLED_PART / FAILED / DISABLED / DELETED / FILL_CANCELLED
- **頻率限制**：倉位、淨值、訂單查詢用 `refresh_cache=False`（讀 OpenD 快取），每 5 秒 refresh 會撞限額

## 6. 時間規則（HKT）

- 日市 09:15–12:00、13:00–16:30；夜市 17:15–03:00（週一至五晚，即週二至六凌晨）
- 交易日 key = `(now + 7 小時).date()`，即 17:00 開始計新一日，日蝕上限喺嗰陣重置
- 假期由「報價超過 180 秒冇更新」判斷，唔交易
- 轉倉：`last_trade_date > today` 嘅最近合約；最後交易日當日已用下月

## 7. 未做 / 已知風險

1. **未連過真 OpenD**：第一件事係喺 SIMULATE 行一日，睇 log 確認合約代號、倉位方向、淨值欄位、成交價欄位（`dealt_avg_price`）同我假設一致
2. **止蝕唔喺交易所**：程式停咗就冇保護。下一步可以研究富途 HK 期貨支唔支援 STOP / STOP_LIMIT，掛一張後備止蝕單
3. 部署：OpenD 要長開，Cloud Run 唔啱；建議 GCP VM（OpenD + bot 同一部機）+ systemd 自動重啟
4. 冇通知：可以加 Telegram／WhatsApp 推送開平倉同停機事件
5. 冇放上 tnt-hk.com 嘅成績面板（用戶有現成 GCP main.py 推頁面嘅方法，喺 claude-ops 分支）
6. 外部平倉嘅出場價係估算（用當時最新價）
7. 報告嘅點數未扣佣金；淨值曲線已含費用
8. 部分成交後超時取消：靠下一個 tick 對賬處理，未專門測試
9. 假期前夕冇夜市嘅情況：倉位會帶到下一個交易日，唔會自動平

## 8. 運行

```bash
cp .env.example .env      # 填 ANTHROPIC_API_KEY
python -m pytest tests -q # 應該 13 passed
python bot.py
python report.py [--futu]
```

停機：建立 `STOP` 檔（即平倉，當日唔再開倉）；暫停開倉：建立 `PAUSE` 檔。
