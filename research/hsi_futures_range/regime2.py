"""接 regime.py（使用者 2026-10-10「三樣都做」）：
1. % 代替點數：止賺 = 入場價 0.1／0.15／0.2／0.3／0.5%；加倉間距 = 0.75 × ATR20 或入場價 1／1.5／2%。
2. 滾動測試：每年 Y（2021 至 2026）只用 Y−2、Y−1 兩年選參數，用在 Y；接駁成一條「真實可用」的成績。
   選法 a = 訓練兩年每年盈虧最高；選法 b = 每年盈虧 ÷ 最深浮虧最高（風險調整）。
3. 災難止蝕：平均成本逆向 2／3／5% 全部平倉（不設 = 原本）。
共同：升跌 ≥ 1%／2%、RSI 穿越／轉向 × 70/30、75/25、80/20、85/15、加倉 1→5 或不加倉。盈虧 = 點 × 張（每點 HK$50），按入場年份歸類；
參數組每個跑一次全期，再按年切開（換參數時舊倉照舊規則平倉，跟實際略有出入）。

用法：python3 research/hsi_futures_range/regime2.py --json /tmp/hsimain.json
     python3 research/hsi_futures_range/regime2.py --json /tmp/hsimain.json --select 2027   # 每年 1 月：用前兩年選選法 b 的參數，
                                                                                            # 印出 main.DIZAI_HENG_PICKS 的一行
"""
import argparse, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402
import rsi_basic as rb                                      # noqa: E402

YEARS = [str(y) for y in range(2018, 2031)]
PH = {"P1": ("2018", "2020"), "P2": ("2021", "2023"), "P3": ("2024", "2026")}
YRS = {"P1": 2.25, "P2": 3.0, "P3": 2.78}


def by_year(t):
    out = {y: {"pnl": 0.0, "n": 0, "loss": 0, "worst": 0.0, "sl": 0} for y in YEARS}
    for x in t:
        r = out[x["entry"][:4]]
        r["pnl"] += x["pnl"]; r["n"] += 1; r["loss"] += x["pnl"] < 0; r["worst"] = min(r["worst"], x["worst"]); r["sl"] += x["reason"] == "sl"
    return out


def phase(Y, p):
    lo, hi = PH[p]
    ys = [y for y in YEARS if lo <= y <= hi]
    return {"ann": sum(Y[y]["pnl"] for y in ys) / YRS[p], "loss": sum(Y[y]["loss"] for y in ys),
            "worst": -min(Y[y]["worst"] for y in ys), "sl": sum(Y[y]["sl"] for y in ys)}


def fmt(Y):
    return "  ".join(f"{p} {phase(Y, p)['ann']:+6.0f}（虧{phase(Y, p)['loss']}，深{phase(Y, p)['worst']:5.0f}）" for p in PH)


def grid_keys():
    """(說明, 參數 dict) 全部 1,280 組。"""
    out = []
    for (trig, (hi, lo), move), tpp, (sname, sp), al, dst in itertools.product(
            itertools.product(("cross", "confirm"), ((70, 30), (75, 25), (80, 20), (85, 15)), (0.01, 0.02)),
            (0.001, 0.0015, 0.002, 0.003, 0.005), (("ATR", None), ("1%", 0.01), ("2%", 0.02)), ((), (1, 1, 1, 1)), (None, 0.02, 0.03, 0.05)):
        if not al and sname != "ATR":
            continue
        key = (f"{rb.NAME[trig]}{hi}/{lo} ≥{move:.0%} 賺{tpp:.2%}" + (f" 加倉1→5 間距{sname}" if al else " 不加倉")
               + (f" 災難{dst:.0%}" if dst else " 無止蝕"))
        out.append((key, {"trig": trig, "hi": hi, "lo": lo, "move": move, "tp_pct": tpp, "add_lots": al,
                          "step_pct": sp if al else None, "dstop_pct": dst}))
    return out


