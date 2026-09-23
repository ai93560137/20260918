#!/usr/bin/env python3
"""新高連續天數入場策略回測引擎（預先登記見 NEWHIGH_BACKTEST.md，跑數前已 commit）。

    python3 newhigh_backtest.py --market hk            # 預設格 + 鄰域 + 出場替代
    python3 newhigh_backtest.py --market us --random 200
    python3 newhigh_backtest.py --market jp --validate  # 跟 analysis/newhighs/ 名單逐檔比對訊號

訊號定義與每日名單（scripts/daily_topdown.py）同一套：在 200 日線上（還原收市）、原始收市價嚴格高於之前
n−1 日原始盤中最高價（n = 63/126/189/252）。入場 = 訊號日下一個交易日開盤；日曆時間等權組合。
"""
import argparse
import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
from universe import Universe  # noqa: E402

MARKETS = {
    "hk": {"index": "hsi", "etf": "2800.HK", "idx": "^HSI", "start": date(2010, 7, 1), "cost": 0.0015, "split": date(2022, 1, 1)},
    "us": {"index": "sp500", "etf": "SPY", "idx": "^GSPC", "start": date(2000, 1, 1), "cost": 0.0005, "split": date(2013, 1, 1)},
    "jp": {"index": "n225", "etf": "1321.T", "idx": "^N225", "start": date(2009, 7, 1), "cost": 0.0010, "split": date(2013, 1, 1)},
}
WINDOWS = {3: 63, 6: 126, 9: 189, 12: 252}
MAX_HOLD = 252
X1_DAYS = 20
X2_LOOKBACK = 20


def consecutive(mask: np.ndarray) -> np.ndarray:
    """連續 True 的計數（False 歸零）。"""
    out = np.zeros(len(mask), dtype=np.int32)
    c = 0
    for i, v in enumerate(mask):
        c = c + 1 if v else 0
        out[i] = c
    return out


def load_full(market: str, repair_hl: bool = False):
    """全市場數據（data_full/<market>/<TICKER>.csv.gz，不進 git）的 loader，格式同 marketdata.load_ohlcv。
    repair_hl：港股敏感度（VCP_FULLMARKET_BACKTEST.md，只作參考）——只因「高低價矛盾」被排除的股票不排除，
    改把最高／最低價修正為包含開市與收市。"""
    base = ROOT / "data_full" / market
    # 品質檢查（scripts/qc_full_market.py）：整檔排除 + 殭屍段
    ex_p, zb_p = base / "_qc_exclude.txt", base / "_qc_zombie.json"
    excluded = set(ex_p.read_text(encoding="utf-8").split()) if ex_p.exists() else set()
    zombies = json.loads(zb_p.read_text(encoding="utf-8")) if zb_p.exists() else {}

    def loader(t: str) -> list[dict]:
        p = base / f"{t.replace('^', '_')}.csv.gz"
        if not p.exists():
            raise FileNotFoundError(p)
        df = pd.read_csv(p, compression="gzip")
        if t.replace('^', '_') in excluded:
            if not repair_hl:
                raise FileNotFoundError(p)
            sys.path.insert(0, str(ROOT / "scripts"))
            from qc_full_market import structural
            if any(not x.startswith("高低價矛盾") for x in structural(df)[0]):
                raise FileNotFoundError(p)
        if repair_hl:
            df["High"] = df[["High", "Open", "Close"]].max(axis=1)
            df["Low"] = df[["Low", "Open", "Close"]].min(axis=1)
        df = df[df["Close"] > 0]
        for a, b in zombies.get(t.replace('^', '_'), []):
            df = df[(df["Date"] < a) | (df["Date"] > b)]
        rows = [(date.fromisoformat(d), o, h, lo, c, int(v) if v == v else 0)
                for d, o, h, lo, c, v in zip(df["Date"], df["Open"], df["High"], df["Low"], df["Close"], df["Volume"])]
        kept, _ = md.drop_spikes(rows)
        keep = {r[0] for r in kept}
        adj = dict(zip(df["Date"], df["AdjClose"]))
        return [{"Date": r[0], "Open": r[1], "High": r[2], "Low": r[3], "Close": r[4],
                 "AdjClose": adj[r[0].isoformat()] if adj[r[0].isoformat()] == adj[r[0].isoformat()] else r[4],
                 "Volume": r[5]} for r in rows if r[0] in keep]
    return loader


