"""[IDEAS #195／#196] 用其他市場訊號做黃金：訊號喺其他市場（Dukascopy H1）計，落單喺 XAUUSD。
市場：美匯指數 DOLLARIDXUSD、EURUSD、USDJPY、標普 500 USA500IDXUSD、美國長債 USTBONDTRUSD、WTI 原油 LIGHTCMDUSD、比特幣 BTCUSD、銅 COPPERCMDUSD。
#195 家族（每個市場 × D1／H4；同 #191 一樣按 22:00 UTC 時段鍵對齊，嗰個市場冇嗰根就唔出訊號）：
  M1 動量：該市場 N 根對數回報按過去 250 根標準化成 z，啱啱過 +zin → dir＝+1 買金（同向）／−1 沽金（反向）；過 −zin 相反
       網格 N ∈ {5,10,20}、zin ∈ {1.0,1.5}、dir ∈ {+1,−1}、ex ∈ EXITS
  M2 MACD 交叉、M3 拋物線 SAR 轉向、M4 均線交叉：#172 J2／J7／J1 喺該市場 K 線計（filt 用該市場 SMA200），網格同 #172 × dir ∈ {+1,−1}
  入場同 #191：黃金下一根第一根 H1 開盤；SL／TP × 黃金 ATR20；D1 480h／H4 80h；扣 0.5 美元；一次一張。
  滾動前向 4 年揀 1 年測（2009→2026；市場數據遲開始嘅年份自然冇成交）。MT5 對照：券商黃金（2022-10→）＋ Dukascopy 該市場訊號。
  判（同 #191）：≥ 200 張、勝率高過基準 ≥ 2pp、平均 ≥ +0.05R、最近 10 年 ≥ 6/10 年正、兩半都正、隔夜息後 > 0、MT5 > 0。
  64 組同時測（多重比較更嚴重）：t < 3.0 嘅合格標「弱」。
#196 候選＝#195「平均 ≥ +0.05R、PF ≥ 1.15、最近 10 年 ≥ 6/10、MT5 > 0」，排喺 935 六個成份之後（按平均 R 高到低）做單倉；
  判「比 935 好」同 #192（平均 > +0.083R、PF > 1.24、最近 10 年 ≥ 7/10、最大回撤唔差過 −26.6R、MT5 > 0）。只係提案。
數據：GCS xau/sig/duka_h1_<品種小寫>/（workflow「天覆陣 Dukascopy H1 補數」，使用者 11-01 要求研究而補）。
用法：python3 research/strategy_search/other_lead.py → OTHER_LEAD.md"""
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
import xag_lead as XL  # noqa: E402

MARKETS = {"DOLLARIDXUSD": "美匯指數", "EURUSD": "歐元", "USDJPY": "美元兌日圓", "USA500IDXUSD": "標普500",
           "USTBONDTRUSD": "美國長債", "LIGHTCMDUSD": "WTI 原油", "BTCUSD": "比特幣", "COPPERCMDUSD": "銅"}
EX = range(3)
DIRS = (1, -1)
FAMILIES = {
    "M1 動量": [dict(N=n, zin=z, dir=d, ex=e) for n, z, d, e in itertools.product((5, 10, 20), (1.0, 1.5), DIRS, EX)],
    "M2 MACD 交叉": [dict(p, dir=d) for p in Q.FAMILIES["J2 MACD 交叉"] for d in DIRS],
    "M3 拋物線 SAR": [dict(p, dir=d) for p in Q.FAMILIES["J7 拋物線 SAR 轉向"] for d in DIRS],
    "M4 均線交叉": [dict(p, dir=d) for p in Q.FAMILIES["J1 均線交叉"] for d in DIRS],
}
JKEY = {"M2": "J2 MACD 交叉", "M3": "J7 拋物線 SAR 轉向", "M4": "J1 均線交叉"}
TFS = (("D1", 480, Q.DI, 86400), ("H4", 80, H.H4I, 14400))
A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def load_mkt(sym):
    cache = f"/tmp/duka_h1_{sym.lower()}.npz"
    if os.path.exists(cache):
        z = np.load(cache)
        return z["t"], z["o"], z["h"], z["l"], z["c"]
    import silver_friday as F
    s = F.load(f"xau/sig/duka_h1_{sym.lower()}/")
    np.savez(cache, t=s[0], o=s[1], h=s[2], l=s[3], c=s[4])
    return s


