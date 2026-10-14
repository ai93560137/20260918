"""每日對帳表／損益帳／風控階梯（scripts/daily_books.py）。唔連 GCS、唔 git show；全部用假資料。"""
import io, json, os, re, sys
from datetime import date, datetime, timezone, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import daily_books as db

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

POS_MD = """| 陣 | 戶口 | 持倉 | 開倉 | 規則 | 完結 | 狀態 | 紀錄 |
|---|---|---|---|---|---|---|---|
| 🌬️ 風揚陣・方向一 | 富途期貨 | 沽 HSI 週期權 10/16：Put 23,750 @46 ＋ Call 24,900 @36（各 1 張，權利金 82 點） | 2026-10-10 | 持有到期 | 2026-10-16 | 持倉中 | x |
| ☁️ 雲垂陣 | 富途期貨 | 沽 MHI 10/29 跨式 C/P 25,000 各 1 張（600／508）＋ MHI2610 期貨對沖沽 1 張 @24,305（10/13 重新對沖） | 2026-09-22 | 止損 | 2026-10-29 | 持倉中 | x |
| ☁️ 雲垂陣 | 富途期貨 | 沽 MES 10/16 跨式 C/P 7,830 各 1 張（88.75／89.75；富途代碼 EX3） | 2026-09-22 | 止損 | 2026-10-16 | 持倉中 | x |
| 🐍 蛇蟠陣（使用者人手） | 富途期貨 | 賣 HSI2610 大恒指期貨 1 手 @24,333（10/13 人手再開） | 2026-10-13 | 通道 | 反手時 | 持倉中（淨空 1 手） | x |
| ✋ 使用者人手 | 富途期貨 | 沽 EW2610 P7,750 1 張 @68（E-mini 月底期權） | 2026-10 | 止損 | 2026-10-30 | 持倉中 | x |
| ✋ 使用者人手 | 富途期貨 | MHI2610 即日交易（對沖 1 手以外嘅手數） | 不定 | 人手 | 即日 | 不定 | x |
"""

print("\n=== POSITIONS.md 解析 ===")
reg, unparsed = db.parse_positions_md(POS_MD)
check("週權兩腳", reg.get("HK.HSI261016P23750000") == -1 and reg.get("HK.HSI261016C24900000") == -1, reg)
check("MHI 跨式兩腳", reg.get("HK.MHI261029C25000000") == -1 and reg.get("HK.MHI261029P25000000") == -1)
check("MHI2610 對沖 −1", reg.get("HK.MHI2610") == -1)
check("MES 第 3 個星期五 EX3", reg.get("US.EX32610C7830x0") == -1 and reg.get("US.EX32610P7830x0") == -1, reg)
check("HSI2610 賣 1 手 → −1", reg.get("HK.HSI2610") == -1)
check("EW P7750 −1", reg.get("US.EW2610P7750x0") == -1)
check("即日列唔算未解析", unparsed == [], unparsed)
reg2, _ = db.parse_positions_md(POS_MD.replace("賣 HSI2610 大恒指期貨 1 手 @24,333（10/13 人手再開）", "空手（24,321 開嘅 HSI2610 −1 手已平倉）").replace("持倉中（淨空 1 手）", "空手"))
check("蛇蟠空手 → 0", reg2.get("HK.HSI2610") == 0.0, reg2)
reg3, _ = db.parse_positions_md(POS_MD.replace("賣 HSI2610 大恒指期貨 1 手", "賣 HSI2610 大恒指期貨淨 −1 手"))
check("淨 −1 手寫法", reg3.get("HK.HSI2610") == -1)
check("nth_friday 10/16=3、10/2=1、10/30=5", db.nth_friday_code(date(2026, 10, 16)) == 3 and db.nth_friday_code(date(2026, 10, 2)) == 1 and db.nth_friday_code(date(2026, 10, 30)) == 5)

