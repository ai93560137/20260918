"""期權 IV 採集 → GCP（R178）：恒指、ES、NQ 的「本週／下週／月尾」三個到期日，每個到期日價平附近 10 檔行使價的 Call、Put。

在跑 Futu OpenD 的 Windows 電腦上執行（跟 push_to_gcp.py 同一台，另開一個視窗）。只讀報價：
只用 get_option_expiration_date / get_option_chain / get_market_snapshot，不落單、不解鎖交易。

每一輪：
  1. 取標的現價（恒指用指數 HK.800000；ES／NQ 用期貨主連，代號可用環境變數改）
  2. 列出到期日，挑三個：本週（本週最後一個、今天之後）、下週（下週最後一個）、月尾（本月最後一個；過了就下個月）
  3. 每個到期日取離現價最近的 STRIKES（預設 10）個行使價，Call、Put 都取 → 快照拿 IV、Delta、買賣價、未平倉
  4. POST 到 GCP：action=futu_data，代號用別名 HK.HSI_IV／US.ES_IV／US.NQ_IV（不會影響波幅頁與 push_to_gcp.py 的資料）。
     雲端已有處理器（R94）：最新一份存 futu/snapshots/<別名>.json，每一輪另存 archive/futu_options/<別名>/<日期>.json。

設定（這個 repo 是公開的，網址與權杖不要寫進檔案；跟 push_to_gcp.py 共用）：
    setx ZHUGE_GCP_URL "https://你的服務.run.app/"
    setx WEBHOOK_SECRET_TOKEN "跟 Cloud Run 環境變數相同的權杖"
  選填：IV_MARKETS（預設 HSI,ES,NQ）、IV_STRIKES（10）、IV_INTERVAL_SEC（1800，每 30 分鐘一輪）、
        IV_ES_UNDERLYINGS／IV_NQ_UNDERLYINGS（逗號分隔，逐個試；預設 US.ESmain,US.ES2612／US.NQmain,US.NQ2612）、
        OPEND_HOST（127.0.0.1）、OPEND_PORT（11111）

用法：
    python iv_push.py --probe        # 第一次先跑：只印找到的到期日、行使價與 IV，不推送
    python iv_push.py --once         # 推一輪就結束
    python iv_push.py                # 長跑：每 IV_INTERVAL_SEC 秒一輪；Ctrl+C 停

注意：
  * 美國期貨期權要有 CME 期權行情權限；沒有的話 IV 會是 0 或空，--probe 會標「⚠️ 沒有 IV」。
  * 權杖只放環境變數；日誌不印網址與權杖。
"""
import argparse, os, sys, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import futu as ft
import requests

SCRIPT_VERSION = "iv-1"
GCP_URL = os.environ.get("ZHUGE_GCP_URL", "").strip()
TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN", "").strip()
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1").strip()
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))
STRIKES = max(2, min(30, int(os.environ.get("IV_STRIKES", "10"))))
INTERVAL_SEC = max(300, int(os.environ.get("IV_INTERVAL_SEC", "1800")))
MARKETS_ON = [x.strip().upper() for x in os.environ.get("IV_MARKETS", "HSI,ES,NQ").split(",") if x.strip()]
HTTP_TIMEOUT_SEC = 30


def _codes(env, default):
    return [x.strip() for x in os.environ.get(env, default).split(",") if x.strip()]


MARKETS = {
    "HSI": {"alias": "HK.HSI_IV", "tz": ZoneInfo("Asia/Hong_Kong"), "underlyings": ["HK.800000"],
            "index_option_type": ft.IndexOptionType.NORMAL},
    "ES": {"alias": "US.ES_IV", "tz": ZoneInfo("America/New_York"),
           "underlyings": _codes("IV_ES_UNDERLYINGS", "US.ESmain,US.ES2612")},
    "NQ": {"alias": "US.NQ_IV", "tz": ZoneInfo("America/New_York"),
           "underlyings": _codes("IV_NQ_UNDERLYINGS", "US.NQmain,US.NQ2612")},
}


