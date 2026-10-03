"""「這段時間的高位／低位已經出現」的判斷：回測（日、週、月）。

問題：一段時間（交易日／週／月）進行中，什麼時候可以說「這段時間的高位已經出現、之後不會再高」？
每一根日內 K 線收市時，用當時已知的資料判斷一次；每邊每段只通知第一次。

交易日 = 香港時間 09:00 至翌日 09:00（日市 09:15–16:30 加當晚夜市 17:15–翌日 03:00）。
週 = 同一個 ISO 週的交易日（週一日市至週五夜市）；月 = 交易日日期同一個月。

數據（GCS，需要 GCP_SA_KEY）：
  archive/futu_k_15m（或 k_60m）/HK.HSI_FRONT/<日期>.json   本地腳本 v9 --export-intraday
  futu/daily/HK.HSI_FRONT.json                              交易日 K（逐日前推的 HAR 波幅預測 R̂）

當時已知的量（不偷看）：
  σ_日 = 當天 R̂ ÷ 1.596 ÷ 昨收（布朗運動：期望波幅 ≈ 1.596σ）
  剩餘變異 = σ_日² ×（當天剩餘時段的變異比例 ＋ 這段時間剩下的整個交易日數）
  各時段的變異比例由之前最多 250 個交易日估；剩下幾個交易日由交易日曆決定（事前已公佈）。
  一段時間的預期波幅 R̂_段 = 第一天的 R̂ × √(交易日數)。

策略（低位對稱）：
  A 耗盡＋回落：已走波幅 ≥ α×R̂_段 且 價格離最高位 ≥ β×R̂_段。
  B 反射原理：之後再創新高的機率 = 2×(1 − Φ(距離 ÷ σ_剩餘))，低於 p 就通知。
  C 時間點：日 = 12:00／16:30；週 = 第 2／3／4 個交易日收市；月 = 第 5／10／15 個交易日收市；
            到時價格離最高位 ≥ β×R̂_段 就通知。

評分（測試期，只算有通知的段）：
  準確率 = 通知之後到這段結束，高位都沒有再被突破（附 95% Wilson 區間）。
  通知率、錯時再突破多少點、通知時離高位多少點、通知的中位時間、離真正高位出現多久。
  參數在前半段挑（通知率 ≥ 30% 中準確率最高），後半段報成績。

用法：python3 research/hsi_futures_range/high_low_in.py [--ktype K_15M] [--json 本地快取] [--periods day,week,month]
"""
import argparse, json, math, sys
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest as bt                                   # noqa: E402  逐日前推 HAR

WEEKDAY_ZH = "一二三四五六日"
PERIOD_ZH = {"day": "交易日", "week": "週", "month": "月"}