print("\n=== journal 期望 ===")
J = {
    ("claude/gifted-carson-v2tvhw", "journal/position.json"): json.dumps({"hsi": {"contract": "HSI2610", "real_pos": -1}}),
    ("claude/dazzling-curie-f3xzb8", "tradingview/data_external/position.json"): json.dumps(
        {"expiry": "2026-10-29", "strike": 25000, "qty": 1, "hedge_expected_mhi_qty": -1, "hedges": [{"contract": "MHI Oct-26 (MHI2610)"}]}),
    ("claude/dazzling-curie-f3xzb8", "tradingview/data_external/position_mes.json"): json.dumps({"expiry": "2026-10-16", "strike": 7830, "qty": 1}),
}
PAPER = "| 1 | 2026-10-10 01:44 | 24,329 | 16.5% | 565 | 23,750 @ 46 | 24,900 @ 36 | **82** | 2026-10-16 | — | — | — | — |\n| 0 | x | x | x | x | 23,000 @ 40 | 25,000 @ 30 | 70 | 2026-10-09 | 24,100 | 0 | 62 | 3,100 |\n"
jexp, jsrc = db.journal_expectations(fetch=lambda b, p: J.get((b, p)), paper_md=PAPER)
check("蛇蟠 real_pos", jexp.get("HK.HSI2610") == -1)
check("雲垂跨式＋對沖", jexp.get("HK.MHI261029C25000000") == -1 and jexp.get("HK.MHI2610") == -1)
check("雲垂 MES", jexp.get("US.EX32610P7830x0") == -1)
check("風揚本週（已結算嗰週唔計）", jexp.get("HK.HSI261016P23750000") == -1 and "HK.HSI261009P23000000" not in jexp, jexp)

print("\n=== 對帳 ===")
RISK = {"run_hkt": "2026-10-13 17:21", "metrics": {"equity": 3000000, "hard_stop": 750000, "gap": 2250000, "futu_equity": 500000,
        "maintenance_margin": 200000, "cushion": 300000, "pnl": 13975, "stop_use": {"HSI 月跨式": 0.39, "MES 跨式": 0.21, "EW P7750": 0.35}},
        "positions": [
            {"code": "HK.HSI2610", "qty": -1, "open_price": 24333, "last": 24373, "futu_pl": -2000},
            {"code": "HK.MHI2610", "qty": -1, "open_price": 24305, "last": 24373, "futu_pl": -680},
            {"code": "HK.MHI261029C25000000", "qty": -1, "futu_pl": 5210}, {"code": "HK.MHI261029P25000000", "qty": -1, "futu_pl": -3230},
            {"code": "HK.HSI261016C24900000", "qty": -1, "futu_pl": 1250}, {"code": "HK.HSI261016P23750000", "qty": -1, "futu_pl": 550},
            {"code": "US.EX32610C7830x0", "qty": -1, "futu_pl": 142.5}, {"code": "US.EX32610P7830x0", "qty": -1, "futu_pl": 327.5},
            {"code": "US.SPCX", "qty": 0.0846, "futu_pl": 13.67}]}
md, st, esc = db.reconcile(RISK, POS_MD, (jexp, jsrc), date(2026, 10, 13), {}, {})
check("全部 ✅ 除 EW", md.count("| ✅ |") == 8 and md.count("| ⚠ |") == 1, md)
check("EW 未解釋第 1 日", "US.EW2610P7750x0" in st["open"] and st["open"]["US.EW2610P7750x0"]["days"] == 1 and esc == [])
md2, st2, esc2 = db.reconcile(RISK, POS_MD, (jexp, jsrc), date(2026, 10, 14), st, {})
check("第 2 日未解釋 → 升級", esc2 and esc2[0]["code"] == "US.EW2610P7750x0" and esc2[0]["days"] == 2 and "升級" in md2, (esc2, st2))
md3, st3, esc3 = db.reconcile(RISK, POS_MD, (jexp, jsrc), date(2026, 10, 14), st, {"US.EW2610P7750x0": {"date": "2026-10-13", "reason": "API 唔回傳 CME 期權"}})
check("有解釋就唔升級、原因入表", esc3 == [] and "API 唔回傳 CME 期權" in md3)
RISK2 = json.loads(json.dumps(RISK)); RISK2["positions"][0]["qty"] = 1
md4, st4, esc4 = db.reconcile(RISK2, POS_MD, (jexp, jsrc), date(2026, 10, 13), {}, {})
check("富途 +1 vs 登記 −1 → ⚠（HSI 期貨預設歸人手，10-14）", "| HK.HSI2610 | 使用者人手 | 大恒指期貨（人手） | +1 | -1 | -1 | ⚠ |" in md4, md4)
check("SPCX 碎股唔入對帳", "SPCX" not in md)

