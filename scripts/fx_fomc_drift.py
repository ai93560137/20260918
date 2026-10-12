#!/usr/bin/env python3
"""pre-FOMC 條件式美元漂移（Karnaukh 2020）回測。登記：forex_research/FX_FOMC_DRIFT_BACKTEST.md（規則寫死，程式照登記實作）。

    python3 scripts/fx_fomc_drift.py --selftest                        # 人造數據迴歸測試（不碰真實 ZQ）
    python3 scripts/fx_fomc_drift.py --check --zq <dir...>             # 跑數前機制檢查：ZQ 覆蓋、訊號數、匯率時點可用性（不算報酬）
    python3 scripts/fx_fomc_drift.py --zq <dir...> --out forex_research/fx_fomc_drift   # 正式跑數（只跑一次）

訊號：t−3（美國交易日）次月 ZQ 結算 → S = (100 − settle) − target_{t−3}，基點；S ≥ +12.5 多美元、≤ −12.5 空美元、否則不交易。
視窗：t−2 的「公告時間 − 5 分鐘」(ET) 進場 → t 的同一時刻出場。DOL = EUR、CHF、JPY、GBP 四貨幣 log 中價報酬等權（正＝美元升值）。
EURUSD 腿：毛 = −sign × Δln(EURUSD) × 1e4；淨 = 毛 − 4.11。
ZQ 檔：FirstRate 個別合約（檔名含 ZQ<月碼><yy>，欄 timestamp,...,close）或 IB `ZQ_YYYYMM.csv.gz`（Time,...,Close）；日線 close 視為結算價。
"""
import argparse
import glob
import gzip
import json
import math
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar, GoodFriday, AbstractHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

ROOT = Path(__file__).resolve().parent.parent
ET = ZoneInfo("America/New_York")
PAIRS = {"EURUSD": -1, "USDCHF": +1, "USDJPY": +1, "GBPUSD": -1}      # 美元報酬符號：報價是 USD/外幣 → −Δln；外幣/USD → +Δln
MONTH_CODE = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
THRESH_BP, COST_BP, PRE_MIN = 12.5, 4.11, 5
START, END = "2003-08-01", "2026-08-31"


class CMECal(AbstractHolidayCalendar):
    rules = USFederalHolidayCalendar.rules + [GoodFriday]


BDAY = CustomBusinessDay(calendar=CMECal())


def tdays_before(d: date, n: int) -> date:
    return (pd.Timestamp(d) - n * BDAY).date()


# ---------- 數據 ----------
def load_calendar(end: str = END) -> pd.DataFrame:
    """排定 FOMC 公告（scheduled=1）；end 預設回測終點，前向傳 None 取全部（含未來）。"""
    c = pd.read_csv(ROOT / "data_forex_rates" / "fomc" / "fomc_announcements.csv", dtype=str)
    c = c[c["scheduled"] == "1"].copy()
    c["date"] = pd.to_datetime(c["date"]).dt.date
    c["ann_time"] = [parse_time(a) or rule_to_time(b) for a, b in zip(c["statement_time_et"].fillna(""), c["statement_time_rule"].fillna("14:00"))]
    hi = pd.Timestamp(end).date() if end else date(2099, 12, 31)
    return c[(c["date"] >= pd.Timestamp(START).date()) & (c["date"] <= hi)].reset_index(drop=True)


def parse_time(s: str):
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m", s, re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return time(h, mi)


def rule_to_time(s: str) -> time:
    h, mi = s.split(":")
    return time(int(h), int(mi))


def load_target() -> pd.Series:
    d = ROOT / "data_forex_rates" / "info"
    t = pd.read_csv(d / "DFEDTAR.csv", parse_dates=["Date"]).set_index("Date")["Value"]
    u = pd.read_csv(d / "DFEDTARU.csv", parse_dates=["Date"]).set_index("Date")["Value"]
    lo = pd.read_csv(d / "DFEDTARL.csv", parse_dates=["Date"]).set_index("Date")["Value"]
    mid = ((u + lo) / 2).dropna()
    s = pd.concat([t[t.index < mid.index.min()], mid]).sort_index()
    idx = pd.date_range(s.index.min(), max(pd.Timestamp(END), pd.Timestamp.today().normalize()) + pd.Timedelta(days=400))
    return s.reindex(idx).ffill()


