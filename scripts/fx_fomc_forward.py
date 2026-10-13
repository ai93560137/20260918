#!/usr/bin/env python3
"""pre-FOMC 條件式美元漂移——前向紙上記錄（含 2025-09 起的回填批次）。協議：forex_research/FX_FOMC_DRIFT_FORWARD.md；規則與 scripts/fx_fomc_drift.py 相同。

    python3 scripts/fx_fomc_forward.py                 # Actions：抓雲垂分支的 ZQ（IB 日線）、Dukascopy M1（快取進 forward/fomc_m1/）、重算全部事件、寫 fomc_events.csv 與 FOMC_STATUS.md
    python3 scripts/fx_fomc_forward.py --local --zq-dir <dir>   # 本機驗證：匯率用 data_forex 的 HistData M1，ZQ 用本機目錄

每次決定性重算（不累加狀態）。事件 = 排定 FOMC 公告，t ≥ 2025-09-01。
訊號：t−3 次月 ZQ 結算 → S（基點）；|S| ≥ 12.5 才交易。視窗：t−2 → t（公告前 5 分鐘 ET）。
"""
import argparse
import csv
import gzip
import io
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fx_fomc_drift import (COST_BP, PAIRS, PRE_MIN, THRESH_BP, M1Cache, load_calendar, load_target, load_zq, settle_at, tdays_before, to_utc, tstat)  # noqa: E402

BACKFILL_START, FWD_START = date(2025, 9, 1), date(2026, 10, 13)
ZQ_HIST = ROOT / "forex_research" / "forward" / "zq_hist"
RAW = "https://raw.githubusercontent.com/ai93560137/20260918/claude/dazzling-curie-f3xzb8/data_forex_ibkr/zq/"
API = "https://api.github.com/repos/ai93560137/20260918/contents/data_forex_ibkr/zq?ref=claude/dazzling-curie-f3xzb8"
DEC = {"EURUSD": 5, "USDCHF": 5, "USDJPY": 3, "GBPUSD": 5}


def fetch_zq(tmp: Path) -> Path:
    """ZQ 日線來源：倉庫內快取 forex_research/forward/zq_hist/（雲垂 IB 各合約檔 ZQ_*.csv.gz 的副本＋上次抓到的 zq_daily.csv）
    ＋ 每天從雲垂分支以 GitHub raw 抓最新 zq_daily.csv（抓到就更新快取；抓不到就用快取並警告）。
    不再依賴 GitHub API 目錄列表——Actions 共用 IP 常撞匿名限額，2026-10-13 曾因此把全部事件誤判成 no_zq。"""
    import requests, shutil
    tmp.mkdir(parents=True, exist_ok=True)
    for f in ZQ_HIST.glob("*.csv*"):
        shutil.copy(f, tmp / f.name)
    try:
        rr = requests.get(RAW + "zq_daily.csv", timeout=60, headers={"User-Agent": "fx-fomc-forward"})
        rr.raise_for_status()
        if len(rr.content) < 40 or not rr.content.startswith(b"date,contract"):
            raise ValueError("zq_daily.csv 內容不像 CSV")
        (tmp / "zq_daily.csv").write_bytes(rr.content)
        ZQ_HIST.mkdir(parents=True, exist_ok=True)
        (ZQ_HIST / "zq_daily.csv").write_bytes(rr.content)
        src = "雲垂分支（已更新快取）"
    except Exception as exc:  # noqa: BLE001
        src = f"快取（雲垂分支抓取失敗：{exc}）"
    try:  # 雲垂若新增合約檔（ZQ_*.csv.gz），順手補進快取；API 失敗不影響
        r = requests.get(API, timeout=60, headers={"User-Agent": "fx-fomc-forward"})
        if r.ok:
            for x in r.json():
                n = x.get("name", "")
                if n.startswith("ZQ_") and n.endswith(".csv.gz") and not (ZQ_HIST / n).exists():
                    rr = requests.get(RAW + n, timeout=60)
                    if rr.ok:
                        (ZQ_HIST / n).write_bytes(rr.content); (tmp / n).write_bytes(rr.content)
    except Exception:  # noqa: BLE001
        pass
    n_files = len(list(tmp.glob("ZQ_*.csv.gz")))
    print(f"ZQ：合約檔 {n_files} 個；zq_daily 來源＝{src}")
    if n_files == 0:
        sys.exit("ZQ 合約檔 0 個——快取目錄 forex_research/forward/zq_hist/ 空了，拒絕把全部事件寫成 no_zq")
    return tmp


