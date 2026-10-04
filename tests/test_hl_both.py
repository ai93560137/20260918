"""research/hsi_futures_range/hl_both.py：預測高低位都出現後入市、1:2 RRR 離場——人造 K 線驗證規則。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research" / "hsi_futures_range"))
import hl_both as hb                                     # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name} {extra}")


def bar(t, o, h, l, c):
    return {"time_key": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


D = ["2026-01-05", "2026-01-06", "2026-01-07"]
W = "2026-W02"


def lv(d):
    return {"date": d, "pred_high": 1050, "pred_low": 950, "low_edge_0.95": 900, "high_edge_0.95": 1100,
            "low_edge_0.9": 920, "high_edge_0.9": 1080}


WL = {W: {"week": W, "anchor": 1000.0, "R_week": 300.0}}


def run(days, before, mode, flips=None):
    return hb.simulate(days, {d["date"]: lv(d["date"]) for d in days}, WL, before, flips or {}, mode, 0.95, 2.0, 0.0)


print("=== 觸發：先碰高位、後碰低位 ===")
days = [{"date": D[0], "bars": [bar(f"{D[0]} 09:30:00", 1000, 1055, 995, 1040),     # 碰高位
                                 bar(f"{D[0]} 09:45:00", 1040, 1045, 960, 970),      # 未碰低位
                                 bar(f"{D[0]} 10:00:00", 970, 975, 945, 950),        # 碰低位 → 觸發
                                 bar(f"{D[0]} 10:15:00", 950, 960, 940, 955)]},
        {"date": D[1], "bars": [bar(f"{D[1]} 09:30:00", 955, 1060, 950, 1055),
                                bar(f"{D[1]} 09:45:00", 1055, 1060, 1040, 1050)]}]
before = {b["time_key"]: 1 for d in days for b in d["bars"]}
tr = run(days, before, "S")
check("S：第二個位（低位 950）被碰到那一根入，跟蛇做多", tr[0]["entry_time"] == f"{D[0]} 10:00:00"
      and tr[0]["entry_price"] == 950 and tr[0]["side"] == 1 and tr[0]["entry_type"] == "高低都現後入", tr[:1])
check("止蝕＝當天九成低位邊 900、目標＝950 + 2×50 = 1050", tr[0]["initial_stop"] == 900 and tr[0]["initial_target"] == 1050)
check("第二天碰到 1050 → 2R 止賺", tr[0]["exit_reason"] == "2R 止賺" and tr[0]["exit_price"] == 1050 and tr[0]["exit_date"] == D[1])
tr = run(days, {k: -1 for k in before}, "S")
check("S：蛇做空 → 在 950 沽，止蝕 1100", tr[0]["side"] == -1 and tr[0]["initial_stop"] == 1100)
tr = run(days, {k: -1 for k in before}, "F")
check("F：最後碰低位 → 買（不理蛇做空）", tr[0]["side"] == 1 and tr[0]["entry_price"] == 950)

print("=== 同一根兩個都碰到、跳空、蛇反手 ===")
d1 = [{"date": D[0], "bars": [bar(f"{D[0]} 09:30:00", 1000, 1060, 940, 1010), bar(f"{D[0]} 09:45:00", 1010, 1020, 1000, 1005)]}]
b1 = {b["time_key"]: 1 for d in d1 for b in d["bars"]}
tr = run(d1, b1, "S")
check("同一根兩個都碰到 → 收市價 1010 入", tr[0]["entry_price"] == 1010 and tr[0]["entry_time"] == f"{D[0]} 09:30:00")
check("F：同一根兩個都碰到 → 不知最後碰哪個，不做", run(d1, b1, "F") == [])
d2 = [{"date": D[0], "bars": [bar(f"{D[0]} 09:30:00", 1000, 1055, 995, 1040), bar(f"{D[0]} 09:45:00", 930, 935, 925, 930),
                              bar(f"{D[0]} 10:00:00", 930, 935, 880, 890)]}]
tr = run(d2, {b["time_key"]: 1 for d in d2 for b in d["bars"]}, "S")
check("開市已低過預測低位 → 開市價 930 入；之後碰到 900 止蝕", tr[0]["entry_price"] == 930 and tr[0]["exit_price"] == 900
      and tr[0]["exit_reason"] == "止蝕")
tr = run(days, before, "S", flips={f"{D[1]} 09:30:00": [(-1, 1000.0)]})
check("S：蛇反手（1000）與目標同一根 → 取較差的蛇反手", tr[0]["exit_reason"] == "蛇反手" and tr[0]["exit_price"] == 1000)
tr = run(days, {k: -1 for k in before}, "F", flips={f"{D[1]} 09:30:00": [(-1, 1000.0)]})
check("F：不理蛇反手", tr[0]["exit_reason"] == "2R 止賺")

print("=== 每天最多一次；S0 對照開市就入 ===")
tr = run(days, before, "S0")
check("S0：第一天開市 1000 入、止蝕 900、目標 1200", tr[0]["entry_price"] == 1000 and tr[0]["entry_type"] == "空手・開市再入"
      and tr[0]["initial_target"] == 1200)
d3 = [{"date": D[0], "bars": [bar(f"{D[0]} 09:30:00", 1000, 1055, 945, 1000), bar(f"{D[0]} 09:45:00", 1000, 1005, 890, 895),
                              bar(f"{D[0]} 10:00:00", 895, 1060, 890, 1055)]}]
tr = run(d3, {b["time_key"]: 1 for d in d3 for b in d["bars"]}, "S")
check("止蝕後同一天不再入", len(tr) == 1 and tr[0]["exit_reason"] == "止蝕")

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
