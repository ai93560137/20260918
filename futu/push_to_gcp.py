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

[v4] 每日日線抽樣（數據品質比對用）：
  每天香港時間 16:30–21:00（港股已收市、美股未開市）讀預設分支的
  data/external/qc/futu_sample.txt（錨點＋昨天有爭議的代號＋隨機抽樣），
  每個代號抓最近 FUTU_DAILY_BARS 根日 K 推到 GCP，隔天由 external_qc.py 對照網站數據。
  關掉：setx FUTU_DAILY 0。清單讀不到就只抓錨點 HK.800000、US.SPY、US.QQQ。

執行：
  python push_to_gcp.py                  # 常駐
  python push_to_gcp.py --once           # 只推一次，用來測試
  python push_to_gcp.py --once --daily   # 立刻跑一次日線抽樣（不看時段），用來測試
"""
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import futu as ft
import requests

SCRIPT_VERSION = "4"
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
DAILY_MAX_CODES = 60                                 # 訂閱額度 100，留給 5 分 K
DAILY_ANCHORS = ["HK.800000", "US.SPY", "US.QQQ"]
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


class FutuPusher:
    def __init__(self):
        self.ctx = None
        self.subscribed = set()
        self.daily_done = None                        # 已完成日線抽樣的香港日期
        self.pending_unsub = []                       # [(訂閱時間, [代號…])]

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
    def fetch_bars(self, symbol):
        if symbol not in self.subscribed:
            ret, err = self.ctx.subscribe([symbol], [SUBTYPE], subscribe_push=False)
            if ret == ft.RET_OK:
                self.subscribed.add(symbol)
            else:
                log(f"  ⚠️ 訂閱 {symbol} 5 分 K 失敗：{err}；改用歷史 K 線")
        if symbol in self.subscribed:
            ret, df = self.ctx.get_cur_kline(symbol, num=BAR_COUNT, ktype=KTYPE)
        else:
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            end = datetime.now().strftime("%Y-%m-%d")
            ret, df, _ = self.ctx.request_history_kline(symbol, start=start, end=end,
                                                        ktype=KTYPE, max_count=None)
        if ret != ft.RET_OK:
            raise RuntimeError(f"K 線取得失敗：{df}")
        df = df.sort_values("time_key").tail(BAR_COUNT)
        return [{"time_key": str(row["time_key"]), "open": num(row["open"]), "high": num(row["high"]),
                 "low": num(row["low"]), "close": num(row["close"]), "volume": num(row["volume"])}
                for _, row in df.iterrows()]

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
            log(f"  ⚠️ 讀不到抽樣清單（{exc}），只抓錨點")
            codes = []
        return list(dict.fromkeys(DAILY_ANCHORS + codes))[:DAILY_MAX_CODES]

    def maybe_run_daily(self, force=False):
        now_hk = datetime.now(HK_TZ)
        minute = now_hk.hour * 60 + now_hk.minute
        today = now_hk.strftime("%Y-%m-%d")
        if not force and (self.daily_done == today or not DAILY_WINDOW_MIN[0] <= minute < DAILY_WINDOW_MIN[1]):
            return True
        codes = self.load_sample()
        log(f"📅 日線抽樣：{len(codes)} 個代號，每個最近 {DAILY_BARS} 根日 K")
        try:
            self.connect()
        except Exception as exc:
            log(f"🔴 日線抽樣連不上 OpenD：{exc}")
            return False
        subscribed, ok, failed = [], 0, []
        for code in codes:
            ret, err = self.ctx.subscribe([code], [ft.SubType.K_DAY], subscribe_push=False)
            if ret != ft.RET_OK:
                failed.append(f"{code}（訂閱：{str(err)[:60]}）")
                continue
            subscribed.append(code)
            ret, df = self.ctx.get_cur_kline(code, num=DAILY_BARS, ktype=ft.KLType.K_DAY)
            if ret != ft.RET_OK or df.empty:
                failed.append(f"{code}（日 K：{str(df)[:60]}）")
                continue
            df = df.sort_values("time_key")
            bars = [{"time_key": str(row["time_key"]), "open": num(row["open"]), "high": num(row["high"]),
                     "low": num(row["low"]), "close": num(row["close"]), "volume": num(row["volume"])}
                    for _, row in df.iterrows()]
            if self.post({"action": "futu_data", "token": TOKEN, "source": "futu_opend",
                          "script_version": SCRIPT_VERSION, "symbol": code, "kline_type": "K_DAY",
                          "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                          "data": bars, "options": []}, quiet=True):
                ok += 1
            else:
                failed.append(f"{code}（推送失敗）")
        if subscribed:
            self.pending_unsub.append((time.time(), subscribed))
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

    def run_symbol(self, symbol):
        log(f"向 OpenD {OPEND_HOST}:{OPEND_PORT} 取 {symbol} 行情…")
        try:
            self.connect()
            bars = self.fetch_bars(symbol)
            spot = bars[-1]["close"] if bars else None
            log(f"  K 線 {len(bars)} 根，最新 {bars[-1]['time_key'] if bars else '—'}（美東）收 {spot}")
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


def main():
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
