#!/usr/bin/env python3
"""CME 6E 期權報價快照（歐元方差賣方 IBKR 版，登記：forex_research/FX_EUR_VRP_IBKR.md）。給雲垂 VM 的 cron 跑；只讀，不下單。

    # crontab（UTC，平日 14:00）：
    # 0 14 * * 1-5  cd <repo> && python3 scripts/ib_fx_option_snapshot.py >> data_forex_ibkr/vrp_snapshot.log 2>&1

    python3 scripts/ib_fx_option_snapshot.py --dry          # 只列出選到的合約與報價，不寫檔（首次除錯用）
    python3 scripts/ib_fx_option_snapshot.py --open         # B 階段：把今天選到的兩腿釘為持倉（寫 vrp_position.json）
    python3 scripts/ib_fx_option_snapshot.py --close        # 期滿後清掉持倉檔

每次記兩種列到 data_forex_ibkr/vrp_snapshots.csv：
  kind=scan  ：今天的 ATM 跨式（到期日離今天 21–35 日曆日、取最接近 30 者）。A 階段量買賣價差。
  kind=track ：若有 vrp_position.json，記該持倉兩腿與標的期貨。B 階段紙上損益用。
延遲報價（type 3）的 bid／ask 同步延遲，買賣價差仍有效；不要拿 IV 水平和別的來源比。
"""
import argparse
import csv
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from ib_insync import IB, Future, FuturesOption

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_forex_ibkr" / "vrp_snapshots.csv"
POS = ROOT / "data_forex_ibkr" / "vrp_position.json"
EXCH = "CME"
SYMBOL = "EUR"
MIN_DTE, MAX_DTE, TARGET_DTE = 21, 35, 30
COLS = ["utc_time", "kind", "expiry", "dte", "strike", "fut_symbol", "fut_bid", "fut_ask", "fut_last",
        "c_bid", "c_ask", "c_last", "c_iv", "c_bid_iv", "c_ask_iv", "c_delta", "c_gamma", "c_vega",
        "p_bid", "p_ask", "p_last", "p_iv", "p_bid_iv", "p_ask_iv", "p_delta", "p_gamma", "p_vega",
        "straddle_bid", "straddle_ask", "half_spread_vol"]


def ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and x > 0


def num(x, nd=6):
    """Greeks 等可為負的數；None／nan → 空字串。"""
    return round(x, nd) if x is not None and not (isinstance(x, float) and math.isnan(x)) else ""


def pnum(x, nd=6):
    """價格：IB 無報價時給 -1 或 nan，一律當缺值。"""
    return round(x, nd) if ok(x) else ""


def grk(g, name):
    return getattr(g, name, None) if g is not None else None


def wait_quotes(ib, tickers, secs=12):
    """等 bid／ask／modelGreeks 都灌進來（延遲報價要幾秒）。"""
    for _ in range(secs):
        ib.sleep(1)
        if all(ok(t.bid) and ok(t.ask) and grk(t.modelGreeks, "vega") is not None for t in tickers):
            break


def pick_front_future(ib):
    cds = ib.reqContractDetails(Future(SYMBOL, exchange=EXCH, currency="USD"))
    today = date.today().strftime("%Y%m%d")
    futs = sorted((cd.contract for cd in cds if cd.contract.lastTradeDateOrContractMonth[:8] > today),
                  key=lambda c: c.lastTradeDateOrContractMonth)
    return futs[:4]


def pick_option(ib, futs):
    """回傳 (標的期貨, 到期日, tradingClass, multiplier, 行使價清單)；到期日 21–35 天內最接近 30。"""
    today = date.today()
    best = None
    for fut in futs:
        for ch in ib.reqSecDefOptParams(fut.symbol, EXCH, "FUT", fut.conId):
            if ch.exchange != EXCH:
                continue
            for e in ch.expirations:
                dte = (datetime.strptime(e, "%Y%m%d").date() - today).days
                if MIN_DTE <= dte <= MAX_DTE:
                    key = abs(dte - TARGET_DTE)
                    if best is None or key < best[0]:
                        best = (key, fut, e, dte, ch.tradingClass, ch.multiplier, sorted(ch.strikes))
    return best[1:] if best else None


def qualify_leg(ib, fut, expiry, strike, right, tclass, mult):
    o = FuturesOption(fut.symbol, expiry, strike, right, EXCH, multiplier=mult, currency="USD", tradingClass=tclass)
    return o if ib.qualifyContracts(o) else None


def leg_fields(t, prefix):
    mg = t.modelGreeks
    return {f"{prefix}_bid": pnum(t.bid), f"{prefix}_ask": pnum(t.ask), f"{prefix}_last": pnum(t.last),
            f"{prefix}_iv": num(grk(mg, "impliedVol"), 5), f"{prefix}_bid_iv": num(grk(t.bidGreeks, "impliedVol"), 5),
            f"{prefix}_ask_iv": num(grk(t.askGreeks, "impliedVol"), 5), f"{prefix}_delta": num(grk(mg, "delta"), 5),
            f"{prefix}_gamma": num(grk(mg, "gamma"), 6), f"{prefix}_vega": num(grk(mg, "vega"), 6)}


