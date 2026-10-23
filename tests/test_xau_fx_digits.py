"""10-23 修：UPDATE_STOP 嘅止損／止賺要按產品小數位 round（EURUSD 5 位），唔可以寫死 2 位。
10-22 EURUSD 14 次 modify 全部 sl=1.12000 tp=1.12000 → EA invalid stops，止損停喺開倉位。"""
import os, sys, types
os.environ.update(XAU_SYMBOL="EURUSD", XAU_EXECUTE="1", WEBHOOK_SECRET_TOKEN="tok", ANTHROPIC_API_KEY="x")
sys.path.insert(0, "/home/user/20260918/xau")
import config, rules, executor   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

print("=== EURUSD：5 位小數 ===")
check("EURUSD profile digits=5、magic 922", config.PRICE_DIGITS == 5 and config.MAGIC == 922, (config.SYMBOL, config.PRICE_DIGITS, config.MAGIC))
pos = {"side": -1, "entry": 1.12100, "stop": 1.12180, "target": 1.11940}
a, stop, target, why = rules.validate_decision({"action": "UPDATE_STOP", "stop_price": 1.12107, "target_price": None}, position=pos, last=1.12010, can_open=True, trades_today=0)
check("UPDATE_STOP 止損保留 5 位 1.12107、止賺沿用 1.1194、SL≠TP", a == "UPDATE_STOP" and stop == 1.12107 and target == 1.1194 and stop != target, (a, stop, target, why))
a, stop, target, why = rules.validate_decision({"action": "UPDATE_STOP", "stop_price": 1.121234567, "target_price": 1.11701234}, position=pos, last=1.12010, can_open=True, trades_today=0)
check("多過 5 位 → round 到 5 位", stop == 1.12123 and target == 1.11701, (stop, target))
state = {"pending_cmds": []}
text = executor.enqueue(state, "UPDATE_STOP", 1.12107, 1.1194, 1000.0, "abcdef1234")
check("modify 指令文字 5 位：sl=1.12107 tp=1.11940 magic=922", text == "modify|all|sl=1.12107|tp=1.11940|magic=922|id=abcdef12", text)
text = executor.enqueue(state, "OPEN_SHORT", 1.12180, 1.11940, 1000.0, "0123456789")
check("open 指令文字 5 位（之前已經啱）", "sl=1.12180|tp=1.11940" in text, text)

print("=== XAUUSD 唔受影響（2 位）===")
class Cfg2:
    PRICE_DIGITS = 2; MIN_SL_USD = config.MIN_SL_USD; MAX_SL_USD = config.MAX_SL_USD; MIN_CONFIDENCE = config.MIN_CONFIDENCE
    MAX_TRADES_PER_DAY = config.MAX_TRADES_PER_DAY; LONG_ONLY = False
for k in dir(config):
    if k.isupper() and not hasattr(Cfg2, k):
        setattr(Cfg2, k, getattr(config, k))
a, stop, target, why = rules.validate_decision({"action": "UPDATE_STOP", "stop_price": 4008.004, "target_price": None}, position={"side": -1, "entry": 4010, "stop": 4015, "target": 3990}, last=4005.0, can_open=True, trades_today=0, cfg=Cfg2)
check("XAUUSD cfg digits=2：空單止損 4008.004 → 4008.0、止賺沿用", a == "UPDATE_STOP" and stop == 4008.0 and target == 3990, (a, stop, target, why))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