print("\n=== 損益帳 ===")
DEALS = {"fetched_hkt": "2026-10-13 17:08", "closed": [
    {"code": "HK.MHI2610", "realized_ccy": 320, "ccy": "HKD"}, {"code": "HK.HSI2610", "realized_ccy": 5700, "ccy": "HKD"},
    {"code": "US.EX32610C7830x0", "realized_ccy": 100, "ccy": "USD"}]}
row = db.pnl_row(RISK, DEALS, [{"time_hkt": "2026-10-13 10:00:00", "realized": -50}, {"time_hkt": "2026-10-12 10:00:00", "realized": 999}], date(2026, 10, 13), "A")
check("雲垂當日已實現 320 + 100 USD", abs(row["real_雲垂陣"] - (320 + 100 * db.USD_HKD)) < 0.01, row)
check("HSI 期貨已實現 5,700、未實現 −2,000 歸人手；蛇蟠 0（10-14 規則）", row["real_使用者人手"] == 5700 and row["unreal_使用者人手"] == -2000
      and not row.get("real_蛇蟠陣") and not row.get("unreal_蛇蟠陣"), row)
check("雲垂未實現含 USD 換算", abs(row["unreal_雲垂陣"] - (-680 + 5210 - 3230 + (142.5 + 327.5) * db.USD_HKD)) < 0.01, row["unreal_雲垂陣"])
check("MT5 只計當日", row["mt5_realized_today"] == -50)
check("權益／緩衝入列", row["equity_total"] == 3000000 and row["cushion"] == 300000 and row["ladder"] == "A")
csv1 = db.upsert_csv(None, row)
csv2 = db.upsert_csv(csv1, dict(row, cushion=1))
check("同日重跑覆蓋、唔重複", csv2.count("2026-10-13") == 1 and ",1," in csv2 or csv2.rstrip().endswith("1") or "2026-10-13" in csv2, csv2)
rows = list(__import__("csv").DictReader(io.StringIO(csv2)))
check("csv 一列、cushion 已覆蓋", len(rows) == 1 and rows[0]["cushion"] == "1")

print("\n=== 風控階梯 ===")
lv, why = db.ladder_level(RISK, "", (), night=False)
check("現況 Ⓐ", lv == "A" and why == [])
R = json.loads(json.dumps(RISK)); R["metrics"]["cushion"] = 35000
check("緩衝 35k → Ⓑ（日間，10-14 線 37.5k）", db.ladder_level(R, "", (), night=False)[0] == "B")
check("緩衝 35k → Ⓒ（夜盤 ×1.5：< 37.5k）", db.ladder_level(R, "", (), night=True)[0] == "C")
R["metrics"]["cushion"] = 14000
check("緩衝 14k → Ⓓ", db.ladder_level(R, "", (), night=False)[0] == "D")
R2 = json.loads(json.dumps(RISK)); R2["metrics"]["gap"] = 0.15 * R2["metrics"]["equity"]
check("離硬止損 15% → Ⓒ", db.ladder_level(R2, "", (), night=False)[0] == "C")
R3 = json.loads(json.dumps(RISK)); R3["metrics"]["stop_use"]["HSI 月跨式"] = 0.85
lv3, why3 = db.ladder_level(R3, "", (), night=False)
check("止損用量 85% → Ⓒ 該策略", lv3 == "C" and any("HSI 月跨式" in w for w in why3))
check("偏離燈 🔴 → Ⓑ", db.ladder_level(RISK, "| 蛇蟠 | 🔴 | z −2.1 |", (), night=False)[0] == "B")
check("對帳升級 → Ⓑ", db.ladder_level(RISK, "", ("蛇蟠陣",), night=False)[0] == "B")
check("is_night 17:15 / 02:59 / 09:00", db.is_night(datetime(2026, 10, 13, 17, 15, tzinfo=db.HKT)) and db.is_night(datetime(2026, 10, 13, 2, 59, tzinfo=db.HKT)) and not db.is_night(datetime(2026, 10, 13, 9, 0, tzinfo=db.HKT)))
msg = db.ladder_message("D", ["x"], date(2026, 10, 13))
check("Ⓓ 訊息直接提示「而家平」", "而家平" in msg and "唔係落單指令" in msg)

