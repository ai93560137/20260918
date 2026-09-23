#!/usr/bin/env python3
"""全量歷史比對：拿第二來源的**整段歷史**逐筆比 yfinance 收市價（不只最新一天）。

    python3 scripts/xcheck_history.py --market us --budget-min 15
    python3 scripts/xcheck_history.py --market jp --budget-min 25

- us：Nasdaq.com historical API（一次請求給 10 年日線；只有仍上市的代碼，已下市的沒有）
  ——比對每一個交易日的收市價
- jp：Yahoo!ファイナンス 歷史頁（Yahoo Japan，與 yfinance 背後的美國 Yahoo 不同數據商）
  - 月線 1995 起全段：每月最後交易日的「調整後終値」（只按拆股還原）vs 我們的 Close
    （同樣只按拆股還原）——回測用的就是月底價
  - 日線最近 20 個交易日：逐日比
  日線全段要 ~8.5 萬頁請求，做不到；月線全段一檔約 19 頁

有時間上限，每次從「從沒比過 / 最久沒比」的代碼開始，進度存在
data/equities/<market>/_xcheck.json，排程每天推進，全部比完後自動輪回重比。
收市價差 > 1% 算不符；check_equities_quality.py 讀這個檔報告覆蓋率與不符（🔴/🟡）。
"""
import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402

TOL = 0.01
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
NQ = dict(UA, **{"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
                 "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"})
ETFS = {"SPY", "QQQ", "DIA", "RSP"}