def select(D, year):
    """選法 b：用 year−2、year−1 兩年，選「盈虧 ÷ 最深浮虧」最高的一組。"""
    tr = [str(int(year) - 2), str(int(year) - 1)]
    best = None
    for key, p in grid_keys():
        Y = by_year(rb.run_adds(D, rb.signals(D, p["hi"], p["lo"], p["trig"], p["move"]), None, p["add_lots"],
                                tp_pct=p["tp_pct"], step_pct=p["step_pct"], dstop_pct=p["dstop_pct"], entry_day=True))
        sc = sum(Y[y]["pnl"] for y in tr if y in Y) / max(1.0, -min(Y[y]["worst"] for y in tr if y in Y))
        if best is None or sc > best[0]:
            best = (sc, key, p)
    sc, key, p = best
    print(f"{year} 選中：{key}（訓練 {tr[0]}–{tr[1]}，分數 {sc:.2f}）")
    print(f'    "{year}": {{"trig": "{p["trig"]}", "hi": {p["hi"]}, "lo": {p["lo"]}, "move": {p["move"]}, "tp_pct": {p["tp_pct"]}, '
          f'"add_lots": {tuple(p["add_lots"])}, "step_pct": {p["step_pct"]}, "dstop_pct": {p["dstop_pct"]}, "train": "{tr[0]}–{tr[1]}"}},')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--select", metavar="YEAR", help="只做每年選參（選法 b），印出 DIZAI_HENG_PICKS 一行")
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    if a.select:
        return select(D, a.select)
    sigs = {}
    for trig, (hi, lo), move in itertools.product(("cross", "confirm"), ((70, 30), (75, 25), (80, 20), (85, 15)), (0.01, 0.02)):
        sigs[trig, hi, lo, move] = rb.signals(D, hi, lo, trig, move)
    res = {}
    for (trig, hi, lo, move), tpp, (sname, sp), al, dst in itertools.product(
            sigs, (0.001, 0.0015, 0.002, 0.003, 0.005), (("ATR", None), ("1%", 0.01), ("2%", 0.02)), ((), (1, 1, 1, 1)), (None, 0.02, 0.03, 0.05)):
        if not al and sname != "ATR":
            continue
        key = (f"{rb.NAME[trig]}{hi}/{lo} ≥{move:.0%} 賺{tpp:.2%}" + (f" 加倉1→5 間距{sname}" if al else " 不加倉")
               + (f" 災難{dst:.0%}" if dst else " 無止蝕"))
        res[key] = by_year(rb.run_adds(D, sigs[trig, hi, lo, move], None, al, tp_pct=tpp, step_pct=sp, dstop_pct=dst, entry_day=True))
    keys = list(res)
    print(f"共 {len(keys)} 組參數\n")

    print("######## 1. % 止賺：三個階段都賺錢、最差階段最好的 8 組（每年盈虧 點 × 張）########")
    ok = [k for k in keys if all(phase(res[k], p)["ann"] > 0 for p in PH)]
    print(f"三個階段都賺錢：{len(ok)}／{len(keys)}")
    for k in sorted(ok, key=lambda k: -min(phase(res[k], p)["ann"] for p in PH))[:8]:
        print(f"  {k:46s} {fmt(res[k])}")
    rank = {p: np.argsort(np.argsort([-phase(res[k], p)["ann"] for k in keys])) for p in PH}
    print("參數排名相關：" + "、".join(f"{p} 對 {q} {np.corrcoef(rank[p], rank[q])[0, 1]:+.2f}" for p, q in itertools.combinations(PH, 2)))

    print("\n######## 2. 滾動測試：用前兩年選參數、用在下一年 ########")
    for label, score in (("a 盈虧最高", lambda k, ys: sum(res[k][y]["pnl"] for y in ys)),
                         ("b 盈虧÷最深浮虧", lambda k, ys: sum(res[k][y]["pnl"] for y in ys) / max(1.0, -min(res[k][y]["worst"] for y in ys)))):
        print(f"\n選法 {label}")
        tot = 0.0
        for y in range(2021, 2027):
            tr = [str(y - 2), str(y - 1)]
            best = max(keys, key=lambda k: score(k, tr))
            r = res[best][str(y)]
            tot += r["pnl"]
            print(f"  {y}：選 {best:46s} 訓練兩年 {sum(res[best][t]['pnl'] for t in tr):+7.0f} → 當年 {r['pnl']:+7.0f}"
                  f"（{r['n']} 筆，虧 {r['loss']}，止蝕 {r['sl']}，最深 {-r['worst']:5.0f}）")
        print(f"  2021 至 2026 合計 {tot:+.0f}（每年 {tot / 5.78:+.0f}）")

    print("\n######## 3. 災難止蝕（同一組參數，只改止蝕）########")
    for base in ("轉向80/20 ≥2% 賺0.15% 加倉1→5 間距ATR", "轉向80/20 ≥1% 賺0.20% 加倉1→5 間距ATR",
                 "轉向75/25 ≥2% 賺0.20% 加倉1→5 間距ATR", "轉向70/30 ≥2% 賺0.50% 加倉1→5 間距ATR"):
        print(f"\n{base}")
        for d in ("無止蝕", "災難2%", "災難3%", "災難5%"):
            k = f"{base} {d}"
            print(f"  {d:6s} {fmt(res[k])}  止蝕 {sum(phase(res[k], p)['sl'] for p in PH)} 次")


if __name__ == "__main__":
    main()
