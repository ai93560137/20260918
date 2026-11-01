"""[IDEAS #189] 組合 A（935）五個指標成份改出場方法：入場訊號唔變，出場加四種揀法，同原本固定 TP／SL 一齊交滾動前向揀。
出場模式（xm）：
  fix  ＝ 原本（TP／SL × ATR，EXITS 三組）
  be   ＝ 同 fix，但浮盈到 +1R 之後止蝕搬去入場價（＋0.5 美元成本），下一根 H1 先生效
  tr2／tr3 ＝ 冇 TP；初始止蝕同 fix；之後追蹤止蝕＝入場後最高（做空最低）H1 價 − 2／3 × 訊號時框 ATR（每根 H1 收市後更新，下一根先生效）
  opp  ＝ 冇 TP；初始止蝕同 fix；同家族出反向訊號 → 下一根 H1 開盤平
時間止蝕照舊（D1 480h、H4 80h）。星期效應（成份 6）唔變。每個成份網格＝原本網格 × 5 個出場模式，滾動前向 4 年揀 1 年測（2009→2026）。
判（主）：五個成份用新揀法、星期效應照舊，做單倉版（同 #186：同時 1 張，按成份次序）→「比 935 好」＝平均 > +0.083R、PF > 1.24、≥ 14/18 年正、
最大回撤唔差過 −26.6R、MT5 2022-10→ > 0，且過 #183 六條。另列「全部固定用某一模式」（唔經滾動揀）做描述。
合格都只係提案；改 935 出場要改程式、使用者經總指揮批。
用法：python3 research/strategy_search/exits_a.py → EXITS_A.md"""
import datetime as dt
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402

MODES = ("fix", "be", "tr2", "tr3", "opp")
COMPS = [  # 名（同 portfolio.streams 一樣）、家族、時框、時間止蝕
    ("1 D1 Keltner 突破", "J5 Keltner 突破", "D1", 480),
    ("2 D1 拋物線 SAR", "J7 拋物線 SAR 轉向", "D1", 480),
    ("3 D1 威廉 %R", "J8 威廉 %R 極端回歸", "D1", 480),
    ("4 H4 MACD", "J2 MACD 交叉", "H4", 80),
    ("5 H4 拋物線 SAR", "J7 拋物線 SAR 轉向", "H4", 80),
]
A_SINGLE = dict(avg=0.083, pf=1.24, yrs=14, dd=-26.6)


def sim2(D, entries, mode, exitL=None, exitS=None):
    """entries：(a, s, sl_dist, tp_dist|None, max_h, atr)。規則同 R.simulate，加保本／追蹤（收市後更新、下一根生效）。"""
    t, o, h, l = D.t, D.o, D.h, D.l
    n = len(t); out = []; busy = -1; k = {"tr2": 2.0, "tr3": 3.0}.get(mode)
    for a, s, d, tpd, mh, atr in entries:
        if a <= busy or a >= n or not d or d <= 0 or math.isnan(d):
            continue
        px = o[a]; sl = px - s * d; tp = None if tpd is None else px + s * tpd
        ext = px; moved = False; ex = None; mask = exitL if s > 0 else exitS
        for j in range(a, n):
            if t[j] - t[a] >= mh * 3600:
                ex, xi = o[j], j - 1; break
            if j > a and (o[j] - sl) * s <= 0:
                ex, xi = o[j], j; break
            if (l[j] <= sl) if s > 0 else (h[j] >= sl):
                ex, xi = sl, j; break
            if tp is not None and ((h[j] >= tp) if s > 0 else (l[j] <= tp)):
                ex, xi = tp, j; break
            if mask is not None and mask[j] and j + 1 < n:
                ex, xi = o[j + 1], j; break
            ext = max(ext, h[j]) if s > 0 else min(ext, l[j])
            if mode == "be" and not moved and (ext - px) * s >= d:
                sl = px + s * R.COST; moved = True
            elif k:
                nsl = ext - s * k * atr
                if (nsl - sl) * s > 0:
                    sl = nsl
        if ex is None:
            break
        out.append((int(t[a]), s, float(d), float((s * (ex - px) - R.COST) / d), int(t[min(xi + 1, n - 1)])))
        busy = xi
    return out


