"""地載陣改良：八年主連 1 分 K 上，訓練期挑規則、測試期驗證一次。

數據：GCS archive/futu_k_1m/HK.HSIMAIN（本地腳本 v13 --export-raw），2018-10 至 2026-10。
訓練期：2018-10-04 至 2023-12-31；測試期：2024-01-01 起。只用訓練期挑，測試期只看一次。

規則族（事先定好，不邊看邊加）：
  方向  fade = 逆市（升 ≥ m 才沽、跌 ≥ m 才買）；mom = 順勢（升 ≥ m 才買、跌 ≥ m 才沽）
  觸發  cross   = RSI(14) 穿越 80／20 那根收市（原規則）
        confirm = RSI 由 80 以上跌回 80 以下（沽）／由 20 以下升回 20 以上（買），即超買超賣後先轉向（只用於 fade）
  開閘  m = 現價對上日收市 0.5%／1%／1.5%／2%
  止蝕  固定 k × ATR20（之前 20 個交易日的平均全日波幅，事前已知），k = 0.10／0.15／0.25
  止賺  R × 止蝕距離（R = 1／1.5／2／3），或 ext = 入場時的當日極值（只用於 fade，原規則）
  時段  all = 全日；day = 日市 09:15–16:30；night = 夜市
  每日  最多 1 筆／不限（同一時間只持一筆）
  一律不加倉（八年數據顯示加倉令虧損放大）；交易日最後一根收市平倉。
成交：訊號 K 線收市確認，下一根開市入場；同一根 K 線內止蝕、止賺都觸及 → 當止蝕（保守）；
  跳空越過止蝕／止賺 → 以開市價成交。成本每邊 1 點（每筆 2 點）。恒指每點 HK$50。

用法：python3 research/hsi_futures_range/dizai_search.py --json /tmp/hsimain.json [--top 15]
"""
import argparse, itertools, json, sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rsi_avg_down as rad                                # noqa: E402

TRAIN_END = "2023-12-31"
COST = 1.0


# ---- 數據 → numpy -------------------------------------------------------------
def prepare(bars):
    n = len(bars)
    o = np.array([b["open"] for b in bars]); h = np.array([b["high"] for b in bars])
    l = np.array([b["low"] for b in bars]); c = np.array([b["close"] for b in bars])
    tk = [b["time_key"] for b in bars]
    sess = [rad.session_of(t) for t in tk]
    days = sorted(set(sess))
    sid = np.array([days.index(s) for s in sess]) if n < 1000 else np.searchsorted(np.array(days), np.array(sess))
    hhmm = np.array([int(t[11:13]) * 60 + int(t[14:16]) for t in tk])
    starts = np.r_[0, np.flatnonzero(np.diff(sid)) + 1]
    ends = np.r_[starts[1:], n]                           # 不含
    # 每個交易日：上日收市、ATR20（之前 20 日平均全日波幅）
    dh = np.array([h[s:e].max() for s, e in zip(starts, ends)])
    dl = np.array([l[s:e].min() for s, e in zip(starts, ends)])
    dc = c[ends - 1]
    prev_close = np.r_[np.nan, dc[:-1]]
    rng = dh - dl
    atr = np.full(len(days), np.nan)
    for k in range(20, len(days)):
        atr[k] = rng[k - 20:k].mean()
    # 日內累積高低（含當根）
    run_hi, run_lo = np.empty(n), np.empty(n)
    for s, e in zip(starts, ends):
        run_hi[s:e] = np.maximum.accumulate(h[s:e]); run_lo[s:e] = np.minimum.accumulate(l[s:e])
    rsi = np.array([np.nan if x is None else x for x in rad.rsi_series(list(c), 14)])
    day_session = (hhmm >= 9 * 60 + 15) & (hhmm <= 16 * 60 + 30)
    return {"o": o, "h": h, "l": l, "c": c, "sid": sid, "days": days, "starts": starts, "ends": ends,
            "prev_close": prev_close[sid], "atr": atr[sid], "run_hi": run_hi, "run_lo": run_lo, "rsi": rsi,
            "day_session": day_session, "tk": tk}


