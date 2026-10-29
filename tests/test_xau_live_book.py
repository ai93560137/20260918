"""[R352] 真倉成交簿：開倉快照、平倉用 realized_total 差額記一筆、換 ticket、後備參考點、跟單頻道補返、指標、補登合併、頁面段落。"""
import os, sys, unittest

os.environ.setdefault("XAU_SYMBOL", "XAUUSD")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import config, live_book, page   # noqa: E402

POS = {"ticket": 981, "side": -1, "lots": 0.05, "entry": 4006.78, "stop": 4015.20, "target": 3999.50, "opened_ts": 1793296794.0}


class Track(unittest.TestCase):
    def test_open_then_close(self):
        st = {}
        self.assertEqual(live_book.track(st, None, None, -305.70, now=1), [])
        self.assertEqual(st["book_ref"], -305.70)
        live_book.track(st, None, POS, -305.70, now=2, extra=lambda p: {"decision_price": 4008.33})
        self.assertEqual(st["book_open"]["stop"], 4015.20)
        moved = {**POS, "stop": 4010.0}                       # 之後移止損：R 仍用初始止損
        live_book.track(st, POS, moved, -305.70, now=3)
        self.assertEqual(st["book_open"]["stop"], 4015.20)
        out = live_book.track(st, moved, None, -636.02, now=4)
        self.assertEqual(len(out), 1)
        t = out[0]
        self.assertEqual(t["pnl_hkd"], -330.32)
        self.assertAlmostEqual(t["exit_est"], 4006.78 + 330.32 / config.HKD_PER_USD / 5, places=2)
        self.assertAlmostEqual(t["exit_est"], 4015.25, places=2)
        self.assertEqual(t["r"], -1.23)                          # 分母＝決策價 4008.33 到初始止損 4015.20（6.87），同 TEST_RESULTS L19 一致
        self.assertEqual(t["decision_price"], 4008.33)
        self.assertEqual(st["book"], out)
        self.assertNotIn("book_open", st)
        self.assertEqual(st["book_ref"], -636.02)

    def test_ticket_switch_counts_as_close(self):
        st = {"book_ref": 0.0}
        live_book.track(st, None, POS, 0.0, now=1)
        new = {**POS, "ticket": 982, "side": 1, "entry": 4000.0, "stop": 3995.0}
        out = live_book.track(st, POS, new, 100.0, now=2)
        self.assertEqual([x["pnl_hkd"] for x in out], [100.0])
        self.assertEqual(st["book_open"]["ticket"], 982)
        self.assertEqual(st["book_ref"], 100.0)

    def test_fallback_ref_from_ladder(self):
        st = {"lots_realized_ref": -44.41}
        out = live_book.track(st, POS, None, -305.70, now=5)
        self.assertEqual(out[0]["pnl_hkd"], -261.29)

    def test_no_ref_no_record(self):
        st = {}
        self.assertEqual(live_book.track(st, POS, None, -10.0, now=5), [])
        self.assertEqual(st["book_ref"], -10.0)

    def test_missing_realized_skips(self):
        st = {"book_ref": 0.0}
        self.assertEqual(live_book.track(st, POS, None, None, now=5), [])
        self.assertEqual(st["book_ref"], 0.0)

    def test_extra_filled_later(self):
        st = {"book_ref": 0.0}
        live_book.track(st, None, POS, 0.0, extra=lambda p: {})
        live_book.track(st, POS, POS, 0.0, extra=lambda p: {"ch": "5231", "decision_price": 4007.0})
        out = live_book.track(st, POS, None, 50.0)
        self.assertEqual((out[0]["ch"], out[0]["decision_price"]), ("5231", 4007.0))

    def test_max_kept(self):
        st = {"book": [{"closed_ts": i, "pnl_hkd": 1.0} for i in range(live_book.MAX)], "book_ref": 0.0}
        live_book.track(st, POS, None, 5.0, now=10 ** 10)
        self.assertEqual(len(st["book"]), live_book.MAX)
        self.assertEqual(st["book"][-1]["pnl_hkd"], 5.0)


