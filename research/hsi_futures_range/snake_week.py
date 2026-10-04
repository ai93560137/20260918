"""跟蛇蟠陣方向持倉多日，用風揚陣的「週預計範圍」做止蝕：2 種入市 × 2 種範圍 × 5 種離場 = 20 組回測。

完整規格見 research/hsi_futures_range/snake_week/README.md（規則、優先次序、紀錄欄位、核對方法）。
輸出（--out，預設 research/hsi_futures_range/snake_week/）：
  REPORT.md                 20 組結果、前後半段、逐年、多空腿、離場原因
  manifest.json             輸入數據 SHA-256、程式 SHA-256、git commit、參數
  levels_daily.csv          每個交易日的預測高低位與範圍邊（逐日前推）
  levels_weekly.csv         每週的基準價、預測波幅、預測高低位與範圍邊（逐週前推）
  snake_flips.csv           蛇蟠陣每次反手（時間、新方向、成交價、通道）
  trades/<設定>.csv          每組設定的逐筆交易（含止蝕位變動路徑）
核對：python3 research/hsi_futures_range/snake_week.py --verify  （獨立重算預測位、逐筆檢查成交價與止蝕）

用法：python3 research/hsi_futures_range/snake_week.py [--json 15 分 K 快取] [--cost 3] [--out 目錄]
"""
import argparse, bisect, csv, hashlib, json, math, subprocess, sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402
import snake_band as sb                                  # noqa: E402

COST = 3.0
DAY_MIN = 120                 # 日：至少要有這麼多天的高低位比例才出預測位
WEEK_MIN = 20                 # 週：至少要有這麼多週
QS = (0.9, 0.95)              # 範圍邊：0.9 = 八成範圍外邊，0.95 = 九成範圍外邊
OUT = HERE / "snake_week"
ENTRIES = {"A": "跟蛇同時入", "B": "等回調到預測位才入"}
BANDS = {0.9: "八成範圍", 0.95: "九成範圍"}
EXITS = {"1": "①蛇反手", "2": "②週末平倉", "3": "③週目標", "4": "④移動止蝕（不理蛇反手）", "5": "⑤移動止蝕＋蛇反手"}
FLIP_EXIT = {"1": True, "2": True, "3": True, "4": False, "5": True}
TRAIL = {"4", "5"}


def q(a, p):
    """線性插值分位（與 main._quantile、band_limit.q 相同）。a 已排序。"""
    pos = (len(a) - 1) * p
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(a) - 1)
    return a[lo] + (a[hi] - a[lo]) * (pos - lo)


def week_key(d):
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def cfg_name(entry, qs, ex):
    return f"{entry}_{int(qs * 100)}_{ex}"


def cfg_label(entry, qs, ex):
    return f"{ENTRIES[entry]}・{BANDS[qs]}・{EXITS[ex]}"


# ---- 預測位（逐日／逐週前推） ---------------------------------------------------
def levels(days):
    daily, ups, downs = {}, [], []
    for d in days:
        hi, lo = max(b["high"] for b in d["bars"]), min(b["low"] for b in d["bars"])
        R, ref = d["rhat"], d["ref"]
        if len(ups) >= DAY_MIN:
            lv = {"date": d["date"], "rhat": R, "ref": ref, "n_hist": len(ups),
                  "pred_high": ref + q(ups, 0.5) * R, "pred_low": ref - q(downs, 0.5) * R}
            for qs in QS:
                lv[f"high_edge_{qs}"] = ref + q(ups, qs) * R
                lv[f"low_edge_{qs}"] = ref - q(downs, qs) * R
            daily[d["date"]] = lv
        bisect.insort(ups, (hi - ref) / R)
        bisect.insort(downs, (ref - lo) / R)
    groups, order = defaultdict(list), []
    for i, d in enumerate(days):
        k = week_key(d["date"])
        if k not in groups:
            order.append(k)
        groups[k].append(i)
    weekly, wu, wd = {}, [], []
    for k in order:
        idx = groups[k]
        if idx[0] == 0:
            continue
        anchor = days[idx[0] - 1]["bars"][-1]["close"]
        n = len(idx)
        Rw = days[idx[0]]["rhat"] * math.sqrt(n)
        hi = max(b["high"] for i in idx for b in days[i]["bars"])
        lo = min(b["low"] for i in idx for b in days[i]["bars"])
        if len(wu) >= WEEK_MIN:
            lv = {"week": k, "first": days[idx[0]]["date"], "sessions": n, "anchor": anchor, "R_week": Rw,
                  "n_hist": len(wu), "pred_high": anchor + q(wu, 0.5) * Rw, "pred_low": anchor - q(wd, 0.5) * Rw}
            for qs in QS:
                lv[f"high_edge_{qs}"] = anchor + q(wu, qs) * Rw
                lv[f"low_edge_{qs}"] = anchor - q(wd, qs) * Rw
            weekly[k] = lv
        bisect.insort(wu, (hi - anchor) / Rw)
        bisect.insort(wd, (anchor - lo) / Rw)
    return daily, weekly


