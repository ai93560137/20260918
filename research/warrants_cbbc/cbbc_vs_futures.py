#!/usr/bin/env python3
"""長年期牛熊證 vs 同到期恒指期貨（第 4 項）：牛證隱含遠期 F_bull = K + 市價×R、熊證 F_bear = K − 市價×R，
與港交所每日報告的期指各合約月結算價（data/hkex_options/futures/hsif_*.csv.gz）按牛熊證到期月內插後比較。

  edge_bull = F_fut(T) − F_bull   > 0 ＝ 牛證比同到期期指便宜 → 買牛證 ＋ 沽該月期指，持有到期鎖 edge（被收回則最多賠緩衝區＋剩餘持有成本）
  edge_bear = F_bear − F_fut(T)   > 0 ＝ 熊證便宜 → 買熊證 ＋ 買該月期指

只看當日有成交的牛熊證（沒成交的收市價會陳舊）。資料：data/hkex_sp/cbbc_*_HSI.csv.gz。

注意：牛熊證的價金是今天付、期指不用付，所以直接比 F_cbbc 與 F_fut 會高估牛證的便宜——要扣掉價金到到期日的資金成本：
  edge_net = edge − 市價×R × rate × 剩餘日/365（--rate 預設 3.5%，港元一年期存款／HIBOR 水平）。
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from retail_flow import load_cbbc  # noqa: E402

FUT = ROOT / "data" / "hkex_options" / "futures"


def load_futures() -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in sorted(glob.glob(str(FUT / "hsif_*.csv.gz")))]
    if not frames:
        sys.exit(f"沒有期指資料：{FUT}（先用 GitHub Actions hkex-option-iv fetch --products hsif）")
    f = pd.concat(frames, ignore_index=True)
    f["date"] = pd.to_datetime(f["date"])
    f = f[f["settle"] > 0]
    # 合約到期日近似：該月倒數第二個交易日 → 用月底減 2 天即可（內插用）
    f["exp_date"] = pd.to_datetime(f["expiry"] + "-01") + pd.offsets.MonthEnd(0) - pd.Timedelta(days=2)
    return f


def fut_at(curve: pd.DataFrame, target: pd.Timestamp) -> float | None:
    """同日期指曲線 (exp_date, settle) 在 target 到期日的線性內插；超出最遠合約 → None。"""
    c = curve.sort_values("exp_date")
    x = c["exp_date"].map(pd.Timestamp.toordinal).to_numpy(float)
    y = c["settle"].to_numpy(float)
    t = float(target.toordinal())
    if t < x[0] - 40 or t > x[-1]:
        return None
    return float(np.interp(t, x, y))


def build(cb: pd.DataFrame, fut: pd.DataFrame, rate: float = 0.035) -> pd.DataFrame:
    cb = cb[(cb["volume"] > 0) & (cb["close"] > 0) & cb["strike"].notna()].copy()
    cb["maturity"] = pd.to_datetime(cb["Maturity Date"], errors="coerce")
    cb = cb[cb["maturity"].notna()]
    cb["fwd_cbbc"] = np.where(cb["sign"] > 0, cb["strike"] + cb["close"] * cb["ratio"], cb["strike"] - cb["close"] * cb["ratio"])
    rows = []
    by_date = {d: g for d, g in fut.groupby("date")}
    for d, g in cb.groupby("date"):
        curve = by_date.get(d)
        if curve is None or len(curve) < 3:
            continue
        front = float(curve.sort_values("exp_date").iloc[0]["settle"])
        for _, r in g.iterrows():
            fm = fut_at(curve, r["maturity"])
            if fm is None:
                continue
            edge = (fm - r["fwd_cbbc"]) if r["sign"] > 0 else (r["fwd_cbbc"] - fm)
            days = (r["maturity"] - d).days
            funding = r["close"] * r["ratio"] * rate * days / 365.0
            rows.append({"edge_net": edge - funding, "funding_pts": funding,"date": d, "code": r["code"], "issuer": r["issuer"], "bull": r["sign"] > 0, "maturity": r["maturity"],
                         "days": (r["maturity"] - d).days, "strike": r["strike"], "call": r["call"], "close": r["close"],
                         "ratio": r["ratio"], "fwd_cbbc": r["fwd_cbbc"], "fut_match": fm, "front": front,
                         "carry_pts": fm - front, "edge_pts": edge, "buffer": abs(r["call"] - r["strike"]),
                         "dist_call_pct": abs(front - r["call"]) / front * 100, "turnover": r["turnover"], "os_pct": r.get("% of issue still out in market *")})
    return pd.DataFrame(rows)


def report(df: pd.DataFrame) -> str:
    L = [f"樣本（有成交、到期在期指曲線範圍內）：{len(df):,} 筆，{df['code'].nunique():,} 隻，{df['date'].min().date()}→{df['date'].max().date()}"]
    df = df.copy()
    df["yr_b"] = pd.cut(df["days"], [0, 90, 365, 730, 1095, 2000], labels=["<3m", "3-12m", "1-2y", "2-3y", ">3y"])
    for bull in (True, False):
        sub = df[df["bull"] == bull]
        L.append(f"\n[{'牛證' if bull else '熊證'}] edge_pts（>0 ＝ 比同到期期指便宜）按年期：")
        t = sub.groupby("yr_b", observed=True).agg(n=("edge_pts", "size"), codes=("code", "nunique"), med=("edge_pts", "median"),
                                                  p25=("edge_pts", lambda x: x.quantile(.25)), p75=("edge_pts", lambda x: x.quantile(.75)),
                                                  carry=("carry_pts", "median"), fund=("funding_pts", "median"),
                                                  net=("edge_net", "median"), net90=("edge_net", lambda x: x.quantile(.9)),
                                                  pos=("edge_net", lambda x: (x > 30).mean()))
        for b, r in t.iterrows():
            L.append(f"  {b:>5}: n={int(r['n']):6d} 隻={int(r['codes']):4d}  edge 中位 {r['med']:+6.0f} [{r['p25']:+.0f},{r['p75']:+.0f}]  "
                     f"期指 carry {r['carry']:+5.0f}  價金資金成本 {r['fund']:5.0f}  → edge_net 中位 {r['net']:+5.0f}  P90 {r['net90']:+5.0f}  net>30 比例 {r['pos']:.0%}")
        lng = sub[sub["days"] > 365]
        if len(lng):
            L.append("  一年以上、按發行商：")
            t2 = lng.groupby("issuer").agg(n=("edge_net", "size"), med=("edge_net", "median"), p90=("edge_net", lambda x: x.quantile(.9))).sort_values("med", ascending=False)
            for iss, r in t2.iterrows():
                if r["n"] >= 30:
                    L.append(f"    {iss}: n={int(r['n'])}  edge_net 中位 {r['med']:+.0f}  P90 {r['p90']:+.0f}")
            # 最佳機會：edge_net 大且距收回價遠
            best = lng[(lng["dist_call_pct"] >= 15)].sort_values("edge_net", ascending=False).head(12)
            L.append("  一年以上、距收回價 ≥15%、edge_net 最大的 12 筆：")
            for _, r in best.iterrows():
                L.append(f"    {r['date'].date()} {int(r['code'])} {r['issuer']} 到期 {r['maturity'].date()} K={r['strike']:.0f} 收 {r['close']:.3f}×{r['ratio']:.0f} "
                         f"F_cbbc={r['fwd_cbbc']:.0f} F_fut={r['fut_match']:.0f} edge={r['edge_pts']:+.0f} 資金 {r['funding_pts']:.0f} net={r['edge_net']:+.0f} 緩衝 {r['buffer']:.0f} 成交 {r['turnover']:,.0f}")
            # 同一隻的 edge 持續性：日均 edge_net 的分佈
            lng = lng[lng["dist_call_pct"] >= 15]          # 近收回價的牛熊證 F_cbbc 被敲出機率壓低，不算便宜
            per = lng.groupby("code")["edge_net"].agg(["size", "median"])
            per = per[per["size"] >= 10]
            L.append(f"  一年以上、距收回價 ≥15%、≥10 個成交日的 {len(per)} 隻：每隻 edge_net 中位的分佈 P10 {per['median'].quantile(.1):+.0f} / 中位 {per['median'].median():+.0f} / P90 {per['median'].quantile(.9):+.0f}；"
                     f"中位 >100 點的 {int((per['median'] > 100).sum())} 隻、>300 點的 {int((per['median'] > 300).sum())} 隻")
            top = per[per["median"] > 300].sort_values("median", ascending=False).head(10)
            for code, r in top.iterrows():
                x = lng[lng["code"] == code]
                L.append(f"    {int(code)} {x['issuer'].iloc[0]} 到期 {x['maturity'].iloc[0].date()} K={x['strike'].iloc[0]:.0f}：{int(r['size'])} 個成交日，edge_net 中位 {r['median']:+.0f}，"
                         f"日均成交 {x['turnover'].median():,.0f}，最近 {x['date'].max().date()} net {x.sort_values('date')['edge_net'].iloc[-1]:+.0f}")
    # 牛＋熊同發行商同到期：F_bear − F_bull ＝ 發行商來回財務費用
    pair = df.groupby(["date", "issuer", "maturity", "bull"])["fwd_cbbc"].median().unstack("bull")
    pair = pair.dropna()
    if len(pair):
        pair["rt"] = pair[False] - pair[True]
        pair = pair.reset_index()
        pair["days"] = (pair["maturity"] - pair["date"]).dt.days
        pair["yr_b"] = pd.cut(pair["days"], [0, 90, 365, 730, 2000], labels=["<3m", "3-12m", "1-2y", ">2y"])
        L.append("\n[同發行商同到期 牛/熊 隱含遠期差 F_bear − F_bull（＝發行商來回財務費用，點）]")
        for b, r in pair.groupby("yr_b", observed=True)["rt"].agg(["size", "median"]).iterrows():
            L.append(f"  {b:>5}: n={int(r['size'])}  中位 {r['median']:+.0f}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--rate", type=float, default=0.035, help="價金資金成本年率（預設 0.035）")
    a = ap.parse_args()
    fut = load_futures()
    print(f"期指結算：{fut['date'].nunique()} 日、合約月 {sorted(fut['expiry'].unique())[-6:]} …；價金資金成本 {a.rate:.2%}")
    cb = load_cbbc()
    df = build(cb, fut, a.rate)
    print(report(df))
    if a.csv:
        df.to_csv(a.csv, index=False)


if __name__ == "__main__":
    main()
