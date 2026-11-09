"""[IDEAS #2018 → 真倉] 龍飛陣 12 個月時間序列動量：MNQ／MES 各最多 1 張，月度只做好（使用者 11-09「12 個月動量 MNQ／MES 各 1 張提早真倉」）。

規則（同回測 batch6 K1 L12 一樣）：每月最後一個美股交易日收市，過去 12 個月（月尾對月尾）報酬 > 0 → 下個月揸 1 張好倉；≤ 0 → 空手。
信號數據：Yahoo NQ=F／ES=F 日線（同回測一樣來源）；攞唔到就用富途 US.<產品>main 日 K；兩樣都攞唔到就唔郁、發 Telegram。

執行（zhuge-longfei-tsm.timer，星期一至五 07:40 HKT＝美東前一晚 18:40／19:40，CME 已重開）：
  1. 新月份決定（上個月已完）：目標 1 而冇倉 → 買 1 張即月；目標 0 而有倉 → 賣出、撤後備止蝕。
     （同回測差異：回測喺月尾收市成交，真倉喺之後第一個晚上成交，相差約 2–3 個鐘或一個週末）
  2. 轉倉：揸緊嘅合約距離最後交易日 ≤ 8 日（markets.SPECS roll_days）→ 賣舊買新、搬止蝕。
  3. 對賬：戶口嗰張合約少過程式記錄 → 查後備止蝕單有冇成交；有就當止蝕出咗，今個月唔再入；冇就發 Telegram 等人睇（可能係人手交易）。
  4. 後備止蝕：入場價 ×（1 − LONGFEI_TSM_STOP_PCT，預設 12%）掛富途伺服器端 GTC 止損單（回測冇止蝕，呢個只係防災難；0 = 唔掛）。
安全：
  - 只有 settings.env LONGFEI_TSM_PRODUCTS 列明嘅產品先落真單（例如 MNQ,MES）；冇列 = 只計信號、寫 log、唔落單。
  - 每隻最多 LONGFEI_TSM_QTY（預設 1）張、只做好；狀態檔 ~/zhuge/tsm/<產品>.json（flock 防重複執行）；~/zhuge/tsm/STOP 存在 = 唔落任何新單。
  - 落單用可成交限價（參考價 ± 0.25%），60 秒未成交就撤、下一日再試；單 remark「zhuge-longfei-tsm」方便總指揮配對。
  - 唔印權杖；Telegram 用 ~/zhuge/env 嘅 TG_BOT_TOKEN／TG_CHAT_ID（同 longfei_guard）。
用法：python tsm_monthly.py [--dry-run] [--products MNQ,MES]
"""
import argparse
import fcntl
import json
import logging
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

log = logging.getLogger("tsm")
ET = ZoneInfo("America/New_York")
HKT = ZoneInfo("Asia/Hong_Kong")
YAHOO = {"MNQ": "NQ=F", "MES": "ES=F"}
LOOKBACK = 12
BUFFER = 0.0025
REMARK = "zhuge-longfei-tsm"
STATE_DIR = Path(os.getenv("TSM_DIR", str(Path.home() / "zhuge" / "tsm"))).expanduser()


# ---------- 純函數（tests/test_tsm_monthly.py） ----------
def month_end_closes(daily):
    """daily: [(YYYY-MM-DD, close)] 已排序 → [(YYYY-MM, 月尾日期, 收市)]（每月最後一根）。"""
    out = {}
    for d, c in daily:
        if c is None or not math.isfinite(c):
            continue
        out[d[:7]] = (d, c)
    return [(m, d, c) for m, (d, c) in sorted(out.items())]


def signal(daily, now_et):
    """用已完結嘅月份計信號 → dict(month, date, ret12, target) 或 None（數據唔夠）。"""
    cur = now_et.strftime("%Y-%m")
    ends = [x for x in month_end_closes(daily) if x[0] < cur]
    if len(ends) < LOOKBACK + 1:
        return None
    m, d, c = ends[-1]
    c0 = ends[-1 - LOOKBACK][2]
    r = c / c0 - 1
    return {"month": m, "date": d, "ret12": round(r, 5), "target": 1 if r > 0 else 0}


