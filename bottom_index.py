#!/usr/bin/env python3
"""抄底指數（量價＋廣度 6 項）四市場檢驗（stock_research/BOTTOM_INDEX_PREREG.md；登記 commit a4710445 之後寫）。

    python3 scripts/get_market_data.py --market us hk jp tw   # data_full（Release）
    python3 bottom_index.py                                    # → research/bottom_index/{us,hk,jp,tw,summary}.json

參數逐字照原文 XQ 腳本（Length 60、20 日均量 ×1.5、RSI 14、AverageIF 10 日、跌停 5 日高峰 0.7 等），唔調。
成交量一律用全市場成交額；美港日「跌停」＝單日 ≤ −10%，台股 ≤ −9.5%（2015-06-01 前 ≤ −6.5%）。
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
from newhigh_backtest import MARKETS, load_full  # noqa: E402

OUT = ROOT / "research" / "bottom_index"
L = 60
W = {"vol_low": 10, "shadow": 10, "vol_struct": 10, "div": 15, "limit_dn": 10, "adv_ratio": 10}
INDEX = {"us": "^GSPC", "hk": "^HSI", "jp": "^N225", "tw": "^TWII"}
HS = (5, 21, 63)
BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 9.9)]
SPLITS = [("2000–2012", date(2000, 1, 1), date(2012, 12, 31)), ("2013 起", date(2013, 1, 1), date(2100, 1, 1))]


def rp(x: pd.Series) -> pd.Series:
    hi, lo = x.rolling(L, min_periods=L).max(), x.rolling(L, min_periods=L).min()
    r = (x - lo) / (hi - lo) * 100
    return r.where(hi != lo, 50.0)


def rsi_wilder(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    au, ad = up.ewm(alpha=1 / n, adjust=False).mean(), dn.ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + au / ad.replace(0, np.nan))


def breadth(m: str) -> pd.DataFrame:
    base = ROOT / "data_full" / m
    loader = load_full(m)
    etf = MARKETS[m].get("etf")
    acc: dict[str, dict] = {}
    for p in sorted(base.glob("*.csv.gz")):
        t = p.name[:-7]
        if t.startswith("_") or t == etf:
            continue
        try:
            rows = loader(t)
        except FileNotFoundError:
            continue
        if len(rows) < 30:
            continue
        df = pd.DataFrame(rows).set_index("Date")
        r = df["AdjClose"] / df["AdjClose"].shift(1) - 1
        ok = (df["Close"] >= 1) & r.notna() & (r.abs() <= 0.60)
        df, r = df[ok], r[ok]
        lim = np.where([d < date(2015, 6, 1) for d in df.index], -0.065, -0.095) if m == "tw" else -0.10
        part = pd.DataFrame({"adv": (r > 0).astype(int), "dec": (r < 0).astype(int), "limdn": (r <= lim).astype(int),
                             "turn": df["Close"] * df["Volume"], "n": 1}, index=df.index)
        for k in part.columns:
            acc.setdefault(k, []).append(part[k])
    out = {k: pd.concat(v, axis=1).sum(axis=1) for k, v in acc.items()}
    return pd.DataFrame(out).sort_index()


def index_ohlc(m: str) -> pd.DataFrame:
    rows = load_full("tw")("^TWII") if m == "tw" else md.load_ohlcv(INDEX[m])
    df = pd.DataFrame(rows).set_index("Date")[["Open", "High", "Low", "Close"]]
    return df[(df["Close"] > 0) & (df["High"] >= df["Low"])]


def score(ix: pd.DataFrame, br: pd.DataFrame) -> pd.DataFrame:
    d = ix.join(br, how="inner")
    d = d[d["n"] >= 20]
    T, C, O, Hh, Lo = d["turn"], d["Close"], d["Open"], d["High"], d["Low"]
    s = pd.DataFrame(index=d.index)
    s["vol_low"] = 100 - rp(T)
    rng = Hh - Lo
    shadow = ((np.minimum(O, C) - Lo) / rng).where(rng > 0, 0.0)
    s["shadow"] = np.where((shadow >= 0.5) & (T > T.rolling(20).mean() * 1.5) & (C >= O), 100.0, 0.0)
    up, dn = (C > C.shift(1)), (C < C.shift(1))
    upv = (T * up).rolling(10).sum() / up.rolling(10).sum().replace(0, np.nan)
    dnv = (T * dn).rolling(10).sum() / dn.rolling(10).sum().replace(0, np.nan)
    ratio = (upv.fillna(0) / dnv).where(dnv > 0, 1.0)
    s["vol_struct"] = rp(ratio)
    rsi = rsi_wilder(C)
    s["div"] = np.where((Lo <= Lo.rolling(20).min()) & (rsi > rsi.rolling(20).min() * 1.02), 100.0, 0.0)
    ld = d["limdn"].astype(float)
    p = rp(ld)
    cond = (ld.rolling(5).max() >= ld.rolling(L).max() * 0.7) & (ld < ld.shift(1))
    s["limit_dn"] = np.where(cond, np.maximum(p, 70), p * 0.5)
    tot = d["adv"] + d["dec"]
    advr = (d["adv"] / tot * 100).where(tot > 0, 50.0)
    a = rp(advr)
    s["adv_ratio"] = np.where(advr > advr.shift(1), np.minimum(a + 10, 100), a)
    s["score"] = sum(s[k] * w for k, w in W.items()) / sum(W.values())
    s["close"] = C
    s["dd60"] = 1 - C / C.rolling(L).max()
    for h in HS:
        s[f"f{h}"] = C.shift(-h) / C - 1
    warm = s[list(W)].notna().all(axis=1) & s["score"].notna()
    first = warm.idxmax()
    s = s.loc[first:]
    return s.iloc[:-63] if len(s) > 63 else s.iloc[:0]


def bucket(x: float) -> int:
    for i, (a, b) in enumerate(BUCKETS):
        if a <= x < b:
            return i
    return len(BUCKETS) - 1


def events(s: pd.DataFrame, sig: str, h: int) -> list[dict]:
    hi = s["score"] >= 50
    mask = hi if sig == "S1" else (hi & hi.shift(1, fill_value=False) & hi.shift(2, fill_value=False)
                                   & ~hi.shift(3, fill_value=False))
    b = s["dd60"].map(bucket)
    ctrl = s[~hi].groupby(b[~hi])[f"f{h}"].mean()
    out, last = [], -10 ** 9
    pos = {d: i for i, d in enumerate(s.index)}
    for d in s.index[mask.to_numpy()]:
        i = pos[d]
        if i - last < h:
            continue
        f = s.at[d, f"f{h}"]
        c = ctrl.get(b.at[d])
        if f != f or c is None or c != c:
            continue
        out.append(dict(d=d, ret=float(f), ex=float(f - c), score=float(s.at[d, "score"]), dd60=float(s.at[d, "dd60"])))
        last = i
    return out


def tstat(x: list[float]) -> dict:
    a = np.array(x)
    if len(a) < 3:
        return dict(n=len(a), mean_pct=float(a.mean() * 100) if len(a) else None, t=None)
    return dict(n=len(a), mean_pct=float(a.mean() * 100), t=float(a.mean() / (a.std(ddof=1) / math.sqrt(len(a)))),
                win=float((a > 0).mean()))


def item_report(s: pd.DataFrame) -> dict:
    """各分項只報告：分項 ≥ 50（訊號型 = 100）vs 其餘嘅 21 日平均報酬差（未控制跌幅、未去重，純描述）。"""
    out = {}
    for k in W:
        a, b = s.loc[s[k] >= 50, "f21"].dropna(), s.loc[s[k] < 50, "f21"].dropna()
        out[k] = dict(days_hi=int(len(a)), mean_hi_pct=float(a.mean() * 100) if len(a) else None,
                      mean_lo_pct=float(b.mean() * 100) if len(b) else None)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    allres, pooled = {}, {}
    for m in ("us", "hk", "jp", "tw"):
        s = score(index_ohlc(m), breadth(m))
        res = dict(market=m, prereg_commit="a4710445", start=str(s.index[0]), end=str(s.index[-1]), days=len(s),
                   share_score_ge50=float((s["score"] >= 50).mean()), latest_score=float(s["score"].iloc[-1]),
                   results={}, items=item_report(s))
        for sig in ("S1", "S3"):
            for h in HS:
                ev = events(s, sig, h)
                res["results"][f"{sig}_h{h}"] = dict(all=tstat([e["ex"] for e in ev]), raw=tstat([e["ret"] for e in ev]),
                                                      splits={lab: tstat([e["ex"] for e in ev if a <= e["d"] <= b])
                                                              for lab, a, b in SPLITS})
                pooled.setdefault(f"{sig}_h{h}", []).extend([dict(e, m=m) for e in ev])
        allres[m] = res
        (OUT / f"{m}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        r = res["results"]["S1_h21"]
        print(f"{m} {res['start']}→{res['end']} 日數 {res['days']} 分數≥50 佔 {res['share_score_ge50']:.0%}："
              f"S1 h21 n={r['all']['n']} 超額 {r['all']['mean_pct']:.2f}% t {r['all']['t']:.2f}｜"
              + "｜".join(f"{k}: n={v['all']['n']} ex {v['all']['mean_pct'] if v['all']['mean_pct'] is not None else float('nan'):.2f}% "
                          f"t {v['all']['t'] if v['all']['t'] is not None else float('nan'):.2f}"
                          for k, v in res["results"].items() if k != "S1_h21"))
    summ = {}
    for k, ev in pooled.items():
        summ[k] = dict(all=tstat([e["ex"] for e in ev]),
                       splits={lab: tstat([e["ex"] for e in ev if a <= e["d"] <= b]) for lab, a, b in SPLITS},
                       by_market={m: allres[m]["results"][k]["all"] for m in allres})
    main_ = summ["S1_h21"]
    pos = sum(1 for m in allres if (main_["by_market"][m]["mean_pct"] or 0) > 0)
    t = main_["all"]["t"] or 0
    sp = all((v["mean_pct"] or 0) > 0 for v in main_["splits"].values())
    if t >= 2 and pos >= 3 and sp:
        v = "✅ 有用"
    elif (main_["all"]["mean_pct"] or 0) <= 0:
        v = "☠️ 冇用"
    else:
        v = "不確定"
    summ["verdict"] = dict(verdict=v, pooled_t=t, markets_positive=pos, splits_positive=sp,
                           s3_vs_s1_h21=dict(S1=main_["all"]["mean_pct"], S3=summ["S3_h21"]["all"]["mean_pct"]))
    summ["latest_scores"] = {m: allres[m]["latest_score"] for m in allres}
    (OUT / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for k, x in summ.items():
        if k in ("verdict", "latest_scores"):
            continue
        a = x["all"]
        print(f"合併 {k}: n={a['n']} 超額 {a['mean_pct']:.2f}% t {a['t']:.2f}｜分段 "
              + "、".join(f"{lab} {v['mean_pct']:.2f}%（t {v['t'] if v['t'] is not None else float('nan'):.2f}）" for lab, v in x["splits"].items()))
    print("判決：", summ["verdict"])


if __name__ == "__main__":
    main()
