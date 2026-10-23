#!/usr/bin/env python3
# =============================================================================
# 金絲雀特別警報(2026-10-23 使用者要求:「未來一兩週嘅保險,價錢追近咗一個月嘅保險,要發特別警報」)
# -----------------------------------------------------------------------------
# 兩個子命令,共用狀態檔 canary/alert_state.json 與紀錄 canary/alert_log.csv(只追加):
#
#   intraday   美股交易時段由 canary_intraday.yml 每 30 分鐘跑。抓 VIX9D / VIX / VIX3M 盤中價,
#              短期軸或災難軸「升級」就寫 canary/alert_intraday.txt(工作流負責發 Telegram):
#                短期軸等級  綠 0 → 走平 1(VIX9D − VIX > −0.5)→ 紅 2(> 0)
#                災難軸等級  綠 0 → 深紅 2(VIX − VIX3M > 0)
#              基準 = 上一個收市燈色(canary_daily.csv 最後一列);同一美股交易日每升一級只發一次,
#              跌回去不發(收市再確認或解除)。盤中讀數會反覆,訊息標明「盤中、未定稿」。
#
#   close      canary_daily.yml 在 Daily report 之後跑,用收市燈色(燈色日 D 對前一個有值的列):
#                * 短期軸 / 災難軸 收市升級(綠→走平、綠→紅、走平→紅、綠→深紅)→ 「收市確認」
#                * D 當日盤中發過預警但收市沒到該等級 → 「收市解除」
#              寫 canary/alert_close.txt;同一燈色日只發一次(排程重複跑也不重發)。
#
# 閾值與手冊 §2 一致(不調參);特別警報只是「通知」,不改燈色、不改統計口徑。
# 純標準庫。用法:
#   python3 canary/special_alert.py intraday [--now 2026-10-23T15:30:00Z] [--dry-run]
#   python3 canary/special_alert.py close [--dry-run]
# =============================================================================
import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(HERE, "canary_daily.csv")
STATE = os.path.join(HERE, "alert_state.json")
LOG = os.path.join(HERE, "alert_log.csv")
OUT_INTRADAY = os.path.join(HERE, "alert_intraday.txt")
OUT_CLOSE = os.path.join(HERE, "alert_close.txt")

NY = ZoneInfo("America/New_York")
HKT = timezone(timedelta(hours=8), "HKT")
FLAT_LO = -0.5                       # 手冊 §2:−0.5 < VIX9D − VIX ≤ 0 走平;> 0 紅
FRESH_MIN = 40                       # 盤中報價距今超過此分鐘數視為不新鮮(休市、假期、斷線),不判
SHORT_NAME = {0: "綠", 1: "走平", 2: "紅"}
DIS_NAME = {0: "綠", 2: "深紅"}
SHORT_ICON = {0: "🟢", 1: "⚪", 2: "🔴"}
DIS_ICON = {0: "🟢", 2: "🟣"}
LOG_FIELDS = ["time_utc", "kind", "day", "axis", "from", "to", "vix9d", "vix", "vix3m", "slope_9d", "slope_3m"]
WEEKDAY_ZH = "一二三四五六日"
SYMBOLS = {"vix9d": "^VIX9D", "vix": "^VIX", "vix3m": "^VIX3M"}


def dz(d):
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d.isoformat()[5:]}({WEEKDAY_ZH[d.weekday()]})"


def short_level(slope):
    if slope is None:
        return None
    return 2 if slope > 0 else (1 if slope > FLAT_LO else 0)


def dis_level(slope):
    if slope is None:
        return None
    return 2 if slope > 0 else 0


def level_from_axis(word, table):
    return {v: k for k, v in table.items()}.get(word)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_rows(path=TABLE):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("axis_short")]


def load_state(path=STATE):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state, path=STATE):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def append_log(rows, path=LOG):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LOG_FIELDS})


def fmt(x):
    return "—" if x is None else f"{x:.2f}"


def sgn(x):
    return "—" if x is None else f"{x:+.2f}"


# ----------------------------------------------------------------------------- 盤中
def fetch_quote(symbol, timeout=15):
    """Yahoo chart API 的 meta:回傳 (價格, 報價時間 UTC datetime)。"""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.request.quote(symbol) + "?interval=5m&range=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (canary-intraday)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        meta = json.load(resp)["chart"]["result"][0]["meta"]
    return float(meta["regularMarketPrice"]), datetime.fromtimestamp(int(meta["regularMarketTime"]), timezone.utc)


