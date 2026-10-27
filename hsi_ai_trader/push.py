"""每 5 分鐘將龍飛陣狀態、成交同最近決策推上 Cloud Run（action=longfei_push），由佢存入 GCS longfei/latest.json。

VM 冇直接寫 GCS 嘅權限，所以同 futu/push_to_gcp.py 一樣經 Cloud Run webhook。
冇設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN 就唔推。失敗只記 log，唔影響交易。
R212 起推模擬同真實戶口淨值、購買力（使用者 10-17；私人 GCS，網頁唔顯示）。權杖唔會寫入 log。
"""
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("push")

MAX_TRADES = 500
MAX_DECISIONS = 30


def _tail_jsonl(path, n):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def build_packet(cfg, state, token):
    pos = state.get("pos") or {}
    trades = [t for t in _tail_jsonl(cfg.log_dir / "trades.jsonl", MAX_TRADES * 3)
              if t.get("type") in ("OPEN", "CLOSE")][-MAX_TRADES:]
    decisions = [{k: d.get(k) for k in ("ts", "bar", "last", "pos", "ai_action", "final", "confidence",
                                        "reason", "rejected", "stop", "target", "usage", "lessons", "session",
                                        "gate", "gate_usage", "gate_reason")}
                 for d in _tail_jsonl(cfg.log_dir / "decisions.jsonl", MAX_DECISIONS)]
    status = {"trd_env": cfg.trd_env, "product": cfg.product, "point_value": cfg.point_value,
              "max_qty": cfg.max_qty, "daily_loss_limit": cfg.daily_loss_limit,
              "day": state.get("day"), "day_pnl": state.get("day_pnl"),
              "trades_today": state.get("trades_today", 0), "halted": bool(state.get("halted")),
              # [R218] 今日慳咗幾多次決策模型：skipped＝冇倉又唔准開；gated＝Haiku 話唔使睇
              "ai_skipped_today": state.get("ai_skipped_today", 0), "ai_gated_today": state.get("ai_gated_today", 0),
              "halt_reason": state.get("halt_reason"), "foreign_qty": state.get("foreign_qty", 0),
              "contract": state.get("contract"), "paused": cfg.pause_file.exists(),
              "stopped": cfg.stop_file.exists(), "real_preflight": state.get("real_preflight"),
              # [R298] 開倉單失敗原因（富途 last_err_msg）同今日有冇因此停開新倉
              "order_fail_today": state.get("order_fail_today", 0), "order_errors": state.get("order_errors"),
              "open_block": state.get("open_block"),
              "buying_power": state.get("buying_power"),   # [R299] 富途最多可開張數
              # [R347] 沿用 HOLD：on 慳咗幾多次；shadow 會沿用幾多次、其中幾多次 AI 其實開咗倉（應該係 0）
              "ai_reused_today": state.get("ai_reused_today", 0), "reuse_shadow_today": state.get("reuse_shadow_today", 0),
              "reuse_shadow_open_today": state.get("reuse_shadow_open_today", 0),
              "size_level": state.get("size_level"),       # [R305] 按成績升級：下一單張數
              # [R212] 戶口淨值同購買力（私人 GCS，網頁唔顯示）：模擬程式報模擬戶口；真實戶口由真倉程式或者戶口檢查
              "sim_account": state.get("sim_account") if cfg.trd_env == "SIMULATE" else None,
              "real_account": state.get("real_account"),
              "pos": {k: pos.get(k) for k in ("code", "side", "qty", "entry", "stop", "target", "opened_at", "days_held")}
              if pos else None}
    return {"action": "longfei_push", "token": token,
            "sent_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "state": status, "trades": trades, "decisions": decisions}


def push(cfg, state):
    url, token = os.getenv("ZHUGE_GCP_URL", "").strip(), os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
    if not url or not token:
        return False
    body = json.dumps(build_packet(cfg, state, token), ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = 200 <= r.status < 300
    except Exception as e:  # noqa: BLE001
        log.warning("上載 GCS 失敗：%s", e.__class__.__name__)   # 唔印網址／權杖
        return False
    if not ok:
        log.warning("上載 GCS 失敗：HTTP %s", r.status)
    return ok
