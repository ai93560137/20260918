"""[IDEAS #1125] 趨勢簿（927）心跳整合：分流、補入 10 月尾上季突破、回報、SL 後清倉、開關關咗唔出指令、/?format=json。GCS 用假 bucket。"""
import json, os, sys, types, unittest

os.environ.update(XAU_SERVER_TZ_RULE="off", WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", XAU_SYMBOL="XAUUSD",
                  ANTHROPIC_API_KEY="x", XAU_REVERSE_LIVE="0", XAU_TREND_LIVE="1", XAU_TREND_ADOPT="qbrk", XAU_ACCOUNT="")
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

import main as xau, config, trend_live as TL, storage   # noqa: E402

NOW = [20764 * 86400 + 3600.0]           # 2026-11-09 01:00 UTC
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



BAR = {"time": 20764 * 86400, "open": 4070.0, "high": 4072.0, "low": 4069.0, "close": 4071.0}


class Heartbeat(unittest.TestCase):
    def setUp(self):
        reset()

    def test_adopt_open_ack_then_sl_clears(self):
        r = hb(927, m1_ohlc=BAR, symbol="XAUUSD")
        self.assertEqual(r["book"], "trend")
        self.assertIn("open|SELL|0.01|sl=4328.18|tp=|magic=927", r["cmd_text"])
        cid = r["cmd_text"].split("id=")[1][:8]
        a = client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": cid, "ok": True, "ticket": 9, "account": "12345"})).get_json()
        self.assertEqual(a["status"], "acked")
        NOW[0] += 60
        pos = [{"ticket": 9, "side": "SELL", "entry": 4071.0, "lots": 0.01, "sl": 4328.18, "open_time": 0}]
        r = hb(927, positions=pos, m1_ohlc={**BAR, "time": BAR["time"] + 60}, symbol="XAUUSD")
        self.assertEqual(r["cmd_text"], ""); self.assertIn("有倉", r["message"])
        NOW[0] += 60
        r = hb(927, positions=[], m1_ohlc={**BAR, "time": BAR["time"] + 120}, symbol="XAUUSD")   # 伺服器端止蝕咗
        self.assertEqual(r["cmd_text"], "")
        st = TL.load_state()
        self.assertIsNone(st["pos"]); self.assertIn(TL.qkey(20764), st["adopted"])
        NOW[0] += 60
        r = hb(927, positions=[], m1_ohlc={**BAR, "time": BAR["time"] + 180}, symbol="XAUUSD")
        self.assertEqual(r["cmd_text"], "")                                                         # 唔會再補入

    def test_off_no_cmd(self):
        config.TREND_LIVE = False
        try:
            r = hb(927, m1_ohlc=BAR, symbol="XAUUSD")
            self.assertEqual(r["cmd_text"], ""); self.assertIn("未開", r["message"])
        finally:
            config.TREND_LIVE = True

    def test_wrong_product_no_cmd(self):
        r = hb(927, m1_ohlc=BAR, symbol="XAGUSD")
        self.assertEqual(r["cmd_text"], "")

    def test_status_json(self):
        hb(927, m1_ohlc=BAR, symbol="XAUUSD")
        s = client.get("/?format=json").get_json()
        self.assertEqual(s["trend_live"]["magic"], 927)


if __name__ == "__main__":
    unittest.main()