def signals(PR, fam, p):
    S = PR.S; key = fam.split()[0]
    if key == "M1":
        n = p["N"]; ok = PR.map >= 0
        r = np.r_[np.full(n, np.nan), np.log(S.dc[n:] / S.dc[:-n])]
        mu = M.rolling(np.nan_to_num(r), 250, np.mean); sd = M.rolling(np.nan_to_num(r), 250, np.std)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.nan_to_num((r - mu) / sd)
        up, dn = z > p["zin"], z < -p["zin"]
        up, dn = up & ~np.r_[False, up[:-1]], dn & ~np.r_[False, dn[:-1]]
        b, x = PR.to_gold(up), PR.to_gold(dn)
    else:
        b, x = Q.signals(S, JKEY[key], p)
        b, x = PR.to_gold(b), PR.to_gold(x)
    return (b, x) if p["dir"] > 0 else (x, b)


def run(PR, fam, p, th):
    G = PR.G; b, x = signals(PR, fam, p); tp, sl = Q.EXITS[p["ex"]]
    both = b & x; b, x = b & ~both, x & ~both
    ent = [(int(G.dfirst[d + 1]), 1 if b[d] else -1, sl * G.datr[d], tp * G.datr[d], th)
           for d in np.flatnonzero(b | x) if 260 <= d < len(G.dc) - 1 and G.datr[d] > 0]
    return R.simulate(G, ent)


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    out = ["# 用其他市場訊號做黃金（IDEAS #195）＋加入 935 單倉（#196）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；訊號喺其他市場（Dukascopy H1）計、落單喺黃金；滾動前向 2009→2026；正數年只睇最近 10 年；64 組同時測，t < 3.0 標弱",
           "", "## 數據", ""]
    mk = {}
    for sym, nm in MARKETS.items():
        try:
            s = load_mkt(sym)
            mk[sym] = s
            out.append(f"- {nm}（{sym}）：{len(s[0]):,} 根 H1，{dt.datetime.fromtimestamp(int(s[0][0]), dt.timezone.utc):%Y-%m} → {dt.datetime.fromtimestamp(int(s[0][-1]), dt.timezone.utc):%Y-%m}，"
                       f"收市 {s[4][0]:.4g} → {s[4][-1]:.4g}")
        except Exception as e:                                # noqa: BLE001
            out.append(f"- {nm}（{sym}）：讀唔到（{e}），略過")
    out += ["", "## #195 各組（樣本外）", "",
            "| 市場 | 時框 | 家族 | 樣本外 | 勝率 | 基準 | 差 | t | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for tf, th, cls, per in TFS:
        Gd, Gm = cls(*gd), cls(*gm)
        Q.T_H = th; base = Q.baseline(Gd)
        for sym, s in mk.items():
            Sx = cls(*s); PR = XL.Pair(Gd, Sx, per); PM = XL.Pair(Gm, Sx, per)
            for fam, grid in FAMILIES.items():
                T = [run(PR, fam, p, th) for p in grid]
                oos, picks = P.wf_stream(lambda p, T=T, grid=grid: T[grid.index(p)], grid)
                oos = [x for x in oos if R.yr(x[0]) >= 2009]
                bw = [base[grid[picks[R.yr(x[0])]]["ex"]].get(R.yr(x[0]), (np.nan, 0))[0] for x in oos]
                rs = np.array([x[3] for x in oos]); st = R.summ(rs); sw = R.summ(R.swap_r(oos))
                win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(bw)) if bw else 0.0
                p10, _ = XL.pos10(oos)
                h1 = R.summ([x[3] for x in oos if R.yr(x[0]) <= 2017]); h2 = R.summ([x[3] for x in oos if R.yr(x[0]) >= 2018])
                mtr, cache = [], {}
                for Y, g in picks.items():
                    if g is None or Y < 2022:
                        continue
                    if g not in cache:
                        cache[g] = run(PM, fam, grid[g], th)
                    mtr += [x for x in cache[g] if R.yr(x[0]) == Y and x[0] >= P.A0]
                smt = R.summ([x[3] for x in mtr])
                ok = dict(n=st["n"] >= 200, edge=win - bwin >= 0.02, avg=st["avg"] >= 0.05, yrs10=p10 >= 6,
                          halves=h1["avg"] > 0 and h2["avg"] > 0, swap=sw["avg"] > 0, mt5=smt["n"] > 0 and smt["avg"] > 0)
                near = st["avg"] >= 0.05 and st["pf"] >= 1.15 and p10 >= 6 and smt["n"] > 0 and smt["avg"] > 0
                name = f"{tf} {MARKETS[sym]} {fam}"
                res[name] = dict(oos=oos, mt=mtr, ok=ok, near=near, s=st, picks=picks, grid=grid)
                v = ("✅" + ("（弱，t < 3.0）" if st["t"] < 3.0 else "")) if all(ok.values()) else "❌ " + "、".join(k for k, b in ok.items() if not b)
                out.append(f"| {MARKETS[sym]} | {tf} | {fam} | {st['n']} 張 {st['avg']:+.3f}R PF {st['pf']:.2f} | {win:.1%} | {bwin:.1%} | {100 * (win - bwin):+.1f}pp | "
                           f"{st['t']:.2f} | {p10}/10 | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | {smt['n']} 張 {smt['avg']:+.3f} | {v}{'；🔸候選' if near else ''} |")
                print(name, st["n"], round(st["avg"], 3), round(st["pf"], 2), p10, smt["n"], round(smt["avg"], 3), flush=True)
    passed = [k for k, r in res.items() if all(r["ok"].values())]
    cands = sorted([k for k, r in res.items() if r["near"]], key=lambda k: -res[k]["s"]["avg"])
    out += ["", f"- #195 合格：{'、'.join(passed) if passed else '冇'}", f"- #196 候選：{'、'.join(cands) if cands else '冇'}", "", "## #196 935 單倉＋候選", ""]
    if cands:
        ds, picksA = P.streams(gd); ms, _ = P.streams(gm, picksA); keys = [k for k in ds if not k.startswith("7")]
        out += ["| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 比 935 好？ |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        variants = [("935 現行", []), ("935＋全部候選", cands)] + ([(f"935＋{c}", [c]) for c in cands] if len(cands) > 1 else [])
        for label, add in variants:
            dd_ = dict(ds); mm_ = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
            for c in add:
                dd_[c] = res[c]["oos"]; mm_[c] = res[c]["mt"]
            kk = keys + add; trs = PS.single(dd_, kk); mtr = PS.single(mm_, kk)
            ok, st, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mtr); p10, _ = XL.pos10(trs)
            eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
            e1, m1, _, _ = P.equity(trs, 30000, 1.0)
            better = st["avg"] > A_SINGLE["avg"] and st["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
            out.append(f"| {label} | {st['n']} | {st['avg']:+.3f} | {st['pf']:.2f} | {st['sum']:+.1f} | {p10}/10 | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                       f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {'—' if not add else ('✅ 更好' if better else '❌')} |")
            print(label, st, p10, dd, flush=True)
        out += ["", "- 候選係睇完 #195 樣本外結果先揀（事後揀選偏差，64 組揀出更嚴重）；更好都只係提案。"]
    else:
        out.append("- 冇候選，935 維持現行。")
    out += ["", "## 合格／候選 2026 揀法", ""] + [f"- {k}：{r['grid'][r['picks'][2026]] if r['picks'].get(2026) is not None else '2026 唔做'}" for k, r in res.items() if r["near"] or all(r["ok"].values())]
    open(os.path.join(HERE, "OTHER_LEAD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
