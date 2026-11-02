# 935 組合 A／A+ 真倉：上線步驟（R364；R365 升級 A+）

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
- **R365 A+**（使用者 11-01「A+，替換 935，寫程式，真倉」）：magic 照 935、同時 1 張、1%／上限 0.01 唔變，加第 7 個成份 D1 內包線突破（上一日內包線、今日收市破母線高／低＋SMA200 同向；TP 4／SL 2 × D1 ATR；20 日；排最後）。回測（#207）：981 張 +0.101R PF 1.30、近 10 年 7/10、正數月 70/117、回撤 −25.7R（組合 A 989 張 +0.083R、−26.6R）。部署：總指揮 `gcp_agent.py --profile xausig deploy` dry-run → 使用者喺總指揮批 → `--yes`；唔使改 env、MT5 唔使改。
- 七個成份（2026 參數）：D1 Keltner 突破、D1 拋物線 SAR（＋SMA200）、D1 威廉 %R（＋SMA200）、H4 MACD（＋H4 SMA200）、H4 拋物線 SAR（＋H4 SMA200）、星期五做多、D1 內包線突破（＋SMA200）。
- 每個 H4 時段（22:00 UTC 對齊）判一次；收市後第一根有成交嘅 K 線開咗 30 分鐘內用市價入，帶 px／dev（EA v0.41 擋滑價 > 1.5 美元）。
- 同一時間最多 1 張；同時幾個訊號按上面次序揀第一個。止蝕／止賺放伺服器端（星期效應冇止賺）。
- 時間止蝕：D1 成份 480 小時、H4 成份 80 小時、星期效應 24 小時，到鐘發 `close|all|magic=935`。
- H1 由經紀 K 線存檔合成，存喺 `xau/sig/combolive/h1.json`（第一次由券商 MT5 歷史補 600 日）。931 停咗寫 K 線存檔就唔開。
- 唔開新倉：control 唔係 RUN、階梯 Ⓑ／Ⓓ、EA 未准交易、數據公佈封鎖期、935 今日已蝕 ≥ 5000 HKD、同戶口已經有 3 張倉、參數年份唔啱。

## 4. 停條件（使用者 11-01 批，已生效）
累計 ≤ −12R、由高位回落 ≤ −15R、連輸 ≥ 10、滿 40 張 PF < 0.85 → 巡檢通知總指揮「建議停」，停唔停由使用者決定。
依據（#186 單倉回測）：最長連輸 9、最差 20 張窗 −9.0R、最差 40 張窗 −10.1R、最大回撤 −26.6R。#184 影子前向警示（累計 ≤ −15R、回撤 ≤ −20R）另計。

## 5. 核對
- `research/strategy_search/combo_live_parity.py`：真倉純 Python 訊號同 research 版 2015→2026 逐根比較，指標成份（R365 起連內包線突破共六個）0 根唔一致；600 日快取同全歷史最後一根 90 次比較 0 次唔一致。
- `tests/test_xau_combo_live.py`：30 項全過（R365 加 A+ 6 項）。

## 6. 每年重揀參數（2027-01 要做）
- `python3 research/strategy_search/aplus_picks.py 2027`（數據要包齊 2026-12）：印出七個成份 2027 揀法，同真倉比較。
- 2026 核對：揀法同真倉一模一樣。2027 預覽（數據到 2026-10）：H4 MACD、H4 拋物線 SAR 由 ex1（TP2／SL2）轉 ex2（TP4／SL2），其餘唔變——12 月尾要再跑確認。
- 揀法變咗 → 改 `xau/combo_live.py` COMPONENTS 嘅 TP 倍＋`SIG_COMBO_PARAM_YEAR`；冇變都要改 `SIG_COMBO_PARAM_YEAR=2027`（唔改 935 唔開新倉）；全部經總指揮 dry-run＋使用者批。

