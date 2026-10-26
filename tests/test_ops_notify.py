"""scripts/ops_notify.py 的單元測試：只測純函式（訊息組成、去重、新鮮度），不碰 GCS／Telegram。

執行：python3 -m unittest tests/test_ops_notify.py -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import ops_notify as on  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ops", "notify_config.json")))
# 測試用 10-13 嘅設定（雲垂當時申報 MHI2610 −1 對沖）；線上設定 10-26 已改 0
LIVE_CFG = CFG
CFG = json.loads(json.dumps(CFG))
CFG["hedge"]["declared_hedge_lots"] = {"HK.MHI2610": -1.0}


def hkt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=on.HKT)


RISK = {"run_hkt": "2026-10-13 15:49",
        "metrics": {"mhi_lots": {"HK.MHI2610": -1.0, "HK.HSI2610": -1.0},
                    "delta_parts": {"straddle": 0.71, "net_with_hedge": -0.29, "hsi_all": -4.84}},
        "positions": [{"code": "HK.MHI2610", "qty": -1.0}]}


class HedgeTests(unittest.TestCase):
    def test_live_config_yunchui_no_hedge(self):   # 10-26 雲垂冇 MHI 對沖；MHI 倉全屬龍飛陣
        msg, _ = on.compose_hedge(RISK, {}, LIVE_CFG, hkt("2026-10-26 15:55"))
        self.assertIn("雲垂對沖申報 +0／其他 -1", msg)
        # 方案 a：即月 MHI 期貨歸龍飛；非即月、MHI 期權歸雲垂（10-29 前 2610 係即月，之後 2611）
        self.assertFalse(on.is_yunchui("HK.MHI2610", LIVE_CFG, "2026-10-26 22:10:00"))
        self.assertTrue(on.is_yunchui("HK.MHI2612", LIVE_CFG, "2026-10-26 22:10:00"))
        self.assertTrue(on.is_yunchui("HK.MHI261127C23200", LIVE_CFG, "2026-10-26"))
        self.assertFalse(on.is_yunchui("HK.MHI2611", LIVE_CFG, "2026-10-29 09:30:00"))
        self.assertTrue(on.is_yunchui("HK.MHI2611", LIVE_CFG, "2026-10-28 09:30:00"))

    def test_basic_line(self):
        msg, st = on.compose_hedge(RISK, {}, CFG, hkt("2026-10-13 15:55"))
        self.assertIn("🛡️ 對沖狀態 15:55", msg)
        self.assertIn("MHI2610 實際淨手數 -1｜雲垂對沖申報 -1／其他 +0", msg)
        self.assertIn("Δ 月跨式 +0.71、含對沖淨 -0.29、恒指全部 -4.84（MHI 手，界線 ±0.5）", msg)
        self.assertNotIn("淨手數有變動", msg)
        self.assertIn("只係資訊", msg)
        self.assertEqual(st["hedge"]["HK.MHI2610"], -1.0)

    def test_change_detected_and_other_lots(self):
        risk = json.loads(json.dumps(RISK)); risk["metrics"]["mhi_lots"]["HK.MHI2610"] = -3.0
        msg, st = on.compose_hedge(risk, {"hedge": {"HK.MHI2610": -1.0}}, CFG, hkt("2026-10-13 14:35"))
        self.assertIn("其他 -2", msg)
        self.assertIn("⚠ MHI2610 淨手數有變動：上次 -1，今次 -3", msg)

    def test_stale_flag(self):
        msg, _ = on.compose_hedge(RISK, {}, CFG, hkt("2026-10-13 16:30"))
        self.assertIn("⚠ 數據過期（auto_risk 可能停咗）", msg)

    def test_missing_snapshot(self):
        msg, _ = on.compose_hedge(None, {}, CFG, hkt("2026-10-13 14:35"))
        self.assertIn("讀不到", msg)

    def test_fallback_without_delta_parts(self):
        risk = {"run_hkt": "2026-10-13 14:30", "metrics": {"delta": {"雲垂": [-0.3, 0.5]}}, "positions": [{"code": "HK.MHI2610", "qty": -1.0}]}
        msg, _ = on.compose_hedge(risk, {}, CFG, hkt("2026-10-13 14:35"))
        self.assertIn("含對沖淨 -0.30", msg)
        self.assertIn("未升級 R154", msg)
        self.assertIn("實際淨手數 -1", msg)   # 從 positions 退回取 qty


DEALS = {"date": "2026-10-13", "fetched_hkt": "2026-10-13 17:08",
         "deals": [{"time_hkt": "2026-10-13 00:12:33", "code": "HK.HSI2610", "side": "賣", "qty": 1.0, "price": 24258.0, "order_id": "A1"},
                   {"time_hkt": "2026-10-13 10:05:00", "code": "HK.MHI2611", "side": "賣", "qty": 1.0, "price": 24305.0, "order_id": "B2"}],
         "closed": [{"code": "HK.MHI2611", "close_time_hkt": "2026-10-13 10:05:00", "qty": 1.0, "open_price": 24168.0,
                     "close_price": 24305.0, "side": "平多", "realized_pts": 137.0, "realized_ccy": 1370.0, "ccy": "HKD"},
                    {"code": "HK.HSI2610", "close_time_hkt": "2026-10-13 01:58:36", "qty": 1.0, "open_price": 24258.0,
                     "close_price": 24252.0, "side": "平空", "realized_pts": 6.0, "realized_ccy": 300.0, "ccy": "HKD"}]}


class DealsTests(unittest.TestCase):
    def test_day_run_yunchui_message(self):
        msg, st, rem = on.compose_deals({"2026-10-13": DEALS}, {}, CFG, hkt("2026-10-13 17:10"), "day")
        self.assertIsNone(rem)
        self.assertIn("→ 雲垂陣", msg)
        self.assertIn("HK.MHI2611 賣 1 @ 24305.0", msg)
        self.assertIn("24168.0 → 24305.0，+137 點，已實現 +1,370 HKD", msg)
        self.assertIn("其他合約（非雲垂）1 筆", msg)
        self.assertNotIn("HSI2610 平空", msg)   # 非雲垂的平倉不列
        self.assertEqual(set(st["deals"]["order_ids"]) & {"A1", "B2"}, {"A1", "B2"})
        self.assertIn("FIFO", msg)
        status = st["deals"]["status"]
        self.assertEqual(status["date"], "2026-10-13"); self.assertEqual(len(status["closed"]), 1)
        self.assertIn("24168.0 → 24305.0", status["summary_text"])

    def test_dedupe_second_run_silent(self):
        _, st, _ = on.compose_deals({"2026-10-13": DEALS}, {}, CFG, hkt("2026-10-13 17:10"), "day")
        msg, st2, rem = on.compose_deals({"2026-10-13": DEALS}, st, CFG, hkt("2026-10-13 17:40"), "day")
        self.assertIsNone(msg); self.assertIsNone(rem)

    def test_stale_fetched_reminder_only(self):
        d = dict(DEALS, fetched_hkt="2026-10-13 05:31")
        msg, st, rem = on.compose_deals({"2026-10-13": d}, {}, CFG, hkt("2026-10-13 17:10"), "day")
        self.assertIsNone(msg)
        self.assertIn("未到 16:35", rem)
        self.assertEqual(st, {})

    def test_missing_file_reminder(self):
        msg, st, rem = on.compose_deals({"2026-10-13": None}, {}, CFG, hkt("2026-10-13 17:10"), "day")
        self.assertIsNone(msg); self.assertIn("不存在", rem)

    def test_night_run_reads_two_days(self):
        yday = dict(DEALS, date="2026-10-12", deals=[{"time_hkt": "2026-10-12 23:50:00", "code": "US.MES2612", "side": "買",
                                                      "qty": 1.0, "price": 7850.0, "order_id": "C3"}], closed=[])
        today = dict(DEALS, fetched_hkt="2026-10-14 03:06", deals=[], closed=[])
        msg, st, rem = on.compose_deals({"2026-10-13": yday, "2026-10-14": today}, {}, CFG, hkt("2026-10-14 03:40"), "night")
        self.assertIsNone(rem)
        self.assertIn("夜盤", msg); self.assertIn("US.MES2612 買 1 @ 7850.0", msg)

    def test_only_non_yunchui_goes_to_user(self):
        d = dict(DEALS, deals=[DEALS["deals"][0]], closed=[])
        msg, st, rem = on.compose_deals({"2026-10-13": d}, {}, CFG, hkt("2026-10-13 17:10"), "day")
        self.assertIn("非雲垂合約，只列給使用者", msg)


class RepoCopyTests(unittest.TestCase):
    def test_repo_deals_doc_strips_money(self):
        _, st, _ = on.compose_deals({"2026-10-13": DEALS}, {}, CFG, hkt("2026-10-13 17:10"), "day")
        doc = on.repo_deals_doc(st["deals"]["status"])
        text = json.dumps(doc, ensure_ascii=False)
        self.assertNotIn("realized_ccy", text)
        self.assertNotIn("1370", text)
        self.assertEqual(doc["closed"][0]["close_price"], 24305.0)
        self.assertEqual(doc["closed"][0]["realized_pts"], 137.0)


class PickTaskTests(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(on.pick_task(hkt("2026-10-13 14:36")), "hedge")
        self.assertEqual(on.pick_task(hkt("2026-10-13 15:58")), "hedge")
        self.assertEqual(on.pick_task(hkt("2026-10-13 17:15")), "deals")
        self.assertEqual(on.pick_task(hkt("2026-10-14 03:45")), "deals")

    def test_pick_task_delayed_schedule(self):
        # GitHub schedule 遲 4–5 個鐘：按 cron 字串判斷，唔再誤判做 hedge
        self.assertEqual(on.pick_task(hkt("2026-10-22 21:13"), "10 9 * * 1-5"), "deals")
        self.assertEqual(on.pick_task(hkt("2026-10-22 08:43"), "40 19 * * 1-5"), "deals")
        self.assertEqual(on.pick_task(hkt("2026-10-22 20:29"), "55 7 * * 1-5"), "hedge")
        self.assertEqual(on.SCHEDULE_TASKS["40 19 * * 1-5"][1], "night")
        self.assertEqual(on.pick_task(hkt("2026-10-13 17:15"), ""), "deals")   # 手動觸發照舊按時間


if __name__ == "__main__":
    unittest.main()
