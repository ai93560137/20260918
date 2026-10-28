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
# [R349] 升級上限由里程碑決定
print("=== [R349] 達到里程碑先升級（cap） ===")
CAPS = (0.06, 0.07, 0.08, 0.10)
check("cap_for：0 個里程碑 → 起點 0.05", ll.cap_for(0.05, CAPS, 0, 0.10) == 0.05)
check("cap_for：M1→0.06、M2→0.07、M3→0.08、M4→0.10", [ll.cap_for(0.05, CAPS, n, 0.10) for n in (1, 2, 3, 4)] == [0.06, 0.07, 0.08, 0.10])
check("cap_for：超出表尾用最後一個、唔超硬上限、壞值當 0", ll.cap_for(0.05, CAPS, 9, 0.10) == 0.10 and ll.cap_for(0.05, CAPS, 4, 0.08) == 0.08 and ll.cap_for(0.05, CAPS, "x", 0.10) == 0.05 and ll.cap_for(0.05, (), 2, 0.10) == 0.05)
K0 = dict(K, cap=0.05)
st = {}
check("里程碑 0：連賺 3 次都停喺 0.05", all(ll.step(st, 10, **K0) == (0.05, 0.05) for _ in range(3)) and ll.current(st, **{k: v for k, v in K0.items() if k != "step"}) == 0.05)
check("里程碑 0：蝕照喺 0.05（最低）", ll.step(st, -10, **K0) == (0.05, 0.05))
K1 = dict(K, cap=0.06)
check("M1 上限 0.06：賺 → 0.06，再賺唔超", ll.step(st, 10, **K1) == (0.05, 0.06) and ll.step(st, 10, **K1) == (0.06, 0.06))
check("M1 上限 0.06：蝕 → 0.05、再賺 → 0.06", ll.step(st, -1, **K1) == (0.06, 0.05) and ll.step(st, 1, **K1) == (0.05, 0.06))
K2 = dict(K, cap=0.08)
for _ in range(5):
    ll.step(st, 1, **K2)
check("M3 上限 0.08：連賺停喺 0.08（唔到硬上限 0.10）", st["lots_level"] == 0.08)
check("上限收回（0.08 → 0.05）：current 即時夾返 0.05", ll.current(st, **{k: v for k, v in K0.items() if k != "step"}) == 0.05)
check("cap 高過硬上限 → 用硬上限", ll.current({"lots_level": 0.2}, start=0.05, lo=0.05, hi=0.10, on=True, cap=0.5) == 0.10)
check("cap=None → 舊行為（只夾硬上限）", ll.current({"lots_level": 0.09}, start=0.05, lo=0.05, hi=0.10, on=True) == 0.09)
check("live_close 傳 cap：平倉賺但里程碑 0 → 唔升", ll.live_close({"lots_realized_ref": 0.0}, pos, None, 50.0, **K0) == (0.05, 0.05))
print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