def run(D, fam, p, th):
    b, x = Q.signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]; m = p["xm"]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d] if m in ("fix", "be") else None, th, D.datr[d])
           for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]
    eL = eS = None
    if m == "opp":
        eL = np.zeros(len(D.t), bool); eL[D.dlast[np.flatnonzero(x)]] = True
        eS = np.zeros(len(D.t), bool); eS[D.dlast[np.flatnonzero(b)]] = True
    return sim2(D, ent, m, eL, eS)


def main():
    R.COST = 0.5
    duka = R.load_duka(); mt = R.load_mt5_spliced(duka)
    fr = {"D1": (Q.DI(*duka), Q.DI(*mt)), "H4": (H.H4I(*duka), H.H4I(*mt))}
    ds, picksA = P.streams(duka); ms, _ = P.streams(mt, picksA)
    keys = [k for k in ds if not k.startswith("7")]
    out = ["# 組合 A 五個指標成份改出場（IDEAS #189）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；出場模式 fix／be（+1R 保本）／tr2／tr3（追蹤 2／3 ATR）／opp（反向訊號）交滾動前向同參數一齊揀；星期效應唔變",
           "", "## 各成份（樣本外 2009→2026）", "", "| 成份 | 原本 | 新揀法 | 新 MT5 | 2026 揀 |", "|---|---|---|---|---|"]
    new_ds, new_ms, forced = dict(ds), {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}, {m: (dict(ds), {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}) for m in MODES}
    for name, fam, tf, th in COMPS:
        D, Mx = fr[tf]; base_grid = Q.FAMILIES[fam]
        grid = [dict(p, xm=m) for p in base_grid for m in MODES]
        T = [run(D, fam, p, th) for p in grid]
        oos, pk = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid)
        oos = [x for x in oos if R.yr(x[0]) >= 2009]
        cache = {}; mtr = []
        for Y, g in pk.items():
            if g is None or Y < 2022:
                continue
            if g not in cache:
                cache[g] = run(Mx, fam, grid[g], th)
            mtr += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= P.A0]
        new_ds[name], new_ms[name] = oos, mtr
        so, sn, sm = R.summ([x[3] for x in ds[name] if R.yr(x[0]) >= 2009]), R.summ([x[3] for x in oos]), R.summ([x[3] for x in mtr])
        out.append(f"| {name} | {R.fmt(so)} | {R.fmt(sn)} | {R.fmt(sm)} | {grid[pk[2026]] if pk.get(2026) is not None else '唔做'} |")
        print(name, so["avg"], sn["avg"], sm["n"], sm["avg"], flush=True)
        for m in MODES:                                      # 描述：全部固定用一個模式，參數照滾動揀
            sub = [p for p in grid if p["xm"] == m]; Ts = [T[grid.index(p)] for p in sub]
            o2, pk2 = P.wf_stream(lambda p, Ts=Ts, sub=sub: Ts[sub.index(p)], sub)
            forced[m][0][name] = [x for x in o2 if R.yr(x[0]) >= 2009]
            mm = []
            for Y, g in pk2.items():
                if g is not None and Y >= 2022:
                    mm += [x for x in run(Mx, fam, sub[g], th) if R.yr(x[0]) == Y and x[0] >= P.A0]
            forced[m][1][name] = mm
    out += ["", "## 單倉版（同 935：同時 1 張）", "",
            "| 版本 | 張數 | 平均 R | PF | 合計 R | 正數年 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 判 #183 | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    vers = [("935 現行（fix）", ds, {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}, False), ("主判：出場交滾動揀", new_ds, new_ms, True)]
    vers += [(f"描述：全部 {m}", forced[m][0], forced[m][1], False) for m in MODES if m != "fix"]
    for label, d_, m_, main_ in vers:
        trs = PS.single(d_, keys); mtr = PS.single(m_, keys)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0)
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and pos >= A_SINGLE["yrs"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0 and all(ok.values())
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {pos}/{ny} | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {'✅' if all(ok.values()) else '❌ ' + '、'.join(k for k, b in ok.items() if not b)} | "
                   f"{'—' if label.startswith('935') else ('✅ 更好' if better else '❌')} |")
        if main_:
            out.append("|  ↳ 逐年 | " + "、".join(f"{y} {np.sum(v):+.1f}" for y, v in sorted(yy.items())) + " |||||||||||||")
        print(label, s, pos, dd, flush=True)
    out += ["", "- 只有「主判」計數；「全部某模式」係事後描述。出場揀法同參數一齊滾動揀，網格大咗 5 倍，選擇偏差亦大咗。", ""]
    open(os.path.join(HERE, "EXITS_A.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
