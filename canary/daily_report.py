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
#   0. 日期對照:報告日(香港日期)/ 應有燈色日 / 燈色日 D / 前一列 D−1 / 適用日(D 之後第一個交易日);
#      每個燈號都寫明「用哪幾天、跟哪幾天比」。報告日一律用香港日期:工作流 22:30 UTC 跑,已是香港翌日 06:30
#   1. 三軸燈色(短期軸/災難軸/黃)+ 與前一列的變化(標明兩個日期)+ 連續天數(標明起日)
#   2. 距離門檻多遠(斜率 = 同日兩鳥相減;黃鳥 = 值日 vs 自身 252 交易日窗口 p90,標明窗口起迄)
#   3. 試用層(無警報權)與觀察名單 W1 的當日讀數(只記錄,不行動)
#   4. 數據新鮮度:各鳥最後日期,落後交易日數;落後 > 1 個交易日則警告
#      + 呆值檢查:原始檔最後一列開高低收四價相同、且與前一日收盤差 < 0.01 → 疑似未更新(日期新、數值舊)
#   5. 健康檢查:列數、日期單調、無重複、最新列六隻鳥齊全;工作流各步驟狀態(--health)
#   6. T−1 訊息回驗:把上一次真正發出的訊息(sent_log.csv 最後一列)拿回來,對照今天重產的表——
#      數值有沒有被上游修訂、燈色有沒有改判、亞洲鳥補值後黃鳥數有沒有變、預測的適用日對不對、
#      連續天數是否接得上;以及燈色日後 5 個交易日已齊時,SPX 實現波動的後驗(只記錄)
#   7. 紅或深紅亮起時附 §3 註記
# 純標準庫。用法:
#   python3 canary/daily_report.py
#   python3 canary/daily_report.py --health refresh=ok build=ok labs=skipped
#   python3 canary/daily_report.py --today 2026-09-27 --dry-run   # 測試:不寫 daily_log / sent_log
# =============================================================================
import argparse
import csv
import hashlib
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_canary_table import RED_NOTE, WINDOW, load_close, rolling_quantile  # noqa: E402

TABLE = os.path.join(HERE, "canary_daily.csv")
OUT_MD = os.path.join(HERE, "DAILY_REPORT.md")
OUT_LOG = os.path.join(HERE, "daily_log.csv")
OUT_TG = os.path.join(HERE, "tg_daily.txt")
OUT_SENT = os.path.join(HERE, "sent_log.csv")          # 只追加、不覆蓋:每次發出的訊息各一列,供次日回驗

BIRDS = ["vix9d", "vix", "vix3m", "vvix", "move", "axvi", "vhsi"]   # vhsi 為試用層資料,亞洲時段
US_BIRDS = ["vix9d", "vix", "vix3m", "vvix", "move"]     # axvi 是亞洲時段,天生慢一天
W1_Q = 0.10                                              # 觀察名單 W1:VVIX/VIX < 滾動 252 日 p10
DATA_DIR = os.path.join(HERE, "data_external")
STALE_TOL = 0.01                                         # 呆值:四價相同且 |C − 前日C| < 此值
SPX_FILE = os.path.join(DATA_DIR, "spx_daily.csv")      # 後驗用:燈色日後 5 個交易日的 SPX 實現波動

LOG_FIELDS = ["date", "axis_short", "axis_disaster", "yellow", "yellow_count",
              "yellow_vvix", "yellow_move", "yellow_axvi",
              "trial_yellow2", "trial_deep_yellow", "trial_red_deep", "trial_red_9d3m", "trial_yellow_vhsi",
              "w1_fear_spike", "vvix_vix_ratio", "ratio_p10",
              "vix9d", "vix", "vix3m", "vvix", "move", "axvi", "vhsi", "slope_9d", "slope_3m",
              "stale_us_days", "stale_print", "generated_at_utc"]

# sent_log.csv:T 日發出的訊息「當時說了什麼」。次日拿最後一列對照重產的表,驗 T−1 訊息正確與否。
COMPARE_VALUES = ["vix9d", "vix", "vix3m", "vvix", "move", "axvi", "vhsi", "slope_9d", "slope_3m",
                  "vvix_p90", "move_p90", "axvi_p90", "vhsi_p90"]
COMPARE_LIGHTS = ["axis_short", "axis_disaster", "yellow", "yellow_count", "yellow_vvix", "yellow_move", "yellow_axvi",
                  "trial_yellow2", "trial_deep_yellow", "trial_red_deep", "trial_red_9d3m", "trial_yellow_vhsi"]
SENT_FIELDS = (["report_date", "generated_at_utc", "light_date", "apply_date_pred",
                "streak_short", "streak_disaster", "streak_yellow", "stale_print", "stale_detail", "tg_sha1", "posthoc_done"]
               + COMPARE_LIGHTS + COMPARE_VALUES)


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


