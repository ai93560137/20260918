# 各陣工作階段對照表（2026-10-14 起換新工作階段）

> **以本表為準**。send_message 前先讀本表（`git fetch origin claude/gcp-trading-v12-rewrite-bz75t2 && git show origin/claude/gcp-trading-v12-rewrite-bz75t2:handoff/SESSIONS.md`）。
> 舊工作階段保留（唔封存），但 Routine 已／將改綁新工作階段；舊嘅收到訊息請轉交新嘅。由 SOP 顧問維護。
> ⚠ 唔好用 fire_trigger 手動觸發綁定新工作階段嘅 Routine：實測會另開一個冇 repo 嘅空白工作階段；排程時間到自動觸發就正常（2026-10-14 04:27 已驗證）。要即時做就直接 send_message 畀該陣。

| 陣／工作 | 新 session（現用） | 舊 session（保留） | 分支 | 交接文件 | Routine 已搬 |
|---|---|---|---|---|---|
| 🛡️ 總指揮 | `session_012CwdLPmAQvC91GZs5Jg9XA` | `session_01N1jfpEJciBkfAgwtd4QxgU` | `claude/beautiful-hypatia-8qrgjj` | `handoff/總指揮.md` | ✅ |
| ☁️ 雲垂陣 | `session_01RkzmKXKixbBkCNqEjhubCK` | `session_01QLJsy4RoeHjPNdNha73ibt` | `claude/dazzling-curie-f3xzb8` | `handoff/雲垂陣.md` | ✅ |
| 🌬️ 風揚陣 | `session_01X2Qv7MgCQxbyyEyGVzivWC` | `session_01AmKfqsQjNQAkz1xgjRo2Mj` | `claude/epic-ramanujan-kp1l1v` | `handoff/風揚陣.md` | ✅ |
| 🐍 蛇蟠陣 | `session_01B4y7p7QzrJwCXEmDDZCx9M` | `session_011i86tjK8gxGxbMdTukZp4B` | `claude/gifted-carson-v2tvhw` | `handoff/蛇蟠陣.md` | ✅ |
| 🏔️ 地載陣 | `session_01UxZXWN28xveAEbzggo49AR` | `session_01QDAzw2CmhvhYWip9SRktBn` | `claude/dizai-expectations-r172` | `handoff/地載陣.md` | ✅（冇 Routine） |
| 🐤 金絲雀 | `session_01AqAysUfBVsCKimicXrwwKZ` | `session_01KucjwzRvueynnK5qm26y9g` | `claude/canary-playbook-final-3um9lp` | `handoff/金絲雀.md` | ✅ |
| 🐦 鳥翔 HTF | `session_018BXPn6zbpuMedYBTga6wp1` | `session_01NQur232BPDVDQzxd2hrvzU` | `claude/stock-research-k9nzau` | `handoff/鳥翔.md` | ✅ |
| 📈 股票市場策略研究 | `session_0159FXFtZPPMiENXrdpy2kQd` | `session_01C1wMzBze3QQ3CBXfrDSZ1t` | `claude/gifted-carson-v2tvhw` | `handoff/股票市場策略研究.md` | — |
| HTF 交易策略指南（動能 ORB） | 🚫 不換（使用者 10-14：已冇用） | `session_01AA5xBGBfBex9d23T23TQFY` | `claude/momentum-orb-research` | — | — |
| 外匯（VM 安裝） | ⏳ | `session_01SHVCr19iNooiT5rp8BxD5t` | `claude/dazzling-curie-f3xzb8` | ⏳ | — |
| 外匯陣（數據測試） | 🚫 不換（使用者 10-14：已冇用） | `session_01Svsn6w1kkBJS3v6cXoGoXN` | `claude/forex-data-testing-w4q3m2` | — | 10-14 檢查提醒已停用；前向測試照由 Actions 跑 |
| GCP agent／IV 採集 | ⏳ | `session_01QECdg96y2dtk2skzrBNpVL` | `claude/gcp-agent-whoami-status-hswp4h` | ⏳ | ⏳ |
| 指數套利 | 🚫 不換（使用者 10-14：已冇用） | `session_01KY3V9mVrkW6G6be4ywdGo3` | `claude/eager-mayer-eq2mek` | — | — |
| XAUUSD GCP and TV | ⏳ | `session_01SRQpEZwv5vYP1RoJcoAmmm` | `claude/tradingview-pine-script-cor9fw` | ⏳ | — |
| 股票套利（TSLA／SPCX） | 🚫 不換（使用者 10-14：已冇用） | `session_01FDZu3TKDUtoEHVmctS36JQ` | `claude/eager-fermi-haqt5y` | — | PR #101 重查提醒已停用 |
| SOP 顧問／預設分支 | ⏳ | `session_01BzZsgkBzxEaLV6CYPW67i6` | `claude/gcp-trading-v12-rewrite-bz75t2` | `handoff/SOP顧問_預設分支.md` | — |
| claude-ops（使用者 VM，台灣） | `session_01J4dioYdtebaEyoaDwGJotM`（不換） | — | — | — | — |
