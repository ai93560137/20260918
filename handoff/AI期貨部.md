# 🤖 AI 期貨部（MHI 純 AI 決策）— 部門章程與交接

成立：2026-10-16（使用者指示「建立一個純 AI 決策期貨交易部門」）
工作階段：`session_0139SPVaaCjhGQM81SipbPgp`　分支：`claude/hsi-ai-trader`
程式：`hsi_ai_trader/`（原交接文件 `hsi_ai_trader/HANDOFF.md`，使用者上載嘅 `hsi-ai-trader.zip` 原封放入）
狀態：**第一版完成、假券商測試 13 passed（本分支 2026-10-16 重跑通過），未曾連過真 OpenD，未落過任何單**

## 1. 部門定位

同其他陣唔同：其他陣係「研究 → 規則 → 人手或半自動執行」，AI 期貨部係 **Claude API 每 5 分鐘自己決定買賣**，
程式只負責執行同硬性風控（AI 無權越過）。

| 項目 | 決定（使用者已確定） |
|---|---|
| 產品 | 小型恒指 MHI 即月，最後交易日轉下月 |
| 決策者 | Claude API（預設 `claude-sonnet-5-5`，`.env` 可改 Opus） |
| 頻率 | 每 5 分鐘（5 分鐘 K 收咗 3 秒後） |
| 時段 | 日市＋夜市 |
| 倉位上限 | 1 張 |
| 每日虧損上限 | HK$10,000（含浮虧），到咗即平倉停機；交易日 17:00 HKT 重置 |
| 券商 | 富途 OpenD |

## 2. 未經使用者確認、要問返嘅嘢

1. **SIMULATE 定 REAL？** 預設 `TRD_ENV=SIMULATE`。使用者喺金系統（諸葛亮）唔要 dry-run，呢度要佢親口決定。
   本部門建議：先 SIMULATE 行足一個日市＋一個夜市，核對完交接文件 §7-1 嘅欄位先轉 REAL。
2. 前任自己加嘅限制（全部喺 `.env`）：每張止蝕 20–150 點（最多 HK$1,500）、每日最多開 20 次倉、收市前 10 分鐘唔開新倉、
   夜市 02:50 強制平倉。
3. 用邊個富途戶口？如果同風揚陣／雲垂陣／人手同一個期貨戶口，按金互相影響，而且見下面 §4 配對問題。

## 3. 同基金規矩點接

- **IDEAS.md**：#106 登記為 🔬 研究中；轉 SIMULATE 前向測試改 📒 紙上，轉 REAL 前改 💼 實倉（規則 5）。
- **POSITIONS.md**：轉 REAL 前登記一列，再 `send_message` 通知總指揮。
- **RISK_LADDER.md**：總指揮宣布 Ⓑ（停開新倉）時，本部門用 `PAUSE` 檔停開新倉；Ⓒ／Ⓓ 用 `STOP` 檔即平倉停機。
  呢個要喺部機上做，即係要有人（使用者或部機上嘅自動化）放檔，雲端工作階段做唔到。
- **部署**：OpenD 要長開，**唔放 Cloud Run**（`hsi_ai_trader/` 已加入 `.gcloudignore`）。建議放富途數據 VM（futu-data，asia-east2，
  已經有 OpenD）＋ systemd 自動重啟；呢步要同 `session_01AQNMTZvQodzptWVui6deqY` 協調。
- **金鑰**：`ANTHROPIC_API_KEY`、富途交易密碼只放部機 `.env`（已在 `.gitignore`），唔入 repo、唔貼對話。

## 4. 要總指揮處理

- `main.py` `FUTU_TEAM_RULES` 現時 `HK.MHI2611` 全部歸人手、`MHI2610` 有雲垂對沖規則。AI 部門嘅 MHI 倉位喺持倉層面同人手分唔開
  （落單 remark 係 `zhuge-mhi`，但持倉快照冇 remark）。最好用**獨立富途子戶口**；同一戶口就要總指揮定配對方法。
- 每日虧損上限 HK$10,000 要唔要計入 RISK_LADDER 嘅策略線。

## 5. 已知風險（摘自 `hsi_ai_trader/HANDOFF.md` §7）

1. 未連過真 OpenD：合約代號、倉位方向（淡倉 `qty<0` 或 `qty>0+SHORT`）、淨值、`dealt_avg_price` 欄位未核實。
2. **止蝕唔喺交易所**：程式停咗倉位就冇保護；要研究富途 HK 期貨接唔接 STOP／STOP_LIMIT 做後備止蝕單。
3. 冇通知（Telegram）、冇成績面板；外部平倉出場價係估算；報告點數未扣佣；部分成交未專門測試；假期前夕冇夜市會帶倉過夜。

## 6. 下一步（順序）

1. 使用者答 §2 三條問題。
2. 部機（futu-data VM）裝：`pip install "setuptools<70" wheel && pip install --no-build-isolation futu-api anthropic`，
   `cp .env.example .env` 填金鑰，`python -m pytest tests -q`（應 13 passed）。
3. SIMULATE 行一日，對 log 核實 §5-1 嘅欄位。
4. 加 Telegram 通知開平倉／停機；研究交易所後備止蝕單。
5. IDEAS 改 📒，前向測試期滿再決定 REAL。
