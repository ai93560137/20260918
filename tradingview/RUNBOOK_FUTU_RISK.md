# 富途持倉 → 報價 → 風險報告：PowerShell 操作手冊

全部只讀：唔落單、唔 unlock_trade、唔改單。報價只作監控，落單以富途即時價為準。
結果檔（`futu_positions.json`、`tradingview/out/`）喺本分支已 `.gitignore`；你部機嘅分支未必有，**唔好 `git add` 佢哋**；要畀 Claude 睇就貼內容入對話。

每個區塊獨立複製，喺 repo 資料夾入面跑（`<你的 repo 路徑>` 換成你部機嘅路徑）。

## 0. 準備（每次開 PowerShell 跑一次）

```powershell
cd <你的 repo 路徑>
$env:PYTHONIOENCODING = "utf-8"
```

## 1. 攞最新版工具（只取兩個程式檔，唔會郁你嘅持倉檔）

```powershell
git fetch origin claude/beautiful-hypatia-8qrgjj
git checkout origin/claude/beautiful-hypatia-8qrgjj -- gcp_ib/futu_positions_quote.py tradingview/risk_report.py
```

第一次用（部機冇 `tradingview\data_external\risk_book.json`）再加呢句：

```powershell
git checkout origin/claude/beautiful-hypatia-8qrgjj -- tradingview/data_external/risk_book.json
```

## 2. 核對 OpenD 登入身份（OpenD 登入 ID 改好之後先跑）

```powershell
python gcp_ib\futu_positions_quote.py --diagnose
```

對照：App「我的」牛牛號尾 3 位 ↔「OpenD 登入用戶 ID」；App 期貨帳戶卡號尾 4 位 ↔「卡號」；資金唔再係 0。

## 3. 搵標普期貨期權（MES 週權、EW 月底）嘅富途代碼

```powershell
python gcp_ib\futu_positions_quote.py --probe-us
```

## 4. 讀持倉＋報價（寫 tradingview\data_external\futu_positions.json）

```powershell
python gcp_ib\futu_positions_quote.py
```

API 仲係讀唔到持倉時，改用固定持倉：

```powershell
python gcp_ib\futu_positions_quote.py --fixed
```

## 5. 出風險報告（本機）

```powershell
python tradingview\risk_report.py --md tradingview\out\risk_report_live.md
```

硬止損按幾個戶口合計權益計：知道合計數就加 `--combined-equity 812000`（換成實數，HKD）。

## 6. 畀 Claude 覆核：複製輸出貼入對話（冇帳號、冇密碼）

```powershell
Get-Content tradingview\data_external\futu_positions.json -Encoding utf8
```

## 單獨查價

```powershell
python gcp_ib\futu_positions_quote.py --codes HK.MHI2610 HK.MHI261029C25000000 HK.MHI261029P25000000 HK.HSI261016C24900000 HK.HSI261016P23750000
```

```powershell
python gcp_ib\futu_positions_quote.py --chain 2026-10-29 24800 25200
```

```powershell
python gcp_ib\futu_positions_quote.py --deals HK.MHI2610 --since 2026-10-01
```
（成交時間係 UTC，加 8 個鐘＝香港時間）

## API 始終讀唔到持倉

富途 App →「持倉 → 期貨」截圖貼入對話，Claude 解析做 `risk_book.json` 格式（只喺本機用，唔 commit）。

## 7. 自動：定時讀持倉＋報價＋計風險（`gcp_ib\auto_risk.py`）

只讀、唔落單。結果寫喺 `tradingview\out\`（`risk_report_live.md`、`risk_history.csv`），唔會 commit。
警報（富途保證金緩衝 < 10 萬、止損用量 ≥ 80%、雲垂 Δ 超 ±0.5、合計權益低過硬止損、讀富途失敗）只喺**出現／解除**時先發 Telegram。

第一次設定（設完要關咗 PowerShell 再開）：

```powershell
setx ZHUGE_COMBINED_EQUITY 2520339
```

想收 Telegram 就再設（同其他通知用同一個 bot；token 只放喺你部機，唔好貼入對話）：

```powershell
setx TG_BOT_TOKEN "你的 bot token"
setx TG_CHAT_ID "你的 chat id"
```

先試一次：

```powershell
python gcp_ib\auto_risk.py --once
```

之後開住一個 PowerShell 視窗一直跑（每 15 分鐘；週末自動停；Ctrl+C 停止）：

```powershell
python gcp_ib\auto_risk.py --every 15
```

推上 GCP（四個陣經 Claude 自動收到；存私人 bucket `futu/risk/`，冇公開頁面）：同 `futu/push_to_gcp.py` 用同一對設定，設過就唔使再設：

```powershell
setx ZHUGE_GCP_URL "https://zhuge-risk-manager-1056099871997.europe-west1.run.app/"
setx WEBHOOK_SECRET_TOKEN "同 Cloud Run 一樣嘅權杖"
```

開機登入就自動跑（唔使管理員權限；放一個 .cmd 入「啟動」資料夾；要停用就刪咗個檔）：

```powershell
$py = (Get-Command python).Source
$startup = [Environment]::GetFolderPath("Startup")
"@echo off`r`ncd /d `"$PWD`"`r`nset PYTHONIOENCODING=utf-8`r`n`"$py`" gcp_ib\auto_risk.py --every 15`r`n" | Set-Content "$startup\ZhugeAutoRisk.cmd" -Encoding ascii
Get-Content "$startup\ZhugeAutoRisk.cmd"
```

（`schtasks /SC ONLOGON` 要管理員權限，會出 `Access is denied`，所以改用啟動資料夾。）

睇最新結果：

```powershell
Get-Content tradingview\out\risk_report_live.md -Encoding utf8 | Select-Object -First 12
Get-Content tradingview\out\risk_history.csv -Tail 5
```

## 8. 每日自動匯出基金報告（R153，`auto_risk.py` 內建）

`auto_risk.py --every 15` 每日香港時間 05:30 之後第一次循環，會喺背景跑一次 `futu_pnl_export.py`（推 `action=futu_pnl` → 📊 基金報告）。
成功先記低（`tradingview\out\pnl_export_state.json`），失敗每日最多試 3 次；輸出喺 `tradingview\out\pnl_export_last.log`。週末唔跑（星期六 05:30 嗰次會跑，包埋星期五夜市）。唔想要就加 `--no-pnl`。

更新（攞新版之後要重開 auto_risk）：

```powershell
git fetch origin claude/beautiful-hypatia-8qrgjj
git checkout origin/claude/beautiful-hypatia-8qrgjj -- gcp_ib/auto_risk.py gcp_ib/futu_pnl_export.py
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object CommandLine -like "*auto_risk.py*" | ForEach-Object { Stop-Process -Id $_.ProcessId }
Start-Process "$([Environment]::GetFolderPath('Startup'))\ZhugeAutoRisk.cmd"
```

查結果：

```powershell
Get-Content tradingview\out\pnl_export_state.json -Encoding utf8
Get-Content tradingview\out\pnl_export_last.log -Encoding utf8 -Tail 5
```
