#!/usr/bin/env python3
"""行業動量回測引擎（多市場）——規格見 SECTOR_ROTATION.md 第一部分預先登記，這裡照做不改。

每月最後交易日 t：每個行業 = 當時 point-in-time 組員各自過去 L 個月總報酬的等權平均
（組員 >= 3 檔的行業才排名）；取最強 N 個行業，行業間等權、行業內等權；t 的下一個
交易日開盤進場、持有到下月換倉日開盤；換手成本 = Σ|權重變動| × 單邊成本。

    python3 sector_momentum_backtest.py --index hsi                 # 預設格 L=6 N=3
    python3 sector_momentum_backtest.py --index hsi --grid          # 3x3 鄰域
    python3 sector_momentum_backtest.py --index hsi --permutation   # 隨機行業對照組（200 次）
    python3 sector_momentum_backtest.py --index hsi --attribution   # 第二部分：低波動/高股息的行業歸因
"""
import argparse
import bisect
import math
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from stock_momentum_backtest import load_series, month_end_dates, next_trading_day, t_stat  # noqa: E402
from universe import INDICES, Universe  # noqa: E402

COST_BPS = {"hk": 15.0, "us": 5.0, "jp": 10.0}
START = {"hsi": date(2010, 7, 1), "sp500": date(2000, 1, 1)}
MIN_MEMBERS = 3
GRID_L = (3, 6, 12)
GRID_N = (2, 3, 4)


def capm(rets: list[float], bench: list[float]) -> dict:
    n = len(rets)
    out = {"alpha_ann": float("nan"), "alpha_t": float("nan"), "beta": float("nan")}
    if n < 3:
        return out
    mb, mr = sum(bench) / n, sum(rets) / n
    sbb = sum((x - mb) ** 2 for x in bench)
    if sbb <= 0:
        return out
    beta = sum((x - mb) * (y - mr) for x, y in zip(bench, rets)) / sbb
    alpha = mr - beta * mb
    resid = [y - alpha - beta * x for x, y in zip(bench, rets)]
    se = math.sqrt(sum(e * e for e in resid) / (n - 2)) * math.sqrt(1 / n + mb * mb / sbb)
    return {"alpha_ann": alpha * 12, "alpha_t": alpha / se if se else float("nan"), "beta": beta}


