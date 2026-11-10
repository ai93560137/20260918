"""[11-10 穩陣組 937–941] 訊號書多本趨勢簿：magic 937 心跳去自己簿、D1 收市規則開倉、回報跨簿搵、busy、到期。GCS 用假 bucket。
舊：[11-10 #1114] 訊號書服務（zhuge-xau-sig）趨勢簿：933 圖心跳分流去趨勢簿（唔去學生真倉）、回報 w 前綴、狀態寫 xau/sig/trend/、/?format=json。GCS 用假 bucket。"""
import json, os, sys, types, unittest

os.environ.update(XAU_SERVER_TZ_RULE="off", WEBHOOK_SECRET_TOKEN="tok", XAU_EXECUTE="0", XAU_SYMBOL="XAUUSD",
                  ANTHROPIC_API_KEY="x", XAU_REVERSE_LIVE="0", XAU_TREND_LIVE="1", XAU_TREND_RULES="mobrk", XAU_TREND_MAGIC="933", XAU_BOOK="signal", XAU_TREND_BOOKS="937:wide,938:spike",
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

import trend_d1rules as D1R   # noqa: E402

DAY = 20768                                   # 2026-11-13（星期五）
NOW = [DAY * 86400 + 10 * 60.0]               # 00:10 UTC：新一日第一批心跳
xau.now_ts = lambda: NOW[0]
client = xau.app.test_client()


def bar(px):
    return {"time": int(NOW[0]) - 60, "open": px, "high": px + 0.5, "low": px - 0.5, "close": px}


def hb(magic, px, positions=None):
    body = {"token": "tok", "action": "heartbeat", "magic": magic, "account": "12345", "equity": 30000, "daily_pnl": 0,
            "positions": positions or [], "trade_allowed": {"account": True, "ea": True, "terminal": True}, "symbol": "XAUUSD", "m1_ohlc": bar(px)}
    return client.post("/", data=json.dumps(body)).get_json()


def seed(book_magic, wide_day=True):
    """30 個完成日幅度 10；最後一個完成日（DAY−1）寬幅收陽 3990–4030。"""
    d1 = {}
    for d in range(DAY - 30, DAY):
        d1[str(d)] = {"o": 4000.0, "h": 4005.0, "l": 3995.0, "c": 4000.0, "t0": d * 86400, "t1": d * 86400 + 3600}
    if wide_day:
        d1[str(DAY - 1)] = {"o": 4000.0, "h": 4030.0, "l": 3990.0, "c": 4028.0, "t0": (DAY - 1) * 86400, "t1": (DAY - 1) * 86400 + 3600}
    bk = TL.book_for(book_magic)
    storage.write_json(bk.state_file, {**TL.empty_state(), "d1": d1})
    return bk


class Books(unittest.TestCase):
    def setUp(self):
        FAKE.clear()
        storage.write_json(config.PREFIX + "control.json", {"mode": "RUN"})
        TL.load_seed = lambda: {}

    def test_books_parsed(self):
        self.assertEqual([(b.magic, b.rules) for b in TL.books()], [(933, ("mobrk",)), (937, ("wide",)), (938, ("spike",))])
        self.assertEqual(TL.book_for(937).state_file, "xau/sig/trend/937/state.json")

    def test_wide_opens_on_own_magic_and_ack_across_books(self):
        bk = seed(937)
        r = hb(937, 4028.5)
        self.assertEqual(r["book"], "trend"); self.assertEqual(r["magic"], 937)
        self.assertIn("open|BUY|0.01|sl=4010.00|tp=|magic=937", r["cmd_text"])     # SL＝寬幅日中位
        cid = r["cmd_text"].split("id=")[1][:8]
        a = client.post("/", data=json.dumps({"token": "tok", "action": "cmd_ack", "id": cid, "ok": True, "ticket": 9, "account": "12345"})).get_json()
        self.assertEqual(a["status"], "acked")
        st = storage.read_json(bk.state_file, None)
        self.assertEqual(st["used"]["wide"], DAY - 1); self.assertEqual(st["pos"]["period"], DAY - 1)
        self.assertIsNone(storage.read_json(TL.STATE_FILE, None))               # 933 主簿冇被寫
        self.assertEqual(hb(937, 4029.0)["cmd_text"], "")                         # 同一根唔再開

    def test_other_book_no_signal(self):
        seed(938)                                       # 938 spike：收市升 28 ≥ 1.5×ATR 但冇 SMA50（得 30 日）→ 冇訊號
        self.assertEqual(hb(938, 4028.5)["cmd_text"], "")

    def test_busy_blocks_same_bar_after_stop(self):
        bk = seed(937)
        st = storage.read_json(bk.state_file, None); st["busy"] = {"wide": DAY - 1}; storage.write_json(bk.state_file, st)
        self.assertEqual(hb(937, 4028.5)["cmd_text"], "")

    def test_status_extra(self):
        seed(937)
        s = client.get("/?format=json").get_json()
        self.assertEqual([b["magic"] for b in s["trend_books"]], [937, 938])
        self.assertEqual(s["trend_live"]["magic"], 933)

    def test_backfill_skips_closed_window_and_repairs(self):
        bk = TL.book_for(937)
        sun = 20758                                         # 2026-11-01 星期日
        bad = {"o": 3872.58, "h": 3902.14, "l": 3871.8, "c": 3898.26, "t0": sun * 86400, "t1": sun * 86400 + 86340}
        storage.write_json(config.PREFIX + "bars/2026-11-01.jsonl", [
            {"time": 0, "utc": sun * 86400 + 60, "open": 3872.0, "high": 3873.0, "low": 3871.8, "close": 3872.5},            # 休市時段（假）
            {"time": 0, "utc": sun * 86400 + 23 * 3600, "open": 3880.74, "high": 3885.0, "low": 3879.82, "close": 3884.0}])  # 真開市
        st = {**TL.empty_state(), "d1": {str(sun): bad}}
        TL.load_seed = lambda: {}
        with TL.use(bk):
            TL.backfill_d1(st, (sun + 5) * 86400)
        r = st["d1"][str(sun)]
        self.assertEqual((r["o"], r["l"], r["t0"]), (3880.74, 3879.82, sun * 86400 + 23 * 3600))
        self.assertTrue(TL.closed_window(sun * 86400 + 60)); self.assertFalse(TL.closed_window(sun * 86400 + 23 * 3600))
        self.assertTrue(TL.closed_window((sun - 1) * 86400 + 12 * 3600)); self.assertFalse(TL.closed_window((sun - 2) * 86400 + 20 * 3600))

    def test_plan_exit_expiry_and_rule(self):
        days = [(d, {"o": 4000.0, "h": 4005.0, "l": 3995.0, "c": 4000.0}) for d in range(100, 140)]
        self.assertIsNone(D1R.plan_exit({"rule": "wide", "side": 1, "period": 135}, days))       # 136–139：4 根
        self.assertEqual(D1R.plan_exit({"rule": "wide", "side": 1, "period": 134}, days), "5 根 D1 到期")
        days2 = days[:-1] + [(139, {"o": 4000.0, "h": 4001.0, "l": 3980.0, "c": 3985.0})]
        self.assertEqual(D1R.plan_exit({"rule": "spike", "side": 1, "period": 137}, days2), "收市穿 5 日相反極端")


if __name__ == "__main__":
    unittest.main()
