#!/usr/bin/env python3
"""富途持倉買賣盤快照：讀你嘅持倉 → 取每個合約嘅買價／賣價／中間價 → 寫 tradingview/data_external/futu_positions.json 並 push。
跑在使用者嘅 GCP VM（OpenD 同機），不在沙盒。純讀取：只用 position_list_query + get_market_snapshot，
不 unlock_trade、不落單、不改單。帳戶號碼唔會寫入輸出檔。
逐個真實帳戶（期貨／證券）讀持倉；同一合約出現多次會重覆列出。
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


def positions(ctx_cls, label, **kw):
    """逐個真實帳戶讀持倉（唔假設邊個帳戶，因為 HSI/MHI 期權通常喺期貨帳戶，唔喺證券帳戶）。"""
    rows = []
    try:
        ctx = ctx_cls(host="127.0.0.1", port=11111, **kw)
    except Exception as e:
        print(f"{label}: 開唔到交易 context：{e}")
        return rows
    try:
        ret, accs = ctx.get_acc_list()
        if ret != RET_OK:
            print(f"{label}: get_acc_list 失敗：{accs}")
            return rows
        print(f"{label}: 搵到 {len(accs)} 個帳戶")
        for _, a in accs.iterrows():
            print(f"  帳戶類型={a.get('acc_type')} 環境={a.get('trd_env')} 市場權限={a.get('trdmarket_auth')} 狀態={a.get('acc_status')}")
            if str(a.get("trd_env")) != "REAL":
                continue
            ret, df = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=int(a["acc_id"]), refresh_cache=True)
            if ret != RET_OK:
                print(f"{label}: 持倉查詢失敗（帳戶類型 {a.get('acc_type')}）：{df}")
                continue
            print(f"  → 持倉查詢成功，{len(df)} 行")
            for _, r in df.iterrows():
                if (num(r.get("qty")) or 0) == 0:
                    continue
                rows.append({"account": label, "code": r["code"], "name": r.get("stock_name", ""),
                             "side": str(r.get("position_side", "")), "qty": num(r.get("qty")),
                             "cost_price": num(r.get("cost_price")), "pl_val": num(r.get("pl_val")),
                             "nominal_price": num(r.get("nominal_price"))})
    finally:
        ctx.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--codes", nargs="*", default=[], help="備用：唔讀持倉，直接查指定合約代碼嘅買賣盤，如 HK.MHI2610")
    a = ap.parse_args()

    if a.codes:
        q = OpenQuoteContext(host="127.0.0.1", port=11111)
        try:
            ret, snap = q.get_market_snapshot(a.codes)
            print(snap[[c for c in ("code", "name", "bid_price", "ask_price", "last_price", "update_time") if c in snap.columns]] if ret == RET_OK else snap)
        finally:
            q.close()
        return

    rows = positions(OpenFutureTradeContext, "期貨帳戶")
    rows += positions(OpenSecTradeContext, "證券帳戶-HK", filter_trdmarket=TrdMarket.HK)
    rows += positions(OpenSecTradeContext, "證券帳戶-US", filter_trdmarket=TrdMarket.US)
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