class Market:
    """一次載入宇宙與價格，之後各參數格共用。"""

    def __init__(self, index: str, start: date | None = None):
        self.uni = Universe(index)
        self.index = index
        self.cost = COST_BPS[self.uni.cfg["market"]] / 10000
        self.bench = self.uni.benchmark
        self.sectors, _ = self.uni.sectors()
        self.series: dict[str, dict] = {}
        for t in self.uni.all_tickers() + [self.bench]:
            try:
                self.series[t] = load_series(t)
            except FileNotFoundError:
                pass
        if self.bench not in self.series:
            raise SystemExit(f"沒有基準 {self.bench} 的數據")
        self.first = {t: min(s) for t, s in self.series.items() if s}
        self.dates = {t: sorted(s) for t, s in self.series.items()}
        cal = sorted(self.series[self.bench])
        start = start or START.get(index) or self.uni.first_date()
        self.cal = [d for d in cal if d >= max(start, self.uni.first_date())]
        self.m_ends = month_end_dates(self.cal)
        self.exec_of = {me: next_trading_day(self.cal, me) for me in self.m_ends}
        # 每個月底的合格組員（當天有價）與行業分組
        self.members: dict[date, list[str]] = {}
        self.holes = self.slots = 0
        self._hold_cache: dict = {}
        self._score_cache: dict = {}
        for me in self.m_ends:
            listed = self.uni.listed_at(me)
            mem = sorted(t for t in self.uni.eligible_at(me, self.first) if me in self.series[t])
            self.members[me] = mem
            self.slots += listed
            self.holes += listed - len(mem)

    def close_on_or_before(self, t: str, d: date) -> float | None:
        ds = self.dates[t]
        i = bisect.bisect_right(ds, d) - 1
        return self.series[t][ds[i]][1] if i >= 0 else None

    def trailing(self, t: str, me: date, months: int) -> float | None:
        """me 往回 months 個月底的總報酬（AdjClose）；價格歷史不滿就 None。
        回看起點早於回測起點時（樣本頭幾個月）用日曆月底 + 當日或之前最後收市。"""
        i = self.m_ends.index(me)
        if i >= months:
            d_start = self.m_ends[i - months]
        else:
            y, m = me.year, me.month - months
            while m <= 0:
                y, m = y - 1, m + 12
            d_start = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        if self.first[t] > d_start:
            return None
        p0 = self.close_on_or_before(t, d_start)
        p1 = self.series[t][me][1]
        return p1 / p0 - 1 if p0 else None

    def sector_groups(self, me: date) -> dict[str, list[str]]:
        g = defaultdict(list)
        for t in self.members[me]:
            s = self.sectors.get(t)
            if s:
                g[s].append(t)
        return {s: v for s, v in g.items() if len(v) >= MIN_MEMBERS}

    def ranked_sectors(self, me: date, L: int) -> tuple[dict[str, list[str]], list[str]]:
        """(行業 -> 組員, 按過去 L 月組員平均報酬排序的行業)；各參數格/隨機對照共用快取。"""
        key = (me, L)
        if key not in self._score_cache:
            groups = self.sector_groups(me)
            score = {}
            for s, mem in groups.items():
                trs = [r for r in (self.trailing(t, me, L) for t in mem) if r is not None]
                if trs:
                    score[s] = sum(trs) / len(trs)
            self._score_cache[key] = (groups, sorted(score, key=score.get, reverse=True))
        return self._score_cache[key]

    def hold_return(self, t: str, d0: date, d1: date) -> float | None:
        """d0 開盤進場到 d1 開盤出場（AdjOpen，含股息）；中途沒價就用最後可得收市結算。"""
        key = (t, d0, d1)
        if key not in self._hold_cache:
            self._hold_cache[key] = self._hold_return(t, d0, d1)
        return self._hold_cache[key]

    def _hold_return(self, t: str, d0: date, d1: date) -> float | None:
        s = self.series[t]
        if d0 not in s:
            return None
        p0 = s[d0][0]
        if d1 in s:
            p1 = s[d1][0]
        else:
            last = [d for d in self.dates[t] if d0 <= d < d1]
            if not last:
                return None
            p1 = s[last[-1]][1]
        return p1 / p0 - 1 if p0 > 0 else None

    def portfolio_return(self, weights: dict[str, float], d0: date, d1: date) -> float:
        tot = wsum = 0.0
        for t, w in weights.items():
            r = self.hold_return(t, d0, d1)
            if r is None:
                continue  # 買不進（停牌），這期不算
            tot += w * r
            wsum += w
        return tot / wsum if wsum else 0.0

    def run(self, L: int, N: int, picker=None) -> dict:
        """picker(me, ranked_sectors) -> 被選行業；預設取前 N（隨機對照組傳自訂函數）。"""
        prev_w: dict[str, float] = {}
        rets, bench, ew, months, picks = [], [], [], [], []
        for i, me in enumerate(self.m_ends[:-1]):
            d0, d1 = self.exec_of[me], self.exec_of[self.m_ends[i + 1]]
            if d0 is None or d1 is None:
                continue
            groups, ranked = self.ranked_sectors(me, L)
            if len(ranked) < N:
                continue
            chosen = picker(me, ranked) if picker else ranked[:N]
            w = {}
            for s in chosen:
                for t in groups[s]:
                    w[t] = w.get(t, 0) + 1 / N / len(groups[s])
            turnover = sum(abs(w.get(t, 0) - prev_w.get(t, 0)) for t in set(w) | set(prev_w))
            r = self.portfolio_return(w, d0, d1) - turnover * self.cost
            b = self.hold_return(self.bench, d0, d1)
            e = self.portfolio_return({t: 1 / len(self.members[me]) for t in self.members[me]}, d0, d1)
            if b is None:
                continue
            rets.append(r)
            bench.append(b)
            ew.append(e)
            months.append(d0)
            picks.append(chosen)
            prev_w = w
        return {"rets": rets, "bench": bench, "ew": ew, "months": months, "picks": picks}


