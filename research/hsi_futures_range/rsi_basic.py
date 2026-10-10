"""回歸基本步（使用者 2026-10-10）：1 分 K RSI(14) 不同超買／超賣組合，不設止蝕、賺 100 點平倉，數有多少筆虧損。

規則：
  RSI 升穿／跌回上限 → 沽；跌穿／升回下限 → 買（穿越 = 進入超買超賣區那根；轉向 = 離開那根）。
  訊號 K 線收市判斷，下一根 1 分 K 開市入場；不看當日升跌、不加倉、同一時間只持一張。
  止賺：入場價 ± 100 點（跳空越過用開市價）；不設止蝕、不限時間，一直持有到止賺為止（可跨日、跨月）。
  數據尾仍未止賺 → 用最後收市價計浮動盈虧（這些就是「虧損」或「未完成」的單）。
  每張每邊成本 1 點；每點 HK$50。主連數據轉月時有價差跳動，持倉跨轉月的盈虧會有偏差。

第二輪（使用者「1,2,3 都做」）：
  1. 加回當日升跌 ≥ 1%／2% 才做（沽單要當日升、買單要當日跌，即逆市）。
  2. 止賺 30／50／100／200 點。
  3. 持倉時間上限 1／5／20 個交易日（1 日 = 當個交易日收市平倉），到期用收市價平倉。

第三輪（使用者「加倉、時間上限、Nasdaq 都試，分年」）：基礎 = 升跌 ≥ 2% ＋ 轉向 80/20 ＋ 止賺 30、不設止蝕。
  加倉：價格每逆向 0.75 × ATR20（由上一次入場價起計）加 1 張，止賺改由平均成本起計；加倉那根 K 不止賺。
  時間上限：20 個交易日，到期收市價全部平倉。
  Nasdaq：同一段時間（恒指上一交易日最後一根 → 訊號那根收市）Nasdaq 同方向走就不做（dizai_cross 的 oppo）。
  盈虧按平倉日所屬年份分年（點 × 張數）；數據尾未平倉的計入 2026 浮動盈虧。

用法：python3 research/hsi_futures_range/rsi_basic.py --json /tmp/hsimain.json [--rounds | --round3]
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

TP = 100.0
COST = 1.0
LEVELS = ((70, 30), (75, 25), (80, 20), (85, 15), (90, 10))


def signals(D, hi, lo, trig, move=None):
    r, rp = D["rsi"], np.r_[np.nan, D["rsi"][:-1]]
    same = np.r_[False, D["sid"][1:] == D["sid"][:-1]]
    if trig == "cross":
        s_x, b_x = (rp <= hi) & (r > hi), (rp >= lo) & (r < lo)
    else:
        s_x, b_x = (rp >= hi) & (r < hi), (rp <= lo) & (r > lo)
    if move:
        chg = D["c"] / D["prev_close"] - 1
        s_x, b_x = s_x & (chg >= move), b_x & (chg <= -move)
    out = [(int(i), -1) for i in np.flatnonzero(s_x & same)] + [(int(i), 1) for i in np.flatnonzero(b_x & same)]
    return sorted(out)


def run(D, sigs, tp=TP, max_days=None):
    o, h, l, c, sid, tk, ends = D["o"], D["h"], D["l"], D["c"], D["sid"], D["tk"], D["ends"]
    n, trades, busy = len(o), [], -1
    for i, side in sigs:
        e = i + 1
        if e <= busy or e >= n:
            continue
        px = o[e]
        tgt = px + side * tp
        j = mg.first_hit(h, e, lambda s, t: h[s:t] >= tgt) if side > 0 else mg.first_hit(l, e, lambda s, t: l[s:t] <= tgt)
        dl = ends[min(sid[e] + max_days - 1, len(ends) - 1)] - 1 if max_days else n - 1
        if j > dl:                                           # 到期（或數據尾）仍未止賺 → 收市價平倉
            j, out, done = dl, c[dl], False
        else:
            out = o[j] if (j > e and side * (o[j] - tgt) > 0) else tgt
            done = True
        mae = (px - l[e:j + 1].min()) if side > 0 else (h[e:j + 1].max() - px)
        trades.append({"i": e, "side": side, "pnl": side * (out - px) - 2 * COST, "done": done, "mae": float(mae),
                       "days": int(sid[j] - sid[e]), "mins": j - e, "open": tk[e], "close": tk[j]})
        busy = j
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--rounds", action="store_true", help="第二輪：升跌條件、止賺點數、持倉時間上限")
    ap.add_argument("--round3", action="store_true", help="第三輪：加倉、時間上限、Nasdaq，分年")
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    if a.rounds:
        return rounds(D)
    if a.round3:
        return round3(D)
    print(f"數據：{D['tk'][0][:10]} 至 {D['tk'][-1][:10]}，{len(D['days'])} 個交易日")
    print("\n組合            筆數  止賺  虧損(未平)  最大浮虧   浮虧≥500 ≥1000 ≥2000  持倉>1日 最長(日)  總盈虧(點)  虧損單詳情")
    for trig in ("cross", "confirm"):
        for hi, lo in LEVELS:
            t = run(D, signals(D, hi, lo, trig))
            lose = [x for x in t if x["pnl"] < 0]
            m = np.array([x["mae"] for x in t])
            detail = "；".join(f"{'買' if x['side'] > 0 else '沽'} {x['open'][:16]} 浮{x['pnl']:+.0f}點" for x in lose) or "—"
            print(f"{'穿越' if trig == 'cross' else '轉向'} {hi}/{lo:<4d} {len(t):6d} {sum(x['done'] for x in t):5d} {len(lose):6d}"
                  f"      {m.max():7.0f}   {(m >= 500).sum():6d} {(m >= 1000).sum():5d} {(m >= 2000).sum():5d}"
                  f"   {sum(x['days'] >= 1 for x in t):6d} {max(x['days'] for x in t):6d}   {sum(x['pnl'] for x in t):+10.0f}  {detail}")


def run_adds(D, sigs, tp, add_lots=(), step_atr=0.75, max_days=None, entry_day=False):
    """加倉版：不設止蝕；止賺由平均成本起計；到期（或數據尾）收市價平倉。"""
    o, h, l, c, sid, ends, atr = D["o"], D["h"], D["l"], D["c"], D["sid"], D["ends"], D["atr"]
    n, trades, busy = len(o), [], -1
    for i, side in sigs:
        e = i + 1
        if e <= busy or e >= n or np.isnan(atr[i]):
            continue
        step = step_atr * atr[i]
        lots, avg, last, adds, k, tp_from = 1, o[e], o[e], 0, e, e
        dl = ends[min(sid[e] + max_days - 1, len(ends) - 1)] - 1 if max_days else n - 1
        worst = 0.0
        while True:
            add_lv = last - side * step if adds < len(add_lots) else None
            tgt = avg + side * tp
            if side > 0:
                j_add = mg.first_hit(l, k, lambda s, t: l[s:t] <= add_lv) if add_lv is not None else mg.BIG
                j_tp = mg.first_hit(h, tp_from, lambda s, t: h[s:t] >= tgt)
            else:
                j_add = mg.first_hit(h, k, lambda s, t: h[s:t] >= add_lv) if add_lv is not None else mg.BIG
                j_tp = mg.first_hit(l, tp_from, lambda s, t: l[s:t] <= tgt)
            j = min(j_add, j_tp)
            seg_end = min(j, dl)
            adverse = l[k:seg_end + 1].min() if side > 0 else h[k:seg_end + 1].max()
            worst = min(worst, lots * side * (adverse - avg))
            if j > dl:                                       # 到期／數據尾
                out, reason, j = c[dl], "time" if max_days and dl < n - 1 else "open", dl
                break
            if j_add <= j_tp:
                px = o[j] if (j > e and side * (o[j] - add_lv) < 0) else add_lv
                q = add_lots[adds]
                avg, lots, last, adds = (avg * lots + px * q) / (lots + q), lots + q, px, adds + 1
                k, tp_from = j, max(tp_from, j + 1)
                continue
            out, reason = (o[j] if (j > tp_from and side * (o[j] - tgt) > 0) else tgt), "tp"
            break
        trades.append({"pnl": lots * side * (out - avg) - 2 * COST * lots, "reason": reason, "lots": lots,
                       "worst": float(worst), "days": int(sid[j] - sid[e]), "year": D["days"][sid[j]][:4], "entry": D["days"][sid[e]]})
        busy = j
    return trades


def round3(D):
    import dizai_cross as dc
    nq = dc.load_us("usatechidxusd")
    sig = signals(D, 80, 20, "confirm", 0.02)
    ft = dc.features(D, sig, nq)
    sig_nq = [(i, s) for i, s in sig if dc.keep(ft, i, s, "oppo")]
    V = [("基礎（不加倉、不限時）", sig, (), None), ("加倉 1→2→3", sig, (1, 1), None), ("加倉 1→2→3→4→5", sig, (1, 1, 1, 1), None),
         ("最多 20 日", sig, (), 20), ("Nasdaq 篩選", sig_nq, (), None),
         ("加倉 1→5 ＋ 20 日", sig, (1, 1, 1, 1), 20), ("加倉 1→5 ＋ Nasdaq", sig_nq, (1, 1, 1, 1), None),
         ("20 日 ＋ Nasdaq", sig_nq, (), 20), ("加倉 1→5 ＋ 20 日 ＋ Nasdaq", sig_nq, (1, 1, 1, 1), 20)]
    years = [str(y) for y in range(2018, 2027)]
    res = [(lab, run_adds(D, sg, 30, al, max_days=md)) for lab, sg, al, md in V]
    print("升跌 ≥ 2% ＋ 轉向 80/20 ＋ 止賺 30（點 × 張數；每點 HK$50）")
    print("\n每年盈虧（點）" + " " * 20 + "".join(f"{y:>8s}" for y in years))
    for lab, t in res:
        print(f"  {lab:26s}" + "".join(f"{sum(x['pnl'] for x in t if x['year'] == y):+8.0f}" for y in years))
    print("\n每年 筆數／虧損" + " " * 19 + "".join(f"{y:>8s}" for y in years))
    for lab, t in res:
        print(f"  {lab:26s}" + "".join(f"{sum(1 for x in t if x['year'] == y):4d}/{sum(1 for x in t if x['year'] == y and x['pnl'] < 0):<3d}" for y in years))
    print("\n風險" + " " * 30 + "最大浮虧(點×張)  最大一筆虧損  最長(日)  最多張數  加滿次數  未平倉")
    for (lab, t), (_, _, al, _) in zip(res, V):
        mx = 1 + sum(al)
        print(f"  {lab:26s}      {-min(x['worst'] for x in t):8.0f}     {-min(min(x['pnl'] for x in t), 0):8.0f}   {max(x['days'] for x in t):6d}"
              f"   {max(x['lots'] for x in t):6d}   {sum(1 for x in t if x['lots'] == mx) if al else 0:6d}   {sum(1 for x in t if x['reason'] == 'open'):4d}")


def summary(t):
    p = np.array([x["pnl"] for x in t]) if t else np.zeros(1)
    m = np.array([x["mae"] for x in t]) if t else np.zeros(1)
    lose = p[p < 0]
    return (f"{len(t):5d} {int((p < 0).sum()):5d} {(p > 0).mean():6.1%} {(-lose.min() if len(lose) else 0):7.0f} {m.max():7.0f}"
            f" {max((x['days'] for x in t), default=0):6d} {p.sum():+9.0f} {p.mean():+7.1f}")


HEAD = "  筆數 虧損   勝率  最大虧損 最大浮虧 最長(日) 總盈虧(點) 每筆"
BEST = (("confirm", 80, 20), ("confirm", 75, 25), ("cross", 80, 20), ("cross", 70, 30))
NAME = {"cross": "穿越", "confirm": "轉向"}


def rounds(D):
    print("\n######## 1. 加回當日升跌條件（止賺 100、不設止蝕、不限時間）########")
    for move in (0.01, 0.02):
        print(f"\n當日升跌 ≥ {move:.0%}            {HEAD}")
        for trig in ("cross", "confirm"):
            for hi, lo in LEVELS:
                print(f"  {NAME[trig]} {hi}/{lo:<4d}        {summary(run(D, signals(D, hi, lo, trig, move)))}")
    print("\n######## 2. 止賺點數（不設止蝕、不限時間）########")
    for trig, hi, lo in BEST:
        print(f"\n{NAME[trig]} {hi}/{lo}               {HEAD}")
        for move in (None, 0.01, 0.02):
            for tp in (30, 50, 100, 200):
                print(f"  升跌{'不限' if not move else f'≥{move:.0%}':4s} 止賺{tp:4d}     {summary(run(D, signals(D, hi, lo, trig, move), tp))}")
    print("\n######## 3. 持倉時間上限（止賺 100、到期收市價平倉）########")
    for trig, hi, lo in BEST:
        print(f"\n{NAME[trig]} {hi}/{lo}               {HEAD}")
        for move in (None, 0.01, 0.02):
            for md in (1, 5, 20):
                print(f"  升跌{'不限' if not move else f'≥{move:.0%}':4s} 最多{md:3d}日    {summary(run(D, signals(D, hi, lo, trig, move), TP, md))}")


if __name__ == "__main__":
    main()