def signals(D, direction, trigger, move, window):
    """回傳 [(訊號 K 線 i, side)]，side +1 買 −1 沽。"""
    r, rp = D["rsi"], np.r_[np.nan, D["rsi"][:-1]]
    chg = D["c"] / D["prev_close"] - 1
    same = np.r_[False, D["sid"][1:] == D["sid"][:-1]]            # 上一根同一交易日（RSI 穿越不跨日）
    up, dn = chg >= move, chg <= -move
    if trigger == "cross":
        hi_x, lo_x = (rp <= 80) & (r > 80), (rp >= 20) & (r < 20)
    else:                                                          # confirm：超買後跌回／超賣後升回
        hi_x, lo_x = (rp >= 80) & (r < 80), (rp <= 20) & (r > 20)
    if direction == "fade":
        short, long_ = hi_x & up, lo_x & dn
    else:
        long_, short = hi_x & up, lo_x & dn
    ok = same & ~np.isnan(D["atr"])
    if window == "day":
        ok &= D["day_session"]
    elif window == "night":
        ok &= ~D["day_session"]
    s = np.flatnonzero(short & ok); g = np.flatnonzero(long_ & ok)
    out = [(int(i), -1) for i in s] + [(int(i), 1) for i in g]
    return sorted(out)


def simulate(D, sigs, k_atr, tp, max_per_day):
    o, h, l, c, sid, ends = D["o"], D["h"], D["l"], D["c"], D["sid"], D["ends"]
    trades, busy_until, per_day = [], -1, {}
    for i, side in sigs:
        e = i + 1
        if e <= busy_until or e >= len(o) or sid[e] != sid[i]:
            continue
        d = sid[i]
        if max_per_day and per_day.get(d, 0) >= max_per_day:
            continue
        entry = o[e]
        dist = k_atr * D["atr"][i]
        sl = entry - side * dist
        if tp == "ext":
            tpx = D["run_lo"][i] if side < 0 else D["run_hi"][i]
            if side * (tpx - entry) <= 0:
                continue
        else:
            tpx = entry + side * tp * dist
        end = ends[d]
        hh, ll = h[e:end], l[e:end]
        if side > 0:
            hit_sl, hit_tp = ll <= sl, hh >= tpx
        else:
            hit_sl, hit_tp = hh >= sl, ll <= tpx
        js = np.flatnonzero(hit_sl); jt = np.flatnonzero(hit_tp)
        j_sl = js[0] if len(js) else 10 ** 9
        j_tp = jt[0] if len(jt) else 10 ** 9
        if j_sl == 10 ** 9 and j_tp == 10 ** 9:
            x, reason, j = c[end - 1], "close", end - 1 - e
        elif j_sl <= j_tp:                                          # 同一根都觸及 → 當止蝕
            bo = o[e + j_sl]
            x = (min(bo, sl) if side > 0 else max(bo, sl)) if j_sl > 0 else sl
            reason, j = "sl", j_sl
        else:
            bo = o[e + j_tp]
            x = (max(bo, tpx) if side > 0 else min(bo, tpx)) if j_tp > 0 else tpx
            reason, j = "tp", j_tp
        pnl = side * (x - entry) - 2 * COST
        trades.append((int(sid[i]), side, float(pnl), reason, float(dist)))
        busy_until = e + j
        per_day[d] = per_day.get(d, 0) + 1
    return trades


def stats(trades, days, lo=None, hi=None):
    t = [x for x in trades if (lo is None or days[x[0]] >= lo) and (hi is None or days[x[0]] <= hi)]
    if not t:
        return {"n": 0}
    p = np.array([x[2] for x in t])
    wins, losses = p[p > 0], p[p <= 0]
    eq = np.cumsum(p)
    mdd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
    years = {}
    for x in t:
        y = days[x[0]][:4]
        years[y] = years.get(y, 0) + x[2]
    return {"n": len(t), "win": len(wins) / len(t), "total": float(p.sum()), "exp": float(p.mean()),
            "rrr": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) and losses.mean() < 0 else float("inf"),
            "pf": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf"),
            "mdd": mdd, "years_up": sum(1 for v in years.values() if v > 0), "years": len(years),
            "by_year": {k: round(v) for k, v in sorted(years.items())}}


