"""scripts/morning_brief.py 的單元測試：只測各段的組字與容錯，不碰 GCS／Telegram。

執行：python3 -m unittest tests/test_morning_brief.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import morning_brief as mb  # noqa: E402

NOW = datetime(2026, 10, 14, 8, 30, tzinfo=mb.HKT)
RISK = {"run_hkt": "2026-10-14 08:16", "alerts": {},
        "metrics": {"equity": 3000000.0, "gap": 2250000.0, "hard_stop": 750000.0, "cushion": 400000.0,
                    "stop_use": {"HSI 月跨式": 0.85, "MES 跨式": 0.21},
                    "delta_parts": {"net_with_hedge": -0.44, "hsi_all": -5.47}}}
PNL = ("date,run_hkt,equity_total,unrealized_total,mt5_realized_today,unreal_雲垂陣,real_雲垂陣,unreal_蛇蟠陣,real_蛇蟠陣\n"
       "2026-10-12,2026-10-12 17:30,2980000,1000,0,0,0,0,0\n"
       "2026-10-13,2026-10-13 17:36,3000000,14240,0,6166.5,320,-1800,5700\n")
RECON = """# 每日對帳表 2026-10-13

| 合約 | 陣 | 用途 | 富途快照 | POSITIONS.md | 陣 journal | 狀態 | 原因／備註 |
|---|---|---:|---:|---:|---:|:-:|---|
| HK.HSI2610 | 蛇蟠陣 | 大恒指期貨（人手） | -1 | -1 | -1 | ✅ |  |
| US.EW2610P7750x0 | 使用者人手 | 標普 Put | — | -1 | — | ⚠ | 富途 API 唔回傳 CME 月底期權 |

