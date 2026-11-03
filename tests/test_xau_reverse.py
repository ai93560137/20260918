"""[R369] 921 反向真倉（magic 926）：鏡像價位、事件處理、心跳／回報分流、開關、保險平倉、§6c、921 事件寫入閘。GCS 用假 bucket。"""
import json, os, sys, types, unittest

os.environ.update(XAU_SERVER_TZ_RULE="off", WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", XAU_SYMBOL="XAUUSD",
                  ANTHROPIC_API_KEY="x", XAU_REVERSE_LIVE="1", XAU_ACCOUNT="")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
try:
    import anthropic                             # noqa: F401
except ImportError:
    _an = types.ModuleType("anthropic")
    class _E(Exception):
        pass
    _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = _E; sys.modules["anthropic"] = _an
import google, google.cloud                      # noqa: E402
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def download_as_bytes(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0].encode("utf-8")
    def upload_from_string(self, data, *a, **k):
        gen = FAKE.get(self.name, (None, 0))[1] + 1
        FAKE[self.name] = (data, gen); self.generation = gen
class _Bucket:
    def blob(self, name): return _Blob(name)
    def get_blob(self, name): return _Blob(name) if name in FAKE else None
class _Client:
    def __init__(self, *a, **k): pass
    def bucket(self, name): return _Bucket()
if "google.cloud.storage" not in sys.modules or not hasattr(sys.modules["google.cloud.storage"], "Client"):
    pass
storage_mod = types.ModuleType("google.cloud.storage"); storage_mod.Client = _Client
sys.modules["google.cloud.storage"] = storage_mod; google.cloud.storage = storage_mod
exc_mod = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
exc_mod.PreconditionFailed = _PC; exc_mod.NotFound = KeyError
api_core = types.ModuleType("google.api_core"); api_core.exceptions = exc_mod
sys.modules["google.api_core"] = api_core; sys.modules["google.api_core.exceptions"] = exc_mod

import main as xau, config, reverse_live as RV, storage   # noqa: E402

NOW = [1792600000.0]
xau.now_ts = lambda: NOW[0]
client = xau.app.test_client()


def hb(magic, positions=None, **extra):
    body = {"token": "tok", "action": "heartbeat", "magic": magic, "account": "12345", "equity": 30000, "daily_pnl": 0,
            "positions": positions or [], "trade_allowed": {"account": True, "ea": True, "terminal": True},
            "m1_ohlc": {"close": 3950.0}, **extra}
    return client.post("/", data=json.dumps(body)).get_json()


def reset():
    FAKE.clear()
    storage.write_json(xau.CONTROL_FILE if hasattr(xau, "CONTROL_FILE") else config.PREFIX + "control.json", {"mode": "RUN"})


