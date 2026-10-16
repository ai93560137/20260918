# MHI AI 交易系統（小型恒指即月）

Claude 每 5 分鐘睇一次市，自己決定開倉、平倉、移止蝕；程式每 5 秒檢查止蝕止賺同風控，經 Futu OpenD 落單。

## 運作方式

| 部分 | 檔案 | 做咩 |
|---|---|---|
| 決策 | `brain.py` | 將 5 分鐘 K 線、日線、倉位、剩餘風險額度交畀 Claude，佢回傳 HOLD / OPEN_LONG / OPEN_SHORT / CLOSE / UPDATE_STOP |
| 風控 | `rules.py` `trader.py` | 驗證 AI 決定、每 5 秒睇止蝕止賺、日蝕上限、時段、轉倉、對賬 |
| 落單 | `broker.py` | 富途 OpenD：報價、倉位、淨值、可成交限價單（買 ask+3 點／賣 bid−3 點，15 秒唔成交就取消） |
| 成績 | `report.py` | 勝率、點數、每日盈虧、回撤、AI 用量 |

## 硬性風控（AI 冇權改）

- 最多 1 張，唔准加倉、唔准一步反手
- 每日虧損到 HK$10,000（含浮虧）即平倉，當日停機（17:00 HKT 重置，夜市計入下一日）
- 開倉一定要有止蝕；止蝕距離限制喺 20–150 點，止蝕風險大過今日剩餘額度就唔准開
- 每個時段收市前 10 分鐘唔開新倉；夜市 02:50 強制平倉，避開隔夜跳空
- 每日最多開 20 次倉
- 最後交易日自動轉下月，舊合約有倉即平
- 富途倉位同系統記錄唔一致時以富途為準；有手動開嘅倉會被接手，並自動設 150 點緊急止蝕
- 報價超過 3 分鐘冇更新（例如假期）唔交易
- 連續 10 次出錯即平倉停機

## 安裝

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install "setuptools<70" wheel
pip install --no-build-isolation futu-api          # 新版 Python 要咁裝
pip install anthropic pytest
cp .env.example .env    # 填 ANTHROPIC_API_KEY
python -m pytest tests -q
```

1. 開住 Futu OpenD，登入你個富途號
2. 用模擬：`TRD_ENV=SIMULATE`（富途期貨模擬戶口）
3. 轉真倉：改 `TRD_ENV=REAL`，喺 OpenD 介面解鎖交易（或者填 `FUTU_TRADE_PASSWORD`）

## 運行

```bash
python bot.py
```

- **即刻停**：喺程式資料夾建立 `STOP` 檔案 → 平倉 + 唔再開倉（刪咗佢、等到下一個交易日先會恢復）
- **暫停開倉**：建立 `PAUSE` 檔案 → 唔開新倉，現有倉照樣管止蝕
- 日誌：`logs/decisions.jsonl`（每次 AI 決定同理由）、`logs/trades.jsonl`、`logs/equity.jsonl`、`logs/bot.log`

## 睇成績

```bash
python report.py            # 由日誌計
python report.py --futu     # 加埋富途實際成交紀錄核對
```

## 要留意

- **止蝕由程式監控，唔係掛喺交易所**。程式或者電腦停咗，倉位就冇止蝕保護。所以最好擺喺長開嘅機（例如 GCP VM），同 OpenD 一齊行。
- AI 每日約 200 次決策（日夜市），用 Sonnet 成本較低；想用 Opus 改 `CLAUDE_MODEL=claude-opus-5-5`。
- 報告嘅「點數」未扣佣金同交易所費；「戶口淨值」嗰行已經包晒。
