# 給雲垂分支：候選 1（Karnaukh pre-FOMC 條件式美元漂移）登記前的數據請求

發出：外匯分支 `claude/forex-data-testing-w4q3m2`，2026-10-12（使用者已在外匯工作階段確認：先發數據請求、讀到全文才登記；ZQ 拉不到 2003 起就接受 2008 起樣本）。
收件：雲垂分支 `claude/dazzling-curie-f3xzb8`（GCP VM；外匯沙盒的網路名單只放行 GitHub，連不到學術網站、聯準會與任何數據站，所以這三樣都要 VM 代抓）。
**全部只讀、不下單、不花錢**；要花錢的選項（CME DataMine／FirstRate）先報價、不要買。

## 1. 論文全文 → 登記用摘錄（最優先；沒有它不能登記）

- 來源（任一可下載者）：AUT 鏡像 `https://acfr.aut.ac.nz/__data/assets/pdf_file/0019/190315/DollarAheadFOMC_NinaKarnaukh.pdf`；SSRN 3221318（2020-01 版，Fisher WP 2018-03-014）；發表版 *International Finance* 2020。
- **PDF 與全文留在 VM，不要 commit**（本倉庫是公開的，不放整篇受版權保護的論文）。`pdftotext -layout` 後，commit 一份**摘錄檔** `data_forex_ibkr/_papers/Karnaukh_DollarAheadFOMC_excerpts.md`，只放登記要用的段落，**逐字引用並標頁碼**，不要改寫、不要自己總結數字：
  1. 樣本：起訖年月、排定會議次數、是否含非排定會議、資料來源與頻率（日收盤？幾點？哪個城市的收盤？）。
  2. 匯率標的：美元指數（哪一個？等權幾個貨幣？）還是逐貨幣；有沒有 EUR/USD 單獨結果。
  3. **訊號定義**：用哪個聯邦基金期貨合約（當月？次月？）、在會議前第幾天量（t−3？）、公式（隱含利率 − 現行目標？有沒有按月內天數調整）、「預期升息／降息」的門檻（多少基點）。
  4. **事件窗**：「兩天」是 t−2 收盤 → t 公告前？還是 t−2 → t−1 收盤？公告當天算不算；公告時間用幾點。
  5. 主結果表：預期升息前／降息前的平均美元報酬（基點）、t 值、R²、樣本數；無條件（全部會議）的平均。
  6. 交易策略：規則、每事件平均報酬、年化夏普、t 值、**有沒有扣交易成本、扣多少**。
  7. 子樣本與穩健性：2008 前後、零利率期間、剔除 2008 等；其他央行有沒有。
  8. 機制段落（資訊先進固定收益再進匯市）與作者對衰退／套利的討論。
  9. 附錄裡任何關於資料清理（例如非排定會議、會議兩天的處理）的句子。
- 另外請用 `pdfinfo` 把頁數、版本日期一併寫進摘錄檔開頭。若兩個版本（2016 工作稿 vs 2020 發表版）數字不同，兩個都抄並標明。

## 2. FOMC 排定公告日曆 1994-01 → 2026-12

- 來源：聯準會 `https://www.federalreserve.gov/monetarypolicy/fomc_historical_year.htm`（逐年頁）＋ `fomccalendars.htm`（近五年與未來）。
- 輸出 `data_forex_ibkr/fomc/fomc_announcements.csv`，欄位：
  `date`（公告日，YYYY-MM-DD，兩天會議取第二天）、`scheduled`（1＝排定；非排定／電話會議＝0，仍列出）、`statement_time_et`（頁面有寫就填 HH:MM；沒寫填空）、`press_conference`（1/0）、`target_before`、`target_after`（目標利率或區間上限，%；2008-12 後填區間上限）、`source_url`、`note`。
- 時間慣例（頁面沒寫時用這個填 `statement_time_et_rule` 欄，並在 note 標「rule」）：1994–2010 約 14:15 ET；2011-04 → 2012 有記者會的會議 12:30 ET、其餘 14:15；2013-01 起一律 14:00 ET。**若你在頁面上看到與此不符的實際時間，以頁面為準並標出來。**
- 另附 `fomc_calendar_check.txt`：每年排定會議次數（應為 8），缺漏或多出的年份說明。

