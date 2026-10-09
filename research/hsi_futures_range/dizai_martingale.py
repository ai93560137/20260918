"""地載陣「留倉、加倍攤平 2 次、回平均價＋近止賺全平、平均成本 1000 點止蝕」：八年主連 1 分 K，訓練期挑、測試期驗證。

規則（使用者 2026-10-09 定）：
  入場  逆市訊號（dizai_search.signals：RSI 穿越／轉向、當日升跌門檻、時段），下一根開市 1 張；同一時間只持一組；每日最多開 1 組。
  加倉  比最近一次入場／加倉價再逆向 g × ATR20（入場時的平均全日波幅），或入場價的固定百分比（step_pct）→ 第一次加 1 張（共 2 張）、第二次加 2 張（共 4 張），最多 2 次。
  止賺  價格到「平均成本 ± tp 點」（有利方向）→ 全部平倉。沒加過倉時就是入場價 ± tp。
  止蝕  價格到「平均成本 ∓ 1000 點」（不利方向）→ 全部平倉。
  留倉  不在 03:00 平倉；一直持有到止賺或止蝕（數據結束仍未平的，按最後收市價計浮動盈虧）。
成交：同一根 K 線先處理不利方向（加倉、止蝕），止賺最早下一根才算（保守）；跳空越過掛單價以開市價成交。
      每張每邊成本 1 點。恒指每點 HK$50。主連轉月會跳價，留倉的單會受影響。

用法：python3 research/hsi_futures_range/dizai_martingale.py --json /tmp/hsimain.json
"""
import argparse, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_search as ds                                 # noqa: E402
import rsi_avg_down as rad                                # noqa: E402

ADD_LOTS = (1, 2)                                         # 第一次加 1 張、第二次加 2 張 → 1→2→4
BIG = 10 ** 12


def first_hit(arr, start, cond_fn, chunk=4096):
    """arr[start:] 之中第一個 cond_fn 為真的位置（絕對索引）；沒有 → BIG。分段搜尋，免得每次掃到數據尾。"""
    n = len(arr)
    s = start
    while s < n:
        e = min(n, s + chunk)
        idx = np.flatnonzero(cond_fn(s, e))
        if len(idx):
            return s + int(idx[0])
        s, chunk = e, chunk * 4
    return BIG


def simulate_mg(D, sigs, g_atr, tp_pts, sl_pts=1000.0, cost=1.0, step_pct=None, step_pts=None, add_lots=ADD_LOTS):
    """加倉間距：step_pts（固定點數）＞ step_pct（入場價百分比，例 0.01 = 1%）＞ g_atr × ATR20。"""
    o, h, l, c, sid = D["o"], D["h"], D["l"], D["c"], D["sid"]
    n = len(o)
    trades, busy_until, opened_day = [], -1, set()
    for i, side in sigs:
        e = i + 1
        if e <= busy_until or e >= n or sid[e] != sid[i] or sid[i] in opened_day:
            continue
        opened_day.add(sid[i])
        step = step_pts if step_pts else (step_pct * o[e] if step_pct else g_atr * D["atr"][i])
        lots, avg, last = 1, o[e], o[e]
        fills = [(int(e), "open", float(o[e]), 1)]
        realized_cost = cost
        adds_done = 0
        k = e                                                # 從這根開始找不利事件
        tp_from = e                                          # 止賺最早從這根開始
        worst = 0.0
        while True:
            add_lv = last - side * step if adds_done < len(add_lots) else None
            sl_lv = avg - side * sl_pts
            tp_lv = avg + side * tp_pts
            if side > 0:
                j_sl = first_hit(l, k, lambda s, t: l[s:t] <= sl_lv)
                j_add = first_hit(l, k, lambda s, t: l[s:t] <= add_lv) if add_lv is not None else BIG
                j_tp = first_hit(h, tp_from, lambda s, t: h[s:t] >= tp_lv)
            else:
                j_sl = first_hit(h, k, lambda s, t: h[s:t] >= sl_lv)
                j_add = first_hit(h, k, lambda s, t: h[s:t] >= add_lv) if add_lv is not None else BIG
                j_tp = first_hit(l, tp_from, lambda s, t: l[s:t] <= tp_lv)
            j_adv = min(j_sl, j_add)
            if j_adv == BIG and j_tp == BIG:                 # 數據結束仍持倉
                x = c[-1]
                pnl = lots * side * (x - avg) - realized_cost - lots * cost
                mae = float((h[e:].max() - avg) if side < 0 else (avg - l[e:].min()))
                trades.append({"sid": int(sid[i]), "side": side, "pnl": float(pnl), "reason": "open", "lots": lots, "mae": mae,
                               "adds": adds_done, "days": int(sid[-1] - sid[i]), "fills": fills})
                busy_until = n
                break
            if j_adv <= j_tp:
                j = j_adv
                if j_add <= j_sl:                            # 加倉（比止蝕近，先到）
                    px = o[j] if (j > e and side * (o[j] - add_lv) < 0) else add_lv
                    q = add_lots[adds_done]
                    avg = (avg * lots + px * q) / (lots + q)
                    lots += q
                    last = px
                    adds_done += 1
                    realized_cost += q * cost
                    fills.append((int(j), "add", float(px), lots))
                    k, tp_from = j, max(tp_from, j + 1)
                    continue
                px = o[j] if (j > e and side * (o[j] - sl_lv) < 0) else sl_lv
                reason = "sl"
            else:
                j = j_tp
                px = o[j] if (j > e and side * (o[j] - tp_lv) > 0) else tp_lv
                reason = "tp"
            pnl = lots * side * (px - avg) - realized_cost - lots * cost
            fills.append((int(j), reason, float(px), 0))
            mae = float((h[e:j + 1].max() - avg) if side < 0 else (avg - l[e:j + 1].min()))
            trades.append({"sid": int(sid[i]), "side": side, "pnl": float(pnl), "reason": reason, "lots": lots, "mae": mae,
                           "adds": adds_done, "days": int(sid[j] - sid[i]), "fills": fills})
            busy_until = j
            break
    return trades


