"""界內證 vs 恒指期權：無模型（model-free）公平價區間、複製成本、套利條件（見 INLINE_WARRANTS.md）。

離線（repo 內港交所結算價，收市後版本）：
    python3 research/warrants_cbbc/inline_vs_options.py --demo
    python3 research/warrants_cbbc/inline_vs_options.py --date 2026-10-09 --expiry 2026-10            # 幾組假想區間的公平價表
    python3 research/warrants_cbbc/inline_vs_options.py --date 2026-10-09 --expiry 2026-10 --lower 23400 --upper 25000 --inline-ask 0.62

即時（在裝有 Futu OpenD 的電腦上，127.0.0.1:11111）：
    python3 research/warrants_cbbc/inline_vs_options.py --live [--csv data/inline_scan/今天.csv] [--owner HK.800000]
  步驟：get_warrant 取相關資產為恒指的所有界內證（代號、上限價、下限價、到期日、買賣價）→ 每個到期日用 get_option_chain
  取同日到期的恒指期權 → get_market_snapshot 取六個相關行使價的買賣價 → 逐隻算公平價區間、相對中值溢價、鎖定套利淨額、自做 condor 成本。
  期權抓不到時退回用 repo 內最近一天的結算價（會標明）。

資料：data/hkex_options/series/hsio_<年>.csv.gz（港交所每日報告的官方結算價 O.Q.P.，scripts/hkex_option_iv.py 抓的）。
界內證到期：界內 HK$1、界外 HK$0.25 → 價值 = DF × [0.25 + 0.75 × P(L ≤ S_T ≤ U)]。
P(S_T ≥ K) 的無模型界：下界 = [C(a) − C(b)]/(b−a)，a＝不小於 K 的最近行使價、b＝再上一格；上界 = [C(a′) − C(b′)]/(b′−a′)，b′＝不大於 K 的最近行使價、a′＝再下一格。
P(L ≤ S ≤ U) = P(S ≥ L) − P(S > U) → 下界 = 下界(L) − 上界(U)，上界 = 上界(L) − 下界(U)。
鎖定套利（只能買界內證、不能沽）：買界內證 ＋ 沽出「次複製組合」＝ 沽 call condor（沽 a_L、買 b_L、買 a′_U、沽 b′_U）× 0.75/w，
條件：次複製組合賣出所得（沽腳 bid、買腳 ask）＋ 0.25×DF − 期權費用 > 界內證賣價 + 界內證費用。
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import gzip
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERIES_DIR = ROOT / "data" / "hkex_options" / "series"
MULT = 50             # 恒指期權每點 HK$
PAY_IN, PAY_OUT = 1.0, 0.25
LOT_INLINE = 10_000   # 界內證一手（常見）
INDEX_CODES = {"HK.800000": "恒指", "HK.800100": "國指", "HK.800700": "科指"}


# ---------- 期權鏈抽象：以 call 計價（put 用買賣權平價換成 call），提供 bid／mid／ask ----------
@dataclass
class Chain:
    strikes: list[int]                 # 已排序
    call_bid: dict[int, float]
    call_ask: dict[int, float]
    forward: float
    label: str                         # 資料來源說明

    def mid(self, k: int) -> float:
        return 0.5 * (self.call_bid[k] + self.call_ask[k])

    def grid(self, k: float) -> tuple[int, int, int, int]:
        """回傳 (a, b, a2, b2)：a＝不小於 k 的最近行使價、b＝其上一格；b2＝不大於 k 的最近行使價、a2＝其下一格。"""
        i = bisect.bisect_left(self.strikes, k)
        if i >= len(self.strikes) - 1 or i == 0:
            raise KeyError(f"行使價 {k} 超出鏈的範圍 {self.strikes[0]}–{self.strikes[-1]}")
        a = self.strikes[i]
        b = self.strikes[i + 1]
        b2 = self.strikes[i] if self.strikes[i] == k else self.strikes[i - 1]
        j = self.strikes.index(b2)
        if j == 0:
            raise KeyError(f"行使價 {k} 下方沒有再一格")
        a2 = self.strikes[j - 1]
        return a, b, a2, b2


def chain_from_settlement(date: str, expiry: str, half_spread_pts: float) -> Chain:
    """repo 內結算價（視為中價）± 假設半差價。"""
    path = SERIES_DIR / f"hsio_{date[:4]}.csv.gz"
    if not path.exists():
        sys.exit(f"找不到 {path}；先跑 GitHub Actions hkex-option-iv 抓資料")
    calls, puts = {}, {}
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            if r["date"] == date and r["expiry"] == expiry:
                (calls if r["cp"] == "C" else puts)[int(r["strike"])] = float(r["oqp"])
    if not calls:
        sys.exit(f"{date} {expiry} 沒有資料")
    k0 = min((k for k in calls if k in puts), key=lambda k: abs(calls[k] - puts[k]))
    fwd = k0 + calls[k0] - puts[k0]
    bid, ask = {}, {}
    for k in sorted(set(calls) | set(puts)):
        if k >= fwd and k in calls:
            m = calls[k]
        elif k < fwd and k in puts:
            m = puts[k] + (fwd - k)
        else:
            continue
        bid[k], ask[k] = m - half_spread_pts, m + half_spread_pts
    return Chain(sorted(bid), bid, ask, fwd, f"港交所結算價 {date} {expiry}（半差價 {half_spread_pts:.0f} 點假設）")


def latest_settlement_date(expiry_month: str) -> str | None:
    path = SERIES_DIR / f"hsio_{dt.date.today().year}.csv.gz"
    if not path.exists():
        return None
    days = set()
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            if r["expiry"] == expiry_month:
                days.add(r["date"])
    return max(days) if days else None


# ---------- 數學 ----------
def digital_bounds(ch: Chain, k: float, side: str) -> tuple[float, float, float]:
    """P(S_T ≥ k) 的 (下界, 中值, 上界)。side='sell'：下界用沽出次複製的實際成交價（沽 a 用 bid、買 b 用 ask）；
    side='mid'：全部用中價（公平價區間）。"""
    a, b, a2, b2 = ch.grid(k)
    if side == "sell":
        lo = (ch.call_bid[a] - ch.call_ask[b]) / (b - a)
    else:
        lo = (ch.mid(a) - ch.mid(b)) / (b - a)
    hi = (ch.mid(a2) - ch.mid(b2)) / (b2 - a2)
    mid = 0.5 * (lo if side == "mid" else (ch.mid(a) - ch.mid(b)) / (b - a)) + 0.5 * hi
    clamp = lambda x: min(1.0, max(0.0, x))
    return clamp(lo), clamp(mid), clamp(hi)


def inline_prob_bounds(ch: Chain, lower: float, upper: float) -> tuple[float, float, float]:
    lo_l, mid_l, hi_l = digital_bounds(ch, lower, "mid")
    lo_u, mid_u, hi_u = digital_bounds(ch, upper, "mid")
    clamp = lambda x: min(1.0, max(0.0, x))
    return clamp(lo_l - hi_u), clamp(mid_l - mid_u), clamp(hi_l - lo_u)


def inline_value(prob: float, df: float = 1.0) -> float:
    return df * (PAY_OUT + (PAY_IN - PAY_OUT) * prob)


def sub_replication_proceeds(ch: Chain, lower: float, upper: float, fee_per_lot_hkd: float, df: float = 1.0) -> tuple[float, float, dict]:
    """沽出次複製組合每份界內證可收到的錢（HK$）＝ 0.25×DF ＋ 0.75 × [CS_sell(L) − CS_buy(U)]。
    L 邊：沽 call a、買 call b（bid／ask）；U 邊：買 call a2、沽 call b2。回傳 (毛收入, 期權費用, 腳位)。"""
    a, b, _, _ = ch.grid(lower)
    _, _, a2, b2 = ch.grid(upper)
    cs_l = (ch.call_bid[a] - ch.call_ask[b]) / (b - a)          # 沽出 1{S≥L} 的次複製，每點
    cs_u = (ch.call_ask[a2] - ch.call_bid[b2]) / (b2 - a2)      # 買入 1{S>U} 的超複製，每點
    gross = PAY_OUT * df + (PAY_IN - PAY_OUT) * (cs_l - cs_u)
    w = min(b - a, b2 - a2)
    inline_per_set = w * MULT / (PAY_IN - PAY_OUT)              # 每組四腳（各一張）對應幾份界內證
    fees = 4 * fee_per_lot_hkd / inline_per_set
    legs = {"sell_call": a, "buy_call": b, "buy_call2": a2, "sell_call2": b2, "inline_per_set": inline_per_set}
    return gross, fees, legs


def long_condor_cost(ch: Chain, lower: float, upper: float, fee_per_lot_hkd: float, df: float = 1.0) -> float:
    """自己買次複製 condor 表達區間看法：每「相當於一份界內證」的成本（HK$，含 0.25 固定部分）。"""
    a, b, _, _ = ch.grid(lower)
    _, _, a2, b2 = ch.grid(upper)
    cs_l = (ch.call_ask[a] - ch.call_bid[b]) / (b - a)
    cs_u = (ch.call_bid[a2] - ch.call_ask[b2]) / (b2 - a2)
    w = min(b - a, b2 - a2)
    return PAY_OUT * df + (PAY_IN - PAY_OUT) * (cs_l - cs_u) + 4 * fee_per_lot_hkd / (w * MULT / (PAY_IN - PAY_OUT))


def inline_buy_cost(ask: float, fee_rate: float = 0.001, fixed_hkd: float = 18.0, lots: int = 10) -> float:
    return ask * (1 + fee_rate) + fixed_hkd / (lots * LOT_INLINE)


def evaluate(ch: Chain, lower: float, upper: float, inline_ask: float | None, fee_lot: float, df: float) -> dict:
    p_lo, p_mid, p_hi = inline_prob_bounds(ch, lower, upper)
    gross, fees, legs = sub_replication_proceeds(ch, lower, upper, fee_lot, df)
    condor = long_condor_cost(ch, lower, upper, fee_lot, df)
    out = {"p_lo": p_lo, "p_mid": p_mid, "p_hi": p_hi, "v_lo": inline_value(p_lo, df), "v_mid": inline_value(p_mid, df),
           "v_hi": inline_value(p_hi, df), "sell_sub": gross, "opt_fees": fees, "lock_threshold": gross - fees, "condor_cost": condor,
           **legs}
    if inline_ask is not None:
        cost = inline_buy_cost(inline_ask)
        out.update({"inline_ask": inline_ask, "inline_cost": cost, "premium_vs_mid": inline_ask - out["v_mid"],
                    "lock_edge": gross - fees - cost, "inline_cheaper_than_condor": inline_ask < condor})
    return out


# ---------- 離線輸出 ----------
def table(date: str, expiry: str, half_spread: float, fee_lot: float, rate: float, days: int) -> None:
    ch = chain_from_settlement(date, expiry, half_spread)
    df = math.exp(-rate * days / 365)
    k0 = int(round(ch.forward / 200) * 200)
    ranges = [(k0 - d, k0 + d) for d in (400, 600, 800, 1200, 1600)] + [(k0 - 1200, k0 + 400), (k0 - 400, k0 + 1200)]
    print(f"{ch.label}：遠期價 F = {ch.forward:,.0f}，剩 {days} 日，折現 {df:.4f}，每張費用 HK${fee_lot:.0f}")
    print(f"{'區間':<16}{'寬度%':>6}{'P下界':>7}{'P中值':>7}{'P上界':>7} | {'價下界':>7}{'價中值':>7}{'價上界':>7} | {'沽次複製可收':>11}{'期權費':>7}{'套利須賣價<':>11}{'自做condor成本':>13}")
    for lo_k, up_k in ranges:
        try:
            e = evaluate(ch, lo_k, up_k, None, fee_lot, df)
        except KeyError as err:
            print(f"{lo_k}-{up_k}: {err}")
            continue
        print(f"{lo_k:>6}-{up_k:<9}{(up_k - lo_k) / ch.forward * 100:>6.1f}{e['p_lo']:>7.3f}{e['p_mid']:>7.3f}{e['p_hi']:>7.3f} | "
              f"{e['v_lo']:>7.3f}{e['v_mid']:>7.3f}{e['v_hi']:>7.3f} | {e['sell_sub']:>11.3f}{e['opt_fees']:>7.3f}{e['lock_threshold']:>11.3f}{e['condor_cost']:>13.3f}")
    print("說明：價下界／上界＝用中價算的無模型區間；「套利須賣價<」已扣期權差價與費用，界內證賣價加費用低於它才是鎖定利潤。")
    print("「自做 condor 成本」＝不買界內證、直接買次複製 condor 表達同一區間看法的每份成本（含 0.25 固定部分），可與界內證賣價直接比。")


def check_one(date, expiry, lower, upper, inline_ask, half_spread, fee_lot, rate, days) -> None:
    ch = chain_from_settlement(date, expiry, half_spread)
    df = math.exp(-rate * days / 365)
    e = evaluate(ch, lower, upper, inline_ask, fee_lot, df)
    print_eval(f"{ch.label}  F={ch.forward:,.0f}", lower, upper, e)


def print_eval(head: str, lower, upper, e: dict) -> None:
    print(f"{head}  區間 {lower:.0f}-{upper:.0f}  P(界內) ∈ [{e['p_lo']:.3f}, {e['p_hi']:.3f}]（中值 {e['p_mid']:.3f}）")
    print(f"  公平價 ∈ [{e['v_lo']:.3f}, {e['v_hi']:.3f}]，中值 {e['v_mid']:.3f}；賣價 {e['inline_ask']:.3f} → 相對中值 "
          f"{'溢價' if e['premium_vs_mid'] > 0 else '折讓'} {abs(e['premium_vs_mid']):.3f}")
    print(f"  鎖定套利：沽次複製可收 {e['sell_sub']:.3f} − 期權費 {e['opt_fees']:.3f} − 買入成本 {e['inline_cost']:.3f} = {e['lock_edge']:+.3f} HK$/份 "
          f"→ {'✔ 有鎖定利潤' if e['lock_edge'] > 0 else '✘ 沒有'}")
    print(f"  自做 condor 成本 {e['condor_cost']:.3f} → {'界內證較便宜' if e['inline_cheaper_than_condor'] else 'condor 較便宜'}；"
          f"四腳：沽C{e['sell_call']} 買C{e['buy_call']} 買C{e['buy_call2']} 沽C{e['sell_call2']}，每組對應 {e['inline_per_set']:,.0f} 份界內證")


# ---------- 即時（Futu OpenD） ----------
def live(host: str, port: int, owner: str, fee_lot: float, rate: float, csv_path: str | None, half_spread_fallback: float) -> None:
    try:
        import futu as ft  # type: ignore
        ft.OpenQuoteContext
    except (ImportError, AttributeError):
        sys.exit("需要 pip install futu-api；且不要在 repo 根目錄用 python3 -c／互動模式跑（repo 的 futu/ 資料夾會蓋掉套件）")
    import time
    ctx = ft.OpenQuoteContext(host=host, port=port)
    try:
        # 1. 界內證清單
        rows, begin = [], 0
        while True:
            req = ft.WarrantDataFilter()
            req.type_list = [ft.WrtType.INLINE]
            req.begin, req.num = begin, 200
            req.sort_field = ft.SortField.CODE
            ret, data = ctx.get_warrant(owner, req)
            if ret != ft.RET_OK:
                sys.exit(f"get_warrant 失敗：{data}")
            df_w, last_page, all_count = data
            rows.extend(df_w.to_dict("records"))
            begin += len(df_w)
            if last_page or len(df_w) == 0 or begin >= all_count:
                break
            time.sleep(3.1)
        print(f"{INDEX_CODES.get(owner, owner)} 界內證 {len(rows)} 隻")
        if not rows:
            return
        by_expiry: dict[str, list[dict]] = {}
        for r in rows:
            by_expiry.setdefault(str(r["maturity_time"])[:10], []).append(r)

        # 2. 每個到期日的期權鏈 ＋ 快照
        results = []
        today = dt.date.today()
        for exp_date, group in sorted(by_expiry.items()):
            exp = dt.date.fromisoformat(exp_date)
            days = max((exp - today).days, 0)
            dfac = math.exp(-rate * days / 365)
            chain = None
            ret, oc = ctx.get_option_chain(owner, index_option_type=ft.IndexOptionType.NORMAL, start=exp_date, end=exp_date,
                                           option_type=ft.OptionType.ALL)
            time.sleep(3.1)
            note = ""
            if ret == ft.RET_OK and len(oc) > 0:
                oc = oc[oc["strike_time"].astype(str).str[:10] == exp_date]
                codes = list(oc["code"])
                snaps = []
                for i in range(0, len(codes), 400):
                    ret2, snap = ctx.get_market_snapshot(codes[i:i + 400])
                    if ret2 != ft.RET_OK:
                        note = f"快照失敗：{snap}"
                        break
                    snaps.append(snap)
                    time.sleep(0.6)
                if snaps and not note:
                    import pandas as pd
                    snap = pd.concat(snaps)
                    chain = chain_from_snapshot(oc, snap, exp_date)
            else:
                note = f"期權鏈無資料（{exp_date}）：{oc if ret != ft.RET_OK else '可能到期日不是期權到期日'}"
            if chain is None:
                month = exp_date[:7]
                d = latest_settlement_date(month)
                if d:
                    chain = chain_from_settlement(d, month, half_spread_fallback)
                    note = (note + "；" if note else "") + f"退回用 {chain.label}"
                else:
                    print(f"{exp_date}: 沒有期權資料，跳過 {len(group)} 隻（{note}）")
                    continue
            for r in group:
                L, U = float(r["lower_strike_price"] or 0), float(r["upper_strike_price"] or 0)
                ask, bid = float(r["ask_price"] or 0), float(r["bid_price"] or 0)
                if L <= 0 or U <= 0 or ask <= 0:
                    continue
                try:
                    e = evaluate(chain, L, U, ask, fee_lot, dfac)
                except KeyError as err:
                    e = {"error": str(err)}
                results.append({"code": r["stock"], "name": r["name"], "issuer": r["issuer"], "expiry": exp_date, "days": days,
                                "lower": L, "upper": U, "bid": bid, "ask": ask, "forward": round(chain.forward),
                                "source": chain.label + (f"（{note}）" if note else ""), **e})

        # 3. 輸出
        ok = [x for x in results if "error" not in x]
        ok.sort(key=lambda x: -x["lock_edge"])
        print(f"\n{'代號':<9}{'發行':<6}{'到期':<11}{'區間':<14}{'買':>6}{'賣':>6}{'公平中值':>8}{'溢價':>7}{'鎖定淨額':>8}{'condor':>7} 來源")
        for x in ok:
            print(f"{x['code']:<9}{str(x['issuer'])[:5]:<6}{x['expiry']:<11}{x['lower']:.0f}-{x['upper']:.0f}{'':<2}{x['bid']:>6.3f}{x['ask']:>6.3f}"
                  f"{x['v_mid']:>8.3f}{x['premium_vs_mid']:>+7.3f}{x['lock_edge']:>+8.3f}{x['condor_cost']:>7.3f} {x['source'][:28]}")
        for x in results:
            if "error" in x:
                print(f"{x['code']} {x['lower']:.0f}-{x['upper']:.0f}: {x['error']}")
        if ok:
            n_lock = sum(1 for x in ok if x["lock_edge"] > 0)
            n_cheap = sum(1 for x in ok if x["inline_cheaper_than_condor"])
            prem = sorted(x["premium_vs_mid"] for x in ok)
            print(f"\n{len(ok)} 隻可算：鎖定套利 ✔ {n_lock} 隻；界內證賣價低於自做 condor 成本 {n_cheap} 隻；"
                  f"賣價相對公平中值的溢價 中位 {prem[len(prem) // 2]:+.3f}、最低 {prem[0]:+.3f}、最高 {prem[-1]:+.3f}")
        if csv_path and results:
            p = Path(csv_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            keys = sorted({k for x in results for k in x})
            with open(p, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["date"] + keys)
                w.writeheader()
                for x in results:
                    w.writerow({"date": today.isoformat(), **x})
            print(f"已寫入 {p}")
    finally:
        ctx.close()


def chain_from_snapshot(oc, snap, exp_date: str) -> Chain:
    """Futu 期權鏈 ＋ 快照 → Chain（call 用自己的 bid/ask；K < F 的用 put 以平價換成 call）。"""
    info = {r["code"]: (str(r["option_type"]), float(r["strike_price"])) for r in oc.to_dict("records")}
    calls, puts = {}, {}
    for r in snap.to_dict("records"):
        typ, k = info.get(r["code"], (None, None))
        if typ is None:
            continue
        bid, ask = float(r.get("bid_price") or 0), float(r.get("ask_price") or 0)
        if bid <= 0 or ask <= 0:
            continue
        (calls if "CALL" in typ.upper() else puts)[int(round(k))] = (bid, ask)
    both = [k for k in calls if k in puts]
    if not both:
        raise KeyError("快照裡沒有同時有 call、put 買賣價的行使價")
    k0 = min(both, key=lambda k: abs(sum(calls[k]) / 2 - sum(puts[k]) / 2))
    fwd = k0 + sum(calls[k0]) / 2 - sum(puts[k0]) / 2
    bid, ask = {}, {}
    for k in sorted(set(calls) | set(puts)):
        if k >= fwd and k in calls:
            bid[k], ask[k] = calls[k]
        elif k < fwd and k in puts:
            bid[k], ask[k] = puts[k][0] + (fwd - k), puts[k][1] + (fwd - k)
    return Chain(sorted(bid), bid, ask, fwd, f"Futu 即時期權買賣價 {exp_date}")


# ---------- 自我檢查 ----------
def demo() -> None:
    F, s = 24_000.0, 0.035
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    def bs_call(k):
        d1 = (math.log(F / k) + 0.5 * s * s) / s
        return F * N(d1) - k * N(d1 - s)
    strikes = list(range(21_000, 27_001, 200))
    mk = lambda hs: Chain(strikes, {k: bs_call(k) - hs for k in strikes}, {k: bs_call(k) + hs for k in strikes}, F, "合成")
    ch0 = mk(0.0)
    for k in (23_000, 24_000, 25_000):
        lo, mid, hi = digital_bounds(ch0, k, "mid")
        exact = N((math.log(F / k) - 0.5 * s * s) / s)
        assert lo <= exact + 1e-9 <= hi + 2e-9 and abs(mid - exact) < 0.01, (k, lo, exact, hi)
    L, U = 23_200, 24_800
    lo, mid, hi = inline_prob_bounds(ch0, L, U)
    exact = N((math.log(F / L) - 0.5 * s * s) / s) - N((math.log(F / U) - 0.5 * s * s) / s)
    assert lo <= exact <= hi and abs(mid - exact) < 0.01
    # 次複製組合到期收益處處 ≤ 界內證收益
    a, b, _, _ = ch0.grid(L)
    _, _, a2, b2 = ch0.grid(U)
    for S in range(22_000, 26_001, 50):
        cs = lambda x, y: (max(S - x, 0) - max(S - y, 0)) / (y - x)
        sub = PAY_OUT + (PAY_IN - PAY_OUT) * (cs(a, b) - cs(a2, b2))
        assert sub <= (PAY_IN if L <= S <= U else PAY_OUT) + 1e-9, (S, sub)
    # 零差價時沽次複製可收 ＝ 下界價；不在格點上的 L、U 也要能算且界更寬
    gross, fees, _ = sub_replication_proceeds(ch0, L, U, 0.0)
    assert abs(gross - inline_value(lo)) < 1e-9 and fees == 0
    lo2, _, hi2 = inline_prob_bounds(ch0, 23_250, 24_750)
    assert lo2 <= lo + 1e-9 and hi2 >= hi - 1e-9
    e = evaluate(mk(3.0), L, U, 0.70, 30.0, 1.0)
    assert e["lock_edge"] < 0 and e["premium_vs_mid"] < 0
    print("自我檢查通過。")
    print(f"合成例：F 24,000、σ_T 3.5%、區間 23,200–24,800 → P(界內) 精確 {exact:.3f}，無模型界 [{lo:.3f}, {hi:.3f}]，"
          f"界內證價 [{inline_value(lo):.3f}, {inline_value(hi):.3f}]")
    print(f"每腳半差價 3 點、每張 HK$30：套利門檻 {e['lock_threshold']:.3f}；中值公平價 {e['v_mid']:.3f} → 界內證要比中值便宜 "
          f"{e['v_mid'] - e['lock_threshold']:.3f} 才鎖得到；自做 condor 成本 {e['condor_cost']:.3f}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--live", action="store_true", help="連 Futu OpenD 掃描全部界內證")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11111)
    p.add_argument("--owner", default="HK.800000", help="指數代號：HK.800000 恒指（預設）、HK.800100 國指、HK.800700 科指")
    p.add_argument("--csv", help="--live 結果另存 CSV（例 data/inline_scan/2026-10-13.csv）")
    p.add_argument("--date", default="2026-10-09")
    p.add_argument("--expiry", default="2026-10", help="月期權到期，如 2026-10")
    p.add_argument("--lower", type=float)
    p.add_argument("--upper", type=float)
    p.add_argument("--inline-ask", type=float, help="界內證賣價（HK$）")
    p.add_argument("--half-spread", type=float, default=3.0, help="離線模式期權每腳半差價（點，預設 3）")
    p.add_argument("--fee-lot", type=float, default=30.0, help="期權每張費用 HK$（交易所＋徵費＋佣金，預設 30）")
    p.add_argument("--rate", type=float, default=0.03, help="折現年率（預設 3%%）")
    p.add_argument("--days", type=int, default=20, help="離線模式到期剩餘日曆日")
    a = p.parse_args()
    if a.demo:
        demo()
    elif a.live:
        live(a.host, a.port, a.owner, a.fee_lot, a.rate, a.csv, a.half_spread)
    elif a.lower and a.upper:
        if a.inline_ask is None:
            sys.exit("請給 --inline-ask")
        check_one(a.date, a.expiry, a.lower, a.upper, a.inline_ask, a.half_spread, a.fee_lot, a.rate, a.days)
    else:
        table(a.date, a.expiry, a.half_spread, a.fee_lot, a.rate, a.days)


if __name__ == "__main__":
    main()
