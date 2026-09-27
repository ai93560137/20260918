#!/usr/bin/env python3
# =============================================================================
# 金絲雀每日總結報告
# -----------------------------------------------------------------------------
# 讀 canary_daily.csv(由 build_canary_table.py 產出),寫三個檔:
#   canary/DAILY_REPORT.md   當日完整報告(每日覆蓋)
#   canary/daily_log.csv     每日一列的長期紀錄(追加;同日重跑則覆蓋該列)——供觀察名單 W1 等
#                            候選日後做「樣本外」考核,也是各策略登記響應後的對帳依據
#   canary/tg_daily.txt      Telegram 短訊(工作流有設 TG 密鑰時發送)
#
# 報告內容:
#   1. 三軸燈色(短期軸/災難軸/黃)+ 與前一日的變化 + 連續天數
#   2. 距離門檻多遠(斜率數值、黃鳥距 p90 的百分比)
#   3. 試用層(無警報權)與觀察名單 W1 的當日讀數(只記錄,不行動)
#   4. 數據新鮮度:各鳥最後日期,落後交易日數;落後 > 1 個交易日則警告
#      + 呆值檢查:原始檔最後一列開高低收四價相同、且與前一日收盤差 < 0.01 → 疑似未更新(日期新、數值舊)
#   5. 健康檢查:列數、日期單調、無重複、最新列六隻鳥齊全;工作流各步驟狀態(--health)
#   6. 紅或深紅亮起時附 §3 註記
# 純標準庫。用法:
#   python3 canary/daily_report.py
#   python3 canary/daily_report.py --health refresh=ok build=ok labs=skipped
# =============================================================================
import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_canary_table import RED_NOTE, rolling_quantile  # noqa: E402

TABLE = os.path.join(HERE, "canary_daily.csv")
OUT_MD = os.path.join(HERE, "DAILY_REPORT.md")
OUT_LOG = os.path.join(HERE, "daily_log.csv")
OUT_TG = os.path.join(HERE, "tg_daily.txt")

BIRDS = ["vix9d", "vix", "vix3m", "vvix", "move", "axvi"]
US_BIRDS = ["vix9d", "vix", "vix3m", "vvix", "move"]     # axvi 是亞洲時段,天生慢一天
W1_Q = 0.10                                              # 觀察名單 W1:VVIX/VIX < 滾動 252 日 p10
DATA_DIR = os.path.join(HERE, "data_external")
STALE_TOL = 0.01                                         # 呆值:四價相同且 |C − 前日C| < 此值

LOG_FIELDS = ["date", "axis_short", "axis_disaster", "yellow", "yellow_count",
              "yellow_vvix", "yellow_move", "yellow_axvi",
              "trial_yellow2", "trial_deep_yellow", "trial_red_deep", "trial_red_9d3m",
              "w1_fear_spike", "vvix_vix_ratio", "ratio_p10",
              "vix9d", "vix", "vix3m", "vvix", "move", "axvi", "slope_9d", "slope_3m",
              "stale_us_days", "stale_print", "generated_at_utc"]