def summary(trades, days, lo=None, hi=None):
    t = [x for x in trades if (lo is None or days[x["sid"]] >= lo) and (hi is None or days[x["sid"]] <= hi)]
    if not t:
        return {"n": 0}
    p = np.array([x["pnl"] for x in t])
    eq = np.cumsum(p)
    mdd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
    years = {}
    for x in t:
        years[days[x["sid"]][:4]] = years.get(days[x["sid"]][:4], 0) + x["pnl"]
    reasons = {}
    for x in t:
        reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    return {"n": len(t), "win": float((p > 0).mean()), "exp": float(p.mean()), "total": float(p.sum()), "mdd": mdd,
            "worst": float(p.min()), "reasons": reasons, "max_lots": max(x["lots"] for x in t),
            "adds2": sum(1 for x in t if x["adds"] == 2), "max_days": max(x["days"] for x in t),
            "years_up": sum(1 for v in years.values() if v > 0), "years": len(years),
            "by_year": {k: round(v) for k, v in sorted(years.items())}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--sl", type=float, default=1000)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    rows = []
    for trig, move, win in itertools.product(("cross", "confirm"), (0.01, 0.015, 0.02), ("all", "night")):
        sig = ds.signals(D, "fade", trig, move, win)
        for g, tp in itertools.product((0.5, 0.75, 1.0), (10, 20, 30, 40, 60, 100)):
            t = simulate_mg(D, sig, g, tp, a.sl)
            rows.append({"key": (trig, move, win, g, tp), "train": summary(t, days, hi=ds.TRAIN_END),
                         "test": summary(t, days, lo="2024-01-01"), "all": summary(t, days)})
    rows.sort(key=lambda r: r["train"].get("exp", -1e9), reverse=True)
    print(f"止蝕：平均成本逆向 {a.sl:.0f} 點；加倉 1→2→4 張；留倉；共 {len(rows)} 組。按訓練期每筆期望值排序：\n")
    for r in rows:
        trig, move, win, g, tp = r["key"]
        tr, te, al = r["train"], r["test"], r["all"]
        print(f"{'穿越' if trig == 'cross' else '轉向'}/門檻{move:.1%}/{'全日' if win == 'all' else '夜市'}/加倉間距{g}ATR/止賺{tp}點："
              f"勝{al['win']:.0%}（訓{tr['win']:.0%}／測{te.get('win', 0):.0%}） 每筆{al['exp']:+.1f}（訓{tr['exp']:+.1f}／測{te.get('exp', 0):+.1f}）"
              f" 總{al['total']:+.0f} 回撤{al['mdd']:.0f} 最差{al['worst']:.0f} n{al['n']} 加滿{al['adds2']} 出場{al['reasons']}"
              f" 賺錢年{al['years_up']}/{al['years']} 最長持倉{al['max_days']}日")


if __name__ == "__main__":
    main()