def plan(state, sig, front, held_qty, stop_filled):
    """決定要做乜（唔做 I/O）。state：{qty, code, month}；held_qty：戶口 state.code 嘅數量；
    回傳 (actions, notes)，actions 係 [("buy", code) | ("sell", code) | ("mark_flat", 原因) | ("set_month", m)]。"""
    acts, notes = [], []
    qty, code = int(state.get("qty") or 0), state.get("code")
    if qty > 0 and held_qty < qty:
        if stop_filled:
            acts.append(("mark_flat", "後備止蝕成交"))
            qty = 0
        else:
            notes.append(f"戶口 {code} 得 {held_qty} 張，少過程式記錄 {qty} 張（人手交易？）：唔郁，等人睇")
            return acts, notes
    if sig and sig["month"] != state.get("month"):
        if sig["target"] == 1 and qty == 0:
            if front:
                acts.append(("buy", front))
            else:
                notes.append("搵唔到即月合約")
                return acts, notes
        elif sig["target"] == 0 and qty > 0:
            acts.append(("sell", code))
            qty = 0
        acts.append(("set_month", sig["month"]))
    if qty > 0 and front and code and code != front and not any(a[0] == "sell" for a in acts):
        acts += [("sell", code), ("buy", front)]
        notes.append(f"轉倉 {code} → {front}")
    return acts, notes


def limit_price(ref, side, tick):
    raw = ref * (1 + BUFFER) if side > 0 else ref * (1 - BUFFER)
    return round((math.ceil(raw / tick - 1e-9) if side > 0 else math.floor(raw / tick + 1e-9)) * tick, 4)


def stop_price(entry, pct, tick):
    return round(math.floor(entry * (1 - pct) / tick + 1e-9) * tick, 4)


# ---------- I/O ----------
def telegram(text):
    tok, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not tok or not chat:
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": "[龍飛陣 12 個月動量] " + text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=15).read()
    except Exception as e:  # noqa: BLE001  唔印網址（有權杖）
        log.warning("Telegram 失敗：%s", e.__class__.__name__)


def yahoo_daily(product):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(YAHOO[product])}?range=2y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (zhuge-longfei)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read())["chart"]["result"][0]
    ts, closes = res["timestamp"], res["indicators"]["quote"][0]["close"]
    last = res.get("meta", {}).get("regularMarketPrice")
    # 時間戳 +6 小時再轉美東日期：無論 Yahoo 用 00:00 定前一晚 18:00 做開始，都落喺正確交易日
    daily = [(datetime.fromtimestamp(t + 6 * 3600, ET).strftime("%Y-%m-%d"), c) for t, c in zip(ts, closes)]
    return daily, (float(last) if last else None)


def futu_daily(broker, product):
    rows = broker.klines(f"US.{product}main", "1d", 800, 1000)
    return [(r["t"][:10], r["c"]) for r in rows]


def load_state(product):
    f = STATE_DIR / f"{product}.json"
    try:
        return json.loads(f.read_text())
    except (FileNotFoundError, ValueError):
        return {"qty": 0, "code": None, "month": None}


def save_state(product, st):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    f = STATE_DIR / f"{product}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    os.replace(tmp, f)


def order_status_filled(broker, order_id):
    from broker import FILLED
    row = broker._order_row(order_id) if order_id else None
    return bool(row is not None and row["order_status"] in FILLED)


def place(broker, code, side, qty, ref, tick):
    from futu import OrderType, TrdSide
    from broker import DEAD, FILLED
    place.last_error = ""
    price = limit_price(ref, side, tick)
    df = broker._place(price=price, qty=qty, code=code, trd_side=TrdSide.BUY if side > 0 else TrdSide.SELL,
                       order_type=OrderType.NORMAL, trd_env=broker.env, acc_id=broker.acc_id, remark=REMARK)
    oid = str(df.iloc[0]["order_id"])
    log.info("落單 %s %s x%d @%s id=%s", "買" if side > 0 else "賣", code, qty, price, oid)
    for _ in range(60):
        time.sleep(1)
        row = broker._order_row(oid)
        if row is None:
            continue
        if row["order_status"] in FILLED:
            return broker._fill(row, price, qty)
        if row["order_status"] in DEAD:
            # [11-09] 首次真倉兩張單「下單失敗」查唔到原因：記低富途嘅狀態同錯誤訊息，寫 log 同 Telegram
            place.last_error = f"{row['order_status']}：{row.get('last_err_msg') or ''}".strip("：")
            log.warning("單 %s 失敗：%s", oid, place.last_error)
            return broker._fill(row, price, 0)
    place.last_error = "60 秒未成交，已撤單"
    return broker.cancel_order(oid)


