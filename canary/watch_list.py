#!/usr/bin/env python3
# =============================================================================
# 金絲雀「👀 留神清單」(觀察名單 W2,2026-10-31 使用者要求「自己額外加嘅判斷寫成規則,放網頁」)
# -----------------------------------------------------------------------------
# 背景:10-30(五) 盤中短期軸到紅、災難軸到深紅,收市回落到走平/綠。正式燈只看收市,
# 金絲雀工作階段額外留意到幾件事,使用者要求寫成固定規則、每日計算、放金絲雀網頁與 Telegram。
#
# **觀察名單,無警報權**:不改任何燈色、不改白話一句的行動建議;只把「留神」講清楚是哪幾條事實。
# **事後提出、證據打折**:四條規則與閾值是看過 10-16〜10-30 這段行情才寫的,不是預先登記的研究;
# 自 2026-10-31 起每日存 canary/watch_log.csv,累積 ≥ 126 個交易日樣本外,再用手冊 §3 口徑考核
# (SPX 5 日 RV 倍率、誤報、與現役燈 Jaccard),未過就淘汰。閾值寫死,不調參。
#
#   L1 盤中升溫頻密  燈色日 D 在內最近 10 個有燈色的交易日裡,短期軸「收市紅」或「盤中預警到紅」的日數 ≥ 3
#                    (盤中預警來自 canary/alert_log.csv,2026-10-23 起才有,之前的日子只數收市紅)
#   L2 盤中驚收市靜  D 的 VIX 當日最高 − 收市 ≥ 3.0 點
#   L3 VVIX 盤中過深黃  D 的 VVIX 當日最高 > D 的 VVIX 滾動 252 日 p95(與試用層「深黃」同一條線)
#   L4 實際波動偏高  posthoc_log.csv 最新一列(燈色日 D 之前 5 個交易日那天)的 SPX 5 日 RV ÷ 前一年中位 ≥ 1.3
#   綜合:亮 ≥ 2 條 → 「👀 加強留神」;否則「平常」。
# 純標準庫。由 daily_report.py 呼叫;也可單獨跑:python3 canary/watch_list.py
# =============================================================================
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data_external")
ALERT_LOG = os.path.join(HERE, "alert_log.csv")
POSTHOC = os.path.join(HERE, "posthoc_log.csv")
OUT_JSON = os.path.join(HERE, "watch_status.json")
OUT_LOG = os.path.join(HERE, "watch_log.csv")

L1_WINDOW, L1_MIN = 10, 3
L2_GAP = 3.0
L4_RATIO = 1.3
LEVEL_MIN = 2
NOTE = "觀察名單 W2,無警報權;不改燈色。2026-10-31 事後提出、證據打折,樣本外累積中(≥126 交易日後考核)。"
LOG_FIELDS = ["light_date", "lit", "level", "L1", "L1_days", "L2", "vix_high", "vix_close",
              "L3", "vvix_high", "vvix_p95", "L4", "posthoc_date", "posthoc_ratio", "generated_at_utc"]
WEEKDAY_ZH = "一二三四五六日"


def _dz(iso):
    from datetime import date
    d = date.fromisoformat(iso)
    return f"{iso[5:]}({WEEKDAY_ZH[d.weekday()]})"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _high_close(bird, day, data_dir=DATA):
    for r in reversed(_read_csv(os.path.join(data_dir, f"{bird}_daily.csv"))):
        if r.get("Date", "")[:10] == day:
            return _f(r.get("High")), _f(r.get("Close"))
    return None, None


