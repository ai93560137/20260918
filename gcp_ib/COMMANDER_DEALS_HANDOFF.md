# 交付總指揮：每日富途成交紀錄（futu_deals_daily.py）

**來源**：分支 `claude/dazzling-curie-f3xzb8`，檔案 `gcp_ib/futu_deals_daily.py`（純讀取，不 unlock_trade、不落單、不改單；帳戶號碼不輸出）。
**使用者要求**：由總指揮每日執行（雲垂 session 唔直接連富途）。

## 做咩
讀富途 `history_deal_list_query`（期貨＋證券 HK／US 真實帳戶）自 `--since`（預設 2026-09-01）起嘅成交，輸出：
- `deals`：當日逐筆成交（時間 HKT、合約、買／賣、手數、價）
- `summary`：按合約彙總（買賣均價、淨手數）
- `closed`：當日平倉（FIFO 配對）嘅 開倉價→平倉價、點數盈虧、HKD 盈虧（MHI ×10／HSI ×50；未知合約只報點數）。未計佣金／費用。

## 點用
- 直接：`python gcp_ib/futu_deals_daily.py --date 2026-10-13 --out deals.json`
- 或 `from futu_deals_daily import run; res = run(day, since)` 嵌入 auto_risk（Futu 連線預設 127.0.0.1:11111，按總指揮環境改 HOST/PORT）。
- 驗證邏輯（唔連富途）：`python gcp_ib/futu_deals_daily.py --self-test`
- 這邊已用模擬資料驗證 FIFO（10/9 賣 24,200 → 10/13 買 24,168 = +32 點 = +HK$320）；**未連真實富途跑過**，首次請核對一次輸出同富途 App 成交紀錄。

## 建議排程（每日）
- 收市後約 16:45 HKT（日盤成交），及翌日凌晨約 03:15 HKT（夜盤 17:15–03:00 成交，按成交時間歸日）。
- 存 `futu/deals/<日期>.json`（同 `futu/risk/latest.json` 同桶），並把「當日平倉」一節加入 16:45 收市摘要。
- 若某日有 MHI／MES 平倉，通報雲垂 session：合約、平倉價、時間、已實現盈虧（雲垂用嚟填 `research/divergence/ledger_yunchui.csv` 嘅 buyback_pts、net_pnl_hkd，並記錄對沖已實現盈虧）。

## 已知限制
- FIFO 只係估算同一合約配對，未必同富途「已實現盈虧」口徑一致；以富途 App 為準。
- 若成交紀錄 API 限制日數／帳戶權限，`--since` 要涵蓋開倉日，否則平倉會配唔到開倉價（會留喺 open lots 內）。
