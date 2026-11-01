# 935 組合 A 真倉：上線步驟（R364）

使用者 11-01 揀：一個 magic 935、同一時間最多 1 張、戶口 …69、每張 1%（唔夠 0.01 手就照開 0.01）、上限 0.01 手。
研究依據：IDEAS #183（組合 A 合格）、#186（單倉版合格：989 張 +0.083R、14/18 年正、回撤 −26.6R）；影子前向 #184 進行緊。

## 1. 部署（總指揮做，使用者喺總指揮工作階段批）
1. PR merge 之後，總指揮跑 `gcp_agent.py --profile xausig deploy`，先做 dry-run，再由使用者批准 `--yes`。部署完 `SIG_COMBO_LIVE` 仍然係 0，即係唔會落單。
2. 開關：`gcp_agent.py --profile xausig env set SIG_COMBO_LIVE=1`，先 dry-run，使用者批先 `--yes`。其餘 env 用預設值：
   - `SIG_COMBO_RISK_PCT=1`、`SIG_COMBO_MAX_LOTS=0.01`、`SIG_COMBO_FLOOR_MAX_PCT=10`（0.01 手風險超過權益 10% 就唔開）
   - `SIG_COMBO_DAY_STOP_HKD=5000`、`SIG_COMBO_ACCOUNT_MAX=3`（931＋933＋934＋935 合共）
   - `SIG_COMBO_PARAM_YEAR=2026`（2027 年要按 #184 重揀參數先改；唔改就唔開新倉）

## 2. MT5（使用者喺 …69 做）
1. 喺 …69 開多一張 **XAUUSD** 圖，唔好用 931、933、934 嗰幾張。
2. 拖 TianfuExecutor **v0.41** 落去，設定：
   - `InpMagic=935`
   - `InpUrl=` zhuge-xau-sig 嘅網址（同 931 一樣）
   - `InpDryRun=false`
   - `InpBotMagics` 已經包咗 931 至 935，唔使改
3. 開咗之後，網頁 `?format=json` 嘅 `combo_live.account.received_utc` 應該喺 3 分鐘以內更新。

## 3. 點運作
- 六個成份（2026 參數）：D1 Keltner 突破、D1 拋物線 SAR（＋SMA200）、D1 威廉 %R（＋SMA200）、H4 MACD（＋H4 SMA200）、H4 拋物線 SAR（＋H4 SMA200）、星期五做多。
- 每個 H4 時段（22:00 UTC 對齊）判一次；收市後第一根有成交嘅 K 線開咗 30 分鐘內用市價入，帶 px／dev（EA v0.41 擋滑價 > 1.5 美元）。
- 同一時間最多 1 張；同時幾個訊號按上面次序揀第一個。止蝕／止賺放伺服器端（星期效應冇止賺）。
- 時間止蝕：D1 成份 480 小時、H4 成份 80 小時、星期效應 24 小時，到鐘發 `close|all|magic=935`。
- H1 由經紀 K 線存檔合成，存喺 `xau/sig/combolive/h1.json`（第一次由券商 MT5 歷史補 600 日）。931 停咗寫 K 線存檔就唔開。
- 唔開新倉：control 唔係 RUN、階梯 Ⓑ／Ⓓ、EA 未准交易、數據公佈封鎖期、935 今日已蝕 ≥ 5000 HKD、同戶口已經有 3 張倉、參數年份唔啱。

## 4. 建議停條件（要使用者批）
同 #184 影子前向警示一樣：累計 ≤ −15R、或者由高位回落 ≤ −20R → 巡檢通知總指揮「建議停」，停唔停由使用者決定。

## 5. 核對
- `research/strategy_search/combo_live_parity.py`：真倉純 Python 訊號同 research 版 2015→2026 逐根比較，五個指標成份 0 根唔一致；600 日快取同全歷史最後一根 90 次比較 0 次唔一致。
- `tests/test_xau_combo_live.py`：24 項全過。
