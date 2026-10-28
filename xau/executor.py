import re
"""EA 指令佇列（實倉）：把動作變成 cmd_text（分行文字，EA 用 StringSplit 讀），cmd_ack 回報後清走。
天覆陣引擎（main.py）同 Telegram 頻道訊號（tgsignal.py）共用。XAU_EXECUTE=0 時 cmd_text 永遠空。"""
import config
import rules

CMD_TTL_SEC = 600            # 指令 10 分鐘內冇執行就作廢（EA 離線時唔好開舊單）


def clean_note(note):
    """[R350] 開倉備註（EA 寫入 MT5 註解）：去掉分隔符 |／=／換行，最長 16 字。"""
    t = "".join(ch for ch in str(note or "") if ch not in "|=\r\n\t").strip()
    return t[:16]


def enqueue(state, action, stop, target, now, cmd_id, lots=None, tag="", magic=None, note=""):
    """回傳指令文字或 None。cmd_id 取前 8 碼。magic 預設本服務（跟單用 FOLLOW_MAGIC）。[R350] note＝開倉備註（AI決策／跟單CTC…），EA 放入 MT5 註解。"""
    cid = cmd_id[:8]; magic = config.MAGIC if magic is None else magic
    lots = rules.lots(state) if lots is None else lots                 # [R346] 階梯級數喺 state
    nd = config.PRICE_DIGITS
    tp = "" if target is None else f"{target:.{nd}f}"
    if action in ("OPEN_LONG", "OPEN_SHORT"):
        text = f"open|{'BUY' if action == 'OPEN_LONG' else 'SELL'}|{lots:.2f}|sl={stop:.{nd}f}|tp={tp}|magic={magic}" \
               + (f"|note={clean_note(note)}" if clean_note(note) else "") + f"|id={cid}"       # [R350] note 放 id 之前（id 保持喺尾，mask／ack 唔受影響）
    elif action == "CLOSE":
        text = f"close|all|magic={magic}|id={cid}"
    elif action == "UPDATE_STOP":
        text = f"modify|all|sl={stop:.{nd}f}|tp={tp}|magic={magic}|id={cid}"
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


def mask_id(cid):
    """公開 JSON 用：指令 id 只露頭 2 碼（10-23 權杖公開，id 外露會被假 cmd_ack 冒認）。"""
    cid = str(cid or "")
    return cid[:2] + "*" * max(0, len(cid) - 2) if cid else cid


def mask_cmd(c):
    out = dict(c)
    out["id"] = mask_id(c.get("id"))
    if "text" in out:
        out["text"] = re.sub(r"id=([0-9a-f]+)", lambda m: "id=" + mask_id(m.group(1)), str(out["text"]))
    return out


def mask_account(a):
    """登入號只露尾 2 位（真倉戶口號碼唔可以公開）。"""
    a = str(a or "")
    return ("…" + a[-2:]) if len(a) > 2 else ("已設" if a else None)
