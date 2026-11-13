# 月尾股債再平衡（#1463／#1466／#1469）上線步驟——程式已寫好，**未部署**

> 使用者 11-13：「69，SP500 0.2 UK100 0.1，冇國債品種」「第一條同第二條轉真倉」；睇完真倉口徑重算（近六年接近打和）之後再確認：「照行，SP500 0.2＋UK100 0.1，…69」。
> 部署同改環境變數由總指揮做 dry-run，使用者親口批准先做。

## 規則 `merebal`（`xau/trend_merebal.py`、`xau/merebal_feed.py`）

- 每月倒數第 6 個交易日（訊號日）UTC 20:45 之後：睇「指數當月至今回報 − 美債 10 年期貨（ZN）當月至今回報」。
  股票跑輸（< 0）→ 做多；否則做空。當日內第一個心跳市價入；一個月只做一次。
- 當月最後一個交易日 UTC 20:45 之後第一個心跳平倉；過咗月都未平就即平。
- 保險止蝕：入場價 ±10%（伺服器端）。回測入面持倉期收市計最深 −5.6%，冇掂過。冇止賺。
- 股債數據：服務喺訊號日自己攞 Yahoo Finance 公開日線（SP500 用 `^GSPC`、UK100 用 `^FTSE`、美債用 `ZN=F`）；要有上月尾收市同當日價先算數。
  攞唔到／唔新鮮 → 10 分鐘後再試，當日攞唔到就**今個月唔做**，記 WARNING。每 UTC 日另外做一次連線檢查（status 嘅 `merebal.probe`）。
- 交易日曆用規則計（平日減美國／英國假期）；同 2010–2026 實際交易日比，訊號日／月尾日唔一致 美國 1／202、英國 3／202 個月（颶風、國葬等突發休市）。
- 2026-11：SP500 訊號日 11-20、UK100 訊號日 11-23；月尾日都係 11-30。

## 真倉口徑回測（`research/strategy_search/PARITY_MEREBAL.md`，2010-07 起，扣成本同隔夜息）

| 腳 | 手數 | 每月淨回報 | t | 做多／做空平均 | 最差一個月 |
|---|---|---|---|---|---|
| SP500 | 0.2 | +0.221% | 1.58 | +0.71%／−0.03% | −4.3% |
| UK100 | 0.1 | +0.362% | 2.82 | +0.47%／+0.29% | −4.8% |

- 合計每月平均約 +9 美元（t 2.54）、標準差 49、最差月 −94。**2021 年起合計只有約 +36 美元**（2022 −132、2026 −56）。
- 價值在於同黃金簿冇關（每月損益相關約 0）；當做細注碼前向測試。
- 檢討點（唔係自動停）：累計已平倉損益 ≤ −200 美元，或者行滿 12 個月，報使用者決定繼續定返影子。

## 券商規格（使用者 11-13 截圖）

| 品種 | 合約 | 最細手數／步長 | 買入／賣出隔夜息（每手每晚） | 三倍日 |
|---|---|---|---|---|
| SP500 | 1 | 0.1／0.1 | −1.6349／+0.3204 美元 | 星期五 |
| UK100 | 1 | 0.1／0.1 | −2.2196／+0.4157 英鎊 | 星期五 |

## 部署（總指揮；全部先 dry-run，使用者親口批）

每個指數一個服務（profile 會自動帶必要環境變數，唔一致就拒絕部署）：

| | SP500 | UK100 |
|---|---|---|
| profile／服務 | `sp500`／`zhuge-sp500` | `uk100`／`zhuge-uk100` |
| profile 自動帶 | `XAU_SYMBOL=SP500`、`XAU_EXECUTE=0`、`XAU_TREND_RULES=merebal`、`XAU_TREND_MEREBAL_CAL=US`、`XAU_TREND_MEREBAL_IDX=^GSPC` | `XAU_SYMBOL=UK100`、`XAU_EXECUTE=0`、`XAU_TREND_RULES=merebal`、`XAU_TREND_MEREBAL_CAL=UK`、`XAU_TREND_MEREBAL_IDX=^FTSE` |
| `XAU_TREND_MAGIC` | `945` | `946` |
| `XAU_TREND_LOTS`／`XAU_TREND_MAX_LOTS` | `0.2`／`0.2` | `0.1`／`0.1` |
| `XAU_QUOTE_PER_USD` | （唔使設） | `0.76`（英鎊報價；只影響港幣損益顯示） |
| GCS 前綴 | `idx/sp500/` | `idx/uk100/` |

1. `python3 scripts/gcp_agent.py --profile sp500 deploy`、`--profile uk100 deploy`（會建立新服務）。
2. 機密同戶口（唔好打明文）：`--profile sp500 env copy --from-profile xausig WEBHOOK_SECRET_TOKEN TG_BOT_TOKEN TG_CHAT_ID XAU_ACCOUNT`（…69 嘅服務係 zhuge-xau-sig）；uk100 一樣。
3. `env set`：`XAU_TREND_MAGIC`、`XAU_TREND_LOTS`、`XAU_TREND_MAX_LOTS`、`XAU_ACTIVE_HOURS_UTC=00-00`、`XAU_ACK_REQUIRE_ACCOUNT=1`、`XAU_TEST_CMDS=0`、`XAU_TREND_LIVE=0`（先關）；uk100 加 `XAU_QUOTE_PER_USD=0.76`。
4. 使用者喺控制台開兩個服務嘅「允許未經驗證的叫用」。
5. 使用者喺 …69 開 **SP500** 同 **UK100** 兩張圖掛 `TianfuExecutor`：`InpUrl` 手填各自服務網址、`InpMagic` 945／946、`InpDryRun=false`；
   **SP500 嗰張 `InpMaxLots` 要改 `0.20`**（預設 0.10 會拒絕 0.2 手）；兩個網址都要加入「允許 WebRequest」清單。
6. 天覆陣核實：心跳、symbol、戶口 …69、`merebal.probe` 冇 err（＝Cloud Run 攞到 Yahoo）、`merebal.key_days` 啱。
7. 使用者再講一次先 `env set XAU_TREND_LIVE=1`。
- 退版：`env set XAU_TREND_LIVE=0`（有倉先平）。

## 程式改動（其他服務行為唔變）

- 新：`xau/trend_merebal.py`（日曆、方向、時段，純計算）、`xau/merebal_feed.py`（Yahoo 日線解析同當月回報）。
- `xau/trend_live.py`：`merebal` 入場（`plan`）、出場（`exit_due`）、訊號日預先攞數據同每日連線檢查（`merebal_prefetch`）、status 加 `merebal`。簿冇 `merebal` 規則時完全唔行。
- `xau/config.py`：產品 `SP500`、`UK100`；`XAU_TREND_MEREBAL_*`。`scripts/gcp_agent.py`：profile `sp500`、`uk100`。`scripts/tianfu_patrol.py`：加兩本簿。
- 測試：`tests/test_xau_trend_merebal.py`（6 個）；其餘 `tests/test_xau_trend_*.py` 逐個檔跑。
