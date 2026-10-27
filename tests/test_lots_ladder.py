"""[R346] 手數階梯純函數測試（唔連 GCS）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import lots_ladder as ll  # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    OK += bool(cond); FAIL += (not cond)
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f" {extra}"))


K = dict(start=0.05, lo=0.05, hi=0.10, step=0.01, on=True)
print("=== [R346] 手數階梯 ===")
st = {}
check("關：固定 start", ll.current({"lots_level": 0.09}, start=0.01, lo=0.05, hi=0.10, on=False) == 0.01)
check("開、冇級數 → start 0.05", ll.current(st, **{k: v for k, v in K.items() if k != "step"}) == 0.05)
check("賺 → +0.01", ll.step(st, 57.27, **K) == (0.05, 0.06) and st["lots_level"] == 0.06)
check("蝕 → −0.01", ll.step(st, -5.02, **K) == (0.06, 0.05))
check("蝕到底 → 停喺 0.05", ll.step(st, -10, **K) == (0.05, 0.05) and st["lots_level"] == 0.05)
for _ in range(7):
    ll.step(st, 1.0, **K)
check("連賺 7 次 → 頂 0.10（唔超）", st["lots_level"] == 0.10 and ll.current(st, **{k: v for k, v in K.items() if k != "step"}) == 0.10)
check("0／None 唔郁", ll.step(st, 0, **K) is None and ll.step(st, None, **K) is None and st["lots_level"] == 0.10)
check("關咗唔郁", ll.step(st, 9, **{**K, "on": False}) is None)
check("lots_log 有紀錄、最多 50", 1 <= len(st["lots_log"]) <= 50 and st["lots_log"][0]["from"] == 0.05 and st["lots_log"][0]["to"] == 0.06)
check("浮點：0.07+0.01 = 0.08", ll.clamp(0.07 + 0.01, 0.05, 0.10) == 0.08)
# 真倉偵測
st = {}
pos = {"side": 1, "entry": 4000.0, "lots": 0.05}
check("冇倉：記參考點、唔郁", ll.live_close(st, None, None, 100.0, **K) is None and st["lots_realized_ref"] == 100.0)
check("開倉中：唔郁、參考點唔變", ll.live_close(st, None, pos, 100.0, **K) is None and ll.live_close(st, pos, pos, 100.0, **K) is None and st["lots_realized_ref"] == 100.0)
check("平倉（realized 100 → 157.27）→ 升一級、參考點更新", ll.live_close(st, pos, None, 157.27, **K) == (0.05, 0.06) and st["lots_realized_ref"] == 157.27)
check("再開再平蝕（157.27 → 152.25）→ 跌一級", ll.live_close(st, pos, None, 152.25, **K) == (0.06, 0.05))
st2 = {}
check("冇參考點就平倉（服務重啟）→ 唔郁、只記參考點", ll.live_close(st2, pos, None, 50.0, **K) is None and st2["lots_realized_ref"] == 50.0)
check("realized 缺 → 唔郁、參考點唔記", ll.live_close(st2, pos, None, None, **K) is None and st2["lots_realized_ref"] == 50.0)
check("env 未同步（MAX 0.01 < MIN 0.05）→ 硬上限優先，lots 0.01", ll.current({}, start=0.05, lo=0.05, hi=0.01, on=True) == 0.01 and ll.step({}, 10, start=0.05, lo=0.05, hi=0.01, step=0.01, on=True) == (0.01, 0.01))
check("關、start 高過硬上限 → 用硬上限", ll.current({}, start=0.05, lo=0.05, hi=0.01, on=False) == 0.01)
print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