def stock_frame(t: str, loader=None) -> pd.DataFrame | None:
    rows = (loader or md.load_ohlcv)(t)
    if len(rows) < 260:
        return None
    df = pd.DataFrame(rows).set_index("Date")
    df = df[df["AdjClose"] > 0]
    f = df["AdjClose"] / df["Close"]
    adj = df["AdjClose"]
    opn = df["Open"].where(df["Open"] > 0)
    low = df["Low"].where(df["Low"] > 0)
    high = pd.concat([df["High"].fillna(df["Close"]), df["Close"]], axis=1).max(axis=1)
    out = pd.DataFrame(index=df.index)
    out["adj"] = adj
    out["aopen"] = (opn * f).fillna(adj)
    alow = (low * f).fillna(adj)
    ma200 = adj.rolling(200).mean()
    above = (adj > ma200).to_numpy()
    close = df["Close"]
    hi = {}
    for w, n in WINDOWS.items():
        ph = high.shift(1).rolling(n - 1, min_periods=n - 1).max()
        hi[w] = ((close > ph) & ph.notna()).to_numpy() & above
    L = np.zeros(len(df), dtype=np.int32)
    for w in (3, 6, 9, 12):          # 由短到長覆寫 = 最長窗口
        L[hi[w]] = w
    for w in WINDOWS:
        out[f"sw{w}"] = consecutive(hi[w])
    same = np.r_[False, L[1:] == L[:-1]]
    sl = np.zeros(len(L), dtype=np.int32)
    for i in range(len(L)):
        sl[i] = 0 if L[i] == 0 else (sl[i - 1] + 1 if i and same[i] else 1)
    out["L"] = L
    out["sl"] = sl
    prevL = np.r_[0, L[:-1]]
    out["upgrade"] = (L > prevL) & (prevL >= 3)
    out["above"] = above
    out["x2"] = (adj < alow.shift(1).rolling(X2_LOOKBACK).min()).to_numpy()
    out["x3"] = (adj < ma200).to_numpy() & ma200.notna().to_numpy()
    return out


