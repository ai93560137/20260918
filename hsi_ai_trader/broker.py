"""Futu OpenD 接口包裝。所有同富途嘅溝通都喺呢度。"""
import time as _time
import logging
from datetime import datetime, timedelta

from futu import (OpenQuoteContext, OpenFutureTradeContext, RET_OK, Market, SecurityType,
                  KLType, AuType, TrdEnv, TrdSide, OrderType, ModifyOrderOp, OrderStatus,
                  SecurityFirm, PositionSide)

from rules import HKT, CONTRACT_RE

log = logging.getLogger("broker")

FILLED = {OrderStatus.FILLED_ALL}
DEAD = {OrderStatus.CANCELLED_ALL, OrderStatus.CANCELLED_PART, OrderStatus.FAILED,
        OrderStatus.DISABLED, OrderStatus.DELETED, OrderStatus.FILL_CANCELLED}


class BrokerError(Exception):
    pass


def _ok(ret, data, what):
    if ret != RET_OK:
        raise BrokerError(f"{what}: {data}")
    return data


class FutuBroker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.env = TrdEnv.REAL if cfg.trd_env.upper() == "REAL" else TrdEnv.SIMULATE
        self.quote = OpenQuoteContext(host=cfg.opend_host, port=cfg.opend_port)
        self.trade = OpenFutureTradeContext(host=cfg.opend_host, port=cfg.opend_port,
                                            security_firm=SecurityFirm.FUTUSECURITIES)
        if self.env == TrdEnv.REAL and cfg.trade_password:
            _ok(*self.trade.unlock_trade(password=cfg.trade_password), "unlock_trade")
        self.acc_id = cfg.acc_id or self._pick_account()
        log.info("Futu 已連接 env=%s acc_id=%s", cfg.trd_env, self.acc_id)

    def close(self):
        self.quote.close()
        self.trade.close()

    # ---------- 戶口 ----------
    def _pick_account(self):
        df = _ok(*self.trade.get_acc_list(), "get_acc_list")
        df = df[df["trd_env"] == self.env]
        if "acc_status" in df:
            df = df[df["acc_status"] != "DISABLED"]
        if df.empty:
            raise BrokerError(f"搵唔到 {self.env} 期貨戶口")
        return int(df.iloc[0]["acc_id"])

    def equity(self) -> float:
        df = _ok(*self.trade.accinfo_query(trd_env=self.env, acc_id=self.acc_id,
                                           refresh_cache=False, currency="HKD"), "accinfo_query")
        return float(df.iloc[0]["total_assets"])

    def positions(self, product: str):
        """回傳 {code: (signed_qty, cost_price)}，只計該產品嘅期貨。"""
        df = _ok(*self.trade.position_list_query(trd_env=self.env, acc_id=self.acc_id,
                                                 refresh_cache=False, currency="HKD"),
                 "position_list_query")
        out = {}
        for _, r in df.iterrows():
            m = CONTRACT_RE.match(str(r["code"]))
            if not m or m.group(1) != product:
                continue
            qty = float(r["qty"])
            if qty == 0:
                continue
            side = str(r.get("position_side", "LONG"))
            signed = -abs(qty) if (side == PositionSide.SHORT or qty < 0) else abs(qty)
            cost = r.get("cost_price")
            try:
                cost = float(cost)
            except (TypeError, ValueError):
                cost = None
            out[str(r["code"])] = (int(signed), cost)
        return out

    # ---------- 行情 ----------
    def list_contracts(self, product: str):
        df = _ok(*self.quote.get_stock_basicinfo(Market.HK, SecurityType.FUTURE),
                 "get_stock_basicinfo")
        res = []
        for _, r in df.iterrows():
            code = str(r["code"])
            m = CONTRACT_RE.match(code)
            if not m or m.group(1) != product:
                continue
            ltd = str(r.get("last_trade_time", "") or "")[:10]
            try:
                d = datetime.strptime(ltd, "%Y-%m-%d").date()
            except ValueError:
                d = None
            res.append((code, d))
        return res

    def snapshot(self, code: str) -> dict:
        df = _ok(*self.quote.get_market_snapshot([code]), "get_market_snapshot")
        r = df.iloc[0]
        upd = str(r.get("update_time", ""))
        try:
            ut = datetime.strptime(upd[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT)
        except ValueError:
            ut = None
        return {"last": float(r["last_price"]), "bid": float(r.get("bid_price") or 0),
                "ask": float(r.get("ask_price") or 0), "update_time": ut,
                "volume": float(r.get("volume") or 0)}

    def klines(self, code: str, ktype: str, days_back: int, max_count: int):
        end = datetime.now(HKT)
        start = end - timedelta(days=days_back)
        kt = {"5m": KLType.K_5M, "1d": KLType.K_DAY, "60m": KLType.K_60M}[ktype]
        ret, df, _ = self.quote.request_history_kline(
            code, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"),
            ktype=kt, autype=AuType.NONE, max_count=1000)
        df = _ok(ret, df, f"request_history_kline {code} {ktype}")
        df = df.tail(max_count)
        return [{"t": str(r["time_key"])[:16], "o": float(r["open"]), "h": float(r["high"]),
                 "l": float(r["low"]), "c": float(r["close"]), "v": float(r["volume"])}
                for _, r in df.iterrows()]

    # ---------- 落單 ----------
    def market_order(self, code: str, side: int, qty: int, slippage: float, timeout=15):
        """以可成交限價單模擬市價：買用 ask+滑點，賣用 bid-滑點。回傳成交價或 None。"""
        snap = self.snapshot(code)
        if side > 0:
            ref = snap["ask"] or snap["last"]
            price = ref + slippage
            trd_side = TrdSide.BUY
        else:
            ref = snap["bid"] or snap["last"]
            price = ref - slippage
            trd_side = TrdSide.SELL
        df = _ok(*self.trade.place_order(price=round(price), qty=qty, code=code,
                                         trd_side=trd_side, order_type=OrderType.NORMAL,
                                         trd_env=self.env, acc_id=self.acc_id,
                                         remark="zhuge-longfei"), "place_order")
        order_id = str(df.iloc[0]["order_id"])
        log.info("落單 %s %s x%d @%s id=%s", trd_side, code, qty, round(price), order_id)
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            _time.sleep(1)
            od = _ok(*self.trade.order_list_query(order_id=order_id, trd_env=self.env,
                                                  acc_id=self.acc_id, refresh_cache=False),
                     "order_list_query")
            if od.empty:
                continue
            st = od.iloc[0]["order_status"]
            if st in FILLED:
                return float(od.iloc[0].get("dealt_avg_price") or price)
            if st in DEAD:
                log.warning("單 %s 狀態 %s", order_id, st)
                return None
        # 超時：取消
        self.trade.modify_order(ModifyOrderOp.CANCEL, order_id, 0, 0,
                                trd_env=self.env, acc_id=self.acc_id)
        log.warning("單 %s 超時已取消", order_id)
        return None
