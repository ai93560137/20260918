"""MT5 差價合約 5 分 K → GCP（R130，對應 main.py 的 action=futu_data；ES 波幅頁 ?view=es_range）

在裝有 MetaTrader 5 終端機的 Windows 電腦上執行（跟 push_to_gcp.py 同一台也可以）。每 PUSH_INTERVAL_SEC 秒：
  1. 向 MT5 取每個代號最新 BAR_COUNT 根 M5（例 US500 → 推成 US.ES_FRONT）
  2. 把券商時間換成紐約時間、K 線「收市時間」（開市時間 + 5 分鐘，跟 Futu／研究數據同一慣例）
  3. 按 CME 全段交易日（紐約前一天 18:00 至當天 17:00，日期取收市那天）合成交易日 K（K_SESSION）
  4. POST 到 GCP：K_5M（最新 5 分 K）＋ K_SESSION（最近幾個交易日），只有 HTTP 200 且 status == "stored" 才算成功

設定（這個 repo 是公開的，網址與權杖不要寫進檔案）：
  Windows（設一次，重開命令列生效）：
    setx ZHUGE_GCP_URL "https://你的服務.run.app/"
    setx WEBHOOK_SECRET_TOKEN "跟 Cloud Run 環境變數相同的權杖"
  選填：MT5_SYMBOLS（券商代號:GCP 別名，逗號分隔；預設 US500:US.ES_FRONT；例 US500:US.ES_FRONT,USTEC:US.NQ_FRONT）、
        MT5_PATH（terminal64.exe 路徑，終端機沒開時用）、MT5_LOGIN／MT5_PASSWORD／MT5_SERVER（終端機已登入就不用）、
        MT5_UTC_OFFSET（券商時間比 UTC 快幾小時；不設就由最新報價自動推算，休市時沿用上一次）、
        PUSH_INTERVAL_SEC（300）、BAR_COUNT（120）、SESSION_DAYS（每輪推最近幾個交易日的 K_SESSION，預設 3）

第一次（補歷史給波幅頁與紙上交易）：
    python mt5_push.py --backfill 400          # 最近 400 個日曆日的 M5 → 交易日 K 全部推上去（約 280 個交易日）；
                                               # 最近 12 個交易日另外推 5 分 K（紙上交易啟動期用）
之後長跑：
    python mt5_push.py                         # 每 5 分鐘一輪；Ctrl+C 停
離線檢查（不用 MT5、不連 GCP）：
    python mt5_push.py --csv NAS100_M5.csv --utc-offset 3 --dry-run

注意：
  * 差價合約（US500）跟 ES 期貨差一個基差（通常不到 1%），波幅與高低位都以推上去的這條序列為準。開始餵價後請停用
    GitHub Actions 的 es_daily_push.yml（yfinance 日線），否則兩個來源會互相覆蓋同一天的交易日 K；--backfill 會把 MT5
    的交易日 K 覆蓋同日期的 yfinance 列，令整條序列同一來源。
  * 券商在紐約 17:00–18:00 休市；如有這段時間的 K 線會略過；週末的 K 線也略過。
  * 權杖只放環境變數；日誌不印網址與權杖。
"""
import argparse, csv, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SCRIPT_VERSION = "mt5-1"
NY = ZoneInfo("America/New_York")
GCP_URL = os.environ.get("ZHUGE_GCP_URL", "").strip()
TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN", "").strip()
SYMBOLS = [tuple(x.split(":", 1)) if ":" in x else (x, x) for x in os.environ.get("MT5_SYMBOLS", "US500:US.ES_FRONT").split(",") if x.strip()]
PUSH_INTERVAL_SEC = int(os.environ.get("PUSH_INTERVAL_SEC", "300"))
BAR_COUNT = int(os.environ.get("BAR_COUNT", "120"))
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "3"))
BOOT_SESSIONS = 12                       # --backfill 時另外推 5 分 K 的交易日數（main.PAPER_BOOT_DAYS）
CHUNK = 400                              # 每個封包最多幾根（main.FUTU_MAX_BARS）
HTTP_TIMEOUT_SEC = 60
BAR_MINUTES = 5
UTC = timezone.utc


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---- 純函數（tests/test_mt5_push.py 有測試） ----
def broker_offset_hours(tick_epoch, now_epoch=None):
    """MT5 的時間戳是「券商時間當作 UTC」的秒數；跟真正的 UTC 相差的整數小時就是券商時差。報價太舊（休市）→ None。"""
    now_epoch = time.time() if now_epoch is None else now_epoch
    diff = tick_epoch - now_epoch
    off = round(diff / 3600)
    return off if abs(diff - off * 3600) <= 900 else None       # 偏離整點超過 15 分鐘 → 報價不是即時的


