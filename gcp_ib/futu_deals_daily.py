#!/usr/bin/env python3
"""富途當日成交紀錄（逐筆）＋已平倉盈虧（FIFO）。純讀取：只用 get_acc_list / history_deal_list_query；
不 unlock_trade、不落單、不改單。帳戶號碼唔會寫入輸出或印出。

點解要有：持倉 API 只見「而家持有咩」，睇唔到平倉價同確實時間；已實現盈虧、ledger（research/divergence/
ledger_yunchui.csv 的 buyback_pts／net_pnl_hkd）都靠成交紀錄。

用法（OpenD 同機；總指揮嘅 auto_risk 可直接 import run()）：
  python gcp_ib/futu_deals_daily.py                      # 今日（HKT）成交＋已平倉盈虧
  python gcp_ib/futu_deals_daily.py --date 2026-10-13    # 指定日期
  python gcp_ib/futu_deals_daily.py --out deals.json     # 同時寫 JSON（預設唔寫檔）
  python gcp_ib/futu_deals_daily.py --self-test          # 唔連富途，只驗證 FIFO 計算

輸出 JSON 欄位：date、deals[{time_hkt, code, side, qty, price, order_id}]、
summary[{code, buy_qty, buy_avg, sell_qty, sell_avg, net_qty}]、
closed[{code, close_time_hkt, qty, open_price, close_price, side, realized_pts, realized_ccy_note}]。
已實現盈虧未計佣金／費用。夜盤（HKEX 17:15–03:00）成交時間跨日：按成交時間所屬日期歸日，
所以建議每日跑兩次：收市後（約 16:45 HKT）同翌日凌晨（約 03:15 HKT）。
"""
import argparse
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))
HOST, PORT = "127.0.0.1", 11111
# 每點價值（貨幣）；未知合約只報點數
MULT = (("HK.MHI", 10, "HKD"), ("HK.HSI", 50, "HKD"), ("HK.MCH", 10, "HKD"))
BUY_SIDES = ("BUY", "BUY_BACK")


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


def fifo_close(deals, day):
    """deals：按時間排序的 [{time, code, sign(+1買/-1賣), qty, price}]，涵蓋 day 之前的開倉。
    回傳 day 當日發生嘅平倉（FIFO 配對）。sign 與持倉相反嘅成交先平倉，剩餘開新倉。"""
    lots = defaultdict(deque)          # code -> deque[[sign, qty, price]]
    closed = []
    for d in deals:
        code, sign, q, px = d["code"], d["sign"], d["qty"], d["price"]
        book = lots[code]
        while q > 1e-9 and book and book[0][0] == -sign:
            lot = book[0]
            take = min(q, lot[1])
            if d["time"].date() == day:
                pts = (px - lot[2]) * lot[0]          # lot[0]=+1 多頭：賣價-買價；-1 空頭：賣價(開)-買價(平)
                m, cur = mult_of(code)
                closed.append({
                    "code": code,
                    "close_time_hkt": d["time"].strftime("%Y-%m-%d %H:%M:%S"),
                    "side": "平空" if lot[0] == -1 else "平多",
                    "qty": take, "open_price": lot[2], "close_price": px,
                    "realized_pts": round(pts * take, 2),
                    "realized_ccy": round(pts * take * m, 2) if m else None,
                    "ccy": cur,
                })
            lot[1] -= take
            q -= take
            if lot[1] <= 1e-9:
                book.popleft()
        if q > 1e-9:
            book.append([sign, q, px])
    return closed


def summarize(day_deals):
    agg = defaultdict(lambda: {"buy_qty": 0.0, "buy_amt": 0.0, "sell_qty": 0.0, "sell_amt": 0.0})
    for d in day_deals:
        a = agg[d["code"]]
        k = "buy" if d["sign"] > 0 else "sell"
        a[k + "_qty"] += d["qty"]
        a[k + "_amt"] += d["qty"] * d["price"]
    out = []
    for code, a in sorted(agg.items()):
        out.append({"code": code,
                    "buy_qty": a["buy_qty"], "buy_avg": round(a["buy_amt"] / a["buy_qty"], 2) if a["buy_qty"] else None,
                    "sell_qty": a["sell_qty"], "sell_avg": round(a["sell_amt"] / a["sell_qty"], 2) if a["sell_qty"] else None,
                    "net_qty": a["buy_qty"] - a["sell_qty"]})
    return out


def build(all_deals, day):
    all_deals = sorted(all_deals, key=lambda d: d["time"])
    day_deals = [d for d in all_deals if d["time"].date() == day]
    return {
        "date": day.isoformat(),
        "deals": [{"time_hkt": d["time"].strftime("%Y-%m-%d %H:%M:%S"), "code": d["code"],
                   "side": "買" if d["sign"] > 0 else "賣", "qty": d["qty"], "price": d["price"],
                   "order_id": d.get("order_id")} for d in day_deals],
        "summary": summarize(day_deals),
        "closed": fifo_close(all_deals, day),
        "note": "已實現盈虧未計佣金／費用；FIFO 配對，涵蓋 --since 起全部成交（預設 2026-09-01）。",
    }


