"""📨 天覆陣訊號書：外部 Telegram 頻道 → 簽名 POST → 訊號書服務（zhuge-xau-sig 等）→ 解析存檔（S0 唔落單）。

用「用戶帳號」（Telethon／MTProto）讀白名單頻道，每則新訊息按關鍵字分流到對應產品嘅訊號書服務。
呢個腳本只讀、只轉發文字，冇任何傳送訊息、加入頻道、刪除嘅程式碼；**唔會下單**。
使用者 10-21 揀方案 B（xau/TG_SIGNAL_PROPOSAL.md）：跑喺專用 VM，獨立 Linux 使用者 tgrelay，家目錄 700、設定檔 600。

環境變數（repo 係公開嘅，ID／hash／密鑰／網址都唔好寫入檔案）：
  TG_API_ID、TG_API_HASH        https://my.telegram.org → API development tools 申請
  TG_CHANNELS                   要監聽嘅頻道，逗號分隔（數字 id、@username 或 t.me 連結）
  TG_ROUTES                     產品=網址，逗號分隔，例：XAUUSD=https://zhuge-xau-sig-….run.app/,EURUSD=https://…
  TG_SIGNAL_INGEST_SECRET       同訊號書服務環境變數相同（HMAC 簽名；唔係 WEBHOOK_SECRET_TOKEN）
  選填：TG_SESSION（session 檔路徑，預設 ~/.tg_relay/user.session；等同成個帳號，chmod 600）
        TG_FORWARD_EDITS=1（訊息被編輯都轉發；預設 0）
        TG_ROUTE_DEFAULT（分流唔到嘅訊息送去邊個產品；預設唔送，只計數）

指令：
  python tg_listener.py --login          # 第一次：輸入電話號碼、驗證碼、兩步驗證密碼，建立 session 檔
  python tg_listener.py --list           # 列出你已加入嘅頻道與 id（揀 TG_CHANNELS 用）
  python tg_listener.py --dry-run        # 只印出收到嘅訊息同分流結果，唔 POST
  python tg_listener.py                  # 長跑（建議用 systemd，見 tg_relay/README.md）
"""
import argparse, asyncio, hashlib, hmac, json, os, re, sys, time, urllib.error, urllib.request

SCRIPT_VERSION = "tg-relay-2"
SECRET = os.environ.get("TG_SIGNAL_INGEST_SECRET", "").strip()
SESSION = os.path.expanduser(os.environ.get("TG_SESSION", "~/.tg_relay/user.session"))
FORWARD_EDITS = os.environ.get("TG_FORWARD_EDITS", "0") == "1"
ROUTE_DEFAULT = os.environ.get("TG_ROUTE_DEFAULT", "").strip().upper()
HTTP_TIMEOUT_SEC = 60          # 訊號書要等 Haiku 解析
RETRIES = 4
HEARTBEAT_SEC = 300
# 關鍵字分流（大小寫不拘）；先中先得。只決定送去邊個服務，真正解析由服務做。
ROUTE_PATTERNS = (
    ("XAUUSD", re.compile(r"XAU\s*/?\s*USD|\bXAU\b|\bGOLD\b|黃金|黄金", re.I)),
    ("EURUSD", re.compile(r"EUR\s*/?\s*USD", re.I)),
    ("GBPUSD", re.compile(r"GBP\s*/?\s*USD", re.I)),
    ("AUDUSD", re.compile(r"AUD\s*/?\s*USD", re.I)),
    ("USDJPY", re.compile(r"USD\s*/?\s*JPY", re.I)),
)
STATS = {"forwarded": 0, "dropped": 0}


def routes_from_env():
    out = {}
    for item in os.environ.get("TG_ROUTES", "").split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip().upper()] = v.strip()
    return out


def route_of(text, reply_text=None):
    """純函數：訊息 → 產品代號或 None。回覆訊息連埋原訊息一齊睇（例如「TP1 到」回覆一條黃金訊號）。"""
    blob = f"{text or ''}\n{reply_text or ''}"
    for sym, pat in ROUTE_PATTERNS:
        if pat.search(blob):
            return sym
    return ROUTE_DEFAULT or None