def load_zq(dirs: list[str]) -> dict[str, pd.Series]:
    """{YYYYMM: Series(date → settle)}；FirstRate 個別合約與 IB 檔都吃；同月兩來源都有時 FirstRate 優先、IB 補缺。"""
    out: dict[str, pd.Series] = {}
    for d in dirs:
        for f in sorted(glob.glob(str(Path(d) / "**" / "*"), recursive=True)):
            name = Path(f).name
            if Path(f).is_dir() or "continuous" in name.lower() or "sample" in name.lower() or "_status" in name or "_probe" in name:
                continue
            m = re.search(r"ZQ_(\d{6})\.csv", name) or None
            key = m.group(1) if m else None
            if key is None:
                m = re.search(r"ZQ([FGHJKMNQUVXZ])(\d{2})", name)
                if not m:
                    continue
                key = f"20{m.group(2)}{MONTH_CODE[m.group(1)]:02d}"
            try:
                df = pd.read_csv(f, compression="gzip" if name.endswith(".gz") else None)
            except Exception as e:
                print(f"  略過 {name}: {e!r}"); continue
            cols = {c.lower(): c for c in df.columns}
            tcol = cols.get("time") or cols.get("timestamp") or cols.get("date")
            ccol = cols.get("close")
            if not (tcol and ccol):
                continue
            s = pd.Series(df[ccol].values, index=pd.to_datetime(df[tcol]).dt.normalize()).sort_index()
            s = s[~s.index.duplicated(keep="last")].astype(float)
            s = s[s > 0]
            is_ib = name.startswith("ZQ_")
            if key in out:
                old = out[key]
                s = pd.concat([old[~old.index.isin(s.index)], s]).sort_index() if not is_ib else pd.concat([old, s[~s.index.isin(old.index)]]).sort_index()
            out[key] = s
    return out


def settle_at(zq: dict[str, pd.Series], ym: str, d: date, lookback: int = 3):
    s = zq.get(ym)
    if s is None:
        return None, "no_contract"
    lo = pd.Timestamp(tdays_before(d, lookback))
    w = s[(s.index <= pd.Timestamp(d)) & (s.index >= lo)]
    if w.empty:
        return None, "no_settle"
    return float(w.iloc[-1]), ("" if w.index[-1] == pd.Timestamp(d) else f"settle_lag_{(pd.Timestamp(d) - w.index[-1]).days}d")


# ---------- 匯率 ----------
LON = ZoneInfo("Europe/London")


def hd_dst_fix(df: pd.DataFrame) -> pd.DataFrame:
    """HistData 年檔（2019 起）在「美國已夏令、歐洲未夏令」的錯位週（3 月第二個週日 → 3 月最後週日；10 月最後週日 → 11 月第一個週日）
    原始時間戳仍是 UTC−5，倉庫以 America/New_York 轉 UTC 後標籤早 1 小時（DATA_QC.md 2026-10-12 補充；FOMC 公告尖峰與週五收市皆驗證）。
    這裡把那些週的標籤加 60 分鐘；Dukascopy 檔不經此函數。"""
    if df.empty or df.Time.dt.year.max() < 2019:
        return df
    days = pd.DatetimeIndex(df.Time.dt.normalize().unique())
    noon = days + pd.Timedelta(hours=12)
    us = np.array([bool(t.tz_localize("UTC").tz_convert(ET).dst()) for t in noon])
    eu = np.array([bool(t.tz_localize("UTC").tz_convert(LON).dst()) for t in noon])
    bad = set(days[us & ~eu & (days.year >= 2019)])
    if not bad:
        return df
    m = df.Time.dt.normalize().isin(bad)
    df = df.copy()
    df.loc[m, "Time"] = df.loc[m, "Time"] + pd.Timedelta(minutes=60)
    return df


