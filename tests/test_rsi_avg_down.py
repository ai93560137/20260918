"""research/hsi_futures_range/rsi_avg_down.py：加倉攤平、回到平均成本減倉、止賺止蝕——用使用者的例子驗證。"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research" / "hsi_futures_range"))
import rsi_avg_down as r                                  # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"  ✅ {name}")
    else:
        FAIL += 1; print(f"  ❌ {name} {extra}")


P = argparse.Namespace(sl_pct=0.02, step=300, cost=0.0)

print("=== 使用者例子：24000 沽 → 24300 加 → 回 24150 平 1 ===")
pos = r.Position(-1, 24000, 23500, P)
check("一路升到 24300 → 加 1 張，S×2 @24150", r.walk(pos, 24000, 24310, False) is None and pos.lots == 2 and pos.avg == 24150)
check("回落到 24150 → 平 1 張，剩 S×1 @24150", r.walk(pos, 24310, 24100, False) is None and pos.lots == 1 and pos.avg == 24150)
check("已實現 = 0（平均成本法）、浮動盈虧 = 24150 − 現價", pos.realized == 0)
res = r.walk(pos, 24100, 23400, False)
check("跌到 23500 止賺全平：總盈虧 = 24000 + 24300 − 24150 − 23500 = 650", res == ("tp", 23500) and pos.realized == 650, (res, pos.realized))

print("=== 再升到 24600：S×3 @24300，止蝕 = 24300 × 1.02 = 24786 ===")
pos = r.Position(-1, 24000, 23500, P)
r.walk(pos, 24000, 24700, False)
check("24300、24600 各加 1 張 → S×3 @24300", pos.lots == 3 and pos.avg == 24300 and pos.max_lots == 3)
check("止蝕價 24786（第三次加倉 24900 之前先止蝕）", round(pos.sl(), 1) == 24786.0 and pos.add_level() == 24900)
res = r.walk(pos, 24700, 24800, False)
check("升穿 24786 → 全部止蝕，虧 3 × 486 = 1458", res == ("sl", 24786.0) and round(pos.realized) == -1458, (res, pos.realized))

print("=== 跳空 ===")
pos = r.Position(-1, 24000, 23500, P)
res = r.walk(pos, 24000, 24700, True)
check("跳空直上 24700：加倉在開市價成交（S×2 @24350），未到止蝕", res is None and pos.lots == 2 and pos.avg == 24350, (pos.lots, pos.avg))
pos = r.Position(1, 24000, 24500, P)
res = r.walk(pos, 24000, 23000, True)
check("買單跳空跌 4.2%：加倉（23000，平均 23500）後即觸止蝕 23030，都以開市價成交", res == ("sl", 23000) and pos.adds == 1, (res, pos.adds))

print("=== 成本 ===")
pos = r.Position(1, 24000, 24100, argparse.Namespace(sl_pct=0.02, step=300, cost=1.0))
res = r.walk(pos, 24000, 24200, False)
check("買 1 張止賺 +100，扣入場、出場各 1 點 = 98", res == ("tp", 24100) and pos.realized == 98, pos.realized)

print("=== 整段回測：訊號、入場、止賺 ===")
bars = []
def add(t, c):
    bars.append({"time_key": t, "open": c, "high": c + 5, "low": c - 5, "close": c})
for k in range(20):                                               # 上一交易日：上下擺動，收市 23900
    add(f"2026-01-05 15:{10 + k:02d}:00", 23900 + (10 if k % 2 else -10) * (k < 19))
seq = [23900 + 30 * k for k in range(1, 11)]                      # 新交易日急升到 24200（+1.26%）
seq += [24170, 24140, 24110, 24080]                               # 回落：RSI 跌回 80 以下
seq += [24120, 24160, 24200, 24240]                               # 再升：RSI 再上穿 80 → 沽
seq += [24240 - 40 * k for k in range(1, 12)]                     # 回落到當日最低位以下
for k, c in enumerate(seq):
    add(f"2026-01-06 09:{16 + k:02d}:00", c)
trades, open_pos = r.run(r.clean([{**b, "volume": 1} for b in bars]),
                         argparse.Namespace(rsi_n=14, rsi_hi=80, rsi_lo=20, move_pct=0.01, same_dir=False,
                                            session_close=False, sl_pct=0.02, step=300, cost=0.0))
t = trades[0] if trades else {}
check("急升途中（當日已升 > 1%）RSI 上穿 80 → 下一根開市沽 1 張", len(trades) == 1 and t["side"] == "沽"
      and t["entry_time"] == "2026-01-06 09:25:00" and t["entry"] == 24200, trades)
check("止賺 = 入場時的當日最低位 23925；開市跳過止賺價 → 以開市價 23920 成交，賺 280 點",
      t.get("tp") == 23925 and t.get("reason") == "tp" and t.get("exit") == 23920 and t.get("pnl_pts") == 280, t)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