def sign(ts, body):
    """同 xau/signals.py sign() 一樣：hex(HMAC-SHA256(secret, f"{ts}." + body))。"""
    return hmac.new(SECRET.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()


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
        "action": "tg_signal", "script_version": SCRIPT_VERSION,
        "channel": title, "channel_id": getattr(chat, "id", None), "msg_id": getattr(msg, "id", None),
        "date": date.isoformat() if date else None,
        "edit_ts": int(edit_date.timestamp()) if edited and edit_date else None,
        "text": (getattr(msg, "message", None) or "").strip(),
        "reply_text": (reply_text or "").strip() or None,
    }


def post(url, payload):
    """簽名 POST 到訊號書；網絡錯誤／5xx 退避重試。回傳回應 dict 或 None。日誌唔印網址、密鑰、訊息原文。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(RETRIES):
        ts = int(time.time())
        headers = {"Content-Type": "application/json", "X-Sig-Ts": str(ts), "X-Sig-Signature": sign(ts, data)}
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                print(f"❌ HTTP {exc.code}（403 = 檢查 TG_SIGNAL_INGEST_SECRET 同 VM 時鐘）", flush=True)
                return None
            why = f"HTTP {exc.code}"
        except Exception as exc:
            why = type(exc).__name__
        wait = 2 ** (attempt + 1)
        print(f"⚠️ POST 失敗（{why}），{wait} 秒後重試", flush=True)
        time.sleep(wait)
    return None


async def heartbeat_loop(routes, n_channels):
    while True:
        body = {"action": "tg_heartbeat", "script_version": SCRIPT_VERSION, "channels": n_channels, "connected": True, **STATS}
        for url in set(routes.values()):
            await asyncio.to_thread(post, url, body)
        await asyncio.sleep(HEARTBEAT_SEC)


def make_client():
    from telethon import TelegramClient          # pip install telethon
    api_id, api_hash = os.environ.get("TG_API_ID", "").strip(), os.environ.get("TG_API_HASH", "").strip()
    if not (api_id and api_hash):
        sys.exit("要先設 TG_API_ID、TG_API_HASH（https://my.telegram.org）")
    os.makedirs(os.path.dirname(SESSION), mode=0o700, exist_ok=True)
    return TelegramClient(SESSION, int(api_id), api_hash, catch_up=True)   # 重連時補返斷線期間嘅訊息（服務按 msg_id 去重）


async def run(dry_run):
    from telethon import events
    chans = channels_from_env()
    if not chans:
        sys.exit("TG_CHANNELS 未設定（先跑 --list 揀頻道）")
    routes = routes_from_env()
    if not dry_run and not (routes and SECRET):
        sys.exit("要先設 TG_ROUTES、TG_SIGNAL_INGEST_SECRET")
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
        sym = route_of(payload["text"], payload["reply_text"])
        url = routes.get(sym) if sym else None
        if dry_run:
            shown = payload["text"][:80].replace("\n", " ")
            print(f"[dry-run] #{payload['msg_id']}{'（編輯）' if edited else ''} → {sym or '分流唔到'}: {shown}", flush=True)
            return
        if not url:
            STATS["dropped"] += 1
            print(f"⏭ #{payload['msg_id']} 分流唔到產品（{sym or '—'}），略過", flush=True)
            return
        resp = await asyncio.to_thread(post, url, payload)
        STATS["forwarded"] += 1
        print(f"📨 #{payload['msg_id']} → {sym} {(resp or {}).get('status')}／{(resp or {}).get('signal_status')}", flush=True)

    client.add_event_handler(lambda e: forward(e, False), events.NewMessage(chats=chans))
    if FORWARD_EDITS:
        client.add_event_handler(lambda e: forward(e, True), events.MessageEdited(chats=chans))
    print(f"✅ {SCRIPT_VERSION} 監聽 {len(chans)} 個頻道、{len(routes)} 個產品{'（dry-run）' if dry_run else ''}；Ctrl+C 停", flush=True)
    if not dry_run:
        asyncio.create_task(heartbeat_loop(routes, len(chans)))
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
    args = ap.parse_args()
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