def zq_from_daily(path: Path, zq: dict) -> dict:
    """zq_daily.csv（date,contract,close）併入 {YYYYMM: Series}。"""
    if not path.exists():
        return zq
    d = pd.read_csv(path, dtype={"contract": str})
    if "fetched_utc" in d.columns:
        # IB 在 23:30 UTC 抓到的「隔日」日線是剛開盤 1.5 小時的半根（CME 時段 22:00 UTC 起算隔日）：
        # 只收 date ≤ 抓取日的列，免得採集中斷時把半根當結算用
        d = d[pd.to_datetime(d["date"]) <= pd.to_datetime(d["fetched_utc"]).dt.normalize()]
    for ym, g in d.groupby("contract"):
        s = pd.Series(g["close"].astype(float).values, index=pd.to_datetime(g["date"])).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        zq[ym] = pd.concat([zq.get(ym, pd.Series(dtype=float)), s]).sort_index() if ym not in zq else pd.concat([zq[ym], s[~s.index.isin(zq[ym].index)]]).sort_index()
    return zq


class DukaM1:
    """Dukascopy M1 bid（按 UTC 日快取進 forward/fomc_m1/<PAIR>_<日>.csv.gz）；缺則抓。"""
    def __init__(self, cache: Path, fetch: bool):
        self.cache, self.fetch, self.mem = cache, fetch, {}
        cache.mkdir(parents=True, exist_ok=True)

    def day(self, pair: str, d: date):
        f = self.cache / f"{pair}_{d.isoformat()}.csv.gz"
        k = (pair, d)
        if k in self.mem:
            return self.mem[k]
        if not f.exists() and self.fetch and d <= datetime.now(timezone.utc).date() - timedelta(days=1):
            from fetch_forex import Feed, Throttled
            try:
                rows = Feed(2, 1.0).candles(f"{pair}/{d.year}/{d.month - 1:02d}/{d.day:02d}/BID_candles_min_1.bi5", datetime(d.year, d.month, d.day), 10 ** DEC[pair])
            except Throttled as e:
                print(f"  限流 {pair} {d}: {e}"); rows = []
            if rows:
                with gzip.open(f, "wt", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh); w.writerow(["Time", "Close"])
                    for r in rows:
                        w.writerow([r[0], f"{r[4]:.{DEC[pair]}f}"])
        s = pd.read_csv(f, parse_dates=["Time"]).set_index("Time")["Close"] if f.exists() else pd.Series(dtype=float)
        self.mem[k] = s
        return s

    def price(self, pair: str, t_utc: pd.Timestamp):
        s = self.day(pair, t_utc.date())
        if s.empty:
            return float("nan")
        w = s[(s.index <= t_utc - pd.Timedelta(minutes=1)) & (s.index > t_utc - pd.Timedelta(minutes=11))]
        return float(w.iloc[-1]) if len(w) else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "forex_research" / "forward")
    ap.add_argument("--local", action="store_true", help="匯率用本機 HistData M1、不抓網路")
    ap.add_argument("--zq-dir", type=Path, help="本機 ZQ 目錄（--local 用）")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    zq_dir = a.zq_dir if a.local else fetch_zq(Path("/tmp/zq_remote"))
    zq = zq_from_daily(zq_dir / "zq_daily.csv", load_zq([str(zq_dir)]))
    cal = load_calendar(end=None)
    cal = cal[cal["date"] >= BACKFILL_START].reset_index(drop=True)
    target = load_target()
    px = M1Cache() if a.local else DukaM1(a.out / "fomc_m1", fetch=True)
    today = datetime.now(timezone.utc)
    rows = []
    for r in cal.itertuples():
        t = r.date
        t3, t2 = tdays_before(t, 3), tdays_before(t, 2)
        ym = f"{t.year + (1 if t.month == 12 else 0)}{(t.month % 12) + 1:02d}"
        tgt = float(target.asof(pd.Timestamp(t3)))
        settle, zflag = settle_at(zq, ym, t3)
        S = (100.0 - settle - tgt) * 100.0 if settle is not None else float("nan")
        sig = 0 if (settle is None or abs(S) < THRESH_BP) else (1 if S > 0 else -1)
        exit_t = (datetime.combine(t, r.ann_time) - timedelta(minutes=PRE_MIN)).time()
        te, tx = to_utc(t2, exit_t), to_utc(t, exit_t)
        phase = "forward" if t >= FWD_START else "backfill"
        stage = "pending_signal" if pd.Timestamp(t3) > today.replace(tzinfo=None) else ("no_zq" if settle is None else ("no_trade" if sig == 0 else ("open" if tx > today.replace(tzinfo=None) else "closed")))
        row = {"date": t.isoformat(), "phase": phase, "stage": stage, "t3": t3.isoformat(), "t2": t2.isoformat(), "next_month": ym, "target_t3": tgt,
               "zq_settle_t3": settle, "zq_flag": zflag, "S_bp": round(S, 2) if settle is not None else None, "signal": sig,
               "entry_utc": te.isoformat(), "exit_utc": tx.isoformat()}
        if sig and te <= today.replace(tzinfo=None):
            ok = True
            for p, sgn in PAIRS.items():
                pi = px.price(p, te); po = px.price(p, tx) if tx <= today.replace(tzinfo=None) else float("nan")
                row[f"{p}_in"], row[f"{p}_out"] = pi, po
                row[f"{p}_usd_bp"] = sgn * math.log(po / pi) * 1e4 if (np.isfinite(pi) and np.isfinite(po)) else float("nan")
                ok = ok and np.isfinite(pi)
            if stage == "closed" and all(np.isfinite(row[f"{p}_usd_bp"]) for p in PAIRS):
                row["dol_bp"] = float(np.mean([row[f"{p}_usd_bp"] for p in PAIRS]))
                row["dol_strat"] = sig * row["dol_bp"]
                row["eur_gross"] = sig * row["EURUSD_usd_bp"]
                row["eur_net"] = row["eur_gross"] - COST_BP
            elif stage == "closed":
                row["stage"] = "closed_missing_price"
        rows.append(row)
    ev = pd.DataFrame(rows)
    ev.to_csv(a.out / "fomc_events.csv", index=False)
    report(ev, a.out)


