"""開市突破（使用者 2026-10-10：「開市時大期一張向上、細期五張向下，之後斬一邊」= 開市後突破某價位就順勢入場）＋ RSI。

規則（恒指主連 1 分 K，只用日市 09:15–16:30）：
  基準價 = 當日日市第一根 1 分 K 開市價。升到基準 × (1 + X) → 買；跌到基準 × (1 − X) → 沽（以掛單價成交，跳空越過用開市價）。
  每日最多一筆（先觸發那邊）；同一根 K 兩邊都觸發 → 當日不做（分不清先後）。
  止蝕：對面（基準 ∓ X，距離 2X）或 回到基準（距離 X）。
  出場：日市收市（16:30 前最後一根收市價）平倉，或 止賺 = 1R／2R（R = 止蝕距離），未到則收市平倉。
  RSI(14)（1 分 K，用入場那根之前一根的收市值，不偷看）：
    無      不篩
    順勢確認 買要 RSI ≥ 60、沽要 RSI ≤ 40
    不追極端 買要 RSI < 70、沽要 RSI > 30
  方向：順勢（突破跟進，= 斬輸留贏）／逆勢（突破反做，對照）。逆勢的止蝕、止賺距離跟順勢一樣。
  入場那根：先查止蝕（不利先行），不算止賺；之後每根同一根止蝕止賺都到 → 當止蝕。每張每邊成本 1 點，每點 HK$50（大期）。
Sharpe = 每個交易日盈虧 × √252。階段：P1 2018-10–2020-12、P2 2021–2023、P3 2024 起。

用法：python3 research/hsi_futures_range/open_breakout.py --json /tmp/hsimain.json
"""
import argparse, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

COST = 1.0
HKD = 50
PH = {"P1": ("0000", "2020-12-31"), "P2": ("2021-01-01", "2023-12-31"), "P3": ("2024-01-01", "9999")}
YEARS = [str(y) for y in range(2018, 2027)]
RSI_RULES = {"無": None, "順勢確認": ("trend", 60, 40), "不追極端": ("noext", 70, 30)}


def day_slices(D):
    """每個交易日的日市（09:15–16:30）索引範圍。"""
    ds_mask, sid = D["day_session"], D["sid"]
    out = []
    for k, (s, e) in enumerate(zip(D["starts"], D["ends"])):
        idx = np.flatnonzero(ds_mask[s:e]) + s
        if len(idx) > 30:
            out.append((k, idx[0], idx[-1] + 1))
    return out


def simulate(D, days, x, stop, exit_, rsi_rule, direction):
    o, h, l, c, rsi = D["o"], D["h"], D["l"], D["c"], D["rsi"]
    res = []                                                 # (交易日索引, 盈虧點, 原因, side)
    for k, s, e in days:
        ref = o[s]
        up, dn = ref * (1 + x), ref * (1 - x)
        hu = np.flatnonzero(h[s:e] >= up)
        ld = np.flatnonzero(l[s:e] <= dn)
        ju = s + hu[0] if len(hu) else None
        jd = s + ld[0] if len(ld) else None
        if ju is None and jd is None:
            continue
        if ju is not None and jd is not None and ju == jd:
            continue
        brk = 1 if (jd is None or (ju is not None and ju < jd)) else -1
        j = ju if brk > 0 else jd
        lv = up if brk > 0 else dn
        px = o[j] if (j > s and brk * (o[j] - lv) > 0) else lv
        if j == s:
            px = o[j] if brk * (o[j] - lv) > 0 else lv
        if rsi_rule:
            r = rsi[j - 1] if j - 1 >= 0 else np.nan
            if np.isnan(r):
                continue
            kind, hi, lo = rsi_rule
            if kind == "trend" and not ((brk > 0 and r >= hi) or (brk < 0 and r <= lo)):
                continue
            if kind == "noext" and not ((brk > 0 and r < hi) or (brk < 0 and r > lo)):
                continue
        side = brk * direction
        dist = (2 * x if stop == "對面" else x) * ref
        sl = px - side * dist
        tp = px + side * exit_ * dist if exit_ else None
        out, why = None, "close"
        for b in range(j, e):
            adverse = l[b] <= sl if side > 0 else h[b] >= sl
            if adverse:
                out = (o[b] if (b > j and side * (o[b] - sl) < 0) else sl); why = "sl"; break
            if tp is not None and b > j and ((h[b] >= tp) if side > 0 else (l[b] <= tp)):
                out = (o[b] if side * (o[b] - tp) > 0 else tp); why = "tp"; break
        if out is None:
            out = c[e - 1]
        res.append((k, side * (out - px) - 2 * COST, why, side))
    return res