def streak_info(rows, key, value):
    """由最新列往前數與 value 相同的列:回傳 (連續列數, 起始日期 ISO, 途中跳過的無資料列日期 list)。
    無資料列(空白,例如美股假期只有 VIX 一根 bar 的列)不算中斷、也不計入天數,但列出來讓讀者知道。"""
    n, start, skipped = 0, None, []
    for r in reversed(rows):
        v = r[key]
        if v == value:
            n += 1
            start = r["date"]
        elif v == "":
            skipped.append(r["date"])
        else:
            break
    # 起點之前的空白列不算「途中」
    skipped = [d for d in skipped if start is None or d > start]
    return n, start, skipped


def streak(rows, key, value):
    return streak_info(rows, key, value)[0]


WEEKDAY_ZH = "一二三四五六日"


def word(v):
    return {"1": "亮", "0": "滅", "": "—"}.get(v, v)


def dz(d):
    """MM-DD(星期),如 09-25(五);接受 date 或 ISO 字串。"""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d.isoformat()[5:]}({WEEKDAY_ZH[d.weekday()]})"


HKT = timezone(timedelta(hours=8), "HKT")   # 香港無夏令時間,固定 +8 即精確


def hk_today():
    return datetime.now(HKT).date()


def prev_weekday(d):
    """d 之前(不含 d)最後一個週一至週五。香港早上報告時,應有燈色日 = 報告日的前一個美股交易日。"""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def utc_stamp_to_hkt(stamp):
    """'2026-09-27T22:35Z' → datetime(香港時間);解析失敗回 None。"""
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc).astimezone(HKT)
    except (TypeError, ValueError):
        return None


def next_weekday(d):
    """d 之後第一個週一至週五(交易所假期不在此估,遇假期順延)。"""
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def window_span(bird, end_iso, window=WINDOW):
    """bird 原始檔上、以 end_iso 為終點(含)的最近 window 個交易日 → (起日, 終日) ISO;不足 window 筆回 None。
    與 build_canary_table 的 p90 口徑一致:窗口在各鳥自己的日曆上、含當日。"""
    path = os.path.join(DATA_DIR, f"{bird}_daily.csv")
    if not os.path.exists(path):
        return None
    end = date.fromisoformat(end_iso)
    ds = [d.isoformat() for d, _ in load_close(path) if d <= end]   # 與產生器同一讀法:排序、去重、跳壞值
    if len(ds) < window:
        return None
    return ds[-window], ds[-1]


def win_text(span, label):
    if span is None:
        return "窗口未滿 252 日"
    return f"窗口 {span[0]}→{span[1]},最近 {WINDOW} 個{label}交易日,含當日"


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
            out.append((b, last["Date"][:10], c, prev["Date"][:10], pc))
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
        return None, None, None, None, None
    p10 = rolling_quantile(vals, q=W1_Q)
    last_ratio, last_p10 = vals[-1], p10[-1]
    lit = None if last_p10 is None else last_ratio < last_p10
    span = (dates[-WINDOW], dates[-1]) if len(dates) >= WINDOW else None
    return last_ratio, last_p10, lit, dates[-1], span


