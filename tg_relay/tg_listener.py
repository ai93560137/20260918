"""[R290] 外部 Telegram 頻道 → Cloud Run（action=tg_signal）→ AI 分析 → 訊號確認 bot 發按鈕 → 人手確認後先送 webhook。

用「用戶帳號」（Telethon／MTProto）讀你已加入但 bot 加唔入去嘅頻道，每則新訊息 POST 到 Cloud Run。
這個腳本只轉發文字，**唔會下單**；下單只會喺你喺 Telegram 按「✅ 確認下單」之後由 Cloud Run 做。

建議跑喺台灣 VM claude-ops（長開、唔會瞓覺），用獨立 Linux 使用者 tgrelay（唔好用 claudeops 使用者）；詳見 tg_relay/README.md。

環境變數（這個 repo 是公開的，ID／hash／權杖／網址都唔好寫入檔案）：
  TG_API_ID、TG_API_HASH     https://my.telegram.org → API development tools 申請
  TG_CHANNELS                要監聽嘅頻道，逗號分隔（@username、t.me 連結或數字 id）
  ZHUGE_GCP_URL              天覆陣 zhuge-xau 網址（https://zhuge-xau-….run.app/），唔係 zhuge-risk-manager
  WEBHOOK_SECRET_TOKEN       同 zhuge-xau 環境變數相同
  選填：TG_SESSION（session 檔路徑，預設 ~/.tg_relay/user.session；等同帳號密碼，chmod 600）
        TG_FORWARD_EDITS=1（訊息被編輯都轉發；預設 0）

指令：
  python tg_listener.py --login          # 第一次：輸入電話號碼同驗證碼，建立 session 檔
  python tg_listener.py --list           # 列出你已加入嘅頻道與 id（揀 TG_CHANNELS 用）
  python tg_listener.py --dry-run        # 只印出收到嘅訊息，唔 POST
  python tg_listener.py                  # 長跑
  python tg_listener.py --set-webhook    # 設定「訊號確認 bot」嘅 webhook（要 TG_SIGNAL_BOT_TOKEN、TG_SIGNAL_WEBHOOK_SECRET）
"""
import argparse, asyncio, json, os, sys, time, urllib.error, urllib.request

SCRIPT_VERSION = "tg-relay-1"
GCP_URL = os.environ.get("ZHUGE_GCP_URL", "").strip()
TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN", "").strip()
SESSION = os.path.expanduser(os.environ.get("TG_SESSION", "~/.tg_relay/user.session"))
FORWARD_EDITS = os.environ.get("TG_FORWARD_EDITS", "0") == "1"
HTTP_TIMEOUT_SEC = 60          # Cloud Run 要等 AI 分析
RETRIES = 4


def channels_from_env():
    out = []
    for item in os.environ.get("TG_CHANNELS", "").split(","):
        item = item.strip()
        if not item:
            continue
        out.append(int(item) if item.lstrip("-").isdigit() else item)
    return out


def build_payload(chat, msg, reply_text=None, edited=False):
    """純函數：Telethon 物件 → POST 封包（測試用 SimpleNamespace 就得）。"""
    title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(getattr(chat, "id", ""))
    edit_date = getattr(msg, "edit_date", None)
    date = getattr(msg, "date", None)
    return {
        "action": "tg_signal", "token": TOKEN, "script_version": SCRIPT_VERSION,
        "channel": title, "channel_id": getattr(chat, "id", None), "msg_id": getattr(msg, "id", None),
        "date": date.isoformat() if date else None,
        "edit_ts": int(edit_date.timestamp()) if edited and edit_date else None,
        "text": (getattr(msg, "message", None) or "").strip(),
        "reply_text": (reply_text or "").strip() or None,
    }