class MarketData:
    """一個市場：日曆 × 股票的矩陣（還原收市/開市、訊號、出場條件、成分股遮罩）。"""

    def __init__(self, market: str, pool: list[str] | None = None, loader=None, top_n: int | None = None,
                 cost: float | None = None):
        """pool/loader/top_n 給全市場版：候選池、數據 loader、每日按 60 日成交額中位數取前 N（point-in-time）。
        不給就是原本的指數成分股版。"""
        cfg = dict(MARKETS[market])
        if cost is not None:
            cfg["cost"] = cost
        self.market, self.cfg = market, cfg
        self.loader = loader or md.load_ohlcv
        self.uni = Universe(cfg["index"])
        hol = set()
        p = ROOT / "universes" / "calendars" / f"{market}.csv"
        if p.exists():
            with open(p, newline="", encoding="utf-8") as f:
                hol = {date.fromisoformat(r["date"]) for r in csv.DictReader(f)}
        cal = set(md.load_series(cfg["etf"])) | set(md.load_series(cfg["idx"]))
        self.cal = sorted(d for d in cal if d >= cfg["start"] - timedelta(days=30) and d not in hol)
        self.ci = {d: i for i, d in enumerate(self.cal)}
        tickers = pool if pool is not None else self.uni.all_tickers(since=cfg["start"])
        idx0 = pd.Index(self.cal)
        tv_rank = None
        if top_n:
            # 第一輪：只算成交額（原始收市 × 量，60 日中位數），決定每日前 N；只保留曾入宇宙的股票，省記憶體
            tvs, names = [], []
            for t in tickers:
                try:
                    rows = self.loader(t)
                except FileNotFoundError:
                    continue
                if len(rows) < 260:
                    continue
                ser = pd.Series([r["Close"] * r["Volume"] for r in rows], index=[r["Date"] for r in rows])
                tvs.append(ser.rolling(60, min_periods=60).median().reindex(idx0).to_numpy(dtype=np.float32))
                names.append(t)
            tv = np.vstack(tvs) if tvs else np.zeros((0, len(self.cal)), dtype=np.float32)
            mem = np.zeros(tv.shape, dtype=bool)
            for j in range(tv.shape[1]):
                col = tv[:, j]
                ok = np.nonzero(~np.isnan(col) & (col > 0))[0]
                if len(ok) <= top_n:
                    mem[ok, j] = True
                else:
                    mem[ok[np.argpartition(-col[ok], top_n - 1)[:top_n]], j] = True
            j0 = next(j for j, d in enumerate(self.cal) if d >= cfg["start"])
            keep = [i for i in range(len(names)) if mem[i, j0:].any()]
            tickers = [names[i] for i in keep]
            tv_rank = {names[i]: mem[i] for i in keep}
            # 成交額名次（1 = 最大；只給訊號報告「大/中/小型」分布用）
            rk = np.full(tv.shape, 0, dtype=np.int32)
            for j in range(tv.shape[1]):
                col = tv[:, j]
                ok = np.nonzero(~np.isnan(col) & (col > 0))[0]
                rk[ok[np.argsort(-col[ok])], j] = np.arange(1, len(ok) + 1)
            self.tv_rankpos = {names[i]: rk[i] for i in keep}
            self.top_n = top_n
            print(f"[{market}] 全市場候選 {len(names)} 檔有數據、曾入前 {top_n} 名 {len(tickers)} 檔", file=sys.stderr)
        frames, first = {}, {}
        for t in tickers:
            try:
                fr = stock_frame(t, self.loader)
            except FileNotFoundError:
                continue
            if fr is not None:
                frames[t], first[t] = fr, fr.index[0]
        self.tickers = sorted(frames)
        S, D = len(self.tickers), len(self.cal)
        idx = pd.Index(self.cal)

        def mat(col, dtype=float, fill=np.nan):
            m = np.full((S, D), fill, dtype=dtype)
            for s, t in enumerate(self.tickers):
                m[s] = frames[t][col].reindex(idx).fillna(fill).to_numpy(dtype=dtype)
            return m

        self.adj, self.aopen = mat("adj"), mat("aopen")
        self.has = ~np.isnan(self.adj)
        self.sw = {w: mat(f"sw{w}", np.int32, 0) for w in WINDOWS}
        self.L, self.sl = mat("L", np.int32, 0), mat("sl", np.int32, 0)
        self.upgrade = mat("upgrade", bool, False)
        self.above = mat("above", bool, False)
        self.exitc = {"x2": mat("x2", bool, False), "x3": mat("x3", bool, False)}
        # 成分股遮罩（point-in-time + 防代碼重用）
        self.member = np.zeros((S, D), dtype=bool)
        pos = {t: s for s, t in enumerate(self.tickers)}
        if tv_rank is not None:
            for t, s in pos.items():
                self.member[s] = tv_rank[t]
        else:
            for j, d in enumerate(self.cal):
                for t in self.uni.eligible_at(d, first):
                    if t in pos:
                        self.member[pos[t], j] = True
        # 日報酬（收市到收市；停牌日 0，隔日用前一個有效收市）
        filled = pd.DataFrame(self.adj.T).ffill().to_numpy().T
        prev = np.c_[np.full(S, np.nan), filled[:, :-1]]
        self.prev_close = prev
        r = self.adj / prev - 1
        self.ret = np.where(self.has & ~np.isnan(prev), r, 0.0)
        # 下一個有價格的交易日（含當天）
        idxs = np.where(self.has, np.arange(D)[None, :], D)
        self.next_px = np.minimum.accumulate(idxs[:, ::-1], axis=1)[:, ::-1]
        self.last_px = np.array([np.nonzero(self.has[s])[0].max() if self.has[s].any() else -1 for s in range(S)])
        self.next_exit = {}
        for k, c in self.exitc.items():
            ii = np.where(c, np.arange(D)[None, :], D)
            self.next_exit[k] = np.minimum.accumulate(ii[:, ::-1], axis=1)[:, ::-1]
        # 股票自己的第幾個交易日（X1 用）
        self.nth = np.cumsum(self.has, axis=1)
        self.start_j = next(j for j, d in enumerate(self.cal) if d >= self.cfg["start"])
        etf = md.load_series(cfg["etf"])
        e = np.array([etf[d][1] if d in etf else np.nan for d in self.cal])
        e = pd.Series(e).ffill().to_numpy()
        self.etf_ret = np.r_[0.0, e[1:] / e[:-1] - 1]
        m = self.member & self.has
        self.ew_ret = np.where(m.sum(0) > 0, (self.ret * m).sum(0) / np.maximum(m.sum(0), 1), 0.0)
        print(f"[{market}] {S} 檔、{D} 個交易日（{self.cal[0]} ~ {self.cal[-1]}）", file=sys.stderr)

    # ---------- 事件 ----------
    def events(self, kind: str, p) -> np.ndarray:
        """布林矩陣：訊號日（收市後）觸發入場。"""
        if kind == "H4":
            w, k = p
            ev = self.sw[w] == k
        elif kind == "H5a":
            ev = self.upgrade & (self.L >= p)
        elif kind == "H5b":
            ev = self.sl == p
        else:
            raise ValueError(kind)
        ev = ev & self.member
        ev[:, :self.start_j] = False
        return ev

    # ---------- 交易 ----------
    def exit_index(self, s: int, entry: int, rule: str) -> tuple[int, bool]:
        """(出場日索引, 是否開盤出場)。下市 → 最後有價日收市出場。"""
        D = len(self.cal)
        cap = min(entry + MAX_HOLD, D - 1)
        if rule == "x1":
            target = self.nth[s, entry] + X1_DAYS
            j = int(np.searchsorted(self.nth[s], target))
            sig = j - 1          # 第 21 個交易日開盤出場 ↔ 「第 20 日收市」後的下一個有價日
            j = self.next_px[s, sig + 1] if sig + 1 < D else D
        else:
            sig = self.next_exit[rule][s, entry]
            j = self.next_px[s, sig + 1] if sig + 1 < D else D
        if j > cap:
            j = self.next_px[s, cap] if cap < D else D
        if j >= D:
            last = self.last_px[s]
            if last < len(self.cal) - 5:      # 下市：最後收市出場
                return last, False
            return D - 1, False               # 還在持有：用最新收市估值
        return int(j), True

    def trades_from_events(self, ev: np.ndarray, rule: str) -> list[tuple[int, int, int, bool]]:
        out = []
        D = len(self.cal)
        for s in range(ev.shape[0]):
            busy_until = -1
            for e in np.nonzero(ev[s])[0]:
                if e + 1 >= D:
                    continue
                entry = self.next_px[s, e + 1]
                if entry >= D or entry <= busy_until:
                    continue
                ex, at_open = self.exit_index(s, entry, rule)
                if ex < entry:
                    continue
                out.append((s, int(entry), ex, at_open))
                busy_until = ex
        return out

    def portfolio(self, trades) -> tuple[np.ndarray, list[float], np.ndarray]:
        """日曆時間等權組合日報酬、每筆淨報酬、每日持倉數。"""
        S, D = self.adj.shape
        cost = self.cfg["cost"]
        diff = np.zeros((S, D + 1), dtype=np.int32)
        extra = np.zeros(D)
        cnt_extra = np.zeros(D)
        tr_ret = []
        for s, a, b, at_open in trades:
            # 入場日：開市 → 收市
            r_a = self.adj[s, a] / self.aopen[s, a] - 1 - cost if a != b or not at_open else \
                self.aopen[s, b] / self.aopen[s, a] - 1 - 2 * cost
            extra[a] += r_a
            cnt_extra[a] += 1
            if b > a:
                # 中間日：a+1 .. b-1 用收市到收市
                if b - 1 >= a + 1:
                    diff[s, a + 1] += 1
                    diff[s, b] -= 1
                if at_open:     # 出場日：前收市 → 開市
                    r_b = self.aopen[s, b] / self.prev_close[s, b] - 1 - cost
                    extra[b] += r_b
                    cnt_extra[b] += 1
                else:           # 收市出場（下市/仍持有）：當天收市到收市
                    extra[b] += self.ret[s, b] - cost
                    cnt_extra[b] += 1
            # 每筆淨報酬
            if at_open:
                gross = self.aopen[s, b] / self.aopen[s, a]
            else:
                gross = self.adj[s, b] / self.aopen[s, a]
            tr_ret.append(gross * (1 - cost) ** 2 - 1)
        C = np.cumsum(diff[:, :D], axis=1)
        total = (self.ret * C).sum(0) + extra
        n = C.sum(0) + cnt_extra
        daily = np.where(n > 0, total / np.maximum(n, 1), 0.0)
        return daily, tr_ret, n

    # ---------- 統計 ----------
    def monthly(self, daily: np.ndarray) -> pd.Series:
        s = pd.Series(daily[self.start_j:], index=pd.to_datetime(self.cal[self.start_j:]))
        return (1 + s).resample("ME").prod() - 1

    def capm(self, y: pd.Series, x: pd.Series) -> tuple[float, float, float]:
        df = pd.concat([y, x], axis=1).dropna()
        Y, X = df.iloc[:, 0].to_numpy(), df.iloc[:, 1].to_numpy()
        n = len(Y)
        Xm = np.c_[np.ones(n), X]
        beta, *_ = np.linalg.lstsq(Xm, Y, rcond=None)
        resid = Y - Xm @ beta
        s2 = resid @ resid / (n - 2)
        cov = s2 * np.linalg.inv(Xm.T @ Xm)
        return float(beta[0]), float(beta[1]), float(beta[0] / math.sqrt(cov[0, 0]))

    def evaluate(self, trades) -> dict:
        daily, tr, n = self.portfolio(trades)
        m = self.monthly(daily)
        me = self.monthly(self.etf_ret)
        mw = self.monthly(self.ew_ret)
        a, b, t = self.capm(m, me)
        _, _, t_ew = self.capm(m, mw)
        sp = pd.Timestamp(self.cfg["split"])
        pre = self.capm(m[m.index < sp], me[me.index < sp])[2] if (m.index < sp).sum() > 24 else float("nan")
        post = self.capm(m[m.index >= sp], me[me.index >= sp])[2] if (m.index >= sp).sum() > 24 else float("nan")
        eq = (1 + pd.Series(daily[self.start_j:])).cumprod()
        eqe = (1 + pd.Series(self.etf_ret[self.start_j:])).cumprod()
        yrs = len(eq) / 252
        hold = [b_ - a_ for _, a_, b_, _ in trades]
        return {"trades": len(trades), "alpha_m": a, "beta": b, "t": t, "t_ew": t_ew, "t_pre": pre, "t_post": post,
                "cagr": eq.iloc[-1] ** (1 / yrs) - 1, "cagr_etf": eqe.iloc[-1] ** (1 / yrs) - 1,
                "mdd": float((eq / eq.cummax() - 1).min()), "mdd_etf": float((eqe / eqe.cummax() - 1).min()),
                "win": float(np.mean([x > 0 for x in tr])) if tr else float("nan"),
                "avg_trade": float(np.mean(tr)) if tr else float("nan"),
                "avg_hold": float(np.mean(hold)) if hold else float("nan"),
                "avg_pos": float(n[self.start_j:].mean()), "invested": float((n[self.start_j:] > 0).mean()),
                "tr": tr, "by_year": {y: float((1 + g).prod() - 1) for y, g in
                                      pd.Series(daily[self.start_j:], index=pd.to_datetime(self.cal[self.start_j:])).groupby(lambda d: d.year)},
                "by_year_etf": {y: float((1 + g).prod() - 1) for y, g in
                                pd.Series(self.etf_ret[self.start_j:], index=pd.to_datetime(self.cal[self.start_j:])).groupby(lambda d: d.year)}}

    def random_trades(self, ev: np.ndarray, rule: str, seed: int) -> list:
        """同一天從「在 200 日線上、當天不是該訊號」的成分股隨機挑一檔，用同一出場規則。"""
        rng = np.random.default_rng(seed)
        D = len(self.cal)
        out = []
        pool_cache = {}
        for s, e in zip(*np.nonzero(ev)):
            if e + 1 >= D:
                continue
            if e not in pool_cache:
                pool_cache[e] = np.nonzero(self.member[:, e] & self.above[:, e] & ~ev[:, e])[0]
            pool = pool_cache[e]
            if len(pool) == 0:
                continue
            r = int(pool[rng.integers(len(pool))])
            entry = self.next_px[r, e + 1]
            if entry >= D:
                continue
            ex, at_open = self.exit_index(r, entry, rule)
            if ex >= entry:
                out.append((r, int(entry), ex, at_open))
        return out


