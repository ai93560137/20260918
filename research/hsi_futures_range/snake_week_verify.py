"""snake_week.py 輸出的獨立核對（不重用模擬邏輯，只用原始 K 線與紀錄檔互相對照）。

核對項目（每項列出通過／失敗數，任何失敗 → 結束碼 1）：
  L1 每日預測位：用 numpy.quantile 重算之前所有日子的高低位比例分位，跟 levels_daily.csv 比（誤差 ≤ 0.01 點）。
  L2 每週預測位：同上，週。
  S1 蛇蟠陣反手：獨立重建「蛇日」（夜市屬下一個交易日）與前 3 蛇日通道，每次反手的價 = 通道價或跳空開市價，且在該根 K 線範圍內。
  T1 成交價在該根 K 線範圍內（入市、離場）。
  T2 持倉期間（入市那根之後、離場那根之前）沒有任何一根 K 線碰到當時有效的止蝕位。
  T3 離場原因與價格吻合：止蝕＝當時止蝕位（跳空＝開市價）；蛇反手＝同一根有反方向反手且價相同；
     週末平倉＝該週最後一根的收市價；週目標＝該根碰到目標價。
  T4 淨利 = (離場 − 入市) × 方向 − 成本；R 倍數 = 淨利 ÷ 風險。
  T5 同一設定的交易不重疊；「蛇反手跟入」的入市價 = 同一根的反手價；「回調掛單成交」的入市價不差過當天預測位。
"""
import csv, math, sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402

EPS = 0.01


class Tally:
    def __init__(self):
        self.ok, self.bad = defaultdict(int), defaultdict(list)

    def check(self, key, cond, msg=""):
        if cond:
            self.ok[key] += 1
        else:
            self.bad[key].append(msg)

    def summary(self):
        lines, fail = [], 0
        for k in sorted(set(self.ok) | set(self.bad)):
            n_bad = len(self.bad[k])
            fail += n_bad
            lines.append(f"  {'✅' if not n_bad else '❌'} {k}: 通過 {self.ok[k]}、失敗 {n_bad}"
                         + (f"（例：{self.bad[k][0]}）" if n_bad else ""))
        return "\n".join(lines), fail


