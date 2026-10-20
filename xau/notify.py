"""Telegram 通知（同 main.py tg_send 一樣：TG_BOT_TOKEN／TG_CHAT_ID 環境變數；冇設或失敗 → False；唔記錄權杖）。"""
import os

import requests

import config


def tg_send(text):
    token, chat = os.environ.get("TG_BOT_TOKEN", "").strip(), os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": f"【{config.TEAM_NAME}】{text}"}, timeout=10)
        return r.status_code == 200
    except Exception as exc:  # noqa: BLE001  不印網址（含權杖）
        print(f"⚠️ [Telegram 發送失敗] {type(exc).__name__}", flush=True)
        return False