def compute(rows, alert_rows=None, posthoc_rows=None, data_dir=DATA):
    """rows = canary_daily.csv 列(依日期排序)。回傳 dict,可直接寫 JSON。"""
    rows = [r for r in rows if r.get("axis_short")]
    alert_rows = _read_csv(ALERT_LOG) if alert_rows is None else alert_rows
    posthoc_rows = _read_csv(POSTHOC) if posthoc_rows is None else posthoc_rows
    last = rows[-1]
    d = last["date"]

    # L1
    win = [r["date"] for r in rows[-L1_WINDOW:]]
    red_days = {r["date"] for r in rows[-L1_WINDOW:] if r["axis_short"] == "紅"}
    red_days |= {a["day"] for a in alert_rows
                 if a.get("kind", "").startswith("盤中預警") and a.get("axis") == "短期軸"
                 and a.get("to") == "紅" and a.get("day") in win}
    l1_days = sorted(red_days)
    l1 = len(l1_days) >= L1_MIN

    # L2
    vh, vc = _high_close("vix", d, data_dir)
    l2_gap = None if vh is None or vc is None else vh - vc
    l2 = l2_gap is not None and l2_gap >= L2_GAP

    # L3
    wh, _ = _high_close("vvix", d, data_dir)
    p95 = _f(last.get("vvix_p95"))
    l3 = wh is not None and p95 is not None and wh > p95

    # L4
    ph = posthoc_rows[-1] if posthoc_rows else None
    ratio = _f(ph.get("ratio")) if ph else None
    l4 = ratio is not None and ratio >= L4_RATIO

    rules = [
        {"id": "L1", "name": "盤中升溫頻密", "lit": l1,
         "rule": f"最近 {L1_WINDOW} 個交易日(含 {_dz(d)}),短期軸收市紅或盤中到紅 ≥ {L1_MIN} 日",
         "value": f"{len(l1_days)} 日" + (f"({'、'.join(_dz(x) for x in l1_days)})" if l1_days else ""),
         "window": f"{_dz(win[0])}→{_dz(win[-1])}"},
        {"id": "L2", "name": "盤中驚、收市靜", "lit": l2,
         "rule": f"{_dz(d)} VIX 當日最高 − 收市 ≥ {L2_GAP:.1f} 點",
         "value": "缺值" if l2_gap is None else f"最高 {vh:.2f} − 收市 {vc:.2f} = {l2_gap:.2f}"},
        {"id": "L3", "name": "VVIX 盤中過深黃線", "lit": l3,
         "rule": f"{_dz(d)} VVIX 當日最高 > 自身 252 日 p95",
         "value": "缺值" if wh is None or p95 is None else f"最高 {wh:.2f} vs p95 {p95:.2f}"},
        {"id": "L4", "name": "實際波動偏高", "lit": l4,
         "rule": f"最新後驗(燈色日後 5 個交易日 SPX 實現波動 ÷ 前一年中位)≥ {L4_RATIO}",
         "value": "未有後驗" if ratio is None else f"燈色日 {_dz(ph['light_date'])} 之後 5 日 = {ratio:.2f} 倍"},
    ]
    lit = sum(r["lit"] for r in rules)
    return {
        "light_date": d,
        "lit": lit,
        "level": "加強留神" if lit >= LEVEL_MIN else "平常",
        "rules": rules,
        "note": NOTE,
        "_log": {"light_date": d, "lit": lit, "level": "加強留神" if lit >= LEVEL_MIN else "平常",
                 "L1": int(l1), "L1_days": ";".join(l1_days),
                 "L2": int(l2), "vix_high": "" if vh is None else f"{vh:.2f}", "vix_close": "" if vc is None else f"{vc:.2f}",
                 "L3": int(l3), "vvix_high": "" if wh is None else f"{wh:.2f}", "vvix_p95": "" if p95 is None else f"{p95:.2f}",
                 "L4": int(l4), "posthoc_date": ph["light_date"] if ph else "",
                 "posthoc_ratio": "" if ratio is None else f"{ratio:.4f}"},
    }


def tg_lines(status):
    head = (f"👀 留神清單(觀察名單,無警報權)|{status['level']}:亮 {status['lit']}/4 條"
            f"(≥ {LEVEL_MIN} 條 = 加強留神)")
    body = [f"• {r['id']} {r['name']} {'🔔亮' if r['lit'] else '滅'}|{r['value']}" for r in status["rules"]]
    return [head] + body


def md_lines(status):
    out = [f"## 3b. 👀 留神清單(觀察名單 W2,無警報權)\n",
           f"**{status['level']}**:亮 {status['lit']}/4 條(≥ {LEVEL_MIN} 條 = 加強留神)。{status['note']}\n",
           "| 規則 | 燈 | 條件 | 讀數 |\n|---|---|---|---|"]
    for r in status["rules"]:
        out.append(f"| {r['id']} {r['name']} | {'亮' if r['lit'] else '滅'} | {r['rule']} | {r['value']} |")
    out.append("")
    return out


def write_outputs(status, generated_at_utc, json_path=OUT_JSON, log_path=OUT_LOG):
    pub = {k: v for k, v in status.items() if not k.startswith("_")}
    pub["generated_at_utc"] = generated_at_utc
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(pub, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    row = dict(status["_log"], generated_at_utc=generated_at_utc)
    old = [r for r in _read_csv(log_path) if r.get("light_date") != row["light_date"]]   # 同燈色日重跑覆蓋該列
    with open(log_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        w.writeheader()
        for r in old + [row]:
            w.writerow({k: r.get(k, "") for k in LOG_FIELDS})


if __name__ == "__main__":
    st = compute(_read_csv(os.path.join(HERE, "canary_daily.csv")))
    print("\n".join(tg_lines(st)))
