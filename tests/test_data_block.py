"""[R348] 數據前 N 小時唔開新倉：純函數測試（假 storage）。"""
import os
import sys
import types

os.environ.setdefault("XAU_BOOK", "")
os.environ.setdefault("DATA_BLOCK_HOURS", "4")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
_an = types.ModuleType("anthropic"); _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = Exception; sys.modules.setdefault("anthropic", _an)
import google, google.cloud  # noqa: E402
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def download_as_bytes(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0].encode("utf-8")
    def upload_from_string(self, data, *a, **k):
        gen = FAKE.get(self.name, (None, 0))[1] + 1; FAKE[self.name] = (data, gen); self.generation = gen
class _Bucket:
    def blob(self, name): return _Blob(name)
    def get_blob(self, name): return _Blob(name) if name in FAKE else None
class _Client:
    def __init__(self, *a, **k): pass
    def bucket(self, name): return _Bucket()
sm = types.ModuleType("google.cloud.storage"); sm.Client = _Client; sys.modules["google.cloud.storage"] = sm; google.cloud.storage = sm
em = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
em.PreconditionFailed = _PC; em.NotFound = KeyError
ac = types.ModuleType("google.api_core"); ac.exceptions = em; sys.modules["google.api_core"] = ac; sys.modules["google.api_core.exceptions"] = em
import json  # noqa: E402
import config, data_block as db  # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    OK += bool(cond); FAIL += (not cond)
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f" {extra}"))

print("=== [R348] 數據前 4 小時唔開新倉 ===")
T = 1793100000.0                                  # 2026-10-27 11:20 UTC 附近
def iso(ts):
    import time; return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
doc = {"updated_utc": iso(T - 3600), "block_hours": 4, "events": [{"t": iso(T + 2 * 3600), "title": "FOMC Statement", "src": "ff"}, {"t": iso(T + 30 * 3600), "title": "GDP", "src": "ff"}]}
check("parse_iso", db._parse_iso("2026-10-28T18:00:00Z") == 1793210400.0 and db._parse_iso("bad") is None)
ev = db.blocked(doc, T)
check("事件前 2 小時 → 封鎖、mins_left 120", ev and ev["title"] == "FOMC Statement" and ev["mins_left"] == 120, ev)
check("事件前 4 小時零 1 秒 → 未封鎖", db.blocked(doc, T + 2 * 3600 - 4 * 3600 - 1) is None)
check("剛好事件前 4 小時 → 封鎖", db.blocked(doc, T + 2 * 3600 - 4 * 3600) is not None)
check("事件時刻 → 唔封鎖（唔含 t）", db.blocked(doc, T + 2 * 3600) is None)
check("DATA_BLOCK_HOURS=0 → 永遠唔封", db.blocked(doc, T, hrs=0) is None)
check("hrs=1 → 事件前 2 小時唔封", db.blocked(doc, T, hrs=1) is None and db.blocked(doc, T + 3600 + 1, hrs=1) is not None)
check("calendar_ok：新鮮 ✓、舊過 48h ✗、冇 events ✗", db.calendar_ok(doc, T) and not db.calendar_ok({**doc, "updated_utc": iso(T - 49 * 3600)}, T) and not db.calendar_ok({"updated_utc": iso(T)}, T) and not db.calendar_ok(None, T))
check("upcoming 排序、只未來", [e["title"] for e in db.upcoming(doc, T)] == ["FOMC Statement", "GDP"] and db.upcoming(doc, T + 40 * 3600) == [])
# check()：讀 GCS（假）、快取、提醒每日一次
logs, tgs = [], []
def log(msg, **kw): logs.append((msg, kw.get("severity")))
def tg(msg): tgs.append(msg)
FAKE.clear(); db._cache.update(ts=0, doc=None, error=None)
st = {}
ev, info = db.check(st, T, "2026-10-27", log=log, tg=tg)
check("日曆讀唔到 → 唔封鎖、照常、WARNING＋TG 一次、記 warned_day", ev is None and info["calendar_ok"] is False and len(logs) == 1 and len(tgs) == 1 and st["data_cal_warned_day"] == "2026-10-27", (ev, info, logs))
db._cache.update(ts=0)
ev, info = db.check(st, T + 60, "2026-10-27", log=log, tg=tg)
check("同日再讀唔到 → 唔再提醒", len(tgs) == 1)
ev, info = db.check(st, T + 60, "2026-10-28", log=log, tg=tg)
check("換日再提醒一次", len(tgs) == 2)
FAKE[db.CAL_OBJECT] = (json.dumps(doc), 1); db._cache.update(ts=0, doc=None, error=None)
ev, info = db.check(st, T, "2026-10-27", log=log, tg=tg)
check("日曆正常 → 封鎖 FOMC、info 有 upcoming、冇新提醒", ev and ev["title"] == "FOMC Statement" and info["calendar_ok"] and len(info["upcoming"]) == 2 and len(tgs) == 2, (ev, info))
FAKE[db.CAL_OBJECT] = (json.dumps({**doc, "events": []}), 2)
ev2, _ = db.check(st, T + 10, "2026-10-27", log=log, tg=tg)
check("10 分鐘內用快取（GCS 改咗都未見）", ev2 is not None)
ev3, _ = db.check(st, T + 601, "2026-10-27", log=log, tg=tg)
check("過 10 分鐘重讀 → 冇事件 → 唔封", ev3 is None)
check("text()", db.text(None) == "冇" and "FOMC" in db.text(ev) and "120 分鐘" in db.text(ev))
print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
