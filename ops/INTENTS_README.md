# 落單意圖價登記（`ops/intents.csv`，FUND_SOP 二之三 缺口 E）

各陣（或代使用者落單嘅工作階段）**出落單指令時**加一行——**喺你自己嘅分支**嘅 `ops/intents.csv`（冇就照本檔表頭新建；分支要列喺 `ops/notify_config.json` 嘅 `intent_branches`，新陣叫 SOP 顧問加），唔使寫預設分支；`scripts/ops_blotter.py` 每次成交通報（17:10／03:40 HKT）後
將富途成交配對到呢度，計滑價點數（正數＝成交差過意圖），寫入私人 GCS `ops/blotter/<月>.csv`，月報列按陣平均滑價。

| 欄 | 例 | 說明 |
|---|---|---|
| date | 2026-10-16 | 出指令嗰日（HKT）；配對當日同翌日（夜盤）成交 |
| team | 雲垂陣 | 陣名，同 `POSITIONS.md` |
| code | HK.MHI2610 | 富途代號；**前綴配對**（期權可只寫到 `HK.HSI261016` 等）。美股期權（富途數據 VM 10-31 核實）：`US.`＋正股＋到期 YYMMDD＋C/P＋行使價×1000、唔補零，例 `US.RDDT261127P80000`（80 put）、`…P82500`（82.5）；只寫到 `US.RDDT261127P` 就配同日到期全部 put |
| side | 賣 | `買`／`賣`（同富途成交一樣） |
| qty | 1 | 手數 |
| intent_price | 24100 | 指令參考價（例如雲垂 16:00 指令嘅期貨參考價、風揚操作箱嘅權利金） |
| note | 16:00 Δ 對沖 | 一句說明 |

repo 公開：只寫價格同手數，**唔寫金額、權益、保證金**。冇登記意圖價嘅成交照樣入 blotter，只係冇滑價。

各陣事後更正 `intents.csv` 之後，SOP 顧問跑 `python3 scripts/ops_blotter.py --rematch` 將已入 blotter 但未配到嘅成交重配。
