# 通知各分支：外部數據來源（貼到各分支的 session）

到每個分支的 session，把下面 ```text 框內整段貼上即可。
內容對所有分支都一樣，各分支只看跟自己有關的那一段。

```text
【通知：外部數據來源統一由預設分支每天彙整】

我們現在有三個外部數據來源，全部每天自動彙整到預設分支的 data/external/：

1. MT5（只有 CFD）：目前只有 XAUUSD M1，EA 開市時每分鐘推到 GCP。
2. Futu：本地 OpenD 每 5 分鐘推到 GCP。目前取 US.QQQ 5 分 K 與最近到期 ATM 期權 IV／Greeks；
   要換商品只要改環境變數 FUTU_SYMBOLS，不用改程式。
   權限：港股股票／期權／期貨 LV1、美股股票 LV3、美股期權 LV1；沒有美國指數、CME、COMEX、日本、新加坡、A 股。
3. IBKR：雲垂的 GCP VM（IB Gateway paper，延遲數據，唯讀）。日經／歐洲週月 IV 每日一行，
   股票收市／開市覆核依需求；原始資料在雲垂分支，預設分支每天鏡像一份。

取數據（不用合併、不影響本分支）：
  git fetch origin claude/gcp-trading-v12-rewrite-bz75t2
  mkdir -p /tmp/ext && git archive origin/claude/gcp-trading-v12-rewrite-bz75t2 data/external | tar -x -C /tmp/ext
  cat /tmp/ext/data/external/README.md     # 目錄、欄位、時區、怎麼加商品
  cat /tmp/ext/data/external/STATUS.md     # 每個系列的最新日期與列數

路徑：
  MT5   data/external/mt5/XAUUSD/M1/<年>/<日期>.csv.gz        （券商伺服器時間，夏令 UTC+3／冬令 UTC+2）
  Futu  data/external/futu/<代號>/K_5M/<年>/<日期>.csv.gz      （交易所當地時間）
        data/external/futu/<代號>/options/<年>/<日期>.csv.gz   （iv 為百分比，每次推送一列一檔）
  IBKR  data/external/ibkr/iv_term_structure/ib_iv_log.csv
        data/external/ibkr/stock_closes/<市場>_<訊號日>.csv

規矩：
- 監測與研究用，永不直接用於下單；下單以券商即時報價為準。
- 不要在本分支重抓這三個來源，也不要改 data/external/（每天會被覆蓋）。
- 要加商品或新來源：先問我，決定後照 README.md 第一節改對應位置。
- MT5／Futu 的歷史從 R95 部署到 Cloud Run 那天開始累積，之前沒有。

各分支看自己的：
- 金絲雀（claude/canary-playbook-final-3um9lp）：週度期權腿只讀價。可用的 IV 來源有兩個：
  IBKR 的 N225／ESTX50 週月 IV（ibkr/iv_term_structure），以及 Futu 期權（目前 US.QQQ；港股期權有權限，要加代號先問我）。
- 雲垂（claude/dazzling-curie-f3xzb8）：IBKR 採集照舊推回本分支即可，預設分支會鏡像
  tradingview/data_external/ib_iv_log.csv 與 data_stock_ibkr/。這兩個路徑要改名的話，
  要同時改預設分支的 scripts/external_data_sync.py。Futu 港股期權可當恒指波動溢價的另一個對照源。
- 蛇蟠（claude/forex-data-testing-w4q3m2）：MT5 XAUUSD M1 從 R95 起每天累積，可接在本分支
  data/XAUUSD_M1_*.csv.gz（同券商 MT5 匯出）之後。注意 time_utc 固定用 +3 換算，冬令要自己修正。
- 鳥翔（claude/stock-research-k9nzau）：IBKR 股票覆核照舊，預設分支也有鏡像（ibkr/stock_closes）。
  Futu 有美股 LV3、港股 LV1，可當第四來源；30 天內歷史 K 線額度只有 100 個代號，大量覆核先問我。

請做一件事：在本分支的交接文件或 README 加一行
「外部數據來源（MT5／Futu／IBKR）：見預設分支 data/external/README.md，取法用 git archive」，
commit 並推回本分支（不要開 PR）。做完回報你加在哪個檔、哪一行。
```
