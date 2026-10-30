"""[IDEAS #149／#150] gb_forward 純函數測試：唔連 GCS。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "research", "gb_rulesim"))
import gb_forward as fw  # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    OK += bool(cond); FAIL += (not cond)
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f" {extra}"))


rec = {"ch": "0342", "kind": "new_signal", "sid": "2249680342_6800", "msg_ts": 1793300000.0, "msg_utc": "2026-10-29 18:00:00",
       "side": "BUY", "entry_low": 4030, "entry_high": 4032, "sl": 4012, "tp": [4035, 4040, 4045, 4050], "text": "原文唔應存"}
d = fw.archive_doc(rec)
check("0342 入場訊號歸檔", d and d["ch"] == "0342" and d["side"] == "BUY")
check("唔存原文", d and "text" not in d)
check("5117 都歸檔", fw.archive_doc(dict(rec, ch="5117", sid="1473735117_1")) is not None)
check("[#152] CTC 都歸檔（只歸檔、唔計變體）", (fw.archive_doc(dict(rec, ch="5231", sid="3996305231_1")) or {}).get("ch") == "5231")
check("其他頻道唔歸檔", fw.archive_doc(dict(rec, ch="7713")) is None)
check("update 唔歸檔", fw.archive_doc(dict(rec, kind="update")) is None)

T0 = 1793300000


def bars(closes, start=T0 - 3600):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append({"utc": start + i * 60, "open": prev, "high": max(prev, c) + 0.2, "low": min(prev, c) - 0.2, "close": c})
        prev = c
    return out


B = bars([4031.0] * 60 + [4031 + k * 0.5 for k in range(0, 60)] + [4060.0] * 400)
sig = dict(fw.archive_doc(rec), ts=float(T0))
ev = fw.evaluate([sig], B, 0)
e = ev["0342"]
check("訊號後 ≥6 小時先計（7.6 小時 K 線 → done 1）", e["done"] == 1 and e["pending"] == 0, e)
check("一路升 V0 all_tp", e["result"]["V0"]["per_signal"][0]["res"] == "all_tp", e["result"]["V0"]["per_signal"])
check("V13 SL10 TP10 → all_tp +10", abs(e["result"]["V13"]["per_signal"][0]["pnl"] - 10) < 0.6, e["result"]["V13"]["per_signal"])
check("未夠 20 張", e["verdict"].startswith("未夠 1／20"), e["verdict"])
ev2 = fw.evaluate([sig], B[:300], 0)
check("K 線未夠 6 小時 → pending", ev2["0342"]["done"] == 0 and ev2["0342"]["pending"] == 1)
old = dict(sig, utc="2026-10-28 10:00:00")
check("起計日前嘅唔計", fw.evaluate([old], B, 0)["0342"]["done"] == 0)

s_ok = {"n": 20, "sum_r": 3.0, "pf": 1.5, "max_dd_r": -2.0}
v, c = fw.judge(s_ok, {"sum_r": -1.0})
check("判法：全部過 → 達標", v == "達標", c)
v, c = fw.judge(dict(s_ok, max_dd_r=-3.5), {"sum_r": -1.0})
check("判法：回撤 −3.5 → 唔達標", v == "唔達標" and c["回撤≤3R"] is False, c)
v, c = fw.judge(s_ok, {"sum_r": 4.0})
check("判法：輸畀 V0 → 唔達標", v == "唔達標" and c["好過V0"] is False, c)
md = fw.to_md(ev, {"run_utc": "t", "archived": 1, "new": 1, "bars_to": "x"})
check("markdown 有兩個頻道", "Gold Brother（0342）" in md and "黃金戰鬥機（5117）" in md)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