## 3. 30 天聯邦基金期貨 ZQ：IB 試拉（看能拉多深，不保證有）

- 合約：`Future('ZQ', exchange='CBOT', currency='USD')`，逐月合約 `lastTradeDateOrContractMonth=YYYYMM`。先 `reqContractDetails` 列出 IB 目前還認得的到期月（已到期合約 IB 通常只保留約 2 年）。
- 對每個認得的合約拉 **1 day** K 線、`whatToShow='TRADES'`、`useRTH=0`，從上市到到期；輸出 `data_forex_ibkr/zq/ZQ_<YYYYMM>.csv.gz`（Time,Open,High,Low,Close,Volume）。
- **結算價問題**：IB 期貨日線的 Close 多數情況是結算價，但不保證。請另對最近 3 個合約抓最近 20 天的 `whatToShow='TRADES'` 日線與 CME 網站公布的結算價對照一次，把差異寫進 `_status.txt`。
- 也請試 `ContFuture('ZQ','CBOT')` 日線能回溯到哪一年（回溯調整的連續價不能直接算隱含利率，但可看深度）。
- 回報：能拉到的最早到期月、每個合約的首尾日期、空回應的合約。**預期只有 2024 下半年起**；若是這樣就照使用者決定走「2008 起樣本」路線，請順便查 FirstRate Data（`firstratedata.com/i/futures/ZQ`）ZQ 日線歷史的**價格與起始年份**，只報價、不買。

## 4. 已有、不用抓

- EURUSD 與七大美元對 H1／M1（Dukascopy 2003-08 起、HistData 2000-05 起）在外匯分支；M6E 成本 4.11 基點（2.25 美元／邊＋1 tick）已定。
- 美國政策利率序列（FRED DFF、FEDFUNDS）在 `data_forex_rates/`。

## 5. 交付

- commit 到雲垂分支：`data_forex_ibkr/_papers/…excerpts.md`、`data_forex_ibkr/fomc/…`、`data_forex_ibkr/zq/…`、更新 `data_forex_ibkr/_status.txt`（ZQ 深度、結算價對照、FirstRate 報價）。commit 訊息 `data(fomc): Karnaukh 摘錄／FOMC 日曆／ZQ 試拉`。
- 外匯分支收到摘錄後才寫登記 `forex_research/FX_FOMC_DRIFT_BACKTEST.md`（規格以論文為準；帳本新增「FOMC 事件樣本」一列，第一次 t ≥ 2.5）；候選 2、3 之後再議。
- 不要用這些數據跑任何回測；不要把 `data_forex_ibkr/` 合併回其他分支。

## 6. 使用者直接在 VM 跑（2026-10-12，提示符 `@ib-data`；一次貼完，約 15–25 分鐘，大部分是 IB 節流等待）

腳本在外匯分支：`scripts/paper_excerpt.py`（PDF → 關鍵詞選段逐字摘錄，全文不進 git）、`scripts/fomc_calendar_fetch.py`（聯準會逐年頁＋日曆頁，存原始 HTML、解析聲明日期、逐篇抓「For release at」時間）、`scripts/ib_zq_probe.py`（IB 試拉 ZQ 含已到期合約與連續合約）。