class Pure(unittest.TestCase):
    def test_magic_default(self):
        self.assertEqual(config.REVERSE_MAGIC, 926)
        self.assertTrue(RV.is_cmd("v1234567")); self.assertFalse(RV.is_cmd("a1234567"))

    def test_mirror(self):
        self.assertEqual(RV.mirror(1, 3940.0, 3965.0), (-1, 3965.0, 3940.0))     # 921 多 → 反向空，SL＝921 TP、TP＝921 SL
        self.assertEqual(RV.mirror(-1, 3960.0, 3930.0), (1, 3930.0, 3960.0))
        self.assertIsNone(RV.mirror(1, 3940.0, None))

    def test_plan(self):
        ev = {"id": "e1", "kind": "open", "ts": 100, "side921": 1, "stop921": 3940.0, "target921": 3965.0}
        acts, notes = RV.plan([ev], None, False, False, None, 150, ttl=180)
        self.assertEqual(acts[0][0], "open")
        acts, notes = RV.plan([ev], None, False, False, None, 400, ttl=180)          # 過期唔追
        self.assertEqual(acts, []); self.assertIn("唔追", notes["e1"])
        acts, notes = RV.plan([ev], {"ticket": 1}, False, False, None, 150, ttl=180)  # 已有倉
        self.assertEqual(acts, [])
        acts, notes = RV.plan([ev], None, False, False, "control＝PAUSE", 150, ttl=180)
        self.assertEqual(acts, []); self.assertIn("PAUSE", notes["e1"])
        cl = {"id": "e2", "kind": "close", "ts": 160, "reason": "止損"}
        acts, _ = RV.plan([cl], {"ticket": 1}, False, False, None, 170)
        self.assertEqual(acts, [("close", "止損")])
        acts, _ = RV.plan([ev, cl], None, False, False, None, 170, ttl=180)          # 同一心跳開完即平：開＋平
        self.assertEqual([a[0] for a in acts], ["open", "close"])

    def test_open_block_6c(self):
        acct = {"daily_pnl": -100, "bots_daily_pnl": -1500, "bots_floating": -200, "trade_allowed": {"a": True}}
        self.assertIsNone(RV.open_block("RUN", acct, principal=None))
        self.assertIn("§6c", RV.open_block("RUN", acct, principal=20000))            # 6% × 20000 = 1200 ≤ 1700
        self.assertIn("926 今日", RV.open_block("RUN", {"daily_pnl": -2500}))
        self.assertIn("dry_run", RV.open_block("RUN", {"dry_run": True}))

    def test_merge_keeps_new_events(self):
        fresh = {"events": [{"id": "a", "done": False}, {"id": "b", "done": False}]}
        mine = {"events": [{"id": "a", "done": True, "note": "x"}], "orders": [1]}
        out = RV.merge(fresh, mine)
        self.assertEqual([e["id"] for e in out["events"]], ["a", "b"])
        self.assertTrue(out["events"][0]["done"]); self.assertFalse(out["events"][1]["done"]); self.assertEqual(out["orders"], [1])


