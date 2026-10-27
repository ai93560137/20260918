"""[R345] EURUSD 即日回測規則（research/eurusd_rulesim/rulesim.py）純函數測試：唔連 GCS、唔連 yfinance。"""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/home/user/20260918/research/eurusd_rulesim")
import rulesim  # noqa: E402

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    OK += bool(cond); FAIL += (not cond)
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f" {extra}"))


D = datetime(2026, 10, 27, 0, 0)


def day_bars(path):
    """path：{(h, m): close}（線性插值）→ 00:00–17:59 每分鐘 K 線，高低＝開收 ±0.5 pip。"""
    pts = sorted((D.replace(hour=h, minute=m), c) for (h, m), c in path.items())
    out = []
    t = D
    while t < D.replace(hour=18):
        before = [p for p in pts if p[0] <= t]
        after = [p for p in pts if p[0] > t]
        if not before:
            c = pts[0][1]
        elif not after:
            c = pts[-1][1]
        else:
            (t0, c0), (t1, c1) = before[-1], after[0]
            c = c0 + (c1 - c0) * ((t - t0) / (t1 - t0))
        o = out[-1][4] if out else c
        out.append((t, o, max(o, c) + 0.00005, min(o, c) - 0.00005, c))
        t += timedelta(minutes=1)
    return out


print("=== [R345] EURUSD 倫敦開市區間突破 ===")
# 07:00–07:30 區間 1.1150–1.1160（10 pip），08:00 向上突破去 1.1200，之後回到 1.1190 收市
up = day_bars({(0, 0): 1.1155, (7, 0): 1.1150, (7, 15): 1.1160, (7, 29): 1.1152, (8, 0): 1.1158, (8, 10): 1.1170,
               (10, 0): 1.1200, (12, 0): 1.1190, (17, 59): 1.1190})
t, why = rulesim.run_day(up, 1)
check("升勢日順勢突破 → 做好", t is not None and t["side"] == 1 and why is None, (t, why))
check("止蝕最少 7 pip（區間另一邊只有 ~5 pip 要夾到 7）", t and t["risk_pips"] >= 7.0, t and t["risk_pips"])
check("1R 後移動止蝕、最終移動止蝕／收市出場、有賺", t and t["pips"] > 0 and t["exit_reason"] in ("移動止蝕", "收市平倉", "保本"), t)
check("HKD 按 0.01 手（1 pip = 0.78）", t and abs(t["hkd"] - t["pips"] * 0.78) < 0.1, t and (t["hkd"], t["pips"]))
t2, why2 = rulesim.run_day(up, -1)
check("跌勢日只做淡：向上突破唔入", t2 is None and "突破" in why2, (t2, why2))
t3, why3 = rulesim.run_day(up, 0)
check("冇日線趨勢 → 唔做", t3 is None and "趨勢" in why3, why3)
t4, why4 = rulesim.run_day(up, 0, allow_both=True)
check("變體 D（冇趨勢過濾）→ 跟突破邊做好", t4 is not None and t4["side"] == 1, (t4, why4))
# 突破後反轉打止蝕
down_after = day_bars({(0, 0): 1.1155, (7, 0): 1.1150, (7, 15): 1.1160, (7, 29): 1.1152, (8, 0): 1.1163,
                       (8, 30): 1.1165, (9, 0): 1.1140, (17, 59): 1.1140})
t5, _ = rulesim.run_day(down_after, 1)
check("突破後反轉 → 止蝕、虧損 ≈ −1R 扣 1 pip 成本", t5 is not None and t5["exit_reason"] == "止蝕" and -1.3 < t5["r"] < -0.9, t5)
# 區間太闊（30 pip）唔做
wide = day_bars({(0, 0): 1.1155, (7, 0): 1.1140, (7, 15): 1.1170, (7, 29): 1.1150, (9, 0): 1.1200, (17, 59): 1.1200})
t6, why6 = rulesim.run_day(wide, 1)
check("開市區間 30 pip > 25 → 唔做", t6 is None and "太闊" in why6, why6)
# 15:00 後突破唔入
late = day_bars({(0, 0): 1.1155, (7, 0): 1.1150, (7, 15): 1.1160, (7, 29): 1.1152, (14, 59): 1.1158, (15, 30): 1.1180, (17, 59): 1.1180})
t7, why7 = rulesim.run_day(late, 1)
check("15:00 UTC 後先突破 → 唔入", t7 is None, (t7, why7))
# 區間 K 線唔夠
short = [b for b in up if not (b[0].hour == 7 and b[0].minute < 20)]
t8, why8 = rulesim.run_day(short, 1)
check("開市區間 K 線唔夠 20 根 → 唔做", t8 is None and "唔夠" in why8, why8)
# 統計
rows = [{"date": "2026-10-20", "r": 1.0, "pips": 10, "hkd": 7.8}, {"date": "2026-10-21", "r": -1.0, "pips": -8, "hkd": -6.24},
        {"date": "2026-10-22", "r": 2.0, "pips": 20, "hkd": 15.6}]
st = rulesim.stats(rows)
check("stats：n、勝率、PF、HKD、回撤", st["n"] == 3 and abs(st["win"] - 0.667) < 0.01 and st["pf"] == 3.0 and st["hkd"] == 17.16 and st["max_dd_hkd"] == -6.24, st)
check("stats 空 → n 0", rulesim.stats([]) == {"n": 0})
closes = {f"2026-09-{d:02d}": 1.10 + d * 0.001 for d in range(1, 31)}
check("日線趨勢：昨收 > 20MA → +1", rulesim.trend_of(closes, "2026-10-01") == 1)
check("日線趨勢：唔夠 20 日 → 0", rulesim.trend_of({"2026-09-29": 1.1, "2026-09-30": 1.2}, "2026-10-01") == 0)
check("to5：60 根 M1 → 12 根 M5、高低正確", len(rulesim.to5(up[:60])) == 12 and rulesim.to5(up[:5])[0][2] == max(b[2] for b in up[:5]))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