def stats(res, D, lo="0000", hi="9999"):
    days = D["days"]
    sel = [r for r in res if lo <= days[r[0]] <= hi]
    nday = sum(1 for d in days if lo <= d <= hi)
    if not sel or nday < 30:
        return None
    p = np.array([r[1] for r in sel])
    daily = np.zeros(nday)
    first = next(i for i, d in enumerate(days) if d >= lo)
    for r in sel:
        daily[r[0] - first] += r[1]
    eq = np.cumsum(daily)
    w, L = p[p > 0], p[p <= 0]
    return {"n": len(p), "win": (p > 0).mean(), "aw": w.mean() if len(w) else 0, "al": -L.mean() if len(L) else 0,
            "pnl": p.sum(), "ann": p.sum() / (nday / 245), "sharpe": daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0,
            "mdd": float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())}


def line(lab, st):
    if not st:
        return f"  {lab:40s} —"
    rrr = st["aw"] / st["al"] if st["al"] else float("nan")
    return (f"  {lab:40s} 筆{st['n']:4d} 勝{st['win']:5.1%} 贏{st['aw']:5.0f} 輸{st['al']:5.0f} RRR {rrr:4.2f}"
            f"｜每年 {st['ann']:+6.0f} 點 Sharpe {st['sharpe']:5.2f} 回撤 {st['mdd']:7.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = day_slices(D)
    print(f"交易日 {len(days)}（有日市）\n")
    grid = list(itertools.product((0.0025, 0.005, 0.0075, 0.01), ("對面", "基準"), (None, 1, 2), RSI_RULES, (1, -1)))
    R = {}
    for x, stop, ex, rk, dr in grid:
        R[x, stop, ex, rk, dr] = simulate(D, days, x, stop, ex, RSI_RULES[rk], dr)

    def lab(key):
        x, stop, ex, rk, dr = key
        return f"{'順勢' if dr > 0 else '逆勢'} ±{x * 100:g}% 止蝕{stop} {'收市' if not ex else f'{ex}R'} RSI{rk}"

    print("######## 1. 全期（2018-10 至 2026-10，1 張大期，點）：純開市突破（無 RSI）########")
    for dr in (1, -1):
        for x, stop, ex in itertools.product((0.0025, 0.005, 0.0075, 0.01), ("對面", "基準"), (None, 1, 2)):
            print(line(lab((x, stop, ex, "無", dr)), stats(R[x, stop, ex, "無", dr], D)))
        print()
    print("######## 2. 三個階段 Sharpe（全部 192 組）########")
    rows = []
    for key, res in R.items():
        ph = {p: stats(res, D, *PH[p]) for p in PH}
        if all(ph.values()):
            rows.append((key, ph))
    pos = [r for r in rows if all(r[1][p]["sharpe"] > 0 for p in PH)]
    print(f"三個階段 Sharpe 都 > 0：{len(pos)}／{len(rows)}；都 > 0.5：{sum(1 for r in rows if all(r[1][p]['sharpe'] > 0.5 for p in PH))}")
    for dname, dr in (("順勢", 1), ("逆勢", -1)):
        sub = [r for r in rows if r[0][4] == dr]
        sub.sort(key=lambda r: -min(r[1][p]["sharpe"] for p in PH))
        print(f"\n{dname}：最差階段 Sharpe 最高 6 組")
        for key, ph in sub[:6]:
            print(f"  {lab(key):40s} " + "  ".join(f"{p} {ph[p]['sharpe']:5.2f}／{ph[p]['ann']:+6.0f}" for p in PH))
    print("\n######## 3. RSI 篩選的作用（順勢，±0.5%，止蝕對面）########")
    for ex in (None, 1, 2):
        for rk in RSI_RULES:
            print(line(lab((0.005, "對面", ex, rk, 1)), stats(R[0.005, "對面", ex, rk, 1], D)))
    print("\n######## 4. 分年（每年盈虧點／勝率／筆數）########")
    picks = [(0.005, "對面", None, "無", 1), (0.005, "對面", None, "順勢確認", 1), (0.005, "對面", None, "不追極端", 1),
             (0.005, "基準", 2, "無", 1), (0.0025, "對面", None, "無", 1), (0.01, "對面", None, "無", 1),
             (0.005, "對面", None, "無", -1), (0.005, "對面", None, "不追極端", -1)]
    best_tr = max((r for r in rows), key=lambda r: min(r[1]["P1"]["sharpe"], r[1]["P2"]["sharpe"]))[0]
    picks.append(best_tr)
    print(" " * 42 + "".join(f"{y:>16s}" for y in YEARS) + "        全期")
    for key in picks:
        res = R[key]
        cells = []
        for y in YEARS:
            st = stats(res, D, f"{y}-01-01", f"{y}-12-31")
            cells.append(f"{st['pnl']:+6.0f}/{st['win']:3.0%}/{st['n']:3d}" if st else " " * 16)
        al = stats(res, D)
        tag = "（2018–2023 挑出）" if key == best_tr else ""
        print(f"  {lab(key) + tag:40s}" + "".join(f"{c:>16s}" for c in cells) + f"  {al['pnl']:+7.0f}（Sharpe {al['sharpe']:.2f}）")


if __name__ == "__main__":
    main()