def post(payload):
    """POST 到 Cloud Run；網絡錯誤／5xx 退避重試。回傳回應 dict 或 None。日誌唔印網址與權杖。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(GCP_URL, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                print(f"❌ HTTP {exc.code}（檢查 WEBHOOK_SECRET_TOKEN）", flush=True)
                return None
            why = f"HTTP {exc.code}"
        except Exception as exc:
            why = type(exc).__name__
        wait = 2 ** (attempt + 1)
        print(f"⚠️ POST 失敗（{why}），{wait} 秒後重試", flush=True)
        time.sleep(wait)
    return None


def set_webhook():
    bot = os.environ.get("TG_SIGNAL_BOT_TOKEN", "").strip()
    secret = os.environ.get("TG_SIGNAL_WEBHOOK_SECRET", "").strip()
    if not (bot and secret and GCP_URL):
        sys.exit("要先設 TG_SIGNAL_BOT_TOKEN、TG_SIGNAL_WEBHOOK_SECRET、ZHUGE_GCP_URL")
    url = GCP_URL.split("?")[0].rstrip("/") + "/?tg=signal"
    body = json.dumps({"url": url, "secret_token": secret, "allowed_updates": ["callback_query"],
                       "drop_pending_updates": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{bot}/setWebhook", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("setWebhook →", json.loads(resp.read().decode()).get("description"))


def make_client():
    from telethon import TelegramClient          # pip install telethon
    api_id, api_hash = os.environ.get("TG_API_ID", "").strip(), os.environ.get("TG_API_HASH", "").strip()
    if not (api_id and api_hash):
        sys.exit("要先設 TG_API_ID、TG_API_HASH（https://my.telegram.org）")
    os.makedirs(os.path.dirname(SESSION), mode=0o700, exist_ok=True)
    return TelegramClient(SESSION, int(api_id), api_hash)


async def run(dry_run):
    from telethon import events
    chans = channels_from_env()
    if not chans:
        sys.exit("TG_CHANNELS 未設定（先跑 --list 揀頻道）")
    if not dry_run and not (GCP_URL and TOKEN):
        sys.exit("要先設 ZHUGE_GCP_URL、WEBHOOK_SECRET_TOKEN")
    client = make_client()
    await client.start()
    try:
        os.chmod(SESSION if SESSION.endswith(".session") else SESSION + ".session", 0o600)
    except OSError:
        pass

    async def forward(event, edited):
        msg = event.message
        if not (msg.message or "").strip():
            return                                # 純圖片／貼圖：冇文字可分析
        chat = await event.get_chat()
        reply_text = None
        if msg.is_reply:
            try:
                reply = await msg.get_reply_message()
                reply_text = reply.message if reply else None
            except Exception:
                pass
        payload = build_payload(chat, msg, reply_text, edited)
        shown = payload["text"][:80].replace("\n", " ")
        if dry_run:
            print(f"[dry-run] {payload['channel']} #{payload['msg_id']}{'（編輯）' if edited else ''}: {shown}", flush=True)
            return
        resp = await asyncio.to_thread(post, payload)
        print(f"📨 {payload['channel']} #{payload['msg_id']} → {(resp or {}).get('status')}"
              f"{'（可確認）' if (resp or {}).get('confirmable') else ''}", flush=True)

    client.add_event_handler(lambda e: forward(e, False), events.NewMessage(chats=chans))
    if FORWARD_EDITS:
        client.add_event_handler(lambda e: forward(e, True), events.MessageEdited(chats=chans))
    print(f"✅ {SCRIPT_VERSION} 監聽 {len(chans)} 個頻道{'（dry-run）' if dry_run else ''}；Ctrl+C 停", flush=True)
    await client.run_until_disconnected()


async def list_dialogs():
    client = make_client()
    await client.start()
    async for d in client.iter_dialogs():
        if d.is_channel or d.is_group:
            print(f"{d.id}\t{d.name}")
    await client.disconnect()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--set-webhook", action="store_true")
    args = ap.parse_args()
    if args.set_webhook:
        return set_webhook()
    if args.login:
        async def _login():
            client = make_client()
            await client.start()
            print("✅ 已登入，session 檔已建立（等同帳號密碼，唔好複製或上傳）")
            await client.disconnect()
        return asyncio.run(_login())
    if args.list:
        return asyncio.run(list_dialogs())
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
