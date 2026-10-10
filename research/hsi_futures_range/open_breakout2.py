"""開市突破（open_breakout.py）＋ 大波幅日篩選 ＋ Nasdaq 隔夜方向 ＋ RSI（使用者 2026-10-10）。

只做順勢（開市後升／跌 X% 先觸發那邊跟進），止蝕在對面（距離 2X），日市收市或 1R／2R 止賺。開市前已知的篩選（都不偷看）：
  波幅  無／上日波幅 ≥ 1.0 × ATR20／≥ 1.3 × ATR20／VHSI 上日收市 > 過去 252 日中位數／> 252 日 75 分位／
        開市跳空 |開市 ÷ 上日收市 − 1| ≥ 0.5%／≥ 1%
  Nasdaq 隔夜（恒指上日日市收市 16:30 → 今日 09:15，Dukascopy USATECH 15 分 K）：
        無／同方向才做／同方向且 ≥ 0.5%／反方向才做（對照）；沒有數據的日子在有 Nasdaq 條件時不做
  RSI   無／順勢確認（買 ≥ 60、沽 ≤ 40）／不追極端（買 < 70、沽 > 30）
階段：P1 2018-10–2020-12、P2 2021–2023、P3 2024 起。成本每邊 1 點，每點 HK$50。

用法：python3 research/hsi_futures_range/open_breakout2.py --json /tmp/hsimain.json
"""
import argparse, csv, itertools, json, sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_cross as dc                                    # noqa: E402
import dizai_search as ds                                   # noqa: E402
import open_breakout as ob                                  # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def vhsi_prev(days):
    rows = [(r["Date"], float(r["Close"])) for r in csv.DictReader(open(REPO / "canary" / "data_external" / "vhsi_daily.csv")) if r["Close"]]
    dates = [d for d, _ in rows]
    vals = np.array([v for _, v in rows])
    out = {}
    import bisect
    for d in days:
        i = bisect.bisect_left(dates, d) - 1                 # 日期早於今日的最後一個收市
        if i >= 252:
            w = vals[i - 251:i + 1]
            out[d] = (vals[i], np.median(w), np.percentile(w, 75))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = ob.day_slices(D)
    o, h, l, c, tk, dates = D["o"], D["h"], D["l"], D["c"], D["tk"], D["days"]
    nq = dc.load_us("usatechidxusd")
    vh = vhsi_prev(dates)
    feat = {}
    prev = None
    for k, s, e in days:
        if prev is not None:
            pk, ps, pe = prev
            rng = h[ps:pe].max() - l[ps:pe].min()
            pc = c[D["ends"][k - 1] - 1]                     # 上一個交易日最後一根（含夜市）
            t0 = dc.hk_to_utc_min(tk[pe - 1])                # 上日日市收市
            t1 = dc.hk_to_utc_min(tk[s]) - 1                 # 今日 09:15 開市
            feat[k] = {"rng_atr": rng / D["atr"][s] if not np.isnan(D["atr"][s]) else np.nan,
                       "gap": o[s] / pc - 1, "nq": dc.us_move(nq, t0, t1), "vh": vh.get(dates[k])}
        prev = (k, s, e)

    VOL = {"無": lambda f: True,
           "上日波幅≥1.0ATR": lambda f: f["rng_atr"] >= 1.0, "上日波幅≥1.3ATR": lambda f: f["rng_atr"] >= 1.3,
           "VHSI>中位": lambda f: f["vh"] is not None and f["vh"][0] > f["vh"][1],
           "VHSI>75分位": lambda f: f["vh"] is not None and f["vh"][0] > f["vh"][2],
           "跳空≥0.5%": lambda f: abs(f["gap"]) >= 0.005, "跳空≥1%": lambda f: abs(f["gap"]) >= 0.01}
    NQ = {"無": lambda f, b: True,
          "NQ同向": lambda f, b: f["nq"] is not None and f["nq"] * b > 0,
          "NQ同向≥0.5%": lambda f, b: f["nq"] is not None and f["nq"] * b >= 0.005,
          "NQ反向": lambda f, b: f["nq"] is not None and f["nq"] * b < 0}
    print(f"交易日 {len(days)}；有 Nasdaq 隔夜數據 {sum(1 for f in feat.values() if f['nq'] is not None)}；有 VHSI {sum(1 for f in feat.values() if f['vh'])}\n")

    R = {}
    for x, ex, vk, nk, rk in itertools.product((0.0025, 0.005), (None, 1, 2), VOL, NQ, ob.RSI_RULES):
        def allow(k, b, vk=vk, nk=nk):
            f = feat.get(k)
            if f is None:
                return False
            try:
                return bool(VOL[vk](f)) and bool(NQ[nk](f, b))
            except TypeError:
                return False
        R[x, ex, vk, nk, rk] = ob.simulate(D, days, x, "對面", ex, ob.RSI_RULES[rk], 1, allow)

    def lab(key):
        x, ex, vk, nk, rk = key
        return f"±{x * 100:g}% {'收市' if not ex else f'{ex}R'} {vk} {nk} RSI{rk}"

    rows = []
    for key, res in R.items():
        ph = {p: ob.stats(res, D, *ob.PH[p]) for p in ob.PH}
        al = ob.stats(res, D)
        if all(ph.values()) and al["n"] >= 80:
            rows.append((key, ph, al))
    print(f"######## 共 {len(R)} 組（全期 ≥ 80 筆的 {len(rows)} 組）########")
    print(f"三段 Sharpe 都 > 0：{sum(1 for r in rows if all(r[1][p]['sharpe'] > 0 for p in ob.PH))}；"
          f"都 > 0.5：{sum(1 for r in rows if all(r[1][p]['sharpe'] > 0.5 for p in ob.PH))}；"
          f"都 > 1：{sum(1 for r in rows if all(r[1][p]['sharpe'] > 1 for p in ob.PH))}")

    print("\n1. 各篩選單獨的效果（±0.25%、收市、其他不篩）")
    base = (0.0025, None, "無", "無", "無")
    for k2 in [base] + [(0.0025, None, v, "無", "無") for v in VOL if v != "無"] + [(0.0025, None, "無", n, "無") for n in NQ if n != "無"] \
            + [(0.0025, None, "無", "無", r) for r in ob.RSI_RULES if r != "無"]:
        st = ob.stats(R[k2], D)
        ph = {p: ob.stats(R[k2], D, *ob.PH[p]) for p in ob.PH}
        print(ob.line(lab(k2), st) + "｜三段 " + "／".join(f"{ph[p]['sharpe']:.2f}" if ph[p] else "—" for p in ob.PH))

    print("\n2. 最差階段 Sharpe 最高 12 組（≥ 80 筆）")
    rows.sort(key=lambda r: -min(r[1][p]["sharpe"] for p in ob.PH))
    for key, ph, al in rows[:12]:
        print(f"  {lab(key):44s} 筆{al['n']:4d} 勝{al['win']:4.0%} 每年{al['ann']:+6.0f} 回撤{al['mdd']:7.0f} 全期Sharpe {al['sharpe']:.2f}｜"
              + "  ".join(f"{p} {ph[p]['sharpe']:5.2f}" for p in ob.PH))

    print("\n3. 只用 2018–2023 挑（P1、P2 較差那段 Sharpe 最高），看 2024 起")
    tr = sorted(rows, key=lambda r: -min(r[1]["P1"]["sharpe"], r[1]["P2"]["sharpe"]))[:8]
    for key, ph, al in tr:
        print(f"  {lab(key):44s} P1 {ph['P1']['sharpe']:5.2f} P2 {ph['P2']['sharpe']:5.2f} → P3 {ph['P3']['sharpe']:5.2f}（每年 {ph['P3']['ann']:+.0f} 點）")

    print("\n4. 分年（每年盈虧點／勝率／筆數）")
    picks = [base] + [r[0] for r in rows[:4]] + [tr[0][0]]
    seen = []
    for k2 in picks:
        if k2 in seen:
            continue
        seen.append(k2)
    print(" " * 46 + "".join(f"{y:>16s}" for y in ob.YEARS) + "    全期")
    for k2 in seen:
        cells = []
        for y in ob.YEARS:
            st = ob.stats(R[k2], D, f"{y}-01-01", f"{y}-12-31")
            cells.append(f"{st['pnl']:+6.0f}/{st['win']:3.0%}/{st['n']:3d}" if st else "—")
        al = ob.stats(R[k2], D)
        print(f"  {lab(k2):44s}" + "".join(f"{c_:>16s}" for c_ in cells) + f"  {al['pnl']:+7.0f}（Sharpe {al['sharpe']:.2f}、回撤 {al['mdd']:.0f}）")


if __name__ == "__main__":
    main()
