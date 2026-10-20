"""EA 指令佇列（實倉）：把動作變成 cmd_text（分行文字，EA 用 StringSplit 讀），cmd_ack 回報後清走。
天覆陣引擎（main.py）同 Telegram 頻道訊號（tgsignal.py）共用。XAU_EXECUTE=0 時 cmd_text 永遠空。"""
import config
import rules

CMD_TTL_SEC = 600            # 指令 10 分鐘內冇執行就作廢（EA 離線時唔好開舊單）


def enqueue(state, action, stop, target, now, cmd_id, lots=None, tag=""):
    """回傳指令文字或 None。cmd_id 取前 8 碼。"""
    cid = cmd_id[:8]
    lots = rules.lots() if lots is None else lots
    tp = "" if target is None else f"{target:.2f}"
    if action in ("OPEN_LONG", "OPEN_SHORT"):
        text = f"open|{'BUY' if action == 'OPEN_LONG' else 'SELL'}|{lots:.2f}|sl={stop:.2f}|tp={tp}|magic={config.MAGIC}|id={cid}"
    elif action == "CLOSE":
        text = f"close|all|magic={config.MAGIC}|id={cid}"
    elif action == "UPDATE_STOP":
        text = f"modify|all|sl={stop:.2f}|tp={tp}|magic={config.MAGIC}|id={cid}"
    else:
        return None
    state["pending_cmds"] = [c for c in (state.get("pending_cmds") or []) if now - c["ts"] < CMD_TTL_SEC]
    state["pending_cmds"].append({"id": cid, "text": text, "ts": now, "acked": False, "tag": tag})
    return text


def cmd_text(state, now):
    if not config.EXECUTE:
        return ""
    return "\n".join(c["text"] for c in (state.get("pending_cmds") or [])
                     if (not c.get("acked") or now < (c.get("resend_until") or 0)) and now - c["ts"] < CMD_TTL_SEC)


def ack(state, cid, payload, now):
    """回傳 True = 搵到未回報嘅指令並標記。"""
    found = False
    for c in state.get("pending_cmds") or []:
        if c["id"] == cid and not c.get("acked"):
            c.update(acked=True, ok=bool(payload.get("ok")), ticket=payload.get("ticket"),
                     message=str(payload.get("message") or "")[:200], acked_ts=now)
            found = True
    return found