# ----------------------------------------------------------------------------- 讀表
def load_table():
    with open(TABLE, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        sys.exit("canary_daily.csv 是空的")
    return rows


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def business_days_between(d0, d1):
    """d0 → d1(不含 d0、含 d1)的週一至週五天數。"""
    n, d = 0, d0
    while d < d1:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def streak(rows, key, value):
    n = 0
    for r in reversed(rows):
        if r[key] == value:
            n += 1
        else:
            break
    return n


# ----------------------------------------------------------------------------- 呆值檢查
def stale_prints():
    """回傳 [(bird, date, close)]:原始檔最後一列 O=H=L=C 且與前一列收盤差 < STALE_TOL。"""
    out = []
    for b in BIRDS:
        path = os.path.join(DATA_DIR, f"{b}_daily.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("Close")]
        if len(rows) < 2:
            continue
        last, prev = rows[-1], rows[-2]
        try:
            o, h, l, c = (float(last[k]) for k in ("Open", "High", "Low", "Close"))
            pc = float(prev["Close"])
        except (KeyError, ValueError):
            continue
        if o == h == l == c and abs(c - pc) < STALE_TOL:
            out.append((b, last["Date"][:10], c))
    return out


# ----------------------------------------------------------------------------- W1 觀察值
def w1_status(rows):
    """VVIX/VIX 比率與其滾動 252 日 p10(只在兩者皆有值的列上算,與 lab 的 ratio.dropna() 日曆一致)。"""
    dates, vals = [], []
    for r in rows:
        vv, vx = f(r["vvix"]), f(r["vix"])
        if vv is not None and vx is not None and vx > 0:
            dates.append(r["date"])
            vals.append(vv / vx)
    if not vals:
        return None, None, None
    p10 = rolling_quantile(vals, q=W1_Q)
    last_ratio, last_p10 = vals[-1], p10[-1]
    lit = None if last_p10 is None else last_ratio < last_p10
    return last_ratio, last_p10, lit


# ----------------------------------------------------------------------------- 報告
def build_report(rows, health, today):
    last, prev = rows[-1], (rows[-2] if len(rows) > 1 else None)
    d_last = date.fromisoformat(last["date"])
    stale_us = business_days_between(d_last, today)
    warnings = []

    # 1. 燈色與變化
    def chg(key):
        if prev is None or prev[key] == last[key]:
            return ""
        return f"(前日 {prev[key] or '—'} → 今日 {last[key] or '—'})"

    def onoff(key):
        return {"1": "亮", "0": "滅", "": "無資料"}.get(last[key], last[key])

    lights = [
        ("短期軸(VIX9D 系)", last["axis_short"] or "無資料", chg("axis_short"),
         streak(rows, "axis_short", last["axis_short"])),
        ("災難軸(VIX3M 系)", last["axis_disaster"] or "無資料", chg("axis_disaster"),
         streak(rows, "axis_disaster", last["axis_disaster"])),
        ("黃(任一)", onoff("yellow"), chg("yellow"), streak(rows, "yellow", last["yellow"])),
    ]
    yparts = [("VVIX", "yellow_vvix", "vvix", "vvix_p90"), ("MOVE", "yellow_move", "move", "move_p90"),
              ("AXVI", "yellow_axvi", "axvi", "axvi_p90")]

    # 2. 距門檻
    s9, s3 = f(last["slope_9d"]), f(last["slope_3m"])
    dist = []
    if s9 is not None:
        dist.append(f"slope_9d = {s9:+.2f}(>0 為紅;−0.5~0 為走平)")
    if s3 is not None:
        dist.append(f"slope_3m = {s3:+.2f}(>0 為深紅)")
    for name, flag, col, pcol in yparts:
        v, p = f(last[col]), f(last[pcol])
        if v is not None and p is not None and p != 0:
            dist.append(f"{name} = {v:.2f},p90 = {p:.2f},距門檻 {(v / p - 1) * 100:+.1f}%")
        else:
            dist.append(f"{name}:當日無資料")

    # 3. 試用與 W1
    trials = [("黃×2", "trial_yellow2"), ("深黃 VVIX p95", "trial_deep_yellow"),
              ("紅相對深度 p90", "trial_red_deep"), ("9D對3M倒掛", "trial_red_9d3m")]
    ratio, p10, w1 = w1_status(rows)

    # 4. 新鮮度
    fresh = []
    latest_by_bird = {}
    for b in BIRDS:
        for r in reversed(rows):
            if r[b] != "":
                latest_by_bird[b] = r["date"]
                break
        else:
            latest_by_bird[b] = "—"
    for b in BIRDS:
        lb = latest_by_bird[b]
        gap = business_days_between(date.fromisoformat(lb), today) if lb != "—" else None
        fresh.append((b, lb, gap))
        if b in US_BIRDS and gap is not None and gap > 1:
            warnings.append(f"{b} 最後日期 {lb},落後 {gap} 個交易日")
        if b == "axvi" and gap is not None and gap > 2:
            warnings.append(f"axvi 最後日期 {lb},落後 {gap} 個交易日(亞洲時段允許 1–2 日)")
    if stale_us > 1:
        warnings.append(f"燈色表最新列 {last['date']},距今 {stale_us} 個交易日,上游可能未更新")
    stale = stale_prints()
    for b, dt, c in stale:
        warnings.append(f"{b} {dt} 疑似呆值:開高低收四價相同({c:.2f})且等於前一日收盤,該日讀數可能是舊值填充")

    # 5. 健康檢查
    checks = []
    dates = [r["date"] for r in rows]
    checks.append(("列數", f"{len(rows)}", True))
    mono = all(dates[i] < dates[i + 1] for i in range(len(dates) - 1))
    checks.append(("日期單調遞增", "是" if mono else "否", mono))
    dup = len(dates) != len(set(dates))
    checks.append(("無重複日期", "否" if dup else "是", not dup))
    missing = [b for b in BIRDS if last[b] == ""]
    checks.append(("最新列六隻鳥齊全", "是" if not missing else "缺 " + "、".join(missing),
                   not missing or missing == ["axvi"]))
    checks.append(("無呆值(四價相同且等於前日收盤)", "是" if not stale else "疑似:" + "、".join(b for b, _, _ in stale),
                   not stale))
    for k, v in health.items():
        checks.append((f"工作流:{k}", v, v.lower() in ("ok", "skipped", "pass")))
    bad = [c for c in checks if not c[2] and not c[0].startswith("無呆值")]   # 呆值已各自成一則警告,不重複
    if bad:
        warnings.extend(f"健康檢查未過:{c[0]} = {c[1]}" for c in bad)

    # ---- Markdown
    md = [f"# 金絲雀每日總結 — 燈色日 {last['date']}",
          f"產生於 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')};"
          f"此燈色只能用於 **{last['date']} 之後**的交易日(lag=1)。\n"]
    if warnings:
        md.append("## ⚠️ 警告\n")
        md += [f"- {w}" for w in warnings]
        md.append("")
    md.append("## 1. 燈色\n")
    md.append("| 軸 | 今日 | 變化 | 連續 |\n|---|---|---|---|")
    for name, val, c, n in lights:
        md.append(f"| {name} | **{val}** | {c or '—'} | {n} 日 |")
    md.append("")
    md.append("黃鳥明細:" + ";".join(f"{n} {onoff(flag)}" for n, flag, _, _ in yparts)
              + f";yellow_count = {last['yellow_count'] or '—'}")
    md.append("")
    md.append("## 2. 距門檻\n")
    md += [f"- {x}" for x in dist]
    md.append("")
    md.append("## 3. 試用層與觀察名單(只記錄,無警報權,不得據此改變響應)\n")
    md.append("| 項目 | 今日 | 變化 | 連續 |\n|---|---|---|---|")
    for name, key in trials:
        md.append(f"| 試用:{name} | {onoff(key)} | {chg(key) or '—'} | {streak(rows, key, last[key])} 日 |")
    if ratio is not None:
        w1txt = "無資料(窗口未滿)" if w1 is None else ("亮" if w1 else "滅")
        md.append(f"| 觀察 W1:VVIX/VIX < p10 | {w1txt} | 比率 {ratio:.2f},p10 {p10 if p10 is None else round(p10, 2)} | 樣本外累積中(自 2026-09-27) |")
    md.append("")
    md.append("## 4. 數據新鮮度\n")
    md.append("| 鳥 | 最後日期 | 落後交易日 |\n|---|---|---|")
    for b, lb, gap in fresh:
        md.append(f"| {b} | {lb} | {'—' if gap is None else gap} |")
    md.append("")
    md.append("## 5. 健康檢查\n")
    md.append("| 項目 | 結果 | 狀態 |\n|---|---|---|")
    for k, v, ok in checks:
        md.append(f"| {k} | {v} | {'✅' if ok else '❌'} |")
    md.append("")
    if last["axis_short"] == "紅" or last["axis_disaster"] == "深紅":
        md.append("## 6. §3 註記(紅或深紅亮起時展示)\n")
        md.append("```\n" + RED_NOTE + "\n```")
        md.append("")
    md.append("---\n口徑:`CANARY_PLAYBOOK.md` §2;欄位說明 `canary/README.md`;長期紀錄 `canary/daily_log.csv`。")

    # ---- Telegram 每日總結(白話、emoji;每天必發,含週末)
    L = {"綠": "🟢", "走平": "⚪", "紅": "🔴", "深紅": "🟣", "": "❔"}
    a_s, a_d = last["axis_short"], last["axis_disaster"]
    ylit = [n for n, flag, _, _ in yparts if last[flag] == "1"]
    weekend_note = ""
    if stale_us == 0 and today.weekday() in (5, 6, 0) and today != d_last:
        weekend_note = f"(今天{'週六' if today.weekday() == 5 else '週日' if today.weekday() == 6 else '週一早上'}無新美股收盤,燈色沿用 {last['date']})"

    # 白話總結
    if a_d == "深紅":
        plain = "🟣 災難軸亮了。這是最準的燈,十次只錯一次。今天起別開新倉、複核止損與保證金,已有倉位不必平,但要盯緊。"
    elif a_s == "紅":
        plain = "🔴 短期軸亮了,市場在為未來幾天的大震盪付保險費。該做的是減注、晚幾天再進場、檢查止損;不是猜方向。"
    elif a_s == "走平":
        plain = "⚪ 保險價格開始走樣,還沒到警戒。留神,不必行動。"
    elif last["yellow"] == "1" and last["yellow_count"] not in ("", "0", "1"):
        plain = "🟡🟡 兩隻以上側翼鳥同時亮,可靠度大幅提高。自己家還沒事,但鄰居兩戶都響了,進場前多想一下。"
    elif last["yellow"] == "1":
        plain = f"🟡 只有 {'、'.join(ylit)} 一隻側翼鳥亮,像鄰居家警報響了,自己家沒事。單隻黃燈誤報約三成,記錄就好,不用行動。"
    else:
        plain = "🟢 一切平靜,保險價格正常。照平常節奏做事。"

    def onoff_emoji(key):
        return {"1": "🔔亮", "0": "滅", "": "—"}.get(last[key], last[key])

    tg = [f"🐤 金絲雀每日總結 📅 {today.isoformat()}",
          f"燈色日 {last['date']}{weekend_note}",
          f"⏰ 此燈色用於 {last['date']} 之後的交易日(lag=1)",
          "",
          "🚦 三軸",
          f"{L.get(a_s, '❔')} 短期軸(一週 vs 一月保險):{a_s or '無資料'},連續 {streak(rows, 'axis_short', a_s)} 天"
          + (f" {chg('axis_short')}" if chg('axis_short') else ""),
          f"{L.get(a_d, '❔')} 災難軸(一月 vs 三月保險):{a_d or '無資料'},連續 {streak(rows, 'axis_disaster', a_d)} 天"
          + (f" {chg('axis_disaster')}" if chg('axis_disaster') else ""),
          f"🟡 側翼鳥:{'、'.join(ylit) if ylit else '全滅'}(黃燈連續 {streak(rows, 'yellow', last['yellow'])} 天)"
          + (f" {chg('yellow')}" if chg('yellow') else ""),
          "",
          "📏 距門檻",
          *[f"• {x}" for x in dist],
          "",
          "🧪 試用層與觀察名單(無警報權,只記錄)",
          "• " + " | ".join(f"{n} {onoff_emoji(k)}" for n, k in trials),
          ]
    if ratio is not None:
        tg.append(f"• W1 VVIX/VIX<p10:{'🔔亮' if w1 else '滅' if w1 is not None else '—'}(比率 {ratio:.2f},門檻 {p10 if p10 is None else round(p10, 2)})")
    tg += ["",
           "🩺 數據與健康",
           "• 新鮮度:" + "、".join(f"{b} {lb}" for b, lb, _ in fresh if b in ("vix", "vvix", "move", "axvi")),
           "• 健康檢查:" + ("全過 ✅" if all(ok for _, _, ok in checks) else "有未過 ❌,見下"),
           ]
    if warnings:
        tg += ["", "⚠️ 警告"] + [f"• {w}" for w in warnings]
    if a_s == "紅" or a_d == "深紅":
        tg += ["", "📌 §3 分工:看未來一兩週的對沖負載看紅,看災難風險看深紅。紅覆蓋面廣、深紅精度高,兩者不排序。"]
    tg += ["", "🗣️ 白話一句", plain,
           "", "⚠️ 這是市場風險的天氣預報,不是買賣建議。金絲雀預測震盪,不預測漲跌。"]
    tg_text = "\n".join(tg)

    # ---- log 列
    log_row = {
        "date": last["date"], "axis_short": last["axis_short"], "axis_disaster": last["axis_disaster"],
        "yellow": last["yellow"], "yellow_count": last["yellow_count"],
        "yellow_vvix": last["yellow_vvix"], "yellow_move": last["yellow_move"], "yellow_axvi": last["yellow_axvi"],
        "trial_yellow2": last["trial_yellow2"], "trial_deep_yellow": last["trial_deep_yellow"],
        "trial_red_deep": last["trial_red_deep"], "trial_red_9d3m": last["trial_red_9d3m"],
        "w1_fear_spike": "" if w1 is None else ("1" if w1 else "0"),
        "vvix_vix_ratio": "" if ratio is None else f"{ratio:.4f}",
        "ratio_p10": "" if p10 is None else f"{p10:.4f}",
        **{b: last[b] for b in BIRDS},
        "slope_9d": last["slope_9d"], "slope_3m": last["slope_3m"],
        "stale_us_days": str(stale_us),
        "stale_print": ";".join(b for b, _, _ in stale),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }
    return "\n".join(md) + "\n", tg_text, log_row, warnings


def append_log(row):
    existing = []
    if os.path.exists(OUT_LOG):
        with open(OUT_LOG, newline="", encoding="utf-8") as fh:
            existing = [r for r in csv.DictReader(fh) if r["date"] != row["date"]]
    existing.append(row)
    existing.sort(key=lambda r: r["date"])
    with open(OUT_LOG, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS, restval="")
        w.writeheader()
        w.writerows(existing)
    return len(existing)


def main():
    ap = argparse.ArgumentParser(description="金絲雀每日總結報告")
    ap.add_argument("--health", nargs="*", default=[], help="工作流步驟狀態,如 refresh=ok build=ok labs=skipped")
    ap.add_argument("--today", default=None, help="覆寫今日日期(YYYY-MM-DD),測試用")
    args = ap.parse_args()
    health = dict(h.split("=", 1) for h in args.health if "=" in h)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()

    rows = load_table()
    md, tg, log_row, warnings = build_report(rows, health, today)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(OUT_TG, "w", encoding="utf-8") as fh:
        fh.write(tg + "\n")
    n = append_log(log_row)
    print(md)
    print(f"[daily_report] 已寫入 DAILY_REPORT.md、tg_daily.txt;daily_log.csv 共 {n} 列;警告 {len(warnings)} 則")
    if warnings:
        print("[daily_report] " + " | ".join(warnings), file=sys.stderr)


if __name__ == "__main__":
    main()