# ---- 模擬 -----------------------------------------------------------------------
def simulate(days, daily, weekly, before, flips, entry, qs, ex, cost, stop_src="week"):
    """days：[{date, bars, ...}]（依時間）；before：K 線 → 該根之前的蛇持倉；flips：K 線 → [(新持倉, 成交價)]。
    stop_src：week = 止蝕用週預計範圍邊（snake_week/README.md）；day = 用當天的日預計範圍邊（snake_day/README.md）。
    規則與優先次序見 README.md 第二節。回傳逐筆交易（dict）。"""
    trades, tr = [], None
    last_week = None
    start = next((i for i, d in enumerate(days) if d["date"] in daily and week_key(d["date"]) in weekly), None)
    if start is None:
        return trades
    edge_key = lambda side: f"{'low' if side > 0 else 'high'}_edge_{qs}"

    def open_trade(side, px, t, d, kind, wl, lv):
        stop = (wl if stop_src == "week" else lv)[edge_key(side)]
        if (stop - px) * side >= 0:
            return None                                           # 止蝕不在正確一邊：不做
        target = None
        if ex == "3":
            target = wl["pred_high" if side > 0 else "pred_low"]
            if (target - px) * side <= 0:
                target = None
        return {"side": side, "entry_date": d["date"], "entry_time": t, "entry_price": px, "entry_type": kind,
                "snake_at_entry": before.get(t), "week": wl["week"], "week_anchor": wl["anchor"], "week_R": wl["R_week"],
                "initial_stop": stop, "stop": stop, "target": target, "initial_target": target,
                "stop_path": [(t, stop)], "entry_index": None, "bars": 0}

    def close_trade(tr, px, t, d, reason):
        gross = (px - tr["entry_price"]) * tr["side"]
        risk = abs(tr["entry_price"] - tr["initial_stop"])
        trades.append({**tr, "exit_date": d["date"], "exit_time": t, "exit_price": px, "exit_reason": reason,
                       "gross": gross, "cost": cost, "net": gross - cost, "risk": risk,
                       "r_multiple": (gross - cost) / risk if risk > 0 else float("nan")})

    def same_bar_after_entry(tr, b, t, d):
        """入市那一根：先看止蝕（保守），再看週目標（目標價在該根範圍內才算）。回傳仍持倉的 tr 或 None。"""
        s = tr["side"]
        tr["bars"] += 1
        if (b["low"] <= tr["stop"]) if s > 0 else (b["high"] >= tr["stop"]):
            close_trade(tr, tr["stop"], t, d, "止蝕（同一根）")
            return None
        tg = tr["target"]
        if tg is not None and ((b["high"] >= tg) if s > 0 else (b["low"] <= tg)):
            close_trade(tr, tg, t, d, "週目標")
            return None
        tr["bars"] -= 1                                           # 下一根起才逐根計
        return tr

    for di in range(start, len(days)):
        d = days[di]
        wk = week_key(d["date"])
        if d["date"] not in daily or wk not in weekly:
            continue
        lv, wl = daily[d["date"]], weekly[wk]
        new_week = wk != last_week
        last_week = wk
        last_session_of_week = di + 1 >= len(days) or week_key(days[di + 1]["date"]) != wk
        entered_today = False
        bars = d["bars"]
        for j, b in enumerate(bars):
            t = b["time_key"]
            snake = before.get(t) or 0
            fl = flips.get(t, [])
            exited_this_bar = False
            # (1) 每天第一根：止蝕更新、A 空手再入
            if j == 0:
                if tr:
                    s = tr["side"]
                    new = tr["stop"]
                    if stop_src == "week":
                        if new_week:
                            cand = wl[edge_key(s)]
                            new = (max(new, cand) if s > 0 else min(new, cand)) if ex in TRAIL else cand
                        if ex in TRAIL and tr["entry_date"] != d["date"]:
                            cand = lv[edge_key(s)]
                            new = max(new, cand) if s > 0 else min(new, cand)
                    elif tr["entry_date"] != d["date"]:                   # day：每天重設為當天日範圍邊（④⑤只收緊）
                        cand = lv[edge_key(s)]
                        new = (max(new, cand) if s > 0 else min(new, cand)) if ex in TRAIL else cand
                    if new != tr["stop"]:
                        tr["stop"] = new
                        tr["stop_path"].append((t, new))
                    if ex == "3" and new_week:
                        tg = wl["pred_high" if s > 0 else "pred_low"]
                        tr["target"] = tg if (tg - tr["entry_price"]) * s > 0 else None
                elif entry == "A" and snake != 0:
                    tr = open_trade(snake, b["open"], t, d, "空手・開市再入", wl, lv)
                    entered_today = tr is not None
            # (2)(3) 持倉：跳空止蝕 → 盤中止蝕／蛇反手（取較差價）→ 目標
            if tr:
                s, stop = tr["side"], tr["stop"]
                tr["bars"] += 1
                if (b["open"] - stop) * s <= 0:
                    close_trade(tr, b["open"], t, d, "止蝕（跳空）"); tr, exited_this_bar = None, True
                else:
                    hit_stop = (b["low"] <= stop) if s > 0 else (b["high"] >= stop)
                    against = [f for f in fl if f[0] == -s] if FLIP_EXIT[ex] else []
                    if hit_stop or against:
                        cands = ([(stop, "止蝕")] if hit_stop else []) + ([(against[0][1], "蛇反手")] if against else [])
                        px, why = min(cands, key=lambda c: c[0] * s)       # 對我們較差的價
                        close_trade(tr, px, t, d, why); tr, exited_this_bar = None, True
                    elif tr["target"] is not None and ((b["high"] >= tr["target"]) if s > 0 else (b["low"] <= tr["target"])):
                        tg = tr["target"]                                  # 開市已越過目標 → 開市價（掛單在開市成交）
                        px = max(tg, b["open"]) if s > 0 else min(tg, b["open"])
                        close_trade(tr, px, t, d, "週目標"); tr, exited_this_bar = None, True
            # (4) 空手：入市
            if not tr:
                if entry == "A" and fl:
                    side, px = fl[-1]                                   # 這根最後一次反手後的方向
                    tr = open_trade(side, px, t, d, "蛇反手跟入", wl, lv)
                    if tr:
                        entered_today = True
                        tr = same_bar_after_entry(tr, b, t, d)
                elif entry == "B" and snake != 0 and not entered_today and not exited_this_bar:
                    level = lv["pred_low"] if snake > 0 else lv["pred_high"]
                    touched = (b["low"] <= level) if snake > 0 else (b["high"] >= level)
                    if touched:
                        px = min(level, b["open"]) if snake > 0 else max(level, b["open"])
                        tr = open_trade(snake, px, t, d, "回調掛單成交", wl, lv)
                        entered_today = True
                        if tr:
                            tr = same_bar_after_entry(tr, b, t, d)
            # (5) 週末平倉
            if tr and ex == "2" and last_session_of_week and j == len(bars) - 1:
                close_trade(tr, b["close"], t, d, "週末平倉"); tr = None
    if tr:
        d = days[-1]
        close_trade(tr, d["bars"][-1]["close"], d["bars"][-1]["time_key"], d, "數據完結")
    return trades