place.last_error = ""


def ref_price(broker, code, yahoo_last):
    try:
        q = broker.snapshot(code, fresh=True)
        if q.get("last"):
            return float(q["last"]), "富途"
    except Exception as e:  # noqa: BLE001
        log.info("富途報價攞唔到（%s），用 Yahoo", str(e)[:80])
    return yahoo_last, "Yahoo"


def run_product(product, armed, dry_run, qty_max, stop_pct):
    from broker import FutuBroker
    from markets import spec_for
    from rules import pick_front_month
    spec = spec_for(product)
    st = load_state(product)
    now_et = datetime.now(ET)
    daily, ylast, src = None, None, "Yahoo"
    try:
        daily, ylast = yahoo_daily(product)
    except Exception as e:  # noqa: BLE001
        log.warning("%s Yahoo 日線失敗：%s", product, e.__class__.__name__)
    trade = armed and not dry_run
    cfg = SimpleNamespace(trd_env="REAL" if trade else "SIMULATE", opend_host=os.getenv("OPEND_HOST", "127.0.0.1"),
                          opend_port=int(os.getenv("OPEND_PORT", "11111")), product=product,
                          trade_password=os.getenv("FUTU_TRADE_PASSWORD", "") if trade else "",
                          acc_id=int(os.getenv("FUTU_ACC_ID", "0")), real_acc_id=int(os.getenv("FUTU_REAL_ACC_ID", "0")))
    broker = FutuBroker(cfg)
    try:
        if daily is None:
            try:
                daily, src = futu_daily(broker, product), "富途"
            except Exception as e:  # noqa: BLE001
                telegram(f"{product}：Yahoo 同富途日線都攞唔到（{str(e)[:60]}），今日唔郁")
                return
        sig = signal(daily, now_et)
        today = now_et.date()
        try:
            contracts = broker.list_contracts(product)
        except Exception:  # noqa: BLE001
            from markets import quarterly_contracts
            contracts = quarterly_contracts(product, spec.market, today)
        front = pick_front_month(contracts, product, today, spec.roll_days)
        held = 0
        if st.get("code"):
            pos = broker.positions(product)
            held = max(0, pos.get(st["code"], (0, None))[0])
        stop_filled = order_status_filled(broker, st.get("stop_id")) if st.get("qty") else False
        acts, notes = plan(st, sig, front, held, stop_filled)
        log.info("%s 信號 %s（%s）前月 %s 狀態 %s → %s %s", product, sig, src, front, st, acts, notes)
        for n in notes:
            telegram(f"{product}：{n}")
        if not armed or dry_run:
            if acts:
                log.info("%s 未啟用真倉（LONGFEI_TSM_PRODUCTS）或 dry-run：唔落單", product)
            return
        if (STATE_DIR / "STOP").exists() and any(a[0] == "buy" for a in acts):
            telegram(f"{product}：有 STOP 檔，唔開新倉（{acts}）")
            acts = [a for a in acts if a[0] != "buy"]
        for kind, arg in acts:
            if kind == "mark_flat":
                telegram(f"{product}：{arg}，記錄改為空手；今個月唔再入")
                st.update(qty=0, code=None, stop_id=None)
            elif kind == "set_month":
                st["month"] = arg
                st["ret12"] = sig["ret12"]
            elif kind == "sell":
                ref, rs = ref_price(broker, arg, ylast)
                if st.get("stop_id"):
                    broker.cancel_order(st["stop_id"])
                px, q = place(broker, arg, -1, int(st.get("qty") or 1), ref, spec.tick)
                if q <= 0:
                    telegram(f"{product}：賣 {arg} 未成交（限價參考 {rs} {ref}；富途：{place.last_error or '冇訊息'}），聽日再試")
                    if st.get("stop_id"):
                        st["stop_id"] = None          # 止蝕已撤，下次重新掛
                    save_state(product, st)
                    return
                telegram(f"{product}：賣出 {arg} x{q} @{px}（入場 {st.get('entry')}）")
                st.update(qty=0, code=None, stop_id=None, exit=px, exit_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            elif kind == "buy":
                ref, rs = ref_price(broker, arg, ylast)
                if not ref:
                    telegram(f"{product}：冇參考價，唔買 {arg}")
                    return
                px, q = place(broker, arg, +1, qty_max, ref, spec.tick)
                if q <= 0:
                    telegram(f"{product}：買 {arg} 未成交（限價參考 {rs} {ref}；富途：{place.last_error or '冇訊息'}），聽日再試")
                    save_state(product, st)              # 未記 set_month，聽日會再試
                    return
                st.update(qty=q, code=arg, entry=px, entry_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          stop_id=None)
                if stop_pct > 0:
                    try:
                        st["stop_id"] = broker.stop_order(arg, -1, q, stop_price(px, stop_pct, spec.tick))
                    except Exception as e:  # noqa: BLE001
                        telegram(f"{product}：後備止蝕掛唔到（{str(e)[:60]}），請人手掛")
                telegram(f"{product}：買入 {arg} x{q} @{px}（12 個月報酬 {sig['ret12'] if sig else '?'}；後備止蝕 "
                         f"{stop_price(px, stop_pct, spec.tick) if stop_pct > 0 else '冇'}）")
            save_state(product, st)
        save_state(product, st)
    finally:
        broker.close()


def diagnose(products):
    """唯讀：列出真倉戶口最近 3 日 remark=zhuge-longfei-tsm 嘅單同富途錯誤訊息（唔解鎖、唔落單）。"""
    from broker import FutuBroker
    from futu import TrdEnv
    for product in products:
        cfg = SimpleNamespace(trd_env="REAL", opend_host=os.getenv("OPEND_HOST", "127.0.0.1"),
                              opend_port=int(os.getenv("OPEND_PORT", "11111")), product=product, trade_password="",
                              acc_id=int(os.getenv("FUTU_ACC_ID", "0")), real_acc_id=int(os.getenv("FUTU_REAL_ACC_ID", "0")))
        broker = FutuBroker(cfg)
        try:
            start = (datetime.now(HKT) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
            ret, df = broker.trade.history_order_list_query(trd_env=TrdEnv.REAL, acc_id=broker.acc_id, start=start)
            if ret != 0:
                print(product, "查唔到訂單：", df)
                continue
            for _, r in df.iterrows():
                if product in str(r.get("code")):
                    print(product, r.get("create_time"), r.get("code"), r.get("trd_side"), r.get("qty"), r.get("price"),
                          r.get("order_status"), "remark=", r.get("remark"), "錯誤=", r.get("last_err_msg"))
        finally:
            broker.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--diagnose", action="store_true", help="唯讀：列出最近真倉單同富途錯誤訊息")
    ap.add_argument("--products", default="MNQ,MES")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.diagnose:
        diagnose([x.strip().upper() for x in a.products.split(",") if x.strip()])
        return
    armed = {x.strip().upper() for x in os.getenv("LONGFEI_TSM_PRODUCTS", "").split(",") if x.strip()}
    qty = max(1, min(int(os.getenv("LONGFEI_TSM_QTY", "1")), 1))         # 使用者批 1 張；改多要再批
    stop_pct = float(os.getenv("LONGFEI_TSM_STOP_PCT", "0.12"))
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / ".lock", "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log.warning("另一個 tsm 程式運行緊，退出")
            return
        for p in [x.strip().upper() for x in a.products.split(",") if x.strip()]:
            if p not in YAHOO:
                continue
            try:
                run_product(p, p in armed, a.dry_run, qty, stop_pct)
            except Exception as e:  # noqa: BLE001
                log.exception("%s 出錯", p)
                telegram(f"{p}：程式出錯 {e.__class__.__name__}: {str(e)[:80]}")
    sys.exit(0)


if __name__ == "__main__":
    main()