def load_gcs(ktype, symbol="HK.HSI_FRONT"):
    sys.path.insert(0, str(REPO / "scripts"))
    import gcp_agent as g
    ctx = g.Ctx(argparse.Namespace(region=None, function=None, bucket=None, project=None))
    s, base = ctx.session, f"https://storage.googleapis.com/storage/v1/b/{ctx.bucket}/o"
    names, token = [], None
    while True:
        params = {"prefix": f"archive/futu_{ktype.lower()}/{symbol}/", "fields": "items(name),nextPageToken"}
        if token:
            params["pageToken"] = token
        r = s.get(base, params=params).json()
        names += [i["name"] for i in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    bars = []
    for n in names:
        bars += s.get(f"{base}/{n.replace('/', '%2F')}", params={"alt": "media"}).json()
    daily = s.get(f"{base}/futu%2Fdaily%2F{symbol}.json", params={"alt": "media"}).json()
    return bars, daily


def session_of(time_key):
    d, hh = time_key[:10], int(time_key[11:13])
    return d if hh >= 9 else (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def session_minutes(hhmm):
    """交易日內的分鐘數（09:00 = 0，翌日 03:00 = 1080），跨午夜也能排序。"""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return ((h - 9) % 24) * 60 + m


def build_days(bars, daily):
    by_day = defaultdict(dict)
    for b in bars:
        if b.get("volume"):
            by_day[session_of(b["time_key"])][b["time_key"]] = b
    D, C, r, F = bt.run(bt.to_rows(daily), 60)
    har = F["HAR（對數，平均）"]
    days = []
    for t in range(1, len(D)):
        d = D[t]
        if np.isnan(har[t]) or d not in by_day or len(by_day[d]) < 4:
            continue
        seq = [by_day[d][k] for k in sorted(by_day[d])]
        days.append({"date": d, "bars": seq, "rhat": har[t] * C[t - 1], "ref": C[t - 1]})
    # 逐日前推的時段變異比例（之前最多 250 天）
    window, sums, counts = deque(), defaultdict(float), defaultdict(int)
    for day in days:
        mean = {k: sums[k] / counts[k] for k in sums if counts[k] >= 5}
        total = sum(mean.values())
        shares = [mean.get(b["time_key"][11:16], 0.0) / total if total else 1.0 / len(day["bars"])
                  for b in day["bars"]]
        day["rem"] = list(np.cumsum(shares[::-1])[::-1][1:]) + [0.0]       # 每根收市後當天還剩的變異比例
        prev, sq = day["bars"][0]["open"], {}
        for b in day["bars"]:
            sq[b["time_key"][11:16]] = math.log(b["close"] / prev) ** 2
            prev = b["close"]
        window.append(sq)
        for k, v in sq.items():
            sums[k] += v
            counts[k] += 1
        if len(window) > 250:
            for k, v in window.popleft().items():
                sums[k] -= v
                counts[k] -= 1
    return days


def build_periods(days, kind):
    def key(d):
        dd = date.fromisoformat(d)
        if kind == "day":
            return d
        if kind == "week":
            y, w, _ = dd.isocalendar()
            return f"{y}-W{w:02d}"
        return d[:7]

    groups = defaultdict(list)
    for day in days:
        groups[key(day["date"])].append(day)
    periods = []
    for k in sorted(groups):
        sess = groups[k]
        n = len(sess)
        if kind == "week" and n < 3 or kind == "month" and n < 12:
            continue                                                 # 不完整的週／月（樣本頭尾）不算
        bars = [(b, j) for j, s in enumerate(sess) for b in s["bars"]]
        periods.append({"key": k, "kind": kind, "sessions": sess, "bars": bars, "n": n,
                        "R": sess[0]["rhat"] * math.sqrt(n)})
    return periods


def checkpoint(period, strat_c, bar, j, k_in_session, last_in_session):
    _, cut, _ = strat_c
    if period["kind"] == "day":
        return bar["time_key"][11:16] == cut and bar["time_key"][:10] == period["sessions"][0]["date"]
    return last_in_session and j + 1 == cut                         # 第 cut 個交易日收市


def run_period(period, strat, side):
    """回傳 (通知的 K 線序號, 通知時的極值, 通知時離極值的點數) 或 (None, None, None)。"""
    hs, ls, R = -math.inf, math.inf, period["R"]
    sess = period["sessions"]
    pos_in_session = defaultdict(int)
    for idx, (b, j) in enumerate(period["bars"]):
        k = pos_in_session[j]
        pos_in_session[j] += 1
        last = k == len(sess[j]["bars"]) - 1
        hs, ls = max(hs, b["high"]), min(ls, b["low"])
        p = b["close"]
        ext = hs if side == "high" else ls
        dist = (hs - p) if side == "high" else (p - ls)
        kind = strat[0]
        if kind == "A":
            if hs - ls >= strat[1] * R and dist >= strat[2] * R:
                return idx, ext, dist
        elif kind == "B":
            s_day = sess[j]["rhat"] / 1.596 / sess[j]["ref"]
            rem = sess[j]["rem"][k] + (period["n"] - 1 - j)
            if rem <= 0:
                return None, None, None
            sig = s_day * math.sqrt(rem) * p
            if dist > 0 and math.erfc(dist / sig / math.sqrt(2)) < strat[1]:     # = 2×(1 − Φ(距離 ÷ σ))
                return idx, ext, dist
        elif kind == "C":
            if checkpoint(period, strat, b, j, k, last) and dist >= strat[2] * R:
                return idx, ext, dist
    return None, None, None


def wilson(hits, n, z=1.96):
    if not n:
        return (float("nan"), float("nan"))
    p = hits / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return mid - half, mid + half


def when(period, idx):
    b, j = period["bars"][idx]
    hhmm = b["time_key"][11:16]
    if period["kind"] == "day":
        return (session_minutes(hhmm), hhmm)
    if period["kind"] == "week":
        wd = date.fromisoformat(period["sessions"][j]["date"]).weekday()
        return (j * 2000 + session_minutes(hhmm), f"週{WEEKDAY_ZH[wd]} {hhmm}")
    return (j * 2000 + session_minutes(hhmm), f"第 {j + 1} 個交易日 {hhmm}")


def hours_between(a, b):
    ta = datetime.strptime(a["time_key"][:16], "%Y-%m-%d %H:%M")
    tb = datetime.strptime(b["time_key"][:16], "%Y-%m-%d %H:%M")
    return (tb - ta).total_seconds() / 3600


def score(periods, strat, side):
    hits, over, pull, whens, delays, n_sig = 0, [], [], [], [], 0
    for per in periods:
        idx, ext, dist = run_period(per, strat, side)
        if idx is None:
            continue
        n_sig += 1
        later = [b for b, _ in per["bars"][idx + 1:]]
        if side == "high":
            final = max([ext] + [b["high"] for b in later])
        else:
            final = min([ext] + [b["low"] for b in later])
        if final == ext:
            hits += 1
        else:
            over.append(abs(final - ext))
        pull.append(dist)
        whens.append(when(per, idx))
        i_ext = next(i for i, (b, _) in enumerate(per["bars"][:idx + 1]) if (b["high"] if side == "high" else b["low"]) == ext)
        delays.append(hours_between(per["bars"][i_ext][0], per["bars"][idx][0]))
    n = len(periods)
    lo, hi = wilson(hits, n_sig)
    return {"strat": strat, "side": side, "n": n, "signals": n_sig, "rate": n_sig / n if n else 0.0,
            "precision": hits / n_sig if n_sig else float("nan"), "ci": (lo, hi),
            "over": float(np.median(over)) if over else 0.0, "pull": float(np.median(pull)) if pull else float("nan"),
            "when": sorted(whens)[len(whens) // 2][1] if whens else "—",
            "delay_h": float(np.median(delays)) if delays else float("nan")}


def base_rates(periods, side):
    """參考：不用任何條件，到某時點時這段時間的高位已經出現的比例。"""
    out = {}
    for per in periods:
        bars = per["bars"]
        final = max(b["high"] for b, _ in bars) if side == "high" else min(b["low"] for b, _ in bars)
        first = next(i for i, (b, _) in enumerate(bars) if (b["high"] if side == "high" else b["low"]) == final)
        frac = (first + 1) / len(bars)
        for q in (0.25, 0.5, 0.75):
            out.setdefault(q, []).append(frac <= q)
    return {q: float(np.mean(v)) for q, v in out.items()}


def grid(kind):
    a = [("A", al, be) for al in (0.6, 0.8, 1.0, 1.2) for be in (0.2, 0.3, 0.4, 0.5)]
    b = [("B", p) for p in (0.05, 0.10, 0.15, 0.20, 0.30)]
    cuts = {"day": ("12:00", "16:30"), "week": (2, 3, 4), "month": (5, 10, 15)}[kind]
    c = [("C", cut, be) for cut in cuts for be in (0.1, 0.2, 0.3, 0.4)]
    return a + b + c


def name(strat, kind):
    if strat[0] == "A":
        return f"A 已走≥{strat[1]}R̂、回落≥{strat[2]}R̂"
    if strat[0] == "B":
        return f"B 再創新高機率<{strat[1]:.0%}"
    cut = strat[1] if kind == "day" else (f"第{strat[1]}天收市")
    return f"C {cut} 回落≥{strat[2]}R̂"


def report(periods, kind, label):
    half = len(periods) // 2
    train, test = periods[:half], periods[half:]
    lines = [f"\n### {PERIOD_ZH[kind]}（{label}）：{len(periods)} 段（{periods[0]['key']} 至 {periods[-1]['key']}），"
             f"訓練 {len(train)}／測試 {len(test)}"]
    out = {}
    for side in ("high", "low"):
        res = [score(train, s, side) for s in grid(kind)]
        ok = [x for x in res if x["rate"] >= 0.3]
        best = sorted(ok, key=lambda x: (-x["precision"], -x["rate"]))[:3]
        b_only = sorted([x for x in ok if x["strat"][0] == "B"], key=lambda x: (-x["precision"], -x["rate"]))[:1]
        picks = best + [x for x in b_only if x not in best]
        br = base_rates(test, side)
        zh = "高位" if side == "high" else "低位"
        lines.append(f"\n{zh}（參考：不加條件，時間過了 1/4、1/2、3/4 時{zh}已出現的比例 "
                     f"{br[0.25]:.0%}／{br[0.5]:.0%}／{br[0.75]:.0%}）")
        lines.append("| 策略 | 訓練準確 | **測試準確**（95% 區間） | 測試通知率 | 通知時離極值 | 錯時再突破 | 通知中位時間 | 極值後多久通知 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        rows = []
        for x in picks:
            t = score(test, x["strat"], side)
            rows.append(t)
            lines.append(f"| {name(x['strat'], kind)} | {x['precision']:.0%} | **{t['precision']:.0%}**"
                         f"（{t['ci'][0]:.0%}–{t['ci'][1]:.0%}） | {t['rate']:.0%} | {t['pull']:,.0f} 點 | "
                         f"{t['over']:,.0f} 點 | {t['when']} | {t['delay_h']:.1f} 小時 |")
        out[side] = rows
    return "\n".join(lines), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ktype", default="K_15M")
    ap.add_argument("--json", help="本地快取 {bars, daily}；沒有就從 GCS 讀並存到這裡")
    ap.add_argument("--periods", default="day,week,month")
    a = ap.parse_args()
    if a.json and Path(a.json).exists():
        cache = json.load(open(a.json))
        bars, daily = cache["bars"], cache["daily"]
    else:
        bars, daily = load_gcs(a.ktype)
        if a.json:
            json.dump({"bars": bars, "daily": daily}, open(a.json, "w"))
    days = build_days(bars, daily)
    print(f"{a.ktype}：{len(days)} 個交易日有 HAR 預測與日內 K 線（{days[0]['date']} 至 {days[-1]['date']}）")
    for kind in a.periods.split(","):
        text, _ = report(build_periods(days, kind), kind, a.ktype)
        print(text)


if __name__ == "__main__":
    main()
