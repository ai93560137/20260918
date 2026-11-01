"""[IDEAS #183] XAUUSD 幾個接近合格策略一齊用（組合）。每個策略只用佢自己嘅滾動前向樣本外成交（每年用前 4 年揀參數、測嗰一年），2009→2026：
  1 D1 J5 Keltner 突破（#172）  2 D1 J7 拋物線 SAR（#172）  3 D1 J8 威廉 %R（#172）
  4 H4 J2 MACD（#182）          5 H4 J7 拋物線 SAR（#182）  6 星期效應 S2（#167）
另列描述：加埋 7 日線 B 確認（#173，固定參數，喺黃金屬事後揀，偏好睇）。
組合判斷（使用者 11-01 准唔計張數）：平均 ≥ +0.05R、PF ≥ 1.15、≥ 11/18 年合計 R 正、2009–17 同 2018–26 兩半都正、扣隔夜息後 > 0、MT5 2022-10→2026-10 > 0。
資金：本金 30,000 HKD，每張風險 3%（同時有幾張就疊加），最少 0.01 手。
用法：python3 research/strategy_search/portfolio.py → PORTFOLIO.md"""
import datetime as dt
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_combo as C  # noqa: E402
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402

A0 = int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp())
HKD = 7.8


def wf_stream(run_fn, grid, years=range(2009, 2027)):
    """回傳 (樣本外成交, 每年揀咗邊組)。"""
    T = [run_fn(p) for p in grid]
    oos, picks = [], {}
    for Y in years:
        best = None
        for gi, tr in enumerate(T):
            s = R.summ([x[3] for x in tr if Y - 4 <= R.yr(x[0]) < Y])
            if s["n"] >= R.MIN_TRAIN_N and s["pf"] >= R.MIN_TRAIN_PF and (best is None or s["avg"] > best[1]):
                best = (gi, s["avg"])
        picks[Y] = None if best is None else best[0]
        if best is not None:
            oos += [x for x in T[best[0]] if R.yr(x[0]) == Y]
    return oos, picks


def streams(arrs, mt5_picks=None):
    """arrs＝(t,o,h,l,c)；mt5_picks 有值就用返嗰啲每年揀法（MT5 對照）。"""
    R.COST = 0.5
    D1 = Q.DI(*arrs); D4 = H.H4I(*arrs); DW = S2.D2(*arrs)
    defs = [
        ("1 D1 Keltner 突破", "J5", D1, 480, Q.FAMILIES["J5 Keltner 突破"]),
        ("2 D1 拋物線 SAR", "J7", D1, 480, Q.FAMILIES["J7 拋物線 SAR 轉向"]),
        ("3 D1 威廉 %R", "J8", D1, 480, Q.FAMILIES["J8 威廉 %R 極端回歸"]),
        ("4 H4 MACD", "J2", D4, 80, Q.FAMILIES["J2 MACD 交叉"]),
        ("5 H4 拋物線 SAR", "J7", D4, 80, Q.FAMILIES["J7 拋物線 SAR 轉向"]),
    ]
    out, picks = {}, {}
    for name, key, D, th, grid in defs:
        def fn(p, D=D, key=key, th=th):
            Q.T_H = th
            return Q.run(D, key, p)
        if mt5_picks is None:
            out[name], picks[name] = wf_stream(fn, grid)
        else:
            tr = []
            for Y, g in mt5_picks[name].items():
                if g is not None and Y >= 2022:
                    tr += [x for x in fn(grid[g]) if R.yr(x[0]) == Y]
            out[name] = tr
    g6 = S2.FAMILIES["S2 星期效應"]
    if mt5_picks is None:
        out["6 星期效應"], picks["6 星期效應"] = wf_stream(lambda p: S2.s2(DW, p), g6)
    else:
        out["6 星期效應"] = [x for Y, g in mt5_picks["6 星期效應"].items() if g is not None and Y >= 2022 for x in S2.s2(DW, g6[g]) if R.yr(x[0]) == Y]
    out["7 日線 B 確認（描述）"] = C.combo(D1, "B")
    return out, picks


