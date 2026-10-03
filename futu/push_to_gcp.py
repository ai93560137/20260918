"""Futu OpenD → GCP 行情推送守護進程（R94，對應 main.py 的 action=futu_data）

在裝有 Futu OpenD 的電腦上執行。每 PUSH_INTERVAL_SEC 秒：
  1. 取最新 BAR_COUNT 根 5 分 K（訂閱後 get_cur_kline；訂閱失敗才退回歷史 K 線）
  2. 取最近到期日、最接近現價的幾檔 Call / Put 的 IV 與 Greeks
  3. POST 到 GCP，只有回 HTTP 200 且 status == "stored" 才算成功

舊版的三個問題（這版都改掉了）：
  * request_history_kline(start='2026-09-01', max_count=10) 從 9/1 往後取，
    拿到的是 9/1 開盤的 10 根，不是最新的；「最新收盤價」其實是舊價格。
  * 快照的 IV 欄位叫 option_implied_volatility，舊版讀 implied_volatility，
    欄位不存在 → 每一檔都送 0。
  * GCP 回 200 + status "ignored"（沒有處理器）也印「大滿貫成功」。

設定（這個 repo 是公開的，網址與權杖不要寫進檔案）：
  Windows（設一次，重開命令列生效）：
    setx ZHUGE_GCP_URL "https://你的服務.run.app/"
    setx WEBHOOK_SECRET_TOKEN "跟 Cloud Run 環境變數相同的權杖"
  選填：FUTU_SYMBOLS（逗號分隔，預設 US.QQQ；例 US.QQQ,US.SPY,HK.800000）、
        OPEND_HOST（127.0.0.1）、OPEND_PORT（11111）、
        PUSH_INTERVAL_SEC（300）、BAR_COUNT（120）、ATM_STRIKES（2 → 每邊 5 檔）

[v4／v5] 每日日線抽樣（數據品質比對用，SOP 第三節）：
  每天香港時間 16:30–21:00（港股已收市、美股未開市）讀預設分支的
  data/external/qc/futu_sample.txt（已排好優先順序：錨點 → 昨天的爭議代號 → 隨機），
  取前 FUTU_DAILY_MAX 個，每個抓最近 FUTU_DAILY_BARS 根日 K 推到 GCP，隔天由 external_qc.py 對照網站數據。
  訂閱額度只有 100：每批 FUTU_DAILY_BATCH 個，訂滿 70 秒退訂再換下一批，所以 FUTU_DAILY_MAX 可以開到幾百。

  要抓多少、抓什麼，只改這台電腦的環境變數（改完重開命令列、重啟腳本）：
    setx FUTU_DAILY_MAX 200                      # 每天抽樣幾個代號（預設 60，上限 1000）
    setx FUTU_DAILY_EXTRA "US.IWM,US.DIA"        # 每天一定要抓的代號（排在最前面，不佔 MAX）
    setx FUTU_DAILY_BARS 20                      # 每個代號抓幾根日 K（預設 20）
    setx FUTU_DAILY 0                            # 關掉日線抽樣
  清單讀不到就只抓錨點 HK.800000、US.SPY、US.QQQ 和 FUTU_DAILY_EXTRA。

[v6] 即月期貨（最後交易日當天轉下月）：
  FUTU_SYMBOLS 放 HK.HSI_FRONT（也可 HK.MHI_FRONT、HK.HHI_FRONT），例如
    setx FUTU_SYMBOLS "US.QQQ,HK.800000,HK.HSI_FRONT"
  每天第一輪向 Futu 查港股期貨清單，取「最後交易日在今天之後」最近的一張月份合約
  （例 HK.HSI2610）；最後交易日當天（香港日期）起就改取下月。
  5 分 K 與日 K 都用固定代號 HK.HSI_FRONT 推上 GCP，封存成一條連續序列；
  轉月後只送轉月日（上一張的最後交易日）以後的 K 線，不會蓋掉前幾天舊合約的封存。
  實際合約代號記在快照的 source（futu_opend:HK.HSI2610）。期貨不取期權（恒指期權看 HK.800000）。
  日期以 Futu 的 time_key（香港時間）為準；夜市 17:15 後的 5 分 K 算當天日期。

執行：
  python push_to_gcp.py                  # 常駐
  python push_to_gcp.py --once           # 只推一次，用來測試
  python push_to_gcp.py --once --daily   # 立刻跑一次日線抽樣（不看時段），用來測試
  python push_to_gcp.py --search 波幅    # 查指數代號（例如 VHSI），不推送、不需設 GCP 網址
  python push_to_gcp.py --futures HSI    # 列出 HSI 期貨合約與最後交易日、今天的即月是哪張，不推送
"""
import math
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import futu as ft
import requests