def intraday(now, fetch=fetch_quote, rows=None, state=None):
    """回傳 (訊息文字或 None, 新狀態, 紀錄列, 說明)。不寫檔,方便測試。"""
    rows = load_rows() if rows is None else rows
    state = dict(load_state() if state is None else state)
    us_day = now.astimezone(NY).date()
    if us_day.weekday() >= 5:
        return None, state, [], f"{us_day} 美股週末,不判"
    quotes = {}
    for k, sym in SYMBOLS.items():
        try:
            px, t = fetch(sym)
        except Exception as e:   # 單隻抓不到就整輪不判,避免半套數字誤報
            return None, state, [], f"抓 {sym} 失敗:{e}"
        if t.astimezone(NY).date() != us_day or (now - t) > timedelta(minutes=FRESH_MIN):
            return None, state, [], f"{sym} 報價時間 {t.isoformat()} 不新鮮(休市或延遲),不判"
        quotes[k] = (px, t)
    base = [r for r in rows if r["date"] < us_day.isoformat()]
    if not base:
        return None, state, [], "燈色表沒有可比的收市列"
    last = base[-1]
    b_short = level_from_axis(last["axis_short"], SHORT_NAME) or 0
    b_dis = level_from_axis(last["axis_disaster"], DIS_NAME) or 0
    if state.get("us_date") != us_day.isoformat():
        state = {"us_date": us_day.isoformat(), "base_date": last["date"],
                 "intraday_short": b_short, "intraday_disaster": b_dis,
                 "close_done": state.get("close_done", [])}
    v9, vx, v3 = (quotes[k][0] for k in ("vix9d", "vix", "vix3m"))
    s9, s3 = v9 - vx, vx - v3
    c_short, c_dis = short_level(s9), dis_level(s3)
    ups = []
    if c_short > max(b_short, state["intraday_short"]):
        ups.append(("短期軸", SHORT_NAME[max(b_short, state["intraday_short"])], SHORT_NAME[c_short]))
        state["intraday_short"] = c_short
    if c_dis > max(b_dis, state["intraday_disaster"]):
        ups.append(("災難軸", DIS_NAME[max(b_dis, state["intraday_disaster"])], DIS_NAME[c_dis]))
        state["intraday_disaster"] = c_dis
    if not ups:
        return None, state, [], (f"未升級:短期軸 {SHORT_NAME[c_short]}(VIX9D−VIX {s9:+.2f}),"
                                  f"災難軸 {DIS_NAME[c_dis]}(VIX−VIX3M {s3:+.2f})")
    qt = max(t for _, t in quotes.values())
    hk = qt.astimezone(HKT)
    ny = qt.astimezone(NY)
    lines = [f"🚨 金絲雀盤中預警(未定稿)📅 {dz(hk.date())} {hk:%H:%M} 香港 / 紐約 {ny:%H:%M}", ""]
    for axis, a, b in ups:
        lines.append(f"⚠️ {axis}盤中升級:{a} → {b}")
    lines += [
        "",
        f"• 短期軸:VIX9D {fmt(v9)} − VIX {fmt(vx)} = {sgn(s9)}(>−0.5 走平,>0 紅)"
        f"|上一收市 {dz(last['date'])} {sgn(f(last.get('slope_9d')))}"
        f"({last['axis_short']})",
        f"• 災難軸:VIX {fmt(vx)} − VIX3M {fmt(v3)} = {sgn(s3)}(>0 深紅)"
        f"|上一收市 {dz(last['date'])} {sgn(f(last.get('slope_3m')))}"
        f"({last['axis_disaster']})",
        "",
        "意思:未來一兩週的保險價錢追近(或超過)一個月的保險,市場在為短期大震盪付更高保險費。",
        "正式燈色以今晚收市為準,明早每日訊息會「收市確認」或「收市解除」。",
        "",
        "⚠️ 盤中讀數會反覆,這不是買賣建議。金絲雀預測震盪,不預測漲跌。",
    ]
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    log = [dict(time_utc=stamp, kind="盤中預警", day=us_day.isoformat(), axis=a, **{"from": x, "to": y},
                vix9d=fmt(v9), vix=fmt(vx), vix3m=fmt(v3), slope_9d=sgn(s9), slope_3m=sgn(s3))
           for a, x, y in ups]
    state["last_intraday"] = {"time_utc": stamp, "vix9d": round(v9, 2), "vix": round(vx, 2), "vix3m": round(v3, 2)}
    return "\n".join(lines), state, log, "升級:" + ";".join(f"{a} {x}→{y}" for a, x, y in ups)


