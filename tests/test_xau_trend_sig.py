"""[11-10 #1114] 訊號書服務（zhuge-xau-sig）趨勢簿：933 圖心跳分流去趨勢簿（唔去學生真倉）、回報 w 前綴、狀態寫 xau/sig/trend/、/?format=json。GCS 用假 bucket。"""
import json, os, sys, types, unittest

os.environ.update(XAU_SERVER_TZ_RULE="off", WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", XAU_SYMBOL="XAUUSD",
                  ANTHROPIC_API_KEY="x", XAU_REVERSE_LIVE="0", XAU_TREND_LIVE="1", XAU_TREND_RULES="mobrk", XAU_TREND_MAGIC="933", XAU_BOOK="signal",
                  XAU_ACCOUNT="", SIG_STUDENT_LIVE="1", SIG_STUDENT_EXECUTE="0")
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

_XAU = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
for _k in [k for k, v in list(sys.modules.items()) if os.path.realpath(getattr(v, "__file__", None) or "/").startswith(_XAU + os.sep)]:
    del sys.modules[_k]                          # [11-10 事故] 同其他測試一齊跑時，舊 storage 綁咗真 GCS → 寫咗真 bucket；一律重新匯入
import main as xau, config, trend_live as TL, storage   # noqa: E402
assert storage.storage is storage_mod and isinstance(storage._bucket(), _Bucket), "測試必須用假 GCS"   # [11-10 事故] 防寫真 bucket

NOW = [20768 * 86400 + 10 * 3600.0]      # 2026-11-13（星期五）10:00 UTC
xau.now_ts = lambda: NOW[0]
client = xau.app.test_client()
BAR = {"time": int(NOW[0]) - 60, "open": 4000.0, "high": 4001.0, "low": 3999.0, "close": 4000.5}


def hb(magic, positions=None, **extra):
    body = {"token": "tok", "action": "heartbeat", "magic": magic, "account": "12345", "equity": 30000, "daily_pnl": 0,
            "positions": positions or [], "trade_allowed": {"account": True, "ea": True, "terminal": True}, "symbol": "XAUUSD",
            "m1_ohlc": BAR, **extra}
    return client.post("/", data=json.dumps(body)).get_json()


def seed_month(break_up):
    """11-02..04 區間 3990–4010；11-05..12 喺區間內；11-13（今日）穿或者唔穿。"""
    d1 = {}
    for d in range(20759, 20769):                                  # 11-02（一）至 11-13（五）
        import datetime as dt
        if dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc).weekday() >= 5:
            continue
        rng = 10.0 if d <= 20761 else 5.0
        d1[str(d)] = {"o": 4000.0, "h": 4000.0 + rng, "l": 4000.0 - rng, "c": 4000.0, "t0": d * 86400, "t1": d * 86400}
    if break_up:
        d1["20768"]["h"] = 4012.0
    storage.write_json(TL.STATE_FILE, {**TL.empty_state(), "d1": d1})


class SigTrend(unittest.TestCase):
    def setUp(self):
        FAKE.clear()
        storage.write_json(config.PREFIX + "control.json", {"mode": "RUN"})
        TL.load_seed = lambda: {}

    def test_prefix_and_magic(self):
        self.assertTrue(config.SIGNAL_BOOK)
        self.assertEqual(TL.STATE_FILE, "xau/sig/trend/state.json")
        self.assertEqual(config.TREND_MAGIC, 933)

    def test_933_goes_to_trend_and_opens(self):
        seed_month(True)
        r = hb(933, m1_ohlc={**BAR, "high": 4012.0, "close": 4011.0})
        self.assertEqual(r["book"], "trend")
        self.assertIn("open|BUY|0.01|sl=3990.00|tp=|magic=933", r["cmd_text"])
        cid = r["cmd_text"].split("id=")[1][:8]
        a = client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": cid, "ok": True, "ticket": 7, "account": "12345"})).get_json()
        self.assertEqual(a["status"], "acked")
        self.assertEqual(TL.load_state()["used"]["mobrk"], TL.mkey(20768))

    def test_inside_range_no_cmd(self):
        seed_month(False)
        r = hb(933)
        self.assertEqual(r["book"], "trend"); self.assertEqual(r["cmd_text"], "")

    def test_off_falls_back_to_student(self):
        config.TREND_LIVE = False
        try:
            r = hb(933)
            self.assertNotEqual(r.get("book"), "trend")                 # 關咗就照舊交學生真倉（933）
        finally:
            config.TREND_LIVE = True

    def test_status_json(self):
        seed_month(False); hb(933)
        s = client.get("/?format=json").get_json()
        self.assertEqual(s["trend_live"]["magic"], 933); self.assertEqual(s["trend_live"]["rules"], ["mobrk"])


if __name__ == "__main__":
    unittest.main()
