"""[11-10 事故] 修復 09:43 UTC 天覆陣跑組合測試時誤寫嘅 gs://zhuge-risk-manager-bucket/xau/trend/state.json（926 趨勢簿）。
預設 dry-run（只印）；使用者批准後加 --write。備份寫入 --backup 目錄（預設 /tmp）。用 generation 前置條件寫，唔會蓋過服務同時嘅寫入。
還原：pos／used／adopted／orders（09:42 UTC 公開 status 記錄）；D1 20759–20763 用 seed、20765–20767 用 xau/bars M1 重算、刪假 20768。
用法：python3 scripts/repair_trend_926_1110.py [--write] [--backup DIR]"""
import sys, json, time
from urllib.parse import quote
sys.path.insert(0, "scripts"); sys.path.insert(0, "xau")
import gcp_agent as G, trend_d1_seed as S
WRITE = "--write" in sys.argv
BK = sys.argv[sys.argv.index("--backup") + 1] if "--backup" in sys.argv else "/tmp"
ctx = G.Ctx(G.build_parser().parse_args(["whoami"])); s = ctx.session; B = ctx.bucket
OBJ = "xau/trend/state.json"
def bars(day):
    return G.gcs_get(ctx, f"xau/bars/{day}.jsonl") or []
def d1_from(bs):
    out = {}
    for b in sorted(bs, key=lambda x: x["utc"]):
        k = str(int(b["utc"]) // 86400); r = out.get(k)
        if r is None:
            out[k] = {"o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"], "t0": int(b["utc"]), "t1": int(b["utc"])}
        else:
            r["h"] = max(r["h"], b["high"]); r["l"] = min(r["l"], b["low"]); r["c"] = b["close"]; r["t1"] = int(b["utc"])
    return out
for attempt in range(6):
    meta = s.get(f"{G.GCS_API}/b/{B}/o/{quote(OBJ, safe='')}", timeout=30).json(); gen = meta["generation"]
    cur = s.get(f"{G.GCS_API}/b/{B}/o/{quote(OBJ, safe='')}", params={"alt": "media", "ifGenerationMatch": gen}, timeout=30).json()
    open(f"{BK}/state926_before_{gen}.json", "w").write(json.dumps(cur))
    d1 = {k: v for k, v in cur["d1"].items() if not (20759 <= int(k) <= 20768)}
    for k in range(20759, 20764):
        if str(k) in S.SEED:
            d1[str(k)] = S.SEED[str(k)]
    live = d1_from(bars("2026-11-08") + bars("2026-11-09") + bars("2026-11-10"))
    live = {k: v for k, v in live.items() if 20765 <= int(k) <= 20767}
    d1.update(live)
    new = {**cur, "d1": d1,
           "pos": {"adopt": True, "period": 8107, "price": 4061.08, "rule": "qbrk", "side": -1, "sl": 4328.18, "ts": 1794178892.5998292, "utc": "2026-11-08 23:01:32"},
           "used": {"qbrk": 8107}, "adopted": [8107],
           "orders": [
               {"id": "w697e37c", "kind": "open", "ts": 1794172113.1079352, "utc": "2026-11-08 21:08:33", "price": 4071.12, "rule": "qbrk", "side": -1, "sl": 4328.18, "period": 8107, "adopt": True, "lots": 0.01,
                "reason": "補入 10 月尾上季突破", "applied": "open|SELL|0.01|sl=4328.18|tp=|magic=926|note=趨勢qbrk|id=w697e37c", "acked": True, "ok": False, "message": "market closed", "ticket": 0, "reverted": True},
               {"id": "wb8f0c96", "kind": "open", "ts": 1794178892.5998292, "utc": "2026-11-08 23:01:32", "price": 4061.08, "rule": "qbrk", "side": -1, "sl": 4328.18, "period": 8107, "adopt": True, "lots": 0.01,
                "reason": "補入 10 月尾上季突破", "applied": "open|SELL|0.01|sl=4328.18|tp=|magic=926|note=趨勢qbrk|id=wb8f0c96", "acked": True, "ok": True, "message": "done at 0.00", "ticket": 519881358}],
           "repaired_utc": "2026-11-10 測試誤寫後由天覆陣還原"}
    for k in sorted(new["d1"], key=int)[-12:]:
        print(k, new["d1"][k])
    print("days", len(new["d1"]), "pending", cur.get("pending_cmds"), "book", cur.get("book"))
    if not WRITE:
        break
    r = s.post(f"https://storage.googleapis.com/upload/storage/v1/b/{B}/o", params={"uploadType": "media", "name": OBJ, "ifGenerationMatch": gen},
               data=json.dumps(new, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, timeout=30)
    print("write", r.status_code, r.text[:120])
    if r.status_code == 200:
        break
    time.sleep(3)