GRIDS = {
    "H4": {"default": (12, 3), "grid": [(w, k) for w in (6, 9, 12) for k in (1, 3, 5)]},
    "H5a": {"default": 6, "grid": [6, 9, 12]},
    "H5b": {"default": 5, "grid": [3, 5, 10]},
}


def label(kind, p):
    if kind == "H4":
        return f"W={p[0]} K={p[1]}"
    if kind == "H5a":
        return {6: "升到≥6", 9: "升到≥9", 12: "升到12"}[p]
    return f"K={p}"


def validate(mkd: MarketData) -> None:
    """跟 analysis/newhighs/<日>.csv（每日名單程式）比對：最長窗口、兩個連續天數、成分股遮罩。"""
    bad = total = 0
    for p in sorted((ROOT / "analysis" / "newhighs").glob("20*.csv")):
        d = date.fromisoformat(p.stem)
        if d not in mkd.ci:
            continue
        j = mkd.ci[d]
        with open(p, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["market"] == mkd.market]
        listed = {}
        for r in rows:
            listed[r["yahoo_ticker"]] = (int(r["longest_months"]), int(r["streak_longest"]))
        engine = {mkd.tickers[s]: (int(mkd.L[s, j]), int(mkd.sl[s, j]))
                  for s in np.nonzero((mkd.L[:, j] > 0) & mkd.member[:, j])[0]}
        for t in set(listed) | set(engine):
            total += 1
            if listed.get(t) != engine.get(t):
                bad += 1
                print(f"  不一致 {d} {t}: 名單 {listed.get(t)} 引擎 {engine.get(t)}", file=sys.stderr)
    print(f"[{mkd.market}] 驗證：{total} 筆（最長窗口, streak_longest）中不一致 {bad}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=list(MARKETS))
    ap.add_argument("--random", type=int, default=0, help="隨機對照次數（預先登記 200）")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "research" / "newhigh")
    args = ap.parse_args()
    mkd = MarketData(args.market)
    if args.validate:
        validate(mkd)
        return
    res = {"market": args.market, "cells": {}, "random": {}}
    for kind, g in GRIDS.items():
        for p in g["grid"]:
            ev = mkd.events(kind, p)
            rules = ("x2", "x1", "x3") if p == g["default"] else ("x2",)
            for rule in rules:
                r = mkd.evaluate(mkd.trades_from_events(ev, rule))
                key = f"{kind}|{label(kind, p)}|{rule}"
                res["cells"][key] = {k: v for k, v in r.items() if k != "tr"}
                if kind in ("H5a", "H5b") and p == g["default"] and rule == "x2":
                    res.setdefault("trade_rets", {})[kind] = r["tr"]
                print(f"{key:28} 筆數 {r['trades']:6d}  alpha t {r['t']:5.2f}  vs等權 t {r['t_ew']:5.2f}  "
                      f"beta {r['beta']:.2f}  年化 {r['cagr']:+.1%} (ETF {r['cagr_etf']:+.1%})  MDD {r['mdd']:.0%} "
                      f"(ETF {r['mdd_etf']:.0%})  勝率 {r['win']:.0%}  每筆 {r['avg_trade']:+.2%}  持有 {r['avg_hold']:.0f} 日  "
                      f"持倉 {r['avg_pos']:.1f}  前/後 t {r['t_pre']:.2f}/{r['t_post']:.2f}", file=sys.stderr)
        if args.random:
            ev = mkd.events(kind, g["default"])
            ts = []
            for seed in range(args.random):
                ts.append(mkd.evaluate(mkd.random_trades(ev, "x2", seed))["t"])
            ts = sorted(ts)
            real = res["cells"][f"{kind}|{label(kind, g['default'])}|x2"]["t"]
            pctl = sum(x < real for x in ts) / len(ts)
            res["random"][kind] = {"median": ts[len(ts) // 2], "p90": ts[int(0.9 * len(ts))], "real_pctl": pctl,
                                   "n": len(ts)}
            print(f"{kind} 隨機對照 {len(ts)} 次：中位數 {ts[len(ts) // 2]:.2f}、第 90 百分位 {ts[int(0.9 * len(ts))]:.2f}；"
                  f"預設格 {real:.2f} 在第 {pctl:.0%} 百分位", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.market}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n",
                                                  encoding="utf-8")


if __name__ == "__main__":
    main()