class M1Cache:
    def __init__(self):
        self.c = {}

    def series(self, pair: str, year: int) -> pd.Series:
        k = (pair, year)
        if k not in self.c:
            d = ROOT / "data_forex" / pair
            f = d / f"{pair}_M1_{year}.csv.gz"
            parts = []
            if f.exists():
                parts.append(hd_dst_fix(pd.read_csv(f, usecols=["Time", "Close"], parse_dates=["Time"])))
            fr = d / f"{pair}_M1_recent.csv.gz"
            if fr.exists():
                r = pd.read_csv(fr, usecols=["Time", "Close"], parse_dates=["Time"])
                parts.append(r[r.Time.dt.year == year])
            s = pd.concat(parts).drop_duplicates("Time", keep="last").set_index("Time")["Close"].sort_index() if parts else pd.Series(dtype=float)
            if len(self.c) > 12:
                self.c.pop(next(iter(self.c)))
            self.c[k] = s
        return self.c[k]

    def fill(self, pair: str, d: date):
        """缺價日的 Dukascopy M1 補抓檔（data_forex_rates/fomc/m1_fill/<PAIR>_<日>.csv.gz）；有則優先於 HistData。"""
        f = ROOT / "data_forex_rates" / "fomc" / "m1_fill" / f"{pair}_{d.isoformat()}.csv.gz"
        if not f.exists():
            return None
        k = ("fill", pair, d)
        if k not in self.c:
            self.c[k] = pd.read_csv(f, usecols=["Time", "Close"], parse_dates=["Time"]).set_index("Time")["Close"].sort_index()
        return self.c[k]

    def price(self, pair: str, t_utc: pd.Timestamp):
        """t 之前最後一根 M1 的收市（標籤 + 1 分 ≤ t），且不早於 t − 10 分鐘。來源優先序：Dukascopy 補抓檔（僅缺價日）→ HistData 年檔。"""
        hi = t_utc - pd.Timedelta(minutes=1)
        lo = t_utc - pd.Timedelta(minutes=11)
        for s in (self.fill(pair, t_utc.date()), self.series(pair, t_utc.year)):
            if s is None or s.empty:
                continue
            w = s[(s.index <= hi) & (s.index > lo)]
            if len(w):
                return float(w.iloc[-1])
        return float("nan")


def to_utc(d: date, t: time) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(d, t, tzinfo=ET).astimezone(ZoneInfo("UTC"))).tz_localize(None)