print("\n=== 人手額度 ===")
why_m, info = db.manual_limits(RISK, DEALS)
check("人手名義 = HSI2610 1 手 × 24,373 × 50", info["manual_notional_hkd"] == round(24373 * 50) and info["codes"] == ["HK.HSI2610 -1"], info)
check("41% NAV 額度內", why_m == [], why_m)
R4 = json.loads(json.dumps(RISK)); R4["positions"][0]["qty"] = -2
why4, info4 = db.manual_limits(R4, DEALS)
check("2 手 → 名義 97% 超額", any("名義" in w for w in why4), why4)
R5 = json.loads(json.dumps(RISK)); R5["positions"][0]["futu_pl"] = -70000
why5, _ = db.manual_limits(R5, {"closed": []})
check("單日虧損 2.3% → 超額", any("單日虧損" in w for w in why5), why5)
check("POSITIONS 解析 MHI2611 小期／HSI2611 買", db.parse_positions_md("| ✋ 使用者人手 | 富途期貨 | 賣 MHI2611 小恒指期貨 10 手 @24,260 | x | y | z | 持倉中 | w |\n| 🐍 蛇蟠陣 | 富途期貨 | 買 HSI2611 大恒指期貨 2 手（x） | a | b | c | 持倉中 | d |")[0] == {"HK.MHI2611": -10.0, "HK.HSI2611": 2.0})
check("ES2612 −1 解析＋歸人手（10-14）", db.parse_positions_md("| ✋ 使用者人手 | 富途期貨 | 賣 ES2612 標普期貨 1 手 @7,803 | x | y | z | 持倉中 | w |")[0] == {"US.ES2612": -1.0}
      and db.split_by_cap("US.ES2612", -1) == [(db.TEAM_MANUAL, -1)])
check("MHI2611 全部歸人手（唔當雲垂對沖）", db.split_by_cap("HK.MHI2611", -10) == [(db.TEAM_MANUAL, -10)], db.split_by_cap("HK.MHI2611", -10))
check("MHI 超出對沖上限歸人手", db.split_by_cap("HK.MHI2610", -3) == [("雲垂陣", -1), (db.TEAM_MANUAL, -2)])

