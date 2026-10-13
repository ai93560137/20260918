# 交接：外匯 VM 安裝工作階段（雲垂分支上的「外匯 IB 報價管線」）

原工作階段：`session_01SHVCr19iNooiT5rp8BxD5t`（標題「雲垂：安裝外匯分支的兩支 IB 報價快照腳本」）。寫於 2026-10-13。
接手工作階段：`session_01YcJyu1yjZaFQTtY37WuQYH`（「💱 外匯 VM 安裝（新，接手 2026-10-14）」），2026-10-14 起由它負責。

**2026-10-14 使用者決定**：外匯研究線（外匯數據測試 session `session_01Svsn6w1kkBJS3v6cXoGoXN`）已停、不開接手，但 VM 上的 L1／6E／ZQ 採集**繼續**，由本工作階段負責（使用者原話：「VM 上的外匯數據採集還要繼續, 轉到外匯（VM 安裝）新工作階段」）。採集出問題直接在對話告訴使用者；預設分支 07:30 流水線心跳不含 VM，VM 健康靠本工作階段在使用者來找時看狀態檔與 log。
分支：`claude/dazzling-curie-f3xzb8`（與雲垂陣共用，**只動下列外匯相關檔**，雲垂的股指檔案不要碰）。

## a. 負責什麼、使用者原話與規矩

- 職責：在 GCP VM `ib-data`（IB Gateway paper 埠 4002、IBC 常駐、ib_insync）上替外匯分支（`claude/forex-data-testing-w4q3m2`，外匯陣，工作階段 `session_01Svsn6w1kkBJS3v6cXoGoXN`）安裝與維護**只讀**的 IB 報價腳本，數據推回本分支。
- 使用者原話（10-12）：「脫離雲垂 重新定立一個自己的策略」「只用雲 取IB 數據」。即：外匯策略的登記、跑數、判決、前向都在外匯分支；本工作只供 IB 數據管線。
- 鐵律：不下單、不改帳戶設定、不花錢買數據訂閱（要花錢先問使用者）；IB 帳密只在 VM 的 `~/ibc/config.ini`，不進 repo、不進對話；不改 `gcp_ib/ib_collector.py` 的既有市場與既有 cron；不把 `data_forex_ibkr/` 合併到其他分支；不用這些數據跑回測（外匯分支做）；`ib_fx_option_snapshot.py --open`（B 階段）要外匯分支通知才執行。
- 本工作階段無法直接操作 VM（沙盒無 Gateway、無 gcloud 認證）。所有 VM 操作都是寫好可貼的 shell 區塊，使用者用瀏覽器 SSH 登入 `ib-data`（提示符 `hengkychansinghing@ib-data`）貼上，再貼回輸出。
- 使用者戶口（決定外匯策略可行性）：富途保證金戶、購買力約 5,700 美元、只有 CME 期貨（6E／M6E 已確認）與美股期權；費用全包 M6E 2.25 美元／邊、6E 6.61 美元／邊。L1 因成本不執行；黃金蛇蟠陣只做多使用者明示不試。

## b. 例行流程（VM `ib-data` 上，時區 UTC）

| cron（UTC） | 做什麼 | 輸出 |
|---|---|---|
| `59 8 * * 1-5`、`59 11 * * 1-5` | `scripts/ib_l1_quote.py --label 0859/1159 --client-id 41`：EURUSD IDEALPRO 即時 bid／ask | `data_forex_ibkr/l1_quotes.csv`、`l1_quote.log` |
| `0 14 * * 1-5` | `scripts/ib_fx_option_snapshot.py --client-id 32`：6E 近月 ATM 跨式（月權 EUU 優先） | `data_forex_ibkr/vrp_snapshots.csv`、`vrp_snapshot.log` |
| `30 23 * * 1-5` | `scripts/ib_zq_daily.py --client-id 45 --push`：ZQ 聯邦基金期貨本月＋後 3 個月合約最近 10 天日線（Close＝結算），按 (date, contract) 去重合併；**腳本自己 commit＋push**（訊息 `data(zq): ZQ 每日結算`），不經 push_fx_quotes.sh。pre-FOMC 美元漂移前向用；首個關鍵日 10-23（五）結算＝10-28 FOMC 的 t−3 | `data_forex_ibkr/zq/zq_daily.csv`、`zq/zq_daily.log`（log 不進 git） |
| `10 2 * * 6` | `gcp_ib/push_fx_quotes.sh`：兩個 CSV 各一個 commit 推回本分支（訊息 `data(ibkr): L1 報價快照`／`data(ibkr): 6E 期權快照`） | `~/ib_fx_push.log` |
| `*/10 * * * *` | `gcp_ib/dismiss_paper_warning.sh`：Gateway 的模擬帳免責聲明框（標題 Warning、501×260）出現就點掉 | `~/ib_warning_click.log` |

