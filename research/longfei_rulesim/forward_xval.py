"""龍飛陣前向測試交叉驗證（使用者 10-31「LEVEL 同其他前向測試都做證，以免錯判」，經總指揮轉達）。

起因：天覆陣 rev15 實時 +0.22R 但離線 −0.07R，差距來自冷卻相位揀中唔同單（research/student_offline/REV15_GAP.md）。
呢度對龍飛陣每個進行中嘅前向測試做同樣檢查：
  ① 離線全期 vs 前向同期（同一套計法）；② 逐筆配對（離線全期切出前向期間 vs 前向自己由開始日跑）；
  ③ 開始時間／參數相位敏感度；④ 標準誤；⑤ 結論（實時可信／離線為準／樣本不足）。

子命令：
  hsi    （本機，要 GCS 讀權）R286 方法 A／B（IDEAS #125）、MHI 新規則（IDEAS #135）
  daily  （GitHub Actions，要 yfinance）#143 V3 日線順勢前向

用法：python3 research/longfei_rulesim/forward_xval.py hsi|daily [--out 結果.json]
只出點數／R／百分比，唔出港幣金額。
"""
import argparse
import json
import math
import random
import statistics
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402

UM_SINCE = "2026-10-23"          # #125 凍結／前向開始
MHI_SINCE = datetime(2026, 10, 27, 18, 10)   # #135 新規則生效