def log(message):
    print(f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {message}", flush=True)


def num(value):
    try:
        v = float(value)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def pick_expiries(expiries, today):
    """到期日清單（YYYY-MM-DD）→ {本週, 下週, 月尾}。今天到期的不要（IV 失真）。"""
    days = sorted({e for e in expiries if e > today.isoformat()})
    if not days:
        return {}
    monday = today - timedelta(days=today.weekday())
    this_end, next_end = monday + timedelta(days=6), monday + timedelta(days=13)
    out = {}
    this_week = [e for e in days if e <= this_end.isoformat()]
    if this_week:
        out["this_week"] = this_week[-1]                      # 本週最後一個（週五）
    next_week = [e for e in days if this_end.isoformat() < e <= next_end.isoformat()]
    if next_week:
        out["next_week"] = next_week[-1]                      # 下週最後一個（通常週五，對應方向一）
    ym = today.strftime("%Y-%m")
    month = [e for e in days if e[:7] == ym]
    if not month:
        nxt = (today.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
        month = [e for e in days if e[:7] == nxt]
    if month:
        out["month_end"] = month[-1]
    return out


class Collector:
    def __init__(self):
        self.ctx = None

    def connect(self):
        if self.ctx is None:
            self.ctx = ft.OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)

    def close(self):
        if self.ctx is not None:
            self.ctx.close()
            self.ctx = None

    def spot(self, code):
        ret, snap = self.ctx.get_market_snapshot([code])
        if ret != ft.RET_OK or snap.empty:
            return None
        row = snap.iloc[0]
        return num(row.get("last_price")) or num(row.get("prev_close_price"))

    def chain(self, code, start, end, kw):
        ret, ch = self.ctx.get_option_chain(code=code, start=start, end=end, **kw)
        if ret != ft.RET_OK:
            raise RuntimeError(str(ch)[:120])
        return ch

    def collect(self, key):
        """回傳 (別名, 標的代號, 現價, {標籤: 到期日}, 期權列) ；找不到就 raise。"""
        m = MARKETS[key]
        kw = {"index_option_type": m["index_option_type"]} if "index_option_type" in m else {}
        today = datetime.now(m["tz"]).date()
        errors = []
        for und in m["underlyings"]:
            try:
                spot = self.spot(und)
                if not spot:
                    errors.append(f"{und}：沒有現價")
                    continue
                ch = self.chain(und, today.isoformat(), (today + timedelta(days=45)).isoformat(), kw)
                if ch.empty:
                    errors.append(f"{und}：45 日內沒有期權鏈")
                    continue
                ch = ch.assign(_exp=ch["strike_time"].astype(str).str[:10])
                picks = pick_expiries(list(ch["_exp"].unique()), today)
                if not picks:
                    errors.append(f"{und}：沒有今天之後的到期日")
                    continue
                rows = []
                for label, exp in picks.items():
                    sub = ch[ch["_exp"] == exp]
                    strikes = sorted(sub["strike_price"].unique(), key=lambda k: abs(float(k) - spot))[:STRIKES]
                    sub = sub[sub["strike_price"].isin(set(strikes))]
                    rows += self.quote(sub, exp, label)
                return m["alias"], und, spot, picks, rows
            except Exception as exc:                            # 換下一個標的代號再試
                errors.append(f"{und}：{exc}")
        raise RuntimeError("；".join(errors) or "沒有標的代號")

    def quote(self, sub, exp, label):
        if sub.empty:
            return []
        meta = {r["code"]: r for _, r in sub.iterrows()}
        ret, snap = self.ctx.get_market_snapshot(list(meta))
        if ret != ft.RET_OK:
            raise RuntimeError(f"期權快照失敗：{str(snap)[:120]}")
        out = []
        for _, r in snap.iterrows():
            info = meta.get(r["code"])
            if info is None:
                continue
            out.append({"code": r["code"], "option_type": str(info["option_type"]).upper(), "expiry": exp,
                        "strike": num(info["strike_price"]),
                        "iv": num(r.get("option_implied_volatility")),
                        "delta": num(r.get("option_delta")), "gamma": num(r.get("option_gamma")),
                        "vega": num(r.get("option_vega")), "theta": num(r.get("option_theta")),
                        "last": num(r.get("last_price")), "bid": num(r.get("bid_price")), "ask": num(r.get("ask_price")),
                        "volume": num(r.get("volume")), "open_interest": num(r.get("option_open_interest")),
                        "label": label})
        return out


LABEL_ZH = {"this_week": "本週", "next_week": "下週", "month_end": "月尾"}


def atm_iv(rows, spot, exp):
    """該到期日離現價最近行使價的 Call、Put IV 平均（有值才算）。"""
    sub = [r for r in rows if r["expiry"] == exp and r.get("strike") is not None]
    if not sub:
        return None, None
    k = min({r["strike"] for r in sub}, key=lambda s: abs(s - spot))
    ivs = [r["iv"] for r in sub if r["strike"] == k and r.get("iv")]
    return k, (sum(ivs) / len(ivs) if ivs else None)


def summary(key, alias, und, spot, picks, rows):
    log(f"✅ {key}（{und} 現價 {spot:,.2f}）→ {alias}：{len(rows)} 張")
    for label, exp in picks.items():
        k, iv = atm_iv(rows, spot, exp)
        n = sum(1 for r in rows if r["expiry"] == exp)
        n_iv = sum(1 for r in rows if r["expiry"] == exp and r.get("iv"))
        ks = sorted({r["strike"] for r in rows if r["expiry"] == exp})
        log(f"   {LABEL_ZH[label]} {exp}：{n} 張（IV 有值 {n_iv}）行使價 {ks[0]:,.0f}–{ks[-1]:,.0f}；"
            + (f"價平 {k:,.0f} IV {iv:.2f}%" if iv else "⚠️ 沒有 IV（可能缺期權行情權限）"))


def post(alias, und, spot, rows):
    if not (GCP_URL and TOKEN):
        log("❌ 未設定 ZHUGE_GCP_URL 或 WEBHOOK_SECRET_TOKEN（見檔頭說明）")
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    packet = {"action": "futu_data", "token": TOKEN, "symbol": alias, "kline_type": "", "source": f"futu_opend:{und}",
              "script_version": SCRIPT_VERSION, "timestamp": now,
              "data": [{"time_key": now, "open": spot, "high": spot, "low": spot, "close": spot, "volume": 0}],
              "options": [{k: v for k, v in r.items() if k != "label"} for r in rows]}
    try:
        resp = requests.post(GCP_URL, json=packet, timeout=HTTP_TIMEOUT_SEC)
    except requests.RequestException as exc:
        log(f"🔴 推送失敗（網路）：{exc}")
        return False
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code == 200 and isinstance(body, dict) and body.get("status") == "stored":
        log(f"   📤 GCP 已存檔：{body.get('options')} 張，IV 有值 {body.get('iv_count')}")
        return True
    log("❌ 權杖被拒：WEBHOOK_SECRET_TOKEN 跟 Cloud Run 上的不一樣。" if resp.status_code == 403
        else f"❌ 推送被拒：HTTP {resp.status_code} {resp.text[:200]}")
    return False


def run_round(col, push):
    ok = True
    col.connect()
    for key in MARKETS_ON:
        if key not in MARKETS:
            log(f"⚠️ 不認識的市場 {key}（只支援 HSI、ES、NQ）")
            continue
        try:
            alias, und, spot, picks, rows = col.collect(key)
        except Exception as exc:
            log(f"❌ {key}：{exc}")
            ok = False
            continue
        summary(key, alias, und, spot, picks, rows)
        if push and rows:
            ok = post(alias, und, spot, rows) and ok
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--probe", action="store_true", help="只印找到的到期日、行使價與 IV，不推送")
    ap.add_argument("--once", action="store_true", help="推一輪就結束")
    args = ap.parse_args()
    log(f"期權 IV 採集 {SCRIPT_VERSION}：{','.join(MARKETS_ON)}，每個到期日 {STRIKES} 個行使價"
        + ("（只檢查，不推送）" if args.probe else ""))
    col = Collector()
    try:
        if args.probe or args.once:
            return 0 if run_round(col, push=not args.probe) else 1
        while True:
            try:
                run_round(col, push=True)
            except Exception as exc:                            # OpenD 斷線等：下一輪重連
                log(f"🔴 這一輪失敗：{exc}")
                col.close()
            log(f"⏳ {INTERVAL_SEC // 60} 分鐘後再取")
            time.sleep(INTERVAL_SEC)
    except KeyboardInterrupt:
        log("已停止")
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    sys.exit(main())