def grid():
    for direction in ("fade", "mom"):
        triggers = ("cross", "confirm") if direction == "fade" else ("cross",)
        tps = (1, 1.5, 2, 3, "ext") if direction == "fade" else (1, 1.5, 2, 3)
        for trig, move, k, tp, win, mpd in itertools.product(triggers, (0.005, 0.01, 0.015, 0.02), (0.10, 0.15, 0.25),
                                                             tps, ("all", "day", "night"), (1, 0)):
            yield {"dir": direction, "trig": trig, "move": move, "k": k, "tp": tp, "win": win, "mpd": mpd}


def label(g):
    return (f"{'逆市' if g['dir'] == 'fade' else '順勢'}/{'穿越' if g['trig'] == 'cross' else '轉向'}/"
            f"門檻{g['move']:.1%}/止蝕{g['k']:.2f}ATR/止賺{g['tp'] if g['tp'] == 'ext' else str(g['tp']) + 'R'}/"
            f"{ {'all': '全日', 'day': '日市', 'night': '夜市'}[g['win']]}/{'每日1筆' if g['mpd'] else '不限'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-train", type=int, default=150)
    ap.add_argument("--out")
    a = ap.parse_args()
    bars = rad.clean(json.loads(Path(a.json).read_text()))
    D = prepare(bars)
    days = D["days"]
    print(f"1 分 K {len(bars)} 根，{len(days)} 個交易日（{days[0]} 至 {days[-1]}）；訓練至 {TRAIN_END}")
    sig_cache, rows = {}, []
    for g in grid():
        key = (g["dir"], g["trig"], g["move"], g["win"])
        if key not in sig_cache:
            sig_cache[key] = signals(D, *key)
        tr = simulate(D, sig_cache[key], g["k"], g["tp"], g["mpd"])
        rows.append({"g": g, "train": stats(tr, days, hi=TRAIN_END), "test": stats(tr, days, lo="2024-01-01"),
                     "all": stats(tr, days)})
    print(f"共 {len(rows)} 組規則")
    ok = [r for r in rows if r["train"]["n"] >= a.min_train]
    ok.sort(key=lambda r: (r["train"]["pf"], r["train"]["exp"]), reverse=True)

    def show(r):
        tr, te = r["train"], r["test"]
        return (f"{label(r['g'])}\n   訓練 n{tr['n']:4d} 勝{tr['win']:.0%} RRR{tr['rrr']:.2f} PF{tr['pf']:.2f} 每筆{tr['exp']:+.1f} "
                f"總{tr['total']:+.0f} 回撤{tr['mdd']:.0f} 賺錢年{tr['years_up']}/{tr['years']}"
                f"\n   測試 n{te.get('n', 0):4d} 勝{te.get('win', 0):.0%} RRR{te.get('rrr', 0):.2f} PF{te.get('pf', 0):.2f} "
                f"每筆{te.get('exp', 0):+.1f} 總{te.get('total', 0):+.0f} 回撤{te.get('mdd', 0):.0f} {te.get('by_year', {})}")
    print(f"\n=== 訓練期 PF 前 {a.top} 名（訓練 ≥ {a.min_train} 筆）→ 測試期 ===")
    for r in ok[:a.top]:
        print(show(r))
    pos_test = sum(1 for r in ok[:50] if r["test"].get("total", 0) > 0)
    print(f"\n訓練前 50 名之中，測試期賺錢的有 {pos_test} 組")
    print(f"全部 {len(ok)} 組：訓練賺錢 {sum(1 for r in ok if r['train']['total'] > 0)}，"
          f"測試賺錢 {sum(1 for r in ok if r['test'].get('total', 0) > 0)}，兩段都賺 "
          f"{sum(1 for r in ok if r['train']['total'] > 0 and r['test'].get('total', 0) > 0)}")
    if a.out:
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