# ----------------------------------------------------------------------------- 收市
def close(rows=None, state=None, now=None):
    rows = load_rows() if rows is None else rows
    state = dict(load_state() if state is None else state)
    now = now or datetime.now(timezone.utc)
    if len(rows) < 2:
        return None, state, [], "燈色表不足兩列"
    cur, prev = rows[-1], rows[-2]
    d = cur["date"]
    done = list(state.get("close_done", []))
    if d in done:
        return None, state, [], f"燈色日 {d} 已處理過,不重發"
    c_s, p_s = level_from_axis(cur["axis_short"], SHORT_NAME), level_from_axis(prev["axis_short"], SHORT_NAME)
    c_d, p_d = level_from_axis(cur["axis_disaster"], DIS_NAME), level_from_axis(prev["axis_disaster"], DIS_NAME)
    msgs, log = [], []
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    vals = dict(vix9d=fmt(f(cur.get("vix9d"))), vix=fmt(f(cur.get("vix"))), vix3m=fmt(f(cur.get("vix3m"))),
                slope_9d=sgn(f(cur.get("slope_9d"))), slope_3m=sgn(f(cur.get("slope_3m"))))
    intr = state.get("us_date") == d
    i_s = state.get("intraday_short", 0) if intr else 0
    i_d = state.get("intraday_disaster", 0) if intr else 0
    for axis, c, p, i, names, icons in (("短期軸", c_s, p_s, i_s, SHORT_NAME, SHORT_ICON),
                                         ("災難軸", c_d, p_d, i_d, DIS_NAME, DIS_ICON)):
        if c is None or p is None:
            continue
        if c > p:
            msgs.append(f"{icons[c]} 收市確認:{axis} {names[p]} → {names[c]}({dz(prev['date'])} → {dz(d)})")
            log.append(dict(time_utc=stamp, kind="收市確認", day=d, axis=axis, **{"from": names[p], "to": names[c]}, **vals))
        if intr and i > max(c, p):
            msgs.append(f"✅ 收市解除:{axis} 盤中曾到{names[i]},收市為{names[c]}({dz(d)})")
            log.append(dict(time_utc=stamp, kind="收市解除", day=d, axis=axis, **{"from": names[i], "to": names[c]}, **vals))
    done = (done + [d])[-30:]
    state["close_done"] = done
    if not msgs:
        return None, state, [], f"燈色日 {d} 無升級、無待解除的盤中預警"
    lines = [f"🚨 金絲雀特別警報(收市)燈色日 {dz(d)}", ""] + msgs + [
        "",
        f"• 短期軸:{dz(d)} VIX9D {vals['vix9d']} − VIX {vals['vix']} = {vals['slope_9d']}"
        f"(前一列 {dz(prev['date'])} {sgn(f(prev.get('slope_9d')))})",
        f"• 災難軸:{dz(d)} VIX {vals['vix']} − VIX3M {vals['vix3m']} = {vals['slope_3m']}"
        f"(前一列 {dz(prev['date'])} {sgn(f(prev.get('slope_3m')))})",
        "",
        f"燈色只管 {dz(d)} 之後的交易日(lag=1)。詳情見每日總結。",
        "⚠️ 這是市場風險的天氣預報,不是買賣建議。金絲雀預測震盪,不預測漲跌。",
    ]
    return "\n".join(lines), state, log, "發:" + ";".join(m.split(":")[0] for m in msgs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["intraday", "close"])
    ap.add_argument("--now", help="UTC 時間 ISO,測試用")
    ap.add_argument("--dry-run", action="store_true", help="只印,不寫狀態、紀錄、訊息檔")
    a = ap.parse_args()
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    if a.cmd == "intraday":
        text, state, log, why = intraday(now)
        out = OUT_INTRADAY
    else:
        text, state, log, why = close(now=now)
        out = OUT_CLOSE
    print(why)
    if a.dry_run:
        if text:
            print("----\n" + text)
        return
    save_state(state)
    if log:
        append_log(log)
    if text:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"寫入 {os.path.relpath(out, os.path.dirname(HERE))}")
    elif os.path.exists(out):
        os.remove(out)


if __name__ == "__main__":
    main()
