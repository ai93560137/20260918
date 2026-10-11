#!/usr/bin/env python3
"""牛熊證重貨區強制對沖（第 1 項）：恒指跌破／升破一批牛熊證收回價時，發行商被迫平掉期指對沖，
看這股「被動流」之後 15／30／60 分鐘恒指期貨是續走還是反轉，並以被收回的對沖量分層。

資料：
  data/hkex_sp/cbbc_*_HSI.csv.gz    每日每隻流通量（O/S）、收回價、換股比率 → 前一交易日收盤的「每個收回價有多少張期指對沖」
  <k15 目錄>/YYYY-MM-DD.json         恒指期貨主連 15 分鐘 K（GCS archive/futu_k_15m/HK.HSI_FRONT/，time_key 為香港時間）
  canary/data_external/hsi_daily.csv 恒指現貨日線（算期現基差，把期貨 K 轉成現貨近似值，因為收回看的是現貨）

事件定義：日市每根 15 分鐘 K，若當根低點創當日新低（含開盤跳空：以前收為基準），把介於〔新低, 舊低〕的牛證收回價全部視為被收回，
強制沽出量 S = Σ O/S ÷ 比率 ÷ 50（張）。熊證對稱處理（新高）。回應變數：事件 K 收盤之後 1／2／4 根 K 的對數回報（以「續跌為正」的方向對齊），
以及到收市的回報。沒有觸發任何收回價的新低 K 當對照組。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from retail_flow import load_cbbc  # noqa: E402

HSI = ROOT / "canary" / "data_external" / "hsi_daily.csv"


def load_k15(k15_dir: Path, start: str, end: str) -> pd.DataFrame:
    rows = []
    for p in sorted(k15_dir.glob("*.json")):
        day = p.stem
        if not (start <= day <= end):
            continue
        try:
            bars = json.loads(p.read_text())
        except ValueError:
            continue
        for b in bars:
            rows.append({"time": pd.Timestamp(b["time_key"]), "open": b["open"], "high": b["high"], "low": b["low"],
                         "close": b["close"], "volume": b.get("volume", 0)})
    k = pd.DataFrame(rows).drop_duplicates("time").sort_values("time").reset_index(drop=True)
    k["date"] = k["time"].dt.normalize()
    k["hm"] = k["time"].dt.strftime("%H:%M")
    # 日市（現貨時段 09:30–16:00 的 K：09:30 … 15:45 開始）
    k = k[(k["hm"] >= "09:30") & (k["hm"] < "16:00")].copy()
    return k


def basis_table(k: pd.DataFrame) -> pd.Series:
    """每日基差 = 期貨 15:45 K 收盤 − 恒指現貨收盤；用前一交易日的值去轉當日 K（避免前視）。"""
    h = pd.read_csv(HSI, parse_dates=["Date"]).set_index("Date")["Close"]
    last = k[k["hm"] == "15:45"].set_index("date")["close"]
    b = (last - h.reindex(last.index)).dropna()
    return b.shift(1).ffill()


def hedge_map(cb: pd.DataFrame) -> dict:
    """{date: (bull DataFrame[call, contracts], bear DataFrame[call, contracts])}，O/S 取該日收盤（用於下一交易日）。"""
    cb = cb[(cb["os"] > 0) & cb["call"].notna() & (cb["ratio"] > 0)].copy()
    cb["contracts"] = cb["os"] / cb["ratio"] / 50.0
    out = {}
    for d, g in cb.groupby("date"):
        bull = g[g["sign"] > 0].groupby("call")["contracts"].sum().sort_index()
        bear = g[g["sign"] < 0].groupby("call")["contracts"].sum().sort_index()
        out[d] = (bull, bear)
    return out


def build_events(k: pd.DataFrame, hmap: dict, basis: pd.Series, horizons=(1, 2, 4)) -> pd.DataFrame:
    h = pd.read_csv(HSI, parse_dates=["Date"]).set_index("Date")["Close"]
    dates = sorted(k["date"].unique())
    hdates = sorted(hmap)
    ev = []
    for i, d in enumerate(dates):
        prev_h = [x for x in hdates if x < d]
        if not prev_h:
            continue
        bull, bear = hmap[prev_h[-1]]
        if d not in basis.index or pd.isna(basis.loc[d]):
            continue
        bs = float(basis.loc[d])
        g = k[k["date"] == d].reset_index(drop=True)
        if len(g) < 10:
            continue
        prev_close_spot = h[h.index < d]
        if prev_close_spot.empty:
            continue
        pc = float(prev_close_spot.iloc[-1])
        lo_spot = (g["low"] - bs).to_numpy()
        hi_spot = (g["high"] - bs).to_numpy()
        close = g["close"].to_numpy()
        logc = np.log(close)
        run_lo, run_hi = pc, pc
        day_close = logc[-1]
        for j in range(len(g)):
            new_lo, new_hi = lo_spot[j] < run_lo, hi_spot[j] > run_hi
            base = {"date": d, "time": g.loc[j, "time"], "bar": j, "gap_open": j == 0}
            fut = {f"r{hz}": (logc[j + hz] - logc[j]) if j + hz < len(g) else np.nan for hz in horizons}
            fut["r_close"] = day_close - logc[j]
            if new_lo:
                hit = bull[(bull.index >= lo_spot[j]) & (bull.index < run_lo)]
                s = float(hit.sum())
                # 方向對齊：跌破牛證 → 強制沽；「續跌」為正
                ev.append({**base, "side": "bull", "S": s, "n_levels": int(len(hit)), "move_pts": run_lo - lo_spot[j],
                           "bar_ret": logc[j] - (logc[j - 1] if j else np.log(pc + bs)),
                           **{kk: -v for kk, v in fut.items()},
                           "near_S": float(bull[(bull.index < lo_spot[j]) & (bull.index >= lo_spot[j] - 100)].sum())})
                run_lo = lo_spot[j]
            if new_hi:
                hit = bear[(bear.index <= hi_spot[j]) & (bear.index > run_hi)]
                s = float(hit.sum())
                ev.append({**base, "side": "bear", "S": s, "n_levels": int(len(hit)), "move_pts": hi_spot[j] - run_hi,
                           "bar_ret": -(logc[j] - (logc[j - 1] if j else np.log(pc + bs))),
                           **fut,
                           "near_S": float(bear[(bear.index > hi_spot[j]) & (bear.index <= hi_spot[j] + 100)].sum())})
                run_hi = hi_spot[j]
    return pd.DataFrame(ev)


def tot_outstanding(hmap: dict) -> pd.DataFrame:
    rows = [{"date": d, "bull_contracts": float(b.sum()), "bear_contracts": float(r.sum())} for d, (b, r) in hmap.items()]
    return pd.DataFrame(rows).set_index("date").sort_index()


def summarize(ev: pd.DataFrame, horizons=(1, 2, 4)) -> str:
    L = []
    cols = [f"r{h}" for h in horizons] + ["r_close"]

    def block(df, title):
        if len(df) == 0:
            L.append(f"  {title}: n=0")
            return
        parts = [f"{c}={df[c].mean()*1e4:+6.1f}bp(勝率續走 {(df[c]>0).mean():.0%})" for c in cols]
        L.append(f"  {title:<34} n={len(df):4d}  " + "  ".join(parts))

    for side in ("bull", "bear"):
        d = ev[ev["side"] == side]
        intr = d[~d["gap_open"]]
        L.append(f"\n[{'跌破牛證收回價（強制沽期指）' if side=='bull' else '升破熊證收回價（強制買期指）'}] 日內新{'低' if side=='bull' else '高'} K 共 {len(intr)} 根；"
                 f"方向對齊後正數＝沿著收回方向續走")
        block(intr[intr["S"] == 0], "對照：新低/新高但沒觸發任何收回價")
        hit = intr[intr["S"] > 0]
        if len(hit) >= 30:
            q = pd.qcut(hit["S"], 3, labels=["S 小", "S 中", "S 大"], duplicates="drop")
            for lab in q.cat.categories:
                sub = hit[q == lab]
                block(sub, f"{lab}（中位 {sub['S'].median():.0f} 張）")
            top = hit[hit["S"] >= hit["S"].quantile(0.9)]
            block(top, f"S 前 10%（≥{hit['S'].quantile(0.9):.0f} 張）")
            # 每點位強度：S ÷ 當根走幅
            hit = hit.assign(dens=hit["S"] / hit["move_pts"].clip(lower=1))
            top2 = hit[hit["dens"] >= hit["dens"].quantile(0.9)]
            block(top2, f"密度前 10%（張/點 ≥{hit['dens'].quantile(0.9):.1f}）")
            for c in cols:
                m = hit[c].notna()
                rho = hit.loc[m, "S"].rank().corr(hit.loc[m, c].rank())
                L.append(f"    Spearman(S, {c}) = {rho:+.3f}  n={int(m.sum())}")
        gap = d[d["gap_open"]]
        block(gap, "跳空開盤（第一根 K）全部")
        if len(gap) >= 20:
            block(gap[gap["S"] >= gap["S"].quantile(0.75)], "跳空且 S 前 25%")
        # 接近重貨區（下方 100 點內有 near_S 大量）但尚未觸發：磁吸或支撐？
        near = intr[(intr["S"] == 0) & (intr["near_S"] > 0)]
        if len(near) >= 30:
            hi = near[near["near_S"] >= near["near_S"].quantile(0.75)]
            lo = near[near["near_S"] <= near["near_S"].quantile(0.25)]
            block(hi, "未觸發、下一個 100 點內重貨（前 25%）")
            block(lo, "未觸發、下一個 100 點內輕貨（後 25%）")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k15", required=True, help="15 分鐘 K JSON 目錄")
    ap.add_argument("--start", default="2025-11-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--csv")
    a = ap.parse_args()
    cb = load_cbbc()
    hmap = hedge_map(cb)
    tot = tot_outstanding(hmap)
    print(f"牛熊證對沖量（張期指等值，每日收盤 O/S）：牛 中位 {tot['bull_contracts'].median():.0f}（max {tot['bull_contracts'].max():.0f}），"
          f"熊 中位 {tot['bear_contracts'].median():.0f}（max {tot['bear_contracts'].max():.0f}）")
    k = load_k15(Path(a.k15), a.start, a.end)
    print(f"15 分鐘 K：{k['date'].nunique()} 個交易日、{len(k)} 根（日市 09:30–16:00）")
    basis = basis_table(k)
    print(f"期現基差（前一日）：中位 {basis.median():+.0f} 點，IQR {basis.quantile(.25):+.0f}…{basis.quantile(.75):+.0f}")
    ev = build_events(k, hmap, basis)
    print(f"事件：{len(ev)} 根（新低 {int((ev['side']=='bull').sum())}、新高 {int((ev['side']=='bear').sum())}），"
          f"其中觸發收回價 {int((ev['S']>0).sum())} 根，觸發量合計 {ev['S'].sum():,.0f} 張")
    print(summarize(ev))
    if a.csv:
        ev.to_csv(a.csv, index=False)
        print("已寫", a.csv)


if __name__ == "__main__":
    main()
