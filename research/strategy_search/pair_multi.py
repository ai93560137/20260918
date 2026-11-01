"""[IDEAS #197] 黃金對沖／一長一短：XAUUSD 對其他市場（#195 嗰 8 個），按滾動 β 對沖（每 1 份黃金配 β 份對手，β＝過去 250 日黃金日回報對對手日回報 OLS 斜率，只用過去數據）。
殘差回報 e＝r金 − β·r對手；累計殘差＝價差 S。D1（22:00 UTC 日界，只用兩邊都有嘅日子），訊號收市判、下一日開盤入／出。
  Q1 價差回歸：z＝(S − 過去 L 日平均) ÷ 過去 L 日標準差；z > +zin → 沽金買對手（side −1），z < −zin → 買金沽對手（+1）；z 返 0／|z| > 4／滿 T 日平倉
       網格 L ∈ {20,60,120}、zin ∈ {2.0,2.5}、T ∈ {20,60}
  Q2 價差趨勢：S 比 L 日前高 → +1，低 → −1；持 20 日（到期再判）；L ∈ {20,60,120}
  Q3 對沖黃金趨勢：黃金收市 > SMA(L) → +1（買金＋沽 β 份對手），< → −1；持 20 日；L ∈ {50,100,200}（去走對手因素，只賺黃金自己嘅走勢）
回報＝side ×（金回報 − β×對手回報）佔黃金名義 %；成本：金 0.5 美元＋對手每腳點差（見 COST_BP）×|β|；隔夜成本敏感度每日 0.01% 名義。
滾動前向 4 年揀（≥ 10 張、PF ≥ 1.1，揀平均最高）測 1 年，2009→2026；MT5 對照＝券商黃金 2022-10→＋Dukascopy 對手。
判（同 #176，正數年按使用者 11-01 只睇最近 10 年）：≥ 80 張、平均 > 0、PF ≥ 1.2、最近 10 年 ≥ 6/10 年正、兩半都正、扣隔夜成本 > 0、MT5 > 0。24 組同時測。
券商有冇得做對手：EURUSD、USDJPY、原油（CL-OIL）、比特幣有；美匯指數、標普 500（券商只有 NAS100）、長債、銅冇 → 合格都只係研究參考。
用法：python3 research/strategy_search/pair_multi.py → PAIR_MULTI.md"""
import datetime as dt
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import other_lead as OL  # noqa: E402
import pair_xau_xag as PX  # noqa: E402
import robust_long as R  # noqa: E402

COST_G = 0.5
COST_BP = {"DOLLARIDXUSD": 2, "EURUSD": 0.5, "USDJPY": 0.5, "USA500IDXUSD": 1.5, "USTBONDTRUSD": 3, "LIGHTCMDUSD": 5, "BTCUSD": 8, "COPPERCMDUSD": 6}
BROKER = {"EURUSD", "USDJPY", "LIGHTCMDUSD", "BTCUSD"}
SWAP_DAY = 0.0001
FAMILIES = {
    "Q1 價差回歸": [dict(L=L, zin=z, T=T) for L, z, T in itertools.product((20, 60, 120), (2.0, 2.5), (20, 60))],
    "Q2 價差趨勢": [dict(L=L) for L in (20, 60, 120)],
    "Q3 對沖黃金趨勢": [dict(L=L) for L in (50, 100, 200)],
}
Y10 = range(2017, 2027)


def prep(days, og, cg, om, cm):
    rg = np.r_[0, np.diff(np.log(cg))]; rm = np.r_[0, np.diff(np.log(cm))]
    n = len(cg); beta = np.full(n, np.nan)
    for i in range(251, n):
        x, y = rm[i - 250:i], rg[i - 250:i]
        v = x.var()
        beta[i] = np.cov(x, y, bias=True)[0, 1] / v if v > 0 else np.nan
    e = rg - np.nan_to_num(beta) * rm
    return dict(days=days, og=og, cg=cg, om=om, cm=cm, beta=beta, S=np.cumsum(np.where(np.isnan(beta), 0, e)))


def _ret(D, a, x, side, bp):
    b = D["beta"][a - 1]
    rg = D["og"][x] / D["og"][a] - 1; rm = D["om"][x] / D["om"][a] - 1
    gross = side * (rg - b * rm)
    cost = COST_G / D["og"][a] + abs(b) * bp / 1e4
    return (int(D["days"][a]) * 86400, side, gross - cost, int(D["days"][x] - D["days"][a]))


