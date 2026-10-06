#!/usr/bin/env python3
"""HTF（Qullamaggie 高漲旗型）回測（預先登記：stock_research/HTF_BACKTEST.md，寫程式前已 commit；四市場各只測一次）。

    python3 htf_backtest.py --market hk --inspect 10        # 只印前 N 筆預設格交易機制（不印績效）
    python3 htf_backtest.py --market hk --trades-only       # 預設格逐筆明細 + 內部一致性可疑清單（不算績效）
    python3 htf_backtest.py --market hk --random 200        # 正式：預設格 + 鄰域 + 隨機對照 + 敏感度
    python3 htf_backtest.py --market hk --random 200 --repair-hl --tag _repairhl   # 港股高低價修正敏感度
    python3 htf_backtest.py --pool                          # 四市場合併檢定 + 判決

- 宇宙：60 日成交額中位數前 N（港 500／日 1000／美 1500／台 500），成本同 VCP 全市場／OOS
- 訊號（t−1 收市後）：21／63／126 日報酬任一在宇宙前 2%；60 日最高價 P 為旗桿頂，旗桿 ≥ G；旗面 3–30 日、深度 ≤ D、
  量縮 < 0.8 倍、收市 > 20 日線；大市 ETF 10MA > 20MA 且雙升
- 入場：t 日盤中最高 > P → 成交 max(開市, P)；開市 > P × 1.05 不買；台股漲停鎖死跳過
- 出場：停損 成交價×(1−ADR20) → 收市後上移到當日低點；第 3 日收市賣一半、停損移到成本；收市 < 10MA 下一日開市出；252 日上限
- 組合：日曆時間、按曝險單位等權；統計沿用 newhigh_backtest.MarketData
"""
import argparse
import bisect
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import newhigh_backtest as nb  # noqa: E402
import vcp_backtest as vb  # noqa: E402
from oos_backtest import locked_matrix  # noqa: E402
from expectancy_report import stats  # noqa: E402

MARKETS = ("hk", "jp", "us", "tw")
GRID = [(g, d) for g in (0.25, 0.30, 0.40) for d in (0.15, 0.20, 0.25)]
DEFAULT = (0.30, 0.20)
MOM_WINDOWS = (21, 63, 126)
MOM_PCT = 98            # 動能：任一窗口報酬在宇宙內百分位 ≥ 98
POLE_LOOK = 60          # 旗桿頂 = 前 60 日最高；旗桿底 = 頂之前 60 日最低
FLAG_MIN, FLAG_MAX = 3, 30
VOL_DRY = 0.8           # 旗面平均量 < 旗桿段（頂之前 20 日）平均量 × 0.8
MA_SUPPORT = 20
CHASE = 0.05
ADR_N = 20
PARTIAL_DAY = 3         # 入場後第 3 個交易日收市賣一半
TRAIL_MA = 10
MAX_HOLD = 252
OUT = ROOT / "research" / "htf"