def read_deals(since):
    """讀所有真實帳戶（期貨＋證券 HK／US）自 since 起嘅成交。"""
    from futu import (OpenFutureTradeContext, OpenSecTradeContext, RET_OK, TrdEnv, TrdMarket)
    ctxs = (("期貨", lambda: OpenFutureTradeContext(host=HOST, port=PORT)),
            ("證券-HK", lambda: OpenSecTradeContext(filter_trdmarket=TrdMarket.HK, host=HOST, port=PORT)),
            ("證券-US", lambda: OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=HOST, port=PORT)))
    out, end = [], (datetime.now(HKT) + timedelta(days=1)).strftime("%Y-%m-%d 03:30:00")
    for label, mk in ctxs:
        ctx = mk()
        try:
            ret, accs = ctx.get_acc_list()
            if ret != RET_OK:
                print(f"[{label}] get_acc_list 失敗：{accs}")
                continue
            for _, a in accs.iterrows():
                if str(a.get("trd_env")) != "REAL":
                    continue
                ret, dl = ctx.history_deal_list_query(start=f"{since} 00:00:00", end=end,
                                                      trd_env=TrdEnv.REAL, acc_id=int(a["acc_id"]))
                if ret != RET_OK:
                    print(f"[{label}] 成交讀取失敗：{dl}")
                    continue
                for _, r in dl.iterrows():
                    q, px = num(r.get("qty")), num(r.get("price"))
                    if not q or px is None:
                        continue
                    try:
                        t = datetime.strptime(str(r["create_time"])[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT)
                    except ValueError:
                        continue
                    out.append({"time": t, "code": r["code"],
                                "sign": 1 if str(r["trd_side"]).upper() in BUY_SIDES else -1,
                                "qty": q, "price": px, "order_id": str(r.get("order_id", ""))})
        finally:
            ctx.close()
    return out


def run(day=None, since="2026-09-01"):
    """供 auto_risk import：回傳當日成交＋已平倉盈虧 dict。"""
    day = day or datetime.now(HKT).date()
    return build(read_deals(since), day)


def show(res):
    print(f"\n=== 富途成交 {res['date']}（HKT）===")
    if not res["deals"]:
        print("（當日冇成交）")
    for d in res["deals"]:
        print(f"{d['time_hkt']}  {d['side']}  {d['code']}  x{d['qty']:g}  @{d['price']:g}")
    if res["summary"]:
        print("\n--- 按合約彙總 ---")
        for s in res["summary"]:
            print(f"{s['code']}: 買 {s['buy_qty']:g}@{s['buy_avg']} / 賣 {s['sell_qty']:g}@{s['sell_avg']} / 淨 {s['net_qty']:+g}")
    if res["closed"]:
        print("\n--- 當日平倉（FIFO，未計佣金）---")
        for c in res["closed"]:
            ccy = f"，{c['realized_ccy']:+,.0f} {c['ccy']}" if c["realized_ccy"] is not None else ""
            print(f"{c['close_time_hkt']}  {c['side']} {c['code']} x{c['qty']:g}  開 {c['open_price']:g} → 平 {c['close_price']:g}"
                  f"  = {c['realized_pts']:+g} 點{ccy}")
    print()


def self_test():
    t = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT)
    deals = [  # 10/9 賣 24,200 → 10/13 買 24,168（平空）；10/13 再賣 24,305（新開）
        {"time": t("2026-10-09 19:49:00"), "code": "HK.MHI2610", "sign": -1, "qty": 1, "price": 24200.0},
        {"time": t("2026-10-13 12:00:00"), "code": "HK.MHI2610", "sign": 1, "qty": 1, "price": 24168.0},
        {"time": t("2026-10-13 15:07:00"), "code": "HK.MHI2610", "sign": -1, "qty": 1, "price": 24305.0},
    ]
    r = build(deals, datetime(2026, 10, 13).date())
    assert len(r["closed"]) == 1 and r["closed"][0]["realized_pts"] == 32 and r["closed"][0]["realized_ccy"] == 320, r["closed"]
    assert [d["side"] for d in r["deals"]] == ["買", "賣"]
    assert r["summary"][0]["net_qty"] == 0
    # 多頭平倉 + 部分平倉
    d2 = [{"time": t("2026-10-13 10:00:00"), "code": "HK.MHI2610", "sign": 1, "qty": 3, "price": 100.0},
          {"time": t("2026-10-13 11:00:00"), "code": "HK.MHI2610", "sign": -1, "qty": 2, "price": 110.0}]
    r2 = build(d2, datetime(2026, 10, 13).date())
    assert r2["closed"][0]["realized_pts"] == 20 and r2["closed"][0]["qty"] == 2, r2["closed"]
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD（HKT），預設今日")
    ap.add_argument("--since", default="2026-09-01", help="FIFO 配對起日（需涵蓋開倉）")
    ap.add_argument("--out", help="同時寫 JSON 檔")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    day = datetime.strptime(a.date, "%Y-%m-%d").date() if a.date else None
    res = run(day, a.since)
    show(res)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fp:
            json.dump(res, fp, ensure_ascii=False, indent=1)
        print(f"已寫入 {a.out}")


if __name__ == "__main__":
    main()