def trades(D, fam, p, bp):
    S, n, out = D["S"], len(D["S"]), []
    st = 252
    if fam.startswith("Q1"):
        L = p["L"]; mu = np.full(n, np.nan); sd = np.full(n, np.nan)
        for i in range(st + L, n):
            w = S[i - L:i]; mu[i] = w.mean(); sd[i] = w.std()
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (S - mu) / sd
        i = st + L
        while i < n - 1:
            if np.isnan(z[i]) or abs(z[i]) < p["zin"] or np.isnan(D["beta"][i]):
                i += 1; continue
            side = -1 if z[i] > 0 else 1; a = i + 1; j = a
            while j < n - 1:
                zj = z[j]
                if (side > 0 and zj >= 0) or (side < 0 and zj <= 0) or abs(zj) > 4 or j - a + 1 >= p["T"]:
                    break
                j += 1
            x = j + 1 if j + 1 < n else j
            out.append(_ret(D, a, x, side, bp)); i = x
    else:
        L = p["L"]; i = max(st, L)
        sma = None
        if fam.startswith("Q3"):
            c = D["cg"]; cs = np.r_[0, np.cumsum(c)]; sma = np.full(n, np.nan); sma[L - 1:] = (cs[L:] - cs[:-L]) / L
        while i < n - 1:
            if np.isnan(D["beta"][i]):
                i += 1; continue
            side = (1 if S[i] > S[i - L] else -1) if sma is None else (1 if D["cg"][i] > sma[i] else -1)
            a = i + 1; x = min(a + 20, n - 1)
            if x <= a:
                break
            out.append(_ret(D, a, x, side, bp)); i = x - 1
    return out


def wf(T, years=range(2009, 2027)):
    oos, pk = [], {}
    for Y in years:
        best = None
        for gi, tr in enumerate(T):
            s = PX.summ([x[2] for x in tr if Y - 4 <= R.yr(x[0]) < Y])
            if s["n"] >= 10 and s["pf"] >= 1.1 and (best is None or s["avg"] > best[1]):
                best = (gi, s["avg"])
        pk[Y] = None if best is None else best[0]
        if best is not None:
            oos += [x for x in T[best[0]] if R.yr(x[0]) == Y]
    return oos, pk


def main():
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd); a0 = int(dt.datetime(2022, 10, 1, tzinfo=dt.timezone.utc).timestamp())
    out = ["# 黃金對沖／一長一短（IDEAS #197）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；滾動 β 對沖；回報佔黃金名義 %；滾動前向 2009→2026；正數年只睇最近 10 年；24 組同時測", "",
           "| 對手 | 家族 | 樣本外 | 近 10 年正 | 兩半 | 扣隔夜後 | MT5 | 券商有得做 | 判 |", "|---|---|---|---|---|---|---|---|---|"]
    passed = []
    for sym, nm in OL.MARKETS.items():
        try:
            m = OL.load_mkt(sym)
        except Exception as e:                                # noqa: BLE001
            out.append(f"| {nm} | — | 讀唔到（{e}） | | | | | | |"); continue
        D = prep(*PX.align(gd, m)); Dm = prep(*PX.align(gm, m)); bp = COST_BP[sym]
        med_b = float(np.nanmedian(D["beta"]))
        for fam, grid in FAMILIES.items():
            T = [trades(D, fam, p, bp) for p in grid]
            oos, pk = wf(T)
            s = PX.summ([x[2] for x in oos]); sw = PX.summ([x[2] - SWAP_DAY * x[3] for x in oos])
            yy = {}
            for x in oos:
                yy.setdefault(R.yr(x[0]), []).append(x[2])
            p10 = sum(1 for y in Y10 if y in yy and np.sum(yy[y]) > 0)
            h1 = PX.summ([x[2] for x in oos if R.yr(x[0]) <= 2017]); h2 = PX.summ([x[2] for x in oos if R.yr(x[0]) >= 2018])
            rs = []
            for Y in range(2022, 2027):
                g = pk.get(Y)
                if g is not None:
                    rs += [x[2] for x in trades(Dm, fam, grid[g], bp) if R.yr(x[0]) == Y and x[0] >= a0]
            sm = PX.summ(rs)
            ok = dict(n=s["n"] >= 80, avg=s["avg"] > 0, pf=s["pf"] >= 1.2, yrs10=p10 >= 6, halves=h1["avg"] > 0 and h2["avg"] > 0,
                      swap=sw["avg"] > 0, mt5=sm["n"] > 0 and sm["avg"] > 0)
            if all(ok.values()):
                passed.append(f"{nm} {fam}")
            out.append(f"| {nm}（β 中位 {med_b:+.2f}） | {fam} | {PX.fmt(s)} | {p10}/10 | {h1['avg'] * 100:+.2f}%／{h2['avg'] * 100:+.2f}% | {sw['avg'] * 100:+.2f}% | "
                       f"{PX.fmt(sm)} | {'有' if sym in BROKER else '冇'} | {'✅' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
            print(nm, fam, PX.fmt(s), p10, PX.fmt(sm), flush=True)
    out += ["", "## 判", "", f"- 合格：{'、'.join(passed) if passed else '冇'}",
            "- 合格只開影子前向；真倉要券商有得做對手、改程式（兩腳同時落單）＋使用者經總指揮批。", ""]
    open(os.path.join(HERE, "PAIR_MULTI.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