SCRIPT_VERSION = "6"
GCP_URL = os.environ.get("ZHUGE_GCP_URL", "").strip()
TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN", "").strip()
# [v3] 多代號：改這個環境變數就能決定 Futu 取哪些商品，不用改程式。
SYMBOLS = [x.strip().upper() for x in
           (os.environ.get("FUTU_SYMBOLS") or os.environ.get("FUTU_SYMBOL") or "US.QQQ").split(",")
           if x.strip()]
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1").strip()
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))
INTERVAL_SEC = max(60, int(os.environ.get("PUSH_INTERVAL_SEC", "300")))
BAR_COUNT = max(10, min(1000, int(os.environ.get("BAR_COUNT", "120"))))
ATM_STRIKES = max(0, int(os.environ.get("ATM_STRIKES", "2")))
KTYPE = ft.KLType.K_5M
SUBTYPE = ft.SubType.K_5M
HTTP_TIMEOUT_SEC = 20

# [v4] 每日日線抽樣
HK_TZ = ZoneInfo("Asia/Hong_Kong")
DAILY_ENABLED = os.environ.get("FUTU_DAILY", "1").strip() != "0"
DAILY_WINDOW_MIN = (16 * 60 + 30, 21 * 60)          # 香港時間 16:30–21:00
DAILY_BARS = max(5, min(100, int(os.environ.get("FUTU_DAILY_BARS", "20"))))
DAILY_MAX = max(1, min(1000, int(os.environ.get("FUTU_DAILY_MAX", "60"))))
FRONT_RE = re.compile(r"^HK\.([A-Z]{2,4})_FRONT$")   # [v6] 即月期貨別名，例 HK.HSI_FRONT
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUBS_USED = len(SYMBOLS) + sum(1 for x in SYMBOLS if FRONT_RE.match(x))   # 即月期貨多訂一個日 K
DAILY_BATCH = max(5, min(100 - SUBS_USED - 5, int(os.environ.get("FUTU_DAILY_BATCH", "50"))))   # 訂閱額度 100
DAILY_ANCHORS = ["HK.800000", "US.SPY", "US.QQQ"]
DAILY_EXTRA = [x.strip().upper() for x in os.environ.get("FUTU_DAILY_EXTRA", "").split(",") if x.strip()]
SAMPLE_URL = os.environ.get(
    "FUTU_SAMPLE_URL",
    "https://raw.githubusercontent.com/ai93560137/20260918/refs/heads/"
    "claude/gcp-trading-v12-rewrite-bz75t2/data/external/qc/futu_sample.txt")
UNSUB_AFTER_SEC = 70                                  # Futu 規定訂閱滿 1 分鐘才能退訂
CODE_RE = re.compile(r"^(US|HK)\.[A-Z0-9][A-Z0-9.]{0,11}$")


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def num(value):
    """pandas / numpy 數值 → float；NaN、inf、無法轉換 → None（JSON 才合法）。"""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


# ---- [v6] 即月期貨 --------------------------------------------------------
def month_contracts(rows, product):
    """Futu 港股期貨清單 [(代號, last_trade_time)] → 該產品的月份合約 [(最後交易日, 代號)]，依日期排序。
    主連（HK.HSImain）等沒有最後交易日的代號會被略過。"""
    pattern = re.compile(rf"^HK\.{re.escape(product)}\d{{4}}$")
    out = []
    for code, last_trade in rows:
        digits = re.sub(r"\D", "", str(last_trade or ""))[:8]          # 2026-10-29／20261029／帶時間都接受
        code, last_trade = str(code), f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        if pattern.match(code) and len(digits) == 8 and DATE_RE.match(last_trade):
            out.append((last_trade, code))
    return sorted(set(out))


