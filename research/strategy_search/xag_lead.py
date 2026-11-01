"""[IDEAS #191／#192] 用白銀訊號做黃金：訊號喺 XAGUSD 計，落單喺 XAUUSD。
#191 家族（D1 同 H4 各計，日界／H4 都係 22:00 UTC 對齊；白銀同黃金按同一個時段鍵對齊，白銀冇嗰根就唔出訊號）：
  X1–X8 ＝ #172 嘅 J1–J8（均線交叉、MACD、DMI、保力加、Keltner、一目、拋物線 SAR、威廉 %R）喺白銀 K 線計，網格同 #172
  X9  ＝ 金銀相對動量：白銀 N 根回報 − 黃金 N 根回報，按過去 250 根標準化成 z；z > zin（白銀跑贏）→ follow 買金／fade 沽金，z < −zin 相反
        網格 N ∈ {5,10,20}、zin ∈ {1.0,1.5}、mode ∈ {follow,fade}、ex ∈ EXITS
  X10 ＝ 白銀突破、黃金未破：白銀收市破 20 根高位而黃金收市未破自己 20 根高位 → 買金（追落後）；低位相反；filt（黃金 SMA200 同向）× ex
  入場：訊號 K 收市後黃金下一根第一根 H1 開盤；SL／TP × 黃金該時框 ATR20；時間止蝕 D1 480h／H4 80h；扣 0.5 美元；一次一張。
  Dukascopy 金、銀 H1 2005→2026；滾動前向 4 年揀 1 年測（2009→2026）；MT5（金、銀券商 2022-08→）用返每年揀法對照。
  判（同 #172，正數年按使用者 11-01「只睇最近 10 年」）：樣本外 ≥ 200 張、勝率高過隨機基準 ≥ 2pp、平均 ≥ +0.05R、最近 10 年（2017–2026）≥ 6/10 年正、
  兩半都正、隔夜息後 > 0、MT5 > 0。20 組同時測，t < 2.5 嘅合格標「弱」。
#192 候選＝#191 入面「平均 ≥ +0.05R、PF ≥ 1.15、最近 10 年 ≥ 6/10 年正、MT5 > 0」；排喺 935 六個成份之後（按平均 R 高到低）做單倉版。
  判「比 935 好」：平均 > +0.083R、PF > 1.24、最近 10 年正數年 ≥ 7/10（935 本身 7/10）、最大回撤唔差過 −26.6R、MT5 > 0。合格都只係提案。
用法：python3 research/strategy_search/xag_lead.py → XAG_LEAD.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import m5_indicators as M  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust_long as R  # noqa: E402

XCACHE = "/tmp/duka_h1_xag.npz"
EX = range(3)
FAMILIES = {f"X{i + 1} 白銀{k[3:]}": v for i, (k, v) in enumerate(Q.FAMILIES.items())}
FAMILIES["X9 金銀相對動量"] = [dict(N=n, zin=z, mode=m, ex=e) for n, z, m, e in itertools.product((5, 10, 20), (1.0, 1.5), ("follow", "fade"), EX)]
FAMILIES["X10 白銀突破黃金未破"] = [dict(filt=f, ex=e) for f, e in itertools.product((False, True), EX)]
JKEY = {f"X{i + 1}": k for i, k in enumerate(Q.FAMILIES)}
TFS = (("D1", 480, Q.DI, 86400), ("H4", 80, H.H4I, 14400))
A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)
Y10 = range(2017, 2027)


def load_xag():
    if os.path.exists(XCACHE):
        z = np.load(XCACHE)
        return z["t"], z["o"], z["h"], z["l"], z["c"]
    import silver_friday as F
    s = F.load("xau/sig/duka_h1_xagusd/")
    np.savez(XCACHE, t=s[0], o=s[1], h=s[2], l=s[3], c=s[4])
    return s


def mt5_silver():
    import import_mt5 as I
    rows = [l.strip().split(",") for l in open("/tmp/xag_mt5/XAGUSD_H1_MAX.csv").read().splitlines()[1:]]
    t = np.array([I.server_to_utc(r[0]) for r in rows]); a = np.array([[float(v) for v in r[1:5]] for r in rows])
    ds = load_xag(); cut = t[0]; pre = [x[ds[0] < cut] for x in ds]
    return [np.r_[pre[0], t], np.r_[pre[1], a[:, 0]], np.r_[pre[2], a[:, 1]], np.r_[pre[3], a[:, 2]], np.r_[pre[4], a[:, 3]]]


class Pair:
    """黃金框 G、白銀框 S；map[g] ＝ 同一時段鍵嘅白銀 index（冇就 −1）。"""
    def __init__(self, G, S, period):
        kg = (G.t[G.dfirst] + 7200) // period; ks = (S.t[S.dfirst] + 7200) // period
        pos = {int(k): i for i, k in enumerate(ks)}
        self.G, self.S = G, S
        self.map = np.array([pos.get(int(k), -1) for k in kg])

    def to_gold(self, arr):
        out = np.zeros(len(self.map), bool); ok = self.map >= 0
        out[ok] = arr[self.map[ok]]
        return out


def zret(c, n, w=250):
    r = np.r_[np.full(n, np.nan), np.log(c[n:] / c[:-n])]
    return r


def signals(PR, fam, p):
    G, S = PR.G, PR.S; key = fam.split()[0]
    if key in JKEY:
        b, x = Q.signals(S, JKEY[key], p)
        b, x = PR.to_gold(b), PR.to_gold(x)
    elif key == "X9":
        n = p["N"]; ok = PR.map >= 0
        rs = np.full(len(PR.map), np.nan); rs[ok] = zret(S.dc, n)[PR.map[ok]]
        rel = rs - zret(G.dc, n)
        mu = M.rolling(np.nan_to_num(rel), 250, np.mean); sd = M.rolling(np.nan_to_num(rel), 250, np.std)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (rel - mu) / sd
        up, dn = np.nan_to_num(z) > p["zin"], np.nan_to_num(z) < -p["zin"]
        pu, pd_ = np.r_[False, up[:-1]], np.r_[False, dn[:-1]]
        up, dn = up & ~pu, dn & ~pd_                       # 只喺啱啱過線嗰根出訊號
        b, x = (up, dn) if p["mode"] == "follow" else (dn, up)
    else:
        sh = np.r_[np.nan, M.rolling(S.dh, 20, np.max)[:-1]]; sl = np.r_[np.nan, M.rolling(S.dl, 20, np.min)[:-1]]
        gh = np.r_[np.nan, M.rolling(G.dh, 20, np.max)[:-1]]; gl = np.r_[np.nan, M.rolling(G.dl, 20, np.min)[:-1]]
        sbo, sbd = S.dc > sh, S.dc < sl
        sbo, sbd = sbo & ~np.r_[False, sbo[:-1]], sbd & ~np.r_[False, sbd[:-1]]
        b = PR.to_gold(sbo) & ~(G.dc > gh); x = PR.to_gold(sbd) & ~(G.dc < gl)
        if p["filt"]:
            b &= G.dc > G.s200; x &= G.dc < G.s200
    return np.nan_to_num(b).astype(bool), np.nan_to_num(x).astype(bool)


def run(PR, fam, p, th):
    G = PR.G; b, x = signals(PR, fam, p); tp, sl = Q.EXITS[p["ex"]]
    both = b & x; b, x = b & ~both, x & ~both
    ent = [(int(G.dfirst[d + 1]), 1 if b[d] else -1, sl * G.datr[d], tp * G.datr[d], th)
           for d in np.flatnonzero(b | x) if 260 <= d < len(G.dc) - 1 and G.datr[d] > 0]
    return R.simulate(G, ent)


def pos10(trs):
    yy = {}
    for x in trs:
        yy.setdefault(R.yr(x[0]), []).append(x[3])
    return sum(1 for y in Y10 if y in yy and np.sum(yy[y]) > 0), yy


def main():
    R.COST = 0.5
    gd, sd = R.load_duka(), load_xag(); gm, sm_ = R.load_mt5_spliced(gd), mt5_silver()
    out = ["# 用白銀訊號做黃金（IDEAS #191）＋加入 935 單倉（#192）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；訊號喺白銀計、落單喺黃金；Dukascopy 2005→2026 滾動前向（2009→2026）；正數年只睇最近 10 年（2017–2026，使用者 11-01）",
           "", "## #191 各家族（樣本外）", "",
           "| 時框 | 家族 | 樣本外 | 勝率 | 基準 | 差 | t | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for tf, th, cls, per in TFS:
        PR = Pair(cls(*gd), cls(*sd), per); PM = Pair(cls(*gm), cls(*sm_), per)
        Q.T_H = th; base = Q.baseline(PR.G)
        for fam, grid in FAMILIES.items():
            T = [run(PR, fam, p, th) for p in grid]
            oos, picks = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid)
            oos = [x for x in oos if R.yr(x[0]) >= 2009]
            bw = [base[grid[picks[R.yr(x[0])]]["ex"]].get(R.yr(x[0]), (np.nan, 0))[0] for x in oos]
            rs = np.array([x[3] for x in oos]); s = R.summ(rs); sw = R.summ(R.swap_r(oos))
            win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(bw)) if bw else 0.0
            p10, _ = pos10(oos)
            h1 = R.summ([x[3] for x in oos if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in oos if R.yr(x[0]) >= 2018])
            mtr, cache = [], {}
            for Y, g in picks.items():
                if g is None or Y < 2022:
                    continue
                if g not in cache:
                    cache[g] = run(PM, fam, grid[g], th)
                mtr += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= P.A0]
            smt = R.summ([x[3] for x in mtr])
            ok = dict(n=s["n"] >= 200, edge=win - bwin >= 0.02, avg=s["avg"] >= 0.05, yrs10=p10 >= 6,
                      halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0, mt5=smt["n"] > 0 and smt["avg"] > 0)
            near = s["avg"] >= 0.05 and s["pf"] >= 1.15 and p10 >= 6 and smt["n"] > 0 and smt["avg"] > 0
            name = f"{tf} {fam}"
            res[name] = dict(oos=oos, mt=mtr, ok=ok, near=near, s=s, picks=picks, grid=grid)
            v = ("✅" + ("（弱，t < 2.5）" if s["t"] < 2.5 else "")) if all(ok.values()) else "❌ " + "、".join(k for k, b in ok.items() if not b)
            out.append(f"| {tf} | {fam} | {s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | {s['t']:.2f} | {p10}/10 | "
                       f"{h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {smt['n']} 張 {smt['avg']:+.3f} | {v}{'；🔸候選' if near else ''} |")
            print(name, s["n"], round(s["avg"], 3), round(s["pf"], 2), p10, smt["n"], round(smt["avg"], 3), flush=True)
    passed = [k for k, r in res.items() if all(r["ok"].values())]
    cands = sorted([k for k, r in res.items() if r["near"]], key=lambda k: -res[k]["s"]["avg"])
    out += ["", f"- #191 合格：{'、'.join(passed) if passed else '冇'}", f"- #192 候選：{'、'.join(cands) if cands else '冇'}", "", "## #192 935 單倉＋候選", ""]
    if cands:
        ds, picksA = P.streams(gd); ms, _ = P.streams(gm, picksA); keys = [k for k in ds if not k.startswith("7")]
        out += ["| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        variants = [("935 現行", []), ("935＋全部候選", cands)] + ([(f"935＋{c}", [c]) for c in cands] if len(cands) > 1 else [])
        for label, add in variants:
            dd_ = dict(ds); mm_ = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
            for c in add:
                dd_[c] = res[c]["oos"]; mm_[c] = res[c]["mt"]
            kk = keys + add; trs = PS.single(dd_, kk); mtr = PS.single(mm_, kk)
            ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr); p10, _ = pos10(trs)
            eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
            e1, m1, _, _ = P.equity(trs, 30000, 1.0)
            better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
            out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                       f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {'—' if not add else ('✅ 更好' if better else '❌')} |")
            print(label, s, p10, dd, flush=True)
        out += ["", "- 候選係睇完 #191 樣本外結果先揀（事後揀選偏差）；更好都只係提案，改 935 要使用者經總指揮批。"]
    else:
        out.append("- 冇候選，935 維持現行。")
    out += ["", "## 合格／候選 2026 揀法", ""] + [f"- {k}：{r['grid'][r['picks'][2026]] if r['picks'].get(2026) is not None else '2026 唔做'}" for k, r in res.items() if r["near"] or all(r["ok"].values())]
    open(os.path.join(HERE, "XAG_LEAD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
