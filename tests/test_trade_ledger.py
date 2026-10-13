"""[R171] 已實現盈虧帳本：MT5 心跳的 balance 變動 → GCS logs/trade_ledger.json 一列。

執行：python3 tests/test_trade_ledger.py
"""
import json, os, sys, types
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")
import functions_framework, google, google.cloud  # noqa: F401  實際套件在，只替換 GCS 與 genai
FAKE = {}
class _Blob:
    def __init__(s, n): s.name = n; s.generation = FAKE.get(n, (None, 0))[1]
    def exists(s): return s.name in FAKE
    def download_as_text(s, *a, **k):
        if s.name not in FAKE: raise KeyError(s.name)
        return FAKE[s.name][0]
    def download_as_bytes(s, *a, **k): return s.download_as_text().encode()
    def upload_from_string(s, d, *a, **k):
        g = FAKE.get(s.name, (None, 0))[1] + 1; FAKE[s.name] = (d, g); s.generation = g
    def reload(s): s.generation = FAKE.get(s.name, (None, 0))[1]
class _Bucket:
    def blob(s, n): return _Blob(n)
    def get_blob(s, n): return _Blob(n) if n in FAKE else None
class _Client:
    def __init__(s, *a, **k): pass
    def bucket(s, n): return _Bucket()
m = types.ModuleType("google.cloud.storage"); m.Client = _Client
sys.modules["google.cloud.storage"] = m; google.cloud.storage = m
g = types.ModuleType("google.genai"); g.Client = lambda *a, **k: None
g.types = types.SimpleNamespace(); sys.modules["google.genai"] = g
e = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
e.PreconditionFailed = _PC; e.NotFound = KeyError
ac = types.ModuleType("google.api_core"); ac.exceptions = e
sys.modules["google.api_core"] = ac; sys.modules["google.api_core.exceptions"] = e
import main  # noqa: E402

OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print(f"  ✅ {n}")
    else: FAIL += 1; print(f"  ❌ {n} {x}")

def ledger():
    raw = FAKE.get(main.TRADE_LEDGER_FILE)
    return json.loads(raw[0]) if raw else []

print("\n一、balance_change_record 分類")
check("沒變 → None", main.balance_change_record({"balance": 100.0}, {"balance": 100.004}) is None)
check("資料不全 → None", main.balance_change_record({}, {"balance": 100.0}) is None)
prev = {"balance": 23127.45, "credit": 5114.0, "net_lots": 0.01, "floating": -3.2, "symbol": "XAUUSD"}
cur = {"balance": 23007.45, "credit": 5114.0, "net_lots": 0.0, "equity": 28121.45, "daily_pnl": -120,
       "received_utc": "2026-10-13 06:17:31", "symbol": "NONE"}
r = main.balance_change_record(prev, cur)
check("有持倉後 balance 下降 → trade", r["kind"] == "trade", r)
check("delta = −120.00", r["delta"] == -120.0, r["delta"])
check("symbol 取平倉前的商品", r["symbol"] == "XAUUSD", r["symbol"])
check("t 用心跳的 received_utc", r["t"] == "2026-10-13 06:17:31")
base = {"balance": 100.0, "credit": 10.0, "net_lots": 0.0, "floating": 0.0, "buy_lots": 0.0, "sell_lots": 0.0}
check("無持倉時 balance 大增 → transfer", main.balance_change_record(base, {**base, "balance": 600.0})["kind"] == "transfer")
check("credit 同額變動 → credit", main.balance_change_record(base, {**base, "balance": 150.0, "credit": 60.0})["kind"] == "credit")
check("只有 floating 也算有持倉", main.balance_change_record({**base, "floating": 5.0}, {**base, "balance": 105.0})["kind"] == "trade")

print("\n二、record_balance_change 寫入 GCS 帳本")
FAKE.clear()
check("沒變不寫", main.record_balance_change(base, dict(base)) is None and ledger() == [])
rec = main.record_balance_change(prev, cur)
rows = ledger()
check("一列寫入、最新在前", len(rows) == 1 and rows[0]["delta"] == -120.0, rows)
main.record_balance_change(prev, cur)
check("同一次心跳重送不重複", len(ledger()) == 1, len(ledger()))
cur2 = {**cur, "balance": 23307.45, "received_utc": "2026-10-13 07:00:00"}
main.record_balance_change({**cur, "net_lots": 0.02}, cur2)
rows = ledger()
check("第二筆插在最前", rows[0]["delta"] == 300.0 and rows[1]["delta"] == -120.0, [x["delta"] for x in rows])
logs = json.loads(FAKE[main.DECISION_LOG_FILE][0])
check("trade 類寫進決策日誌（key=realized）", logs and logs[0].get("k") == "realized", logs[:1])

print("\n三、上限")
FAKE.clear()
b = 1000.0
for i in range(main.TRADE_LEDGER_MAX + 5):
    nb = b + 1.0
    main.record_balance_change({"balance": b, "net_lots": 0.01}, {"balance": nb, "received_utc": f"t{i}"})
    b = nb
check(f"最多保留 {main.TRADE_LEDGER_MAX} 列", len(ledger()) == main.TRADE_LEDGER_MAX, len(ledger()))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
