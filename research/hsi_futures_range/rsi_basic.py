"""回歸基本步（使用者 2026-10-10）：1 分 K RSI(14) 不同超買／超賣組合，不設止蝕、賺 100 點平倉，數有多少筆虧損。

規則：
  RSI 升穿／跌回上限 → 沽；跌穿／升回下限 → 買（穿越 = 進入超買超賣區那根；轉向 = 離開那根）。
  訊號 K 線收市判斷，下一根 1 分 K 開市入場；不看當日升跌、不加倉、同一時間只持一張。
  止賺：入場價 ± 100 點（跳空越過用開市價）；不設止蝕、不限時間，一直持有到止賺為止（可跨日、跨月）。
  數據尾仍未止賺 → 用最後收市價計浮動盈虧（這些就是「虧損」或「未完成」的單）。
  每張每邊成本 1 點；每點 HK$50。主連數據轉月時有價差跳動，持倉跨轉月的盈虧會有偏差。

用法：python3 research/hsi_futures_range/rsi_basic.py --json /tmp/hsimain.json
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


def signals(D, hi, lo, trig):
    r, rp = D["rsi"], np.r_[np.nan, D["rsi"][:-1]]
    same = np.r_[False, D["sid"][1:] == D["sid"][:-1]]
    if trig == "cross":
        s_x, b_x = (rp <= hi) & (r > hi), (rp >= lo) & (r < lo)
    else:
        s_x, b_x = (rp >= hi) & (r < hi), (rp <= lo) & (r > lo)
    out = [(int(i), -1) for i in np.flatnonzero(s_x & same)] + [(int(i), 1) for i in np.flatnonzero(b_x & same)]
    return sorted(out)


def run(D, sigs):
    o, h, l, c, sid, tk = D["o"], D["h"], D["l"], D["c"], D["sid"], D["tk"]
    n, trades, busy = len(o), [], -1
    for i, side in sigs:
        e = i + 1
        if e <= busy or e >= n:
            continue
        px = o[e]
        tgt = px + side * TP
        j = mg.first_hit(h, e, lambda s, t: h[s:t] >= tgt) if side > 0 else mg.first_hit(l, e, lambda s, t: l[s:t] <= tgt)
        if j >= n:                                           # 數據尾仍未止賺
            j, out, done = n - 1, c[-1], False
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
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
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


if __name__ == "__main__":
    main()
