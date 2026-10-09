"""地載陣加倍攤平版：刻意用全部八年數據 curve fitting，找「八年零止蝕、利潤最高」的參數，並列出每組的安全邊際。

這是**過度擬合**：用全部數據挑參數，八年表現不代表將來。用途：
  1. 知道這個方法在歷史上最好可以做到怎樣（上限）；
  2. 當作前向測試的對照：實際跟這組回測差多遠 = 過度擬合的代價；
  3. 看最佳組合的共通點，以及每個參數移一格會怎樣（脆弱程度）。

搜尋範圍（加倍攤平、留倉、逆市、每日最多開 1 組；引擎 dizai_martingale.simulate_mg）：
  觸發 RSI 穿越／轉向 × 門檻 1.5／1.75／2／2.25／2.5／3% × 全日／夜市
  × 加倉間距 0.5／0.75／1／1.25／1.5 × ATR20 或 300／500／700／1000／1500 點
  × 加倉張數 1→2→4／1→2→3／1→2 × 止賺 20／30／40／60／80／100／150 點 × 止蝕（平均成本逆向）1000／1500／2000／3000 點
安全邊際 = 止蝕點數 − 所有沒止蝕的單之中最大逆向幅度（離最終平均成本最遠的點數）；越大越不靠運氣。

用法：python3 research/hsi_futures_range/dizai_curvefit.py --json /tmp/hsimain.json --out /tmp/curvefit.json [--procs 4]
"""
import argparse, itertools, json, sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

D = None
SIGS = {}
TRIGS = ("cross", "confirm")
MOVES = (0.015, 0.0175, 0.02, 0.0225, 0.025, 0.03)
WINS = ("all", "night")
SPACINGS = tuple(("atr", g) for g in (0.5, 0.75, 1.0, 1.25, 1.5)) + tuple(("pts", p) for p in (300, 500, 700, 1000, 1500))
LOTS = ((1, 2), (1, 1), (1,))
TPS = (20, 30, 40, 60, 80, 100, 150)
SLS = (1000, 1500, 2000, 3000)


def run_one(key):
    trig, move, win, spacing, lots, tp, sl = key
    sig = SIGS[(trig, move, win)]
    kw = {"step_pts": spacing[1]} if spacing[0] == "pts" else {}
    t = mg.simulate_mg(D, sig, spacing[1] if spacing[0] == "atr" else None, tp, sl_pts=sl, add_lots=lots, **kw)
    days = D["days"]
    s, a, b = mg.summary(t, days), mg.summary(t, days, hi=ds.TRAIN_END), mg.summary(t, days, lo="2024-01-01")
    if not s.get("n"):
        return None
    ok = [x for x in t if x["reason"] != "sl"]
    return {"key": [trig, move, win, list(spacing), list(lots), tp, sl], "n": s["n"], "win": s["win"], "exp": s["exp"],
            "total": s["total"], "mdd": s["mdd"], "worst": s["worst"], "n_sl": s["reasons"].get("sl", 0),
            "margin": sl - max((x["mae"] for x in ok), default=0.0), "max_lots": s["max_lots"], "max_days": s["max_days"],
            "years_up": s["years_up"], "years": s["years"], "by_year": s["by_year"],
            "train_exp": a.get("exp"), "test_exp": b.get("exp"), "max_loss_if_sl": -sl * (1 + sum(lots))}


def init(path):
    global D, SIGS
    D = ds.prepare(rad.clean(json.loads(Path(path).read_text())))
    SIGS = {(t, m, w): ds.signals(D, "fade", t, m, w) for t in TRIGS for m in MOVES for w in WINS}


def label(k):
    trig, move, win, sp, lots, tp, sl = k
    spz = f"{sp[1]}×ATR" if sp[0] == "atr" else f"{sp[1]:.0f}點"
    return (f"{'穿越' if trig == 'cross' else '轉向'}/門檻{move:.2%}/{'全日' if win == 'all' else '夜市'}/間距{spz}/"
            f"張數{'→'.join(str(sum((1,) + tuple(lots[:i]))) for i in range(len(lots) + 1))}/止賺{tp}/止蝕{sl}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    keys = list(itertools.product(TRIGS, MOVES, WINS, SPACINGS, LOTS, TPS, SLS))
    print(f"共 {len(keys)} 組", flush=True)
    with Pool(a.procs, initializer=init, initargs=(a.json,)) as pool:
        rows = [r for r in pool.imap_unordered(run_one, keys, chunksize=40) if r]
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False))
    zero = sorted((r for r in rows if r["n_sl"] == 0 and r["n"] >= 100), key=lambda r: r["total"], reverse=True)
    print(f"八年零止蝕（≥ 100 筆）：{len(zero)} 組")
    print("\n=== 零止蝕、總利潤最高 15 組 ===")
    for r in zero[:15]:
        print(f"{label(r['key'])}\n   n{r['n']} 勝{r['win']:.1%} 每筆{r['exp']:+.1f} 總{r['total']:+.0f} 安全邊際{r['margin']:.0f}點 "
              f"最壞情況{r['max_loss_if_sl']}點 最多{r['max_lots']}張 最長持倉{r['max_days']}日 {r['by_year']}")
    safe = sorted((r for r in zero if r["margin"] >= 0.5 * r["key"][6]), key=lambda r: r["total"], reverse=True)
    print(f"\n=== 零止蝕、而且安全邊際 ≥ 止蝕一半（最接近時離止蝕仍 ≥ 50%）：{len(safe)} 組，總利潤最高 15 組 ===")
    for r in safe[:15]:
        print(f"{label(r['key'])}\n   n{r['n']} 勝{r['win']:.1%} 每筆{r['exp']:+.1f} 總{r['total']:+.0f} 安全邊際{r['margin']:.0f}點 "
              f"最壞情況{r['max_loss_if_sl']}點 最多{r['max_lots']}張 最長持倉{r['max_days']}日 {r['by_year']}")


if __name__ == "__main__":
    main()