- clientId 表：17 ib_collector、23 ib_fx_history、24 ib_stock_verify、31 htf_5m_fetch、32 6E 快照、41 L1、45 ZQ 每日、77 ibkr_vol_export。
- ZQ 安裝依據：外匯分支 `forex_research/IBKR_ZQ_DAILY_REQUEST.md`（協議 `FX_FOMC_DRIFT_FORWARD.md`）；本分支 10-12 20:31、23:30 UTC 已有 `data(zq)` commit，證實 cron 在跑。`data_forex_ibkr/zq/_status.txt` 記 ZQ 試拉結果（IB 日線 Close 是否等於 CME 結算仍待人工核對）。
- VM repo 設了 `git config rebase.autostash true`（否則 CSV 被追加後工作樹髒，`run_daily.sh` 的 `pull --rebase` 會中止）。
- 狀態檔：`data_forex_ibkr/_l1_vrp_install_status.txt`（安裝全紀錄、VM 實測輸出、改動說明）。

## c. Routine／send_later

- 本工作階段建立的一次性觸發都已發完（PR #91 安全網已刪；10-13 14:20 的 6E 首筆檢查已觸發）。
- poke-only routine `trig_01RYyrFDQFkSdepHwdDAEScc`（「外匯陣 → 雲垂 通知」）**不搬**：外匯數據測試已停，不會再有人觸發（SOP 顧問 10-14 確認）。
- 另有「GCP agent」工作階段的 `trig_01FTWXBqXqUv3s89YmUF7apo`（10-14 檢查 IV 採集，提到 claude-ops／`ssh ibdata`／`/srv/ibshare`）——不是本工作建立的，由 SOP 顧問處理，本工作階段不用管。

## d. 誰找我、我找誰

- 外匯分支 `session_01Svsn6w1kkBJS3v6cXoGoXN`：2026-10-14 起已停，不再收發通知。
- 新雲垂 `session_01RkzmKXKixbBkCNqEjhubCK`：同一分支的推送若撞到雲垂 commit，用 send_message 協調（各陣 id 以預設分支 `handoff/SESSIONS.md` 為準）。
- 可改的外匯檔：`gcp_ib/push_fx_quotes.sh`、`gcp_ib/dismiss_paper_warning.sh`、`scripts/ib_l1_quote.py`、`scripts/ib_fx_option_snapshot.py`、`scripts/ib_zq_daily.py`、`data_forex_ibkr/`；雲垂陣的檔不碰。
- 預設分支 SOP 顧問 `session_01BzZsgkBzxEaLV6CYPW67i6`：發交接要求。

## e. 進行中／未完成／已知坑

- **待確認**：10-13 14:00 UTC 6E 首筆正式快照與 L1 08:59／11:59 是否寫入。CSV 週六才推，要請使用者在 VM 貼：
  `tail -n 20 ~/20260918/data_forex_ibkr/vrp_snapshot.log; tail -n 3 ~/20260918/data_forex_ibkr/vrp_snapshots.csv; tail -n 5 ~/20260918/data_forex_ibkr/l1_quotes.csv; tail -n 5 ~/ib_warning_click.log`
  預期：`scan` 一列、`trading_class=EUU`、`half_spread_vol` 有值；L1 兩列有 bid／ask。
- **10-13 已知**：分支上 `ib_iv_log.csv` 10-13 有 ESTX50、6E、6J，**N225 缺**（另一工作階段的 trig_01FTWX… 10-14 08:00 會查）。
- 外匯分支已據文獻報告登記並開跑「pre-FOMC 條件式美元漂移」前向（它分支 `fx_fomc_forward.yml`、`forward/zq_hist/`）；若要雲垂供 ZQ 或其他 IB 數據，會發請求文件。
- 第一筆週推：10-17（六）02:10 UTC，之後確認 CSV 出現在本分支。
- 坑：①貼指令時常多打字元（如 `Scd`），失敗先看第一行；②10141 免責聲明框會擋所有 API（自動點框已裝）；③VM 工作樹髒會擋 pull（autostash 已設）；④IB 對已到期期貨歷史深度有限；⑤沙盒連不到學術全文網站。
- 文獻報告：`data_forex_ibkr/_lit_review_fx_strategies_2026-10-12.md`（候選 1 FOMC 條件式漂移、候選 2 產出缺口時序、候選 3 FOMC 當日空美元）。

## f. 開工第一步要讀

1. 本檔。
2. `data_forex_ibkr/_l1_vrp_install_status.txt`（尤其「VM 實測」「4B／4D」「安裝結論」）。
3. `data_forex_ibkr/_requests_to_forex_2026-10-12.md`（第 0、6 節）。
4. `gcp_ib/push_fx_quotes.sh`、`gcp_ib/dismiss_paper_warning.sh`、`scripts/ib_l1_quote.py`、`scripts/ib_fx_option_snapshot.py`。
5. 外匯分支：`git fetch origin claude/forex-data-testing-w4q3m2` 後看 `forex_research/VERDICTS.md`、`IBKR_*_REQUEST.md`。