```bash
cd ~/20260918 && git pull --rebase origin claude/dazzling-curie-f3xzb8
git fetch origin claude/forex-data-testing-w4q3m2
git checkout origin/claude/forex-data-testing-w4q3m2 -- scripts/paper_excerpt.py scripts/fomc_calendar_fetch.py scripts/ib_zq_probe.py
mkdir -p data_forex_ibkr/_papers data_forex_ibkr/fomc data_forex_ibkr/zq ~/papers

# 1. 論文：PDF 留在 ~/papers（不進 git），只 commit 摘錄
curl -fsSL -A "Mozilla/5.0" -o ~/papers/Karnaukh_DollarAheadFOMC.pdf \
  "https://acfr.aut.ac.nz/__data/assets/pdf_file/0019/190315/DollarAheadFOMC_NinaKarnaukh.pdf" \
  && ls -la ~/papers/ || echo "AUT 下載失敗：請用瀏覽器從 SSRN 3221318 下載後放到 ~/papers/Karnaukh_DollarAheadFOMC.pdf 再跑下一行"
command -v pdftotext >/dev/null || sudo -n apt-get install -y poppler-utils 2>/dev/null || echo "沒有 pdftotext，腳本會改用 pypdf"
python3 scripts/paper_excerpt.py ~/papers/Karnaukh_DollarAheadFOMC.pdf data_forex_ibkr/_papers/Karnaukh_DollarAheadFOMC_excerpts.md

# 2. FOMC 日曆 1994→2027（約 300 個網頁請求，每個隔 0.7 秒 ≈ 4–5 分鐘）
python3 scripts/fomc_calendar_fetch.py --out data_forex_ibkr/fomc 2>&1 | tee data_forex_ibkr/fomc/_fetch.log

# 3. IB 試拉 ZQ（clientId 43；每合約隔 11 秒，約 40 個合約 ≈ 8 分鐘）
python3 scripts/ib_zq_probe.py --out data_forex_ibkr/zq --client-id 43 2>&1 | tee data_forex_ibkr/zq/_probe.log

# 4. 推回雲垂分支
git add data_forex_ibkr/_papers data_forex_ibkr/fomc data_forex_ibkr/zq
git commit -m "data(fomc): Karnaukh 摘錄／FOMC 日曆／ZQ 試拉"
git push origin claude/dazzling-curie-f3xzb8
```

- 第 1 步若 AUT 連不上，用瀏覽器從 SSRN 下載 PDF 放到 `~/papers/` 後只重跑 `python3 scripts/paper_excerpt.py …` 那行。
- 第 2 步會印每年「排定 N，非排定 M」，排定不是 8 的年份會標 ←，外匯分支會對原始 HTML 複核。
- 第 3 步預期多數舊合約「無資料」（IB 只保留已到期約 2 年）；這就是我們要的答案。
- FirstRate ZQ 日線的價格與起始年份請你在瀏覽器看一眼 `https://firstratedata.com/i/futures/ZQ`，把兩個數字告訴我即可，不用買。

## 7. 進度（2026-10-12 19:30 UTC）

| 項目 | 狀態 |
|---|---|
| 論文摘錄 | **未完成**：AUT 對 curl 回 403；等使用者用瀏覽器下載 PDF 上傳到 VM `~/papers/` 後跑 `paper_excerpt.py`（見第 6 節 B） |
| FOMC 日曆 | **完成**：VM 抓回原始頁（`data_forex_rates/fomc/raw/`，28 頁），外匯分支離線解析 `scripts/fomc_calendar_parse.py` → `data_forex_rates/fomc/fomc_announcements.csv`（1994→2027，每年排定 8 次；2020 的 3/17–18 取消）。排定會議數：1994–2015 論文樣本 176（論文摘要說 176 次排定公告，吻合）、2003-08→2026-08 184、2008-01→2026-08 148。聲明時間：2016 起逐篇抓到「For release at」；之前新聞稿只寫 For immediate release，用時代規則欄 `statement_time_rule`（1994–2011-03 14:15；2011-04→2012 有記者會 12:30／無 14:15；2013 起 14:00）。VM 版解析（統計聲明連結）在 1994–1999 少算、2021 起多算，已由離線版取代 |
| ZQ 試拉 | **深度確認**：IB 只列出已到期約 2 個月內的合約（最早 ZQ 2025-09），每個合約本身有 3 年日線（如 ZQ 2026-03 自 2023-04 起）；連續合約與 `_status.txt` 因第二次執行 clientId 43 撞號而沒寫。結論同預期：**IB 不能提供 2003–2024 的 ZQ**，照使用者決定走 2008 起樣本，待 FirstRate 報價（使用者看 `firstratedata.com/i/futures/ZQ`）。選配：用 `includeExpired=True` 明示 2024-01→2025-08 各月再試一次，最多再多 1–2 年，不改變結論 |
