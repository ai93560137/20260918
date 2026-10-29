"""[R357] 🐯 虎翼頁（?view=huyi）同 action=huyi_push。

執行：python3 tests/test_huyi.py
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
from types import SimpleNamespace  # noqa: E402

OK = FAIL = 0
OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print(f"  ✅ {n}")
    else: FAIL += 1; print(f"  ❌ {n} {x}")

req = lambda **a: SimpleNamespace(args=a)
import flask  # noqa: E402
app = flask.Flask("t")

print("\n一、未有數據")
FAKE.clear()
html = main.handle_huyi_get(req())
check("頁面照出、寫明紙上同未有候選", "🐯 虎翼" in html and "紙上" in html and "暫時冇候選" in html)
check("研究判決表", "95% 現金擔保 put" in html and "美 0.90" in html)
check("導覽有虎翼", "?view=huyi" in main.page_nav("welcome"))

print("\n二、推數據")
P = {"asof_hkt": "2026-10-30 08:00", "mode": "paper",
     "candidates": [{"date": "2026-10-29", "market": "us", "code": "GOOG", "name": "Alphabet", "drop_pct": -12.7,
                     "close": 250.5, "atm_iv": 0.305, "rv63": 0.279, "rho": 1.09, "rho_star": 0.9, "leg": "put95",
                     "strike": 237.5, "expiry": "2026-11-28", "premium": 4.2, "secret": "x"}],
     "paper": [], "notes": ["<i>x</i>"]}
with app.app_context():
    r = main.handle_huyi_push(P)
r = r[0] if isinstance(r, tuple) else r
check("存入 GCS", main.HUYI_FILE in FAKE and json.loads(FAKE[main.HUYI_FILE][0])["candidates"][0]["code"] == "GOOG")
check("唔明欄位唔存", "secret" not in FAKE[main.HUYI_FILE][0])
html = main.handle_huyi_get(req())
check("候選表顯示", "GOOG" in html and "−12.7" in html.replace("-", "−") and "30.5%" in html, html[-2000:])
check("注意事項有 escape", "&lt;i&gt;x" in html and "<i>x</i>" not in html)
with app.app_context():
    j = main.handle_huyi_get(req(format="json"))
j = j[0] if isinstance(j, tuple) else j
check("JSON", '"GOOG"' in j.get_data(as_text=True))

print("\n三、太大拒收")
with app.app_context():
    r = main.handle_huyi_push({"notes": ["x" * 300] * 20, "candidates": [{"note": "y" * 80, **{k: "z" * 80 for k in main.HUYI_ROW_KEYS}}] * 200})
check("413", (r[1] if isinstance(r, tuple) else 200) == 413)

print(f"\n合計 ✅ {OK}  ❌ {FAIL}")
sys.exit(1 if FAIL else 0)