def pick_front(contracts, today):
    """即月 = 最後交易日「在今天之後」最近的一張；最後交易日當天就轉下月。
    回 (代號, 最後交易日, 上一張的最後交易日或 None)；找不到 → (None, None, None)。"""
    for i, (last_trade, code) in enumerate(contracts):
        if last_trade > today:
            prev = contracts[i - 1] if i > 0 else None
            prev_ok = prev is not None and prev_month(prev[1], 0) == prev_month(code)   # 必須正好是上個月那張
            return code, last_trade, (prev[0] if prev_ok else None)
    return None, None, None


def prev_month(code, back=1):
    """HK.HSI2610 → (2026, 9)：上一個月份合約的年月；back=0 → 合約本身的年月。"""
    year, month = 2000 + int(code[-4:-2]), int(code[-2:]) - back
    return (year, month) if month >= 1 else (year - 1, month + 12)


def bars_from_df(df):
    return [{"time_key": str(row["time_key"]), "open": num(row["open"]), "high": num(row["high"]),
             "low": num(row["low"]), "close": num(row["close"]), "volume": num(row["volume"])}
            for _, row in df.iterrows()]


class FutuPusher:
    def __init__(self):
        self.ctx = None
        self.subscribed = set()
        self.daily_done = None                        # 已完成日線抽樣的香港日期
        self.pending_unsub = []                       # [(訂閱時間, [代號…])]
        self.front = {}                               # [v6] 別名 → {day, code, last_trade, start}

    def connect(self):
        if self.ctx is None:
            self.ctx = ft.OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
            self.subscribed = set()
            self.pending_unsub = []

    def close(self):
        if self.ctx is not None:
            try:
                self.ctx.close()
            finally:
                self.ctx = None
                self.subscribed = set()
                self.pending_unsub = []

    # ---- K 線 -------------------------------------------------------------
    def fetch_bars(self, symbol, ktype=KTYPE, subtype=SUBTYPE, count=BAR_COUNT):
        if (symbol, subtype) not in self.subscribed:
            ret, err = self.ctx.subscribe([symbol], [subtype], subscribe_push=False)
            if ret == ft.RET_OK:
                self.subscribed.add((symbol, subtype))
            else:
                log(f"  ⚠️ 訂閱 {symbol} {subtype} 失敗：{err}；改用歷史 K 線")
        if (symbol, subtype) in self.subscribed:
            ret, df = self.ctx.get_cur_kline(symbol, num=count, ktype=ktype)
        else:
            days = 7 if ktype == KTYPE else count * 2 + 10
            start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            ret, df, _ = self.ctx.request_history_kline(symbol, start=start, end=end,
                                                        ktype=ktype, max_count=None)
        if ret != ft.RET_OK:
            raise RuntimeError(f"K 線取得失敗：{df}")
        return bars_from_df(df.sort_values("time_key").tail(count))

    # ---- 期權 -------------------------------------------------------------
    def fetch_options(self, symbol, spot):
        today = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        ret, chain = self.ctx.get_option_chain(code=symbol, start=today, end=end)
        if ret != ft.RET_OK:
            raise RuntimeError(f"期權鏈取得失敗：{chain}")
        if chain.empty:
            return []
        expiries = sorted(str(x)[:10] for x in chain["strike_time"].unique())
        later = [x for x in expiries if x > today]             # 當天到期的 IV 失真，優先用下一個
        expiry = (later or expiries)[0]
        chain = chain[chain["strike_time"].astype(str).str[:10] == expiry]
        strikes = sorted(chain["strike_price"].unique(), key=lambda k: abs(float(k) - spot))
        keep = set(strikes[:ATM_STRIKES * 2 + 1])
        chain = chain[chain["strike_price"].isin(keep)].sort_values(["option_type", "strike_price"])
        if chain.empty:
            return []
        meta = {row["code"]: row for _, row in chain.iterrows()}
        ret, snap = self.ctx.get_market_snapshot(list(meta))
        if ret != ft.RET_OK:
            raise RuntimeError(f"期權快照取得失敗：{snap}")
        options = []
        for _, row in snap.iterrows():
            info = meta.get(row["code"])
            if info is None:
                continue
            options.append({
                "code": row["code"],
                "option_type": str(info["option_type"]),          # CALL / PUT
                "expiry": expiry,
                "strike": num(info["strike_price"]),
                "iv": num(row.get("option_implied_volatility")),  # 百分比：20 = 20%
                "delta": num(row.get("option_delta")),
                "gamma": num(row.get("option_gamma")),
                "vega": num(row.get("option_vega")),
                "theta": num(row.get("option_theta")),
                "last": num(row.get("last_price")),
                "bid": num(row.get("bid_price")),
                "ask": num(row.get("ask_price")),
                "volume": num(row.get("volume")),
                "open_interest": num(row.get("option_open_interest")),
            })
        return options

    # ---- 一輪 -------------------------------------------------------------
    def run_once(self, force_daily=False):
        """每個代號各推一包；全部成功才回 True。之後視時段跑日線抽樣、退掉過期的日線訂閱。"""
        results = [self.run_symbol(symbol) for symbol in SYMBOLS]
        if DAILY_ENABLED or force_daily:
            results.append(self.maybe_run_daily(force_daily))
        self.release_daily_subs()
        return all(results)

    # ---- [v4] 每日日線抽樣 ------------------------------------------------
    @staticmethod
    def load_sample():
        try:
            resp = requests.get(SAMPLE_URL, timeout=HTTP_TIMEOUT_SEC)
            resp.raise_for_status()
            text = resp.content.decode("utf-8", errors="replace")     # 不靠伺服器宣告的編碼
            lines = [line.strip() for line in text.split("\n")]
            codes = [line.upper() for line in lines if line and not line.startswith("#")]
            bad = [c for c in codes if not CODE_RE.match(c)]
            if bad:
                log(f"  ⚠️ 抽樣清單有 {len(bad)} 行不像代號，已略過：{bad[:3]}")
            codes = [c for c in codes if CODE_RE.match(c)]
        except requests.RequestException as exc:
            log(f"  ⚠️ 讀不到抽樣清單（{exc}），只抓錨點與 FUTU_DAILY_EXTRA")
            codes = []
        fixed = list(dict.fromkeys(DAILY_ANCHORS + [c for c in DAILY_EXTRA if CODE_RE.match(c)]))
        rest = [c for c in dict.fromkeys(codes) if c not in fixed]
        return fixed + rest[:DAILY_MAX]

    def maybe_run_daily(self, force=False):
        now_hk = datetime.now(HK_TZ)
        minute = now_hk.hour * 60 + now_hk.minute
        today = now_hk.strftime("%Y-%m-%d")
        if not force and (self.daily_done == today or not DAILY_WINDOW_MIN[0] <= minute < DAILY_WINDOW_MIN[1]):
            return True
        codes = self.load_sample()
        batches = [codes[i:i + DAILY_BATCH] for i in range(0, len(codes), DAILY_BATCH)]
        log(f"📅 日線抽樣：{len(codes)} 個代號，分 {len(batches)} 批（每批 ≤ {DAILY_BATCH}），每個最近 {DAILY_BARS} 根日 K")
        try:
            self.connect()
        except Exception as exc:
            log(f"🔴 日線抽樣連不上 OpenD：{exc}")
            return False
        ok, failed, done = 0, [], 0
        for n, batch in enumerate(batches, 1):
            now_min = datetime.now(HK_TZ).hour * 60 + datetime.now(HK_TZ).minute
            if not force and now_min >= DAILY_WINDOW_MIN[1]:
                log(f"  ⏹️ 已過香港時間 21:00（美股快開市），剩下 {len(codes) - done} 個代號明天再抓")
                break
            started, subscribed = time.time(), []
            for code in batch:
                done += 1
                ret, err = self.ctx.subscribe([code], [ft.SubType.K_DAY], subscribe_push=False)
                if ret != ft.RET_OK:
                    failed.append(f"{code}（訂閱：{str(err)[:60]}）")
                    continue
                subscribed.append(code)
                ret, df = self.ctx.get_cur_kline(code, num=DAILY_BARS, ktype=ft.KLType.K_DAY)
                if ret != ft.RET_OK or df.empty:
                    failed.append(f"{code}（日 K：{str(df)[:60]}）")
                    continue
                bars = bars_from_df(df.sort_values("time_key"))
                if self.post({"action": "futu_data", "token": TOKEN, "source": "futu_opend",
                              "script_version": SCRIPT_VERSION, "symbol": code, "kline_type": "K_DAY",
                              "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                              "data": bars, "options": []}, quiet=True):
                    ok += 1
                else:
                    failed.append(f"{code}（推送失敗）")
            if not subscribed:
                continue
            if n < len(batches):                      # 還有下一批：等滿 70 秒退訂，把額度讓出來
                wait = UNSUB_AFTER_SEC - (time.time() - started)
                if wait > 0:
                    log(f"  ⏳ 第 {n}/{len(batches)} 批完成，等 {int(wait)} 秒退訂再抓下一批")
                    time.sleep(wait)
                ret, err = self.ctx.unsubscribe(subscribed, [ft.SubType.K_DAY])
                if ret != ft.RET_OK:
                    log(f"  ⚠️ 第 {n} 批退訂失敗：{err}；停止，剩下的明天再抓")
                    self.pending_unsub.append((started, subscribed))
                    break
            else:
                self.pending_unsub.append((started, subscribed))
        log(f"📅 日線抽樣完成：成功 {ok}／{len(codes)}"
            + (f"；失敗：{'、'.join(failed[:8])}" + ("…" if len(failed) > 8 else "") if failed else ""))
        if ok:
            self.daily_done = today
        return not failed

    def release_daily_subs(self):
        if self.ctx is None:
            return
        keep = []
        for started, codes in self.pending_unsub:
            if time.time() - started < UNSUB_AFTER_SEC:
                keep.append((started, codes))
                continue
            ret, err = self.ctx.unsubscribe(codes, [ft.SubType.K_DAY])
            if ret != ft.RET_OK:
                log(f"  ⚠️ 日線退訂失敗（下一輪再試）：{err}")
                keep.append((started, codes))
        self.pending_unsub = keep

    # ---- [v6] 即月期貨 -----------------------------------------------------
    def last_trading_day_before_month_end(self, year, month):
        """港交所月份合約的最後交易日 = 該月倒數第二個港股交易日。"""
        first = date(year, month, 1)
        last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        ret, days = self.ctx.request_trading_days(market=ft.TradeDateMarket.HK,
                                                  start=first.isoformat(), end=last.isoformat())
        if ret != ft.RET_OK:
            raise RuntimeError(f"交易日曆取得失敗：{days}")
        dates = sorted(str(d.get("time", ""))[:10] for d in days)
        if len(dates) < 2:
            raise RuntimeError(f"{year}-{month:02d} 交易日不足兩天")
        return dates[-2]

    def resolve_front(self, alias):
        """每個香港日期查一次：即月合約、它的最後交易日、可以送的最早 K 線日期（轉月日）。"""
        today = datetime.now(HK_TZ).strftime("%Y-%m-%d")
        cached = self.front.get(alias)
        if cached and cached["day"] == today:
            return cached
        product = FRONT_RE.match(alias).group(1)
        ret, df = self.ctx.get_stock_basicinfo(ft.Market.HK, ft.SecurityType.FUTURE)
        if ret != ft.RET_OK:
            raise RuntimeError(f"港股期貨清單取得失敗：{df}")
        contracts = month_contracts(zip(df["code"], df["last_trade_time"]), product)
        code, last_trade, prev_last = pick_front(contracts, today)
        if code is None:
            seen = [c for c in df["code"].astype(str) if c.startswith(f"HK.{product}")][:8]
            raise RuntimeError(f"找不到 {product} 的即月合約（Futu 列出的：{seen or '無'}）")
        if prev_last is None:                          # 上一張已下架：用交易日曆推它的最後交易日
            try:
                prev_last = self.last_trading_day_before_month_end(*prev_month(code))
            except Exception as exc:                   # 推不出來就只送今天的 K 線，最保守
                log(f"  ⚠️ 推算轉月日失敗（{exc}），只送今天的 K 線")
        start = prev_last if prev_last and prev_last <= today else today
        info = {"day": today, "code": code, "last_trade": last_trade, "start": start}
        old = cached["code"] if cached else None
        if old != code:
            log(f"  🔁 {alias} → {code}（最後交易日 {last_trade}；K 線從 {start} 起算）"
                + (f"，由 {old} 轉月" if old else ""))
            if old:
                self.drop_subscriptions(old)
        self.front[alias] = info
        return info

    def drop_subscriptions(self, code):
        subs = [s for c, s in self.subscribed if c == code]
        if not subs:
            return
        ret, err = self.ctx.unsubscribe([code], subs)
        if ret == ft.RET_OK:
            self.subscribed -= {(code, s) for s in subs}
        else:
            log(f"  ⚠️ 舊合約 {code} 退訂失敗（不影響推送）：{err}")

    def run_front(self, alias):
        log(f"向 OpenD {OPEND_HOST}:{OPEND_PORT} 取 {alias}（即月期貨）行情…")
        try:
            self.connect()
            info = self.resolve_front(alias)
            code, start = info["code"], info["start"]
            bars = [b for b in self.fetch_bars(code) if b["time_key"][:10] >= start]
            days = [b for b in self.fetch_bars(code, ft.KLType.K_DAY, ft.SubType.K_DAY, DAILY_BARS)
                    if b["time_key"][:10] >= start]
        except Exception as exc:
            log(f"🔴 OpenD 取數失敗：{exc}（下一輪重新連線）")
            self.close()
            return False
        log(f"  {code}：5 分 K {len(bars)} 根，最新 {bars[-1]['time_key'] if bars else '—'}（香港）"
            f"收 {bars[-1]['close'] if bars else '—'}；日 K {len(days)} 根")
        if not bars and not days:
            log("  ℹ️ 轉月後還沒有 K 線，下一輪再推")
            return True
        base = {"action": "futu_data", "token": TOKEN, "source": f"futu_opend:{code}",
                "script_version": SCRIPT_VERSION, "symbol": alias, "options": []}
        ok = True
        if bars:
            ok = self.post({**base, "kline_type": "K_5M", "data": bars,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        if days:
            ok = self.post({**base, "kline_type": "K_DAY", "data": days,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, quiet=True) and ok
        return ok

    def run_symbol(self, symbol):
        if FRONT_RE.match(symbol):
            return self.run_front(symbol)
        log(f"向 OpenD {OPEND_HOST}:{OPEND_PORT} 取 {symbol} 行情…")
        try:
            self.connect()
            bars = self.fetch_bars(symbol)
            spot = bars[-1]["close"] if bars else None
            log(f"  K 線 {len(bars)} 根，最新 {bars[-1]['time_key'] if bars else '—'}（交易所時間）收 {spot}")
            options = []
            if spot is not None:
                try:
                    options = self.fetch_options(symbol, spot)
                    ivs = [o["iv"] for o in options if o["iv"]]
                    log(f"  期權 {len(options)} 檔，IV 有值 {len(ivs)} 檔"
                        + (f"，範圍 {min(ivs):.2f}%～{max(ivs):.2f}%" if ivs else ""))
                except Exception as exc:                    # 期權失敗不擋 K 線
                    log(f"  ⚠️ 期權略過：{exc}")
        except Exception as exc:
            log(f"🔴 OpenD 取數失敗：{exc}（下一輪重新連線）")
            self.close()
            return False

        return self.post({"action": "futu_data", "token": TOKEN, "source": "futu_opend",
                  "script_version": SCRIPT_VERSION, "symbol": symbol, "kline_type": "K_5M",
                  "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "data": bars, "options": options})

    def post(self, packet, quiet=False):
        try:
            response = requests.post(GCP_URL, json=packet, timeout=HTTP_TIMEOUT_SEC)
        except requests.RequestException as exc:
            log(f"🔴 推送失敗（網路）：{exc}")
            return False
        try:
            body = response.json()
        except ValueError:
            body = {}
        status = body.get("status") if isinstance(body, dict) else None
        if response.status_code == 200 and status == "stored":
            if quiet:
                return True
            log(f"✅ GCP 已存檔：K 線 {body.get('bars')} 根，最新 {body.get('latest_time')} "
                f"收 {body.get('latest_close')}，IV {body.get('iv_count')}/{body.get('options')} 檔")
            for warning in body.get("warnings") or []:
                log(f"  ⚠️ GCP 提醒：{warning}")
            return True
        if response.status_code == 200 and status == "ignored":
            log("❌ GCP 回 ignored：雲端還是舊版 main.py，沒有 futu_data 處理器 → 請部署 R94。")
        elif response.status_code == 403:
            log("❌ 權杖被拒：WEBHOOK_SECRET_TOKEN 跟 Cloud Run 上的不一樣。")
        else:
            log(f"❌ 推送被拒：HTTP {response.status_code} {response.text[:300]}")
        return False


def search(keyword):
    """列出名稱或代號含關鍵字的港股、美股指數，例如 --search 波幅 找 VHSI。只讀，不推送。"""
    ctx = ft.OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        for market in (ft.Market.HK, ft.Market.US):
            ret, df = ctx.get_stock_basicinfo(market, ft.SecurityType.IDX)
            if ret != ft.RET_OK:
                print(f"{market}：查不到（{str(df)[:80]}）")
                continue
            hits = df[df["name"].astype(str).str.contains(keyword, case=False, regex=False)
                      | df["code"].astype(str).str.contains(keyword, case=False, regex=False)]
            print(f"{market}：{len(hits)} 筆")
            for _, row in hits.head(50).iterrows():
                print(f"  {row['code']}\t{row['name']}")
    finally:
        ctx.close()
    return 0


def futures(product):
    """列出港股期貨裡 <product> 的合約、最後交易日，以及今天的即月。只讀，不推送。"""
    product = product.strip().upper() or "HSI"
    ctx = ft.OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        ret, df = ctx.get_stock_basicinfo(ft.Market.HK, ft.SecurityType.FUTURE)
        if ret != ft.RET_OK:
            print(f"查不到港股期貨清單：{str(df)[:120]}")
            return 1
        hits = df[df["code"].astype(str).str.startswith(f"HK.{product}")]
        for _, row in hits.iterrows():
            print(f"  {row['code']}\t最後交易日 {str(row.get('last_trade_time') or '—')[:10]}\t{row.get('name', '')}")
        today = datetime.now(HK_TZ).strftime("%Y-%m-%d")
        code, last_trade, _ = pick_front(month_contracts(zip(df["code"], df["last_trade_time"]), product), today)
        print(f"今天（{today}）的即月：{code or '找不到'}" + (f"，最後交易日 {last_trade}" if code else ""))
    finally:
        ctx.close()
    return 0


def main():
    if "--futures" in sys.argv[1:]:
        idx = sys.argv.index("--futures")
        return futures(sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "HSI")
    if "--search" in sys.argv[1:]:
        idx = sys.argv.index("--search")
        return search(sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "")
    if not GCP_URL or not TOKEN:
        print("請先設定環境變數 ZHUGE_GCP_URL 與 WEBHOOK_SECRET_TOKEN（見檔案開頭說明）。", file=sys.stderr)
        return 2
    once = "--once" in sys.argv[1:]
    force_daily = "--daily" in sys.argv[1:]
    pusher = FutuPusher()
    log(f"🚀 Futu 行情推送啟動（v{SCRIPT_VERSION}）：{', '.join(SYMBOLS)} → {GCP_URL}"
        + ("（只推一次）" if once else f"，每 {INTERVAL_SEC} 秒"))
    try:
        while True:
            ok = pusher.run_once(force_daily=force_daily)
            if once:
                if pusher.pending_unsub:                 # 測試模式：等滿 1 分鐘再退訂，不留訂閱
                    time.sleep(UNSUB_AFTER_SEC)
                    pusher.release_daily_subs()
                return 0 if ok else 1
            time.sleep(INTERVAL_SEC)
    except KeyboardInterrupt:
        log("收到 Ctrl+C，結束。")
        return 0
    finally:
        pusher.close()


if __name__ == "__main__":
    sys.exit(main())
