"""[R223] 試富途伺服器端止蝕單（HK 期貨，只限模擬戶口）：掛 → 查 → 改 → 撤。

總指揮 10-18：HSI 轉真倉前要有「OpenD／VM 死咗都生效」嘅後備止蝕，唔接受淨係 Telegram watchdog。
呢個程式只係驗證富途模擬期貨戶口接唔接受 STOP／STOP_LIMIT 單：止蝕價放喺現價下面 2,000 點（唔會觸發），
每張單掛完即刻改價再撤，最後一定撤晒。寫死 SIMULATE，唔會掂真戶口。

用法（VM 瀏覽器 SSH，提示符要係 @futu-data-tw）：
    cd ~/20260918/hsi_ai_trader && ~/zhuge-venv/bin/python stop_order_probe.py
"""
import inspect
import os
import sys
import time
from dataclasses import replace
from datetime import datetime

os.environ["PRODUCT"] = "HSI"
os.environ.pop("LONGFEI_INSTANCE", None)            # 確保唔係真倉程式設定

from futu import ModifyOrderOp, OrderType, TrdEnv, TrdSide  # noqa: E402

from broker import FutuBroker  # noqa: E402
from config import Config  # noqa: E402
from markets import spec_for  # noqa: E402
from rules import pick_front_month  # noqa: E402

DIST = 2000          # 止蝕價離現價幾多點（唔會觸發）


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


def try_type(b, code, last, otype, name):
    tick = b.spec.tick
    aux = round(last - DIST)
    price = aux - 50 * tick if otype == OrderType.STOP_LIMIT else aux
    params = inspect.signature(b.trade.place_order).parameters
    if "aux_price" not in params:
        say(f"❌ {name}：futu-api 版本冇 aux_price 參數，要升級 futu-api")
        return False
    say(f"\n== {name}：賣 1 張 {code}，觸發價 {aux}（現價 {last}，低 {DIST} 點，唔會觸發）")
    ret, df = b.trade.place_order(price=price, qty=1, code=code, trd_side=TrdSide.SELL, order_type=otype,
                                  aux_price=aux, trd_env=TrdEnv.SIMULATE, acc_id=b.acc_id,
                                  remark="zhuge-longfei-stop-probe")
    if ret != 0:
        say(f"❌ 掛單失敗：{df}")
        return False
    oid = str(df.iloc[0]["order_id"])
    say(f"✅ 掛單成功 order_id={oid}")
    ok = True
    try:
        r = show(b, oid, "掛單後")
        if r is not None and str(r.get("order_status")) in ("FAILED", "DISABLED", "CANCELLED_ALL"):
            ok = False
        new_aux = aux - 100
        new_price = new_aux - 50 * tick if otype == OrderType.STOP_LIMIT else new_aux
        mp = inspect.signature(b.trade.modify_order).parameters
        kw = {"aux_price": new_aux} if "aux_price" in mp else {}
        ret, d2 = b.trade.modify_order(ModifyOrderOp.NORMAL, oid, 1, new_price, trd_env=TrdEnv.SIMULATE,
                                       acc_id=b.acc_id, **kw)
        say(("✅ 改價成功" if ret == 0 else f"❌ 改價失敗：{d2}") + f"（觸發價改做 {new_aux}）")
        ok = ok and ret == 0
        show(b, oid, "改價後")
    finally:
        ret, d3 = b.trade.modify_order(ModifyOrderOp.CANCEL, oid, 0, 0, trd_env=TrdEnv.SIMULATE, acc_id=b.acc_id)
        say("✅ 已撤單" if ret == 0 else f"⚠ 撤單失敗：{d3}（請喺富途 App 模擬盤人手撤 {oid}）")
        show(b, oid, "撤單後")
    return ok


def main():
    cfg = replace(Config(), trd_env="SIMULATE", product="HSI", acc_id=0)
    b = FutuBroker(cfg)
    if b.env != TrdEnv.SIMULATE:
        say("❌ 唔係模擬環境，停止")
        sys.exit(1)
    try:
        sp = spec_for("HSI")
        code = pick_front_month(b.list_contracts("HSI"), "HSI", datetime.now(sp.tz).date(), cfg.roll_days)
        last = b.snapshot(code)["last"]
        say(f"模擬期貨戶口 acc_id={b.acc_id}；合約 {code}；現價 {last}；時間 {datetime.now(sp.tz):%Y-%m-%d %H:%M}")
        res = {name: try_type(b, code, last, ot, name)
               for name, ot in (("STOP（止損市價）", OrderType.STOP), ("STOP_LIMIT（止損限價）", OrderType.STOP_LIMIT))}
        say("\n== 結果：" + "；".join(f"{k} {'✅' if v else '❌'}" for k, v in res.items()))
    finally:
        b.close()


if __name__ == "__main__":
    main()
