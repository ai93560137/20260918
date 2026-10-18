"""[R223] 試富途伺服器端止蝕單（HK 期貨同美股證券戶口，只限模擬戶口）：掛 → 查 → 改 → 撤。

總指揮 10-18：HSI 轉真倉前要有「OpenD／VM 死咗都生效」嘅後備止蝕，唔接受淨係 Telegram watchdog。
呢個程式只係驗證富途模擬戶口接唔接受 STOP／STOP_LIMIT 單：
- 期貨（HSI）：賣出止蝕，觸發價喺現價下面 2,000 點（唔會觸發）。
- 美股（SPY 等）：買入止蝕 1 股，觸發價喺現價上面 30%（唔會觸發；唔使有倉、唔會變沽空）。
先試 GTC（長期有效，隔夜都生效先算真正後備止蝕），唔受就試當日有效。每張單掛完即刻改價再撤，最後一定撤晒。
預設 SIMULATE。真戶口要同時加 --real --i-understand（使用者 10-18 批准用真戶口試）：單價放得好遠、即掛即撤，
被拒就冇單；真戶口單會由富途 App 見到，跑完要喺 App 確認冇殘留單。

用法（VM 瀏覽器 SSH，提示符要係 @futu-data-tw）：
    cd ~/20260918/hsi_ai_trader && ~/zhuge-venv/bin/python stop_order_probe.py [HSI|SPY] [--real --i-understand]
"""
import inspect
import os
import sys
import time
from dataclasses import replace
from datetime import datetime

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
PRODUCT = (ARGS[0] if ARGS else "HSI").upper()
REAL = "--real" in sys.argv and "--i-understand" in sys.argv
os.environ["PRODUCT"] = PRODUCT
os.environ.pop("LONGFEI_INSTANCE", None)            # 確保唔係真倉程式設定

from futu import ModifyOrderOp, OrderType, TrdEnv, TrdSide  # noqa: E402
try:
    from futu import TimeInForce  # noqa: E402
except ImportError:  # 舊版 futu-api
    TimeInForce = None

from broker import FutuBroker  # noqa: E402
from config import Config  # noqa: E402
from markets import spec_for  # noqa: E402
from rules import pick_front_month  # noqa: E402

DIST = 2000          # 止蝕價離現價幾多點（唔會觸發）
ENV = TrdEnv.REAL if REAL else TrdEnv.SIMULATE


def say(*a):
    print(*a, flush=True)


def order_row(b, oid):
    try:
        return b._order_row(oid)
    except Exception as e:  # noqa: BLE001
        say("   查單出錯：", e)
        return None


def show(b, oid, label):
    time.sleep(2)
    r = order_row(b, oid)
    if r is None:
        say(f"   {label}：查唔到單")
        return None
    say(f"   {label}：狀態={r.get('order_status')} 類型={r.get('order_type')} 價={r.get('price')} "
        f"觸發價={r.get('aux_price', '—')} 有效期={r.get('time_in_force', '—')}")
    return r