def summarize(res: dict) -> dict:
    rets, bench, ew = res["rets"], res["bench"], res["ew"]
    eq = eqb = 1.0
    peak, mdd = 1.0, 0.0
    for r, b in zip(rets, bench):
        eq *= 1 + r
        eqb *= 1 + b
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    c_b, c_e = capm(rets, bench), capm(rets, ew)
    return {"n": len(rets), "total": eq - 1, "bench_total": eqb - 1, "mdd": mdd,
            "alpha_t": c_b["alpha_t"], "alpha_ann": c_b["alpha_ann"], "beta": c_b["beta"],
            "alpha_t_ew": c_e["alpha_t"], "alpha_ann_ew": c_e["alpha_ann"],
            "t_excess": t_stat([r - b for r, b in zip(rets, bench)])}


def split(res: dict, cut: date) -> tuple[dict, dict]:
    a = {k: [x for x, d in zip(res[k], res["months"]) if d < cut] for k in ("rets", "bench", "ew", "months")}
    b = {k: [x for x, d in zip(res[k], res["months"]) if d >= cut] for k in ("rets", "bench", "ew", "months")}
    return a, b


def fmt(s: dict) -> str:
    return (f"{s['n']} 月  總報酬 {s['total']:+.0%} vs 基準 {s['bench_total']:+.0%}  "
            f"alpha {s['alpha_ann']:+.1%}/年 t={s['alpha_t']:.2f} beta {s['beta']:.2f}  "
            f"| vs 等權 alpha t={s['alpha_t_ew']:.2f}  MDD {s['mdd']:.0%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="hsi", choices=[k for k in INDICES if k != "djia"])
    ap.add_argument("--L", type=int, default=6)
    ap.add_argument("--N", type=int, default=3)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--permutation", action="store_true")
    ap.add_argument("--attribution", action="store_true")
    args = ap.parse_args()

    mk = Market(args.index)
    print(f"{args.index}：{mk.m_ends[0]} ~ {mk.m_ends[-1]}，{len(mk.m_ends)} 個月底；基準 {mk.bench}；"
          f"成本 {mk.cost * 1e4:.0f}bps；倖存者偏差洞 {mk.holes / max(mk.slots, 1):.1%}")
    res = mk.run(args.L, args.N)
    s = summarize(res)
    print(f"L={args.L} N={args.N}：{fmt(s)}")
    cut = date(2022, 1, 1) if args.index == "hsi" else date(2013, 1, 1)
    for label, part in zip((f"{cut} 前", f"{cut} 起"), split(res, cut)):
        if len(part["rets"]) > 12:
            print(f"   {label}：{fmt(summarize(part))}")
    yrs = defaultdict(lambda: [1.0, 1.0])
    for r, b, d in zip(res["rets"], res["bench"], res["months"]):
        yrs[d.year][0] *= 1 + r
        yrs[d.year][1] *= 1 + b
    print("   按年（策略/基準）：" + "  ".join(f"{y}:{a - 1:+.0%}/{b - 1:+.0%}" for y, (a, b) in sorted(yrs.items())))
    from collections import Counter
    cnt = Counter(x for p in res["picks"] for x in p)
    print("   行業入選次數：" + "、".join(f"{k} {v}" for k, v in cnt.most_common()))

    if args.grid:
        print("\n鄰域（alpha t vs 基準 / vs 等權）：")
        print("       " + "".join(f"   N={n}        " for n in GRID_N))
        for L in GRID_L:
            cells = []
            for n in GRID_N:
                g = summarize(mk.run(L, n))
                cells.append(f"{g['alpha_t']:5.2f} / {g['alpha_t_ew']:5.2f}")
            print(f"L={L:>2}  " + "   ".join(cells))

    if args.permutation:
        ts = []
        for seed in range(200):
            rng = random.Random(seed)
            r = mk.run(args.L, args.N, picker=lambda me, ranked: rng.sample(ranked, args.N))
            ts.append(summarize(r)["alpha_t"])
        ts.sort()
        pct = sum(x < s["alpha_t"] for x in ts) / len(ts)
        print(f"\n隨機行業對照組 200 次：alpha t 中位數 {ts[100]:.2f}、第 90 百分位 {ts[179]:.2f}；"
              f"預設格 {s['alpha_t']:.2f} 位於第 {pct:.1%} 百分位（{sum(x < s['alpha_t'] for x in ts)}/200 次隨機低於它）")

    if args.attribution:
        attribution(mk)


def attribution(mk: "Market") -> None:
    """第二部分：低波動 A / 高股息的 Brinson 行業歸因（基準 = 全體成分股等權）。"""
    from stock_momentum_backtest import derive_dividends, trailing_vol
    daily = {t: sorted((d, v[1]) for d, v in s.items()) for t, s in mk.series.items()}
    ddates = {t: [d for d, _ in rows] for t, rows in daily.items()}
    divs = {t: derive_dividends(s) for t, s in mk.series.items() if t != mk.bench}

    def pick(me: date, kind: str) -> list[str]:
        sc = []
        for t in mk.members[me]:
            if kind == "lowvol":
                v = trailing_vol(daily[t], ddates[t], me, 252)
                if v is not None:
                    sc.append((-v, t))
            else:
                if mk.first[t] > me - timedelta(days=round(12 * 30.4375)):
                    continue
                ttm = sum(x for d, x in divs[t] if me - timedelta(days=round(12 * 30.4375)) < d <= me)
                c = mk.series[t][me][2]
                if ttm > 0 and c > 0:
                    sc.append((ttm / c, t))
        return [t for _, t in sorted(sc, reverse=True)[:10]]

    for kind, label in (("lowvol", "低波動 A（252 日、10 檔）"), ("divyield", "高股息（12 月、10 檔）")):
        rows = []
        for i, me in enumerate(mk.m_ends[:-1]):
            d0, d1 = mk.exec_of[me], mk.exec_of[mk.m_ends[i + 1]]
            if d0 is None or d1 is None or not mk.members[me]:
                continue
            port = pick(me, kind)
            if not port:
                continue
            sec = lambda t: mk.sectors.get(t, "未分類")  # noqa: E731
            bench_by = defaultdict(list)
            for t in mk.members[me]:
                r = mk.hold_return(t, d0, d1)
                if r is not None:
                    bench_by[sec(t)].append(r)
            port_by = defaultdict(list)
            for t in port:
                r = mk.hold_return(t, d0, d1)
                if r is not None:
                    port_by[sec(t)].append(r)
            nb = sum(len(v) for v in bench_by.values())
            npf = sum(len(v) for v in port_by.values())
            if not nb or not npf:
                continue
            rb = sum(sum(v) for v in bench_by.values()) / nb
            alloc = sel = 0.0
            for s_, v in bench_by.items():
                wb = len(v) / nb
                wp = len(port_by.get(s_, [])) / npf
                rbs = sum(v) / len(v)
                alloc += (wp - wb) * (rbs - rb)
                if port_by.get(s_):
                    sel += wp * (sum(port_by[s_]) / len(port_by[s_]) - rbs)
            rows.append((d0, alloc, sel))
        print(f"\n行業歸因——{label}，基準 = 全體成分股等權（月平均，年化 ×12）：")
        for lab, rr in (("全期", rows), ("2022 前", [r for r in rows if r[0] < date(2022, 1, 1)]),
                        ("2022 起", [r for r in rows if r[0] >= date(2022, 1, 1)])):
            if rr:
                a = [x[1] for x in rr]
                b = [x[2] for x in rr]
                print(f"   {lab}（{len(rr)} 月）：行業配置 {sum(a) / len(a) * 12:+.1%}/年 (t={t_stat(a):.2f})  "
                      f"行業內選股 {sum(b) / len(b) * 12:+.1%}/年 (t={t_stat(b):.2f})")


if __name__ == "__main__":
    main()
