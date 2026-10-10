#!/usr/bin/env python3
"""富途持倉＋報價＋盈虧：自動讀你嘅持倉 → 搵每個合約嘅買價／賣價／中間價 → 計盈虧。
跑在使用者自己部電腦（OpenD 同機）。純讀取：只用 get_acc_list / accinfo_query / position_list_query /
history_deal_list_query / get_market_snapshot / get_option_chain；不 unlock_trade、不落單、不改單。
帳戶號碼唔會寫入輸出檔或印出。

持倉來源（逐個試，攞到就用）：
  1. position_list_query（富途持倉 API）
  2. 如果讀到 0 行：用成交紀錄（history_deal_list_query，由 --since 起）反推淨持倉
用法：
  python gcp_ib\\futu_positions_quote.py                 # 讀持倉 → 報價 → 盈虧，寫 futu_positions.json
  python gcp_ib\\futu_positions_quote.py --diagnose      # 印出各帳戶資料來源診斷（市值、持倉行數、成交筆數）
  python gcp_ib\\futu_positions_quote.py --push          # 完成後 commit+push 結果（要你已登入 git）
  python gcp_ib\\futu_positions_quote.py --chain 2026-10-29 24800 25200   # 查恒指期權鏈買賣盤
  python gcp_ib\\futu_positions_quote.py --codes HK.MHI2610              # 查指定合約買賣盤
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from futu import (IndexOptionType, OpenFutureTradeContext, OpenQuoteContext, OpenSecTradeContext, RET_OK,
                  TrdEnv, TrdMarket)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "data_external" / "futu_positions.json"
HKT = timezone(timedelta(hours=8))
HOST, PORT = "127.0.0.1", 11111
# 每點價值（貨幣）。未知合約只顯示點數盈虧。
MULT = (("HK.MHI", 10, "HKD"), ("HK.HSI", 50, "HKD"), ("HK.MCH", 10, "HKD"))


def num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def mult_of(code):
    for pre, m, cur in MULT:
        if code.startswith(pre):
            return m, cur
    return None, None


def real_accounts(ctx):
    ret, accs = ctx.get_acc_list()
    if ret != RET_OK:
        print(f"get_acc_list 失敗：{accs}")
        return []
    return [a for _, a in accs.iterrows() if str(a.get("trd_env")) == "REAL"]


def contexts():
    yield "期貨帳戶", OpenFutureTradeContext(host=HOST, port=PORT)
    yield "證券帳戶-HK", OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host=HOST, port=PORT)
    yield "證券帳戶-US", OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=HOST, port=PORT)


def read_holdings(since, diagnose):
    rows = []
    for label, ctx in contexts():
        try:
            for a in real_accounts(ctx):
                acc_id = int(a["acc_id"])
                tag = f"{label}（{a.get('acc_type')}，權限 {a.get('trdmarket_auth')}）"
                ret, info = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=acc_id, refresh_cache=True)
                mv = num(info.iloc[0].get("market_val")) if ret == RET_OK and len(info) else None
                ret, df = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=acc_id, refresh_cache=True)
                npos = len(df) if ret == RET_OK else -1
                end = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
                ret2, dl = ctx.history_deal_list_query(start=f"{since} 00:00:00", end=end, trd_env=TrdEnv.REAL, acc_id=acc_id)
                ndeal = len(dl) if ret2 == RET_OK else -1
                if diagnose:
                    print(f"[診斷] {tag}：市值={mv}，持倉 {npos} 行，{since} 起成交 {ndeal} 筆")
                    if ret != RET_OK:
                        print(f"        持倉錯誤：{df}")
                    if ret2 != RET_OK:
                        print(f"        成交錯誤：{dl}")
                if ret == RET_OK:
                    for _, r in df.iterrows():
                        if (num(r.get("qty")) or 0) != 0:
                            q = num(r.get("qty"))
                            short = "SHORT" in str(r.get("position_side")).upper()
                            rows.append({"source": "positions", "account": label, "code": r["code"], "name": r.get("stock_name", ""),
                                         "qty": -abs(q) if short else q, "open_price": num(r.get("cost_price")),
                                         "futu_pl": num(r.get("pl_val"))})
                if ret2 == RET_OK and len(dl):
                    net, cash = {}, {}
                    names = {}
                    for _, d in dl.iterrows():
                        sign = 1 if str(d["trd_side"]).upper() in ("BUY", "BUY_BACK") else -1
                        q = num(d["qty"]) or 0
                        net[d["code"]] = net.get(d["code"], 0) + sign * q
                        c = cash.setdefault(d["code"], {1: [0, 0], -1: [0, 0]})
                        c[sign][0] += q
                        c[sign][1] += q * (num(d["price"]) or 0)
                        names[d["code"]] = d.get("stock_name", "")
                    known = {r["code"] for r in rows if r["account"] == label}
                    for code, q in net.items():
                        if q == 0 or code in known:
                            continue
                        side = -1 if q < 0 else 1
                        n, amt = cash[code][side]
                        rows.append({"source": "deals", "account": label, "code": code, "name": names[code], "qty": q,
                                     "open_price": round(amt / n, 2) if n else None, "futu_pl": None})
        finally:
            ctx.close()
    return rows


def quotes(codes):
    q = OpenQuoteContext(host=HOST, port=PORT)
    try:
        ret, snap = q.get_market_snapshot(codes)
        if ret != RET_OK:
            sys.exit(f"get_market_snapshot 失敗：{snap}")
        return {s["code"]: s for _, s in snap.iterrows()}
    finally:
        q.close()


def price_ok(x):
    return x is not None and x > 0


def pnl(rows, by):
    for r in rows:
        s = by.get(r["code"])
        bid = num(s.get("bid_price")) if s is not None else None
        ask = num(s.get("ask_price")) if s is not None else None
        last = num(s.get("last_price")) if s is not None else None
        r.update(bid=bid if price_ok(bid) else None, ask=ask if price_ok(ask) else None, last=last,
                 quote_time=str(s.get("update_time")) if s is not None else None)
        r["mid"] = round((r["bid"] + r["ask"]) / 2, 2) if r["bid"] and r["ask"] else None
        # 平倉價：空倉用賣價買回，多倉用買價沽出；冇單邊價就用最後成交，並標注
        q, op = r["qty"], r["open_price"]
        side_px, why = (r["ask"], "ask") if q < 0 else (r["bid"], "bid")
        if side_px is None:
            side_px, why = last, "last（冇" + ("賣" if q < 0 else "買") + "價）"
        m, cur = mult_of(r["code"])
        r["close_basis"], r["close_price"] = why, side_px
        if op is not None and side_px is not None:
            r["pnl_pts_per_unit"] = round((side_px - op) * (1 if q > 0 else -1), 2)
            r["pnl_ccy"] = round(r["pnl_pts_per_unit"] * abs(q) * m, 0) if m else None
            r["ccy"] = cur
            if r["mid"] is not None:
                r["pnl_ccy_mid"] = round((r["mid"] - op) * (1 if q > 0 else -1) * abs(q) * m, 0) if m else None
    return rows


def show(rows):
    print(f"\n{'合約':<24}{'數量':>5}{'開倉價':>9}{'買價':>8}{'賣價':>8}{'中間':>8}{'最後':>8}  平倉基準  盈虧")
    tot = {}
    for r in rows:
        f = lambda v: "-" if v is None else f"{v:g}"
        p = r.get("pnl_ccy")
        print(f"{r['code']:<24}{r['qty']:>5g}{f(r['open_price']):>9}{f(r['bid']):>8}{f(r['ask']):>8}{f(r['mid']):>8}{f(r['last']):>8}"
              f"  {r['close_basis']}  {'-' if p is None else format(p, ',.0f') + ' ' + r['ccy']}  （報價 {r['quote_time']}）")
        if p is not None:
            tot[r["ccy"]] = tot.get(r["ccy"], 0) + p
    for c, v in tot.items():
        print(f"合共（可計算者，{c}）：{v:,.0f}")


def push():
    for c in (["git", "add", str(OUT)],
              ["git", "commit", "-q", "-m", "data: 富途持倉報價快照"],
              ["git", "pull", "--rebase", "-q", "origin", "claude/dazzling-curie-f3xzb8"],
              ["git", "push", "-q", "origin", "HEAD:claude/dazzling-curie-f3xzb8"]):
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        if r.returncode and c[1] != "commit":
            print(f"push 失敗 {c[1]}：{r.stderr.strip()[:200]}")
            return
    print("已 push")


def chain(exp, klo, khi):
    q = OpenQuoteContext(host=HOST, port=PORT)
    try:
        for label, t in (("標準", IndexOptionType.NORMAL), ("小型", IndexOptionType.SMALL)):
            ret, ch = q.get_option_chain(code="HK.800000", start=exp, end=exp, index_option_type=t)
            if ret != RET_OK:
                print(f"{label}：get_option_chain 失敗：{ch}")
                continue
            ch = ch[(ch["strike_price"] >= klo) & (ch["strike_price"] <= khi)]
            if ch.empty:
                print(f"{label}：呢個到期日／範圍冇合約")
                continue
            ret, snap = q.get_market_snapshot(list(ch["code"]))
            if ret != RET_OK:
                print(f"{label}：snapshot 失敗：{snap}")
                continue
            px = snap[[c for c in ("code", "name", "bid_price", "ask_price", "last_price", "update_time") if c in snap.columns]]
            out = ch[["code", "strike_price", "option_type"]].merge(px, on="code", how="left").sort_values(["strike_price", "option_type"])
            print(f"--- {label}恒指期權 {exp} ---")
            print(out.to_string(index=False))
    finally:
        q.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-01", help="成交紀錄起日（反推持倉用）")
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--chain", nargs=3, metavar=("EXPIRY", "KLO", "KHI"))
    ap.add_argument("--codes", nargs="*", default=[])
    a = ap.parse_args()

    if a.chain:
        return chain(a.chain[0], float(a.chain[1]), float(a.chain[2]))
    if a.codes:
        for c, s in quotes(a.codes).items():
            print(c, s.get("name"), "買", s.get("bid_price"), "賣", s.get("ask_price"), "最後", s.get("last_price"), s.get("update_time"))
        return

    rows = read_holdings(a.since, a.diagnose)
    if not rows:
        sys.exit("持倉同成交紀錄都冇讀到（用 --diagnose 睇每個帳戶嘅情況）")
    rows = pnl(rows, quotes([r["code"] for r in rows]))
    show(rows)
    out = {"fetched_hkt": datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S"), "positions": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已寫入 {OUT}")
    if a.push:
        push()


if __name__ == "__main__":
    main()
