#!/usr/bin/env python3
"""富途持倉買賣盤快照：讀你嘅持倉 → 取每個合約嘅買價／賣價／中間價 → 寫 tradingview/data_external/futu_positions.json 並 push。
跑在使用者嘅 GCP VM（OpenD 同機），不在沙盒。純讀取：只用 position_list_query + get_market_snapshot，
不 unlock_trade、不落單、不改單。帳戶號碼唔會寫入輸出檔。
前置：VM 已裝 OpenD 並登入（登入／驗證碼你自己喺 VM 做，唔好貼畀 Claude）；pip install futu-api。
用法：python3 gcp_ib/futu_positions_quote.py [--no-push]
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from futu import OpenQuoteContext, OpenSecTradeContext, OpenFutureTradeContext, RET_OK, TrdEnv, TrdMarket

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "data_external" / "futu_positions.json"
HKT = timezone(timedelta(hours=8))


def num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def positions(ctx_cls, market):
    rows = []
    try:
        ctx = ctx_cls(filter_trdmarket=market, host="127.0.0.1", port=11111)
    except Exception as e:
        print(f"{market}: 開唔到交易 context：{e}")
        return rows
    try:
        ret, df = ctx.position_list_query(trd_env=TrdEnv.REAL)
        if ret != RET_OK:
            print(f"{market}: position_list_query 失敗：{df}")
            return rows
        for _, r in df.iterrows():
            if (num(r.get("qty")) or 0) == 0:
                continue
            rows.append({"market": str(market), "code": r["code"], "name": r.get("stock_name", ""),
                         "side": str(r.get("position_side", "")), "qty": num(r.get("qty")),
                         "cost_price": num(r.get("cost_price")), "pl_val": num(r.get("pl_val")),
                         "nominal_price": num(r.get("nominal_price"))})
    finally:
        ctx.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()

    rows = positions(OpenSecTradeContext, TrdMarket.HK)
    try:
        rows += positions(OpenFutureTradeContext, TrdMarket.FUTURES)
    except Exception as e:
        print(f"期貨帳戶：{e}")
    if not rows:
        sys.exit("冇讀到持倉（OpenD 有冇登入？）")

    q = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        ret, snap = q.get_market_snapshot([r["code"] for r in rows])
        if ret != RET_OK:
            sys.exit(f"get_market_snapshot 失敗：{snap}")
        by = {s["code"]: s for _, s in snap.iterrows()}
    finally:
        q.close()

    for r in rows:
        s = by.get(r["code"])
        bid = num(s.get("bid_price")) if s is not None else None
        ask = num(s.get("ask_price")) if s is not None else None
        r.update({"bid": bid, "ask": ask, "last": num(s.get("last_price")) if s is not None else None,
                  "mid": round((bid + ask) / 2, 2) if bid and ask else None,
                  "quote_time": str(s.get("update_time")) if s is not None else None})
    out = {"fetched_hkt": datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S"), "positions": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))

    if not a.no_push:
        for c in (["git", "add", str(OUT)],
                  ["git", "commit", "-q", "-m", "data: 富途持倉買賣盤快照（VM）"],
                  ["git", "pull", "--rebase", "-q", "origin", "claude/dazzling-curie-f3xzb8"],
                  ["git", "push", "-q", "origin", "HEAD:claude/dazzling-curie-f3xzb8"]):
            r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
            if r.returncode and c[1] != "commit":
                print(f"push 失敗 {c[1]}：{r.stderr.strip()[:200]}")
                return


if __name__ == "__main__":
    main()
