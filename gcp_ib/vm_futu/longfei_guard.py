"""[R199] 龍飛陣 VM 守衛：風控階梯 → PAUSE＋通知，加 watchdog（Telegram）。只用標準庫，唔落單。

由 zhuge-longfei-guard.service 跑（每 30 秒一輪）。讀：
- ZHUGE_LADDER_FILE（auto_risk 每 10 分鐘寫「級別 day|night YYYY-MM-DD HH:MM [hard_stop]」）
- AI_DATA_DIR/heartbeat（hsi_ai_trader 每 5 秒寫 JSON：utc、qty、errors、halted、foreign_qty…）
使用者 2026-10-16 定：只有 Ⓑ 會放 AI_DATA_DIR/PAUSE（停開新倉）；Ⓒ／Ⓓ、硬止損、級別檔冇咗／讀唔到／
舊過 LADDER_MAX_AGE_MIN（30 分鐘，週末除外）**只發 Telegram 通知，唔放 STOP、唔平倉、唔停開新倉**。
guard 自己放嘅檔內容以「guard:」開頭；只會刪自己放嗰啲（包括舊版 guard 放過嘅 STOP），人手放嘅 STOP／PAUSE 唔郁。
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HKT = timezone(timedelta(hours=8))
DATA = Path(os.environ.get("AI_DATA_DIR") or "~/zhuge/ai_trader").expanduser()
# [R202] 龍飛陣多產品：HSI 用 DATA；LONGFEI_EXTRA_PRODUCTS（例如 SPY,QQQ,DIA）各用 DATA_<產品>（zhuge-longfei@<產品>.service）
EXTRA = [x.strip().upper() for x in os.environ.get("LONGFEI_EXTRA_PRODUCTS", "").split(",") if x.strip()]
DIRS = [("HSI", DATA)] + [(p, DATA.with_name(f"{DATA.name}_{p}")) for p in EXTRA]
# [R209] 真倉程式（zhuge-longfei-real@<產品>）：標籤「<產品>真倉」，資料 ~/zhuge/ai_trader_real_<產品>
REAL = [x.strip().upper() for x in os.environ.get("LONGFEI_REAL_PRODUCTS", "").split(",") if x.strip()]
DIRS += [(f"{p}真倉", DATA.with_name(f"{DATA.name}_real_{p}")) for p in REAL]
LADDER = Path(os.environ.get("ZHUGE_LADDER_FILE") or "~/zhuge/ladder_level").expanduser()
# [R205] 美股 ETF 喺證券戶口：LONGFEI_ETF_SEC_LADDER=1 先改跟證券戶口級別檔（轉真倉前、證券戶口入咗錢先開，RISK_LADDER §6b）；
# 未開就照舊跟期貨戶口（戶口級風控，全部產品一齊）
SEC_LADDER = Path(os.environ.get("ZHUGE_SEC_LADDER_FILE") or "~/zhuge/ladder_level_sec").expanduser()
ETF_SEC = os.environ.get("LONGFEI_ETF_SEC_LADDER", "").strip() == "1"
LADDER_MAX_AGE_MIN = float(os.environ.get("LADDER_MAX_AGE_MIN", "30"))   # RISK_LADDER §6b
HB_STALE_MIN = float(os.environ.get("WATCHDOG_STALE_MIN", "10"))
ERR_ALERT = int(os.environ.get("WATCHDOG_ERRORS", "3"))
REPEAT_MIN = float(os.environ.get("WATCHDOG_REPEAT_MIN", "30"))
LOOP_SEC = 30
TAG = "guard:"
START = time.monotonic()


def log(msg):
    print(f"{datetime.now(HKT):%m-%d %H:%M:%S} {msg}", flush=True)


def weekend_closed(t):
    wd = t.weekday()
    return (wd == 5 and t.hour >= 6) or wd == 6 or (wd == 0 and t.hour < 6)


def telegram(text):
    tok, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not tok or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": "[龍飛陣 VM] " + text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=15).read()
        return True
    except Exception as e:          # 唔好印網址（有權杖）
        log(f"Telegram 失敗：{e.__class__.__name__}")
        return False


def desired(now, ladder=None):
    """回傳 (動作, 原因, 要唔要警報)：動作只會係 None 或 PAUSE（Ⓑ）。ladder 預設期貨戶口級別檔。"""
    try:
        raw = (ladder or LADDER).read_text(encoding="utf-8")
        lv, sess, d, hm = raw.split()[:4]
        ts = datetime.strptime(f"{d} {hm}", "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
    except FileNotFoundError:
        starting = time.monotonic() - START < LADDER_MAX_AGE_MIN * 60    # 啱開機等 auto_risk 第一次寫，唔使警報
        return None, "冇風控級別檔", not starting
    except (OSError, ValueError):
        return None, "風控級別檔讀唔到", True
    age = (now - ts).total_seconds() / 60
    if age > LADDER_MAX_AGE_MIN and not weekend_closed(now):
        return None, f"風控級別檔 {age:.0f} 分鐘冇更新（auto_risk 停咗？）", True
    if lv == "B":
        return "PAUSE", f"風控 Ⓑ（{sess}）", False
    if lv in ("C", "D"):
        extra = "，硬止損" if "hard_stop" in raw else ""
        return None, f"風控 Ⓒ／Ⓓ：{lv}（{sess}{extra}）—— 照常交易，請自己決定要唔要停龍飛陣（touch ~/zhuge/ai_trader/STOP）", True
    if lv == "A":
        return None, f"風控 Ⓐ（{sess}）", False
    return None, f"風控級別唔明：{lv}", True


def ours(p):
    try:
        return p.read_text(encoding="utf-8").startswith(TAG)
    except OSError:
        return False


def apply(action, reason, data=DATA):
    """放／收 guard 自己嘅 PAUSE、STOP；回傳有冇改動。"""
    changed = False
    for name in ("PAUSE", "STOP"):
        p = data / name
        if name == action:
            if not p.exists():
                p.write_text(f"{TAG} {reason} {datetime.now(HKT):%Y-%m-%d %H:%M}\n", encoding="utf-8")
                changed = True
        elif p.exists() and ours(p):
            p.unlink()
            changed = True
    return changed


class Watchdog:
    def __init__(self, label="HSI", data=DATA):
        self.last = {}
        self.label, self.data = label, data

    def alert(self, key, text, now):
        t = self.last.get(key)
        if t is None or (now - t).total_seconds() >= REPEAT_MIN * 60:
            self.last[key] = now
            log("⚠ " + text)
            telegram(text)

    def once(self, key, text, now):
        if key not in self.last:
            self.last[key] = now
            log(text)
            telegram(text)

    def clear(self, key):
        self.last.pop(key, None)

    def check(self, now):
        try:
            hb = json.loads((self.data / "heartbeat").read_text(encoding="utf-8"))
            age = (now - datetime.fromisoformat(hb["utc"])).total_seconds() / 60
        except (OSError, ValueError, KeyError):
            hb, age = {}, None
        qty = hb.get("qty") or 0
        tag = f"[{self.label}] "
        prod = self.label.replace("真倉", "")
        unit = (f"zhuge-longfei-real@{prod}" if self.label.endswith("真倉") else
                "zhuge-longfei" if self.label == "HSI" else f"zhuge-longfei@{self.label}")
        booting = time.monotonic() - START < HB_STALE_MIN * 60          # 啱開機：bot 未寫第一個心跳，唔好誤報
        if (age is None or age > HB_STALE_MIN) and not booting:
            what = "冇心跳檔" if age is None else f"{age:.0f} 分鐘冇心跳"
            if qty:
                self.alert("stale_pos", f"🚨 {tag}AI 程式 {what}，仲有 {qty} 張 {hb.get('code')} {hb.get('side')}（止蝕 {hb.get('stop')}），"
                           f"冇程式守止蝕！請即睇（journalctl -u {unit}）", now)
            elif not weekend_closed(now.astimezone(HKT)):
                self.alert("stale", f"⚠ {tag}AI 程式 {what}（冇倉）", now)
        elif age is not None and age <= HB_STALE_MIN:
            self.clear("stale_pos"), self.clear("stale")
        if hb.get("errors", 0) >= ERR_ALERT:
            self.alert("errors", f"⚠ {tag}AI 程式連續出錯 {hb.get('errors')} 次", now)
        else:
            self.clear("errors")
        if (hb.get("foreign_qty") or 0) != 0:                  # 有正負（外來淡倉係負數）；只喺出現時發一次
            self.once("foreign", f"⚠ {tag}即月有 {hb.get('foreign_qty')} 張唔屬龍飛陣嘅倉，龍飛陣停開新倉", now)
        else:
            self.clear("foreign")
        if hb.get("calendar_warn"):                            # [R348] 數據日曆有問題：照常交易，每日提一次
            self.once(f"cal_{now.astimezone(HKT):%Y-%m-%d}", f"⚠ {tag}美國數據日曆：{hb['calendar_warn']}"
                      "（數據前 4 小時唔入市暫時唔生效，照常交易）", now)
        if hb.get("halted"):                                   # 日蝕停機會停到 17:00，只喺變化時發一次
            self.once("halted", f"⚠ {tag}AI 程式已停機（halted），新交易日先會再開", now)
        else:
            self.clear("halted")


def dirs_for(key, etf_sec=None):
    """[R205] 某個級別檔管邊啲產品資料夾：未開 ETF_SEC → 期貨級別管全部；開咗 → HSI 跟期貨、ETF 跟證券。"""
    etf_sec = ETF_SEC if etf_sec is None else etf_sec
    return [d for l, d in DIRS if not etf_sec or (l.replace("真倉", "") == "HSI") == (key == "fut")]


def main():
    for _, d in DIRS:
        d.mkdir(parents=True, exist_ok=True)
    wds = [Watchdog(label, d) for label, d in DIRS]
    wd = wds[0]
    last = {"fut": "init", "sec": "init"}
    log(f"guard 開始：{', '.join(f'{l}={d}' for l, d in DIRS)} LADDER={LADDER}"
        + (f" ETF 跟證券戶口 {SEC_LADDER}" if ETF_SEC else ""))
    while True:
        now = datetime.now(timezone.utc)
        res = {"fut": desired(now.astimezone(HKT))}
        if ETF_SEC:
            res["sec"] = desired(now.astimezone(HKT), SEC_LADDER)
        for key, (action, reason, alarm) in res.items():
            dirs = dirs_for(key)
            tag = "[證券戶口] " if key == "sec" else ""
            changed = any([apply(action, reason, d) for d in dirs])   # 戶口級風控：同一戶口嘅產品一齊
            if changed or action != last[key]:
                msg = f"{tag}{reason} → {'停開新倉（PAUSE）' if action else '照常開倉'}"
                log(msg)
                if changed or (last[key] != "init" and action != last[key]):
                    telegram(msg)
                last[key] = action
            if alarm:
                wd.alert(f"ladder_{key}", "⚠ " + tag + reason, now)
            else:
                wd.clear(f"ladder_{key}")
        for w in wds:
            w.check(now)
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
