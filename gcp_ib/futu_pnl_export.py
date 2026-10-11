#!/usr/bin/env python3
"""富途成交＋手續費＋資金流水 → 推上 Cloud Run（action=futu_pnl，main.py R152），做基金報告嘅已實現盈虧。
跑喺使用者自己部電腦（OpenD 同機）。只讀：唔落單、唔 unlock_trade、唔改單。帳號唔會寫入輸出或印出。

用法（PowerShell，喺 repo 資料夾）：
  python gcp_ib\\futu_pnl_export.py                      # 由 2026-06-01 攞到今日，推上 GCP
  python gcp_ib\\futu_pnl_export.py --since 2026-08-01   # 改起始日（要早過報告起始日 9/1，等 9 月平倉搵到開倉成本）
  python gcp_ib\\futu_pnl_export.py --dry-run            # 只寫本機檔，唔推
設定：同 auto_risk.py 一樣用 ZHUGE_GCP_URL、WEBHOOK_SECRET_TOKEN（環境變數，唔好寫入 repo）。
本機副本：tradingview/out/futu_pnl_export.json（tradingview/out/ 已 .gitignore，唔會 commit）。
"""
import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from futu import RET_OK, TrdEnv

from futu_positions_quote import contexts, num, real_accounts

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "out" / "futu_pnl_export.json"
HKT = timezone(timedelta(hours=8))
CHUNK_DAYS = 30
SCRIPT_VERSION = "R152"


def chunks(start, end):
    d = start
    while d <= end:
        e = min(d + timedelta(days=CHUNK_DAYS - 1), end)
        yield d, e
        d = e + timedelta(days=1)


def fetch(since):
    today = datetime.now(HKT).date()
    deals, fees, flows, positions, notes = [], {}, [], [], []
    seen = set()
    for label, ctx in contexts():
        try:
            for a in real_accounts(ctx):
                acc = int(a["acc_id"])
                if str(a.get("acc_status", "ACTIVE")) == "DISABLED" or acc in seen:
                    continue
                seen.add(acc)
                for s, e in chunks(since, today):
                    ret, df = ctx.history_deal_list_query(start=f"{s} 00:00:00", end=f"{e} 23:59:59",
                                                          trd_env=TrdEnv.REAL, acc_id=acc)
                    if ret != RET_OK:
                        notes.append(f"{label} 成交 {s}–{e} 失敗：{str(df)[:120]}")
                        continue
                    for _, r in df.iterrows():
                        deals.append({"account": label, "deal_id": str(r.get("deal_id")), "order_id": str(r.get("order_id")),
                                      "code": r.get("code"), "name": r.get("stock_name", ""), "side": str(r.get("trd_side")),
                                      "qty": num(r.get("qty")), "price": num(r.get("price")),
                                      "time": str(r.get("create_time")), "status": str(r.get("status", ""))})
                    try:
                        ret, cf = ctx.get_acc_cash_flow(trd_env=TrdEnv.REAL, acc_id=acc, start=str(s), end=str(e))
                    except TypeError:                     # 舊版 futu-api 冇 start／end
                        ret, cf = -1, "futu-api 太舊（冇 get_acc_cash_flow start/end）"
                    if ret == RET_OK:
                        for _, r in cf.iterrows():
                            flows.append({"account": label, "date": str(r.get("clearing_date")), "ccy": str(r.get("currency")),
                                          "type": str(r.get("cashflow_type")), "dir": str(r.get("cashflow_direction")),
                                          "amount": num(r.get("cashflow_amount")), "remark": str(r.get("cashflow_remark"))[:80]})
                    else:
                        notes.append(f"{label} 資金流水 {s}–{e}：{str(cf)[:120]}")
                ids = sorted({d["order_id"] for d in deals if d["account"] == label and d["order_id"] not in fees})
                for i in range(0, len(ids), 400):
                    try:
                        ret, fd = ctx.order_fee_query(order_id_list=ids[i:i + 400], trd_env=TrdEnv.REAL, acc_id=acc)
                    except Exception as e:                 # 舊版冇 order_fee_query
                        ret, fd = -1, e.__class__.__name__
                    if ret == RET_OK:
                        for _, r in fd.iterrows():
                            fees[str(r.get("order_id"))] = num(r.get("fee_amount"))
                    else:
                        notes.append(f"{label} 手續費查詢失敗：{str(fd)[:120]}")
                ret, pf = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=acc, refresh_cache=True)
                if ret == RET_OK:
                    for _, r in pf.iterrows():
                        if num(r.get("qty")):
                            q = num(r.get("qty"))
                            positions.append({"code": r.get("code"), "qty": -abs(q) if "SHORT" in str(r.get("position_side")).upper() else q})
        finally:
            ctx.close()
    return {"action": "futu_pnl", "script_version": SCRIPT_VERSION, "since": str(since),
            "fetched_hkt": datetime.now(HKT).strftime("%Y-%m-%d %H:%M"), "deals": deals, "fees": fees,
            "cash_flows": flows, "positions": positions, "notes": notes}


def push(body):
    url, tok = os.environ.get("ZHUGE_GCP_URL"), os.environ.get("WEBHOOK_SECRET_TOKEN")
    if not url or not tok:
        return "冇設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN，冇推"
    req = urllib.request.Request(url, data=json.dumps({**body, "token": tok}, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8") or "{}")
        return f"GCP ✅ {res.get('status')}（成交 {res.get('deals')} 筆）" if res.get("status") == "stored" else f"GCP ⚠ {res}"
    except urllib.error.HTTPError as e:
        return f"GCP ❌ HTTP {e.code}"
    except Exception as e:                                   # 唔好印網址同權杖
        return f"GCP ❌ {e.__class__.__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-06-01")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    body = fetch(date.fromisoformat(a.since))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"成交 {len(body['deals'])} 筆、手續費 {len(body['fees'])} 張單、資金流水 {len(body['cash_flows'])} 筆、持倉 {len(body['positions'])} 個")
    for n in body["notes"]:
        print("  注意：", n)
    print(f"本機副本：{OUT}")
    if not a.dry_run:
        print(push(body))


if __name__ == "__main__":
    main()