# ----------------------------------------------------------------------------- T−1 訊息回驗
def load_sent():
    if not os.path.exists(OUT_SENT):
        return []
    with open(OUT_SENT, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def spx_fwd5(light_date):
    """燈色日 D 之後 5 個交易日的 SPX 實現波動(與 lab_common.fwd 同口徑:5 個對數報酬的樣本標準差×√252×100)、
    是否出現 −2% 單日,以及 D 之前 252 日的無條件 5 日 RV 中位。D+5 未齊則回 None。"""
    if not os.path.exists(SPX_FILE):
        return None
    ser = load_close(SPX_FILE)
    ds = [d.isoformat() for d, _ in ser]
    px = [v for _, v in ser]
    # D 不在 SPX 日曆上(例如假期孤 bar)→ 取 ≤ D 的最後一個 SPX 交易日
    i = max((k for k, d in enumerate(ds) if d <= light_date), default=None)
    if i is None or i + 5 >= len(px):
        return None
    r = [math.log(px[k + 1] / px[k]) for k in range(len(px) - 1)]      # r[k] = k→k+1 的報酬,對應日期 ds[k+1]

    def rv(j):                                                          # 以 j 為訊號日:報酬 r[j..j+4](日期 j+1..j+5)
        w = r[j:j + 5]
        if len(w) < 5:
            return None
        m = sum(w) / 5
        return math.sqrt(sum((x - m) ** 2 for x in w) / 4) * math.sqrt(252) * 100

    fwd = rv(i)
    down = any(x < -0.02 for x in r[i:i + 5])
    hist = [v for v in (rv(j) for j in range(max(0, i - 252), i)) if v is not None]
    med = sorted(hist)[len(hist) // 2] if hist else None
    return {"spx_day": ds[i], "end": ds[i + 5], "rv": fwd, "down2": down, "median": med}


def verify_previous(rows, sent, today):
    """回傳 (lines, posthoc_ids):lines 是回驗結果文字;posthoc_ids 是本次完成後驗的 sent 列 generated_at。"""
    lines, done = [], []
    by_date = {r["date"]: r for r in rows}
    if not sent:
        return ["首次產出,沒有前一則訊息可驗(明天起每天回驗昨天發出的訊息)"], done
    S = sent[-1]
    ld = S["light_date"]
    sent_hk = utc_stamp_to_hkt(S.get("generated_at_utc"))
    sent_txt = f"{dz(sent_hk.date())} {sent_hk:%H:%M} 香港" if sent_hk else dz(S["report_date"])
    lines.append(f"對象:{sent_txt} 發出、燈色日 {dz(ld)} 的訊息(生成 {S['generated_at_utc']})")
    cur = by_date.get(ld)
    if cur is None:
        lines.append(f"⚠️ 燈色日 {dz(ld)} 這一列今天在表中消失了(上游重建了日線?)——昨日訊息無從對照")
        return lines, done
    filled, revised, relit = [], [], []
    for k in COMPARE_VALUES:
        old, new = S.get(k, ""), cur.get(k, "")
        if old == new:
            continue
        if old == "" and new != "":
            filled.append(f"{k} 補值 {new}")
        else:
            revised.append(f"{k} {old or '—'} → {new or '—'}")
    for k in COMPARE_LIGHTS:
        old, new = S.get(k, ""), cur.get(k, "")
        if old == new:
            continue
        if old == "" and new != "":
            filled.append(f"{k} 補判 {word(new)}")
        else:
            relit.append(f"{k} {word(old) if old else '—'} → {word(new) if new else '—'}")
    if revised:
        lines.append("❌ 數值被上游修訂(昨日訊息用的是舊值):" + ";".join(revised))
    if relit:
        lines.append("❌ 燈色改判(昨日訊息的燈色在事後看是錯的):" + ";".join(relit))
    if filled:
        lines.append("ℹ️ 補值(昨日訊息當時未到的亞洲鳥今天補進來,昨日訊息在當時資訊下正確):" + ";".join(filled))
    if not (revised or relit or filled):
        lines.append(f"✅ 燈色日 {dz(ld)} 的全部讀數與燈色,與今天重產的表逐欄一致({len(COMPARE_VALUES)} 個數值、{len(COMPARE_LIGHTS)} 個燈)")
    # 呆值有沒有被真值取代(stale_detail = "bird@YYYY-MM-DD@值";呆值列未必是燈色日,按它自己的日期查)
    for item in filter(None, S.get("stale_detail", "").split(";")):
        b, sd, old = (item.split("@") + ["", ""])[:3]
        row_sd = by_date.get(sd)
        new = row_sd.get(b, "") if row_sd else ""
        if row_sd is None:
            lines.append(f"⚠️ 昨日警告 {b} {dz(sd)} 疑似呆值 {old}:該日今天不在表中,無法對照")
        else:
            lines.append(f"{'✅' if old != new else '⚠️'} 昨日警告 {b} {dz(sd)} 疑似呆值 {old}:"
                         + (f"今天已被真值 {new or '—'} 取代" if old != new else "今天仍是同一個值,上游未修正,該讀數仍不可信"))
    # 預測的適用日 vs 實際下一列
    later = [r["date"] for r in rows if r["date"] > ld]
    if later:
        actual = later[0]
        ok = actual == S.get("apply_date_pred", "")
        lines.append(f"{'✅' if ok else '⚠️'} 昨日說適用日 {dz(S['apply_date_pred'])},實際下一個交易日列是 {dz(actual)}"
                     + ("" if ok else "(中間有假期或缺列;昨日訊息的適用日寫錯,燈色本身不受影響)"))
    else:
        lines.append(f"⏳ 適用日 {dz(S['apply_date_pred'])} 尚未有新收盤,無法驗;燈色沿用")
    # 連續天數接得上嗎(僅當今天燈色日就是 T−1 燈色日的下一列)
    last = rows[-1]
    if later and last["date"] == later[0]:
        for key, sk in (("axis_short", "streak_short"), ("axis_disaster", "streak_disaster"), ("yellow", "streak_yellow")):
            if last[key] == "" or S.get(sk, "") == "":
                continue
            n_now = streak_info(rows, key, last[key])[0]
            expect = int(S[sk]) + 1 if S.get(key, "") == last[key] else 1
            lines.append(f"{'✅' if n_now == expect else '⚠️'} {key} 連續天數:昨日 {S[sk]} → 今日 {n_now}(預期 {expect})")
    # 後驗:凡 sent 列的燈色日 D 已有 D+5 個 SPX 交易日、且尚未後驗者。
    # 週末與假期會有好幾則訊息沿用同一個燈色日(例:10-02(五) 被週六、週日、週一三則沿用),
    # 後驗只看燈色日,所以同一個燈色日只印一行,但三列都標記完成。
    posthoc_seen = {}
    for row in sent:
        if row.get("posthoc_done") == "1":
            continue
        if row["light_date"] in posthoc_seen:
            if posthoc_seen[row["light_date"]]:
                done.append(row["generated_at_utc"])
            continue
        ph = spx_fwd5(row["light_date"])
        posthoc_seen[row["light_date"]] = ph is not None
        if ph is None:
            continue
        ratio = (ph["rv"] / ph["median"]) if (ph["median"] and ph["rv"] is not None) else None
        lights = f"短期軸 {row.get('axis_short') or '—'}、災難軸 {row.get('axis_disaster') or '—'}、黃 {word(row.get('yellow', ''))}"
        lines.append(f"📐 後驗 燈色日 {dz(row['light_date'])}({lights}):其後 5 個交易日({dz(ph['spx_day'])} 收盤→{dz(ph['end'])})"
                     f" SPX 實現波動 {ph['rv']:.1f}% 年化,為前一年 5 日 RV 中位({ph['median']:.1f}%)的 "
                     f"{ratio:.2f} 倍;{'出現' if ph['down2'] else '未出現'} −2% 單日。單日樣本只記錄,不作結論(手冊看整體倍率)")
        done.append(row["generated_at_utc"])
    return lines, done


# ----------------------------------------------------------------------------- 報告
def build_report(rows, health, today, sent=None):
    last, prev = rows[-1], (rows[-2] if len(rows) > 1 else None)
    d_last = date.fromisoformat(last["date"])
    expected_d = prev_weekday(today)                                   # 應有燈色日(香港早上 = 前一個美股交易日)
    stale_us = business_days_between(d_last, expected_d) if d_last < expected_d else 0
    warnings = []
    D, D1 = dz(d_last), (dz(prev["date"]) if prev else "—")          # 燈色日、前一列
    d_apply = next_weekday(d_last)                                     # 適用日(lag=1)

    # 1. 燈色與變化(變化 = 該燈上一個有值的列 對 燈色日 D,兩個日期都寫出)
    def prev_with(key):
        """燈色日之前、該欄最近一個有值的列(通常就是 D−1;D−1 空白時往前找,日期會寫在括號裡)。"""
        for r in reversed(rows[:-1]):
            if r.get(key, "") != "":
                return r
        return None

    def chg(key):
        lv = last.get(key, "")
        if lv == "":
            return ""   # 燈色日本身無資料,不談變化
        p = prev_with(key)
        if p is None or p[key] == lv:
            return ""
        return f"({dz(p['date'])} {word(p[key])} → {D} {word(lv)})"

    def run(key):
        """連續天數 + 起日,如「7 日(自 09-17(三) 起)」;途中有無資料列則註明。"""
        v = last.get(key, "")
        if v == "":
            return "—"
        n, start, skipped = streak_info(rows, key, v)
        note = "" if not skipped else f",途中 {len(skipped)} 列無資料不計:{'、'.join(dz(d) for d in skipped[-3:])}"
        return f"{n} 日(自 {dz(start)} 起{note})"

    def onoff(key):
        v = last.get(key, "")
        return {"1": "亮", "0": "滅", "": "無資料"}.get(v, v)

    v9, vx, v3 = f(last["vix9d"]), f(last["vix"]), f(last["vix3m"])
    s9, s3 = f(last["slope_9d"]), f(last["slope_3m"])
    cmp_short = (f"{D} VIX9D {v9:.2f} − 同日 VIX {vx:.2f} = {s9:+.2f}" if s9 is not None else "缺 VIX9D 或 VIX")
    cmp_dis = (f"{D} VIX {vx:.2f} − 同日 VIX3M {v3:.2f} = {s3:+.2f}" if s3 is not None else "缺 VIX 或 VIX3M")
    cmp_yel = f"各鳥 {D} 收盤 vs 自身截至 {D} 的 {WINDOW} 交易日 p90(明細見距門檻)"
    lights = [
        ("短期軸(VIX9D 系)", last["axis_short"] or "無資料", cmp_short, chg("axis_short"), run("axis_short")),
        ("災難軸(VIX3M 系)", last["axis_disaster"] or "無資料", cmp_dis, chg("axis_disaster"), run("axis_disaster")),
        ("黃(任一)", onoff("yellow"), cmp_yel, chg("yellow"), run("yellow")),
    ]
    yparts = [("VVIX", "yellow_vvix", "vvix", "vvix_p90"), ("MOVE", "yellow_move", "move", "move_p90"),
              ("AXVI", "yellow_axvi", "axvi", "axvi_p90")]

    # 2. 距門檻(每行寫明:哪一天的值、跟哪個窗口的 p90 比)
    dist = []
    if s9 is not None:
        dist.append(f"短期軸 slope_9d:{cmp_short}(>0 紅;−0.5~0 走平;其餘綠)→ {last['axis_short']}")
    if s3 is not None:
        dist.append(f"災難軸 slope_3m:{cmp_dis}(>0 深紅)→ {last['axis_disaster']}")

    def last_with(col):
        for r in reversed(rows):
            if r.get(col, "") != "":
                return r
        return None

    def dist_line(name, bird, col, pcol):
        r = last_with(col)
        if r is None:
            return f"{name}:無資料"
        v, p = f(r[col]), f(r.get(pcol))
        win = win_text(window_span(bird, r["date"]), name.split("(")[0])
        if r["date"] == last["date"]:
            head = f"{name}:{D} 值 {v:.2f}"
        else:
            head = f"{name}:{D} 列無值,不計入 {D} 燈色;最近 {dz(r['date'])} 值 {v:.2f}"
        if v is not None and p is not None and p != 0:
            return f"{head} vs p90 {p:.2f}({win})→ {'亮' if v > p else '滅'},距門檻 {(v / p - 1) * 100:+.1f}%"
        return f"{head}({win})"

    for name, flag, col, pcol in yparts:
        dist.append(dist_line(name, col, col, pcol))
    dist.append(dist_line("VHSI(試用)", "vhsi", "vhsi", "vhsi_p90"))

    # 3. 試用與 W1
    vv95, s9p90 = f(last["vvix_p95"]), f(last["slope9_p90"])
    vhr = last_with("vhsi")
    trials = [
        ("黃×2", "trial_yellow2", f"{D} 三隻黃鳥亮數 yellow_count = {last['yellow_count'] or '—'},≥2 亮"),
        ("深黃 VVIX p95", "trial_deep_yellow",
         f"{D} VVIX {last['vvix'] or '—'} vs p95 {last['vvix_p95'] or '—'}({win_text(window_span('vvix', last['date']), 'VVIX')})"),
        ("紅相對深度 p90", "trial_red_deep",
         f"{D} slope_9d {last['slope_9d'] or '—'} vs 其 p90 {last['slope9_p90'] or '—'}(窗口 = 截至 {D} 最近 {WINDOW} 個有 VIX9D 的交易日)"),
        ("9D對3M倒掛", "trial_red_9d3m",
         f"{D} VIX9D {v9:.2f} − 同日 VIX3M {v3:.2f} = {v9 - v3:+.2f},>0 亮" if (v9 is not None and v3 is not None) else "缺值"),
        ("黃VHSI p90", "trial_yellow_vhsi",
         (f"{D} 列無值;最近 {dz(vhr['date'])} VHSI {vhr['vhsi']} vs p90 {vhr.get('vhsi_p90') or '—'}"
          if vhr and vhr["date"] != last["date"] else
          f"{D} VHSI {last.get('vhsi') or '—'} vs p90 {last.get('vhsi_p90') or '—'}") if vhr else "無資料"),
    ]
    ratio, p10, w1, ratio_date, w1_span = w1_status(rows)
    w1_cmp = ""
    if ratio is not None:
        rr = last_with("vvix") if ratio_date == last["date"] else next(r for r in reversed(rows) if r["date"] == ratio_date)
        w1_cmp = (f"{dz(ratio_date)} VVIX {rr['vvix']} ÷ 同日 VIX {rr['vix']} = {ratio:.2f} vs p10 "
                  f"{'—' if p10 is None else round(p10, 2)}({'窗口未滿' if w1_span is None else f'窗口 {w1_span[0]}→{w1_span[1]}'})")

    # 4. 新鮮度
    fresh = []
    latest_by_bird = {}
    for b in BIRDS:
        for r in reversed(rows):
            if r.get(b, "") != "":
                latest_by_bird[b] = r["date"]
                break
        else:
            latest_by_bird[b] = "—"
    for b in BIRDS:
        lb = latest_by_bird[b]
        gap = (business_days_between(date.fromisoformat(lb), expected_d) if date.fromisoformat(lb) < expected_d else 0) \
            if lb != "—" else None
        fresh.append((b, lb, gap))
        if b in US_BIRDS and gap is not None and gap > 1:
            warnings.append(f"{b} 最後日期 {lb},落後應有燈色日 {expected_d} 共 {gap} 個交易日")
        if b in ("axvi", "vhsi") and gap is not None and gap > 2:
            warnings.append(f"{b} 最後日期 {lb},落後應有燈色日 {expected_d} 共 {gap} 個交易日(亞洲時段允許 1–2 日)")
    if stale_us >= 1:
        warnings.append(f"燈色表最新列 {dz(d_last)} ≠ 應有燈色日 {dz(expected_d)},差 {stale_us} 個交易日:"
                        f"上游未更新,或其間為美股假期(假期則屬正常);燈色沿用 {dz(d_last)}")
    holiday_like = [r["date"] for r in rows[-30:] if r["vix"] != "" and r["vix9d"] == "" and r["vix3m"] == ""]
    for hd in holiday_like:
        warnings.append(f"{dz(hd)} 有 VIX 值但無 VIX9D、VIX3M(疑似美股假期只剩一根 bar):該列燈色空白,"
                        f"不計入連續天數、不作「變化」的比較基準")
    stale = stale_prints()
    for b, dt, c, pdt, pc in stale:
        warnings.append(f"{b} {dz(dt)} 疑似呆值:開高低收四價相同({c:.2f})且等於前一列 {dz(pdt)} 收盤({pc:.2f}),"
                        f"{dt} 讀數可能是舊值填充")

    # 5. 健康檢查
    checks = []
    dates = [r["date"] for r in rows]
    checks.append(("列數", f"{len(rows)}", True))
    mono = all(dates[i] < dates[i + 1] for i in range(len(dates) - 1))
    checks.append(("日期單調遞增", "是" if mono else "否", mono))
    dup = len(dates) != len(set(dates))
    checks.append(("無重複日期", "否" if dup else "是", not dup))
    missing = [b for b in BIRDS if last.get(b, "") == ""]
    checks.append(("最新列各鳥齊全(亞洲鳥可慢一日)", "是" if not missing else "缺 " + "、".join(missing),
                   all(m in ("axvi", "vhsi") for m in missing)))
    checks.append(("無呆值(四價相同且等於前日收盤)", "是" if not stale else "疑似:" + "、".join(b for b, *_ in stale),
                   not stale))
    for k, v in health.items():
        checks.append((f"工作流:{k}", v, v.lower() in ("ok", "skipped", "pass")))
    bad = [c for c in checks if not c[2] and not c[0].startswith("無呆值")]   # 呆值已各自成一則警告,不重複
    if bad:
        warnings.extend(f"健康檢查未過:{c[0]} = {c[1]}" for c in bad)

    # 6. T−1 訊息回驗
    verify_lines, posthoc_done = verify_previous(rows, sent or [], today)
    if any(x.startswith("❌") for x in verify_lines):
        warnings.append("T−1 訊息回驗有 ❌:昨日訊息的數值或燈色在今天的表上已不成立,見「T−1 訊息回驗」")

    # ---- Markdown
    md = [f"# 金絲雀每日總結 — 燈色日 {last['date']}",
          f"產生於 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
          f"(香港 {datetime.now(HKT).strftime('%Y-%m-%d %H:%M')});"
          f"此燈色只能用於 **{last['date']} 之後**的交易日(lag=1),第一個適用日 **{d_apply.isoformat()}**。\n"]
    if warnings:
        md.append("## ⚠️ 警告\n")
        md += [f"- {w}" for w in warnings]
        md.append("")
    md.append("## 0. 日期對照(每個燈號用哪幾天、跟哪幾天比)\n")
    md.append("| 角色 | 日期 | 用途 |\n|---|---|---|")
    md.append(f"| 報告日 | {dz(today)} | 產出本報告的香港日期(工作流 22:30 UTC 執行,已是香港翌日早上) |")
    md.append(f"| 應有燈色日 | {dz(expected_d)} | 報告日之前最後一個美股交易日;「新鮮度」落後交易日以此日起算,燈色日 D 應等於它 |")
    md.append(f"| 燈色日 D | **{D}** | 所有正式燈以 D 當日收盤計算:短期軸 = D 的 VIX9D − D 的 VIX;災難軸 = D 的 VIX − D 的 VIX3M;"
              f"黃 = 各鳥 D 值 vs 各鳥自身截至 D 的 {WINDOW} 交易日 p90(含 D) |")
    md.append(f"| 前一列 D−1 | {D1} | 「變化」欄 = 該燈上一個有值的列(通常即 D−1,空白則再往前,括號內寫明日期)對 D 列;"
              f"呆值檢查 = D 的四價 對 D−1 的收盤 |")
    md.append(f"| 適用日 | {dz(d_apply)} | D 之後第一個交易日(lag=1;以週一至五估,遇假期順延)。此燈只管適用日起的 5 個交易日 |")
    md.append(f"| 亞洲鳥 AXVI / VHSI | 各自最近值日 | 亞洲時段(澳洲、香港)收盤,天生比美鳥慢一日;D 列無值時**不計入** D 的黃燈,只括注最近值供參考 |")
    md.append("")
    md.append("## 1. 燈色\n")
    md.append("| 軸 | 今日 | 比較(哪幾天) | 變化(前一列 → 燈色日) | 連續(起日) |\n|---|---|---|---|---|")
    for name, val, cmp_, c, n in lights:
        md.append(f"| {name} | **{val}** | {cmp_} | {c or '—'} | {n} |")
    md.append("")
    md.append("黃鳥明細:" + ";".join(f"{n} {onoff(flag)}" for n, flag, _, _ in yparts)
              + f";yellow_count = {last['yellow_count'] or '—'}")
    md.append("")
    md.append("## 2. 距門檻\n")
    md += [f"- {x}" for x in dist]
    md.append("")
    md.append("## 3. 試用層與觀察名單(只記錄,無警報權,不得據此改變響應)\n")
    md.append("| 項目 | 今日 | 比較(哪幾天) | 變化(前一列 → 燈色日) | 連續(起日) |\n|---|---|---|---|---|")
    for name, key, cmp_ in trials:
        md.append(f"| 試用:{name} | {onoff(key)} | {cmp_} | {chg(key) or '—'} | {run(key)} |")
    if ratio is not None:
        w1txt = "無資料(窗口未滿)" if w1 is None else ("亮" if w1 else "滅")
        md.append(f"| 觀察 W1:VVIX/VIX < p10 | {w1txt} | {w1_cmp} | — | 樣本外累積中(自 2026-09-27) |")
    md.append("")
    md.append("## 4. 數據新鮮度\n")
    md.append(f"| 鳥 | 最後日期 | 落後交易日(至應有燈色日 {dz(expected_d)}) |\n|---|---|---|")
    for b, lb, gap in fresh:
        md.append(f"| {b} | {lb} | {'—' if gap is None else gap} |")
    md.append("")
    md.append("## 5. 健康檢查\n")
    md.append("| 項目 | 結果 | 狀態 |\n|---|---|---|")
    for k, v, ok in checks:
        md.append(f"| {k} | {v} | {'✅' if ok else '❌'} |")
    md.append("")
    md.append("## 6. T−1 訊息回驗(昨天發出的訊息,今天對照重產的表)\n")
    md += [f"- {x}" for x in verify_lines]
    md.append("")
    if last["axis_short"] == "紅" or last["axis_disaster"] == "深紅":
        md.append("## 7. §3 註記(紅或深紅亮起時展示)\n")
        md.append("```\n" + RED_NOTE + "\n```")
        md.append("")
    md.append("---\n口徑:`CANARY_PLAYBOOK.md` §2;欄位說明 `canary/README.md`;長期紀錄 `canary/daily_log.csv`。")

    # ---- Telegram 每日總結(白話、emoji;每天必發,含週末)
    L = {"綠": "🟢", "走平": "⚪", "紅": "🔴", "深紅": "🟣", "": "❔"}
    a_s, a_d = last["axis_short"], last["axis_disaster"]
    ylit = [n for n, flag, _, _ in yparts if last[flag] == "1"]
    weekend_note = ""
    if stale_us == 0 and today.weekday() in (6, 0):
        weekend_note = f"(香港今天{'週日' if today.weekday() == 6 else '週一早上'},美股尚無新收盤,燈色沿用 {last['date']})"

    # 白話總結
    if a_s == "" and a_d == "":
        plain = (f"❔ 燈色日 {D} 缺 VIX9D 與 VIX3M 讀數(多半是美股假期只剩 VIX 一根 bar),今天判不了燈。"
                 f"請沿用上一個有燈色的交易日,不要把空白當綠燈。")
    elif a_d == "深紅":
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
        v = last.get(key, "")
        return {"1": "🔔亮", "0": "滅", "": "—"}.get(v, v)

    tg = [f"🐤 金絲雀每日總結 📅 {today.isoformat()}",
          f"燈色日 {last['date']}{weekend_note}",
          f"⏰ 此燈色用於 {last['date']} 之後的交易日(lag=1),第一個適用日 {dz(d_apply)}",
          "",
          "📆 日期對照(每個燈用哪幾天)",
          f"• 燈色日 D = {D}:所有燈都用這一天的收盤算",
          f"• 短期軸 = D 的 VIX9D 減 D 的 VIX;災難軸 = D 的 VIX 減 D 的 VIX3M(同一天兩隻鳥相減)",
          f"• 黃燈 = 各鳥 D 的值,對比該鳥自己截至 D 的 {WINDOW} 個交易日 p90(窗口起迄見距門檻)",
          f"• 「變化」= 該燈上一個有值的列(通常是前一列 {D1})對 燈色日 {D},括號內寫明兩個日期;連續天數括注起日,途中無資料列不計並列出",
          f"• 亞洲鳥 AXVI / VHSI 若 {D} 列無值,不計入 {D} 黃燈,只括注最近值日期",
          f"• 報告日 {dz(today)}(香港);應有燈色日 {dz(expected_d)};適用日 {dz(d_apply)} = D 之後第一個交易日",
          "",
          "🚦 三軸",
          f"{L.get(a_s, '❔')} 短期軸(一週 vs 一月保險):{a_s or '無資料'},{run('axis_short')}"
          + (f" {chg('axis_short')}" if chg('axis_short') else "") + f"|{cmp_short}",
          f"{L.get(a_d, '❔')} 災難軸(一月 vs 三月保險):{a_d or '無資料'},{run('axis_disaster')}"
          + (f" {chg('axis_disaster')}" if chg('axis_disaster') else "") + f"|{cmp_dis}",
          f"🟡 側翼鳥:{'、'.join(ylit) if ylit else '全滅'}(黃燈 {run('yellow')})"
          + (f" {chg('yellow')}" if chg('yellow') else "") + f"|{cmp_yel}",
          "",
          "📏 距門檻(值日 vs 窗口)",
          *[f"• {x}" for x in dist],
          "",
          "🧪 試用層與觀察名單(無警報權,只記錄)",
          *[f"• {n} {onoff_emoji(k)}|{c}" for n, k, c in trials],
          ]
    if ratio is not None:
        tg.append(f"• W1 VVIX/VIX<p10:{'🔔亮' if w1 else '滅' if w1 is not None else '—'}|{w1_cmp}")
    tg += ["",
           "🩺 數據與健康",
           f"• 新鮮度(各鳥最後日期,落後至應有燈色日 {dz(expected_d)} 的交易日數):"
           + "、".join(f"{b} {lb}(落後 {'—' if gap is None else gap})" for b, lb, gap in fresh if b in ("vix", "vvix", "move", "axvi", "vhsi")),
           "• 健康檢查:" + ("全過 ✅" if all(ok for _, _, ok in checks) else "有未過 ❌,見下"),
           ]
    tg += ["", "🔁 回驗昨日訊息(T−1)"] + [f"• {x}" for x in verify_lines]
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
        "trial_yellow_vhsi": last.get("trial_yellow_vhsi", ""),
        "w1_fear_spike": "" if w1 is None else ("1" if w1 else "0"),
        "vvix_vix_ratio": "" if ratio is None else f"{ratio:.4f}",
        "ratio_p10": "" if p10 is None else f"{p10:.4f}",
        **{b: last.get(b, "") for b in BIRDS},
        "slope_9d": last["slope_9d"], "slope_3m": last["slope_3m"],
        "stale_us_days": str(stale_us),
        "stale_print": ";".join(b for b, *_ in stale),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }
    sent_row = {
        "report_date": today.isoformat(), "generated_at_utc": log_row["generated_at_utc"],
        "light_date": last["date"], "apply_date_pred": d_apply.isoformat(),
        "streak_short": "" if last["axis_short"] == "" else str(streak_info(rows, "axis_short", last["axis_short"])[0]),
        "streak_disaster": "" if last["axis_disaster"] == "" else str(streak_info(rows, "axis_disaster", last["axis_disaster"])[0]),
        "streak_yellow": "" if last["yellow"] == "" else str(streak_info(rows, "yellow", last["yellow"])[0]),
        "stale_print": log_row["stale_print"],
        "stale_detail": ";".join(f"{b}@{dt}@{c:.2f}" for b, dt, c, _, _ in stale),
        "tg_sha1": hashlib.sha1(tg_text.encode("utf-8")).hexdigest()[:12],
        "posthoc_done": "0",
        **{k: last.get(k, "") for k in COMPARE_LIGHTS + COMPARE_VALUES},
    }
    return "\n".join(md) + "\n", tg_text, log_row, warnings, sent_row, posthoc_done


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


def append_sent(sent, row, posthoc_done):
    """只追加;同時把已完成後驗的舊列標記 posthoc_done=1(唯一允許改動舊列的欄位)。"""
    for r in sent:
        if r.get("generated_at_utc") in posthoc_done:
            r["posthoc_done"] = "1"
    sent.append(row)
    with open(OUT_SENT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SENT_FIELDS, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(sent)
    return len(sent)


def main():
    ap = argparse.ArgumentParser(description="金絲雀每日總結報告")
    ap.add_argument("--health", nargs="*", default=[], help="工作流步驟狀態,如 refresh=ok build=ok labs=skipped")
    ap.add_argument("--today", default=None, help="覆寫報告日(香港日期,YYYY-MM-DD),測試用")
    ap.add_argument("--dry-run", action="store_true", help="只寫 DAILY_REPORT.md / tg_daily.txt,不動 daily_log / sent_log")
    args = ap.parse_args()
    health = dict(h.split("=", 1) for h in args.health if "=" in h)
    today = date.fromisoformat(args.today) if args.today else hk_today()   # 報告日 = 香港日期

    rows = load_table()
    sent = load_sent()
    md, tg, log_row, warnings, sent_row, posthoc_done = build_report(rows, health, today, sent)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(OUT_TG, "w", encoding="utf-8") as fh:
        fh.write(tg + "\n")
    print(md)
    if args.dry_run:
        print("[daily_report] --dry-run:未寫 daily_log.csv / sent_log.csv")
    else:
        n = append_log(log_row)
        m = append_sent(sent, sent_row, posthoc_done)
        print(f"[daily_report] 已寫入 DAILY_REPORT.md、tg_daily.txt;daily_log.csv 共 {n} 列;sent_log.csv 共 {m} 列;警告 {len(warnings)} 則")
    if warnings:
        print("[daily_report] " + " | ".join(warnings), file=sys.stderr)


if __name__ == "__main__":
    main()
