"""恒指窩輪 vs 恒指期權：同行使價、同到期日逐隻比對（D 類）。見 MISPRICING_RESEARCH.md 第三節 D。

    python3 research/warrants_cbbc/warrant_iv_scan.py --demo
    python3 research/warrants_cbbc/warrant_iv_scan.py --live [--owner HK.800000] [--csv 檔名] [--max-days 120]

做法（--live，裝有 Futu OpenD 的電腦）：
  1. get_warrant(HK.800000, CALL／PUT) 分頁抓齊恒指認購／認沽證：行使價、到期日、換股比率、買賣價、Futu 的 IV、街貨比。
  2. 按到期日分組；每個到期日 get_option_chain + get_market_snapshot 取恒指期權買賣價（到期日要完全相同，兩邊都以 EAS 結算才能鎖）。
  3. 每隻窩輪：
     - 期權公平價：同行使價有期權就用期權中價；沒有就用相鄰行使價的 IV 線性插值 ＋ Black-Scholes。
     - 溢價 = 窩輪賣價 × 換股比率 ÷ 期權公平價 − 1；窩輪 IV（由賣價反推）− 期權 IV。
     - 鎖定淨額（點）= 同行使價期權 bid − 窩輪賣價 × 換股比率 − 費用：買窩輪、沽期權、持有到期，正數＝無論恒指去哪都賺。
       只能這個方向（窩輪不能沽）。沒有同行使價期權就不算鎖定（只算溢價）。
  4. 印出每個到期日的溢價分佈、IV 差分佈、鎖定 ✔ 清單；--csv 存全部列。

費用假設：期權每張 HK$30（÷50 = 0.6 點）、窩輪 0.1%。期權保證金、窩輪發行商信用風險不在內。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import sys
from pathlib import Path

MULT = 50
INDEX_CODES = {"HK.800000": "恒指", "HK.800100": "國指", "HK.800700": "科指"}


def _N(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(F: float, K: float, T: float, sigma: float, call: bool) -> float:
    if T <= 0 or sigma <= 0:
        return max(F - K, 0.0) if call else max(K - F, 0.0)
    st = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * st * st) / st
    d2 = d1 - st
    return F * _N(d1) - K * _N(d2) if call else K * _N(-d2) - F * _N(-d1)


def implied_vol(price: float, F: float, K: float, T: float, call: bool) -> float | None:
    """二分法反推 IV（價格以指數點計）。無解回 None。"""
    intrinsic = max(F - K, 0.0) if call else max(K - F, 0.0)
    if price <= intrinsic or T <= 0:
        return None
    lo, hi = 0.01, 3.0
    if bs_price(F, K, T, hi, call) < price:
        return None
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bs_price(F, K, T, mid, call) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


class OptionExpiry:
    """一個到期日的恒指期權：strike → (call_bid, call_ask, put_bid, put_ask)，含遠期價與 IV 曲線。"""

    def __init__(self, expiry: dt.date, quotes: dict[float, dict], today: dt.date):
        self.expiry = expiry
        self.quotes = quotes
        self.T = max((expiry - today).days, 1) / 365
        both = [k for k, q in quotes.items() if q.get("c") and q.get("p")]
        if not both:
            raise ValueError("沒有同時有 call、put 買賣價的行使價")
        mid = lambda bidask: 0.5 * (bidask[0] + bidask[1])
        k0 = min(both, key=lambda k: abs(mid(quotes[k]["c"]) - mid(quotes[k]["p"])))
        self.forward = k0 + mid(quotes[k0]["c"]) - mid(quotes[k0]["p"])
        self.strikes = sorted(quotes)
        self.iv = {}
        for k in self.strikes:
            q = quotes[k]
            side = "p" if k < self.forward else "c"
            if q.get(side):
                v = implied_vol(mid(q[side]), self.forward, k, self.T, side == "c")
                if v:
                    self.iv[k] = v

    def iv_at(self, k: float) -> float | None:
        ks = sorted(self.iv)
        if not ks:
            return None
        if k <= ks[0]:
            return self.iv[ks[0]]
        if k >= ks[-1]:
            return self.iv[ks[-1]]
        for a, b in zip(ks, ks[1:]):
            if a <= k <= b:
                w = (k - a) / (b - a)
                return self.iv[a] * (1 - w) + self.iv[b] * w
        return None

    def fair(self, k: float, call: bool) -> tuple[float | None, str]:
        """(公平價點數, 來源)。同行使價有報價 → 期權中價；否則插值 IV ＋ BS。"""
        q = self.quotes.get(k)
        side = "c" if call else "p"
        if q and q.get(side):
            return 0.5 * (q[side][0] + q[side][1]), "期權中價"
        v = self.iv_at(k)
        if v is None:
            return None, "無"
        return bs_price(self.forward, k, self.T, v, call), "IV 插值"

    def bid(self, k: float, call: bool) -> float | None:
        q = self.quotes.get(k)
        side = "c" if call else "p"
        return q[side][0] if q and q.get(side) else None


def evaluate_warrant(w: dict, ox: OptionExpiry, fee_lot: float = 30.0, fee_rate: float = 0.001) -> dict:
    """w: code, name, issuer, call(bool), strike, ratio, bid, ask, iv_futu, street, expiry."""
    K, R, ask = w["strike"], w["ratio"], w["ask"]
    fair_pts, src = ox.fair(K, w["call"])
    out = {**w, "forward": round(ox.forward), "T_days": round(ox.T * 365), "fair_src": src}
    if fair_pts is None or ask <= 0 or R <= 0:
        out.update({"error": "沒有期權公平價"})
        return out
    ask_pts = ask * R
    out["fair_price"] = fair_pts / R
    out["premium_pct"] = (ask_pts / fair_pts - 1) * 100 if fair_pts > 0 else None
    out["iv_warrant"] = implied_vol(ask_pts, ox.forward, K, ox.T, w["call"])
    out["iv_option"] = ox.iv_at(K)
    out["iv_gap"] = (out["iv_warrant"] - out["iv_option"]) * 100 if out["iv_warrant"] and out["iv_option"] else None
    ob = ox.bid(K, w["call"])
    if ob is not None:
        fees_pts = fee_lot / MULT + ask_pts * fee_rate
        out["lock_edge_pts"] = ob - ask_pts - fees_pts
        out["option_bid"] = ob
    else:
        out["lock_edge_pts"] = None
    return out


def summarize(rows: list[dict]) -> list[str]:
    ok = [r for r in rows if "error" not in r and r.get("premium_pct") is not None]
    lines = []
    if not ok:
        return ["沒有可算的窩輪"]
    def q(vals, p):
        vals = sorted(vals)
        return vals[min(len(vals) - 1, int(p * len(vals)))]
    prem = [r["premium_pct"] for r in ok]
    gaps = [r["iv_gap"] for r in ok if r.get("iv_gap") is not None]
    locks = [r for r in ok if r.get("lock_edge_pts") is not None]
    pos = [r for r in locks if r["lock_edge_pts"] > 0]
    cheap = [r for r in ok if r["premium_pct"] < 0]
    lines.append(f"{len(ok)} 隻可算（{len({r['expiry'] for r in ok})} 個到期日）；賣價相對期權公平價溢價：中位 {q(prem, .5):+.1f}%，10% {q(prem, .1):+.1f}%，90% {q(prem, .9):+.1f}%")
    if gaps:
        lines.append(f"窩輪 IV − 期權 IV（波幅點）：中位 {q(gaps, .5):+.1f}，10% {q(gaps, .1):+.1f}，90% {q(gaps, .9):+.1f}")
    lines.append(f"賣價低於期權公平價（負溢價）：{len(cheap)} 隻；有同行使價期權可鎖的 {len(locks)} 隻中鎖定淨額 > 0：{len(pos)} 隻")
    by_exp = {}
    for r in ok:
        by_exp.setdefault(r["expiry"], []).append(r["premium_pct"])
    for e in sorted(by_exp):
        v = by_exp[e]
        lines.append(f"  {e}: {len(v)} 隻，溢價中位 {q(v, .5):+.1f}%")
    return lines


def print_rows(rows: list[dict], top: int = 40) -> None:
    ok = sorted((r for r in rows if "error" not in r and r.get("premium_pct") is not None), key=lambda r: r["premium_pct"])
    print(f"{'代號':<9}{'發行':<5}{'C/P':<4}{'到期':<11}{'行使價':>7}{'比率':>6}{'買':>7}{'賣':>7}{'公平':>7}{'溢價%':>7}{'IV輪':>6}{'IV權':>6}{'鎖定pt':>8} 來源")
    for r in ok[:top]:
        print(f"{r['code']:<9}{str(r['issuer'])[:4]:<5}{'C' if r['call'] else 'P':<4}{r['expiry']:<11}{r['strike']:>7.0f}{r['ratio']:>6.0f}"
              f"{r['bid']:>7.3f}{r['ask']:>7.3f}{r['fair_price']:>7.3f}{r['premium_pct']:>+7.1f}"
              f"{(r['iv_warrant'] or 0) * 100:>6.1f}{(r['iv_option'] or 0) * 100:>6.1f}"
              f"{(r['lock_edge_pts'] if r['lock_edge_pts'] is not None else float('nan')):>8.1f} {r['fair_src']}")
    print("（按溢價由低到高；鎖定pt＝同行使價期權 bid − 窩輪賣價×比率 − 費用，正數才是套利）")
    for l in summarize(rows):
        print(l)


def write_csv(rows: list[dict], path: str, day: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date"] + keys)
        w.writeheader()
        for r in rows:
            w.writerow({"date": day, **r})


# ---------- Futu ----------
def _warrant_request_cls(ft):
    cls = getattr(ft, "WarrantRequest", None) or getattr(ft, "WarrantDataFilter", None)
    if cls is None:
        from futu.quote.quote_get_warrant import Request as cls  # type: ignore
    return cls


def scan_live(host: str, port: int, owner: str, max_days: int, fee_lot: float, log=print) -> tuple[list[dict], dict]:
    try:
        import futu as ft  # type: ignore
        ft.OpenQuoteContext
    except (ImportError, AttributeError):
        sys.exit("需要 pip install futu-api；用完整路徑執行，不要在 repo 根目錄互動模式 import futu")
    import time
    ctx = ft.OpenQuoteContext(host=host, port=port)
    results, meta = [], {"owner": owner, "n_warrants": 0, "expiries": 0}
    today = dt.date.today()
    try:
        warrants = []
        for wtype, is_call in ((ft.WrtType.CALL, True), (ft.WrtType.PUT, False)):
            begin = 0
            while True:
                req = _warrant_request_cls(ft)()
                req.type_list = [wtype]
                req.begin, req.num = begin, 200
                req.sort_field = ft.SortField.CODE
                ret, data = ctx.get_warrant(owner, req)
                if ret != ft.RET_OK:
                    raise RuntimeError(f"get_warrant 失敗：{data}")
                df, last_page, all_count = data
                for r in df.to_dict("records"):
                    try:
                        exp = dt.date.fromisoformat(str(r["maturity_time"])[:10])
                    except ValueError:
                        continue
                    if (exp - today).days > max_days or (exp - today).days <= 0:
                        continue
                    ask, bid = float(r.get("ask_price") or 0), float(r.get("bid_price") or 0)
                    if ask <= 0:
                        continue
                    warrants.append({"code": str(r["stock"]), "name": str(r.get("name", "")), "issuer": str(r.get("issuer", "")),
                                     "call": is_call, "strike": float(r["strike_price"]), "ratio": float(r["conversion_ratio"] or 0),
                                     "bid": bid, "ask": ask, "iv_futu": float(r.get("implied_volatility") or 0),
                                     "street": float(r.get("street_rate") or 0), "expiry": exp.isoformat()})
                begin += len(df)
                if last_page or len(df) == 0 or begin >= all_count:
                    break
                time.sleep(3.1)
            time.sleep(3.1)
        meta["n_warrants"] = len(warrants)
        log(f"{INDEX_CODES.get(owner, owner)} 窩輪（≤{max_days} 日到期、有賣價）{len(warrants)} 隻")
        by_exp: dict[str, list[dict]] = {}
        for w in warrants:
            by_exp.setdefault(w["expiry"], []).append(w)
        for exp_s, group in sorted(by_exp.items()):
            ret, oc = ctx.get_option_chain(owner, index_option_type=ft.IndexOptionType.NORMAL, start=exp_s, end=exp_s,
                                           option_type=ft.OptionType.ALL)
            time.sleep(3.1)
            if ret != ft.RET_OK or len(oc) == 0:
                log(f"  {exp_s}: 沒有同日到期的恒指期權，{len(group)} 隻窩輪只能略過（不能同日結算鎖定）")
                for w in group:
                    results.append({**w, "error": "沒有同日到期期權"})
                continue
            oc = oc[oc["strike_time"].astype(str).str[:10] == exp_s]
            info = {r["code"]: (str(r["option_type"]), float(r["strike_price"])) for r in oc.to_dict("records")}
            codes = list(info)
            quotes: dict[float, dict] = {}
            for i in range(0, len(codes), 400):
                ret2, snap = ctx.get_market_snapshot(codes[i:i + 400])
                if ret2 != ft.RET_OK:
                    log(f"  {exp_s}: 快照失敗 {snap}")
                    break
                for r in snap.to_dict("records"):
                    typ, k = info.get(r["code"], (None, None))
                    b, a = float(r.get("bid_price") or 0), float(r.get("ask_price") or 0)
                    if typ is None or b <= 0 or a <= 0:
                        continue
                    quotes.setdefault(k, {})["c" if "CALL" in typ.upper() else "p"] = (b, a)
                time.sleep(0.6)
            try:
                ox = OptionExpiry(dt.date.fromisoformat(exp_s), quotes, today)
            except ValueError as err:
                log(f"  {exp_s}: {err}")
                for w in group:
                    results.append({**w, "error": str(err)})
                continue
            meta["expiries"] += 1
            for w in group:
                results.append(evaluate_warrant(w, ox, fee_lot))
            n_ok = sum(1 for w in group if "error" not in results[-1])
            log(f"  {exp_s}: 期權 {len(quotes)} 個行使價，F={ox.forward:,.0f}，窩輪 {len(group)} 隻")
    finally:
        ctx.close()
    return results, meta


def demo() -> None:
    today = dt.date(2026, 10, 9)
    exp = dt.date(2026, 10, 29)
    F, T = 24_200.0, 20 / 365
    # 合成期權鏈：IV 16%，差價 ±3 點
    quotes = {}
    for k in range(22_000, 26_401, 200):
        c = bs_price(F, k, T, 0.16, True); p = bs_price(F, k, T, 0.16, False)
        quotes[float(k)] = {"c": (c - 3, c + 3), "p": (p - 3, p + 3)}
    ox = OptionExpiry(exp, quotes, today)
    assert abs(ox.forward - F) < 1, ox.forward
    assert abs(ox.iv_at(24_200) - 0.16) < 0.005
    # 窩輪 A：IV 20% 開價（正常偏貴）；窩輪 B：IV 12% 開價（便宜到可鎖）
    K, R = 24_600.0, 10_000.0
    a_pts = bs_price(F, K, T, 0.20, True); b_pts = bs_price(F, K, T, 0.12, True)
    wa = {"code": "A", "name": "", "issuer": "X", "call": True, "strike": K, "ratio": R, "bid": a_pts / R - 0.001, "ask": a_pts / R, "iv_futu": 20, "street": 10, "expiry": exp.isoformat()}
    wb = {**wa, "code": "B", "ask": b_pts / R, "bid": b_pts / R - 0.001}
    ea, eb = evaluate_warrant(wa, ox), evaluate_warrant(wb, ox)
    assert ea["premium_pct"] > 0 and ea["lock_edge_pts"] < 0 and abs(ea["iv_warrant"] - 0.20) < 0.005
    assert eb["premium_pct"] < 0 and eb["lock_edge_pts"] > 0 and eb["iv_gap"] < 0
    # 不在格點的行使價 → IV 插值
    wc = {**wa, "code": "C", "strike": 24_500.0}
    ec = evaluate_warrant(wc, ox)
    assert ec["fair_src"] == "IV 插值" and ec["lock_edge_pts"] is None
    print("自我檢查通過。")
    print_rows([ea, eb, ec])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--live", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11111)
    p.add_argument("--owner", default="HK.800000")
    p.add_argument("--max-days", type=int, default=120, help="只看到期 ≤ N 日的窩輪（預設 120）")
    p.add_argument("--fee-lot", type=float, default=30.0)
    p.add_argument("--csv")
    p.add_argument("--top", type=int, default=40)
    a = p.parse_args()
    if a.demo:
        demo()
        return
    if a.live:
        rows, meta = scan_live(a.host, a.port, a.owner, a.max_days, a.fee_lot)
        print_rows(rows, a.top)
        if a.csv:
            write_csv(rows, a.csv, dt.date.today().isoformat())
            print(f"已寫入 {a.csv}")
        return
    p.print_help()


if __name__ == "__main__":
    main()
