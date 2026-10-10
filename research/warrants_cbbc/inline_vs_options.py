"""界內證 vs 恒指期權：無模型（model-free）公平價區間、複製成本、套利條件（見 INLINE_WARRANTS.md）。

    python3 research/warrants_cbbc/inline_vs_options.py --demo
    python3 research/warrants_cbbc/inline_vs_options.py --date 2026-10-09 --expiry 2026-10            # 幾組假想區間的公平價表
    python3 research/warrants_cbbc/inline_vs_options.py --date 2026-10-09 --expiry 2026-10 --lower 23400 --upper 25000 --inline-ask 0.62

資料：data/hkex_options/series/hsio_<年>.csv.gz（港交所每日報告的官方結算價 O.Q.P.，scripts/hkex_option_iv.py 抓的）。
界內證到期：界內 HK$1、界外 HK$0.25 → 價值 = DF × [0.25 + 0.75 × P(L ≤ S_T ≤ U)]。
P(S_T ≥ K) 的無模型界：下界 = [C(K) − C(K+w)]/w，上界 = [C(K−w) − C(K)]/w（w＝行使價間距 200）。
P(L ≤ S ≤ U) = P(S ≥ L) − P(S > U) → 下界 = 下界(L) − 上界(U)，上界 = 上界(L) − 下界(U)。
鎖定套利（只能買界內證、不能沽）：買界內證 ＋ 沽出「次複製組合」＝ 沽 call condor（沽 L、買 L+w、買 U−w、沽 U）× 0.75/w，
條件：0.75/w × [C_bid(L) − C_ask(L+w) − C_ask(U−w) + C_bid(U)] + 0.25×DF − 期權費用 > 界內證賣價 + 界內證費用。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES_DIR = ROOT / "data" / "hkex_options" / "series"
STEP = 200            # 恒指月期權行使價間距（點）
MULT = 50             # 恒指期權每點 HK$
PAY_IN, PAY_OUT = 1.0, 0.25
LOT_INLINE = 10_000   # 界內證一手（常見）


# ---------- 資料 ----------
def load_chain(date: str, expiry: str) -> tuple[dict[int, float], dict[int, float]]:
    """回傳 (call 結算價 by strike, put 結算價 by strike)，單位：點。"""
    year = date[:4]
    path = SERIES_DIR / f"hsio_{year}.csv.gz"
    if not path.exists():
        sys.exit(f"找不到 {path}；先跑 GitHub Actions hkex-option-iv 抓資料")
    calls, puts = {}, {}
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            if r["date"] != date or r["expiry"] != expiry:
                continue
            k, v = int(r["strike"]), float(r["oqp"])
            (calls if r["cp"] == "C" else puts)[k] = v
    if not calls:
        sys.exit(f"{date} {expiry} 沒有資料")
    return calls, puts


def forward_from_chain(calls: dict[int, float], puts: dict[int, float]) -> float:
    k0 = min((k for k in calls if k in puts), key=lambda k: abs(calls[k] - puts[k]))
    return k0 + calls[k0] - puts[k0]


def synthetic_call(calls: dict[int, float], puts: dict[int, float], fwd: float, k: int) -> float:
    """用價外那邊的報價（流通較好）：K ≥ F 用 call；K < F 用 put ＋ (F − K)（買賣權平價，折現忽略）。"""
    if k >= fwd:
        if k not in calls:
            raise KeyError(k)
        return calls[k]
    if k not in puts:
        raise KeyError(k)
    return puts[k] + (fwd - k)


# ---------- 數學 ----------
def digital_bounds(c, k: int, w: int = STEP) -> tuple[float, float, float]:
    """P(S_T ≥ k) 的 (下界, 中值, 上界)。c(k) 回傳合成 call 價。"""
    lo = (c(k) - c(k + w)) / w
    hi = (c(k - w) - c(k)) / w
    mid = (c(k - w) - c(k + w)) / (2 * w)
    clamp = lambda x: min(1.0, max(0.0, x))
    return clamp(lo), clamp(mid), clamp(hi)


def inline_bounds(c, lower: int, upper: int, w: int = STEP) -> tuple[float, float, float]:
    """P(L ≤ S_T ≤ U) 的 (下界, 中值, 上界)。"""
    lo_l, mid_l, hi_l = digital_bounds(c, lower, w)
    lo_u, mid_u, hi_u = digital_bounds(c, upper, w)
    clamp = lambda x: min(1.0, max(0.0, x))
    return clamp(lo_l - hi_u), clamp(mid_l - mid_u), clamp(hi_l - lo_u)


def inline_value(prob: float, df: float = 1.0) -> float:
    return df * (PAY_OUT + (PAY_IN - PAY_OUT) * prob)


def sub_replication_proceeds(c, lower: int, upper: int, half_spread_pts: float, fee_per_lot_hkd: float,
                             df: float = 1.0, w: int = STEP) -> tuple[float, float]:
    """沽出次複製組合，每份界內證可收到的錢（HK$）＝ 0.25×DF ＋ 0.75/w × condor 淨收入（沽腳用 bid、買腳用 ask）。
    回傳 (毛收入, 期權費用)，皆以每份界內證計。"""
    bid = lambda k: c(k) - half_spread_pts
    ask = lambda k: c(k) + half_spread_pts
    condor_pts = bid(lower) - ask(lower + w) - ask(upper - w) + bid(upper)
    gross = PAY_OUT * df + (PAY_IN - PAY_OUT) / w * condor_pts
    # 每一組 condor（4 腳）對應 w×MULT/(0.75) 份界內證
    inline_per_set = w * MULT / (PAY_IN - PAY_OUT)
    fees = 4 * fee_per_lot_hkd / inline_per_set
    return gross, fees


def long_condor_cost(c, lower: int, upper: int, half_spread_pts: float, fee_per_lot_hkd: float, w: int = STEP) -> float:
    """想自己做區間看法：買入次複製 condor（買 L、沽 L+w、沽 U−w、買 U）每「相當於一份界內證」的成本（HK$，不含 0.25 固定部分）。"""
    bid = lambda k: c(k) - half_spread_pts
    ask = lambda k: c(k) + half_spread_pts
    condor_pts = ask(lower) - bid(lower + w) - bid(upper - w) + ask(upper)
    inline_per_set = w * MULT / (PAY_IN - PAY_OUT)
    return (PAY_IN - PAY_OUT) / w * condor_pts + 4 * fee_per_lot_hkd / inline_per_set


def inline_buy_cost(ask: float, fee_rate: float = 0.001, fixed_hkd: float = 18.0, lots: int = 10) -> float:
    """買入界內證每份成本（HK$）：賣價 ＋ 法定費用與佣金 ＋ 平台費攤分。"""
    return ask * (1 + fee_rate) + fixed_hkd / (lots * LOT_INLINE)


# ---------- 輸出 ----------
def table(date: str, expiry: str, ranges: list[tuple[int, int]], half_spread: float, fee_lot: float, rate: float, days: int) -> None:
    calls, puts = load_chain(date, expiry)
    fwd = forward_from_chain(calls, puts)
    c = lambda k: synthetic_call(calls, puts, fwd, k)
    df = math.exp(-rate * days / 365)
    print(f"{date} 恒指期權 {expiry} 到期：遠期價 F = {fwd:,.0f}，剩 {days} 日，折現 {df:.4f}，行使價間距 {STEP}，"
          f"期權每腳半差價 {half_spread:.0f} 點、每張費用 HK${fee_lot:.0f}")
    print(f"{'區間':<16}{'寬度%':>6}{'P下界':>7}{'P中值':>7}{'P上界':>7} | {'價下界':>7}{'價中值':>7}{'價上界':>7} | {'沽次複製可收':>11}{'期權費':>7}{'套利須賣價<':>11}{'自做condor成本':>13}")
    for lo_k, up_k in ranges:
        try:
            p_lo, p_mid, p_hi = inline_bounds(c, lo_k, up_k)
            gross, fees = sub_replication_proceeds(c, lo_k, up_k, half_spread, fee_lot, df)
            condor = long_condor_cost(c, lo_k, up_k, half_spread, fee_lot)
        except KeyError as e:
            print(f"{lo_k}-{up_k}: 缺行使價 {e}")
            continue
        be = gross - fees            # 界內證賣價（含費用）要低於這個數才鎖得到
        width = (up_k - lo_k) / fwd * 100
        print(f"{lo_k:>6}-{up_k:<9}{width:>6.1f}{p_lo:>7.3f}{p_mid:>7.3f}{p_hi:>7.3f} | "
              f"{inline_value(p_lo, df):>7.3f}{inline_value(p_mid, df):>7.3f}{inline_value(p_hi, df):>7.3f} | "
              f"{gross:>11.3f}{fees:>7.3f}{be:>11.3f}{PAY_OUT * df + condor:>13.3f}")
    print("說明：價下界／上界＝用結算價（視為中價）算的無模型區間；「套利須賣價<」已扣期權差價與費用，界內證賣價加費用低於它才是鎖定利潤。")
    print("「自做 condor 成本」＝不買界內證、直接買次複製 condor 表達同一區間看法的每份成本（含 0.25 固定部分），可與界內證賣價直接比。")


def check_one(date, expiry, lower, upper, inline_ask, half_spread, fee_lot, rate, days) -> None:
    calls, puts = load_chain(date, expiry)
    fwd = forward_from_chain(calls, puts)
    c = lambda k: synthetic_call(calls, puts, fwd, k)
    df = math.exp(-rate * days / 365)
    p_lo, p_mid, p_hi = inline_bounds(c, lower, upper)
    gross, fees = sub_replication_proceeds(c, lower, upper, half_spread, fee_lot, df)
    cost = inline_buy_cost(inline_ask)
    edge = gross - fees - cost
    print(f"F={fwd:,.0f}  區間 {lower}-{upper}  P(界內) ∈ [{p_lo:.3f}, {p_hi:.3f}]（中值 {p_mid:.3f}）")
    print(f"界內證公平價 ∈ [{inline_value(p_lo, df):.3f}, {inline_value(p_hi, df):.3f}]，中值 {inline_value(p_mid, df):.3f}；你的賣價 {inline_ask:.3f}"
          f" → 相對中值 {'溢價' if inline_ask > inline_value(p_mid, df) else '折讓'} {abs(inline_ask - inline_value(p_mid, df)):.3f}")
    print(f"鎖定套利：沽次複製可收 {gross:.3f} − 期權費 {fees:.3f} − 買入成本 {cost:.3f} = {edge:+.3f} HK$/份 "
          f"→ {'✔ 有鎖定利潤' if edge > 0 else '✘ 沒有'}")
    print(f"每組 condor（4 腳、各 1 張）對應 {STEP * MULT / (PAY_IN - PAY_OUT):,.0f} 份界內證（≈ {STEP * MULT / (PAY_IN - PAY_OUT) / LOT_INLINE:.1f} 手）")


def demo() -> None:
    # 合成鏈：F=24,000、σ_T=3.5%（≈ 15% IV、20 日）、對數常態，驗證界的方向與 BS 數字
    F, s = 24_000.0, 0.035
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    def bs_call(k):
        d1 = (math.log(F / k) + 0.5 * s * s) / s
        return F * N(d1) - k * N(d1 - s)
    c = bs_call
    for k in (23_000, 24_000, 25_000):
        lo, mid, hi = digital_bounds(c, k)
        d2 = (math.log(F / k) - 0.5 * s * s) / s
        exact = N(d2)
        assert lo <= exact + 1e-9 and exact <= hi + 1e-9, (k, lo, exact, hi)
        assert abs(mid - exact) < 0.01, (k, mid, exact)
    lo, mid, hi = inline_bounds(c, 23_200, 24_800)
    exact = N((math.log(F / 23_200) - 0.5 * s * s) / s) - N((math.log(F / 24_800) - 0.5 * s * s) / s)
    assert lo <= exact <= hi and abs(mid - exact) < 0.01
    # 次複製組合的到期收益在每個 S_T 都 ≤ 界內證收益
    L, U, w = 23_200, 24_800, STEP
    for S in range(22_000, 26_001, 50):
        payoff_inline = PAY_IN if L <= S <= U else PAY_OUT
        cs = lambda a, b: max(S - a, 0) - max(S - b, 0)
        sub = PAY_OUT + (PAY_IN - PAY_OUT) / w * (cs(L, L + w) - cs(U - w, U))
        assert sub <= payoff_inline + 1e-9, (S, sub, payoff_inline)
    # 完美市場（零差價、零費用）下，沽次複製可收 = 下界價
    gross, fees = sub_replication_proceeds(c, L, U, 0.0, 0.0)
    assert abs(gross - inline_value(lo)) < 1e-9 and fees == 0
    print("自我檢查通過。")
    print(f"合成例：F 24,000、σ_T 3.5%、區間 23,200–24,800 → P(界內) 精確 {exact:.3f}，無模型界 [{lo:.3f}, {hi:.3f}]，"
          f"界內證價 [{inline_value(lo):.3f}, {inline_value(hi):.3f}]")
    g3, f3 = sub_replication_proceeds(c, L, U, 3.0, 30.0)
    print(f"每腳半差價 3 點、每張 HK$30：沽次複製可收 {g3:.3f} − 費用 {f3:.3f} = {g3 - f3:.3f}；"
          f"中值公平價 {inline_value(mid):.3f} → 界內證要比中值便宜 {inline_value(mid) - (g3 - f3):.3f} 才鎖得到")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--date", default="2026-10-09")
    p.add_argument("--expiry", default="2026-10", help="月期權到期，如 2026-10")
    p.add_argument("--lower", type=int)
    p.add_argument("--upper", type=int)
    p.add_argument("--inline-ask", type=float, help="界內證賣價（HK$）")
    p.add_argument("--half-spread", type=float, default=3.0, help="期權每腳半差價（點，預設 3）")
    p.add_argument("--fee-lot", type=float, default=30.0, help="期權每張費用 HK$（交易所＋徵費＋佣金，預設 30）")
    p.add_argument("--rate", type=float, default=0.03, help="折現年率（預設 3%%）")
    p.add_argument("--days", type=int, default=20, help="到期剩餘日曆日（折現用）")
    a = p.parse_args()
    if a.demo:
        demo()
        return
    if a.lower and a.upper:
        if a.inline_ask is None:
            sys.exit("請給 --inline-ask")
        check_one(a.date, a.expiry, a.lower, a.upper, a.inline_ask, a.half_spread, a.fee_lot, a.rate, a.days)
        return
    calls, puts = load_chain(a.date, a.expiry)
    fwd = forward_from_chain(calls, puts)
    k0 = int(round(fwd / STEP) * STEP)
    ranges = [(k0 - d, k0 + d) for d in (400, 600, 800, 1200, 1600)] + [(k0 - 1200, k0 + 400), (k0 - 400, k0 + 1200)]
    table(a.date, a.expiry, ranges, a.half_spread, a.fee_lot, a.rate, a.days)


if __name__ == "__main__":
    main()