# ---- 統計 -----------------------------------------------------------------------
def stats(trs):
    if not trs:
        return {"n": 0}
    p = np.array([t["net"] for t in trs]); r = np.array([t["r_multiple"] for t in trs])
    w, l = p[p > 0], p[p <= 0]
    eq = np.cumsum(p)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq))
    sd = p.std(ddof=1) if len(p) > 1 else float("nan")
    hold = [t["sessions"] for t in trs]
    return {"n": len(p), "win": float((p > 0).mean()), "avg_win": float(w.mean()) if len(w) else 0.0,
            "avg_loss": float(l.mean()) if len(l) else 0.0,
            "rrr": float(w.mean() / -l.mean()) if len(w) and len(l) and l.mean() < 0 else float("nan"),
            "mean": float(p.mean()), "R": float(np.nanmean(r)), "pf": float(w.sum() / -l.sum()) if l.sum() < 0 else float("inf"),
            "t": float(p.mean() / sd * math.sqrt(len(p))) if sd > 0 else float("nan"), "total": float(p.sum()), "dd": dd,
            "hold": float(np.mean(hold))}


def add_sessions(trs, days):
    pos = {d["date"]: i for i, d in enumerate(days)}
    for t in trs:
        t["sessions"] = pos[t["exit_date"]] - pos[t["entry_date"]] + 1
    return trs