def try_type(b, code, last, otype, name, stock):
    tick = b.spec.tick
    if stock:          # 美股：買入止蝕 1 股，觸發價高過現價 30%
        side, aux = TrdSide.BUY, round(last * 1.3, 2)
        price = round(aux + 50 * tick, 2) if otype == OrderType.STOP_LIMIT else aux
        far = f"高 30%"
    else:              # 期貨：賣出止蝕，觸發價低過現價 2,000 點
        side, aux = TrdSide.SELL, round(last - DIST)
        price = aux - 50 * tick if otype == OrderType.STOP_LIMIT else aux
        far = f"低 {DIST} 點"
    params = inspect.signature(b.trade.place_order).parameters
    if "aux_price" not in params:
        say(f"❌ {name}：futu-api 版本冇 aux_price 參數，要升級 futu-api")
        return False
    tifs = ([("GTC", TimeInForce.GTC)] if TimeInForce is not None and "time_in_force" in params else []) + [("當日", None)]
    oid = None
    for tif_name, tif in tifs:
        kw = {"time_in_force": tif} if tif is not None else {}
        if stock and "fill_outside_rth" in params:
            kw["fill_outside_rth"] = False
        say(f"\n== {name}（{tif_name}有效）：{'買' if stock else '賣'} 1 {'股' if stock else '張'} {code}，觸發價 {aux}（現價 {last}，{far}，唔會觸發）")
        ret, df = b.trade.place_order(price=price, qty=1, code=code, trd_side=side, order_type=otype,
                                      aux_price=aux, trd_env=ENV, acc_id=b.acc_id,
                                      remark="zhuge-longfei-stop-probe", **kw)
        if ret == 0:
            oid = str(df.iloc[0]["order_id"])
            say(f"✅ 掛單成功 order_id={oid}")
            break
        say(f"❌ 掛單失敗：{df}")
    if oid is None:
        return False
    ok = True
    try:
        r = show(b, oid, "掛單後")
        if r is not None and str(r.get("order_status")) in ("FAILED", "DISABLED", "CANCELLED_ALL"):
            ok = False
        new_aux = round(aux * 1.01, 2) if stock else aux - 100
        new_price = (round(new_aux + 50 * tick, 2) if stock else new_aux - 50 * tick) \
            if otype == OrderType.STOP_LIMIT else new_aux
        mp = inspect.signature(b.trade.modify_order).parameters
        kw = {"aux_price": new_aux} if "aux_price" in mp else {}
        ret, d2 = b.trade.modify_order(ModifyOrderOp.NORMAL, oid, 1, new_price, trd_env=ENV,
                                       acc_id=b.acc_id, **kw)
        say(("✅ 改價成功" if ret == 0 else f"❌ 改價失敗：{d2}") + f"（觸發價改做 {new_aux}）")
        ok = ok and ret == 0
        show(b, oid, "改價後")
    finally:
        ret, d3 = b.trade.modify_order(ModifyOrderOp.CANCEL, oid, 0, 0, trd_env=ENV, acc_id=b.acc_id)
        say("✅ 已撤單" if ret == 0 else f"⚠ 撤單失敗：{d3}（請即喺富途 App {'真實戶口' if REAL else '模擬盤'}人手撤 {oid}）")
        show(b, oid, "撤單後")
    return ok


def main():
    if "--real" in sys.argv and not REAL:
        say("❌ 真戶口要同時加 --i-understand")
        sys.exit(1)
    cfg = replace(Config(), trd_env="REAL" if REAL else "SIMULATE", product=PRODUCT,
                  acc_id=(Config().real_acc_id if REAL else 0))
    b = FutuBroker(cfg)
    if b.env != ENV:
        say("❌ 環境唔對，停止")
        sys.exit(1)
    if REAL:
        say("⚠ 真實戶口測試：單價好遠唔會觸發，掛完即撤。跑完請喺富途 App 確認冇殘留單。")
    try:
        sp = spec_for(PRODUCT)
        stock = sp.kind == "stock"
        code = (f"US.{PRODUCT}" if stock else
                pick_front_month(b.list_contracts(PRODUCT), PRODUCT, datetime.now(sp.tz).date(), cfg.roll_days))
        last = b.snapshot(code, fresh=True)["last"]
        say(f"{'真實' if REAL else '模擬'}{'證券' if stock else '期貨'}戶口 acc_id={b.acc_id}；{code}；現價 {last}；"
            f"時間 {datetime.now(sp.tz):%Y-%m-%d %H:%M}（{sp.tz}）")
        res = {name: try_type(b, code, last, ot, name, stock)
               for name, ot in (("STOP（止損市價）", OrderType.STOP), ("STOP_LIMIT（止損限價）", OrderType.STOP_LIMIT))}
        say("\n== 結果：" + "；".join(f"{k} {'✅' if v else '❌'}" for k, v in res.items()))
    finally:
        b.close()


if __name__ == "__main__":
    main()
