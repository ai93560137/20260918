"""交易核心：風控循環（每幾秒）+ AI 決策（每 5 分鐘）。
券商、AI、時鐘都係注入，方便用假物件測試。"""
import json
import logging
from datetime import datetime, timezone

from rules import (session_status, trading_day_key, pick_front_month, stop_hit, target_hit,
                   validate_decision)

log = logging.getLogger("trader")


def _atr(bars, n=14):
    if len(bars) < 2:
        return None
    trs = []
    for prev, b in zip(bars[:-1], bars[1:]):
        trs.append(max(b["h"] - b["l"], abs(b["h"] - prev["c"]), abs(b["l"] - prev["c"])))
    trs = trs[-n:]
    return round(sum(trs) / len(trs), 1)


class Trader:
    def __init__(self, cfg, broker, brain, clock):
        self.cfg = cfg
        self.broker = broker
        self.brain = brain
        self.clock = clock
        self.cfg.log_dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()
        self.errors = 0
        self._contract_cache = (None, None)  # (day_key, code)
        self._daily_cache = (None, None)

    # ---------- 狀態同日誌 ----------
    def _load_state(self):
        try:
            return json.loads(self.cfg.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self):
        tmp = self.cfg.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.cfg.state_file)

    def _log(self, name, rec):
        rec = {"ts": self.clock().isoformat(timespec="seconds"), **rec}
        with open(self.cfg.log_dir / f"{name}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- 主循環一步 ----------
    def tick(self):
        now = self.clock()
        try:
            self._tick(now)
            self.errors = 0
        except Exception as e:  # noqa: BLE001
            self.errors += 1
            log.exception("tick 出錯 (%d)", self.errors)
            self._log("events", {"type": "ERROR", "msg": str(e), "count": self.errors})
            if self.errors >= self.cfg.max_consecutive_errors and not self.state.get("halted"):
                self._halt(f"連續 {self.errors} 次出錯")
                try:
                    self._flatten_all("連續出錯")
                except Exception:  # noqa: BLE001
                    log.exception("出錯後平倉失敗")
        finally:
            self._save_state()
            self._write_heartbeat()

    def _write_heartbeat(self):
        """watchdog 用：真實 UTC 時間（唔用注入嘅 clock）、有冇倉、連續出錯次數。"""
        pos = self.state.get("pos") or {}
        rec = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "trd_env": self.cfg.trd_env, "code": pos.get("code"), "qty": pos.get("qty", 0),
               "side": pos.get("side"), "stop": pos.get("stop"), "errors": self.errors,
               "halted": bool(self.state.get("halted"))}
        try:
            tmp = self.cfg.heartbeat_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cfg.heartbeat_file)
        except OSError:
            log.exception("寫心跳失敗")

    def _tick(self, now: datetime):
        st = self.state
        cfg = self.cfg

        # 1) 交易日重置
        day = trading_day_key(now)
        if st.get("day") != day:
            eq = self.broker.equity()
            st.update({"day": day, "day_start_equity": eq, "trades_today": 0,
                       "today_trades": [], "halted": False, "halt_reason": None})
            self._log("events", {"type": "NEW_DAY", "day": day, "equity": eq})

        # 2) 即月合約
        contract = self._front_month(now)
        if not contract:
            raise RuntimeError("搵唔到即月合約")

        # 3) 對賬：以富途實際倉位為準
        positions = self.broker.positions(cfg.product)
        for code, (qty, _) in positions.items():
            if code != contract:
                self._close(code, qty, f"轉倉：平舊合約 {code}")
        qty, cost = positions.get(contract, (0, None))
        self._reconcile(contract, qty, cost, now)
        if abs(qty) > cfg.max_qty:
            excess = abs(qty) - cfg.max_qty
            side = 1 if qty > 0 else -1
            self._close(contract, side * excess, f"超出上限 {cfg.max_qty} 張，減倉")
            qty = side * cfg.max_qty

        snap = self.broker.snapshot(contract)
        last = snap["last"]
        session, mins_left = session_status(now)
        stale = (snap["update_time"] is None or
                 (now - snap["update_time"]).total_seconds() > cfg.stale_quote_sec)

        # 4) 每日虧損上限
        eq = self.broker.equity()
        day_pnl = eq - st["day_start_equity"]
        st["last_equity"], st["day_pnl"] = eq, day_pnl
        if day_pnl <= -cfg.daily_loss_limit and not st.get("halted"):
            self._halt(f"今日虧損 HK${-day_pnl:,.0f} 到達上限")
        if st.get("halted") and qty != 0:
            self._close(contract, qty, "停機平倉：" + (st.get("halt_reason") or ""), last)
            return

        # 5) 手動停機開關
        if cfg.stop_file.exists():
            if not st.get("halted"):
                self._halt("STOP 檔案存在")
            if qty != 0:
                self._close(contract, qty, "STOP 檔案：平倉", last)
            return

        # 6) 夜市收市前強制平倉（避開隔夜跳空）
        if (qty != 0 and session == "NIGHT" and cfg.flatten_before_night_close
                and mins_left is not None and mins_left <= cfg.flatten_before_night_close_min):
            self._close(contract, qty, "夜市收市前平倉", last)
            return

        # 7) 止蝕 / 止賺（喺交易時段、報價新鮮先檢查）
        meta = st.get("pos")
        if qty != 0 and meta and session and not stale:
            side = 1 if qty > 0 else -1
            if stop_hit(side, last, meta.get("stop")):
                self._close(contract, qty, f"止蝕 {meta['stop']}", last)
                return
            if target_hit(side, last, meta.get("target")):
                self._close(contract, qty, f"止賺 {meta['target']}", last)
                return

        # 8) AI 決策（每 N 分鐘，K 線收咗先做）
        if session and not stale and not st.get("halted") and self._decision_due(now):
            self._decide(now, contract, qty, snap, session, mins_left)

    # ---------- 決策 ----------
    def _decision_due(self, now):
        n = self.cfg.decision_interval_min
        if now.minute % n != 0 or now.second < 3:
            return False
        key = now.strftime("%Y-%m-%d %H:%M")
        if self.state.get("last_decision_bar") == key:
            return False
        self.state["last_decision_bar"] = key
        return True

    def _can_open(self, mins_left):
        st, cfg = self.state, self.cfg
        return (not st.get("halted") and not cfg.pause_file.exists()
                and mins_left is not None and mins_left > cfg.no_entry_before_close_min)

    def _decide(self, now, contract, qty, snap, session, mins_left):
        st, cfg = self.state, self.cfg
        last = snap["last"]
        remaining = cfg.daily_loss_limit + st.get("day_pnl", 0)
        can_open = self._can_open(mins_left)
        ctx = self._context(now, contract, qty, snap, session, mins_left, remaining, can_open)
        d = self.brain.decide(ctx)
        meta = st.get("pos") or {}
        action, stop, target, rejected = validate_decision(
            d, position=qty, entry=meta.get("entry"), last=last, cfg=cfg,
            remaining_loss=remaining, can_open=can_open, trades_today=st.get("trades_today", 0))
        rec = {"bar": st["last_decision_bar"], "contract": contract, "last": last, "pos": qty,
               "ai_action": d.get("action"), "ai_stop": d.get("stop_price"),
               "ai_target": d.get("target_price"), "confidence": d.get("confidence"),
               "reason": d.get("reason"), "final": action, "stop": stop, "target": target,
               "rejected": rejected, "usage": d.get("_usage"), "day_pnl": st.get("day_pnl")}
        self._log("decisions", rec)
        hist = st.setdefault("recent_decisions", [])
        hist.append({"t": now.strftime("%H:%M"), "action": action, "ai": d.get("action"),
                     "reason": (d.get("reason") or "")[:120], "rejected": rejected})
        st["recent_decisions"] = hist[-8:]
        log.info("AI %s → %s %s", d.get("action"), action, rejected or d.get("reason", ""))

        if action in ("OPEN_LONG", "OPEN_SHORT"):
            side = 1 if action == "OPEN_LONG" else -1
            px = self.broker.market_order(contract, side, cfg.max_qty, cfg.slippage_points)
            if px is None:
                self._log("events", {"type": "ORDER_FAILED", "action": action})
                return
            # 以實際成交價重新校正止蝕距離
            dist = abs(last - stop)
            stop_adj = round(px - side * dist)
            tgt_adj = round(px + side * abs(target - last)) if target else None
            st["pos"] = {"code": contract, "side": side, "qty": cfg.max_qty, "entry": px,
                         "stop": stop_adj, "target": tgt_adj, "opened_at": now.isoformat(),
                         "reason": d.get("reason")}
            st["trades_today"] = st.get("trades_today", 0) + 1
            self._log("trades", {"type": "OPEN", "code": contract, "side": side,
                                 "qty": cfg.max_qty, "price": px, "stop": stop_adj,
                                 "target": tgt_adj, "reason": d.get("reason")})
        elif action == "CLOSE":
            self._close(contract, qty, "AI：" + (rejected or d.get("reason") or ""), last)
        elif action == "UPDATE_STOP" and st.get("pos"):
            st["pos"]["stop"] = stop
            if target:
                st["pos"]["target"] = target
            self._log("trades", {"type": "UPDATE_STOP", "code": contract, "stop": stop,
                                 "target": st["pos"].get("target"), "reason": d.get("reason")})

    def _context(self, now, contract, qty, snap, session, mins_left, remaining, can_open):
        cfg, st = self.cfg, self.state
        bars5 = self.broker.klines(contract, "5m", days_back=4, max_count=60)
        day_key = st.get("day")
        if self._daily_cache[0] != day_key:
            try:
                daily = self.broker.klines(f"HK.{cfg.product}main", "1d", days_back=45, max_count=20)
            except Exception:  # noqa: BLE001
                daily = self.broker.klines(contract, "1d", days_back=45, max_count=20)
            self._daily_cache = (day_key, daily)
        daily = self._daily_cache[1]
        meta = st.get("pos") or {}
        pos = None
        if qty != 0:
            side = 1 if qty > 0 else -1
            entry = meta.get("entry")
            pos = {"side": "LONG" if side > 0 else "SHORT", "qty": abs(qty), "entry": entry,
                   "stop": meta.get("stop"), "target": meta.get("target"),
                   "unrealized_points": round((snap["last"] - entry) * side, 1) if entry else None,
                   "opened_at": meta.get("opened_at")}
        return {
            "now_hkt": now.strftime("%Y-%m-%d %H:%M"), "weekday": now.strftime("%a"),
            "session": session, "minutes_to_session_close": round(mins_left or 0),
            "contract": contract,
            "quote": {"last": snap["last"], "bid": snap["bid"], "ask": snap["ask"]},
            "atr14_5m": _atr(bars5), "bars_5m": bars5, "bars_daily": daily,
            "position": pos,
            "risk": {"day_pnl_hkd": round(st.get("day_pnl", 0)),
                     "remaining_loss_budget_hkd": round(remaining),
                     "point_value_hkd": cfg.point_value, "max_qty": cfg.max_qty,
                     "stop_points_min": cfg.min_stop_points, "stop_points_max": cfg.max_stop_points,
                     "trades_today": st.get("trades_today", 0),
                     "max_trades_per_day": cfg.max_trades_per_day,
                     "new_entries_allowed": can_open},
            "today_trades": st.get("today_trades", [])[-10:],
            "recent_decisions": st.get("recent_decisions", []),
        }

    # ---------- 執行 ----------
    def _close(self, code, qty, reason, ref_price=None):
        if qty == 0:
            return None
        side = -1 if qty > 0 else 1
        px = self.broker.market_order(code, side, abs(qty), self.cfg.slippage_points)
        meta = self.state.get("pos") or {}
        if px is None:
            self._log("events", {"type": "CLOSE_FAILED", "code": code, "reason": reason})
            return None
        self._record_exit(code, qty, px, reason, meta)
        return px

    def _record_exit(self, code, qty, px, reason, meta):
        st = self.state
        entry = meta.get("entry") if meta.get("code") == code else None
        side = 1 if qty > 0 else -1
        pts = round((px - entry) * side, 1) if entry is not None else None
        hkd = round(pts * abs(qty) * self.cfg.point_value) if pts is not None else None
        rec = {"type": "CLOSE", "code": code, "side": side, "qty": abs(qty), "entry": entry,
               "price": px, "points": pts, "pnl_hkd_gross": hkd, "reason": reason,
               "opened_at": meta.get("opened_at")}
        self._log("trades", rec)
        st.setdefault("today_trades", []).append(
            {"side": "LONG" if side > 0 else "SHORT", "entry": entry, "exit": px,
             "points": pts, "reason": reason[:60]})
        if meta.get("code") == code:
            st["pos"] = None
        log.info("平倉 %s %s @%s 點數=%s (%s)", code, qty, px, pts, reason)

    def _reconcile(self, contract, qty, cost, now):
        """富途倉位同自己記錄唔一致時，以富途為準。"""
        st, cfg = self.state, self.cfg
        meta = st.get("pos")
        if qty == 0 and meta:
            snap = self.broker.snapshot(meta["code"])
            self._record_exit(meta["code"], meta["side"] * meta.get("qty", 1), snap["last"],
                              "倉位喺外部被平（估算價）", meta)
            st["pos"] = None
        elif qty != 0 and (not meta or meta.get("code") != contract
                           or meta.get("side") != (1 if qty > 0 else -1)):
            side = 1 if qty > 0 else -1
            entry = cost or self.broker.snapshot(contract)["last"]
            st["pos"] = {"code": contract, "side": side, "qty": abs(qty), "entry": entry,
                         "stop": round(entry - side * cfg.max_stop_points), "target": None,
                         "opened_at": now.isoformat(), "reason": "接手現有倉位，設緊急止蝕"}
            self._log("events", {"type": "ADOPT_POSITION", "code": contract, "qty": qty,
                                 "entry": entry, "stop": st["pos"]["stop"]})

    def _flatten_all(self, reason):
        for code, (qty, _) in self.broker.positions(self.cfg.product).items():
            self._close(code, qty, reason)

    def _halt(self, reason):
        self.state["halted"] = True
        self.state["halt_reason"] = reason
        self._log("events", {"type": "HALT", "reason": reason})
        log.warning("停機：%s", reason)

    def _front_month(self, now):
        day = self.state.get("day")
        if self._contract_cache[0] == day and self._contract_cache[1]:
            return self._contract_cache[1]
        code = pick_front_month(self.broker.list_contracts(self.cfg.product),
                                self.cfg.product, now.date())
        self._contract_cache = (day, code)
        if code and self.state.get("contract") != code:
            self._log("events", {"type": "CONTRACT", "code": code})
            self.state["contract"] = code
        return code

    def snapshot_equity(self):
        st = self.state
        self._log("equity", {"equity": st.get("last_equity"), "day": st.get("day"),
                             "day_pnl": st.get("day_pnl"), "pos": (st.get("pos") or {}).get("side", 0)})
