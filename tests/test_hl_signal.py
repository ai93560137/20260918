"""research/hsi_futures_range/hl_signal.py：訊號版（高位已出現＋低位已出現都亮後入市、1:2 RRR）——人造 K 線驗證規則。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research" / "hsi_futures_range"))
import hl_signal as hs                                   # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name} {extra}")


def bar(t, o, h, l, c):
    return {"time_key": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


D = ["2026-01-05", "2026-01-06"]
W = "2026-W02"
LV = {d: {"date": d, "pred_high": 1050, "pred_low": 950, "low_edge_0.95": 900, "high_edge_0.95": 1100} for d in D}
WL = {W: {"week": W, "anchor": 1000.0, "R_week": 300.0}}


def mk(date, prices):
    return {"date": date, "rhat": 100.0, "ref": 1000.0, "rem": [0.5] * len(prices),
            "bars": [bar(f"{date} {9 + i // 4:02d}:{(i % 4) * 15:02d}:00", *p) for i, p in enumerate(prices)]}


print("=== A 訊號：兩邊都亮的下一根開市入 ===")
# R̂ = 100：A 要已走 ≥ 80、離極值 ≥ 50
d0 = mk(D[0], [(1000, 1040, 995, 1035),      # 0
               (1035, 1045, 1030, 1040),     # 1 高 1045
               (1040, 1041, 960, 965),       # 2 低 960：已走 85、離高 80 → 高位已現（A）；離低 5
               (965, 1020, 962, 1015),       # 3 離低 55 → 低位已現（A）
               (1015, 1018, 1010, 1012),     # 4 ← 入市（下一根開市 1015）
               (1012, 1150, 1011, 1140)])    # 5 目標
rows, trig = hs.signals([d0], LV)
a = {(r["signal"], r["side"]): r for r in rows}
check("A：高位已現在第 2 根、低位已現在第 3 根", a[("A", "high")]["bar_index"] == 2 and a[("A", "low")]["bar_index"] == 3, a)
check("觸發＝第 4 根入市，最後亮的是低位已現", trig["A"][D[0]] == (4, "low"), trig["A"])
before = {b["time_key"]: 1 for b in d0["bars"]}
tr = hs.simulate([d0], LV, WL, before, {}, trig["A"], "S")
check("S：跟蛇做多，入市價＝第 4 根開市 1015、止蝕 900、目標 1015 + 2×115 = 1245", tr[0]["entry_price"] == 1015
      and tr[0]["initial_stop"] == 900 and tr[0]["initial_target"] == 1245 and tr[0]["entry_type"] == "訊號都現後入", tr[:1])
tr = hs.simulate([d0], LV, WL, {k: -1 for k in before}, {}, trig["A"], "F")
check("F：最後亮低位已現 → 買（不理蛇做空）", tr[0]["side"] == 1)
tr = hs.simulate([d0], LV, WL, {k: -1 for k in before}, {}, trig["A"], "S")
check("S：蛇做空 → 沽、止蝕 1100、目標 1015 − 2×85 = 845", tr[0]["side"] == -1 and tr[0]["initial_stop"] == 1100
      and tr[0]["initial_target"] == 845)

print("=== 離場：2R、止蝕、蛇反手、跳空 ===")
d1 = mk(D[1], [(1015, 1250, 1010, 1240)])
tr = hs.simulate([d0, d1], LV, WL, {b["time_key"]: 1 for d in (d0, d1) for b in d["bars"]}, {}, trig["A"], "S")
check("翌日碰 1245 → 2R 止賺（持倉多日）", tr[0]["exit_reason"] == "2R 止賺" and tr[0]["exit_price"] == 1245 and tr[0]["exit_date"] == D[1])
d1 = mk(D[1], [(890, 895, 880, 885)])
tr = hs.simulate([d0, d1], LV, WL, {b["time_key"]: 1 for d in (d0, d1) for b in d["bars"]}, {}, trig["A"], "S")
check("翌日開市 890 已低過止蝕 → 跳空止蝕 890", tr[0]["exit_reason"] == "止蝕（跳空）" and tr[0]["exit_price"] == 890)
fl = {d0["bars"][5]["time_key"]: [(-1, 1050.0)]}
tr = hs.simulate([d0], LV, WL, before, fl, trig["A"], "S")
check("S：蛇反手 1050 平倉", tr[0]["exit_reason"] == "蛇反手" and tr[0]["exit_price"] == 1050)
tr = hs.simulate([d0], LV, WL, before, fl, trig["A"], "F")
check("F：不理蛇反手（持倉到數據完結）", tr[0]["exit_reason"] == "數據完結")

print("=== 不做的情況 ===")
check("F：兩個訊號同一根亮（不知最後亮哪個）→ 不做",
      hs.simulate([d0], LV, WL, before, {}, {D[0]: (4, None)}, "F") == [])
check("兩個訊號都亮在當天最後一根 → 沒有下一根，不觸發",
      D[0] not in hs.signals([mk(D[0], [(1000, 1040, 995, 1035), (1035, 1045, 1030, 1040), (1040, 1041, 960, 965),
                                         (965, 1020, 962, 1015)])], LV)[1]["A"])
check("止蝕不在正確一邊（入市價低過九成低位邊）→ 不做",
      hs.simulate([mk(D[0], [(890, 895, 880, 885)] * 2)], LV, WL, {f"{D[0]} 09:15:00": 1}, {}, {D[0]: (1, "low")}, "S") == [])

print("=== B 訊號：機率 < 5% ===")
# σ = 100/1.596/1000 × √0.5 × 價；離極值夠遠時機率很小
d2 = mk(D[0], [(1000, 1100, 995, 1090), (1090, 1092, 900, 905), (905, 1000, 903, 995), (995, 996, 990, 992)])
rows, trig = hs.signals([d2], LV)
b = {r["side"]: r for r in rows if r["signal"] == "B"}
check("B：高位已現（離高 195、機率 < 5%）、低位已現各有一根", "high" in b and "low" in b
      and float(b["high"]["prob"]) < 0.05 and float(b["low"]["prob"]) < 0.05, b)

print("=== R 測試：不設目標（rr = 0）、其他倍數 ===")
_, trig = hs.signals([d0], LV)                         # 上面 B 一節換了 trig，這裡重算 d0 的
d1 = mk(D[1], [(1015, 1500, 1010, 1490)])
allb = {b["time_key"]: 1 for d in (d0, d1) for b in d["bars"]}
tr = hs.simulate([d0, d1], LV, WL, allb, {}, trig["A"], "S", rr=0.0)
check("rr = 0 → 不設目標，碰到 1500 也不止賺（數據完結）", tr[0]["initial_target"] is None and tr[0]["exit_reason"] == "數據完結")
tr = hs.simulate([d0, d1], LV, WL, allb, {}, trig["A"], "S", rr=3.0)
check("rr = 3 → 目標 1015 + 3×115 = 1360，原因寫「3R 止賺」", tr[0]["initial_target"] == 1360 and tr[0]["exit_reason"] == "3R 止賺")

print("=== HK50 差價合約：券商時間 → 香港時間 ===")
import hk50_cfd as hk
check("冬令（2024-03-04，UTC+2）03:15 開市那根 → 香港 09:30 收市", hk.broker_to_hk("2024.03.04 03:15:00") == "2024-03-04 09:30:00")
check("夏令（2024-03-11，UTC+3）04:15 → 香港 09:30", hk.broker_to_hk("2024.03.11 04:15:00") == "2024-03-11 09:30:00")
check("夏令最後一根 21:45 → 香港翌日 03:00（屬前一個交易日）", hk.broker_to_hk("2024.06.03 21:45:00") == "2024-06-04 03:00:00"
      and hk.session_of("2024-06-04 03:00:00") == "2024-06-03")

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