class Flow(unittest.TestCase):
    def setUp(self):
        reset()

    def test_open_then_close(self):
        RV.emit("open", NOW[0], side921=1, stop921=3940.0, target921=3965.0, price=3950.0, decision="d1")
        r = hb(926)
        self.assertIn("open|SELL|0.01|sl=3965.00|tp=3940.00|magic=926", r["cmd_text"])
        self.assertIn("|id=v", r["cmd_text"])
        cid = r["cmd_text"].rsplit("id=", 1)[1][:8]
        a = client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": cid, "ok": True, "ticket": 77, "account": "12345"})).get_json()
        self.assertEqual(a["status"], "acked")
        pos = [{"ticket": 77, "side": "SELL", "entry": 3950.0, "lots": 0.01, "sl": 3965.0, "tp": 3940.0, "open_time": NOW[0]}]
        NOW[0] += 60
        r = hb(926, positions=pos)
        self.assertEqual(r["cmd_text"], "")                                             # 已 ack、有倉，唔再發
        RV.emit("close", NOW[0], reason="921 AI 平倉")
        NOW[0] += 5
        r = hb(926, positions=pos)
        self.assertIn("close|all|magic=926", r["cmd_text"])

    def test_orphan_close(self):
        storage.write_json(xau.STATE_FILE, {"position": None})
        pos = [{"ticket": 9, "side": "BUY", "entry": 3950.0, "lots": 0.01, "sl": 3940.0, "tp": 3960.0, "open_time": NOW[0] - 3600}]
        r = hb(926, positions=pos)
        self.assertIn("close|all|magic=926", r["cmd_text"])
        self.assertIn("保險", r["message"])

    def test_off_sends_nothing(self):
        RV.emit("open", NOW[0], side921=1, stop921=3940.0, target921=3965.0, price=3950.0)
        old = config.REVERSE_LIVE
        try:
            config.REVERSE_LIVE = False
            r = hb(926)
            self.assertEqual(r["cmd_text"], ""); self.assertIn("未開", r["message"])
        finally:
            config.REVERSE_LIVE = old

    def test_926_heartbeat_not_921(self):
        storage.write_json(xau.ACCOUNT_FILE, {"equity": 1, "positions": []})
        hb(926, positions=[{"ticket": 5, "side": "SELL", "entry": 1, "lots": 0.01, "sl": 2, "tp": 0.5, "open_time": NOW[0]}])
        self.assertEqual(storage.read_json(xau.ACCOUNT_FILE, {}).get("equity"), 1)       # 921 戶口快照冇畀 926 心跳覆寫
        self.assertTrue(storage.read_json(RV.ACCOUNT_FILE, {}).get("positions"))

    def test_emit_gate(self):
        old = config.EXECUTE
        try:
            config.EXECUTE = True                                                       # 921 真倉時唔出反向事件（避免同戶口對沖）
            xau._reverse_emit("open", NOW[0], side921=1, stop921=1.0, target921=2.0, price=1.5)
            self.assertEqual(RV.load_state()["events"], [])
        finally:
            config.EXECUTE = old
        xau._reverse_emit("open", NOW[0], side921=1, stop921=1.0, target921=2.0, price=1.5)
        self.assertEqual(len(RV.load_state()["events"]), 1)

    def test_risk_sizing(self):
        old = (config.RISK_SIZING, config.REVERSE_RISK_PCT, config.REVERSE_MAX_LOTS)
        try:
            config.RISK_SIZING, config.REVERSE_RISK_PCT, config.REVERSE_MAX_LOTS = True, 2.0, 0.10
            n, info = RV.size(30000, 3950.0, 3965.0)            # 600 HKD ÷（15 × 100 × 7.8＝11,700／手）＝0.051 → 0.05
            self.assertAlmostEqual(n, 0.05); self.assertEqual(info["mode"], "risk")
            n, _ = RV.size(3_000_000, 3950.0, 3965.0)           # 夾 0.10 上限
            self.assertAlmostEqual(n, 0.10)
            n, info = RV.size(3000, 3950.0, 3965.0)             # 60 HKD 唔夠 0.01 手 → 唔開
            self.assertEqual(n, 0.0)
            RV.emit("open", NOW[0], side921=1, stop921=3940.0, target921=3965.0, price=3950.0)
            r = hb(926)
            self.assertIn("open|SELL|0.05|sl=3965.00|tp=3940.00|magic=926", r["cmd_text"])
        finally:
            config.RISK_SIZING, config.REVERSE_RISK_PCT, config.REVERSE_MAX_LOTS = old

    def test_status_json(self):
        s = client.get("/?format=json").get_json()
        self.assertIn("reverse_live", s)
        self.assertEqual(s["reverse_live"]["magic"], 926)