def num(s: str) -> float | None:
    try:
        return float(str(s).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def us_series(s: requests.Session, t: str) -> dict[date, float] | None:
    """Nasdaq 10 年日線收市 {date: close}；沒有這個代碼回 None。"""
    sym = t.replace("-", ".")   # Yahoo BRK-B -> Nasdaq BRK.B
    r = s.get(f"https://api.nasdaq.com/api/quote/{sym}/historical", timeout=60,
              params={"assetclass": "etf" if t in ETFS else "stocks", "fromdate": "1995-01-01",
                      "todate": date.today().isoformat(), "limit": "20000"})
    r.raise_for_status()
    d = r.json().get("data")
    rows = ((d or {}).get("tradesTable") or {}).get("rows") or []
    if not rows:
        return None
    out = {}
    for x in rows:
        m, dd, y = x["date"].split("/")
        c = num(x["close"])
        if c:
            out[date(int(y), int(m), int(dd))] = c
    return out


class Blocked(Exception):
    """第二來源拒答/限流（非 200、或頁面沒有 histories 欄位）——不能當成「沒有數據」記錄。"""


YJ_PAUSE = 2.5   # 每頁間隔秒數（2026-09-23 實測：連續快抓約 40 頁後 Yahoo!ファイナンス 開始回空頁）


def yj_page(s: requests.Session, t: str, params: dict) -> list[dict]:
    for wait in (0, 30, 60, 120):
        if wait:
            print(f"  {t}: 疑似限流，等 {wait}s 重試", file=sys.stderr)
            time.sleep(wait)
        try:
            r = s.get(f"https://finance.yahoo.co.jp/quote/{t}/history", params=params, timeout=45)
        except requests.RequestException:
            continue
        if r.status_code == 404:
            return []   # 真的沒有這個代碼的頁面（已下市）
        if r.status_code != 200:
            continue
        u = r.text.replace('\\"', '"')
        i = u.find('"histories":')
        if i < 0:
            continue    # 頁面沒有數據欄位 = 被擋或格式變了，不是「沒有數據」
        return json.JSONDecoder().raw_decode(u[i + len('"histories":'):])[0]
    raise Blocked(f"{t} {params}")


def yj_pages(s: requests.Session, t: str, params: dict, max_pages: int) -> list[dict]:
    rows = []
    for page in range(1, max_pages + 1):
        arr = yj_page(s, t, dict(params, page=page))
        time.sleep(YJ_PAUSE)
        if not arr:
            break
        rows += arr
        if len(arr) < 20:
            break
    return rows


def find_breaks(ours: dict[date, float], theirs: dict[date, float],
                actions: list[date]) -> tuple[dict[date, float], list[dict]]:
    """兩來源價格比值（對方/我們）的「階梯」＝其中一方對公司行動（分拆、股份交換、ADR 比例變動…）
    做了回溯調整、另一方沒做或倍數不同。找出每個階梯並分類：
    - yahoo_adjusted：我們的 actions.csv 在該日 ±5 天內有記錄（Yahoo 把分拆記成非整數拆股並回溯
      調整，總回報正確）——調整方法不同，不是數據錯
    - yahoo_unadjusted：我們沒有任何記錄、對方有調——我們的價格在該日有一個**假的跳動**，
      總回報會失真（例：BIIB 2017 分拆 Bioverativ），要報告
    把對方階梯前的價格按階梯倍數對齊後回傳，剩下的差異才算逐筆不符。從最近的階梯往回做。"""
    th = dict(theirs)
    days = sorted(d for d in th if d in ours and ours[d] > 0 and th[d] > 0)
    breaks = []
    W = 10
    i = len(days) - W
    while i >= W:
        before = [th[d] / ours[d] for d in days[i - W:i]]
        after = [th[d] / ours[d] for d in days[i:i + W]]
        rb, ra = sorted(before)[W // 2], sorted(after)[W // 2]
        step = ra / rb
        flat = max(before) / min(before) < 1.01 and max(after) / min(after) < 1.01
        if flat and abs(step - 1) > 0.01:
            e = days[i]
            near = any(abs((a - e).days) <= 5 for a in actions)
            breaks.append({"date": e.isoformat(), "step": round(1 / step, 4),
                           "type": "yahoo_adjusted" if near else "yahoo_unadjusted"})
            for d in th:
                if d < e:
                    th[d] *= step          # 對方階梯前的價格對齊到階梯後的比值水準
            i -= W                          # 同一個階梯不重複認
        else:
            i -= 1
    return th, breaks


def compare(ours: dict[date, float], theirs: dict[date, float]) -> dict:
    n = bad = 0
    worst, examples = 0.0, []
    for d, c2 in sorted(theirs.items()):
        c1 = ours.get(d)
        if c1 is None or c1 <= 0 or c2 <= 0:
            continue
        n += 1
        diff = c2 / c1 - 1
        if abs(diff) > TOL:
            bad += 1
            if len(examples) < 5:
                examples.append(f"{d} 我們 {c1:g} vs 對方 {c2:g}（{diff:+.1%}）")
        worst = max(worst, abs(diff))
    return {"n_cmp": n, "n_bad": bad, "max_diff": round(worst, 5), "examples": examples}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=["us", "jp"], required=True)
    ap.add_argument("--budget-min", type=float, default=15)
    args = ap.parse_args()
    m = args.market
    base = md.V2_DIR / m
    state_path = base / "_xcheck.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    status = json.loads((base / "_fetch_status.json").read_text(encoding="utf-8"))
    tickers = [t for t, v in status.items() if v.get("rows") and not t.startswith("^")]
    tickers.sort(key=lambda t: state.get(t, {}).get("checked", ""))   # 沒比過的（空字串）最先
    today = datetime.now(timezone.utc).date().isoformat()
    s = requests.Session()
    s.headers.update(NQ if m == "us" else dict(UA, **{"Accept-Language": "ja"}))
    started, done = time.monotonic(), 0
    for t in tickers:
        if time.monotonic() - started > args.budget_min * 60:
            break
        ours = {r["Date"]: r["Close"] for r in md.load_ohlcv(t)}
        try:
            if m == "us":
                theirs = us_series(s, t)
                rec = {"source": "nasdaq 10y daily"}
                if theirs is None:
                    rec.update(n_cmp=0, n_bad=0, max_diff=0, examples=[], note="第二來源沒有此代碼（已下市/改代碼）")
                else:
                    raw = compare(ours, theirs)
                    divs, splits = md.load_actions(t)
                    th, breaks = find_breaks(ours, theirs, [d for d, _ in splits])
                    rec.update(compare(ours, th), span=f"{min(theirs)}~{max(theirs)}",
                               n_bad_raw=raw["n_bad"], breaks=breaks)
            else:
                monthly = yj_pages(s, t, {"from": "19950101", "to": today.replace("-", ""), "timeFrame": "m"}, 25)
                daily = yj_pages(s, t, {"timeFrame": "d"}, 1)
                # 月線：每月最後一個交易日的收市；對方用「調整後終値」（values[5]，只按拆股還原）
                last_of = {}
                for d in sorted(ours):
                    last_of[(d.year, d.month)] = d
                th_m = {}
                for h in monthly:
                    y, mo, _ = map(int, h["date"].split("-"))
                    d = last_of.get((y, mo))
                    v = num(h["values"][5]["value"])
                    if d and v and (y, mo) != (int(today[:4]), int(today[5:7])):   # 本月未完不比
                        th_m[d] = v
                th_d = {}
                for h in daily:
                    v = num(h["values"][5]["value"])
                    if v:
                        th_d[date.fromisoformat(h["date"])] = v
                cm, cd = compare(ours, th_m), compare(ours, th_d)
                if not monthly and not daily:
                    rec = {"source": "yahoo.co.jp", "n_cmp": 0, "n_bad": 0, "max_diff": 0, "examples": [],
                           "note": "第二來源沒有此代碼（已下市/改代碼）"}
                else:
                    rec = {"source": "yahoo.co.jp 月線全段 + 最近 20 日",
                           "n_cmp": cm["n_cmp"] + cd["n_cmp"], "n_bad": cm["n_bad"] + cd["n_bad"],
                           "max_diff": max(cm["max_diff"], cd["max_diff"]),
                           "examples": (cm["examples"] + cd["examples"])[:5],
                           "span": f"{min(th_m) if th_m else '-'}~{max(th_d) if th_d else '-'}"}
        except Blocked as exc:
            print(f"STOP 第二來源持續拒答（{exc}），保存進度、下輪再續", file=sys.stderr)
            break
        except Exception as exc:
            print(f"WARN {t}: {exc}", file=sys.stderr)
            time.sleep(2)
            continue
        rec["checked"] = today
        state[t] = rec
        done += 1
        if rec.get("n_bad"):
            print(f"{t}: {rec['n_bad']}/{rec['n_cmp']} 筆不符，最大 {rec['max_diff']:.1%}；例 {rec['examples'][:2]}")
        time.sleep(0.4 if m == "us" else 0.2)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    covered = sum(1 for t in tickers if t in state)
    print(f"本輪比對 {done} 檔；累計覆蓋 {covered}/{len(tickers)} 檔、{sum(v.get('n_cmp', 0) for v in state.values()):,} 筆、"
          f"不符 {sum(v.get('n_bad', 0) for v in state.values()):,} 筆")


if __name__ == "__main__":
    main()
