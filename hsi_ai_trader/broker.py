"""Futu OpenD 接口包裝。所有同富途嘅溝通都喺呢度。"""
import fcntl
import json
import math
import os
import time as _time
import logging
from datetime import datetime, timedelta
from pathlib import Path

from futu import (OpenQuoteContext, OpenFutureTradeContext, OpenSecTradeContext, RET_OK, Market,
                  SecurityType, KLType, AuType, TrdEnv, TrdSide, TrdMarket, OrderType, ModifyOrderOp,
                  OrderStatus, SecurityFirm, PositionSide)

from markets import ET, quarterly_contracts, spec_for
from rules import HKT, CONTRACT_RE

log = logging.getLogger("broker")

FILLED = {OrderStatus.FILLED_ALL}
DEAD = {OrderStatus.CANCELLED_ALL, OrderStatus.CANCELLED_PART, OrderStatus.FAILED,
        OrderStatus.DISABLED, OrderStatus.DELETED, OrderStatus.FILL_CANCELLED}


class BrokerError(Exception):
    pass


# [R226] 10-18：富途報價快照每 30 秒最多 60 次（成個 OpenD 共用）。17 個程式每 5 秒各自查一次 ≈ 每 30 秒 100 次，
# 超額令程式出錯、連 auto_risk／push_to_gcp 都攞唔到報價。改做所有龍飛陣程式共用一個快取檔：
# 舊過 QUOTE_CACHE_SEC 先由其中一個程式一次過查晒所有產品（一個請求），大約每 30 秒 8 次。
QUOTE_CACHE = Path(os.getenv("ZHUGE_QUOTE_CACHE", str(Path.home() / "zhuge" / "quote_cache.json")))
QUOTE_CACHE_SEC = float(os.getenv("QUOTE_CACHE_SEC", "4"))
WANTED_TTL_SEC = 600                     # 10 分鐘冇程式要嘅代號就唔再查（例如轉倉後嘅舊合約）
RATE_LIMIT_MARK = "频率太高"
UNLOCK_MARK = "解锁"          # [R232] 富途：「没有解锁交易，请先解锁交易」（OpenD 重新登入後解鎖會冇咗）


def is_rate_limited(err) -> bool:
    return RATE_LIMIT_MARK in str(err)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _enc(q):
    return {**q, "update_time": q["update_time"].isoformat() if q.get("update_time") else None}


