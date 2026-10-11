#!/usr/bin/env python3
"""跨發行商溢價系統化（第 5 項）：用 backtest_hist.csv（backtest_hist.py --source hkex 的輸出）回答三件事——
  1. 控制貨性（strike/forward）與年期後，各發行商窩輪相對期權公平值的溢價差多少、每月排名穩不穩；
  2. 流通量（O/S%）高的窩輪溢價是否被壓低（「發行商縮 IV」）：跨輪比較 + 同一隻輪的時間序列（固定效應）；
  3. 牛熊證：控制年期、距收回價後各發行商的財務費用（折讓點數）差多少。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "research" / "warrants_cbbc" / "backtest_hist.csv"


def load(path: Path) -> pd.DataFrame:
    use = ["code", "date", "type", "issuer", "close", "ratio", "strike", "fwd", "days", "premium_pct", "fair_pts", "iv_issuer",
           "os_pct", "turnover", "discount_pts", "dist_call_pct", "expiry", "call_level", "note"]
    df = pd.read_csv(path, usecols=use, low_memory=False, dtype={"note": str, "expiry": str, "code": str})
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")
    # 窩輪列沒填 fwd（只有牛熊證列有）：用同日牛熊證列的前月遠期價補上
    fwd_by_date = df[df["fwd"] > 0].groupby("date")["fwd"].median()
    df["fwd"] = df["fwd"].where(df["fwd"] > 0, df["date"].map(fwd_by_date))
    return df


def warrants(df: pd.DataFrame) -> str:
    w = df[df["type"].isin(["CALL", "PUT"]) & df["premium_pct"].notna() & (df["fwd"] > 0)].copy()
    w = w[w["premium_pct"].between(-50, 200)]
    w["mny"] = np.where(w["type"] == "CALL", w["strike"] / w["fwd"] - 1, 1 - w["strike"] / w["fwd"])  # >0 = 價外
    w["mny_b"] = pd.cut(w["mny"], [-1, -0.04, 0, 0.04, 0.08, 0.12, 1], labels=["ITM>4%", "ITM0-4", "OTM0-4", "OTM4-8", "OTM8-12", "OTM>12"])
    w["days_b"] = pd.cut(w["days"], [0, 30, 60, 120, 400], labels=["<30d", "30-60", "60-120", ">120"])
    w["cell"] = w["type"] + "|" + w["mny_b"].astype(str) + "|" + w["days_b"].astype(str) + "|" + w["date"].astype(str)
    med = w.groupby("cell")["premium_pct"].transform("median")
    cnt = w.groupby("cell")["premium_pct"].transform("size")
    w["dev"] = w["premium_pct"] - med
    w = w[cnt >= 3]
    traded = w[w["turnover"] > 0]
    L = [f"窩輪樣本 {len(w):,}（同日同貨性同年期 ≥3 隻才比較）；有成交 {len(traded):,}"]
    L.append("\n[1] 發行商效應：同日同貨性同年期格子內，相對格子中位的溢價偏差（百分點）")
    tab = traded.groupby("issuer").agg(n=("dev", "size"), dev_med=("dev", "median"), dev_mean=("dev", "mean"),
                                       prem_med=("premium_pct", "median"), iv_med=("iv_issuer", "median"),
                                       codes=("code", "nunique")).sort_values("dev_med")
    for iss, r in tab.iterrows():
        if r["n"] < 200:
            continue
        L.append(f"  {iss}: 偏差中位 {r['dev_med']:+5.1f}  平均 {r['dev_mean']:+5.1f}  原始溢價中位 {r['prem_med']:5.1f}%  "
                 f"發行商 IV 中位 {r['iv_med']:4.1f}  n={int(r['n']):6d}  隻數 {int(r['codes'])}")
    # 每月排名穩定度
    m = traded.groupby(["month", "issuer"])["dev"].median().unstack()
    m = m.loc[:, m.notna().sum() >= len(m) * 0.7]
    ranks = m.rank(axis=1)
    rho = [ranks.iloc[i].corr(ranks.iloc[i + 1]) for i in range(len(ranks) - 1)]
    L.append(f"  每月發行商排名 vs 下月：Spearman 平均 {np.nanmean(rho):+.2f}（{len(rho)} 對月份；{', '.join(f'{x:+.2f}' for x in rho)}）")
    L.append("  每月最便宜／最貴：")
    for mo, row in m.iterrows():
        L.append(f"    {mo}: 最便宜 {row.idxmin()}({row.min():+.1f})  最貴 {row.idxmax()}({row.max():+.1f})  差距 {row.max()-row.min():.1f} 點")
    # 選最便宜 vs 隨機：省多少溢價
    best = traded.sort_values("dev").groupby("cell").first()
    L.append(f"  每格選最便宜一隻 vs 格子中位：平均省 {(-best['dev']).mean():.1f} 個百分點溢價（相對公平值），中位 {(-best['dev']).median():.1f}")

    L.append("\n[2] 流通量（O/S%）與溢價：跨輪（同格子內偏差）")
    traded_os = traded[traded["os_pct"].notna()].copy()
    traded_os["os_b"] = pd.cut(traded_os["os_pct"], [-1, 5, 15, 30, 50, 80, 101], labels=["0-5", "5-15", "15-30", "30-50", "50-80", "80+"])
    t2 = traded_os.groupby("os_b", observed=True).agg(n=("dev", "size"), dev_med=("dev", "median"), dev_mean=("dev", "mean"),
                                                      prem=("premium_pct", "median"))
    for b, r in t2.iterrows():
        L.append(f"  O/S {b:>5}%: 偏差中位 {r['dev_med']:+5.1f}  平均 {r['dev_mean']:+5.1f}  原始溢價中位 {r['prem']:5.1f}%  n={int(r['n'])}")
    rho = traded_os["os_pct"].rank().corr(traded_os["dev"].rank())
    L.append(f"  Spearman(O/S%, 偏差) = {rho:+.3f}")
    # 同一隻輪的時間序列：去掉輪與日期固定效應後，Δos 與 Δdev
    g = traded_os.groupby("code")
    x = traded_os["os_pct"] - g["os_pct"].transform("mean")
    y = traded_os["dev"] - g["dev"].transform("mean")
    keep = g["dev"].transform("size") >= 20
    rho_fe = x[keep].rank().corr(y[keep].rank())
    beta = np.polyfit(x[keep], y[keep], 1)[0]
    L.append(f"  同一隻輪內（固定效應，≥20 日的輪）：Spearman {rho_fe:+.3f}，斜率 {beta*10:+.2f} 個百分點溢價 / 每 +10% O/S（n={int(keep.sum())}）")
    # 生命週期：掛牌後天數
    traded_os["age"] = (traded_os["date"] - traded_os.groupby("code")["date"].transform("min")).dt.days
    a_b = pd.cut(traded_os["age"], [-1, 10, 30, 60, 120, 400], labels=["0-10d", "10-30", "30-60", "60-120", ">120"])
    t3 = traded_os.groupby(a_b, observed=True)["dev"].agg(["size", "median", "mean"])
    L.append("  掛牌後天數 → 偏差中位／平均： " + "；".join(f"{b}: {r['median']:+.1f}/{r['mean']:+.1f} (n={int(r['size'])})" for b, r in t3.iterrows()))
    return "\n".join(L)


def cbbcs(df: pd.DataFrame) -> str:
    c = df[df["type"].isin(["BULL", "BEAR"]) & df["discount_pts"].notna() & (df["turnover"] > 0)].copy()
    c = c[c["discount_pts"].between(-600, 600) & (c["days"] > 0)]
    c["days_b"] = pd.cut(c["days"], [0, 60, 180, 365, 730, 2000], labels=["<2m", "2-6m", "6-12m", "1-2y", ">2y"])
    c["dist_b"] = pd.cut(c["dist_call_pct"], [0, 2, 4, 8, 15, 100], labels=["<2%", "2-4", "4-8", "8-15", ">15"])
    c["cell"] = c["type"] + "|" + c["days_b"].astype(str) + "|" + c["dist_b"].astype(str) + "|" + c["date"].astype(str)
    med = c.groupby("cell")["discount_pts"].transform("median")
    cnt = c.groupby("cell")["discount_pts"].transform("size")
    c["dev"] = c["discount_pts"] - med   # 正 = 比同類便宜（折讓更大）
    c = c[cnt >= 3]
    L = [f"\n牛熊證（有成交）樣本 {len(c):,}"]
    L.append("[3] 發行商效應：同日同方向同年期同距離格子內，折讓點數相對格子中位（正＝較便宜）")
    tab = c.groupby("issuer").agg(n=("dev", "size"), dev_med=("dev", "median"), dev_mean=("dev", "mean"),
                                  disc=("discount_pts", "median")).sort_values("dev_med", ascending=False)
    for iss, r in tab.iterrows():
        if r["n"] < 500:
            continue
        L.append(f"  {iss}: 偏差中位 {r['dev_med']:+5.1f} 點  平均 {r['dev_mean']:+5.1f}  原始折讓中位 {r['disc']:+5.0f}  n={int(r['n'])}")
    m = c.groupby(["month", "issuer"])["dev"].median().unstack()
    m = m.loc[:, m.notna().sum() >= len(m) * 0.7]
    ranks = m.rank(axis=1)
    rho = [ranks.iloc[i].corr(ranks.iloc[i + 1]) for i in range(len(ranks) - 1)]
    L.append(f"  每月排名穩定度 Spearman 平均 {np.nanmean(rho):+.2f}")
    best = c.sort_values("dev", ascending=False).groupby("cell").first()
    L.append(f"  每格選折讓最大的一隻 vs 格子中位：平均多 {best['dev'].mean():.0f} 點、中位 {best['dev'].median():.0f} 點")
    # O/S 與折讓
    co = c[c["os_pct"].notna()]
    rho = co["os_pct"].rank().corr(co["dev"].rank())
    g = co.groupby("code")
    keep = g["dev"].transform("size") >= 20
    x = (co["os_pct"] - g["os_pct"].transform("mean"))[keep]
    y = (co["dev"] - g["dev"].transform("mean"))[keep]
    L.append(f"  O/S% 與折讓偏差：跨證 Spearman {rho:+.3f}；同一隻內 Spearman {x.rank().corr(y.rank()):+.3f}，"
             f"斜率 {np.polyfit(x, y, 1)[0]*10:+.1f} 點 / 每 +10% O/S")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(CSV))
    a = ap.parse_args()
    df = load(Path(a.csv))
    print(warrants(df))
    print(cbbcs(df))


if __name__ == "__main__":
    main()
