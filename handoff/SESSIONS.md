# 各陣工作階段對照表（2026-10-14 起換新工作階段）

> 規矩（使用者 10-15）：工作階段上下文超過約 60 萬 tokens 就換新（10-15 由 40 萬改 60 萬）（SOP 顧問每週日用量快照會列出；FUND_SOP 二之三 A）。

> **以本表為準**。send_message 前先讀本表（`git fetch origin claude/gcp-trading-v12-rewrite-bz75t2 && git show origin/claude/gcp-trading-v12-rewrite-bz75t2:handoff/SESSIONS.md`）。
> 舊工作階段保留（唔封存），但 Routine 已／將改綁新工作階段；舊嘅收到訊息請轉交新嘅。由 SOP 顧問（新 `session_012caA3uVCQjRHHryN5HnMrn`）維護。
> ⚠ 唔好用 fire_trigger 手動觸發綁定新工作階段嘅 Routine：實測會另開一個冇 repo 嘅空白工作階段；排程時間到自動觸發就正常（2026-10-14 04:27 已驗證）。要即時做就直接 send_message 畀該陣。

| 陣／工作 | 新 session（現用） | 舊 session（保留） | 分支 | 交接文件 | Routine 已搬 |
|---|---|---|---|---|---|
| 🛡️ 總指揮 | `session_01ELtWSJc46vAFMT4oh3fCTV`（10-18 再換，上下文 67 萬） | `session_012CwdLPmAQvC91GZs5Jg9XA`（10-14）、`session_01N1jfpEJciBkfAgwtd4QxgU` | `claude/beautiful-hypatia-8qrgjj` | `handoff/總指揮.md` | ✅ |
| ☁️ 雲垂陣 | `session_013KSbtb9YJejCuaunQBdJDC`（10-18 再換，上下文 66 萬） | `session_01RkzmKXKixbBkCNqEjhubCK`（10-14）、`session_01QLJsy4RoeHjPNdNha73ibt` | `claude/dazzling-curie-f3xzb8` | `handoff/雲垂陣.md` | ✅ |
| 🌬️ 風揚陣 | `session_01BvMYgEWCVAJRi7v2WgT1qb`（10-15 再換，上下文過長） | `session_01X2Qv7MgCQxbyyEyGVzivWC`（10-14）、`session_01AmKfqsQjNQAkz1xgjRo2Mj` | `claude/epic-ramanujan-kp1l1v` | `handoff/風揚陣.md` | ✅ |
| 🐍 蛇蟠陣 | `session_01B4y7p7QzrJwCXEmDDZCx9M` | `session_011i86tjK8gxGxbMdTukZp4B` | `claude/gifted-carson-v2tvhw` | `handoff/蛇蟠陣.md` | ✅ |
| 🏔️ 地載陣 | `session_01UxZXWN28xveAEbzggo49AR` | `session_01QDAzw2CmhvhYWip9SRktBn` | `claude/dizai-expectations-r172` | `handoff/地載陣.md` | ✅（冇 Routine） |
| 🐤 金絲雀 | `session_01AqAysUfBVsCKimicXrwwKZ` | `session_01KucjwzRvueynnK5qm26y9g` | `claude/canary-playbook-final-3um9lp` | `handoff/金絲雀.md` | ✅ |
| 🐦 鳥翔 HTF | `session_018BXPn6zbpuMedYBTga6wp1` | `session_01NQur232BPDVDQzxd2hrvzU` | `claude/stock-research-k9nzau` | `handoff/鳥翔.md` | ✅ |
| 📈 股票市場策略研究 | `session_0159FXFtZPPMiENXrdpy2kQd` | `session_01C1wMzBze3QQ3CBXfrDSZ1t` | `claude/gifted-carson-v2tvhw` | `handoff/股票市場策略研究.md` | — |
| HTF 交易策略指南（動能 ORB） | 🚫 不換（使用者 10-14：已冇用） | `session_01AA5xBGBfBex9d23T23TQFY` | `claude/momentum-orb-research` | — | — |
| 外匯（VM 安裝；L1／6E／ZQ 採集繼續，使用者 10-14 決定） | `session_01YcJyu1yjZaFQTtY37WuQYH` | `session_01SHVCr19iNooiT5rp8BxD5t` | `claude/dazzling-curie-f3xzb8` | `handoff/外匯_VM安裝.md` | — |
| 外匯陣（數據測試） | 🚫 不換（使用者 10-14：已冇用） | `session_01Svsn6w1kkBJS3v6cXoGoXN` | `claude/forex-data-testing-w4q3m2` | — | 10-14 檢查提醒已停用；前向測試照由 Actions 跑 |
| GCP／VM／IBKR 資料採集（IV 日誌、claude-ops） | `session_01Mv7vE7k7oogpkK9fkBrLcm` | `session_01QECdg96y2dtk2skzrBNpVL` | `claude/gcp-agent-whoami-status-hswp4h` | `handoff/GCP_VM_IV採集.md` | ✅ |
| 指數套利 | 🚫 不換（使用者 10-14：已冇用） | `session_01KY3V9mVrkW6G6be4ywdGo3` | `claude/eager-mayer-eq2mek` | — | — |
| 🥇 XAUUSD GCP and TV | `session_015birEN7ure48Xk98cKz2PE` | `session_01SRQpEZwv5vYP1RoJcoAmmm` | `claude/tradingview-pine-script-cor9fw` | `handoff/XAUUSD_GCP_TV.md` | ✅（冇 Routine） |
| 股票套利（TSLA／SPCX） | 🚫 不換（使用者 10-14：已冇用） | `session_01FDZu3TKDUtoEHVmctS36JQ` | `claude/eager-fermi-haqt5y` | — | PR #101 重查提醒已停用 |
| 🖥️ 富途數據 VM（10-16 起 futu-data-tw，asia-east1-b；香港 futu-data 已停服務、保留待使用者刪；10-15 起推 GCS `futu/risk/latest.json`，改推送內容經 `gcp_ib/vm_futu/settings.env` PR） | `session_01AQNMTZvQodzptWVui6deqY`（總指揮 10-15 開） | — | `claude/futu-vm-setup` | `AGENTIC.md`「VM：futu-data」、`tradingview/RUNBOOK_FUTU_VM.md` | — |
| 🏦 債券每日快報（美債 Telegram，`bond_daily.yml` HKT 週二至六 07:30） | `session_013x5qHyMDisW7VCLNo6w88x`（10-15 總指揮開） | `session_01WrfzzWWLTysdSLJNZ3Mh5u`（美國國債數據與股票市場關係） | `claude/us-intl-data-stock-market-vgt0yi` | `handoff/債券快報.md`（該分支 518b054） | —（冇 Routine，Actions 排程） |
| 🐉 龍飛陣（AI 決策：HSI＋美股 ETF SPY／QQQ／DIA，10-16 22:20 起喺 futu-data-tw 跑，全部富途模擬戶口；2026-10-16 成立） | `session_0139SPVaaCjhGQM81SipbPgp` | — | `claude/hsi-ai-trader` | `handoff/龍飛陣.md` | —（未有 Routine） |
| 🐯 虎翼（大跌股賣 put；使用者 10-30 成立，10-31 加入總指揮白名單；實倉規則照虎翼草案） | `session_01Mt8CWjLKUQw2jyTNk48rrS` | — | `claude/huyi-bigdrop-options` | `handoff/虎翼.md` | ✅（美股 06:17、港股 19:41 掃描） |
| 🌌 天覆陣（XAUUSD CFD／MT5 改造；使用者 10-20 批准抽出獨立 Cloud Run `zhuge-xau`，GCS 只寫 `xau/`，影子階段唔落單；2026-10-20 成立） | `session_01N9ooQRNEnSz5WQRUg81hi5`（10-21 換，上下文 61 萬） | `session_01Xi2KRPAn4M1iG7VvrVxBUx` | `claude/tianfu`（舊名 `claude/keen-davinci-1zx3uo`、`claude/tianfu-xau`） | `handoff/天覆陣.md`（該分支，PR #236） | — |
| 🧭 SOP 顧問／預設分支 | `session_012caA3uVCQjRHHryN5HnMrn` | `session_01BzZsgkBzxEaLV6CYPW67i6` | `claude/gcp-trading-v12-rewrite-bz75t2` | `handoff/SOP顧問_預設分支.md` | — |
| claude-ops（使用者 VM，台灣） | `session_01J4dioYdtebaEyoaDwGJotM`（不換） | — | — | — | — |