class HTF:
    def __init__(self, market: str, exclude: set | None = None, repair_hl: bool = False):
        pool = [l.strip() for l in (ROOT / "universes" / "full" / f"{market}_pool.txt").read_text(
            encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        self.market = market
        self.m = m = nb.MarketData(market, pool=pool, loader=nb.load_full(market, repair_hl), top_n=vb.FULL_TOP_N[market],
                                   cost=vb.FULL_COST[market])
        S, D = m.adj.shape
        idx = pd.Index(m.cal)
        self.ci = {d: j for j, d in enumerate(m.cal)}
        # 基準 ETF 數據錯誤防護：指數 ETF 單日 |報酬| > 50% 只可能是分拆未調整／錯列（1321.T 2026-10-05、0050.TW 2014-01-02）→ 記 0
        for j in np.nonzero(np.abs(m.etf_ret) > 0.5)[0]:
            print(f"[{market}] 基準 ETF {m.cal[j]} 單日報酬 {m.etf_ret[j]:+.1%} 判為數據錯誤，記 0", file=sys.stderr)
            m.etf_ret[j] = 0.0
        self.raw = {}
        mom = {w: np.full((S, D), np.nan, dtype=np.float32) for w in MOM_WINDOWS}
        for s, t in enumerate(m.tickers):
            df = pd.DataFrame(m.loader(t)).set_index("Date")
            df = df[df["AdjClose"] > 0]
            close, adj = df["Close"], df["AdjClose"]
            high = pd.concat([df["High"].fillna(close), close], axis=1).max(axis=1)
            low = pd.concat([df["Low"].where(df["Low"] > 0).fillna(close), close], axis=1).min(axis=1)
            for w in MOM_WINDOWS:
                mom[w][s] = (adj / adj.shift(w) - 1).reindex(idx).to_numpy(dtype=np.float32)
            dl = list(df.index)
            self.raw[s] = {"dates": {d: i for i, d in enumerate(dl)}, "dlist": dl,
                           "jarr": np.array([self.ci.get(d, -1) for d in dl], dtype=np.int64),
                           "open": df["Open"].to_numpy(dtype=float), "high": high.to_numpy(dtype=float),
                           "low": low.to_numpy(dtype=float), "close": close.to_numpy(dtype=float),
                           "vol": df["Volume"].to_numpy(dtype=float), "adj": adj.to_numpy(dtype=float),
                           "adr": (high / low - 1).rolling(ADR_N).mean().to_numpy(dtype=float),
                           "ma10": adj.rolling(10).mean().to_numpy(dtype=float),
                           "ma20": adj.rolling(20).mean().to_numpy(dtype=float)}
        # 動能篩選：每天宇宙內各窗口報酬的百分位（97／98／99 三個版本，98 判決用）
        self.mom_ok = {q: np.zeros((S, D), dtype=bool) for q in (97, 98, 99)}
        for j in range(D):
            mem = m.member[:, j]
            for w in MOM_WINDOWS:
                col = mom[w][:, j]
                ok = mem & ~np.isnan(col)
                if ok.sum() < 50:
                    continue
                pct = pd.Series(col[ok]).rank(pct=True).to_numpy() * 100
                for q in self.mom_ok:
                    self.mom_ok[q][np.nonzero(ok)[0][pct >= q], j] = True
        del mom
        # 大市過濾：ETF 10 日線 > 20 日線，且兩條都高於前一日
        lvl = pd.Series(np.cumprod(1 + m.etf_ret))
        ma10, ma20 = lvl.rolling(10).mean(), lvl.rolling(20).mean()
        self.mkt_ok = ((ma10 > ma20) & (ma10 > ma10.shift(1)) & (ma20 > ma20.shift(1))).to_numpy()
        self.locked = locked_matrix(m, market)
        self.exclude = exclude or set()
        self.scan()

    def scan(self) -> None:
        """找出全部「t−1 旗型成立、t 日盤中突破」的候選（G、D 只先用鄰域最寬邊界過濾，格子在 trades() 才套）。"""
        m = self.m
        g_min, d_max = min(g for g, _ in GRID), max(d for _, d in GRID)
        self.setups = []
        n_mom = 0
        for s, rw in self.raw.items():
            jarr, high, low, close, vol, adj, opn = (rw[k] for k in ("jarr", "high", "low", "close", "vol", "adj", "open"))
            n = len(high)
            jp = jarr[:-1]
            cand = np.nonzero((jarr[1:] >= m.start_j) & (jp >= 0))[0] + 1
            if len(cand) == 0:
                continue
            cand = cand[self.mom_ok[MOM_PCT][s, jarr[cand - 1]] & m.member[s, jarr[cand - 1]]]
            for p in cand:
                if p < 2 * POLE_LOOK + 1:
                    continue
                n_mom += 1
                win = high[p - POLE_LOOK:p]
                k = int(np.argmax(win))                      # 相同最高價取最早一天
                ptop = p - POLE_LOOK + k
                P = high[ptop]
                flag_len = (p - 1) - ptop
                if not (FLAG_MIN <= flag_len <= FLAG_MAX) or not high[p] > P:
                    continue
                pole_low = low[ptop - POLE_LOOK:ptop + 1].min()
                G = P / pole_low - 1 if pole_low > 0 else 0.0
                Dflag = (P - low[ptop + 1:p].min()) / P
                if G < g_min or Dflag > d_max:
                    continue
                volp = vol[ptop - 19:ptop + 1].mean()
                volf = vol[ptop + 1:p].mean()
                if not (volp > 0 and volf < VOL_DRY * volp):
                    continue
                if not adj[p - 1] > rw["ma20"][p - 1]:
                    continue
                adr = rw["adr"][p - 1]
                if not (adr == adr and adr > 0):
                    continue
                o = opn[p] if opn[p] == opn[p] and opn[p] > 0 else P
                self.setups.append({"s": s, "p": p, "j": int(jarr[p]), "pivot": P, "open": o, "G": G, "D": Dflag,
                                    "flag_len": int(flag_len), "adr": adr, "mkt": bool(self.mkt_ok[jarr[p - 1]])})
        self.setup_days = {}
        for st in self.setups:
            self.setup_days.setdefault(st["j"], set()).add(st["s"])
        n_mkt = sum(st["mkt"] for st in self.setups)
        print(f"[{self.market}] 動能候選日 {n_mom}、旗型成立且突破 {len(self.setups)}（鄰域最寬邊界）、其中大市過濾成立 {n_mkt}",
              file=sys.stderr)

    # ---------- 出場模擬 ----------
    def simulate(self, s: int, p: int, fill: float, adr: float, trail: str = "ma10", adr_stop: bool = True) -> list:
        """回傳各腿 [(出場 raw 索引, 出場原始價, 是否收市出場, 單位)]。"""
        rw = self.raw[s]
        high, low, close, opn, adj, ma = (rw[k] for k in ("high", "low", "close", "open", "adj", trail))
        n = len(close)
        stop = fill * (1 - adr) if adr_stop else -math.inf
        o0 = opn[p] if opn[p] == opn[p] and opn[p] > 0 else fill
        pre_fill_low = o0 < fill and low[p] == o0        # 低點就是開市價、而成交在開市之後 → 低點發生在成交前
        if low[p] <= stop and not pre_fill_low:
            return [(p, stop, False, 1.0)]
        stop = max(stop, low[p])
        legs, units, exit_next_open = [], 1.0, False
        last = min(n, p + MAX_HOLD + 1)
        for k in range(p + 1, last):
            o = opn[k] if opn[k] == opn[k] and opn[k] > 0 else close[k]
            if exit_next_open:
                legs.append((k, o, False, units))
                return legs
            if low[k] <= stop:
                legs.append((k, min(o, stop), False, units))
                return legs
            if k == p + PARTIAL_DAY:
                legs.append((k, close[k], True, 0.5))
                units = 0.5
                stop = max(stop, fill)
            if k >= p + PARTIAL_DAY and ma[k] == ma[k] and adj[k] < ma[k]:
                exit_next_open = True
        k = last - 1
        legs.append((k, close[k], True, units))
        return legs

    def _trade(self, s: int, p: int, fill: float, legs: list, info: dict | None = None) -> dict:
        rw = self.raw[s]
        f_in = rw["adj"][p] / rw["close"][p]
        out = []
        for k, px, at_close, u in legs:
            f_out = rw["adj"][k] / rw["close"][k]
            out.append({"b": self.cal_j(rw["dlist"][k]), "k": k, "out_adj": px * f_out, "at_close": at_close, "u": u})
        return {"s": s, "p": p, "a": self.cal_j(rw["dlist"][p]), "fill": fill, "in_adj": fill * f_in, "legs": out,
                "info": info or {}}

    def cal_j(self, d) -> int:
        j = self.ci.get(d)
        return j if j is not None else min(bisect.bisect_left(self.m.cal, d), len(self.m.cal) - 1)

    # ---------- 交易 ----------
    def trades(self, g: float, d: float, *, trail: str = "ma10", close_confirm: bool = False, mkt_filter: bool = True,
               adr_min: float = 0.0, mom_q: int = MOM_PCT, random_seed: int | None = None) -> list[dict]:
        m = self.m
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        out, busy = [], {}
        for st in sorted(self.setups, key=lambda x: (x["j"], x["s"])):
            s, p, j, P, o = st["s"], st["p"], st["j"], st["pivot"], st["open"]
            if st["G"] < g or st["D"] > d or st["adr"] < adr_min:
                continue
            if mom_q != MOM_PCT and not self.mom_ok[mom_q][s, j - 1]:
                continue
            if mkt_filter and not st["mkt"]:
                continue
            rw = self.raw[s]
            if rng is None:
                if (m.tickers[s], rw["dlist"][p].isoformat()) in self.exclude:
                    continue
                if close_confirm:
                    # 敏感度：t 收市 > P 才確認，t+1 開市買（停損用 t 日 ADR）
                    if not rw["close"][p] > P or p + 1 >= len(rw["close"]):
                        continue
                    pe = p + 1
                    if rw["jarr"][pe] < 0:          # 次日是個股有、日曆沒有的日子（例：日本假期）→ 跳過
                        continue
                    fill = rw["open"][pe] if rw["open"][pe] == rw["open"][pe] and rw["open"][pe] > 0 else rw["close"][pe]
                    adr = rw["adr"][p]
                else:
                    pe, fill, adr = p, max(o, P), st["adr"]
                if o > P * (1 + CHASE) or self.locked[s, rw["jarr"][pe]] or pe <= busy.get(s, -1):
                    continue
                if not (adr == adr and adr > 0):
                    continue
                legs = self.simulate(s, pe, fill, adr, trail)
                busy[s] = legs[-1][0]
                out.append(self._trade(s, pe, fill, legs, st))
            else:
                # 隨機對照：同日 t−1 通過動能篩選（大市過濾同日成立）、當天不是 HTF 訊號的宇宙內股票，t 開市買，同一套出場
                pool = np.nonzero(self.mom_ok[MOM_PCT][:, j - 1] & m.member[:, j - 1])[0]
                pool = pool[~np.isin(pool, list(self.setup_days[j]))]
                if len(pool) == 0:
                    continue
                r = int(pool[rng.integers(len(pool))])
                rr = self.raw[r]
                pr = rr["dates"].get(m.cal[j])
                if pr is None or pr < 1 or self.locked[r, j]:
                    continue
                o_r, adr_r = rr["open"][pr], rr["adr"][pr - 1]
                if not (o_r == o_r and o_r > 0 and adr_r == adr_r and adr_r > 0):
                    continue
                legs = self.simulate(r, pr, o_r, adr_r, trail)
                out.append(self._trade(r, pr, o_r, legs))
        return out

    # ---------- 組合 ----------
    def daily(self, trades: list[dict], risk_weight: bool = False) -> tuple[np.ndarray, list[float], np.ndarray]:
        """日曆時間、按曝險單位加權的組合日報酬；每筆淨報酬；每日曝險單位。"""
        m = self.m
        S, D = m.adj.shape
        cost = m.cfg["cost"]
        wdiff = np.zeros((S, D + 1))
        num, den = np.zeros(D), np.zeros(D)
        tr = []
        for t in trades:
            s, a, in_adj = t["s"], t["a"], t["in_adj"]
            w = 1.0
            if risk_weight:                       # 敏感度：倉位 ∝ 1 ÷ ADR（風險倉位法），截在 0.25–4 倍
                adr = t["info"].get("adr") or self.raw[s]["adr"][t["p"] - 1]
                w = float(np.clip(0.05 / adr, 0.25, 4.0))
            legs = t["legs"]
            if len(legs) == 1 and legs[0]["b"] == a:        # 入場當日全部停損
                lg = legs[0]
                num[a] += w * (lg["out_adj"] / in_adj - 1 - 2 * cost)
                den[a] += w
                tr.append(lg["out_adj"] / in_adj * (1 - cost) ** 2 - 1)
                continue
            num[a] += w * (m.adj[s, a] / in_adj - 1 - cost)
            den[a] += w
            net = 0.0
            for lg in legs:
                b, u = lg["b"], lg["u"] * w
                if b - 1 >= a + 1:
                    wdiff[s, a + 1] += u
                    wdiff[s, b] -= u
                if lg["at_close"]:
                    num[b] += u * (m.ret[s, b] - cost)
                else:
                    prev = m.prev_close[s, b]
                    num[b] += u * ((lg["out_adj"] / prev - 1 if prev == prev and prev > 0 else 0.0) - cost)
                den[b] += u
                net += lg["u"] * (lg["out_adj"] / in_adj)
            tr.append(net * (1 - cost) ** 2 - 1)
        C = np.cumsum(wdiff[:, :D], axis=1)
        num += (m.ret * C).sum(0)
        den += C.sum(0)
        return np.where(den > 0, num / np.maximum(den, 1e-12), 0.0), tr, den

    def abn(self, daily: np.ndarray) -> dict:
        m = self.m
        mo, me = m.monthly(daily), m.monthly(m.etf_ret)
        _, b, _ = m.capm(mo, me)
        x = (mo - b * me).dropna()
        return {str(k.date())[:7]: float(v) for k, v in x.items()}

    def evaluate(self, trades: list[dict], risk_weight: bool = False) -> dict:
        m = self.m
        daily, tr, n = self.daily(trades, risk_weight)
        holds = [t["legs"][-1]["b"] - t["a"] for t in trades]
        st = stats(m, daily, tr, holds)
        mo, me, mw = m.monthly(daily), m.monthly(m.etf_ret), m.monthly(m.ew_ret)
        a, b, t = m.capm(mo, me)
        sp = pd.Timestamp(m.cfg["split"])
        pre = m.capm(mo[mo.index < sp], me[me.index < sp])[2] if (mo.index < sp).sum() > 24 else float("nan")
        post = m.capm(mo[mo.index >= sp], me[me.index >= sp])[2] if (mo.index >= sp).sum() > 24 else float("nan")
        pos = sum(sorted(tr, reverse=True)[:10])
        st.update({"alpha_t": t, "beta": b, "t_ew": m.capm(mo, mw)[2], "t_pre": pre, "t_post": post,
                   "top10_share": float(pos / sum(tr)) if sum(tr) > 0 else float("nan"),
                   "avg_pos": float(n[m.start_j:].mean()), "invested": float((n[m.start_j:] > 0).mean()),
                   "stopped_first_day": sum(len(x["legs"]) == 1 and x["legs"][0]["b"] == x["a"] for x in trades),
                   "partial_reached": sum(any(lg["u"] == 0.5 for lg in x["legs"]) for x in trades),
                   "by_year": {y: float((1 + g).prod() - 1) for y, g in pd.Series(
                       daily[m.start_j:], index=pd.to_datetime(m.cal[m.start_j:])).groupby(lambda d: d.year)},
                   "by_year_etf": {y: float((1 + g).prod() - 1) for y, g in pd.Series(
                       m.etf_ret[m.start_j:], index=pd.to_datetime(m.cal[m.start_j:])).groupby(lambda d: d.year)}})
        return st

    # ---------- 明細與內部一致性 ----------
    def detail(self, trades: list[dict]) -> list[dict]:
        m, out = self.m, []
        for t in trades:
            s, p = t["s"], t["p"]
            rw = self.raw[s]
            dl = rw["dlist"]
            info = t["info"]
            sus = []
            for q in (p - 1, p):
                o, h, lo, c = rw["open"][q], rw["high"][q], rw["low"][q], rw["close"][q]
                if not (lo * 0.99 <= c <= h * 1.01) or (o == o and o > 0 and not (lo * 0.99 <= o <= h * 1.01)):
                    sus.append(f"{dl[q]} 開收市超出高低價")
                if q >= 1 and rw["close"][q - 1] > 0 and abs(c / rw["close"][q - 1] - 1) > 0.5:
                    sus.append(f"{dl[q]} 單日 |漲跌| > 50%")
                if rw["vol"][q] == 0:
                    sus.append(f"{dl[q]} 成交量 0")
            if h > 0 and (rw["high"][p] / rw["low"][p] - 1) > 0.5:
                sus.append(f"{dl[p]} 當日高低差 > 50%")
            out.append({"ticker": m.tickers[s], "signal": dl[p - 1].isoformat(), "entry": dl[p].isoformat(),
                        "pivot": info.get("pivot"), "open": info.get("open"), "fill": t["fill"],
                        "pole_gain": info.get("G"), "flag_depth": info.get("D"), "flag_len": info.get("flag_len"),
                        "adr": info.get("adr"), "stop0": t["fill"] * (1 - info["adr"]) if info.get("adr") else None,
                        "day_low": rw["low"][p],
                        "legs": [{"exit": dl[lg["k"]].isoformat(), "units": lg["u"], "px": lg["out_adj"] * rw["close"][lg["k"]] / rw["adj"][lg["k"]],
                                  "how": "收市" if lg["at_close"] else "開市/停損"} for lg in t["legs"]],
                        "net": sum(lg["u"] * lg["out_adj"] for lg in t["legs"]) / t["in_adj"] - 1,
                        "suspect": sus,
                        "tv_rank": int(m.tv_rankpos[m.tickers[s]][t["a"]]) if hasattr(m, "tv_rankpos") else None})
        return out


def run_market(mk: str, n_random: int, trades_only: bool, inspect: int, repair_hl: bool, tag: str) -> None:
    sus_p = OUT / f"{mk}_suspect.json"
    excl = {tuple(x) for x in json.loads(sus_p.read_text())} if sus_p.exists() and not trades_only else set()
    h = HTF(mk, excl, repair_hl)
    m = h.m
    if inspect:
        for d in h.detail(h.trades(*DEFAULT)[:inspect]):
            print(json.dumps(d, ensure_ascii=False, default=float))
        return
    trs = h.trades(*DEFAULT)
    if trades_only:
        det = h.detail(trs)
        sus = [[d["ticker"], d["entry"]] for d in det if d["suspect"]]
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{mk}_trades_detail.json").write_text(json.dumps({"market": mk, "n_total": len(det), "trades_detail": det},
                                                                 ensure_ascii=False, default=float) + "\n", encoding="utf-8")
        (OUT / f"{mk}_suspect.json").write_text(json.dumps(sus, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[{mk}] 預設格 {len(det)} 筆明細已寫出；內部一致性可疑 {len(sus)} 筆（{len(sus) / max(len(det), 1):.1%}）；未算績效",
              file=sys.stderr)
        return
    res = {"market": mk, "excluded_suspects": sorted(map(list, excl)), "n_setups": len(h.setups), "cells": {}, "abn": {}}
    for g, d in GRID:
        key = f"G{g:.2f}_D{d:.2f}"
        t_ = trs if (g, d) == DEFAULT else h.trades(g, d)
        res["cells"][key] = h.evaluate(t_)
    res["default"] = f"G{DEFAULT[0]:.2f}_D{DEFAULT[1]:.2f}"
    st = res["cells"][res["default"]]
    daily, tr, _ = h.daily(trs)
    res["abn"]["HTF"] = h.abn(daily)
    top = set(np.argsort(-np.nan_to_num(np.array(tr), nan=-9))[:10])
    res["abn"]["HTF_drop10"] = h.abn(h.daily([t for i, t in enumerate(trs) if i not in top])[0])
    # 敏感度（各一個數，不參與判決）
    sens = {"ma20_trail": h.evaluate(h.trades(*DEFAULT, trail="ma20")),
            "close_confirm_next_open": h.evaluate(h.trades(*DEFAULT, close_confirm=True)),
            "risk_weight": h.evaluate(trs, risk_weight=True),
            "adr_min_4pct": h.evaluate(h.trades(*DEFAULT, adr_min=0.04)),
            "no_market_filter": h.evaluate(h.trades(*DEFAULT, mkt_filter=False)),
            "mom_97": h.evaluate(h.trades(*DEFAULT, mom_q=97)),
            "mom_99": h.evaluate(h.trades(*DEFAULT, mom_q=99))}
    res["sensitivity"] = {k: {x: v[x] for x in ("trades", "alpha_t", "cagr", "mdd", "win", "avg_hold", "t_pre", "t_post")}
                          for k, v in sens.items()}
    det = h.detail(trs)
    res["flag_len_hist"] = {str(k): int(v) for k, v in pd.Series([x["flag_len"] for x in det]).value_counts().sort_index().items()}
    res["flag_depth_quartiles"] = [float(x) for x in np.percentile([x["flag_depth"] for x in det], [25, 50, 75])] if det else []
    if det and det[0]["tv_rank"] is not None:
        rk = np.array([x["tv_rank"] for x in det])
        res["tv_rank_dist"] = {"top_third": float((rk <= m.top_n / 3).mean()), "mid_third": float(((rk > m.top_n / 3) & (rk <= 2 * m.top_n / 3)).mean()),
                               "bottom_third": float((rk > 2 * m.top_n / 3).mean())}
    print(f"[{mk}] 預設格 筆數 {st['trades']:5d}  alpha t {st['alpha_t']:5.2f}  vs等權 {st['t_ew']:5.2f}  前/後 {st['t_pre']:.2f}/{st['t_post']:.2f}  "
          f"年化 {st['cagr']:+.1%}（ETF {st['cagr_etf']:+.1%}）  MDD {st['mdd']:.0%}  勝率 {st['win']:.0%}  RRR {st['rrr']:.2f}  "
          f"期望值 {st['expectancy']:+.2%}  持有 {st['avg_hold']:.1f} 日  前10筆佔 {st['top10_share']:.0%}", file=sys.stderr)
    for key, c in res["cells"].items():
        print(f"   {key}  筆數 {c['trades']:5d}  alpha t {c['alpha_t']:5.2f}", file=sys.stderr)
    for key, c in res["sensitivity"].items():
        print(f"   敏感度 {key:24s} 筆數 {c['trades']:5d}  alpha t {c['alpha_t']:5.2f}", file=sys.stderr)
    rnd = []
    for sd in range(n_random):
        rnd.append(h.abn(h.daily(h.trades(*DEFAULT, random_seed=sd))[0]))
    if rnd:
        real = tstat_series(res["abn"]["HTF"])
        rt = sorted(tstat_series(x) for x in rnd)
        res["random"] = {"n": len(rt), "pctl": sum(x < real for x in rt) / len(rt), "median": rt[len(rt) // 2],
                         "p95": rt[int(0.95 * len(rt))], "real_resid_t": real}
        print(f"   隨機對照 {len(rt)} 次：真實殘差 t {real:.2f}，第 {res['random']['pctl']:.0%} 百分位（中位 {res['random']['median']:.2f}）",
              file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{mk}{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with gzip.open(OUT / f"{mk}{tag}_random.json.gz", "wt", encoding="utf-8") as f:
        json.dump(rnd, f)


def tstat_series(abn: dict) -> float:
    x = pd.Series(abn).dropna()
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 24 else float("nan")


def pooled(series: list[dict]) -> pd.Series:
    return pd.DataFrame([pd.Series(s) for s in series]).T.sort_index().mean(axis=1)


def pool_all(markets=MARKETS) -> None:
    R = {mk: json.loads((OUT / f"{mk}.json").read_text(encoding="utf-8")) for mk in markets}
    RN = {mk: json.load(gzip.open(OUT / f"{mk}_random.json.gz", "rt", encoding="utf-8")) for mk in markets}
    real = tstat_series(pooled([R[mk]["abn"]["HTF"] for mk in markets]))
    drop10 = tstat_series(pooled([R[mk]["abn"]["HTF_drop10"] for mk in markets]))
    n = min(len(RN[mk]) for mk in markets)
    rt = sorted(tstat_series(pooled([RN[mk][i] for mk in markets])) for i in range(n))
    pct = sum(x < real for x in rt) / n if n else float("nan")
    cells = {mk: R[mk]["cells"][R[mk]["default"]] for mk in markets}
    pos = sum(c["alpha_t"] > 0 for c in cells.values())
    neg = sum(c["alpha_t"] < 0 for c in cells.values())
    abs_pos = all(c["cagr"] > 0 for c in cells.values())
    if real >= 2.5 and pct >= 0.95 and pos >= 3 and abs_pos and drop10 > 0:
        v = "✅ 有希望（未證實，要前向驗證）"
    elif real < 1.0 or neg >= 2:
        v = "☠️"
    else:
        v = "不確定"
    out = {"pooled_t": real, "pooled_t_drop10": drop10, "random_pctl": pct, "random_median": rt[n // 2] if n else None,
           "random_p95": rt[int(0.95 * n)] if n else None, "pos_alpha": pos, "neg_alpha": neg, "abs_all_positive": abs_pos,
           "verdict": v, "per_market": {mk: {x: cells[mk][x] for x in ("alpha_t", "t_ew", "t_pre", "t_post", "cagr", "cagr_etf",
                                                                       "cum", "cum_etf", "mdd", "trades", "win", "rrr", "avg_hold")}
                                        for mk in markets}}
    print(f"合併 alpha t {real:.2f}  去前10筆 {drop10:.2f}  隨機第 {pct:.0%} 百分位（中位 {out['random_median']:.2f}）  "
          f"alpha>0 市場 {pos}/{len(markets)}  四地絕對回報都正 {abs_pos}  → {v}", file=sys.stderr)
    (OUT / "pooled.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--random", type=int, default=0)
    a.add_argument("--inspect", type=int, default=0)
    a.add_argument("--trades-only", action="store_true")
    a.add_argument("--repair-hl", action="store_true", help="港股敏感度：高低價修正為含開收市、放回被排除股票")
    a.add_argument("--tag", default="", help="輸出檔名後綴（敏感度用，例：_repairhl）")
    a.add_argument("--pool", action="store_true")
    args = a.parse_args()
    if args.pool:
        pool_all()
        return
    if not args.market:
        a.error("--market 或 --pool")
    run_market(args.market, args.random, args.trades_only, args.inspect, args.repair_hl, args.tag)


if __name__ == "__main__":
    main()