# ---------- 核心 ----------
def build_events(cal: pd.DataFrame, target: pd.Series, zq: dict | None, m1: M1Cache, check_only: bool = False, window_shift: int = 0) -> pd.DataFrame:
    rows = []
    for r in cal.itertuples():
        t = r.date
        t3, t2 = tdays_before(t, 3 + window_shift), tdays_before(t, 2 + window_shift)
        t_exit = tdays_before(t, window_shift) if window_shift else t
        ym = f"{t.year + (1 if t.month == 12 else 0)}{(t.month % 12) + 1:02d}"
        tgt = float(target.asof(pd.Timestamp(t3)))
        settle, zflag = (None, "no_zq") if zq is None else settle_at(zq, ym, t3)
        S = (100.0 - settle - tgt) * 100.0 if settle is not None else float("nan")
        sig = 0 if (settle is None or abs(S) < THRESH_BP) else (1 if S > 0 else -1)
        exit_t = (datetime.combine(t, r.ann_time) - timedelta(minutes=PRE_MIN)).time()
        te, tx = to_utc(t2, exit_t), to_utc(t_exit, exit_t)
        row = {"date": t.isoformat(), "t3": t3.isoformat(), "t2": t2.isoformat(), "next_month": ym, "target_t3": tgt, "zq_settle_t3": settle, "zq_flag": zflag,
               "S_bp": round(S, 2) if settle is not None else None, "signal": sig, "ann_time_et": r.ann_time.strftime("%H:%M"), "entry_utc": te.isoformat(), "exit_utc": tx.isoformat()}
        px_ok = True
        for p, sgn in PAIRS.items():
            a, b = m1.price(p, te), m1.price(p, tx)
            row[f"{p}_in"], row[f"{p}_out"] = a, b
            if not (np.isfinite(a) and np.isfinite(b)):
                px_ok = False
            row[f"{p}_usd_bp"] = sgn * math.log(b / a) * 1e4 if (np.isfinite(a) and np.isfinite(b)) else float("nan")
        row["px_ok"] = px_ok
        if check_only:
            for p in PAIRS:
                row.pop(f"{p}_usd_bp", None)
        else:
            row["dol_bp"] = float(np.mean([row[f"{p}_usd_bp"] for p in PAIRS])) if px_ok else float("nan")
            row["eur_usd_bp"] = row["EURUSD_usd_bp"]
            row["dol_strat"] = sig * row["dol_bp"] if sig else 0.0
            row["eur_gross"] = sig * row["eur_usd_bp"] if sig else 0.0
            row["eur_net"] = row["eur_gross"] - COST_BP if sig else 0.0
            tgt_after = float(target.asof(pd.Timestamp(t) + pd.Timedelta(days=1)))
            row["realized_change_bp"] = round((tgt_after - float(target.asof(pd.Timestamp(t) - pd.Timedelta(days=1)))) * 100, 1)
        rows.append(row)
    return pd.DataFrame(rows)