def _dec(q):
    ut = q.get("update_time")
    return {**q, "update_time": datetime.fromisoformat(ut) if ut else None}


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
        if self.env == TrdEnv.REAL:
            if cfg.trade_password:
                self._unlock()
            else:
                log.warning("真倉但 FUTU_TRADE_PASSWORD 未設：OpenD 冇人手解鎖就落唔到單")
        self.acc_id = cfg.acc_id or self._pick_account()
        log.info("Futu 已連接 env=%s acc_id=%s", cfg.trd_env, self.acc_id)

    def _unlock(self):
        _ok(*self.trade.unlock_trade(password=self.cfg.trade_password), "unlock_trade")
        log.info("已解鎖交易")

    def _place(self, **kw):
        """place_order；真倉遇到「未解鎖」（OpenD 重新登入咗）就重新解鎖再試一次。"""
        ret, data = self.trade.place_order(**kw)
        if (ret != RET_OK and UNLOCK_MARK in str(data) and self.env == TrdEnv.REAL
                and self.cfg.trade_password):
            log.warning("落單話未解鎖，重新解鎖再試：%s", data)
            self._unlock()
            ret, data = self.trade.place_order(**kw)
        return _ok(ret, data, "place_order")

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

    def _snapshots(self, codes) -> dict:
        """一個請求查多個代號（get_market_snapshot 一次最多 400 個）。"""
        df = _ok(*self.quote.get_market_snapshot(list(codes)), "get_market_snapshot")
        out = {}
        for _, r in df.iterrows():
            code = str(r["code"])
            upd = str(r.get("update_time", ""))
            try:
                # 富途報價時間係交易所當地時間（港期 HKT、美股美東）
                ut = datetime.strptime(upd[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=HKT if code.startswith("HK.") else ET)
            except ValueError:
                ut = None
            out[code] = {"last": float(r["last_price"]), "bid": float(r.get("bid_price") or 0),
                         "ask": float(r.get("ask_price") or 0), "update_time": ut,
                         "volume": float(r.get("volume") or 0)}
        return out

    def snapshot(self, code: str, fresh: bool = False) -> dict:
        """報價快照。fresh=False 用共用快取（[R226]）；落單前 fresh=True 直接查。快取出問題就自己查。"""
        if not fresh:
            try:
                return self._shared_snapshot(code)
            except BrokerError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("共用報價快取出錯，改為自己查")
        return self._snapshots([code])[code]

    def _shared_snapshot(self, code: str) -> dict:
        now = _time.time()
        data = _read_json(QUOTE_CACHE)
        q = (data.get("quotes") or {}).get(code)
        if q and now - float(data.get("ts") or 0) < QUOTE_CACHE_SEC:
            return _dec(q)
        QUOTE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(QUOTE_CACHE.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)              # 同一時間得一個程式去查，其他等佢寫好就用
            try:
                data = _read_json(QUOTE_CACHE)
                q = (data.get("quotes") or {}).get(code)
                now = _time.time()
                if q and now - float(data.get("ts") or 0) < QUOTE_CACHE_SEC:
                    return _dec(q)
                wanted = {c: t for c, t in (data.get("wanted") or {}).items() if now - float(t) < WANTED_TTL_SEC}
                wanted[code] = now
                try:
                    quotes = self._snapshots(sorted(wanted))
                except BrokerError as e:
                    if is_rate_limited(e):
                        raise
                    wanted = {code: now}                  # 其他代號有問題（例如舊合約）：只查自己，清走其他
                    quotes = self._snapshots([code])
                tmp = QUOTE_CACHE.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps({"ts": now, "wanted": wanted,
                                           "quotes": {c: _enc(v) for c, v in quotes.items()}}), encoding="utf-8")
                os.replace(tmp, QUOTE_CACHE)
                return quotes[code]
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

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
        只查詢，唔落單、唔解鎖；唔回傳戶口號碼。R212 起 account 帶淨值同購買力（私人 GCS，網頁唔顯示）。"""
        row = self._real_account()
        if row is None:
            return {"ok": False, "found": False, "note": f"搵唔到 {self.spec.market} 真實戶口"}
        acc_id = int(row["acc_id"])
        out = {"found": True, "acc_type": str(row.get("acc_type", "")), "qty": qty}
        ccy = "USD" if self.spec.currency == "USD" else "HKD"
        info = _ok(*self.trade.accinfo_query(trd_env=TrdEnv.REAL, acc_id=acc_id, refresh_cache=True,
                                             currency=ccy), "accinfo_query REAL").iloc[0]
        out["funded"] = _num(info.get("total_assets")) > 0
        out["account"] = self._acct_fields(info, ccy)       # [R212] 使用者 10-17：真實戶口淨值同購買力上載私人 GCS
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

    @staticmethod
    def _acct_fields(info, ccy):
        return {"currency": ccy, "equity": round(_num(info.get("total_assets")), 2),
                "power": round(_num(info.get("power")), 2),
                "max_power_short": round(_num(info.get("max_power_short")), 2),
                "cash": round(_num(info.get("cash")), 2),
                "maintenance_margin": round(_num(info.get("maintenance_margin")), 2)}

    def account_snapshot(self) -> dict:
        """[R212] 而家戶口（模擬或真實）嘅淨值同購買力，ETF 用美元、期貨用港幣。只上載私人 GCS。"""
        ccy = "USD" if self.spec.currency == "USD" else "HKD"
        info = _ok(*self.trade.accinfo_query(trd_env=self.env, acc_id=self.acc_id, refresh_cache=False,
                                             currency=ccy), "accinfo_query").iloc[0]
        return self._acct_fields(info, ccy)

    def futures_room(self, code: str, side: int, price: float) -> dict:
        """[R209] 期貨戶口緩衝（淨值 − 維持保證金，港幣）同每張初始保證金（做好／做淡），富途即時查，唔寫死。"""
        info = _ok(*self.trade.accinfo_query(trd_env=self.env, acc_id=self.acc_id, refresh_cache=True,
                                             currency="HKD"), "accinfo_query").iloc[0]
        ti = _ok(*self.trade.acctradinginfo_query(order_type=OrderType.NORMAL, code=code, price=price,
                                                  trd_env=self.env, acc_id=self.acc_id),
                 "acctradinginfo_query").iloc[0]
        return {"cushion": _num(info.get("total_assets")) - _num(info.get("maintenance_margin")),
                "im": _num(ti.get("long_required_im" if side > 0 else "short_required_im"))}

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

    # ---------- [R234] 伺服器端後備止蝕（GTC STOP 單，放喺富途伺服器；部機／OpenD 死咗都生效）----------
    # ---------- [R261] 交易所假期（富途交易日曆）----------
    def is_trading_day(self, market: str, day) -> bool:
        """富途 request_trading_days：港股／美股交易日（包半日市）。查唔到就當交易日（唔阻住交易），一日查一次。"""
        cache = self.__dict__.setdefault("_tdays", {})
        key = (market, day.isoformat())
        if key in cache:
            return cache[key]
        try:
            from futu import TradeDateMarket
            mk = TradeDateMarket.US if market == "US" else TradeDateMarket.HK
            start, end = (day - timedelta(days=10)).isoformat(), (day + timedelta(days=10)).isoformat()
            data = _ok(*self.quote.request_trading_days(market=mk, start=start, end=end), "request_trading_days")
            days = {str(x.get("time"))[:10] for x in data}
            for k in range(-10, 11):
                d = (day + timedelta(days=k)).isoformat()
                cache[(market, d)] = d in days
        except Exception as e:  # noqa: BLE001
            log.warning("查交易日曆失敗（當交易日）：%s", e)
            return True
        return cache[key]

    def stop_order(self, code: str, side: int, qty: int, trigger: float) -> str:
        """掛止損市價單（side：+1 買／-1 賣），長期有效；回傳 order_id。"""
        from futu import TimeInForce
        trigger = round(trigger, 4)
        df = self._place(price=trigger, qty=qty, code=code, trd_side=TrdSide.BUY if side > 0 else TrdSide.SELL,
                         order_type=OrderType.STOP, aux_price=trigger, time_in_force=TimeInForce.GTC,
                         trd_env=self.env, acc_id=self.acc_id, remark="zhuge-longfei-stop")
        oid = str(df.iloc[0]["order_id"])
        log.info("後備止蝕 %s %s x%d 觸發 %s id=%s", "買" if side > 0 else "賣", code, qty, trigger, oid)
        return oid

    def modify_stop(self, order_id: str, qty: int, trigger: float):
        trigger = round(trigger, 4)
        _ok(*self.trade.modify_order(ModifyOrderOp.NORMAL, order_id, qty, trigger, aux_price=trigger,
                                     trd_env=self.env, acc_id=self.acc_id), "modify_order")

    def cancel_order(self, order_id: str):
        """撤單，再查最終狀態；回傳 (成交均價, 成交數量)（撤之前已經觸發成交就唔係 0）。"""
        try:
            self.trade.modify_order(ModifyOrderOp.CANCEL, order_id, 0, 0, trd_env=self.env, acc_id=self.acc_id)
        except Exception:  # noqa: BLE001
            log.exception("撤單 %s 失敗", order_id)
        for _ in range(5):
            row = self._order_row(order_id)
            if row is not None and (row["order_status"] in FILLED or row["order_status"] in DEAD):
                return self._fill(row, None, 0)
            _time.sleep(1)
        raise BrokerError(f"撤單 {order_id} 後查唔到最終狀態")

    def market_order(self, code: str, side: int, qty: int, slippage: float, timeout=15):
        """以可成交限價單模擬市價：買用 ask+滑點，賣用 bid-滑點。
        回傳 (成交均價, 成交數量)；完全冇成交回傳 (None, 0)。超時會取消，取消後再查：部分成交同取消前啱啱成交都計返。"""
        snap = self.snapshot(code, fresh=True)           # 落單要最新價，唔用快取
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
        df = self._place(price=price, qty=qty, code=code, trd_side=trd_side, order_type=OrderType.NORMAL,
                         trd_env=self.env, acc_id=self.acc_id, remark="zhuge-longfei", **extra)
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