HEAD = ("| 設定 | 交易 | 勝率 | 平均賺／平均蝕 | **RRR** | **期望值／筆** | 期望值（R） | 盈虧比 | t 值 | 平均持倉（交易日） | 總點數／最大回撤 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|")


def fmt(s):
    if not s.get("n"):
        return "| 0 | — | — | — | — | — | — | — | — | — |"
    return (f"| {s['n']} | {s['win']:.0%} | +{s['avg_win']:,.0f}／{s['avg_loss']:,.0f} | **{s['rrr']:.2f}** | "
            f"**{s['mean']:+.1f} 點** | {s['R']:+.2f} | {s['pf']:.2f} | {s['t']:+.2f} | {s['hold']:.1f} | "
            f"{s['total']:+,.0f}／{s['dd']:,.0f} |")


# ---- 紀錄輸出 -------------------------------------------------------------------
LEDGER_FIELDS = ["id", "config", "side", "entry_date", "entry_time", "entry_price", "entry_type", "snake_at_entry",
                 "week", "week_anchor", "week_R", "initial_stop", "initial_target", "final_stop", "stop_path",
                 "exit_date", "exit_time", "exit_price", "exit_reason", "bars", "sessions", "gross", "cost", "net",
                 "risk", "r_multiple"]


def write_ledger(path, name, trs):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(LEDGER_FIELDS)
        for i, t in enumerate(trs, 1):
            w.writerow([i, name, "多" if t["side"] > 0 else "空", t["entry_date"], t["entry_time"], f"{t['entry_price']:.4f}",
                        t["entry_type"], t["snake_at_entry"], t["week"], f"{t['week_anchor']:.4f}", f"{t['week_R']:.4f}",
                        f"{t['initial_stop']:.4f}", "" if t["initial_target"] is None else f"{t['initial_target']:.4f}",
                        f"{t['stop']:.4f}", ";".join(f"{a}={b:.4f}" for a, b in t["stop_path"]),
                        t["exit_date"], t["exit_time"], f"{t['exit_price']:.4f}", t["exit_reason"], t["bars"], t["sessions"],
                        f"{t['gross']:.4f}", f"{t['cost']:.4f}", f"{t['net']:.4f}", f"{t['risk']:.4f}", f"{t['r_multiple']:.4f}"])


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in r.items()})


def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def git_head():
    try:
        return subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


# ---- 主程式 ---------------------------------------------------------------------
def load(path):
    if path and Path(path).exists():
        c = json.load(open(path))
        return c["bars"], c["daily"]
    return hl.load_gcs("K_15M")


def build(bars, daily_k, cost):
    days = hl.build_days(bars, daily_k)
    sdays = sb.snake_days(days)
    before, flips, snake_trades = sb.snake_run(sdays, cost)
    dl, wl = levels(days)
    return days, sdays, before, flips, snake_trades, dl, wl