class Summary(unittest.TestCase):
    def test_metrics_and_merge(self):
        seed = [{"closed_ts": 100, "pnl_hkd": 200.0, "r": 1.0}, {"closed_ts": 200, "pnl_hkd": -100.0, "r": -1.0}]
        book = [{"closed_ts": 150, "pnl_hkd": 999.0}, {"closed_ts": 300, "pnl_hkd": 0.0}, {"closed_ts": 400, "pnl_hkd": -150.0, "r": -1.2}]
        rows = live_book.merged(book, seed)
        self.assertEqual([r["closed_ts"] for r in rows], [100, 200, 300, 400])   # 成交簿只取 seed 最後一筆之後
        sm = live_book.summary(rows, now=400, day_key=lambda ts: ts // 1000, week_key=lambda ts: ts // 1000)
        self.assertEqual((sm["n"], sm["wins"], sm["losses"], sm["flat"]), (4, 1, 2, 1))
        self.assertEqual(sm["pf"], round(200 / 250, 2))
        self.assertEqual(sm["max_dd"], 250.0)
        self.assertEqual(sm["total"], -50.0)
        self.assertEqual(sm["avg_r"], round((1 - 1 - 1.2) / 3, 2))
        self.assertEqual(sm["today"], -50.0)

    def test_empty(self):
        sm = live_book.summary([])
        self.assertEqual((sm["n"], sm["win_rate"], sm["pf"], sm["max_dd"]), (0, None, None, None))


class Page(unittest.TestCase):
    def test_section(self):
        st = {"book_ref": -305.70}
        live_book.track(st, None, POS, -305.70, now=1793296800, extra=lambda p: {"decision_price": 4008.33})
        live_book.track(st, POS, None, -636.02, now=1793301900)
        v = live_book.view(st, [], {"daily_pnl": -20.82, "realized_total": -636.02}, now=1793301900)
        html_ = page.live_book_section("💰 真倉績效・921（AI 自主）", v)
        for frag in ("真倉績效", "-330.32", "HK$-636.02", "HK$-20.82", "決策 4008.33", "估", "已平倉逐筆"):
            self.assertIn(frag, html_)
        self.assertNotIn("<th>頻道</th>", html_)

    def test_section_none(self):
        self.assertEqual(page.live_book_section("x", None), "")


class Breakdown(unittest.TestCase):
    def test_groups_921(self):
        rows = [{"closed_ts": 10, "opened_ts": 1793296740, "side": -1, "lots": 0.05, "pnl_hkd": -330.32, "r": -1.23},
                {"closed_ts": 20, "opened_ts": 1793245980, "side": -1, "lots": 0.05, "pnl_hkd": 372.28, "r": 1.49},
                {"closed_ts": 30, "opened_ts": 1793180000, "side": 1, "lots": 0.01, "pnl_hkd": 76.0, "r": 1.5}]
        v = live_book.view({}, rows, {}, now=40)
        names = [g for g, _ in v["groups"]]
        self.assertEqual(names, ["方向", "開倉時段", "手數"])
        side = dict(v["groups"][0][1])
        self.assertEqual(side["淡（SELL）"]["n"], 2)
        self.assertEqual(side["淡（SELL）"]["total"], 41.96)
        self.assertEqual(live_book.session_of(1793296740), "紐約（13–22 UTC）")     # 17:59 UTC
        self.assertEqual(live_book.session_of(1793245980), "亞洲（22–07 UTC）")     # 03:53 UTC
        html_ = page.live_book_section("921", v)
        self.assertIn("按方向細分", html_)
        self.assertIn("按開倉時段細分", html_)
        self.assertIn("dec-scroll", html_)

    def test_groups_932_by_channel(self):
        rows = [{"closed_ts": 1, "side": 1, "pnl_hkd": 929.69, "ch": "0342", "r": 0.84},
                {"closed_ts": 2, "side": 1, "pnl_hkd": -1261.53, "ch": "0342", "r": -1.02},
                {"closed_ts": 3, "side": -1, "pnl_hkd": 203.55, "ch": "5231", "r": 0.31}]
        v = live_book.view({}, rows, {}, now=5)
        self.assertEqual([g for g, _ in v["groups"]], ["頻道", "方向"])
        ch = dict(v["groups"][0][1])
        self.assertEqual(ch["…0342 Gold Brother"]["total"], -331.84)
        self.assertEqual(ch["…5231 CTC"]["wins"], 1)


class Forward(unittest.TestCase):
    def test_forward_section(self):
        summ = lambda n, w, f, l, r, pf, dd: {"n": n, "win": w, "flat": f, "loss": l, "sum_r": r, "pf": pf, "max_dd_r": dd}
        fw = {"gb": {"meta": {"run_utc": "2026-10-29T1842Z", "bars_to": "2026-10-29 18:40"},
                     "eval": {"0342": {"name": "Gold Brother", "candidate": "V13", "done": 5, "pending": 0, "verdict": "未夠 5／20 張",
                                       "result": {"V0": {"name": "基準", "summary": summ(5, 0, 4, 1, -1.0, 0.0, -1.0)},
                                                  "V13": {"name": "SL 10 TP 10", "summary": summ(5, 1, 0, 4, -1.51, 0.25, -1.51)}}}}},
              "student": {"own": {"rule:rev15": {"filled": 89, "win": 47, "sl": 39, "r_sum": 27.34}}}}
        book = {"rows": [{"opened_ts": 1793296794, "side": -1, "entry": 4006.78, "decision_price": 4008.33},
                         {"opened_ts": 1793289474, "side": -1, "entry": 4014.94, "decision_price": 4014.77}]}
        h = page.forward_section(fw, book)
        for frag in ("前向測試", "V13 ⭐候選", "-1.51", "未夠 5／20 張", "rev15", "89／100", "+0.31", "2／20", "+1.55", "已觸發 P3"):
            self.assertIn(frag, h)

    def test_forward_bad_data(self):
        self.assertIn("讀唔到", page.forward_section({"gb": {"eval": {"0342": {"result": {"V0": {}}}}}}))
        self.assertEqual(page.forward_section(None), "")


class S1Reserved(unittest.TestCase):
    def test_signal_page_931_reserved(self):
        keep = (config.SIGNAL_BOOK, config.SIG_DECIDE, config.SIG_S1_OPEN)
        try:
            config.SIGNAL_BOOK, config.SIG_DECIDE, config.SIG_S1_OPEN = True, True, False
            s = {"execute": True, "signals": {}, "live_book": live_book.view({}, [], {}), "live_book_follow": live_book.view({}, [], {})}
            h = page.render_signal_book(s)
            self.assertIn("S1 停開新倉；規則學生過門檻（11-25）後再定", h)
            self.assertNotIn("真倉績效・931", h)
            config.SIG_S1_OPEN = True
            h = page.render_signal_book(s)
            self.assertIn("S1 運行中（0 張）；規則學生過門檻（11-25）後再定", h)
        finally:
            config.SIGNAL_BOOK, config.SIG_DECIDE, config.SIG_S1_OPEN = keep


if __name__ == "__main__":
    unittest.main()
