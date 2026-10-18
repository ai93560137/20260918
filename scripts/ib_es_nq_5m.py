#!/usr/bin/env python3
"""ib-data VM：用 IB 延遲歷史 K 線推 ES／NQ 前月 5 分 K 上 Cloud Run（只讀：唔落單、唔改單）。

取代使用者部機 futu/mt5_push.py 嘅 K_5M（MT5 SP500ft／NAS100ft 同 CME 對唔上，10-16 實測 ES 低位差 60 點）。
封包同 mt5_push 一樣：action=futu_data、kline_type=K_5M、最近 BAR_COUNT 根；
symbol US.ES_FRONT／US.NQ_FRONT，source "ib_delayed:ESZ6" 之類（ES／NQ 頁頂嘅 MT5 警告睇 source）。
time_key = 紐約時間嘅「收市時間」（"2026-10-16 15:55:00" 代表 15:50–15:55），用 IB K 線本身嘅時間，唔用 VM 時鐘；
只推 CME 交易時段（紐約前一日 18:00 至當日 17:00，週末唔推）。最後一根可能未完成，唔推，下一輪先推（休市超過 1 小時嗰陣就係已完成，照推）。
唔推 K_SESSION（日線由 GitHub Actions yfinance 推，R230）。

設定（使用者喺 VM 自己做，權杖唔好貼入對話）：沿用 ~/zhuge/env（ZHUGE_GCP_URL、WEBHOOK_SECRET_TOKEN，chmod 600）。
先試：  . ~/zhuge/env && python3 ~/zhuge/ib_es_nq_5m.py --dry        # 只印唔推
一次性補推最近 12 個交易日（main.PAPER_BOOT_DAYS；蓋走封存入面 MT5 嘅舊根）：
        . ~/zhuge/env && python3 ~/zhuge/ib_es_nq_5m.py --backfill-days 12 --dry   # 先睇
        . ~/zhuge/env && python3 ~/zhuge/ib_es_nq_5m.py --backfill-days 12         # 真推（舊到新分包，每包 ≤400 根）
crontab（UTC，每 5 分鐘，週日晚至週五）：
    */5 * * * 0-5  . $HOME/zhuge/env && python3 $HOME/zhuge/ib_es_nq_5m.py >> $HOME/zhuge/es_nq_5m.log 2>&1

clientId 55（VM 已用 17、23、24、31、41、53、54、77）。Gateway 每晚約 23:50 UTC 重啟：嗰幾輪連唔到會印錯誤，
之後一輪會用歷史 K 線補返中間嘅根。
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SCRIPT_VERSION = "ib5m-2"
NY = ZoneInfo("America/New_York")
UTC = timezone.utc
BAR_MINUTES = 5
BAR_COUNT = 120                         # 同 mt5_push.BAR_COUNT
DURATION = "36000 S"                    # 10 小時 = 120 根 5 分 K
ROLL_DAYS = 8                           # 到期（第三個星期五）前 8 日轉去下一季（CME 成交量大約嗰時轉）
QUARTER_MONTHS = (3, 6, 9, 12)
MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}
MARKETS = [("ES", "US.ES_FRONT"), ("NQ", "US.NQ_FRONT")]
HTTP_TIMEOUT_SEC = 60
CHUNK = 400                             # 每包最多幾根（main.FUTU_MAX_BARS 500；同 mt5_push.CHUNK）
CLOSED_AFTER = timedelta(minutes=60)    # 最後一根收市已過咗咁耐（休市／週末）→ 已完成，照推


# ---- 純函數（tests/test_ib_es_nq_5m.py 有測試） ----
def third_friday(y, m):
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(weeks=2)


def front_month(today, roll_days=ROLL_DAYS):
    """今日用邊張季月合約 → (年, 月)。到期日前 roll_days 日起轉去下一季。"""
    y, m = today.year, today.month
    for _ in range(6):
        qm = next((q for q in QUARTER_MONTHS if q >= m), None)
        if qm is None:
            y, m = y + 1, 1
            continue
        if today < third_friday(y, qm) - timedelta(days=roll_days):
            return y, qm
        y, m = (y + 1, 1) if qm == 12 else (y, qm + 1)
    raise ValueError(today)


def local_symbol(root, y, m):
    return f"{root}{MONTH_CODE[m]}{y % 10}"


def ny_close_key(bar_open_utc, minutes=BAR_MINUTES):
    """K 線開市時間（UTC，有時區）→ 紐約收市時間字串。"""
    t = bar_open_utc.astimezone(NY).replace(tzinfo=None) + timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def session_of(time_key):
    """紐約時間（收市）→ CME 交易日：18:00 起算下一天（同 futu/mt5_push.session_of）。"""
    t = datetime.strptime(time_key[:19], "%Y-%m-%d %H:%M:%S")
    return (t + timedelta(hours=6)).strftime("%Y-%m-%d")


def in_session(time_key):
    """排除週末同 17:00–18:00 休市（收市時間 17:00 嗰根屬當日最後一根）。同 futu/mt5_push.in_session。"""
    t = datetime.strptime(time_key[:19], "%Y-%m-%d %H:%M:%S")
    hm = t.strftime("%H:%M")
    if "17:00" < hm <= "18:00":
        return False
    return datetime.strptime(session_of(time_key), "%Y-%m-%d").weekday() < 5


def to_utc(d):
    """ib_insync 嘅 bar.date（formatDate=2 → 有時區 datetime）→ UTC。冇時區當 UTC。"""
    if isinstance(d, datetime):
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    raise ValueError(f"5 分 K 嘅時間唔係 datetime：{d!r}")


def bars_to_packet_data(bars, count=BAR_COUNT, now_utc=None):
    """IB BarData 列表 → 封包 data。最後一根可能未完成唔要（除非佢收市已過 CLOSED_AFTER，即係休市中）；
    去重、排序、只留交易時段、最近 count 根。"""
    rows = sorted(bars, key=lambda b: to_utc(b.date))
    if rows and (now_utc is None or to_utc(rows[-1].date) + timedelta(minutes=BAR_MINUTES) > now_utc - CLOSED_AFTER):
        rows = rows[:-1]
    out = {}
    for b in rows:
        tk = ny_close_key(to_utc(b.date))
        if not in_session(tk) or not b.close or b.close <= 0:
            continue
        vol = float(b.volume) if b.volume and b.volume > 0 else 1.0    # main.py 當 volume 0 係開市前佔位 K 線略過（同 mt5_push）
        out[tk] = {"time_key": tk, "open": float(b.open), "high": float(b.high), "low": float(b.low),
                   "close": float(b.close), "volume": vol}
    return [out[k] for k in sorted(out)][-count:]


def last_sessions(data, n):
    """只留最近 n 個 CME 交易日（session_of）嘅 K 線。"""
    keep = set(sorted({session_of(b["time_key"]) for b in data})[-n:])
    return [b for b in data if session_of(b["time_key"]) in keep]


def chunks(data, size=CHUNK):
    """舊到新分包：最後一包係最新，推完之後即時快照就係最新嗰包。"""
    return [data[i:i + size] for i in range(0, len(data), size)]


def ib_end(dt_utc):
    """reqHistoricalData 嘅 endDateTime（UTC 格式）。"""
    return dt_utc.strftime("%Y%m%d-%H:%M:%S")


def packet(token, alias, source, data):
    return {"action": "futu_data", "token": token, "symbol": alias, "kline_type": "K_5M",
            "source": source, "script_version": SCRIPT_VERSION, "data": data}


def post(url, body, timeout=HTTP_TIMEOUT_SEC):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=55)
    ap.add_argument("--dry", action="store_true", help="只印，唔推 Cloud Run")
    ap.add_argument("--only", choices=[r for r, _ in MARKETS], help="只做一個（試用）")
    ap.add_argument("--backfill-days", type=int, default=0,
                    help="一次性補推最近 N 個交易日（每次攞 1 星期、分包 ≤400 根推）；平時 cron 唔好用")
    a = ap.parse_args()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    url, tok = os.environ.get("ZHUGE_GCP_URL", "").strip(), os.environ.get("WEBHOOK_SECRET_TOKEN", "").strip()
    if not a.dry and (not url or not tok):
        print(now, "冇設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN（. ~/zhuge/env）")
        return 1
    from ib_insync import IB, Future
    ib = IB()
    errors = []
    ib.errorEvent += lambda req_id, code, msg, contract: errors.append(f"{code} {msg}")
    try:
        ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=20, readonly=True)
    except Exception as e:                      # noqa: BLE001  Gateway 重啟中（約 23:50 UTC）
        print(now, f"連唔到 IB Gateway：{e.__class__.__name__}")
        return 1
    ib.reqMarketDataType(3)                     # 冇訂閱 → 延遲行情
    y, m = front_month(datetime.now(NY).date())
    failed = 0
    for root, alias in MARKETS:
        if a.only and root != a.only:
            continue
        errors.clear()
        c = Future(root, f"{y}{m:02d}", "CME", currency="USD")
        try:
            if not ib.qualifyContracts(c):
                print(now, root, f"qualify 失敗 {y}{m:02d}；IB 訊息：{errors[-3:]}")
                failed += 1
                continue
            if a.backfill_days > 0:
                bars, end = [], ""
                for _ in range(a.backfill_days // 5 + 2):              # 每次 1 星期，向前行
                    got = ib.reqHistoricalData(c, endDateTime=end, durationStr="1 W", barSizeSetting="5 mins",
                                               whatToShow="TRADES", useRTH=False, formatDate=2, timeout=120)
                    if not got:
                        break
                    bars = list(got) + bars
                    end = ib_end(to_utc(min(b.date for b in got)))
            else:
                bars = ib.reqHistoricalData(c, endDateTime="", durationStr=DURATION, barSizeSetting="5 mins",
                                            whatToShow="TRADES", useRTH=False, formatDate=2, timeout=60)
        except Exception as e:                  # noqa: BLE001
            print(now, root, f"歷史 K 線例外 {e!r}；IB 訊息：{errors[-3:]}")
            failed += 1
            continue
        sym = c.localSymbol or local_symbol(root, y, m)
        if a.backfill_days > 0:
            data = last_sessions(bars_to_packet_data(bars or [], count=10 ** 6, now_utc=datetime.now(UTC)),
                                 a.backfill_days)
        else:
            data = bars_to_packet_data(bars or [], now_utc=datetime.now(UTC))
        if not data:
            print(now, root, sym, f"冇交易時段內嘅 5 分 K（IB 回 {len(bars or [])} 根；IB 訊息：{errors[-3:]}）")
            if not bars:
                failed += 1
            continue
        last = data[-1]
        print(now, f"{root} {sym} → {alias}：{len(data)} 根，紐約 {data[0]['time_key'][5:16]} → {last['time_key'][5:16]}，"
                   f"最新 O{last['open']} H{last['high']} L{last['low']} C{last['close']} V{last['volume']:.0f}")
        if a.dry:
            continue
        for part in chunks(data):
            try:
                res = post(url, packet(tok, alias, f"ib_delayed:{sym}", part))
                ok = res.get("status") == "stored"
                print(now, root, "推送：", res.get("status"), res.get("bars"), res.get("latest_time"))
                failed += 0 if ok else 1
            except Exception as e:              # noqa: BLE001  唔印網址同權杖
                print(now, root, f"推送失敗：{e.__class__.__name__}")
                failed += 1
    ib.disconnect()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