def run_all(days, dl, wl, before, flips, cost, stop_src="week"):
    out = {}
    for entry in ENTRIES:
        for qs in QS:
            for ex in EXITS:
                trs = simulate(days, dl, wl, before, flips, entry, qs, ex, cost, stop_src)
                out[(entry, qs, ex)] = add_sessions(trs, days)
    return out


def report(res, days, dl, wl, snake_trades, cost, manifest, stop_src="week"):
    start = min((t["entry_date"] for trs in res.values() for t in trs), default=days[0]["date"])
    end = days[-1]["date"]
    st = [t for t in snake_trades if t[0] >= start]
    sp = np.array([t[2] for t in st])
    snake_line = (f"{len(sp)} 筆、勝率 {(sp > 0).mean():.0%}、平均賺／蝕 +{sp[sp > 0].mean():,.0f}／{sp[sp <= 0].mean():,.0f}、"
                  f"RRR {sp[sp > 0].mean() / -sp[sp <= 0].mean():.2f}、期望值 {sp.mean():+.1f} 點／筆、"
                  f"盈虧比 {sp[sp > 0].sum() / -sp[sp <= 0].sum():.2f}、t {sp.mean() / sp.std(ddof=1) * math.sqrt(len(sp)):+.2f}、"
                  f"總 {sp.sum():+,.0f} 點") if len(sp) else "—"
    tradable = [d["date"] for d in days if d["date"] >= start]
    mid = tradable[len(tradable) // 2]
    L = [f"# 跟蛇蟠陣持倉多日＋{'週' if stop_src == 'week' else '日'}預計範圍止蝕：20 組回測結果", "",
         f"- 期間：{start} 至 {end}（可交易 {len(tradable)} 個交易日；前半段到 {mid} 前、後半段 {mid} 起）",
         f"- 成本：每筆來回 {cost:g} 點；1 張；點數（恒指每點 HK$50、小型恒指 HK$10）",
         f"- 輸入數據 SHA-256：15 分 K `{manifest['input']['bars_sha256'][:16]}…`、交易日 K `{manifest['input']['daily_sha256'][:16]}…`",
         f"- 程式：`snake_week.py` SHA-256 `{manifest['script_sha256'][:16]}…`；規格見 README.md",
         "", "## 對照：蛇蟠陣本身（同期、同一條 15 分 K 重建）", "", f"- {snake_line}", "",
         "## 20 組結果（全期）", "", HEAD]
    for (e, qs, ex), trs in res.items():
        L.append(f"| {cfg_name(e, qs, ex)} {cfg_label(e, qs, ex)} " + fmt(stats(trs)))
    L += ["", f"## 前半段（{start} 至 {mid} 前）／後半段（{mid} 起）：按入市日期分", "",
          "| 設定 | 前半段 交易 | 前半段 期望值 | 前半段 RRR | 後半段 交易 | 後半段 期望值 | 後半段 RRR | 兩段同號？ |", "|---|---|---|---|---|---|---|---|"]
    for (e, qs, ex), trs in res.items():
        a = stats([t for t in trs if t["entry_date"] < mid]); b = stats([t for t in trs if t["entry_date"] >= mid])
        same = "✅" if a.get("n") and b.get("n") and (a["mean"] > 0) == (b["mean"] > 0) else "❌"
        L.append(f"| {cfg_name(e, qs, ex)} | {a.get('n', 0)} | {a.get('mean', float('nan')):+.1f} | {a.get('rrr', float('nan')):.2f} | "
                 f"{b.get('n', 0)} | {b.get('mean', float('nan')):+.1f} | {b.get('rrr', float('nan')):.2f} | {same} |")
    years = sorted({t["entry_date"][:4] for trs in res.values() for t in trs})
    L += ["", "## 逐年（期望值／筆，括號是交易數；按入市年份）", "", "| 設定 | " + " | ".join(years) + " |", "|---|" + "---|" * len(years)]
    for (e, qs, ex), trs in res.items():
        cells = []
        for y in years:
            s = stats([t for t in trs if t["entry_date"][:4] == y])
            cells.append(f"{s['mean']:+.1f}（{s['n']}）" if s.get("n") else "—")
        L.append(f"| {cfg_name(e, qs, ex)} | " + " | ".join(cells) + " |")
    L += ["", "## 多空腿（期望值／筆，括號是交易數）", "", "| 設定 | 做多 | 做空 |", "|---|---|---|"]
    for (e, qs, ex), trs in res.items():
        lg = stats([t for t in trs if t["side"] > 0]); sh = stats([t for t in trs if t["side"] < 0])
        L.append(f"| {cfg_name(e, qs, ex)} | {lg.get('mean', float('nan')):+.1f}（{lg.get('n', 0)}） | "
                 f"{sh.get('mean', float('nan')):+.1f}（{sh.get('n', 0)}） |")
    L += ["", "## 離場原因（筆數）", "", "| 設定 | 原因 |", "|---|---|"]
    for (e, qs, ex), trs in res.items():
        cnt = defaultdict(int)
        for t in trs:
            cnt[t["exit_reason"]] += 1
        L.append(f"| {cfg_name(e, qs, ex)} | " + "、".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda x: -x[1])) + " |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="15 分 K 快取 {bars, daily}（high_low_in.py 同格式）")
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--stop", choices=("week", "day"), default="week", help="止蝕用週或日預計範圍邊")
    ap.add_argument("--out", help="輸出目錄（預設 week → snake_week/、day → snake_day/）")
    ap.add_argument("--verify", action="store_true", help="只核對已輸出的紀錄（需要同一份輸入數據）")
    a = ap.parse_args()
    bars, daily_k = load(a.json)
    out = Path(a.out) if a.out else (OUT if a.stop == "week" else HERE / "snake_day")
    if a.verify:
        import snake_week_verify as v
        sys.exit(v.verify(bars, daily_k, out))
    days, sdays, before, flips, snake_trades, dl, wl = build(bars, daily_k, a.cost)
    res = run_all(days, dl, wl, before, flips, a.cost, a.stop)
    (out / "trades").mkdir(parents=True, exist_ok=True)
    for (e, qs, ex), trs in res.items():
        write_ledger(out / "trades" / f"{cfg_name(e, qs, ex)}.csv", cfg_name(e, qs, ex), trs)
    write_csv(out / "levels_daily.csv", dl.values(),
              ["date", "rhat", "ref", "n_hist", "pred_high", "pred_low"] + [f"{s}_edge_{x}" for x in QS for s in ("high", "low")])
    write_csv(out / "levels_weekly.csv", wl.values(),
              ["week", "first", "sessions", "anchor", "R_week", "n_hist", "pred_high", "pred_low"]
              + [f"{s}_edge_{x}" for x in QS for s in ("high", "low")])
    rows = []
    for t in sorted(flips):
        for side, px in flips[t]:
            rows.append({"time_key": t, "new_side": side, "price": px})
    write_csv(out / "snake_flips.csv", rows, ["time_key", "new_side", "price"])
    script = Path(__file__).read_bytes()
    manifest = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "git_head": git_head(),
                "script_sha256": hashlib.sha256(script).hexdigest(),
                "input": {"bars": len(bars), "bars_sha256": sha256_json(sorted(bars, key=lambda b: b["time_key"])),
                          "daily": len(daily_k), "daily_sha256": sha256_json(sorted(daily_k, key=lambda b: str(b["time_key"]))),
                          "first_bar": min(b["time_key"] for b in bars), "last_bar": max(b["time_key"] for b in bars)},
                "params": {"stop_source": a.stop, "cost_per_round_trip": a.cost, "day_min": DAY_MIN, "week_min": WEEK_MIN, "bands": list(QS),
                           "snake_lookback": sb.LOOKBACK, "entries": ENTRIES, "exits": EXITS},
                "configs": {cfg_name(e, qs, ex): {"label": cfg_label(e, qs, ex), "trades": len(trs),
                                                  "net_total": round(sum(t["net"] for t in trs), 2)}
                            for (e, qs, ex), trs in res.items()}}
    json.dump(manifest, open(out / "manifest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    text = report(res, days, dl, wl, snake_trades, a.cost, manifest, a.stop)
    (out / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