def equity(trs, start=30000.0, pct=3.0):
    """同時有倉就疊加；按開倉時權益計手數（最少 0.01）；平倉先入帳。"""
    ev = sorted([(x[0], 0, i) for i, x in enumerate(trs)] + [(x[4], 1, i) for i, x in enumerate(trs)], key=lambda e: (e[0], -e[1]))
    eq = peak = start; mdd = 0.0; lots = {}; maxopen = 0; skipped = 0
    for ts, kind, i in ev:
        x = trs[i]
        if kind == 0:
            lot = math.floor(eq * pct / 100 / (x[2] * 100 * HKD) / 0.01 + 1e-9) * 0.01
            if lot < 0.01:
                lot = 0.01; skipped += 1
            lots[i] = lot; maxopen = max(maxopen, len(lots))
        elif i in lots:
            eq += x[3] * x[2] * 100 * lots.pop(i) * HKD
            peak = max(peak, eq); mdd = min(mdd, eq / peak - 1)
    return eq, mdd, maxopen, skipped


def report(name, trs, mt5_trs):
    rs = np.array([x[3] for x in trs]); s = R.summ(rs)
    yy = {}
    for x in trs:
        yy.setdefault(R.yr(x[0]), []).append(x[3])
    pos = sum(1 for v in yy.values() if np.sum(v) > 0)
    h1 = R.summ([x[3] for x in trs if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in trs if R.yr(x[0]) >= 2018])
    sw = R.summ(R.swap_r(trs)); m = R.summ([x[3] for x in mt5_trs if x[0] >= A0])
    ok = dict(avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, yrs=pos >= 11, halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0, mt5=m["n"] > 0 and m["avg"] > 0)
    return ok, s, pos, len(yy), h1, h2, sw, m, yy


def main():
    duka = R.load_duka()
    ds, picks = streams(duka)
    ms, _ = streams(R.load_mt5_spliced(duka), picks)
    core = [k for k in ds if not k.startswith("7")]
    out = ["# XAUUSD 幾個策略一齊用（IDEAS #183）", "",
           "- 每個策略只用滾動前向樣本外成交（2009→2026）；組合唔計張數（使用者 11-01 准）；本金 30,000 HKD、每張風險 3%", "",
           "## 各策略（樣本外）", "", "| 策略 | 張數 | 平均 R | PF | 合計 R | 正數年 | MT5 2022-10→ |", "|---|---|---|---|---|---|---|"]
    for k in ds:
        ok, s, pos, ny, h1, h2, sw, m, _ = report(k, [x for x in ds[k] if R.yr(x[0]) >= 2009], ms[k])
        out.append(f"| {k} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {pos}/{ny} | {m['n']} 張 {m['avg']:+.3f} |")
    res = {}
    for label, keys in (("組合 A（1–6，全部樣本外）", core), ("組合 B（1–6＋日線 B，描述）", list(ds))):
        trs = sorted([x for k in keys for x in ds[k] if R.yr(x[0]) >= 2009])
        mt = [x for k in keys for x in ms[k]]
        ok, s, pos, ny, h1, h2, sw, m, yy = report(label, trs, mt)
        eq, mdd, mo, sk = equity(trs)
        eqm, mddm, _, _ = equity(sorted(x for x in mt if x[0] >= A0))
        res[label] = ok
        out += ["", f"## {label}", "",
                f"- {s['n']} 張 平均 {s['avg']:+.3f}R PF {s['pf']:.2f} 合計 {s['sum']:+.1f}R；{pos}/{ny} 年正；2009–17 {h1['avg']:+.3f}、2018–26 {h2['avg']:+.3f}；扣隔夜息後 {sw['avg']:+.3f}；MT5 {m['n']} 張 {m['avg']:+.3f}R",
                f"- 30,000 HKD 每張 3%：2009→2026 最終 {eq:,.0f}，最大回撤 {mdd:.0%}，最多同時 {mo} 張（{sk} 張 0.01 手仍超 3%）；MT5 2022-10→ 最終 {eqm:,.0f}，回撤 {mddm:.0%}",
                f"- 逐年合計 R：" + "、".join(f"{y} {np.sum(v):+.1f}" for y, v in sorted(yy.items())),
                f"- 判：{'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)}"]
        print(label, s, pos, flush=True)
    out += ["", "## 判", "", f"- 組合 A：{'✅ 合格' if all(res['組合 A（1–6，全部樣本外）'].values()) else '❌'}（主判）；組合 B 只作描述",
            "- 注意：六個策略係睇完結果先揀嘅「接近合格」，組合有事後揀選偏差；合格都只係影子前向候選，真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "PORTFOLIO.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