def to_ny_close(broker_epoch, offset_h, minutes=BAR_MINUTES):
    """券商時間戳（K 線開市）→ 紐約時間的收市時間字串。"""
    t = datetime.fromtimestamp(broker_epoch - offset_h * 3600, UTC).astimezone(NY).replace(tzinfo=None)
    return (t + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def session_of(time_key):
    """紐約時間（收市）→ CME 交易日：18:00 起算下一天（跟 main.MARKETS['US'] 相同）。"""
    t = datetime.strptime(time_key[:19], "%Y-%m-%d %H:%M:%S")
    return (t + timedelta(hours=6)).strftime("%Y-%m-%d")


def in_session(time_key):
    """排除週末與 17:00–18:00 休市時段（收市時間 17:00 整那根屬於當天，是最後一根）。"""
    t = datetime.strptime(time_key[:19], "%Y-%m-%d %H:%M:%S")
    hm = t.strftime("%H:%M")
    if "17:00" < hm <= "18:00":
        return False
    wd = datetime.strptime(session_of(time_key), "%Y-%m-%d").weekday()
    return wd < 5


def rates_to_bars(rates, offset_h):
    """MT5 copy_rates 的列（time／open／high／low／close／tick_volume）→ 封包用的 K 線（紐約收市時間、依時間排序、去重）。"""
    out = {}
    for r in rates:
        tk = to_ny_close(int(r["time"]), offset_h)
        if not in_session(tk):
            continue
        vol = float(r.get("tick_volume") or r.get("real_volume") or r.get("volume") or 0) or 1.0
        out[tk] = {"time_key": tk, "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                   "close": float(r["close"]), "volume": vol}
    return [out[k] for k in sorted(out)]


def session_bars(bars, drop_head=True):
    """5 分 K → 交易日 K（time_key = 'YYYY-MM-DD 00:00:00'，跟 push_to_gcp.session_bars 同一格式）。
    drop_head：取到的 K 線由某個交易日中途開始 → 那個不完整的交易日不要（否則會把雲端完整的一天蓋成半天）。"""
    groups = {}
    for b in sorted(bars, key=lambda b: b["time_key"]):
        groups.setdefault(session_of(b["time_key"]), []).append(b)
    out = []
    for day in sorted(groups):
        g = groups[day]
        out.append({"time_key": f"{day} 00:00:00", "open": g[0]["open"], "high": max(b["high"] for b in g),
                    "low": min(b["low"] for b in g), "close": g[-1]["close"], "volume": sum(b["volume"] for b in g),
                    "bars": len(g), "first": g[0]["time_key"], "last": g[-1]["time_key"]})
    if drop_head and len(out) > 1 and out[0]["first"][11:16] != "18:05":   # 第一根不是 18:05 收市那根 → 由中途開始
        out = out[1:]
    return out


def read_csv(path):
    """MT5 匯出格式（Time,Open,High,Low,Close,Volume；Time = 'YYYY.MM.DD HH:MM:SS' 券商時間）→ copy_rates 同款列。"""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            t = datetime.strptime(r["Time"], "%Y.%m.%d %H:%M:%S").replace(tzinfo=UTC)
            rows.append({"time": int(t.timestamp()), "open": r["Open"], "high": r["High"], "low": r["Low"], "close": r["Close"],
                         "tick_volume": r.get("Volume") or r.get("TickVolume") or 0})
    return rows


# ---- MT5 與 GCP ----
class Feed:
    def __init__(self, dry_run=False, utc_offset=None):
        self.dry_run, self.offset, self.mt5 = dry_run, utc_offset, None

    def connect(self):
        if self.mt5:
            return
        import MetaTrader5 as mt5                                   # pip install MetaTrader5（只有 Windows）
        kw = {}
        if os.environ.get("MT5_PATH"):
            kw["path"] = os.environ["MT5_PATH"]
        if os.environ.get("MT5_LOGIN"):
            kw.update(login=int(os.environ["MT5_LOGIN"]), password=os.environ.get("MT5_PASSWORD", ""), server=os.environ.get("MT5_SERVER", ""))
        if not mt5.initialize(**kw):
            raise RuntimeError(f"MT5 initialize 失敗：{mt5.last_error()}")
        self.mt5 = mt5

    def offset_for(self, symbol):
        env = os.environ.get("MT5_UTC_OFFSET")
        if env not in (None, ""):
            return int(env)
        tick = self.mt5.symbol_info_tick(symbol)
        off = broker_offset_hours(int(tick.time)) if tick else None
        if off is not None:
            self.offset = off
        if self.offset is None:
            raise RuntimeError("推算不到券商時差（休市中沒有即時報價）；請設 MT5_UTC_OFFSET，例如 setx MT5_UTC_OFFSET 3")
        return self.offset

    def rates(self, symbol, count=None, days=None):
        mt5 = self.mt5
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 沒有代號 {symbol}（市場觀察加不進去）")
        if days:
            end = datetime.now(UTC) + timedelta(hours=self.offset or 0) + timedelta(days=1)
            arr = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, end - timedelta(days=days), end)
        else:
            arr = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, count or BAR_COUNT)
        if arr is None or not len(arr):
            raise RuntimeError(f"MT5 取不到 {symbol} 的 M5：{mt5.last_error()}")
        return [{k: r[k] for k in ("time", "open", "high", "low", "close", "tick_volume")} for r in arr]

    def post(self, packet, quiet=False):
        if self.dry_run:
            log(f"  （dry-run）{packet['kline_type']} {packet['symbol']} {len(packet['data'])} 根，"
                f"{packet['data'][0]['time_key']} → {packet['data'][-1]['time_key']}")
            return True
        if not GCP_URL or not TOKEN:
            sys.exit("請先 setx ZHUGE_GCP_URL 與 WEBHOOK_SECRET_TOKEN（重開命令列生效）")
        req = urllib.request.Request(GCP_URL, data=json.dumps(packet).encode("utf-8"), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
                code, body = resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            code, body = exc.code, {}
        except (urllib.error.URLError, ValueError, OSError) as exc:
            log(f"🔴 推送失敗（網路）：{type(exc).__name__}")
            return False
        status = body.get("status") if isinstance(body, dict) else None
        if code == 200 and status == "stored":
            if not quiet:
                log(f"✅ GCP 已存檔：K 線 {body.get('bars')} 根，最新 {body.get('latest_time')} 收 {body.get('latest_close')}")
                for w in body.get("warnings") or []:
                    log(f"  ⚠️ GCP 提醒：{w}")
            return True
        if code == 403:
            log("❌ 權杖被拒：WEBHOOK_SECRET_TOKEN 跟 Cloud Run 上的不一樣。")
        else:
            log(f"❌ GCP 回 HTTP {code} status={status}：{str(body.get('message') if isinstance(body, dict) else '')[:120]}")
        return False

    def packet(self, alias, symbol, kline_type, data):
        return {"action": "futu_data", "token": TOKEN, "source": f"mt5_cfd:{symbol}", "script_version": SCRIPT_VERSION,
                "symbol": alias, "kline_type": kline_type, "options": [], "data": data,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    def push(self, alias, symbol, bars):
        """一輪：最新 5 分 K ＋ 最近 SESSION_DAYS 個交易日的交易日 K。"""
        if not bars:
            log(f"  {symbol}：沒有可推的 K 線")
            return True
        days = session_bars(bars)[-SESSION_DAYS:]
        five = bars[-BAR_COUNT:]
        log(f"  {symbol} → {alias}：5 分 K {len(five)} 根，最新 {five[-1]['time_key']}（紐約）收 {five[-1]['close']}；"
            f"交易日 K {len(days)} 根（{days[0]['time_key'][:10]} 至 {days[-1]['time_key'][:10]}，最新一天 {days[-1]['bars']} 根）")
        ok = self.post(self.packet(alias, symbol, "K_5M", five))
        return self.post(self.packet(alias, symbol, "K_SESSION", days), quiet=True) and ok

    def backfill(self, alias, symbol, bars, calendar_days):
        days = session_bars(bars)
        log(f"  {symbol} → {alias}：{len(bars)} 根 M5 → {len(days)} 個交易日 K（{days[0]['time_key'][:10]} 至 {days[-1]['time_key'][:10]}）")
        ok = True
        for i in range(0, len(days), CHUNK):
            ok = self.post(self.packet(alias, symbol, "K_SESSION", days[i:i + CHUNK]), quiet=True) and ok
            time.sleep(0.5)
        boot = {d["time_key"][:10] for d in days[-BOOT_SESSIONS:]}
        five = [b for b in bars if session_of(b["time_key"]) in boot]
        log(f"  最近 {len(boot)} 個交易日的 5 分 K {len(five)} 根（紙上交易啟動期）")
        for i in range(0, len(five), CHUNK):
            ok = self.post(self.packet(alias, symbol, "K_5M", five[i:i + CHUNK]), quiet=True) and ok
            time.sleep(0.5)
        return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill", type=int, metavar="天", help="補最近 N 個日曆日的歷史（交易日 K 全部、最近 12 個交易日的 5 分 K）")
    ap.add_argument("--once", action="store_true", help="只推一輪就結束")
    ap.add_argument("--dry-run", action="store_true", help="不連 GCP，只印會推什麼")
    ap.add_argument("--csv", help="離線：讀 MT5 匯出的 M5 CSV 代替連線 MT5（配合 --utc-offset）")
    ap.add_argument("--utc-offset", type=int, help="券商時間比 UTC 快幾小時（--csv 必填；連線時可代替 MT5_UTC_OFFSET）")
    a = ap.parse_args()
    feed = Feed(dry_run=a.dry_run, utc_offset=a.utc_offset)
    if a.csv:
        if a.utc_offset is None:
            sys.exit("--csv 要配合 --utc-offset（券商時間比 UTC 快幾小時）")
        bars = rates_to_bars(read_csv(a.csv), a.utc_offset)
        symbol, alias = SYMBOLS[0]
        log(f"CSV {a.csv}：{len(bars)} 根（紐約收市時間 {bars[0]['time_key'] if bars else '—'} → {bars[-1]['time_key'] if bars else '—'}）")
        (feed.backfill(alias, symbol, bars, a.backfill) if a.backfill else feed.push(alias, symbol, bars))
        return
    while True:
        try:
            feed.connect()
            for symbol, alias in SYMBOLS:
                off = a.utc_offset if a.utc_offset is not None else feed.offset_for(symbol)
                feed.offset = off
                if a.backfill:
                    feed.backfill(alias, symbol, rates_to_bars(feed.rates(symbol, days=a.backfill), off), a.backfill)
                else:
                    feed.push(alias, symbol, rates_to_bars(feed.rates(symbol, count=max(BAR_COUNT, SESSION_DAYS * 300)), off))
        except Exception as exc:                                     # 任何錯誤都不讓守護進程死掉
            log(f"🔴 {exc}（{PUSH_INTERVAL_SEC} 秒後重試）")
            if feed.mt5:
                try:
                    feed.mt5.shutdown()
                except Exception:
                    pass
                feed.mt5 = None
        if a.once or a.backfill:
            break
        time.sleep(PUSH_INTERVAL_SEC)


if __name__ == "__main__":
    main()
