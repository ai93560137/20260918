"""交易核心：風控循環（每幾秒）+ AI 決策（每 5 分鐘）。
券商、AI、時鐘都係注入，方便用假物件測試。"""
import fcntl
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from markets import FX_TO_HKD, SPECS, fee_hkd, order_qty, session_day, spec_for
from rules import (round_tick, session_status, trading_day_key, pick_front_month, stop_hit, target_hit,
                   validate_decision)

log = logging.getLogger("trader")


def is_rate_limited(err) -> bool:
    """[R226] 富途查詢次數超額（例如報價快照每 30 秒最多 60 次）。同 broker.is_rate_limited 一樣；唔 import broker 免得測試要 futu。"""
    return "频率太高" in str(err)


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
            if is_rate_limited(e):
                # [R226] 富途查詢次數超額：等下一輪再試，唔計入連續出錯（唔好因為限速停機平倉）
                log.warning("富途查詢次數超額，下一輪再試：%s", e)
                self._log("events", {"type": "RATE_LIMIT", "msg": str(e)[:200]})
                return
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
               "foreign_qty": self.state.get("foreign_qty", 0),
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
        day = trading_day_key(now, cfg.market, cfg.kind)
        if st.get("day") != day:
            eq = self.broker.equity()
            st.update({"day": day, "day_start_equity": eq, "trades_today": 0,
                       "ai_skipped_today": 0, "ai_gated_today": 0,
                       "today_trades": [], "halted": False, "halt_reason": None})
            self._log("events", {"type": "NEW_DAY", "day": day, "equity": eq})

        # 2) 即月合約
        contract = self._front_month(now)
        if not contract:
            raise RuntimeError("搵唔到即月合約")

        # 3) 對賬：同一富途戶口有其他陣／人手倉（例如使用者人手大期、或者其他陣），而且同合約係淨額顯示。
        #    所以只管自己落過嘅倉（state["pos"]），落單手數只用自己嘅手數；唔屬於自己嘅倉一律唔掂。
        positions = self.broker.positions(cfg.product)
        meta = st.get("pos")
        if meta and meta["code"] != contract:          # 自己嘅倉喺舊合約 → 轉倉只平自己嗰份
            if positions.get(meta["code"], (0, None))[0] != 0:
                self._close(meta["code"], meta["side"] * meta["qty"], f"轉倉：平舊合約 {meta['code']}")
            else:
                snap_old = self.broker.snapshot(meta["code"])
                self._record_exit(meta["code"], meta["side"] * meta["qty"], snap_old["last"],
                                  "倉位喺外部被平（估算價）", meta)
        broker_qty = positions.get(contract, (0, None))[0]
        self._reconcile(contract, broker_qty, positions, now)
        qty = self._own_qty(contract)

        snap = self.broker.snapshot(contract)
        last = snap["last"]
        session, mins_left = session_status(now, cfg.market, cfg.kind)
        if session and not self._is_trading_day(now):   # [R261] 交易所假期：當休市，唔問 Claude、唔開倉
            session, mins_left = None, None
        stale = (snap["update_time"] is None or
                 (now - snap["update_time"]).total_seconds() > cfg.stale_quote_sec)

        self._real_preflight(now, contract, last)

        # 4) 每日虧損上限：只計自己嘅盈虧（已實現＋浮動，扣估算佣金），唔用戶口淨值，
        #    否則其他陣蝕錢都會令龍飛陣停機
        st["last_equity"] = self.broker.equity()
        day_pnl = self._own_day_pnl(contract, last)
        st["day_pnl"] = day_pnl
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
            if meta.get("entry") is not None:            # 覆盤用：持倉期間最多浮賺（MFE）／浮蝕（MAE），單位點
                exc = (last - meta["entry"]) * side
                meta["mfe"] = round(max(meta.get("mfe", 0.0), exc), 4)
                meta["mae"] = round(min(meta.get("mae", 0.0), exc), 4)
            self._ensure_server_stop(contract, qty)
            if stop_hit(side, last, meta.get("stop")):
                self._close(contract, qty, f"止蝕 {meta['stop']}", last)
                return
            if target_hit(side, last, meta.get("target")):
                self._close(contract, qty, f"止賺 {meta['target']}", last)
                return

        # 8) AI 決策（每 N 分鐘，K 線收咗先做）
        if session and not stale and not st.get("halted") and self._decision_due(now):
            # 使用者 10-17：冇倉又唔可以開新倉（暫停、時段、組合限制、收市前）就唔問 Claude，慳 API 費用；
            # 有倉照問（管理止蝕同平倉）。止蝕／止賺本身由程式每幾秒檢查，唔靠 Claude
            if qty == 0 and not (self._can_open(mins_left, session) and not self._portfolio_block()):
                st["ai_skipped_today"] = st.get("ai_skipped_today", 0) + 1
            else:
                self._decide(now, contract, qty, snap, session, mins_left)

    # ---------- 決策 ----------
    def _is_trading_day(self, now):
        fn = getattr(self.broker, "is_trading_day", None)
        if not fn:
            return True
        day = session_day(now, self.cfg.market)
        ok = fn(self.cfg.market, day)
        if not ok and self.state.get("holiday") != day.isoformat():
            self.state["holiday"] = day.isoformat()
            self._log("events", {"type": "HOLIDAY", "day": day.isoformat(), "market": self.cfg.market,
                                 "note": "交易所假期：唔問 Claude、唔開倉"})
        return ok

    def _decision_due(self, now):
        n = self.cfg.decision_interval_min
        if now.minute % n != 0 or now.second < 3:
            return False
        key = now.strftime("%Y-%m-%d %H:%M")
        if self.state.get("last_decision_bar") == key:
            return False
        self.state["last_decision_bar"] = key
        return True

    def _can_open(self, mins_left, session=None):
        st, cfg = self.state, self.cfg
        sp = spec_for(cfg.product)
        if sp.kind == "stock" and not sp.ext_hours:     # 使用者 10-17：差價太闊嘅 ETF 盤前盤後唔開新倉
            if session != "RTH":
                return False
            mins_left = (mins_left or 0) - 240            # 收市計 16:00，唔係 20:00
        return (not st.get("halted") and not cfg.pause_file.exists() and not st.get("foreign_qty")
                and mins_left is not None and mins_left > cfg.no_entry_before_close_min)

    def _decide(self, now, contract, qty, snap, session, mins_left):
        st, cfg = self.state, self.cfg
        last = snap["last"]
        remaining = cfg.daily_loss_limit + st.get("day_pnl", 0)
        can_open = self._can_open(mins_left, session) and not self._portfolio_block()
        ctx = self._context(now, contract, qty, snap, session, mins_left, remaining, can_open)
        gate = None
        if qty == 0 and can_open and cfg.gate_model:
            # [R218] 方案 A：冇倉先用 Haiku 篩；佢話唔使睇就唔問決策模型（有倉一律直接問）
            gate = self.brain.screen(ctx)
            if not gate.get("look"):
                st["ai_gated_today"] = st.get("ai_gated_today", 0) + 1
                self._log("decisions", {"bar": st["last_decision_bar"], "contract": contract, "last": last,
                                        "pos": qty, "ai_action": None, "final": "HOLD", "gate": "SKIP",
                                        "reason": gate.get("reason"), "rejected": None, "stop": None,
                                        "target": None, "usage": None, "gate_usage": gate.get("_usage"),
                                        "day_pnl": st.get("day_pnl"), "session": session})
                return
        d = self.brain.decide(ctx)
        meta = st.get("pos") or {}
        n_open = order_qty(spec_for(cfg.product), last, cfg.max_qty)   # 期貨張數／ETF 股數
        if cfg.real_size_frac and last:          # [R249] 真倉美股：每單 = 比例 × 實時權益
            eq = st.get("last_equity") or self.broker.equity()
            n_open = max(int(cfg.real_size_frac * eq / (last * FX_TO_HKD[cfg.currency])), 0)
        action, stop, target, rejected = validate_decision(
            d, position=qty, entry=meta.get("entry"), last=last, cfg=cfg,
            remaining_loss=remaining, can_open=can_open, trades_today=st.get("trades_today", 0), qty=n_open,
            current_stop=meta.get("stop"))
        rec = {"bar": st["last_decision_bar"], "contract": contract, "last": last, "pos": qty,
               "ai_action": d.get("action"), "ai_stop": d.get("stop_price"),
               "ai_target": d.get("target_price"), "confidence": d.get("confidence"),
               "reason": d.get("reason"), "final": action, "stop": stop, "target": target,
               "rejected": rejected, "usage": d.get("_usage"), "day_pnl": st.get("day_pnl"),
               "lessons": d.get("_lessons"), "session": session,
               "gate": "LOOK" if gate else None, "gate_usage": (gate or {}).get("_usage"),
               "gate_reason": (gate or {}).get("reason")}
        self._log("decisions", rec)
        hist = st.setdefault("recent_decisions", [])
        hist.append({"t": now.strftime("%H:%M"), "action": action, "ai": d.get("action"),
                     "reason": (d.get("reason") or "")[:120], "rejected": rejected})
        st["recent_decisions"] = hist[-8:]
        log.info("AI %s → %s %s", d.get("action"), action, rejected or d.get("reason", ""))

        if action in ("OPEN_LONG", "OPEN_SHORT"):
            with self._portfolio_lock():          # [R216] 幾隻同時出訊號：逐隻排隊，睇完其他程式先開
                self._open(now, contract, action, d, last, stop, target, n_open, session)
        elif action == "CLOSE":
            self._close(contract, qty, "AI：" + (rejected or d.get("reason") or ""), last)
        elif action == "UPDATE_STOP" and st.get("pos"):
            st["pos"]["stop"] = stop
            if target:
                st["pos"]["target"] = target
            self._move_server_stop()
            self._log("trades", {"type": "UPDATE_STOP", "code": contract, "stop": stop,
                                 "target": st["pos"].get("target"), "reason": d.get("reason")})

    def _open(self, now, contract, action, d, last, stop, target, n_open, session):
        st, cfg = self.state, self.cfg
        side = 1 if action == "OPEN_LONG" else -1
        block = self._portfolio_block(side)
        if block:
            self._log("events", {"type": "OPEN_SKIPPED", "action": action, "reason": block})
            log.info("唔開：%s", block)
            return
        n_open = self._cap_open_qty(contract, side, last, n_open)
        if not n_open:
            return
        px, filled = self.broker.market_order(contract, side, n_open, cfg.slippage_points)
        if not filled:
            self._log("events", {"type": "ORDER_FAILED", "action": action})
            return
        if filled < n_open:
            self._log("events", {"type": "PARTIAL_FILL", "action": action, "wanted": n_open, "filled": filled})
            n_open = filled
        # 以實際成交價重新校正止蝕距離
        dist = abs(last - stop)
        stop_adj = round_tick(px - side * dist, cfg.tick)
        tgt_adj = round_tick(px + side * abs(target - last), cfg.tick) if target else None
        st["pos"] = {"code": contract, "side": side, "qty": n_open, "entry": px,
                     "stop": stop_adj, "target": tgt_adj, "opened_at": now.isoformat(),
                     "reason": d.get("reason"), "risk_pts": round(dist, 4), "mfe": 0.0, "mae": 0.0,
                     "lessons": d.get("_lessons"), "confidence": d.get("confidence"), "session": session,
                     "model": (d.get("_usage") or {}).get("model")}       # [R218] 覆盤比較唔同決策模型
        st["trades_today"] = st.get("trades_today", 0) + 1
        self._log("trades", {"type": "OPEN", "code": contract, "side": side,
                             "qty": n_open, "price": px, "stop": stop_adj,
                             "target": tgt_adj, "reason": d.get("reason"), "risk_pts": round(dist, 4),
                             "confidence": d.get("confidence"), "lessons": d.get("_lessons"),
                             "session": session, "model": st["pos"]["model"]})
        self._ensure_server_stop(contract, side * n_open)
        self._save_state()                        # 即刻寫，等其他程式睇到呢個倉

    # ---------- [R216] 組合層面（使用者 10-17：A 美股大盤組同方向最多 2 隻；C 全部 ETF 合計日蝕 HK$200,000）----------
    def _peer_states(self):
        """同一部 VM 其他 ETF 程式嘅狀態（模擬對模擬、真倉對真倉）。"""
        base = self.cfg.state_file.parent.parent
        prefix = "ai_trader_real_" if self.cfg.instance_real else "ai_trader_"
        out = {}
        for p, sp in SPECS.items():
            if sp.kind != "stock" or p == self.cfg.product:
                continue
            try:
                out[p] = json.loads((base / f"{prefix}{p}" / "state.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        return out

    def _portfolio_block(self, side=None):
        """唔准開新倉嘅原因（冇就 None）。只管 ETF；唔會平已有嘅倉。"""
        cfg, st = self.cfg, self.state
        if cfg.kind != "stock":
            return None
        peers = self._peer_states()
        if cfg.etf_total_daily_loss:
            total = (st.get("day_pnl") or 0) + sum(float(s.get("day_pnl") or 0) for s in peers.values()
                                                  if s.get("day") == st.get("day"))
            if total <= -cfg.etf_total_daily_loss:
                return f"全部 ETF／個股今日合計虧損 HK${-total:,.0f}，到咗合計上限 HK${cfg.etf_total_daily_loss:,.0f}"
        for name, group in (("美股大盤組", cfg.etf_group_us_eq), ("科技股組", cfg.etf_group_tech)):   # [R225]
            if side and cfg.group_max_same_dir and cfg.product in group:
                same = sorted(p for p, s in peers.items()
                              if p in group and (s.get("pos") or {}).get("side") == side)
                if len(same) >= cfg.group_max_same_dir:
                    return f"{name}已有 {len(same)} 隻同方向持倉（{'、'.join(same)}）"
        return None

    @contextmanager
    def _portfolio_lock(self):
        """ETF 程式開倉時互相排隊（同一時間只有一隻喺度檢查＋落單），避免同時開爆上限。"""
        if self.cfg.kind != "stock":
            yield
            return
        path = self.cfg.state_file.parent.parent / ("longfei_real_open.lock" if self.cfg.instance_real
                                                    else "longfei_open.lock")
        try:
            f = open(path, "a")
        except OSError:
            yield
            return
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()

    def _context(self, now, contract, qty, snap, session, mins_left, remaining, can_open):
        cfg, st = self.cfg, self.state
        bars5 = self.broker.klines(contract, "5m", days_back=4, max_count=60)
        day_key = st.get("day")
        if self._daily_cache[0] != day_key:
            try:
                daily = self.broker.klines(contract if cfg.kind == "stock" else f"{cfg.market}.{cfg.product}main",
                                           "1d", days_back=45, max_count=20)
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
            "product": cfg.product, "market": cfg.market,
            "now_exchange": now.astimezone(spec_for(cfg.product).tz).strftime("%Y-%m-%d %H:%M %a"),
            "session": session, "minutes_to_session_close": round(mins_left or 0),
            "contract": contract,
            "quote": {"last": snap["last"], "bid": snap["bid"], "ask": snap["ask"]},
            "atr14_5m": _atr(bars5), "bars_5m": bars5, "bars_daily": daily,
            "position": pos,
            "risk": {"day_pnl_hkd": round(st.get("day_pnl", 0)),
                     "remaining_loss_budget_hkd": round(remaining),
                     "point_value_hkd": cfg.point_value, "currency": cfg.currency, "tick": cfg.tick,
                     "order_qty": order_qty(spec_for(cfg.product), snap["last"], cfg.max_qty),
                     "kind": cfg.kind,
                     "stop_points_min": cfg.min_stop_points or None,   # None = 唔限
                     "stop_points_max": cfg.max_stop_points or None,
                     "trades_today": st.get("trades_today", 0),
                     "max_trades_per_day": cfg.max_trades_per_day or None,
                     "new_entries_allowed": can_open,
                     # [R216] 組合限制：寫住唔准開邊個方向（例如美股大盤組同方向已有 2 隻）
                     "portfolio_long_blocked": self._portfolio_block(1),
                     "portfolio_short_blocked": self._portfolio_block(-1)},
            "today_trades": st.get("today_trades", [])[-10:],
            "recent_decisions": st.get("recent_decisions", []),
        }

    # ---------- 執行 ----------
    def _real_preflight(self, now, contract, last):
        """每 REAL_PREFLIGHT_MIN 分鐘唯讀查一次真實戶口準備好未（模擬盤都查，等入金後即刻知）。結果上載 GCS。"""
        cfg, st = self.cfg, self.state
        fn = getattr(self.broker, "real_preflight", None)
        if not fn or cfg.real_preflight_min <= 0 or not last:
            return
        prev = st.get("real_preflight") or {}
        try:
            if prev.get("ts") and (now - datetime.fromisoformat(prev["ts"])).total_seconds() < cfg.real_preflight_min * 60:
                return
        except (TypeError, ValueError):
            pass
        try:
            # [R240] 用盡槓桿：股數由富途可買數量決定，準備檢查只問「買唔買到／沽唔沽到 1 股」
            qty = 1 if (cfg.real_size_max or cfg.real_size_frac) else order_qty(spec_for(cfg.product), last, cfg.max_qty)
            res = fn(contract, qty, last)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": f"{e.__class__.__name__}: {str(e)[:120]}"}
        res["ts"] = now.isoformat(timespec="seconds")
        if isinstance(res.get("account"), dict):             # [R212] 真實戶口淨值同購買力另外存
            st["real_account"] = {**res.pop("account"), "ts": res["ts"], "source": "preflight"}
        if bool(res.get("ok")) != bool(prev.get("ok")) or not prev:
            self._log("events", {"type": "REAL_PREFLIGHT", **res})
            log.info("真倉準備檢查：%s", res)
        st["real_preflight"] = res

    def _futures_room_ok(self, contract, side, price, n_open):
        """[R209] 真倉期貨：開倉後緩衝 ≥ Ⓑ 線（夜盤 ×1.5）＋ 日蝕上限先開，唔夠就唔開（記 OPEN_SKIPPED）。"""
        cfg = self.cfg
        if cfg.trd_env != "REAL":
            return n_open
        try:
            r = self.broker.futures_room(contract, side, price)
        except Exception as e:  # noqa: BLE001
            self._log("events", {"type": "OPEN_SKIPPED", "reason": f"查唔到期貨緩衝：{e.__class__.__name__}"})
            return 0
        night = session_status(self.clock(), cfg.market, cfg.kind)[0] == "NIGHT"
        need = cfg.fut_ladder_b_day * (cfg.fut_ladder_night_mult if night else 1) + cfg.daily_loss_limit
        after = r["cushion"] - r["im"] * n_open
        if r["im"] > 0 and after >= need:
            return n_open
        self._log("events", {"type": "OPEN_SKIPPED", "reason": "期貨戶口緩衝唔夠" if r["im"] > 0 else "查唔到每張保證金",
                             "cushion_after": round(after), "need": round(need), "night": night})
        log.warning("期貨緩衝唔夠，唔開：開倉後 %.0f < 要求 %.0f", after, need)
        return 0

    def _cap_open_qty(self, contract, side, price, n_open):
        """開倉前問富途最多可以開幾多（購買力／可沽空數量）。唔夠就減細；一股都唔得就唔開。
        查唔到：REAL 唔開（寧願錯過），SIMULATE 照開。期貨只喺 REAL 查戶口緩衝（期貨戶口同其他陣共用按金）。"""
        if self.cfg.kind != "stock":
            return self._futures_room_ok(contract, side, price, n_open)
        try:
            cap = self.broker.max_open_qty(contract, side, price)
        except Exception as e:  # noqa: BLE001
            if self.cfg.trd_env == "REAL":
                self._log("events", {"type": "OPEN_SKIPPED", "reason": f"查唔到可開數量：{e.__class__.__name__}"})
                return 0
            log.warning("查唔到可開數量（模擬盤照開）：%s", e)
            return n_open
        if self.cfg.real_size_max and not self.cfg.real_size_frac:   # [R235] 用盡槓桿：可開數量平均分畀未有倉嘅真倉美股
            peers = self._peer_states()
            slots = 1 + sum(1 for p in self.cfg.real_products
                            if p != self.cfg.product and p in SPECS and SPECS[p].kind == "stock"
                            and not (peers.get(p) or {}).get("pos"))
            n_max = cap // slots
            self._log("events", {"type": "OPEN_SIZE_MAX", "cap": cap, "slots": slots, "qty": n_max})
            if n_max <= 0:
                self._log("events", {"type": "OPEN_SKIPPED", "reason": "購買力唔夠一股", "cap": cap})
            return max(n_max, 0)
        if cap >= n_open:
            return n_open
        self._log("events", {"type": "OPEN_CAPPED" if cap > 0 else "OPEN_SKIPPED", "wanted": n_open, "cap": cap,
                             "reason": "購買力唔夠" if side > 0 else "借唔到貨／沽空額度唔夠"})
        return max(cap, 0)

    def _close(self, code, qty, reason, ref_price=None):
        if qty == 0:
            return None
        meta = self.state.get("pos") or {}
        if meta.get("code") == code and meta.get("server_stop_id"):
            try:
                spx, sfilled = self._cancel_server_stop(meta)
            except Exception as e:  # noqa: BLE001
                self._log("events", {"type": "CLOSE_FAILED", "code": code, "reason": f"撤後備止蝕失敗：{e}"})
                return None                      # 唔知後備止蝕有冇成交就唔落平倉單，免得反手；下一輪再試
            if sfilled:                          # 撤之前已經觸發：伺服器已經平咗（部分）
                part = min(sfilled, abs(qty)) * (1 if qty > 0 else -1)
                self._record_exit(code, part, spx, "後備止蝕（富途伺服器）", meta)
                if abs(part) >= abs(qty):
                    return spx
                qty -= part
                meta = {**meta, "qty": abs(qty)}
                self.state["pos"] = meta
        side = -1 if qty > 0 else 1
        px, filled = self.broker.market_order(code, side, abs(qty), self.cfg.slippage_points)
        if not filled:
            self._log("events", {"type": "CLOSE_FAILED", "code": code, "reason": reason})
            return None
        if filled < abs(qty):                    # 部分平倉：記低已平嗰份，其餘繼續管理（下一輪再平）
            part = filled if qty > 0 else -filled
            self._record_exit(code, part, px, reason + f"（部分 {filled}／{abs(qty)}）", meta)
            if meta.get("code") == code:
                self.state["pos"] = {**meta, "qty": abs(qty) - filled}
            self._log("events", {"type": "PARTIAL_CLOSE", "code": code, "wanted": abs(qty), "filled": filled})
            return px
        self._record_exit(code, qty, px, reason, meta)
        return px

    def _record_exit(self, code, qty, px, reason, meta):
        st = self.state
        entry = meta.get("entry") if meta.get("code") == code else None
        side = 1 if qty > 0 else -1
        pts = round((px - entry) * side, 4) if entry is not None else None
        hkd = round(pts * abs(qty) * self.cfg.point_value) if pts is not None else None
        net = hkd - fee_hkd(spec_for(self.cfg.product), qty, self.cfg.fee_per_side_hkd) if hkd is not None else None
        risk = meta.get("risk_pts") if meta.get("code") == code else None
        hold = None
        try:
            hold = round((self.clock() - datetime.fromisoformat(meta["opened_at"])).total_seconds() / 60, 1)
        except (KeyError, TypeError, ValueError):
            pass
        # 覆盤欄位：R 倍數（點數 ÷ 開倉時止蝕距離）、MFE／MAE、持倉分鐘、開倉時信心、教學簿版本、時段
        rec = {"type": "CLOSE", "code": code, "side": side, "qty": abs(qty), "entry": entry,
               "price": px, "points": pts, "pnl_hkd_gross": hkd, "pnl_hkd_net": net, "reason": reason,
               "opened_at": meta.get("opened_at"), "risk_pts": risk,
               "r_multiple": round(pts / risk, 2) if pts is not None and risk else None,
               "mfe": meta.get("mfe"), "mae": meta.get("mae"), "hold_min": hold,
               "confidence": meta.get("confidence"), "lessons": meta.get("lessons"),
               "open_session": meta.get("session"), "open_reason": (meta.get("reason") or "")[:200],
               "model": meta.get("model")}
        self._log("trades", rec)
        st.setdefault("today_trades", []).append(
            {"side": "LONG" if side > 0 else "SHORT", "entry": entry, "exit": px,
             "points": pts, "pnl_hkd": net, "reason": reason[:60]})
        if meta.get("code") == code:
            st["pos"] = None
        log.info("平倉 %s %s @%s 點數=%s (%s)", code, qty, px, pts, reason)

    # ---------- [R234] 伺服器端後備止蝕 ----------
    def _server_trigger(self, side, stop):
        """後備止蝕觸發價：程式止蝕再遠 buffer%，平時由程式先止蝕，唔會兩邊同時平倉。"""
        return round_tick(stop - side * abs(stop) * self.cfg.server_stop_buffer_pct / 100, self.cfg.tick)

    def _ensure_server_stop(self, contract, qty):
        """真倉有倉但未有後備止蝕就掛（開倉後、或者之前掛唔到／部分平倉後重掛）。失敗唔影響程式止蝕，下一輪再試。"""
        meta = self.state.get("pos")
        if not (self.cfg.server_stop and qty and meta and meta.get("code") == contract
                and meta.get("stop") and not meta.get("server_stop_id")):
            return
        side = 1 if qty > 0 else -1
        trigger = self._server_trigger(side, meta["stop"])
        try:
            meta["server_stop_id"] = self.broker.stop_order(contract, -side, abs(qty), trigger)
            meta["server_stop"] = trigger
            self._log("events", {"type": "SERVER_STOP", "code": contract, "qty": abs(qty), "trigger": trigger,
                                 "order_id": meta["server_stop_id"]})
        except Exception as e:  # noqa: BLE001
            if not meta.get("server_stop_failed"):
                self._log("events", {"type": "SERVER_STOP_FAILED", "code": contract, "error": str(e)[:200]})
            meta["server_stop_failed"] = True
            log.warning("掛後備止蝕失敗（程式止蝕照用，下一輪再試）：%s", e)

    def _move_server_stop(self):
        meta = self.state.get("pos")
        if not (meta and meta.get("server_stop_id") and meta.get("stop")):
            return
        trigger = self._server_trigger(meta["side"], meta["stop"])
        try:
            self.broker.modify_stop(meta["server_stop_id"], meta["qty"], trigger)
            meta["server_stop"] = trigger
        except Exception as e:  # noqa: BLE001
            self._log("events", {"type": "SERVER_STOP_MODIFY_FAILED", "error": str(e)[:200],
                                 "order_id": meta["server_stop_id"], "keep": meta.get("server_stop")})

    def _cancel_server_stop(self, meta):
        """撤後備止蝕；回傳 (成交價, 成交數量)，撤之前已經觸發就唔係 0。撤唔到（狀態不明）會 raise。"""
        px, filled = self.broker.cancel_order(meta["server_stop_id"])
        meta["server_stop_id"] = None
        self._log("events", {"type": "SERVER_STOP_CANCELLED", "code": meta.get("code"), "filled": filled})
        return px, filled

    def _own_qty(self, contract):
        meta = self.state.get("pos")
        return meta["side"] * meta["qty"] if meta and meta.get("code") == contract else 0

    def _reconcile(self, contract, broker_qty, positions, now):
        """唔接手、唔平、唔減其他人嘅倉；只記低「外來倉」並停開新倉。"""
        st = self.state
        meta = st.get("pos")
        own = self._own_qty(contract)
        if own != 0 and broker_qty == 0:
            px, reason = None, "倉位喺外部被平（估算價）"
            if meta.get("server_stop_id"):
                try:
                    px, filled = self._cancel_server_stop(meta)
                    reason = "後備止蝕（富途伺服器）" if filled else reason
                except Exception as e:  # noqa: BLE001
                    log.exception("查後備止蝕失敗")
                    self._log("events", {"type": "SERVER_STOP_ORPHAN", "order_id": meta.get("server_stop_id"),
                                         "error": str(e)[:200], "note": "倉已冇但後備止蝕撤唔到，請喺富途 App 人手撤"})
            if px is None:
                px = self.broker.snapshot(meta["code"])["last"]
            self._record_exit(meta["code"], own, px, reason, meta)
            own = 0
        foreign = broker_qty - own
        others = {c: q for c, (q, _) in positions.items() if c != contract and q}
        if foreign != st.get("foreign_qty", 0) or others != st.get("foreign_other", {}):
            self._log("events", {"type": "FOREIGN_POSITION", "code": contract, "foreign_qty": foreign,
                                 "broker_qty": broker_qty, "own_qty": own, "other_months": others,
                                 "note": "唔屬龍飛陣嘅倉（可能係雲垂陣對沖或人手），唔會掂；即月有外來倉時停開新倉"})
            if foreign:
                log.warning("即月 %s 有外來倉 %+d 張（富途淨額 %+d，自己 %+d），停開新倉", contract,
                            foreign, broker_qty, own)
        st["foreign_qty"], st["foreign_other"] = foreign, others

    def _own_day_pnl(self, contract, last):
        cfg, st = self.cfg, self.state
        realized = sum(t.get("pnl_hkd") or 0 for t in st.get("today_trades", []))
        meta = st.get("pos")
        unreal = 0.0
        if meta and meta.get("code") == contract and meta.get("entry") is not None:
            unreal = ((last - meta["entry"]) * meta["side"] * meta["qty"] * cfg.point_value
                      - fee_hkd(spec_for(cfg.product), meta["qty"], cfg.fee_per_side_hkd))
        return realized + unreal

    def _flatten_all(self, reason):
        meta = self.state.get("pos")      # 只平自己嘅倉
        if meta:
            self._close(meta["code"], meta["side"] * meta["qty"], reason)

    def _halt(self, reason):
        self.state["halted"] = True
        self.state["halt_reason"] = reason
        self._log("events", {"type": "HALT", "reason": reason})
        log.warning("停機：%s", reason)

    def _front_month(self, now):
        day = self.state.get("day")
        if self._contract_cache[0] == day and self._contract_cache[1]:
            return self._contract_cache[1]
        if self.cfg.kind == "stock":                       # ETF 冇合約月份
            code = f"{self.cfg.market}.{self.cfg.product}"
            self._contract_cache = (day, code)
            self.state["contract"] = code
            return code
        code = pick_front_month(self.broker.list_contracts(self.cfg.product),
                                self.cfg.product, now.astimezone(spec_for(self.cfg.product).tz).date(),
                                self.cfg.roll_days)
        self._contract_cache = (day, code)
        if code and self.state.get("contract") != code:
            self._log("events", {"type": "CONTRACT", "code": code})
            self.state["contract"] = code
        return code

    def snapshot_equity(self):
        st = self.state
        # [R212] 使用者 10-17：模擬同真實戶口淨值、購買力上載私人 GCS（網頁唔顯示）
        fn = getattr(self.broker, "account_snapshot", None)
        if fn:
            key = "real_account" if self.cfg.trd_env == "REAL" else "sim_account"
            try:
                st[key] = {**fn(), "ts": self.clock().isoformat(timespec="seconds")}
            except Exception as e:  # noqa: BLE001
                log.warning("讀戶口淨值失敗：%s", e)
        self._log("equity", {"equity": st.get("last_equity"), "day": st.get("day"),
                             "day_pnl": st.get("day_pnl"), "pos": (st.get("pos") or {}).get("side", 0)})
