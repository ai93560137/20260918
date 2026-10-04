"""research/hsi_futures_range/snake_week.py：用人造 K 線逐條驗證入市、止蝕、離場規則（不連網、不讀 GCS）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research" / "hsi_futures_range"))
import snake_week as sw                                  # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name} {extra}")


def bar(t, o, h, l, c):
    return {"time_key": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


def day(date, *bars):
    return {"date": date, "bars": list(bars), "rhat": 100.0, "ref": 1000.0}


def dlv(date, pred_low=950, pred_high=1050, low_edge=900, high_edge=1100):
    return {"date": date, "pred_low": pred_low, "pred_high": pred_high,
            **{f"low_edge_{q}": low_edge for q in sw.QS}, **{f"high_edge_{q}": high_edge for q in sw.QS}}


def wlv(week, low_edge=800, high_edge=1200, pred_low=900, pred_high=1100):
    return {"week": week, "anchor": 1000.0, "R_week": 300.0, "pred_low": pred_low, "pred_high": pred_high,
            **{f"low_edge_{q}": low_edge for q in sw.QS}, **{f"high_edge_{q}": high_edge for q in sw.QS}}


W1, W2 = "2026-W02", "2026-W03"          # 2026-01-05（一）起、2026-01-12（一）起
D = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"]


def run(days, before, flips, entry, ex, daily=None, weekly=None, qs=0.9, cost=0.0):
    daily = daily or {d["date"]: dlv(d["date"]) for d in days}
    weekly = weekly or {W1: wlv(W1), W2: wlv(W2)}
    return sw.simulate(days, daily, weekly, before, flips, entry, qs, ex, cost)


print("=== A＋①：跟蛇反手入、蛇反手出（同一價反手） ===")
days = [day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1010, 990, 1005), bar(f"{D[0]} 09:30:00", 1005, 1030, 1000, 1025)),
        day(D[1], bar(f"{D[1]} 09:15:00", 1020, 1022, 960, 965), bar(f"{D[1]} 09:30:00", 965, 970, 950, 955))]
before = {f"{D[0]} 09:15:00": 0, f"{D[0]} 09:30:00": 0, f"{D[1]} 09:15:00": 1, f"{D[1]} 09:30:00": -1}
flips = {f"{D[0]} 09:30:00": [(1, 1020.0)], f"{D[1]} 09:15:00": [(-1, 970.0)]}
tr = run(days, before, flips, "A", "1")
check("蛇做多 1020 跟入、蛇反手 970 平倉", tr[0]["entry_price"] == 1020 and tr[0]["exit_price"] == 970
      and tr[0]["exit_reason"] == "蛇反手" and tr[0]["entry_type"] == "蛇反手跟入", tr[:1])
check("同一價反手做空，數據完結平倉", tr[1]["side"] == -1 and tr[1]["entry_price"] == 970 and tr[1]["exit_reason"] == "數據完結"
      and tr[1]["exit_price"] == 955)
check("止蝕＝當週範圍邊、成本照扣", tr[0]["initial_stop"] == 800 and tr[1]["initial_stop"] == 1200
      and run(days, before, flips, "A", "1", cost=3.0)[0]["net"] == -53)

print("=== 止蝕：盤中、跳空、與蛇反手同一根取較差價 ===")
days = [day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1010, 990, 1005)),
        day(D[1], bar(f"{D[1]} 09:15:00", 1000, 1000, 790, 795))]
before = {b["time_key"]: 1 for d in days for b in d["bars"]}
tr = run(days, before, {}, "A", "1")
check("A 空手時開市再入；碰到 800 止蝕在 800", tr[0]["entry_type"] == "空手・開市再入" and tr[0]["entry_price"] == 1000
      and tr[0]["exit_price"] == 800 and tr[0]["exit_reason"] == "止蝕")
days[1]["bars"][0] = bar(f"{D[1]} 09:15:00", 780, 790, 770, 775)
tr = run(days, before, {}, "A", "1")
check("開市已低過止蝕 → 開市價離場（跳空）", tr[0]["exit_price"] == 780 and tr[0]["exit_reason"] == "止蝕（跳空）")
days[1]["bars"][0] = bar(f"{D[1]} 09:15:00", 1000, 1000, 790, 795)
tr = run(days, before, {f"{D[1]} 09:15:00": [(-1, 850.0)]}, "A", "1")
check("同一根止蝕 800 與蛇反手 850 → 取較差的 800", tr[0]["exit_price"] == 800 and tr[0]["exit_reason"] == "止蝕")

print("=== ② 週末平倉、下週一開市再入 ===")
days = [day(D[i], bar(f"{D[i]} 09:15:00", 1000 + i, 1005 + i, 995 + i, 1002 + i)) for i in range(6)]
before = {b["time_key"]: 1 for d in days for b in d["bars"]}
tr = run(days, before, {}, "A", "2")
check("週五最後一根收市平倉", tr[0]["exit_reason"] == "週末平倉" and tr[0]["exit_date"] == D[4] and tr[0]["exit_price"] == 1006)
check("下週一開市價再入", tr[1]["entry_date"] == D[5] and tr[1]["entry_price"] == 1005 and tr[1]["entry_type"] == "空手・開市再入")

print("=== ③ 週目標 ===")
days = [day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1010, 995, 1005)),
        day(D[1], bar(f"{D[1]} 09:15:00", 1005, 1120, 1000, 1110))]
before = {b["time_key"]: 1 for d in days for b in d["bars"]}
tr = run(days, before, {}, "A", "3")
check("碰到週預測高位 1100 → 1100 止賺", tr[0]["exit_price"] == 1100 and tr[0]["exit_reason"] == "週目標")
days[1]["bars"][0] = bar(f"{D[1]} 09:15:00", 1130, 1140, 1125, 1135)
tr = run(days, before, {}, "A", "3")
check("開市已高過目標 → 開市價 1130", tr[0]["exit_price"] == 1130)
tr = run([day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1010, 995, 1005), bar(f"{D[0]} 09:30:00", 1005, 1110, 1004, 1100))],
         {f"{D[0]} 09:15:00": 0, f"{D[0]} 09:30:00": 0}, {f"{D[0]} 09:30:00": [(1, 1010.0)]}, "A", "3")
check("入市那一根之後碰到目標 → 同一根止賺", tr[0]["exit_time"] == tr[0]["entry_time"] and tr[0]["exit_price"] == 1100)

print("=== ④ 移動止蝕：只收緊、不理蛇反手；⑤ 加蛇反手 ===")
days = [day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1010, 995, 1005)),
        day(D[1], bar(f"{D[1]} 09:15:00", 1005, 1010, 1000, 1008)),
        day(D[2], bar(f"{D[2]} 09:15:00", 1008, 1010, 940, 945))]
daily = {D[0]: dlv(D[0], low_edge=900), D[1]: dlv(D[1], low_edge=950), D[2]: dlv(D[2], low_edge=920)}
before = {b["time_key"]: 1 for d in days for b in d["bars"]}
flips = {f"{D[1]} 09:15:00": [(-1, 1002.0)]}
tr = run(days, before, flips, "A", "4", daily=daily)
check("④ 第二天收緊到 950、第三天 920 不放鬆 → 950 止蝕", tr[0]["exit_price"] == 950 and tr[0]["exit_reason"] == "止蝕"
      and [round(s) for _, s in tr[0]["stop_path"]] == [800, 950], tr[0]["stop_path"])
check("④ 不理蛇反手（第二天反手也不平倉）", tr[0]["exit_date"] == D[2])
tr = run(days, before, flips, "A", "5", daily=daily)
check("⑤ 蛇反手就平倉", tr[0]["exit_reason"] == "蛇反手" and tr[0]["exit_price"] == 1002)

print("=== 新一週：①～③ 重設為新一週的範圍邊；④⑤ 只收緊 ===")
days = [day(D[4], bar(f"{D[4]} 09:15:00", 1000, 1010, 995, 1005)),
        day(D[5], bar(f"{D[5]} 09:15:00", 1005, 1010, 760, 770))]
before = {b["time_key"]: 1 for d in days for b in d["bars"]}
weekly = {W1: wlv(W1, low_edge=800), W2: wlv(W2, low_edge=750)}
tr = run(days, before, {}, "A", "1", weekly=weekly)
check("① 下週止蝕重設到 750（可放鬆）→ 低位 760 不觸發", tr[0]["exit_reason"] == "數據完結"
      and tr[0]["stop"] == 750, tr[0])
daily = {D[4]: dlv(D[4], low_edge=700), D[5]: dlv(D[5], low_edge=700)}
tr = run(days, before, {}, "A", "4", weekly=weekly, daily=daily)
check("④ 下週不放鬆，仍是 800 → 止蝕", tr[0]["exit_price"] == 800 and tr[0]["exit_reason"] == "止蝕")

print("=== B：等回調到預測位 ===")
days = [day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1010, 960, 970), bar(f"{D[0]} 09:30:00", 970, 975, 940, 945)),
        day(D[1], bar(f"{D[1]} 09:15:00", 930, 935, 925, 930))]
before = {b["time_key"]: 1 for d in days for b in d["bars"]}
tr = run(days, before, {}, "B", "1")
check("蛇做多，碰到預測低位 950 才買在 950", tr[0]["entry_price"] == 950 and tr[0]["entry_type"] == "回調掛單成交"
      and tr[0]["entry_time"] == f"{D[0]} 09:30:00")
check("每天最多入一次（之後持倉到數據完結，只有 1 筆）", len(tr) == 1)
tr = run([day(D[0], bar(f"{D[0]} 09:15:00", 940, 945, 930, 935))], {f"{D[0]} 09:15:00": 1}, {}, "B", "1")
check("開市已低過預測位 → 開市價 940 成交", tr[0]["entry_price"] == 940)
tr = run([day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1000, 790, 795))], {f"{D[0]} 09:15:00": 1}, {}, "B", "1")
check("同一根碰到入市又碰到止蝕 → 當作止蝕", tr[0]["exit_reason"] == "止蝕（同一根）" and tr[0]["exit_price"] == 800)
tr = run([day(D[0], bar(f"{D[0]} 09:15:00", 1000, 1010, 940, 945))], {f"{D[0]} 09:15:00": 1}, {}, "B", "1",
         weekly={W1: wlv(W1, low_edge=960)})
check("止蝕位不在入市價之下（週範圍邊 960 > 950）→ 不做", tr == [])

print("=== 預測位：逐日前推 ===")
import copy
base = [{"date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", "rhat": 100.0, "ref": 1000.0 + i,
         "bars": [bar(f"2025-{1 + i // 28:02d}-{1 + i % 28:02d} 09:15:00", 1000 + i, 1040 + i % 7, 960 - i % 5, 1000 + i)]}
        for i in range(200)]
d1, w1 = sw.levels(base)
mod = copy.deepcopy(base); mod[-1]["bars"][0]["high"] += 5000
d2, w2 = sw.levels(mod)
check("日：少於 120 天不出預測位", min(d1) == base[120]["date"])
check("改最後一天不影響任何一天的預測位（只用之前的數據）", d1 == d2)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
