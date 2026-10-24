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
  python tg_listener.py --history 90     # 讀每個頻道最近 90 日舊訊息送去訊號書做歷史解析（加 --dry-run 只數唔送）
"""
import argparse, asyncio, hashlib, hmac, json, os, re, sys, time, urllib.error, urllib.request

SCRIPT_VERSION = "tg-relay-3"
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
    fwd = getattr(msg, "fwd_from", None)                 # v3：轉發標頭（原發佈時間、原頻道 id）——分辨「轉載群組」同「原頻道」
    fwd_date = getattr(fwd, "date", None) if fwd else None
    from_id = getattr(fwd, "from_id", None) if fwd else None
    fwd_from_id = (getattr(from_id, "channel_id", None) or getattr(from_id, "user_id", None)) if from_id else None
    return {
        "action": "tg_signal", "script_version": SCRIPT_VERSION,
        "channel": title, "channel_id": getattr(chat, "id", None), "msg_id": getattr(msg, "id", None),
        "date": date.isoformat() if date else None,
        "edit_ts": int(edit_date.timestamp()) if edited and edit_date else None,
        "fwd_date": fwd_date.isoformat() if fwd_date else None, "fwd_from_id": fwd_from_id,
        "fwd_post_id": getattr(fwd, "channel_post", None) if fwd else None,
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


async def backfill(days, dry_run, skip_days=0):
    """讀每個頻道最近 days 日嘅舊訊息（由舊到新），送去訊號書做歷史解析（history=true，唔當即時訊號）。
    每條之間停 2.5 秒（服務每分鐘上限 30 個）；服務按頻道＋訊息 id 去重，中途斷咗再跑會跳過已處理嘅。"""
    import datetime as _dt
    chans, routes = channels_from_env(), routes_from_env()
    if not dry_run and not (routes and SECRET):
        sys.exit("要先設 TG_ROUTES、TG_SIGNAL_INGEST_SECRET")
    since = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    until = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=skip_days) if skip_days else None   # 10-25：最近 N 日已經入咗唔再送（每條慳 2.5 秒）
    skipped = 0
    client = make_client()
    await client.start()
    total = sent = 0
    for ch in chans:
        chat = await client.get_entity(ch)
        n = 0
        async for msg in client.iter_messages(chat, reverse=True, offset_date=since):   # reverse＋offset_date：由 since 之後、舊到新
            if not (msg.message or "").strip():
                continue
            if until is not None and msg.date and msg.date >= until:
                skipped += 1
                continue
            reply_text = None
            if msg.is_reply:
                try:
                    reply = await msg.get_reply_message()
                    reply_text = reply.message if reply else None
                except Exception:
                    pass
            payload = {**build_payload(chat, msg, reply_text, False), "history": True}
            sym = route_of(payload["text"], payload["reply_text"])
            url = routes.get(sym) if sym else None
            total += 1
            n += 1
            if dry_run or not url:
                continue
            resp = await asyncio.to_thread(post, url, payload)
            sent += 1
            if sent % 50 == 0:
                print(f"📜 已送 {sent} 條（最後 {(resp or {}).get('status')}）", flush=True)
            await asyncio.sleep(2.5)
        print(f"📜 頻道 #{getattr(chat, 'id', '?')}：{n} 條有文字嘅訊息", flush=True)
    await client.disconnect()
    print(f"✅ 歷史訊息完成：共 {total} 條，送出 {sent} 條{'（dry-run 冇送）' if dry_run else ''}{f'；最近 {skip_days} 日已有、跳過 {skipped} 條' if skip_days else ''}", flush=True)


async def fwd_stats(days):
    """只印統計、唔 POST、唔印原文：每個頻道最近 days 日嘅訊息有幾多係轉發、原發佈→貼出延遲、原頻道 id。
    用嚟分辨我哋聽嘅係原頻道定轉載群組（天覆陣 10-22 延遲分析）。"""
    import datetime as _dt, statistics as _st
    chans = channels_from_env()
    since = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    client = make_client()
    await client.start()
    for ch in chans:
        chat = await client.get_entity(ch)
        n = fwd = 0; lags = []; src = {}
        async for msg in client.iter_messages(chat, reverse=True, offset_date=since):
            if not (msg.message or "").strip():
                continue
            n += 1
            f = getattr(msg, "fwd_from", None)
            if not f:
                continue
            fwd += 1
            from_id = getattr(f, "from_id", None)
            sid = getattr(from_id, "channel_id", None) or getattr(from_id, "user_id", None) or ("name:" + str(getattr(f, "from_name", None) or "?"))
            src[sid] = src.get(sid, 0) + 1
            if getattr(f, "date", None) and msg.date:
                lags.append((msg.date - f.date).total_seconds() / 60)
        top = sorted(src.items(), key=lambda kv: -kv[1])[:5]
        lag_txt = f"延遲中位 {_st.median(lags):.1f} 分、90 百分位 {sorted(lags)[int(len(lags) * 0.9) - 1 if len(lags) > 1 else 0]:.1f} 分" if lags else "—"
        print(f"頻道 #{getattr(chat, 'id', '?')}：{n} 條有文字，轉發 {fwd} 條（{fwd / n:.0%}）；{lag_txt}；原來源 id（條數）：{top}" if n else f"頻道 #{getattr(chat, 'id', '?')}：0 條", flush=True)
    await client.disconnect()


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
    ap.add_argument("--history", type=int, metavar="DAYS", help="讀每個頻道最近 DAYS 日嘅舊訊息送去訊號書做歷史解析")
    ap.add_argument("--history-skip-days", type=int, default=0, metavar="N", help="配合 --history：最近 N 日嘅訊息唔再送（之前已經入咗，例如 90）")
    ap.add_argument("--fwd-stats", type=int, metavar="DAYS", help="只印統計：每頻道最近 DAYS 日有幾多條係轉發、原發佈→貼出延遲、原來源 id（唔 POST、唔印原文）")
    args = ap.parse_args()
    if args.fwd_stats:
        return asyncio.run(fwd_stats(args.fwd_stats))
    if args.history:
        return asyncio.run(backfill(args.history, args.dry_run, args.history_skip_days))
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