def tstat(x) -> float:
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def summarize(ev: pd.DataFrame, seed: int = 20261012) -> dict:
    sg = ev[(ev.signal != 0) & ev.px_ok].copy()
    post = sg[sg.date >= "2016-01-01"]
    out = {"n_scheduled": int(len(ev)), "n_signal": int(len(sg)), "n_long_usd": int((sg.signal > 0).sum()), "n_short_usd": int((sg.signal < 0).sum()),
           "n_no_zq": int((ev.zq_flag.isin(["no_contract", "no_settle", "no_zq"])).sum()), "n_px_missing": int((~ev.px_ok).sum())}
    def blk(x):
        x = np.asarray(x, float); x = x[np.isfinite(x)]
        return {"n": int(len(x)), "mean": float(x.mean()) if len(x) else None, "sd": float(x.std(ddof=1)) if len(x) > 1 else None, "t": tstat(x),
                "hit": float((x > 0).mean()) if len(x) else None, "worst": float(x.min()) if len(x) else None, "best": float(x.max()) if len(x) else None, "sum": float(x.sum())}
    out["H1_dol_gross"] = blk(sg.dol_strat)
    out["H2_eur_net"] = blk(sg.eur_net)
    out["H2_eur_gross"] = blk(sg.eur_gross)
    out["H2_post2016_eur_net"] = blk(post.eur_net)
    out["H1_post2016_dol"] = blk(post.dol_strat)
    out["legs"] = {"long_usd_dol": blk(sg[sg.signal > 0].dol_strat), "short_usd_dol": blk(sg[sg.signal < 0].dol_strat),
                   "long_usd_eur_net": blk(sg[sg.signal > 0].eur_net), "short_usd_eur_net": blk(sg[sg.signal < 0].eur_net)}
    ex = sg[~sg.date.isin(["2008-10-29", "2008-12-16"])]
    out["H1_excl_2008_outliers"] = blk(ex.dol_strat)
    ns = ev[(ev.signal == 0) & ev.px_ok & ev.S_bp.notna()]
    out["no_signal_dol"] = blk(ns.dol_bp)
    if len(sg) > 3:
        x, y = sg.S_bp.values.astype(float), sg.dol_bp.values.astype(float)
        X = np.column_stack([np.ones(len(x)), x]); beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
        yhat = X @ beta; r2 = 1 - ((y - yhat) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        se = math.sqrt(((y - yhat) ** 2).sum() / (len(x) - 2) / ((x - x.mean()) ** 2).sum())
        out["regression_dol_on_S"] = {"slope": float(beta[1]), "t": float(beta[1] / se), "r2": float(r2), "n": int(len(x))}
    sgn = sg.signal.values.astype(float); dol = sg.dol_bp.values.astype(float)
    if len(sg) > 3:
        rng = np.random.default_rng(seed); obs = tstat(sgn * dol)
        perm = np.array([tstat(rng.choice([-1, 1], size=len(sgn)) * dol) for _ in range(1000)])
        out["permutation"] = {"t_obs": obs, "pct_rank": float((perm < obs).mean()), "p_one_sided": float((perm >= obs).mean())}
    hit = sg[sg.realized_change_bp.notna()]
    out["signal_vs_realized"] = {"n": int(len(hit)), "direction_match": float(((np.sign(hit.realized_change_bp) == hit.signal) | ((hit.realized_change_bp == 0) & False)).mean()) if len(hit) else None}
    out["by_year_eur_net"] = {str(y): float(v) for y, v in sg.groupby(pd.to_datetime(sg.date).dt.year).eur_net.sum().items()}
    out["by_year_n"] = {str(y): int(v) for y, v in sg.groupby(pd.to_datetime(sg.date).dt.year).size().items()}
    return out


def verdict(s: dict) -> str:
    t1 = s["H1_dol_gross"]["t"]; h2 = s["H2_eur_net"]; p = s["H2_post2016_eur_net"]
    if s["n_signal"] < 25:
        return "樣本不足（有訊號事件 < 25）：🔍 待續"
    h2ok = (h2["mean"] or 0) > 0 and (h2["t"] or 0) >= 1.5 and (p["mean"] or 0) > 0
    if t1 >= 2.5 and h2ok:
        return "✅（H1 t ≥ 2.5 且 H2 過）"
    if t1 >= 1.5 or (t1 >= 2.5 and not h2ok):
        return "🔍" + ("（H1 過但 H2 不過）" if t1 >= 2.5 else "（H1 1.5–2.5）")
    return "☠️（H1 t < 1.5）"


# ---------- 自測與檢查 ----------
def selftest() -> None:
    """人造：四貨幣在視窗內讓美元升 X 基點、訊號 +20 → dol_strat 應 = X；訊號 −20 → −X；|S|<12.5 → 0。不讀任何真實 ZQ。"""
    cal = load_calendar().head(6).copy()
    target = load_target()
    X = 37.0
    class FakeM1(M1Cache):
        """進場日（t−2）給基準價，出場日（公告日）給美元升 X 基點後的價。"""
        exit_dates: set = set()
        def price(self, pair, t_utc):
            base = {"EURUSD": 1.1, "USDCHF": 0.9, "USDJPY": 110.0, "GBPUSD": 1.3}[pair]
            k = PAIRS[pair] * X / 1e4
            return base * math.exp(k) if t_utc.date() in self.exit_dates else base
    fm = FakeM1(); fm.exit_dates = {pd.Timestamp(d).date() for d in cal.date}
    # 人造 ZQ：三個事件給 +20（做多美元）、兩個 −20、一個 0
    zq = {}
    for i, r in enumerate(cal.itertuples()):
        t3 = tdays_before(r.date, 3); ym = f"{r.date.year + (1 if r.date.month == 12 else 0)}{(r.date.month % 12) + 1:02d}"
        tgt = float(target.asof(pd.Timestamp(t3))); S = [20, 20, 20, -20, -20, 0][i]
        zq[ym] = pd.Series([100 - tgt - S / 100], index=[pd.Timestamp(t3)])
    ev = build_events(cal, target, zq, fm)
    got = [round(v, 6) for v in ev.dol_strat]      # 美元固定升 X：多美元 +X、空美元 −X、無訊號 0
    want = [X, X, X, -X, -X, 0.0]
    assert got == want, (got, want)
    assert all(abs(v - X) < 1e-6 for v in ev.dol_bp), ev.dol_bp.tolist()
    assert list(ev.signal) == [1, 1, 1, -1, -1, 0]
    assert abs(ev.eur_net.iloc[0] - (X - COST_BP)) < 1e-6
    print("✅ selftest 通過：視窗報酬 = 人造漂移、訊號門檻、方向與成本正確", ev[["date", "S_bp", "signal", "dol_bp", "dol_strat", "eur_net"]].to_string(index=False))


def check(zq_dirs: list[str] | None) -> None:
    cal = load_calendar(); target = load_target(); m1 = M1Cache()
    zq = load_zq(zq_dirs) if zq_dirs else None
    if zq:
        keys = sorted(zq); print(f"ZQ 合約 {len(keys)} 個：{keys[0]} → {keys[-1]}；缺月：{[k for k in (f'{y}{m:02d}' for y in range(int(keys[0][:4]), int(keys[-1][:4])+1) for m in range(1,13)) if keys[0] <= k <= keys[-1] and k not in zq]}")
        for k in keys[:3] + keys[-3:]:
            s = zq[k]; print(f"  {k}: {len(s)} 日 {s.index.min().date()} → {s.index.max().date()} 範圍 {s.min():.3f}–{s.max():.3f}")
    ev = build_events(cal, target, zq, m1, check_only=True)
    print(f"排定會議 {len(ev)}（{ev.date.min()} → {ev.date.max()}）；匯率時點齊全 {int(ev.px_ok.sum())}，缺 {int((~ev.px_ok).sum())}")
    if (~ev.px_ok).any():
        print("  缺價事件：", ev[~ev.px_ok][["date", "entry_utc", "exit_utc"]].to_string(index=False))
    if zq:
        print("ZQ 旗標：", ev.zq_flag.value_counts().to_dict())
        print(f"訊號：多美元 {(ev.signal > 0).sum()}、空美元 {(ev.signal < 0).sum()}、不交易 {(ev.signal == 0).sum()}（其中無 ZQ {(ev.zq_flag.isin(['no_contract','no_settle'])).sum()}）")
        print("有訊號事件：", ev[ev.signal != 0][["date", "next_month", "S_bp", "signal", "zq_flag"]].to_string(index=False))
        print("無 ZQ 的排定會議：", ev[ev.zq_flag.isin(["no_contract", "no_settle"])].date.tolist())
    print("公告時間分佈：", ev.ann_time_et.value_counts().to_dict())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--zq", nargs="*", default=[])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    if a.check:
        check(a.zq or None); return
    if not a.zq or not a.out:
        sys.exit("正式跑數需要 --zq <dir...> 與 --out")
    cal = load_calendar(); target = load_target(); m1 = M1Cache(); zq = load_zq(a.zq)
    ev = build_events(cal, target, zq, m1)
    s = summarize(ev)
    plc = build_events(cal, target, zq, m1, window_shift=10)             # 偽事件：同訊號、視窗提前兩週（t−12 → t−10）
    s["placebo_shift10"] = {"dol": blk_simple(plc[(plc.signal != 0) & plc.px_ok].dol_strat), "eur_net": blk_simple(plc[(plc.signal != 0) & plc.px_ok].eur_net)}
    s["verdict"] = verdict(s)
    a.out.mkdir(parents=True, exist_ok=True)
    ev.to_csv(a.out / "events.csv", index=False)
    (a.out / "stats.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: s[k] for k in ("n_scheduled", "n_signal", "n_long_usd", "n_short_usd", "n_no_zq", "H1_dol_gross", "H2_eur_net", "H2_post2016_eur_net", "H1_post2016_dol", "regression_dol_on_S", "permutation", "placebo_shift10", "verdict") if k in s}, ensure_ascii=False, indent=1, default=str))


def blk_simple(x):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return {"n": int(len(x)), "mean": float(x.mean()) if len(x) else None, "t": tstat(x)}


if __name__ == "__main__":
    main()