## 人手交易額度
人手持倉：HK.HSI2610 -1
額度內 ✅（名義 ≤ NAV 50%、單日虧損 ≤ NAV 2%）
"""
POSITIONS = """| 陣 | 戶口 | 持倉 | 開倉 | 規則 | 完結 | 狀態 | 紀錄 |
|---|---|---|---|---|---|---|---|
| 🌬️ 風揚陣・方向一 | 富途期貨 | 沽 HSI 週期權 10/16：Put 23,750 @46 ＋ Call 24,900 @36（各 1 張） | x | x | 2026-10-16 現金結算 | 持倉中 | x |
| ✋ 使用者人手 | 富途期貨 | 沽 EW2610 P7,750 | x | x | 2026-10-30 | 持倉中 | x |
| ✋ 使用者人手 | 富途期貨 | MHI 即日 | 不定 | x | 即日 | 不定 | x |
"""
CANARY = "🐤 金絲雀每日總結 📅 2026-10-14\n\n🚦 三軸\n🟢 短期軸:綠,19 日|數字\n🔴 災難軸:紅|數字\n\n其他\n"
CAL = {"events": [{"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High"},
                  {"title": "Speech", "country": "USD", "date": "2026-10-14T09:00:00-04:00", "impact": "Low"},
                  {"title": "Old", "country": "USD", "date": "2026-10-10T08:30:00-04:00", "impact": "High"}]}


class SectionTests(unittest.TestCase):
    def test_risk(self):
        out = "\n".join(mb.section_risk(RISK, {"date": "2026-10-13", "level": "B", "why": ["緩衝 < 15 萬"]}, NOW))
        self.assertIn("Ⓑ 停開新倉", out)
        self.assertIn("緩衝 < 15 萬", out)
        self.assertIn("離硬止損 HK$2,250,000（75%）", out)
        self.assertIn("HSI 月跨式 85% ⚠", out)
        self.assertNotIn("數據舊", out)

    def test_risk_missing_and_stale(self):
        self.assertIn("讀不到 futu/risk/latest.json", "\n".join(mb.section_risk(None, None, NOW)))
        stale = dict(RISK, run_hkt="2026-10-13 17:36")
        self.assertIn("⚠ 數據舊", "\n".join(mb.section_risk(stale, None, NOW)))

    def test_canary(self):
        out = mb.section_canary(CANARY, date(2026, 10, 14))
        self.assertEqual(out[1:], ["🟢 短期軸:綠,19 日", "🔴 災難軸:紅"])
        self.assertIn("未出", "\n".join(mb.section_canary(CANARY, date(2026, 10, 15))))

    def test_pnl(self):
        out = "\n".join(mb.section_pnl(PNL))
        self.assertIn("蛇蟠陣 已實現 +5,700／未實現 -1,800", out)
        self.assertIn("合計權益對前一日 +20,000", out)
        self.assertIn("讀不到", "\n".join(mb.section_pnl(None)))

    def test_reconcile(self):
        out = "\n".join(mb.section_reconcile(RECON))
        self.assertIn("1 合約一致 ✅、1 不一致 ⚠", out)
        self.assertIn("US.EW2610P7750x0（使用者人手）", out)
        self.assertIn("人手：額度內 ✅", out)

    def test_divergence(self):
        md = "更新 2026-10-13\n| 策略 | 燈 |\n|---|---|\n| 蛇蟠 | ⚪ |\n| 雲垂 | 🟡 |\n"
        self.assertIn("🟡 雲垂", "\n".join(mb.section_divergence(md)))
        self.assertIn("全部 ⚪", "\n".join(mb.section_divergence(md.replace("🟡", "⚪"))))

    def test_events_and_expiry(self):
        out = "\n".join(mb.section_events(CAL, POSITIONS, NOW))
        self.assertIn("20:30 USD CPI m/m", out)
        self.assertNotIn("Speech", out)
        self.assertNotIn("Old", out)
        self.assertIn("⏳ 2 日後到期：🌬️ 風揚陣・方向一 沽 HSI 週期權 10/16：Put 23,750 @46 ＋ Call 24,900 @36（2026-10-16）", out)
        self.assertNotIn("EW2610", out)   # 16 日後，不列

    def test_events_from_calendar(self):
        csv_text = ("date,time_hkt,market,category,event,impact,affects,event_week,source\n"
                    "2026-10-14,20:30,USD,數據,CPI m/m,High,雲垂 MES,Y,FF\n"
                    "2026-10-15,08:30,AUD,數據,Employment Change,High,,Y,FF\n"
                    "2026-10-16,,持倉,持倉到期,🌬️ 風揚：沽 HSI 週期權 10/16,High,見事件,Y,POSITIONS.md\n"
                    "2026-10-19,全日,HK,HK 假期,HK 休市：重陽節補假,Holiday,風揚,Y,cal\n")
        out = "\n".join(mb.section_events(None, None, NOW, csv_text))
        self.assertIn("⚠ 本週係事件週：CPI m/m", out)
        self.assertIn("20:30 USD CPI m/m（雲垂 MES）", out)
        self.assertNotIn("Employment Change", out)          # 明日 08:30 已超過 24 小時
        self.assertIn("⏳ 2 日後（10-16）：🌬️ 風揚", out)
        self.assertNotIn("重陽", out)                       # 5 日後，不列
        self.assertIn("20:30 USD CPI m/m", "\n".join(mb.section_events(CAL, POSITIONS, NOW, "bad,header\n")))

    def test_settlement_and_todo(self):
        self.assertEqual(mb.hsi_settlement(date(2026, 10, 14)), date(2026, 10, 29))
        fri = "\n".join(mb.section_todo(date(2026, 10, 16)))
        self.assertIn("風揚方向一", fri)
        settle_week = "\n".join(mb.section_todo(date(2026, 10, 26)))
        self.assertIn("恒指月結算 10-29（尚餘 3 個交易日", settle_week)

    def test_build_survives_all_missing(self):
        text = mb.build(NOW, {k: None for k in ("risk", "ladder", "pnl", "calendar", "canary", "reconcile", "divergence", "positions")})
        self.assertIn("☀️ 晨會簡報 10-14（三）", text)
        self.assertIn("只係資訊、唔係落單指令", text)
        self.assertEqual(text.count("【"), 7)


class StressTest(unittest.TestCase):
    """壓力情景（總指揮 R193 格式；虛構數字）。"""
    ST = {"night": True, "lines": {"B": 56250, "C": 37500, "D": 22500}, "scenarios": [
        {"name": "HSI −5%", "cushion_after": 30000, "ladder": "C"},
        {"name": "ES +3%", "cushion_after": 90000, "ladder": "A"},
        {"name": "VIX +10", "cushion_after": 50000, "ladder": "B"},
        {"name": "ES −5% 且 IV +10", "cushion_after": 10000, "ladder": "D"},
        {"name": "HSI +5%", "cushion_after": 80000, "ladder": "A"}]}

    def test_lines_and_worst_four(self):
        self.assertIn("夜盤線 Ⓑ<HK$56,250", mb.ladder_lines(self.ST))
        out = mb.stress_lines(self.ST)
        self.assertTrue(out[0].startswith("⚠ "))
        self.assertTrue(out[0].index("ES −5% 且 IV +10") < out[0].index("HSI −5%"))
        self.assertNotIn("ES +3%", out[0])

    def test_missing_stress(self):
        self.assertEqual(mb.stress_lines(None), [])
        self.assertIn("RISK_LADDER", mb.ladder_lines(None))


if __name__ == "__main__":
    unittest.main()