def st(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n == 0:
        return {"n": 0}
    m = statistics.mean(xs)
    if n < 2:
        return {"n": n, "mean": round(m, 2)}
    sd = statistics.stdev(xs)
    se = sd / math.sqrt(n)
    return {"n": n, "mean": round(m, 2), "sd": round(sd, 2), "se": round(se, 2),
            "t": round(m / se, 2) if se else None, "win": round(sum(x > 0 for x in xs) / n, 3)}


def diff_z(a, b):
    """前向 a vs 離線 b 平均差嘅 z（Welch）；樣本 < 2 返 None。"""
    if a.get("n", 0) < 2 or b.get("n", 0) < 2:
        return None
    return round((a["mean"] - b["mean"]) / math.sqrt(a["se"] ** 2 + b["se"] ** 2), 2)


# ---------- R286 方法 A（user_method.method_a，加 5 分鐘相位參數）----------
def method_a_phase(bars, keys, ctx, since=None, phase=4):
    trades, busy_until, done = [], None, set()
    for i, (t, o, h, lo, c) in enumerate(bars):
        if t.minute % 5 != phase or not any(a <= t.time() < b for a, b in um.WINDOWS):
            continue
        sd = um.session_date(t)
        x = ctx.get(sd)
        if not x or sd in done or (busy_until and t <= busy_until) or (since and sd.isoformat() < since):
            continue
        if not (x["pdc"] < x["sma"] and c <= x["open"] - um.ENTRY_OPEN_ATR * x["atr"]
                and c <= x["pdl"] + um.ENTRY_PDL_ATR * x["atr"]):
            continue
        done.add(sd)
        px, t_out = um.manage(bars, i, -1, c, x["atr"], keys)
        busy_until = t_out
        pts = (c - px) - 2 * um.COST
        trades.append({"entry_t": t.strftime("%Y-%m-%d %H:%M"), "day": sd.isoformat(), "pts": round(pts, 1),
                       "r": round(pts / (um.STOP_ATR * x["atr"]), 3)})
    return trades


def part_hsi():
    from google.cloud import storage
    import swing_check as sc
    b = storage.Client().bucket(um.GCS_BUCKET)
    raw = {}
    for x in b.list_blobs(prefix=um.GCS_BARS):
        try:
            raw[x.name.rsplit("/", 1)[1][:10]] = json.loads(x.download_as_bytes())
        except Exception:  # noqa: BLE001
            continue
    pnl = json.loads(b.blob("futu/pnl/latest.json").download_as_bytes())
    bars = um.load(raw)
    dkeys, ctx = um.daily(bars)
    out = {"bars": [str(bars[0][0]), str(bars[-1][0])]}

    # ---- #125 方法 A ----
    A = {}
    full = method_a_phase(bars, dkeys, ctx, None, 4)
    fwd_run = method_a_phase(bars, dkeys, ctx, UM_SINCE, 4)
    fwd_slice = [t for t in full if t["day"] >= UM_SINCE]
    fit = [t for t in full if t["day"] < UM_SINCE]
    A["offline_full"] = st([t["pts"] for t in full])
    A["offline_before_since"] = st([t["pts"] for t in fit])
    A["offline_slice_fwd_period"] = st([t["pts"] for t in fwd_slice])
    A["forward_run"] = st([t["pts"] for t in fwd_run])
    s1, s2 = {t["entry_t"] for t in fwd_slice}, {t["entry_t"] for t in fwd_run}
    A["pairing"] = {"both": len(s1 & s2), "only_offline": sorted(s1 - s2), "only_forward": sorted(s2 - s1)}
    A["forward_trades"] = fwd_run
    A["z_forward_vs_offline_before"] = diff_z(A["forward_run"], A["offline_before_since"])
    # 相位：5 分鐘收市用邊一分鐘（富途 time_key＝分鐘結束；現行 minute%5==4，即 :x4／:x9）
    A["phase"] = {}
    for ph in range(5):
        f = method_a_phase(bars, dkeys, ctx, None, ph)
        A["phase"][ph] = {"full": st([t["pts"] for t in f]),
                          "fwd_slice": st([t["pts"] for t in f if t["day"] >= UM_SINCE])}
    # 開始時間：由前向開始日前後幾日開始跑，前向期間結果
    A["start"] = {}
    for d in ("2026-10-16", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"):
        f = method_a_phase(bars, dkeys, ctx, d, 4)
        A["start"][d] = st([t["pts"] for t in f if t["day"] >= UM_SINCE])
    out["method_a"] = A

    # ---- #125 方法 B（使用者入場、系統出場）----
    B = {}
    bfull = um.method_b(bars, dkeys, ctx, pnl, None)
    brun = um.method_b(bars, dkeys, ctx, pnl, UM_SINCE)
    bfwd = [t for t in bfull if um.session_date(datetime.strptime(t["entry_t"], "%Y-%m-%d %H:%M")).isoformat() >= UM_SINCE]
    bfit = [t for t in bfull if t not in bfwd]
    B["offline_before_since"] = st([t["managed_pts"] for t in bfit])
    B["offline_before_since_actual"] = st([t["actual_pts"] for t in bfit])
    B["offline_slice_fwd_period"] = st([t["managed_pts"] for t in bfwd])
    B["forward_run"] = st([t["managed_pts"] for t in brun])
    B["forward_actual"] = st([t["actual_pts"] for t in brun])
    k1 = {(t["entry_t"], t["side"]): t["managed_pts"] for t in bfwd}
    k2 = {(t["entry_t"], t["side"]): t["managed_pts"] for t in brun}
    B["pairing"] = {"both": len(set(k1) & set(k2)),
                    "same_result": sum(1 for k in set(k1) & set(k2) if abs(k1[k] - k2[k]) < 0.05),
                    "only_offline": len(set(k1) - set(k2)), "only_forward": len(set(k2) - set(k1))}
    B["z_forward_vs_offline_before"] = diff_z(B["forward_run"], B["offline_before_since"])
    B["forward_hit_stop"] = sum(1 for t in brun if t["managed_pts"] <= -120)
    out["method_b"] = B

    # ---- #135 MHI 新規則：真倉逐筆 vs 同一入場離線模擬（swing_check S）----
    keys = sc.day_keys(bars)
    idx_by_t = {bb[0]: i for i, bb in enumerate(bars)}
    lf = json.loads(b.blob("longfei/real/MHI/latest.json").download_as_bytes())
    trades = lf.get("trades", [])
    opens = [t for t in trades if t.get("type") == "OPEN"
             and datetime.fromisoformat(t["ts"]).replace(tzinfo=None) >= MHI_SINCE]
    closes = [t for t in trades if t.get("type") == "CLOSE"]
    M = {"pairs": []}
    for o in opens:
        t0 = datetime.fromisoformat(o["ts"]).replace(tzinfo=None, second=0, microsecond=0)
        c = next((c for c in closes if c.get("opened_at", "")[:16] == o["ts"][:16]
                  or (c["ts"] > o["ts"] and c.get("entry") == o["price"])), None)
        j = next((k for k in range(len(bars)) if bars[k][0] > t0), None)   # 富途 time_key＝分鐘結束：入場嗰分鐘之後第一支
        if j is None:
            continue
        sim = sc.run(bars, keys, j - 1 if j else j, o["side"], o["price"], "S")
        shifts = {}
        for sh in (-2, -1, 0, 1, 2, 5):
            jj = j - 1 + sh
            if 0 < jj < len(bars):
                shifts[sh] = round(sc.run(bars, keys, jj, o["side"], bars[jj][4], "S"), 1)
        M["pairs"].append({"entry": o["ts"][:16], "side": o["side"], "px": o["price"], "stop": o.get("stop"),
                           "real_pts_net": (c["points"] - 2 * sc.COST) if c else None,
                           "real_exit": c["ts"][:16] if c else None, "real_reason": (c or {}).get("reason"),
                           "sim_pts_net": round(sim, 1), "entry_shift_sim_pts": shifts})
    M["real"] = st([p["real_pts_net"] for p in M["pairs"]])
    M["sim_same_entries"] = st([p["sim_pts_net"] for p in M["pairs"]])
    # 順日線隨機（T）基準：全期 vs 新規則期間（同 swing_check：每日 1 次、20 個種子）
    by_day = {}
    for i, (t, *_r) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in sc.WINDOWS):
            sd = um.session_date(t)
            x = ctx.get(sd)
            if x:
                by_day.setdefault(sd, []).append((i, 1 if x["pdc"] > x["sma"] else -1))
    full_means, fwd_all = [], []
    for seed in range(20):
        rnd = random.Random(seed)
        xs = []
        for sd in sorted(by_day):
            i, s = rnd.choice(by_day[sd])
            xs.append((sd, sc.run(bars, keys, i, s, bars[i][4], "S")))
        full_means.append(statistics.mean(v for _, v in xs))
        fwd_all += [v for d, v in xs if d >= MHI_SINCE.date() + timedelta(days=1)]
    M["T_full_mean_of_20"] = round(statistics.mean(full_means), 2)
    M["T_full_seed_range"] = [round(min(full_means), 1), round(max(full_means), 1)]
    one = random.Random(0)
    xs0 = []
    for sd in sorted(by_day):
        i, s = one.choice(by_day[sd])
        xs0.append(sc.run(bars, keys, i, s, bars[i][4], "S"))
    M["T_full_seed0"] = st(xs0)
    M["T_fwd_period_pooled_20seeds"] = st(fwd_all)
    out["mhi_135"] = M
    return out


# ---------- #143 V3（GitHub Actions）----------
def part_daily():
    import yfinance as yf
    from google.cloud import storage
    from rulesim import US
    COST = 0.0005
    df = yf.download(US, start="2019-01-01", interval="1d", progress=False, auto_adjust=True, group_by="ticker")
    closes = {}
    for p in US:
        try:
            s = df[p]["Close"].dropna()
        except KeyError:
            continue
        closes[p] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
    alld = sorted({d for c in closes.values() for d in c})

    def series(win=200, first_cost=True):
        pos = {}
        for p, c in closes.items():
            ks = [d for d in alld if d in c]
            cur, o = 0.0, {}
            for i, d in enumerate(ks):
                if i >= win:
                    cur = 1.0 if c[d] > sum(c[k] for k in ks[i - win:i]) / win else 0.0
                o[d] = cur
            pos[p] = o
        port, prev = {}, {}
        for i in range(1, len(alld)):
            d0, d1 = alld[i - 1], alld[i]
            rs = n = 0
            for p, c in closes.items():
                if d0 in c and d1 in c:
                    w = pos[p].get(d0, 0.0)
                    base = prev.get(p, 0.0 if first_cost else w)
                    rs += w * (c[d1] / c[d0] - 1) - abs(w - base) * COST
                    prev[p] = w
                    n += 1
            port[d1] = rs / n if n else 0.0
        return port

    fwd = json.loads(storage.Client().bucket("zhuge-risk-manager-bucket").blob(
        "longfei/daily_trend/forward.json").download_as_bytes())
    base = series()
    rows = []
    for r in fwd["rows"]:
        rows.append({"date": r["date"], "forward": r["ret"], "offline": round(base.get(r["date"], float("nan")), 5)})
    oos = [v for d, v in base.items() if d >= "2020-01-01"]
    res = {"pairs": rows,
           "max_abs_diff": max((abs(r["forward"] - r["offline"]) for r in rows), default=None),
           "offline_oos_daily": st([v * 100 for v in oos]),          # 單位：%
           "forward_daily": st([r["forward"] * 100 for r in rows]),
           "phase": {}}
    for win in (190, 200, 210):
        s = series(win)
        res["phase"][f"sma{win}"] = {"oos_daily_pct": st([v * 100 for d, v in s.items() if d >= "2020-01-01"]),
                                     "fwd_days": [round(s.get(r["date"], float("nan")), 5) for r in rows]}
    s = series(200, first_cost=False)
    res["phase"]["no_first_day_cost"] = [round(s.get(r["date"], float("nan")), 5) for r in rows]
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/xval/daily_trend.json").upload_from_string(
        json.dumps(res, ensure_ascii=False), content_type="application/json")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=("hsi", "daily"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    res = part_hsi() if a.part == "hsi" else part_daily()
    text = json.dumps(res, ensure_ascii=False, indent=1, default=str)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