def wk(d):
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def read(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def verify(bars, daily_k, out):
    out = Path(out)
    T = Tally()
    days = hl.build_days(bars, daily_k)
    allbars = [b for d in days for b in d["bars"]]
    by_t = {b["time_key"]: b for b in allbars}
    order = {b["time_key"]: i for i, b in enumerate(allbars)}
    day_of = {b["time_key"]: d["date"] for d in days for b in d["bars"]}
    # ---- L1／L2 預測位
    ld = {r["date"]: r for r in read(out / "levels_daily.csv")}
    ups, downs = [], []
    for d in days:
        R, ref = d["rhat"], d["ref"]
        if d["date"] in ld:
            r = ld[d["date"]]
            exp = {"pred_high": ref + np.quantile(ups, 0.5) * R, "pred_low": ref - np.quantile(downs, 0.5) * R}
            for qs in ("0.9", "0.95"):
                exp[f"high_edge_{qs}"] = ref + np.quantile(ups, float(qs)) * R
                exp[f"low_edge_{qs}"] = ref - np.quantile(downs, float(qs)) * R
            for k, v in exp.items():
                T.check("L1 每日預測位", abs(float(r[k]) - v) <= EPS, f"{d['date']} {k} {r[k]} vs {v:.4f}")
        hi, lo = max(b["high"] for b in d["bars"]), min(b["low"] for b in d["bars"])
        ups.append((hi - ref) / R); downs.append((ref - lo) / R)
    T.check("L1 每日預測位（有輸出）", len(ld) > 0)
    lw = {r["week"]: r for r in read(out / "levels_weekly.csv")}
    groups = defaultdict(list)
    for i, d in enumerate(days):
        groups[wk(d["date"])].append(i)
    wu, wd = [], []
    for k in sorted(groups, key=lambda k: groups[k][0]):
        idx = groups[k]
        if idx[0] == 0:
            continue
        anchor = days[idx[0] - 1]["bars"][-1]["close"]
        Rw = days[idx[0]]["rhat"] * math.sqrt(len(idx))
        if k in lw:
            r = lw[k]
            T.check("L2 每週預測位", abs(float(r["anchor"]) - anchor) <= EPS and abs(float(r["R_week"]) - Rw) <= EPS,
                    f"{k} anchor/R")
            for qs in ("0.9", "0.95"):
                T.check("L2 每週預測位", abs(float(r[f"low_edge_{qs}"]) - (anchor - np.quantile(wd, float(qs)) * Rw)) <= EPS, k)
                T.check("L2 每週預測位", abs(float(r[f"high_edge_{qs}"]) - (anchor + np.quantile(wu, float(qs)) * Rw)) <= EPS, k)
        hi = max(b["high"] for i in idx for b in days[i]["bars"]); lo = min(b["low"] for i in idx for b in days[i]["bars"])
        wu.append((hi - anchor) / Rw); wd.append((anchor - lo) / Rw)
    # ---- S1 蛇蟠陣反手
    sday = {}
    for i, d in enumerate(days):
        nxt = days[i + 1]["date"] if i + 1 < len(days) else None
        for b in d["bars"]:
            h = b["time_key"][11:16]
            sday[b["time_key"]] = d["date"] if (b["time_key"][:10] == d["date"] and "09:00" <= h < "17:00") else nxt
    sdates = sorted({v for v in sday.values() if v})
    hi_s, lo_s = defaultdict(lambda: -1e18), defaultdict(lambda: 1e18)
    for t, s in sday.items():
        if s:
            hi_s[s] = max(hi_s[s], by_t[t]["high"]); lo_s[s] = min(lo_s[s], by_t[t]["low"])
    pos_s = {s: i for i, s in enumerate(sdates)}
    flips = defaultdict(list)
    for r in read(out / "snake_flips.csv"):
        t, side, px = r["time_key"], int(r["new_side"]), float(r["price"])
        flips[t].append((side, px))
        b, s = by_t.get(t), sday.get(t)
        if not b or s is None or pos_s[s] < 3:
            T.check("S1 蛇反手", False, f"{t} 找不到 K 線或蛇日")
            continue
        prev = sdates[pos_s[s] - 3:pos_s[s]]
        up, dn = max(hi_s[x] for x in prev), min(lo_s[x] for x in prev)
        exp = max(up, b["open"]) if side > 0 else min(dn, b["open"])
        T.check("S1 蛇反手", abs(px - exp) <= EPS and b["low"] - EPS <= px <= b["high"] + EPS, f"{t} {side} {px} vs {exp}")
    # ---- T 逐筆
    last_bar_of_week = {}
    for k, idx in groups.items():
        last_bar_of_week[days[idx[-1]]["bars"][-1]["time_key"]] = k
    for path in sorted((out / "trades").glob("*.csv")):
        name = path.stem
        prev_exit = None
        for r in read(path):
            side = 1 if r["side"] == "多" else -1
            et, xt = r["entry_time"], r["exit_time"]
            ep, xp = float(r["entry_price"]), float(r["exit_price"])
            eb, xb = by_t.get(et), by_t.get(xt)
            tag = f"{name}#{r['id']}"
            T.check("T1 成交價在 K 線範圍內", eb is not None and xb is not None
                    and eb["low"] - EPS <= ep <= eb["high"] + EPS and xb["low"] - EPS <= xp <= xb["high"] + EPS, tag)
            if eb is None or xb is None:
                continue
            path_ = [(a, float(b)) for a, b in (x.split("=") for x in r["stop_path"].split(";"))]

            def stop_at(t):
                s = path_[0][1]
                for a, b in path_:
                    if a <= t:
                        s = b
                return s
            breached = None
            for i in range(order[et] + 1, order[xt]):
                b = allbars[i]
                s = stop_at(b["time_key"])
                if (b["low"] <= s - EPS) if side > 0 else (b["high"] >= s + EPS):
                    breached = b["time_key"]; break
            T.check("T2 持倉期間沒有碰到止蝕", breached is None, f"{tag} {breached}")
            why = r["exit_reason"]
            s_x = stop_at(xt)
            if why.startswith("止蝕（跳空）"):
                ok = abs(xp - xb["open"]) <= EPS and ((xb["open"] <= s_x + EPS) if side > 0 else (xb["open"] >= s_x - EPS))
            elif why.startswith("止蝕"):
                ok = abs(xp - s_x) <= EPS
            elif why == "蛇反手":
                ok = any(f[0] == -side and abs(f[1] - xp) <= EPS for f in flips.get(xt, []))
            elif why == "週末平倉":
                ok = xt in last_bar_of_week and abs(xp - xb["close"]) <= EPS
            elif why == "週目標":
                ok = (xb["high"] >= xp - EPS) if side > 0 else (xb["low"] <= xp + EPS)
            elif why == "數據完結":
                ok = xt == allbars[-1]["time_key"]
            else:
                ok = False
            T.check("T3 離場原因與價格吻合", ok, f"{tag} {why} {xp} 止蝕 {s_x}")
            net = (xp - ep) * side - float(r["cost"])
            risk = abs(ep - float(r["initial_stop"]))
            T.check("T4 淨利與 R 倍數", abs(net - float(r["net"])) <= EPS and abs(risk - float(r["risk"])) <= EPS
                    and (risk == 0 or abs(net / risk - float(r["r_multiple"])) <= 1e-3), tag)
            T.check("T5 交易不重疊", prev_exit is None or order[et] >= order[prev_exit], tag)
            prev_exit = xt
            if r["entry_type"] == "蛇反手跟入":
                T.check("T5 蛇反手跟入＝反手價", any(f[0] == side and abs(f[1] - ep) <= EPS for f in flips.get(et, [])), tag)
            elif r["entry_type"] == "回調掛單成交":
                lv = ld[day_of[et]]
                level = float(lv["pred_low"] if side > 0 else lv["pred_high"])
                T.check("T5 回調掛單價不差過預測位", (ep <= level + EPS) if side > 0 else (ep >= level - EPS), tag)
            elif r["entry_type"] == "空手・開市再入":
                T.check("T5 開市再入＝當天第一根開市價", abs(ep - eb["open"]) <= EPS
                        and days[[d["date"] for d in days].index(day_of[et])]["bars"][0]["time_key"] == et, tag)
    text, fail = T.summary()
    print(f"核對 {out}：\n{text}\n{'全部通過' if not fail else f'失敗 {fail} 項'}")
    return 1 if fail else 0