print("\n=== 私隱：公開版冇金額、Actions 日誌只印字數 ===")
import os, contextlib
why_pub = ["Ⓒ 減半：富途保證金緩衝 HK$95,000 < 100,000", "Ⓓ 全平：離硬止損只剩 9% < 10%"]
mw = ["人手名義 HK$1,300,000 ＝ NAV 52% > 50%"]
info_pub = {"nav": 3000000, "manual_notional_hkd": 1218450, "manual_realized_today_hkd": 5700, "manual_unrealized_hkd": -1800, "codes": ["HK.HSI2610 -1"]}
pub, priv = db.tail_sections("D", why_pub, mw, info_pub, False)
check("公開版冇 HK$ 金額", "HK$" not in pub and "1,218,450" not in pub and "95,000" not in pub, pub)
check("公開版冇 NAV 百分比", not re.search(r"NAV\s*\d", pub) and "只剩 9%" not in pub, pub)
check("公開版保留等級、合約、⚠ 字眼（下游 regex 用）", "Ⓓ 全平" in pub and "HK.HSI2610 -1" in pub and "## 人手交易額度" in pub and "⚠" in pub)
check("私人版有齊金額", "HK$1,218,450" in priv and "NAV 41%" in priv and "HK$95,000" in priv)
pub_ok, _ = db.tail_sections("A", [], [], info_pub, True)
check("額度內最後一行照舊（晨會簡報讀）", pub_ok.strip().splitlines()[-1].startswith("額度內 ✅") and "夜盤線" in pub_ok)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    os.environ["GITHUB_ACTIONS"] = "true"; db.print_private("權益 HK$3,000,000")
    os.environ.pop("GITHUB_ACTIONS"); db.print_private("本機 HK$1")
out = buf.getvalue()
check("Actions 唔印金額、本機照印", "3,000,000" not in out and "Actions 日誌公開" in out and "本機 HK$1" in out, out)

print("\n=== 補倉／提款 ===")
def tu(c, night=False):
    R = json.loads(json.dumps(RISK)); R["metrics"]["cushion"] = c
    lv, why = db.ladder_level(R, "", (), night=night)
    return lv, why, db.topup_advice(R, lv, why, night)
lv, why, t = tu(35000)
check("緩衝 35k（Ⓑ）→ 建議入金 1 萬補到 4.5 萬", lv == "B" and t and "HK$10,000" in t[0] and "HK$45,000" in t[0] and "17:15 前" in t[0], t)
lv, why, t = tu(23000)
check("緩衝 23k（Ⓒ）→ 30 分鐘內入金 3 萬可代替減半", lv == "C" and "30 分鐘內" in t[0] and "HK$30,000" in t[0], t)
lv, why, t = tu(14000)
check("緩衝 14k（Ⓓ）→ 唔接受補倉代替全平", lv == "D" and "唔接受補倉代替全平" in t[0], t)
lv, why, t = tu(35000, night=True)
check("夜盤 35k（Ⓒ）→ 目標 6.75 萬、入金 4 萬", lv == "C" and "HK$40,000" in t[0] and "HK$67,500" in t[0], t)
R3b = json.loads(json.dumps(RISK)); R3b["metrics"]["stop_use"]["HSI 月跨式"] = 0.85
lv3b, why3b = db.ladder_level(R3b, "", (), night=False)
t3b = db.topup_advice(R3b, lv3b, why3b, False)
check("止損用量觸發 Ⓒ → 補倉唔解決", any("補倉唔解決" in x for x in t3b) and not any("入金 HK$" in x for x in t3b), t3b)
lv, why, t = tu(400000)
check("Ⓐ 緩衝 40 萬 → 可提款上限 10 萬", lv == "A" and t and t[0].startswith("🏧") and "HK$100,000" in t[0], t)
lv, why, t = tu(250000)
check("Ⓐ 緩衝 25 萬（< 30 萬）→ 冇提款額", t == [], t)
pub_t, priv_t = db.tail_sections("A", [], [], info_pub, False, ["🏧 可提款上限 HK$100,000"])
check("提款上限只放私人版", "可提款" not in pub_t and "HK$100,000" in priv_t)
_, _, t = tu(35000)
pub_t, priv_t = db.tail_sections("B", ["Ⓑ 停開新倉：富途保證金緩衝 HK$35,000 < 37,500"], [], info_pub, False, t)
check("補倉建議公開版冇金額、私人版有", "💰 補倉" in pub_t and "HK$" not in pub_t and "HK$10,000" in priv_t, pub_t)
check("公開版最後一行照舊", pub_t.strip().splitlines()[-1].startswith("額度內 ✅"))
check("Ⓒ 訊息附補倉建議", "30 分鐘內" in db.ladder_message("C", ["x"], date(2026, 10, 13), tu(23000)[2]))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
