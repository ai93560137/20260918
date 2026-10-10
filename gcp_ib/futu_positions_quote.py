#!/usr/bin/env python3
"""富途持倉＋報價＋盈虧：自動讀你嘅持倉 → 搵每個合約嘅買價／賣價／中間價 → 計盈虧。
跑在使用者自己部電腦（OpenD 同機）。純讀取：只用 get_acc_list / accinfo_query / position_list_query /
history_order_list_query / order_list_query / history_deal_list_query / get_market_snapshot / get_option_chain；不 unlock_trade、不落單、不改單。
帳戶號碼唔會寫入輸出檔；--diagnose 只印尾 4 位（牛牛號尾 3 位）方便對照 App。

持倉來源（逐個試，攞到就用）：
  1. position_list_query（富途持倉 API）
  2. 如果讀到 0 行：用成交紀錄（history_deal_list_query，由 --since 起）反推淨持倉
用法：
  python gcp_ib\\futu_positions_quote.py                 # 讀持倉 → 報價 → 盈虧，寫 futu_positions.json
  python gcp_ib\\futu_positions_quote.py --fixed        # 直接按 position.json 查 MHI 期權＋對沖期貨報價計盈虧
  python gcp_ib\\futu_positions_quote.py --diagnose      # 核對 OpenD 登入牛牛號／帳戶卡號（只印尾幾位）、資產、持倉、訂單、成交
  python gcp_ib\\futu_positions_quote.py --push          # 完成後 commit+push 結果到目前分支（repo 公開，持倉會公開！）
  python gcp_ib\\futu_positions_quote.py --chain 2026-10-29 24800 25200   # 查恒指期權鏈買賣盤
  python gcp_ib\\futu_positions_quote.py --codes HK.MHI2610              # 查指定合約買賣盤
  python gcp_ib\\futu_positions_quote.py --probe-us                       # 搵 MES／EW 標普期貨期權代碼
  python gcp_ib\\futu_positions_quote.py --deals HK.MHI2610 --since 2026-10-01   # 某合約嘅成交紀錄
輸出 tradingview/data_external/futu_positions.json（已 .gitignore，唔會 commit）。
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
MULT = (("HK.MHI", 10, "HKD"), ("HK.HSI", 50, "HKD"), ("HK.MCH", 10, "HKD"),
        ("US.EW", 50, "USD"), ("US.EX", 5, "USD"), ("US.MES", 5, "USD"), ("US.ES", 50, "USD"))  # EW＝E-mini 月底；EX1-4＝MES 週五


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


def mask(x, keep=4):
    """只留尾幾位，畀使用者對照 App（唔印全號）。"""
    s = str(x or "").strip()
    if not s or s in ("N/A", "nan", "None"):
        return "-"
    return "…" + s[-keep:]


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


def diagnose(since):
    """核對 OpenD 登入身份同帳戶：持倉讀到 0 時，逐項排除原因。只讀；帳號只印尾 4 位。"""
    import futu
    print(f"futu-api 版本：{getattr(futu, '__version__', '?')}（太舊可能讀唔到期貨／綜合帳戶，建議 pip install -U futu-api）")
    seen, found_any = set(), False
    for label, ctx in contexts():
        try:
            try:
                uid = ctx.get_login_user_id()
            except Exception as e:  # 舊版冇呢個方法
                uid = f"讀唔到（{e.__class__.__name__}）"
            print(f"\n=== {label}：OpenD 登入用戶 ID（牛牛號）尾 3 位 = {mask(uid, 3)}")
            ret, accs = ctx.get_acc_list()
            if ret != RET_OK:
                print(f"  get_acc_list 失敗：{accs}")
                continue
            if accs.empty:
                print("  （呢類冇任何帳戶）")
            for _, a in accs.iterrows():
                aid = int(a["acc_id"])
                print(f"  帳戶 {mask(aid)}｜卡號 {mask(a.get('card_num'))}｜綜合卡號 {mask(a.get('uni_card_num'))}｜"
                      f"{a.get('trd_env')}｜{a.get('acc_type')}｜狀態 {a.get('acc_status', '?')}｜"
                      f"券商 {a.get('security_firm', '?')}｜權限 {a.get('trdmarket_auth')}")
                if str(a.get("trd_env")) != "REAL" or (label, aid) in seen:
                    continue
                seen.add((label, aid))
                if str(a.get("acc_status", "ACTIVE")) == "DISABLED":
                    print("    → 失效帳戶（DISABLED），唔會有持倉；略過")
                    continue
                for cur in ("HKD", "USD"):
                    try:
                        r, info = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=aid, refresh_cache=True, currency=cur)
                    except TypeError:
                        r, info = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=aid, refresh_cache=True)
                    if r != RET_OK:
                        print(f"    資金（{cur}）失敗：{info}")
                        continue
                    row = info.iloc[0] if len(info) else {}
                    keys = ("total_assets", "cash", "market_val", "initial_margin", "maintenance_margin", "unrealized_pl")
                    print(f"    資金（{cur}）：" + "，".join(f"{k}={num(row.get(k))}" for k in keys if k in getattr(info, "columns", [])))
                    if (num(row.get("total_assets")) or 0) > 0:
                        found_any = True
                r, df = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=aid, refresh_cache=True)
                print(f"    持倉：{len(df) if r == RET_OK else '失敗 ' + str(df)} 行")
                if r == RET_OK and len(df):
                    found_any = True
                    for _, x in df.iterrows():
                        print(f"      {x['code']} {x.get('stock_name', '')} 數量 {x.get('qty')} {x.get('position_side', '')}")
                r, od = ctx.order_list_query(trd_env=TrdEnv.REAL, acc_id=aid, refresh_cache=True)
                print(f"    今日訂單：{len(od) if r == RET_OK else '失敗 ' + str(od)} 張")
                end = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
                r, ho = ctx.history_order_list_query(start=f"{since} 00:00:00", end=end, trd_env=TrdEnv.REAL, acc_id=aid)
                print(f"    {since} 起歷史訂單：{len(ho) if r == RET_OK else '失敗 ' + str(ho)} 張")
                r, dl = ctx.history_deal_list_query(start=f"{since} 00:00:00", end=end, trd_env=TrdEnv.REAL, acc_id=aid)
                print(f"    {since} 起成交：{len(dl) if r == RET_OK else '失敗 ' + str(dl)} 筆")
        finally:
            ctx.close()
    print("\n=== 點解讀 ===")
    if not found_any:
        print("所有帳戶資產＝0、冇持倉 → 幾乎肯定 OpenD 登入咗另一個富途 ID。請核對：")
        print("  1. 富途牛牛 App →「我的」→ 頭像下面嘅牛牛號（尾 3 位）vs 上面「OpenD 登入用戶 ID」尾 3 位")
        print("  2. App →「交易」→ 期貨帳戶卡號尾 4 位 vs 上面「卡號」")
        print("  唔同 → 喺 OpenD 登出，改用 App 嗰個牛牛號（或 App 綁定嘅手機／電郵）重新登入，再跑 --diagnose。")
        print("  相同但仍然係 0 → 富途 App「我的 → 設定 → OpenAPI」確認已同意 API 交易協議，或升級 futu-api／OpenD 至最新版。")
    else:
        print("有帳戶讀到資產／持倉 → 身份正確；直接跑冇參數版本就會用 position_list_query 嘅持倉。")


def read_holdings(since):
    """回傳 (持倉行, 帳戶資金摘要)。資金摘要唔包帳號。"""
    rows, accounts = [], []
    seen = set()
    for label, ctx in contexts():
        try:
            for a in real_accounts(ctx):
                acc_id = int(a["acc_id"])
                if str(a.get("acc_status", "ACTIVE")) == "DISABLED" or acc_id in seen:
                    continue
                seen.add(acc_id)
                r0, info = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=acc_id, refresh_cache=True)
                if r0 == RET_OK and len(info):
                    row = info.iloc[0]
                    accounts.append({"account": label, "currency": str(row.get("currency", "HKD")),
                                     **{k: num(row.get(k)) for k in ("total_assets", "cash", "market_val", "initial_margin",
                                                                      "maintenance_margin", "unrealized_pl", "risk_status")
                                        if k in info.columns}})
                ret, df = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=acc_id, refresh_cache=True)
                end = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
                ret2, dl = ctx.history_deal_list_query(start=f"{since} 00:00:00", end=end, trd_env=TrdEnv.REAL, acc_id=acc_id)
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
    return rows, accounts


def deals(codes, since):
    """列出指定合約嘅成交（時間、買賣、數量、價）。只讀；唔印帳號。"""
    end = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    for label, ctx in contexts():
        try:
            for a in real_accounts(ctx):
                if str(a.get("acc_status", "ACTIVE")) == "DISABLED":
                    continue
                for code in codes:
                    ret, dl = ctx.history_deal_list_query(code=code, start=f"{since} 00:00:00", end=end,
                                                          trd_env=TrdEnv.REAL, acc_id=int(a["acc_id"]))
                    if ret != RET_OK or dl.empty:
                        continue
                    print(f"--- {label} {code}：{len(dl)} 筆 ---")
                    cols = [c for c in ("create_time", "trd_side", "qty", "price", "status") if c in dl.columns]
                    print(dl.sort_values(cols[0])[cols].to_string(index=False))
        finally:
            ctx.close()


def fixed_holdings():
    """持倉 API 讀唔到時用：按 repo 嘅 tradingview/data_external/position.json 組出 HSI 持倉（MHI 期權兩腿＋對沖期貨）。"""
    import re
    pos = json.loads((ROOT / "tradingview" / "data_external" / "position.json").read_text(encoding="utf-8"))
    ymd = pos["expiry"][2:].replace("-", "")
    k = int(round(pos["strike"] * 1000))
    rows = []
    for cp, key in (("C", "call_sold"), ("P", "put_sold")):
        rows.append({"source": "position.json", "account": "固定", "code": f"HK.MHI{ymd}{cp}{k:08d}", "name": f"MHI {ymd} {pos['strike']} {cp}",
                     "qty": -pos["qty"], "open_price": pos["legs"][key], "futu_pl": None})
    net, px = {}, {}
    for h in pos.get("hedges", []):
        m = re.search(r"\((MHI\d{4})\)", h.get("contract", ""))
        if not m:
            continue
        code = "HK." + m.group(1)
        sign = -1 if h["side"] == "sell" else 1
        net[code] = net.get(code, 0) + sign * h["qty"]
        if sign == -1 or code not in px:
            px[code] = h["price"]
    for code, q in net.items():
        if q:
            rows.append({"source": "position.json", "account": "固定", "code": code, "name": code, "qty": q,
                         "open_price": px.get(code), "futu_pl": None})
    extra = ROOT / "tradingview" / "data_external" / "positions_extra.json"
    if extra.exists():
        for w in json.loads(extra.read_text(encoding="utf-8")).get("hsi_weekly", []):
            rows.append({"source": "positions_extra.json", "account": "固定", "code": w["code"], "name": w["name"],
                         "qty": w["qty"], "open_price": w["open_price"], "futu_pl": None})
    return rows


def quotes(codes, quiet=False):
    """逐批查快照；有一個代碼錯就改為逐個查，唔會因為一個壞代碼成批失敗。"""
    codes = [c for c in dict.fromkeys(codes) if c]
    out = {}
    if not codes:
        return out
    q = OpenQuoteContext(host=HOST, port=PORT)
    try:
        ret, snap = q.get_market_snapshot(codes)
        if ret == RET_OK:
            return {s["code"]: s for _, s in snap.iterrows()}
        for c in codes:
            ret, snap = q.get_market_snapshot([c])
            if ret == RET_OK and len(snap):
                out[c] = snap.iloc[0]
            elif not quiet:
                print(f"  報價失敗 {c}：{snap}")
        return out
    finally:
        q.close()


def quote_dict(by):
    """快照 → 可寫入 JSON 嘅精簡報價（買／賣／中間／最後＋報價時間）。"""
    d = {}
    for code, s in by.items():
        bid, ask = num(s.get("bid_price")), num(s.get("ask_price"))
        bid, ask = (bid if price_ok(bid) else None), (ask if price_ok(ask) else None)
        d[code] = {"name": str(s.get("name", "")), "bid": bid, "ask": ask,
                   "mid": round((bid + ask) / 2, 4) if bid and ask else None,
                   "last": num(s.get("last_price")) if price_ok(num(s.get("last_price"))) else None,
                   "quote_time": str(s.get("update_time") or "") or None}
    return d


# 標的期貨候選代碼（第一個有價嘅做 F）
UNDERLYING_CODES = ["HK.MHI2610", "HK.HSImain", "US.ESmain", "US.ES2612", "US.MESmain", "US.MES2612"]


def probe_us():
    """搵標普期貨期權（MES 週權、EW 月底）嘅富途代碼。只讀報價。"""
    from futu import Market, SecurityType
    q = OpenQuoteContext(host=HOST, port=PORT)
    try:
        print("1) 美國期貨代碼（get_stock_basicinfo，篩 ES／MES）")
        ret, df = q.get_stock_basicinfo(Market.US, SecurityType.FUTURE)
        if ret == RET_OK:
            m = df[df["code"].str.contains(r"\.(?:M?ES)", regex=True)]
            print(m[[c for c in ("code", "name", "lot_size", "listing_date") if c in m.columns]].head(30).to_string(index=False)
                  if len(m) else "   冇 ES／MES")
        else:
            print(f"   失敗：{df}")
        print("2) 期貨快照")
        for c, s in quote_dict(quotes(UNDERLYING_CODES[2:], quiet=True)).items():
            print(f"   {c} {s['name']} 買 {s['bid']} 賣 {s['ask']} 最後 {s['last']} {s['quote_time']}")
        print("3) 期貨期權鏈（get_option_chain 對期貨標的；行使價 7700–7900）")
        for und in UNDERLYING_CODES[2:]:
            for st, en in (("2026-10-16", "2026-10-16"), ("2026-10-30", "2026-10-30")):
                try:
                    ret, ch = q.get_option_chain(code=und, start=st, end=en)
                except Exception as e:
                    print(f"   {und} {st}：例外 {e}")
                    continue
                if ret != RET_OK:
                    print(f"   {und} {st}：{ch}")
                    continue
                ch = ch[(ch["strike_price"] >= 7700) & (ch["strike_price"] <= 7900)]
                print(f"   {und} {st}：{len(ch)} 隻" + ("" if ch.empty else "\n" + ch[["code", "strike_price", "option_type"]].head(12).to_string(index=False)))
        print("搵到代碼就用：python gcp_ib\\futu_positions_quote.py --codes <代碼>；搵唔到報告會用模型價（Black-76）。")
        print("另一條路：OpenD 登入 ID 改啱之後，持倉 API 會直接回傳 EW／MES 持倉嘅正確代碼。")
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
        last = last if price_ok(last) else None          # 冇行情權限時富途回傳 0，唔可以當成交價
        r.update(bid=bid if price_ok(bid) else None, ask=ask if price_ok(ask) else None, last=last,
                 quote_time=str(s.get("update_time")) if s is not None else None)
        r["mid"] = round((r["bid"] + r["ask"]) / 2, 2) if r["bid"] and r["ask"] else None
        # 平倉價：空倉用賣價買回，多倉用買價沽出；冇單邊價就用最後成交，並標注
        q, op = r["qty"], r["open_price"]
        side_px, why = (r["ask"], "ask") if q < 0 else (r["bid"], "bid")
        if side_px is None and last is not None:
            side_px, why = last, "last（冇" + ("賣" if q < 0 else "買") + "價）"
        if side_px is None and r.get("futu_pl") is not None and op is not None and mult_of(r["code"])[0]:
            side_px = op - r["futu_pl"] / (abs(q) * mult_of(r["code"])[0]) * (1 if q < 0 else -1)
            why = "富途持倉估值（冇行情）"
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
    if input("repo 係公開嘅，push 會公開你嘅持倉。真係要 push？輸入 yes：").strip().lower() != "yes":
        print("冇 push")
        return
    br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    for c in (["git", "add", str(OUT)],
              ["git", "commit", "-q", "-m", "data: 富途持倉報價快照"],
              ["git", "pull", "--rebase", "-q", "origin", br],
              ["git", "push", "-q", "origin", f"HEAD:{br}"]):
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
    ap.add_argument("--fixed", action="store_true", help="唔讀富途持倉，直接按 position.json 查報價計盈虧")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--chain", nargs=3, metavar=("EXPIRY", "KLO", "KHI"))
    ap.add_argument("--codes", nargs="*", default=[])
    ap.add_argument("--probe-us", action="store_true", help="搵 MES／EW 標普期貨期權嘅富途代碼")
    ap.add_argument("--deals", nargs="+", metavar="CODE", help="列出指定合約由 --since 起嘅成交")
    a = ap.parse_args()

    if a.deals:
        return deals(a.deals, a.since)
    if a.probe_us:
        return probe_us()
    if a.chain:
        return chain(a.chain[0], float(a.chain[1]), float(a.chain[2]))
    if a.codes:
        for c, s in quotes(a.codes).items():
            print(c, s.get("name"), "買", s.get("bid_price"), "賣", s.get("ask_price"), "最後", s.get("last_price"), s.get("update_time"))
        return

    if a.diagnose:
        return diagnose(a.since)
    rows, accounts = ([], []) if a.fixed else read_holdings(a.since)
    if not rows:
        print("（富途 API 冇讀到持倉，改用 position.json 嘅固定持倉）")
        rows = fixed_holdings()
    by = quotes([r["code"] for r in rows])
    by.update(quotes([c for c in UNDERLYING_CODES if c not in by], quiet=True))   # 標的：冇權限唔使報錯
    rows = pnl(rows, by)
    show(rows)
    for acc in accounts:
        print(f"資金（{acc['account']}，{acc.get('currency')}）：權益 {acc.get('total_assets')}，"
              f"初始保證金 {acc.get('initial_margin')}，維持保證金 {acc.get('maintenance_margin')}")
    out = {"fetched_hkt": datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S"), "positions": rows,
           "quotes": quote_dict(by), "accounts": accounts}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已寫入 {OUT}")
    if a.push:
        push()


if __name__ == "__main__":
    main()
