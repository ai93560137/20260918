"""[IDEAS #148] Gold Brother 跟單規則回測（research/gb_rulesim/gb_rulesim.py）純函數測試：唔連 GCS、唔連 yfinance。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research", "gb_rulesim"))
import gb_rulesim as gb  # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    OK += bool(cond); FAIL += (not cond)
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f" {extra}"))


T0 = 1_800_000_000


def bars_from(closes, start=T0, step=60, wick=0.3):
    """每分鐘 K 線：開＝上一收，收＝給定；高低＝開收 ± wick。"""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append({"utc": start + i * step, "open": o, "high": max(o, c) + wick, "low": min(o, c) - wick, "close": c})
        prev = c
    return out


BUY = {"sid": "x_1", "ts": T0 + 60 * 40, "utc": "2026-10-29 00:40", "side": "BUY", "lo": 4064.0, "hi": 4066.0, "sl": 4046.0, "tp": [4069.0, 4074.0, 4079.0, 4084.0]}

print("simulate：")
flat = [4065.0] * 40
# 一路升到 TP4
up = flat + [4065 + k for k in range(0, 22)]
r = gb.simulate(bars_from(up), BUY)
check("一路升 → all_tp", r["res"] == "all_tp" and abs(r["pnl"] - 19.0) < 0.6, r)
# 一路跌到 SL（F11 型）
down = flat + [4065 - k for k in range(0, 22)]
r = gb.simulate(bars_from(down), BUY)
check("一路跌 → sl、R −1", r["res"] == "sl" and abs(r["r"] + 1.0) < 0.05, r)
r = gb.simulate(bars_from(down), BUY, sl_cap=10)
check("SL 上限 10 → 蝕一半", r["res"] == "sl" and abs(r["r"] + 0.5) < 0.05, r)
r = gb.simulate(bars_from(down), BUY, mae_stop=10)
check("MAE 止損 10 → mae_stop −0.5R", r["res"] == "mae_stop" and abs(r["r"] + 0.5) < 0.05, r)
r = gb.simulate(bars_from(down), BUY, time_stop=5)
check("時間止損 5 分鐘浮虧 → time_stop", r["res"] == "time_stop" and r["r"] < 0, r)
# 到 TP1 收市 → 保本 → 回落掃保本
be = flat + [4065, 4067, 4069.5, 4070, 4068, 4066, 4064.5, 4063]
r = gb.simulate(bars_from(be), BUY)
check("到 TP1 保本後回落 → be、pnl≈0", r["res"] == "be" and abs(r["pnl"]) < 0.01, r)
r = gb.simulate(bars_from(be), BUY, lock="tp2_be")
check("鎖晚一級：TP1 唔鎖 → 持倉中（open）", r["res"] == "open", r)
r = gb.simulate(bars_from(be), BUY, lock="tp1_flat")
check("TP1 全平 → tp1_flat +4", r["res"] == "tp1_flat" and abs(r["pnl"] - 4.0) < 0.01, r)
# 追價過濾：前 30 分鐘升 29
chase = [4036 + i for i in range(0, 30)] + [4065.0] * 10 + [4065 - k for k in range(0, 22)]
r = gb.simulate(bars_from(chase), BUY, chase=15)
check("先行 20 ≥15 → skip_chase", r["res"] == "skip_chase", r)
r = gb.simulate(bars_from(chase), BUY, chase=25)
check("門檻 25 → 唔略過（先行只有 20）", r["res"] != "skip_chase", r)
pm = gb.pre_move(bars_from(chase), BUY["ts"])
check("pre_move ＝ +20（訊號前 30 根：4045→4065）", pm is not None and abs(pm - 20.0) < 1e-6, pm)
# 回調限價：價格冇回到 4064 → not_filled
r = gb.simulate(bars_from(up), BUY, entry="pullback")
check("回調限價冇回調 → not_filled", r["res"] == "not_filled", r)
pb = flat + [4065, 4064.2, 4063.9, 4066, 4070, 4075, 4080, 4085]
r = gb.simulate(bars_from(pb), BUY, entry="pullback")
check("回調限價成交 4064 → all_tp，pnl 20", r["res"] == "all_tp" and abs(r["pnl"] - 20.0) < 0.01, r)
# 冇 K 線
check("冇 K 線 → no_bars", gb.simulate(bars_from(flat[:10]), BUY)["res"] == "no_bars")

r = gb.simulate(bars_from(up), BUY, sl_cap=10, tp_set=[5, 10, 15, 20])
check("tp_set 5/10/15/20 一路升 → all_tp +20、R＝20/19", r["res"] == "all_tp" and abs(r["pnl"] - 20.0) < 0.01 and abs(r["r"] - 20 / 19) < 0.01, r)
r = gb.simulate(bars_from(up), BUY, sl_cap=10, tp_set=[10], lock="tp1_flat")
check("tp_set [10] 單一 TP＝伺服器 TP → all_tp +10", r["res"] == "all_tp" and abs(r["pnl"] - 10.0) < 0.01, r)
mid = flat + [4065, 4068, 4071, 4075.5, 4076, 4072, 4068, 4064.5, 4062]
r = gb.simulate(bars_from(mid), BUY, sl_cap=10, tp_set=[10, 20])
check("tp_set [10,20] 到 TP1 收市保本 → 回落 → be", r["res"] == "be" and abs(r["pnl"]) < 0.01, r)
check("V11–V14 喺 VARIANTS", all(k in gb.VARIANTS for k in ("V11", "V12", "V13", "V14")))

print("summarize：")
s = gb.summarize([{"res": "all_tp", "r": 1.0, "pnl": 20}, {"res": "sl", "r": -1.0, "pnl": -20}, {"res": "be", "r": 0.0, "pnl": 0}, {"res": "skip_chase", "r": 0.0, "pnl": 0}, {"res": "sl", "r": -0.5, "pnl": -10}])
check("n 4、勝 1 平 1 負 2、ΣR −0.5、略過 1", s["n"] == 4 and s["win"] == 1 and s["flat"] == 1 and s["loss"] == 2 and abs(s["sum_r"] + 0.5) < 1e-9 and s["skipped"] == 1, s)
check("PF 1/1.5", abs(s["pf"] - 0.67) < 0.01, s)
check("最大回撤 −1.5", abs(s["max_dd_r"] + 1.5) < 1e-9, s)
check("最長連敗 1（保本重設、略過唔算）", s["max_loss_streak"] == 1, s)
s2 = gb.summarize([{"res": "sl", "r": -1.0, "pnl": -20}, {"res": "skip_chase", "r": 0.0, "pnl": 0}, {"res": "sl", "r": -1.0, "pnl": -20}])
check("略過唔重設連敗 → 2", s2["max_loss_streak"] == 2, s2)

print("calibrate：")
fut = bars_from([4090.0] * 60, step=300)          # 5 分鐘期貨，一直 4090；訊號中位 4065 → offset 25
sig = dict(BUY, ts=T0 + 300 * 20)
win, off = gb.calibrate(fut, sig)
check("offset 25", off == 25.0, off)
check("校正後開盤 4065", win and abs(win[0]["open"] - 4065.0) < 1e-9, win[:1])
check("窗口含訊號前 60 分鐘", win and win[0]["utc"] >= sig["ts"] - 3600 - 300, win[0]["utc"] - sig["ts"])
check("bar_len 300", gb.bar_len(fut) == 300)

print("parse：")
h = {"sid": "2249680342_6754", "msg_ts": 1793237400.0, "msg_utc": "2026-10-29 01:30:00", "signal": {"kind": "new_signal", "side": "BUY", "entry_low": 4064, "entry_high": 4066, "sl": 4046, "tp": [4069, 4074, 4079, 4084]}}
p = gb.parse_history(h)
check("parse_history 入場訊號", p and p["side"] == "BUY" and p["tp"] == [4069.0, 4074.0, 4079.0, 4084.0], p)
check("parse_history update → None", gb.parse_history({"signal": {"kind": "update"}}) is None)
rec = {"ch": "0342", "kind": "new_signal", "sid": "2249680342_6756", "msg_ts": 1.0, "msg_utc": "2026-10-29 07:30:00", "side": "SELL", "entry_low": 4029, "entry_high": 4031, "sl": 4049, "tp": [4026, 4021, 4016, 4011]}
check("parse_recent 0342", gb.parse_recent(rec) is not None and gb.parse_recent(dict(rec, ch="5231")) is None)

check("out_prefix 0342 沿用舊位、5117 分開", gb.out_prefix("2249680342") == "xau/sig/gb_rulesim/" and gb.out_prefix("1473735117") == "xau/sig/gb_rulesim/5117/")
check("parse_recent 指定 5117", gb.parse_recent(dict(rec, ch="5117"), "5117") is not None and gb.parse_recent(rec, "5117") is None)

import lzma, struct
recs = b"".join(struct.pack(">5if", i * 60, 4000000 + i, 4000500 + i, 3999500 + i, 4001000 + i, 1.5) for i in range(3))
day_bars = gb.decode_duka_day(lzma.compress(recs, format=lzma.FORMAT_ALONE), 1800000000)
check("Dukascopy 解碼 3 根、價 ÷1000", len(day_bars) == 3 and abs(day_bars[0]["open"] - 4000.0) < 1e-9 and abs(day_bars[0]["close"] - 4000.5) < 1e-9 and day_bars[1]["utc"] == 1800000060, day_bars[:1])
check("Dukascopy 高低欄位", abs(day_bars[0]["high"] - 4001.0) < 1e-9 and abs(day_bars[0]["low"] - 3999.5) < 1e-9)
check("Dukascopy 空檔 → []", gb.decode_duka_day(b"", 0) == [] and gb.decode_duka_day(b"xx", 0) == [])

print("run_all / to_markdown：")
sigs = [BUY, dict(BUY, sid="x_2", ts=T0 + 60 * 40, side="SELL", lo=4064.0, hi=4066.0, sl=4084.0, tp=[4061.0, 4056.0, 4051.0, 4046.0])]
res, dropped = gb.run_all(sigs, lambda s: (bars_from(up), 0.0), variants={"V0": gb.VARIANTS["V0"], "V2": gb.VARIANTS["V2"]})
check("兩變體、兩張", set(res) == {"V0", "V2"} and res["V0"]["summary"]["n"] == 2 and not dropped, res["V0"]["summary"])
check("BUY all_tp、SELL sl", res["V0"]["per_signal"][0]["res"] == "all_tp" and res["V0"]["per_signal"][1]["res"] == "sl")
md = gb.to_markdown(res, dropped, {"run_utc": "t", "n_signals": 2, "n_used": 2, "since": "2026-09-01", "price_src": "test"})
check("markdown 有表頭同 V0 行", "| V0 |" in md and "| 變體 |" in md)
res2, dropped2 = gb.run_all(sigs, lambda s: ([], None), variants={"V0": gb.VARIANTS["V0"]})
check("冇 K 線 → dropped 2", len(dropped2) == 2 and res2["V0"]["summary"]["n"] == 0)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
