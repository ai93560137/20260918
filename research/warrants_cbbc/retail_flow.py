#!/usr/bin/env python3
"""散戶淨流向（第 2 項）：牛熊證 / 窩輪每日「流通量變化」當作散戶淨買入，看對恒指未來 1–5 日回報有沒有預測力。

資料：data/hkex_sp/{cbbc,dwrc}_YYYYMM_HSI.csv.gz（港交所按月檔；No. Bought/Sold 是流通量提供者視角，
Sold 為負數 → 散戶淨買入 = −(Bought + Sold)），canary/data_external/hsi_daily.csv。

曝險換算：牛熊證 delta≈1 → 單位數 ÷ 換股比率 = 指數單位；窩輪用 Delta (%) 欄（= delta ÷ 比率 × 100）。
再 ÷ 50 換成期指張數等值。牛／購為正、熊／沽為負。
"""
from __future__ import annotations

import argparse
import glob
import gzip
import io
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SP = ROOT / "data" / "hkex_sp"
HSI = ROOT / "canary" / "data_external" / "hsi_daily.csv"


def _read(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rb") as f:
        raw = f.read()
    if not raw.strip():
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(raw))


def load_cbbc() -> pd.DataFrame:
    frames = [_read(Path(p)) for p in sorted(glob.glob(str(SP / "cbbc_*_HSI.csv.gz")))]
    df = pd.concat([f for f in frames if len(f)], ignore_index=True)
    df = df.rename(columns={
        "CBBC Code": "code", "Trade Date": "date", "No. of CBBC Bought *": "lp_bought",
        "No. of CBBC Sold *": "lp_sold", "No. of CBBC still out in market *": "os",
        "Ent. Ratio^": "ratio", "Bull/Bear": "bb", "Closing Price": "close", "Turnover": "turnover",
        "Call Level": "call", "Strike Level": "strike", "Issuer": "issuer", "Volume": "volume",
    })
    df["date"] = pd.to_datetime(df["date"])
    for c in ("lp_bought", "lp_sold", "os", "ratio", "close", "turnover", "volume", "call"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["sign"] = np.where(df["bb"].astype(str).str.lower().str.startswith("bull"), 1.0, -1.0)
    df["retail_net_units"] = -(df["lp_bought"].fillna(0) + df["lp_sold"].fillna(0))
    df["idx_units"] = df["retail_net_units"] / df["ratio"]
    return df


def load_dwrc() -> pd.DataFrame:
    frames = [_read(Path(p)) for p in sorted(glob.glob(str(SP / "dwrc_*_HSI.csv.gz")))]
    df = pd.concat([f for f in frames if len(f)], ignore_index=True)
    df = df.rename(columns={
        "Warrant Code": "code", "Trade Date": "date", "No. of Warrants Bought *": "lp_bought",
        "No. of Warrants Sold *": "lp_sold", "No. of Warrants still out in market *": "os",
        "Ent. Ratio^": "ratio", "Call/Put": "cp", "Delta (%)": "delta_pct", "Closing Price": "close",
        "Turnover": "turnover", "Volume": "volume", "Issuer": "issuer",
    })
    df["date"] = pd.to_datetime(df["date"])
    for c in ("lp_bought", "lp_sold", "os", "ratio", "delta_pct", "close", "turnover", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["retail_net_units"] = -(df["lp_bought"].fillna(0) + df["lp_sold"].fillna(0))
    # Delta (%) = delta / ratio × 100；沽輪 delta 為負（若檔案給正值則補上符號）
    d = df["delta_pct"].fillna(0) / 100.0
    is_put = df["cp"].astype(str).str.lower().str.startswith("put")
    d = np.where(is_put & (d > 0), -d, d)
    df["idx_units"] = df["retail_net_units"] * d
    df["sign"] = np.where(is_put, -1.0, 1.0)
    return df


def check_identity(cb: pd.DataFrame) -> str:
    """驗證 −(Bought+Sold) ≈ ΔO/S（同一隻、相鄰交易日）。"""
    g = cb.sort_values(["code", "date"]).groupby("code")
    d_os = g["os"].diff()
    ok = (d_os - cb.sort_values(["code", "date"])["retail_net_units"]).abs()
    ok = ok[d_os.notna()]
    frac = float((ok <= 1).mean()) if len(ok) else float("nan")
    return f"ΔO/S 與 −(Bought+Sold) 相符比例：{frac:.1%}（{len(ok):,} 筆）"


def daily_flow(cb: pd.DataFrame, dw: pd.DataFrame) -> pd.DataFrame:
    def agg(df, label):
        exp = (df["idx_units"] * df["sign"]).where(df["idx_units"].notna(), 0.0) if label == "cbbc" else df["idx_units"]
        tmp = pd.DataFrame({"date": df["date"], "exp": exp, "turn": df["turnover"].fillna(0),
                            "long": np.where(df["sign"] > 0, df["idx_units"].abs() * np.sign(df["retail_net_units"]), 0.0),
                            "short": np.where(df["sign"] < 0, df["idx_units"].abs() * np.sign(df["retail_net_units"]), 0.0)})
        out = tmp.groupby("date").agg(exp=("exp", "sum"), turn=("turn", "sum"), long=("long", "sum"), short=("short", "sum"))
        out.columns = [f"{label}_{c}" for c in out.columns]
        return out
    f = agg(cb, "cbbc").join(agg(dw, "dw"), how="outer").fillna(0.0)
    # 期指張數等值：指數單位 ÷ 50
    for c in ("cbbc_exp", "dw_exp", "cbbc_long", "cbbc_short", "dw_long", "dw_short"):
        f[c] = f[c] / 50.0
    f["total_exp"] = f["cbbc_exp"] + f["dw_exp"]
    return f


def with_returns(f: pd.DataFrame, horizons=(1, 2, 3, 5, 10)) -> pd.DataFrame:
    h = pd.read_csv(HSI, parse_dates=["Date"]).set_index("Date")["Close"]
    h = h[h.index >= f.index.min() - pd.Timedelta(days=40)]
    df = f.join(h.rename("hsi"), how="left")
    df = df[df["hsi"].notna()]
    df["r0"] = np.log(df["hsi"]).diff()  # 當日回報（同期）
    for k in horizons:
        df[f"r{k}"] = np.log(df["hsi"].shift(-k) / df["hsi"])
    for c in ("cbbc_exp", "dw_exp", "total_exp"):
        roll = df[c].rolling(20, min_periods=10)
        df[f"{c}_z"] = (df[c] - roll.mean()) / roll.std()
    return df


def spearman(x: pd.Series, y: pd.Series):
    m = x.notna() & y.notna()
    if m.sum() < 10:
        return float("nan"), int(m.sum())
    return float(x[m].rank().corr(y[m].rank())), int(m.sum())


def boot_ci(x: pd.Series, y: pd.Series, n=2000, seed=0):
    m = x.notna() & y.notna()
    xs, ys = x[m].rank().to_numpy(), y[m].rank().to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(xs), (n, len(xs)))
    vals = [np.corrcoef(xs[i], ys[i])[0, 1] for i in idx]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def report(df: pd.DataFrame, horizons=(1, 2, 3, 5, 10)) -> str:
    lines = []
    lines.append(f"樣本：{df.index.min().date()} → {df.index.max().date()}，{len(df)} 個交易日")
    lines.append(f"日均散戶淨流向（期指張數等值）：牛熊證 {df['cbbc_exp'].mean():+.0f}（std {df['cbbc_exp'].std():.0f}），"
                 f"窩輪 {df['dw_exp'].mean():+.0f}（std {df['dw_exp'].std():.0f}）")
    for sig in ("cbbc_exp", "dw_exp", "total_exp"):
        lines.append(f"\n[{sig}] 原值 → Spearman 與未來 k 日恒指回報（括號：bootstrap 95% CI）")
        rho0, n0 = spearman(df[sig], df["r0"])
        lines.append(f"  同日 r0：rho={rho0:+.3f} n={n0}   （流向與當天回報同向＝追價；反向＝接貨）")
        for k in horizons:
            rho, n = spearman(df[sig], df[f"r{k}"])
            lo, hi = boot_ci(df[sig], df[f"r{k}"])
            flag = " ★" if (lo > 0 or hi < 0) else ""
            lines.append(f"  r{k:<2}: rho={rho:+.3f} [{lo:+.3f},{hi:+.3f}] n={n}{flag}")
        zc = f"{sig}_z"
        lines.append(f"  z 分數（20 日）五分位 → 未來 5 日平均回報(bp) / 未來 1 日(bp)：")
        sub = df[df[zc].notna()].copy()
        if len(sub) >= 25:
            sub["q"] = pd.qcut(sub[zc], 5, labels=False, duplicates="drop")
            tab = sub.groupby("q").agg(n=("r5", "size"), r1=("r1", "mean"), r5=("r5", "mean"), r10=("r10", "mean"))
            for q, row in tab.iterrows():
                lines.append(f"    Q{int(q)+1}: n={int(row['n']):3d}  r1={row['r1']*1e4:+6.0f}  r5={row['r5']*1e4:+6.0f}  r10={row['r10']*1e4:+6.0f}")
            # 極端日：z>1.5（散戶狂買牛） vs z<-1.5（狂買熊）
            hot = sub[sub[zc] > 1.5]; cold = sub[sub[zc] < -1.5]
            lines.append(f"    z>+1.5（狂買牛/購）n={len(hot)}: r1={hot['r1'].mean()*1e4:+.0f} r5={hot['r5'].mean()*1e4:+.0f} 勝率(r5<0)={(hot['r5']<0).mean():.0%}")
            lines.append(f"    z<−1.5（狂買熊/沽）n={len(cold)}: r1={cold['r1'].mean()*1e4:+.0f} r5={cold['r5'].mean()*1e4:+.0f} 勝率(r5>0)={(cold['r5']>0).mean():.0%}")
    # 簡單策略：隔日反向持有 k 日（z 為信號，每天按 −sign(z) 持倉，重疊）
    lines.append("\n[策略] 每日以 −sign(total_exp_z) 持有 1 日（反向散戶）：")
    sub = df[df["total_exp_z"].notna()]
    pos = -np.sign(sub["total_exp_z"])
    pnl = pos * sub["r1"]
    lines.append(f"  日均 {pnl.mean()*1e4:+.1f}bp，年化 Sharpe≈{pnl.mean()/pnl.std()*np.sqrt(250):+.2f}，n={pnl.notna().sum()}，"
                 f"買入持有同期 {sub['r1'].mean()*1e4:+.1f}bp/日")
    pos2 = np.sign(sub["total_exp_z"])
    pnl2 = pos2 * sub["r1"]
    lines.append(f"  同向跟隨散戶：日均 {pnl2.mean()*1e4:+.1f}bp，Sharpe≈{pnl2.mean()/pnl2.std()*np.sqrt(250):+.2f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="輸出每日流向 CSV")
    a = ap.parse_args()
    cb, dw = load_cbbc(), load_dwrc()
    print(f"牛熊證 {len(cb):,} 筆 / 窩輪 {len(dw):,} 筆")
    print(check_identity(cb))
    f = daily_flow(cb, dw)
    df = with_returns(f)
    print(report(df))
    if a.csv:
        df.to_csv(a.csv)
        print("已寫", a.csv)


if __name__ == "__main__":
    main()
