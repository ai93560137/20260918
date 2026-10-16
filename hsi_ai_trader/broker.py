"""Futu OpenD 接口包裝。所有同富途嘅溝通都喺呢度。"""
import math
import time as _time
import logging
from datetime import datetime, timedelta

from futu import (OpenQuoteContext, OpenFutureTradeContext, OpenSecTradeContext, RET_OK, Market,
                  SecurityType, KLType, AuType, TrdEnv, TrdSide, TrdMarket, OrderType, ModifyOrderOp,
                  OrderStatus, SecurityFirm, PositionSide)

from markets import quarterly_contracts, spec_for
from rules import HKT, CONTRACT_RE

log = logging.getLogger("broker")

FILLED = {OrderStatus.FILLED_ALL}
DEAD = {OrderStatus.CANCELLED_ALL, OrderStatus.CANCELLED_PART, OrderStatus.FAILED,
        OrderStatus.DISABLED, OrderStatus.DELETED, OrderStatus.FILL_CANCELLED}


class BrokerError(Exception):
    pass


def _num(v):
    """富途有啲欄位會係 'N/A'（例如期貨戶口嘅購買力）；當 0。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x != x else x


def _ok(ret, data, what):
    if ret != RET_OK:
        raise BrokerError(f"{what}: {data}")
    return data


class FutuBroker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.env = TrdEnv.REAL if cfg.trd_env.upper() == "REAL" else TrdEnv.SIMULATE
        self.quote = OpenQuoteContext(host=cfg.opend_host, port=cfg.opend_port)
        self.spec = spec_for(cfg.product)
        if self.spec.kind == "stock":                      # ETF：證券戶口（美股）
            self.trade = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=cfg.opend_host,
                                             port=cfg.opend_port, security_firm=SecurityFirm.FUTUSECURITIES)
        else:
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
        # 模擬盤港期／美期可能係唔同戶口：優先揀交易權限包含該市場嘅（例如 US），揀唔到就用第一個
        mkt = self.spec.market
        if "trdmarket_auth" in df:
            hit = df[df["trdmarket_auth"].astype(str).str.contains(mkt)]
            if not hit.empty:
                df = hit
        row = df.iloc[0]
        log.info("揀戶口 acc_id=%s 權限=%s（產品 %s，市場 %s）", row["acc_id"], row.get("trdmarket_auth"),
                 self.cfg.product, mkt)
        return int(row["acc_id"])

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
            code = str(r["code"])
            if self.spec.kind == "stock":
                if code != f"{self.spec.market}.{product}":
                    continue
            else:
                m = CONTRACT_RE.match(code)
                if not m or m.group(2) != product:
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
        market = Market.US if self.spec.market == "US" else Market.HK
        df = _ok(*self.quote.get_stock_basicinfo(market, SecurityType.FUTURE),
                 "get_stock_basicinfo")
        res = []
        for _, r in df.iterrows():
            code = str(r["code"])
            m = CONTRACT_RE.match(code)
            if not m or m.group(2) != product:
                continue
            ltd = str(r.get("last_trade_time", "") or "")[:10]
            try:
                d = datetime.strptime(ltd, "%Y-%m-%d").date()
            except ValueError:
                d = None
            res.append((code, d))
        if not res and self.spec.market == "US":       # 富途攞唔到美期合約列表：按 CME 季月規則推算
            res = quarterly_contracts(product, "US", datetime.now(self.spec.tz).date())
            log.warning("富途冇 %s 合約列表，用季月推算：%s", product, [c for c, _ in res])
        return res

    def snapshot(self, code: str) -> dict:
        df = _ok(*self.quote.get_market_snapshot([code]), "get_market_snapshot")
        r = df.iloc[0]
        upd = str(r.get("update_time", ""))
        try:
            # 富途報價時間係交易所當地時間（港期 HKT、美期美東）；SIMULATE 首日要核實美期
            ut = datetime.strptime(upd[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.spec.tz)
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

    # ---------- 真倉準備（唯讀；唔落單、唔解鎖）----------
    def _real_account(self):
        df = _ok(*self.trade.get_acc_list(), "get_acc_list")
        df = df[df["trd_env"] == TrdEnv.REAL]
        if "acc_status" in df:
            df = df[df["acc_status"] != "DISABLED"]
        if self.cfg.real_acc_id:
            df = df[df["acc_id"] == self.cfg.real_acc_id]
        elif "trdmarket_auth" in df:
            hit = df[df["trdmarket_auth"].astype(str).str.contains(self.spec.market)]
            if not hit.empty:
                df = hit
        return None if df.empty else df.iloc[0]

    def real_preflight(self, code: str, qty: int, price: float) -> dict:
        """查真實戶口準備好未（入咗錢、孖展、可唔可以買／沽空 qty 股或張、美股日內交易限制）。
        只查詢，唔落單、唔解鎖；只回傳是／否同次數，唔回傳金額或戶口號碼（會上載 GCS）。"""
        row = self._real_account()
        if row is None:
            return {"ok": False, "found": False, "note": f"搵唔到 {self.spec.market} 真實戶口"}
        acc_id = int(row["acc_id"])
        out = {"found": True, "acc_type": str(row.get("acc_type", "")), "qty": qty}
        ccy = "USD" if self.spec.currency == "USD" else "HKD"
        info = _ok(*self.trade.accinfo_query(trd_env=TrdEnv.REAL, acc_id=acc_id, refresh_cache=True,
                                             currency=ccy), "accinfo_query REAL").iloc[0]
        out["funded"] = _num(info.get("total_assets")) > 0
        for k in ("is_pdt", "pdt_seq", "dt_status", "risk_status"):
            v = info.get(k)
            if v is not None and str(v) not in ("", "N/A", "nan"):
                out[k] = v if isinstance(v, (bool, int)) else str(v)
        ti = _ok(*self.trade.acctradinginfo_query(order_type=OrderType.NORMAL, code=code, price=price,
                                                  trd_env=TrdEnv.REAL, acc_id=acc_id),
                 "acctradinginfo_query REAL").iloc[0]
        if self.spec.kind == "future":
            # 期貨：富途 max_cash_and_margin_buy／max_sell_short 係 'N/A'；改用「最大購買力」(power) 對比每張初始保證金。
            # 只回傳佔購買力百分比（唔係金額）
            power = _num(info.get("power"))
            for side, k in (("long", "long_required_im"), ("short", "short_required_im")):
                im = _num(ti.get(k)) * qty
                out[f"can_{side}"] = power > 0 and (im <= power if im > 0 else True)
                if im > 0 and power > 0:
                    out[f"im_pct_{side}"] = round(im / power * 100)
        else:
            out["can_long"] = _num(ti.get("max_cash_and_margin_buy")) >= qty
            out["can_short"] = _num(ti.get("max_sell_short")) >= qty
        out["ok"] = bool(out["funded"] and out["can_long"] and out["can_short"])
        return out

    def max_open_qty(self, code: str, side: int, price: float):
        """而家戶口（SIMULATE 或 REAL）最多可以開幾多：做好用現金＋孖展購買力，做淡用可沽空數量。"""
        ti = _ok(*self.trade.acctradinginfo_query(order_type=OrderType.NORMAL, code=code, price=price,
                                                  trd_env=self.env, acc_id=self.acc_id),
                 "acctradinginfo_query").iloc[0]
        return int(_num(ti.get("max_cash_and_margin_buy" if side > 0 else "max_sell_short")))

    # ---------- 落單 ----------
    def _order_row(self, order_id):
        od = _ok(*self.trade.order_list_query(order_id=order_id, trd_env=self.env,
                                              acc_id=self.acc_id, refresh_cache=False), "order_list_query")
        return None if od.empty else od.iloc[0]

    @staticmethod
    def _fill(row, price, default_qty):
        """由訂單資料計 (成交均價, 成交數量)；冇成交回傳 (None, 0)。"""
        q = int(_num(row.get("dealt_qty"))) or default_qty
        if q <= 0:
            return None, 0
        return _num(row.get("dealt_avg_price")) or price, q

    def market_order(self, code: str, side: int, qty: int, slippage: float, timeout=15):
        """以可成交限價單模擬市價：買用 ask+滑點，賣用 bid-滑點。
        回傳 (成交均價, 成交數量)；完全冇成交回傳 (None, 0)。超時會取消，取消後再查：部分成交同取消前啱啱成交都計返。"""
        snap = self.snapshot(code)
        tick = self.spec.tick
        if side > 0:
            ref = snap["ask"] or snap["last"]
            price = math.ceil((ref + slippage) / tick - 1e-9) * tick     # 買：向上取 tick
            trd_side = TrdSide.BUY
        else:
            ref = snap["bid"] or snap["last"]
            price = math.floor((ref - slippage) / tick + 1e-9) * tick    # 賣：向下取 tick
            trd_side = TrdSide.SELL
        price = round(price, 4)
        extra = {"fill_outside_rth": True} if self.spec.kind == "stock" else {}   # ETF 盤前盤後都可成交
        df = _ok(*self.trade.place_order(price=price, qty=qty, code=code,
                                         trd_side=trd_side, order_type=OrderType.NORMAL,
                                         trd_env=self.env, acc_id=self.acc_id,
                                         remark="zhuge-longfei", **extra), "place_order")
        order_id = str(df.iloc[0]["order_id"])
        log.info("落單 %s %s x%d @%s id=%s", trd_side, code, qty, price, order_id)
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            _time.sleep(1)
            row = self._order_row(order_id)
            if row is None:
                continue
            st = row["order_status"]
            if st in FILLED:
                return self._fill(row, price, qty)
            if st in DEAD:
                log.warning("單 %s 狀態 %s", order_id, st)
                return self._fill(row, price, 0)          # 部分成交後取消（CANCELLED_PART）都計返已成交嗰啲
        # 超時：取消，再查最終成交（取消同成交可能同時發生）
        try:
            self.trade.modify_order(ModifyOrderOp.CANCEL, order_id, 0, 0, trd_env=self.env, acc_id=self.acc_id)
        except Exception:  # noqa: BLE001
            log.exception("取消單 %s 失敗", order_id)
        row = None
        for _ in range(5):
            _time.sleep(1)
            row = self._order_row(order_id)
            if row is not None and (row["order_status"] in FILLED or row["order_status"] in DEAD):
                break
        if row is None:
            log.error("單 %s 超時、取消後查唔到狀態；下一輪對賬會見到差額", order_id)
            return None, 0
        px, q = self._fill(row, price, qty if row["order_status"] in FILLED else 0)
        log.warning("單 %s 超時已取消：成交 %d／%d", order_id, q, qty)
        return px, q
