"""地載陣「極高勝率＋正期望值」搜尋：止賺近、止蝕遠（R < 1）。訓練期挑、測試期驗證一次。

沿用 dizai_search.py 的引擎（不加倉、03:00 收市平倉、同一根 K 線止蝕止賺都觸及當止蝕、每邊成本 1 點）。
規則族（事先定好）：
  方向／觸發  逆市（RSI 穿越、轉向）、順勢（穿越）
  開閘        當日升跌 ≥ 0.5%／1%／1.5%／2%
  止蝕        k × ATR20，k = 0.15／0.25／0.4／0.6／1.0（1.0 ≈ 一整天的波幅，近乎只靠收市平倉）
  止賺        R × 止蝕距離，R = 0.1／0.2／0.33／0.5（止賺比止蝕近 → 勝率高）
  時段        全日／日市／夜市；每日最多 1 筆／不限
挑選（只看訓練期）：勝率 ≥ --min-win、筆數 ≥ --min-train、每筆期望值 > 0，按每筆期望值排。

用法：python3 research/hsi_futures_range/dizai_hiwin.py --json /tmp/hsimain.json [--min-win 0.75]
"""
import argparse, itertools, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_search as ds                                 # noqa: E402
import rsi_avg_down as rad                                # noqa: E402

KS = (0.15, 0.25, 0.4, 0.6, 1.0)
RS = (0.1, 0.2, 0.33, 0.5)


def grid():
    for direction in ("fade", "mom"):
        for trig in (("cross", "confirm") if direction == "fade" else ("cross",)):
            for move, k, r, win, mpd in itertools.product((0.005, 0.01, 0.015, 0.02), KS, RS,
                                                          ("all", "day", "night"), (1, 0)):
                yield {"dir": direction, "trig": trig, "move": move, "k": k, "tp": r, "win": win, "mpd": mpd}


def worst(trades):
    return min(x[2] for x in trades) if trades else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--min-win", type=float, default=0.75)
    ap.add_argument("--min-train", type=int, default=150)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    cache, rows = {}, []
    for g in grid():
        key = (g["dir"], g["trig"], g["move"], g["win"])
        if key not in cache:
            cache[key] = ds.signals(D, *key)
        tr = ds.simulate(D, cache[key], g["k"], g["tp"], g["mpd"])
        rows.append({"g": g, "tr": tr, "train": ds.stats(tr, days, hi=ds.TRAIN_END),
                     "test": ds.stats(tr, days, lo="2024-01-01"), "all": ds.stats(tr, days)})
    print(f"共 {len(rows)} 組；訓練期勝率 ≥ {a.min_win:.0%} 的有 "
          f"{sum(1 for r in rows if r['train'].get('n', 0) >= a.min_train and r['train']['win'] >= a.min_win)} 組，"
          f"其中期望值為正 {sum(1 for r in rows if r['train'].get('n', 0) >= a.min_train and r['train']['win'] >= a.min_win and r['train']['exp'] > 0)} 組")
    ok = [r for r in rows if r["train"].get("n", 0) >= a.min_train and r["train"]["win"] >= a.min_win and r["train"]["exp"] > 0]
    ok.sort(key=lambda r: r["train"]["exp"], reverse=True)
    for r in ok[:a.top]:
        tr, te, al = r["train"], r["test"], r["all"]
        print(f"{ds.label(r['g']).replace('止賺' + str(r['g']['tp']) + 'R', '止賺' + str(r['g']['tp']) + 'R(=' + format(r['g']['tp'] * r['g']['k'], '.3f') + 'ATR)')}\n"
              f"   訓練 n{tr['n']:4d} 勝{tr['win']:.0%} RRR{tr['rrr']:.2f} 每筆{tr['exp']:+.1f} 總{tr['total']:+.0f} 回撤{tr['mdd']:.0f}\n"
              f"   測試 n{te.get('n', 0):4d} 勝{te.get('win', 0):.0%} RRR{te.get('rrr', 0):.2f} 每筆{te.get('exp', 0):+.1f} "
              f"總{te.get('total', 0):+.0f} 回撤{te.get('mdd', 0):.0f}｜八年最差一筆{worst(r['tr']):.0f} {al['by_year']}")
    top = ok[:50]
    print(f"\n訓練期合格前 {len(top)} 組之中，測試期期望值為正：{sum(1 for r in top if r['test'].get('exp', 0) > 0)}；"
          f"測試期勝率仍 ≥ {a.min_win:.0%}：{sum(1 for r in top if r['test'].get('win', 0) >= a.min_win)}")


if __name__ == "__main__":
    main()