def make_row(kind, now, fut, ft, expiry, dte, strike, ct, pt):
    row = {c: "" for c in COLS}
    row.update({"utc_time": now, "kind": kind, "expiry": expiry, "dte": dte, "strike": strike, "fut_symbol": fut.localSymbol,
                "fut_bid": pnum(ft.bid), "fut_ask": pnum(ft.ask), "fut_last": pnum(ft.last)})
    row.update(leg_fields(ct, "c"))
    row.update(leg_fields(pt, "p"))
    if all(ok(v) for v in (ct.bid, ct.ask, pt.bid, pt.ask)):
        sb, sa = ct.bid + pt.bid, ct.ask + pt.ask
        row["straddle_bid"], row["straddle_ask"] = round(sb, 6), round(sa, 6)
        v = (grk(ct.modelGreeks, "vega") or 0) + (grk(pt.modelGreeks, "vega") or 0)
        if v > 0:                                   # IB 的 vega = 每 1 個波動點的價格變動
            row["half_spread_vol"] = round((sa - sb) / 2 / v, 4)
    return row


def snapshot(ib, fut, expiry, dte, strike, tclass, mult, kind, now, legs=None):
    c = legs[0] if legs else qualify_leg(ib, fut, expiry, strike, "C", tclass, mult)
    p = legs[1] if legs else qualify_leg(ib, fut, expiry, strike, "P", tclass, mult)
    if not (c and p):
        return None
    ts = [ib.reqMktData(x, "", False, False) for x in (fut, c, p)]
    wait_quotes(ib, ts[1:])
    row = make_row(kind, now, fut, ts[0], expiry, dte, strike, ts[1], ts[2])
    for x in (fut, c, p):
        ib.cancelMktData(x)
    return row, (c, p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=32)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--open", action="store_true", help="把今天的 ATM 兩腿釘為 B 階段持倉")
    ap.add_argument("--close", action="store_true", help="清除持倉檔")
    args = ap.parse_args()
    if args.close:
        POS.unlink(missing_ok=True)
        print("持倉檔已清除")
        return
    ib = IB()
    ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=20)
    ib.reqMarketDataType(3)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    futs = pick_front_future(ib)
    sel = pick_option(ib, futs)
    if not sel:
        print(now, "找不到 21–35 天到期的 6E 期權")
        ib.disconnect()
        return
    fut, expiry, dte, tclass, mult, strikes = sel
    ib.qualifyContracts(fut)
    ft = ib.reqMktData(fut, "", False, False)
    ib.sleep(5)
    ref = ft.last if ok(ft.last) else ((ft.bid + ft.ask) / 2 if ok(ft.bid) and ok(ft.ask) else None)
    ib.cancelMktData(fut)
    if ref is None:
        print(now, "標的期貨無報價")
        ib.disconnect()
        return
    strike = min(strikes, key=lambda k: abs(k - ref))
    res = snapshot(ib, fut, expiry, dte, strike, tclass, mult, "scan", now)
    if res:
        rows.append(res[0])
        if args.open and not args.dry:
            c, p = res[1]
            POS.write_text(json.dumps({"opened": now, "expiry": expiry, "strike": strike, "fut_conId": fut.conId,
                                       "call_conId": c.conId, "put_conId": p.conId, "tradingClass": tclass,
                                       "multiplier": mult, "fut_symbol": fut.localSymbol}, indent=1), encoding="utf-8")
            print("已釘持倉：", POS)
    if POS.exists() and not args.open:
        pos = json.loads(POS.read_text(encoding="utf-8"))
        pf = Future(conId=pos["fut_conId"], exchange=EXCH)
        pc = FuturesOption(conId=pos["call_conId"], exchange=EXCH)
        pp = FuturesOption(conId=pos["put_conId"], exchange=EXCH)
        if ib.qualifyContracts(pf, pc, pp):
            d = (datetime.strptime(pos["expiry"], "%Y%m%d").date() - date.today()).days
            if d >= 0:
                r2 = snapshot(ib, pf, pos["expiry"], d, pos["strike"], pos["tradingClass"], pos["multiplier"], "track", now, legs=(pc, pp))
                if r2:
                    rows.append(r2[0])
    ib.disconnect()
    for r in rows:
        print(now, r["kind"], r["expiry"], r["strike"], "半價差(波動點)=", r["half_spread_vol"], "bid/ask 認購", r["c_bid"], r["c_ask"], "認沽", r["p_bid"], r["p_ask"])
    if args.dry or not rows:
        return
    OUT.parent.mkdir(exist_ok=True)
    new = not OUT.exists()
    with open(OUT, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