def report(ev: pd.DataFrame, out: Path) -> None:
    cl = ev[(ev.stage == "closed") & ev.signal.ne(0)]
    fw = cl[cl.phase == "forward"]; bf = cl[cl.phase == "backfill"]
    def blk(x):
        x = np.asarray(x, float); x = x[np.isfinite(x)]
        return (len(x), x.mean() if len(x) else float("nan"), tstat(x), (x > 0).mean() if len(x) else float("nan"), x.sum())
    L = ["# pre-FOMC 美元漂移前向狀態（自動產生，scripts/fx_fomc_forward.py）", "",
         "規則：t−3 次月 ZQ 隱含目標變動 ≥ +12.5 基點做多美元、≤ −12.5 做空；t−2 公告前 5 分鐘 ET 進、t 同時刻出；DOL = EUR/CHF/JPY/GBP 等權；EURUSD 腿淨扣 4.11 基點（M6E）。協議與監測規則見 `FX_FOMC_DRIFT_FORWARD.md`。", "",
         f"- 事件 {len(ev)}（{ev.date.min()} → {ev.date.max()}）；階段：{ev.stage.value_counts().to_dict()}",
         f"- 有訊號且已平倉：回填 {len(bf)}、前向 {len(fw)}"]
    for name, d in (("前向（2026-10-13 起，正式成績）", fw), ("回填批次（2025-09 → 2026-09，管線驗證，不是樣本外）", bf), ("合併", cl)):
        n, m, t, h, s = blk(d.dol_strat) if len(d) else (0, float("nan"), float("nan"), float("nan"), 0)
        n2, m2, t2, h2, s2 = blk(d.eur_net) if len(d) else (0, float("nan"), float("nan"), float("nan"), 0)
        L.append(f"- **{name}**：DOL 毛 {n} 筆、均 {m:+.1f} 基點、t {t:.2f}、命中 {h:.0%}、累計 {s:+.0f}；EURUSD 淨 均 {m2:+.1f}、t {t2:.2f}、累計 {s2:+.0f}")
    L += ["", "## 監測規則進度（只算前向）", "", "| 里程碑 | 條件 | 現況 |", "|---|---|---|",
          f"| 12 筆有訊號 | EURUSD 淨累計 > 0，否則停 | {len(fw)}/12，累計 {fw.eur_net.sum() if len(fw) else 0:+.0f} |",
          f"| 隨時 | 前向 EURUSD 淨累計回撤 ≤ 150 基點（論文最差單筆 −265），否則停 | — |",
          f"| 25 筆 | 報 DOL t；t ≥ 2 → 「前向支持」，否則續記 | {len(fw)}/25 |", "",
          "## 事件明細（最近 20）", "", "| 公告日 | 階段 | 狀態 | 次月 | ZQ 結算(t−3) | 目標 | S 基點 | 訊號 | DOL 毛 | EURUSD 淨 |", "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in ev.tail(20).itertuples():
        f = lambda v, d=1: ("" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:+.{d}f}")
        L.append(f"| {r.date} | {r.phase} | {r.stage} | {r.next_month} | {'' if r.zq_settle_t3 is None or pd.isna(r.zq_settle_t3) else f'{r.zq_settle_t3:.4f}'} | {r.target_t3:.3f} | {f(r.S_bp, 1) if r.S_bp is not None else ''} | {int(r.signal)} | {f(getattr(r, 'dol_strat', float('nan')))} | {f(getattr(r, 'eur_net', float('nan')))} |")
    nxt = ev[ev.stage == "pending_signal"].head(1)
    if len(nxt):
        L += ["", f"下一個事件：{nxt.iloc[0].date}（t−3 = {nxt.iloc[0].t3} 看訊號，t−2 = {nxt.iloc[0].t2} 進場）"]
    (out / "FOMC_STATUS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:12]))


if __name__ == "__main__":
    main()