class Fallback(unittest.TestCase):
    """[R370] 921 圖冇心跳 → 用 926 心跳 K 線餵 921 影子。"""
    def setUp(self):
        reset()
        self.seed = [self.bar(int(NOW[0]) // 60 * 60 - 120)]          # 921 圖之前留低嘅金價 K 線（價錢核對參考）
        storage.write_json(xau.M1_FILE, self.seed)

    def bar(self, t, new=True):
        return {"time": t, "open": 3950.0, "high": 3951.0, "low": 3949.0, "close": 3950.5, "is_new_bar": new}

    def test_fallback_feeds_921(self):
        t = int(NOW[0]) // 60 * 60
        r = hb(926, m1_ohlc=self.bar(t))
        self.assertTrue(RV.load_state()["last"]["fed_921"])
        m1 = storage.read_json(xau.M1_FILE, [])
        self.assertEqual(m1[-1]["time"], t)                                             # 921 M1 歷史收到 926 嘅 K 線
        self.assertEqual(storage.read_json(xau.ACCOUNT_FILE, None), None)               # 921 戶口快照冇被寫
        self.assertEqual(r["status"], "monitoring")

    def test_921_alive_no_fallback(self):
        storage.write_json(xau.ACCOUNT_FILE, {"received_ts": NOW[0] - 30, "positions": []})
        t = int(NOW[0]) // 60 * 60
        hb(926, m1_ohlc=self.bar(t))
        self.assertFalse(RV.load_state()["last"]["fed_921"])
        self.assertEqual(storage.read_json(xau.M1_FILE, []), self.seed)

    def test_dedup_same_bar(self):
        t = int(NOW[0]) // 60 * 60
        hb(926, m1_ohlc=self.bar(t))
        n1 = len(storage.read_json(xau.M1_FILE, []))
        resp = xau._feed_bars({"m1_ohlc": self.bar(t)}, {}, 0, NOW[0])                   # 921 圖重開送同一根
        self.assertEqual(resp.get("message"), "duplicate M1 bar")
        self.assertEqual(len(storage.read_json(xau.M1_FILE, [])), n1)

    def test_execute_never_fallback(self):
        old = config.EXECUTE
        try:
            config.EXECUTE = True
            self.assertFalse(xau.shadow_feed({"m1_ohlc": self.bar(int(NOW[0]) // 60 * 60)}, NOW[0]))
        finally:
            config.EXECUTE = old

    def test_cmd_text_unaffected(self):
        RV.emit("open", NOW[0], side921=1, stop921=3940.0, target921=3965.0, price=3950.0)
        r = hb(926, m1_ohlc=self.bar(int(NOW[0]) // 60 * 60))
        self.assertIn("open|SELL|", r["cmd_text"]); self.assertIn("magic=926", r["cmd_text"])

    def test_wrong_symbol_no_fallback_no_cmd(self):
        """11-03：926 圖掛咗 XAGUSD → 唔餵 921、唔出反向指令。"""
        RV.emit("open", NOW[0], side921=1, stop921=3940.0, target921=3965.0, price=3950.0)
        silver = {"time": int(NOW[0]) // 60 * 60, "open": 49.4, "high": 49.5, "low": 49.3, "close": 49.48, "is_new_bar": True}
        r = hb(926, m1_ohlc=silver, symbol="XAGUSD")
        self.assertFalse(RV.load_state()["last"]["fed_921"])
        self.assertEqual(storage.read_json(xau.M1_FILE, []), self.seed)
        self.assertEqual(r["cmd_text"], "")
        self.assertIn("唔係 XAUUSD", RV.load_state()["last"]["note"])

    def test_price_check_when_no_symbol(self):
        self.assertFalse(xau.product_ok({"m1_ohlc": {"close": 49.48}}))
        self.assertTrue(xau.product_ok({"m1_ohlc": {"close": 3952.0}}))
        self.assertFalse(xau.product_ok({"m1_ohlc": {"close": 3950.5 * 1.025}}))          # 差 > 2% 當錯產品
        self.assertFalse(xau.product_ok({"symbol": "XAGUSD", "m1_ohlc": {"close": 3950.0}}))

    def test_wrong_symbol_telegram_throttled(self):
        sent = []
        old = xau.notify.tg_send
        try:
            xau.notify.tg_send = lambda t: sent.append(t) or True
            silver = {"time": int(NOW[0]) // 60 * 60, "close": 49.48, "is_new_bar": True}
            hb(926, m1_ohlc=silver); hb(926, m1_ohlc=silver)            # 冇 symbol：靠價錢同 921 舊 K 線比
            self.assertEqual(storage.read_json(xau.M1_FILE, []), self.seed)
            self.assertEqual(len(sent), 1); self.assertIn("926", sent[0])
        finally:
            xau.notify.tg_send = old
        self.assertTrue(xau.product_ok({"symbol": "XAUUSD.s"}))
        FAKE.clear()
        self.assertFalse(xau.product_ok({"m1_ohlc": {"close": 3950.0}}, strict=True))      # 冇舊 K 線：餵 921 唔冒險


if __name__ == "__main__":
    unittest.main()
