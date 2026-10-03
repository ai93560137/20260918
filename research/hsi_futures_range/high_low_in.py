"""「當天高位／低位已經出現」的判斷：回測。

問題：交易日（09:15 日市開市至翌日 03:00 夜市收市）進行中，什麼時候可以說「今天的高位已經出現、之後不會再高」？
每一根日內 K 線收市時，用當時已知的資料判斷一次；每邊每天只通知第一次。

數據（GCS，需要 GCP_SA_KEY）：
  archive/futu_k_15m/HK.HSI_FRONT/<日期>.json   本地腳本 v9 的 --export-intraday（時間是 K 線結束時間，香港時間）
  futu/daily/HK.HSI_FRONT.json                  交易日 K（算逐日前推的 HAR 波幅預測 R̂）

策略（低位對稱）：
  A 耗盡＋回落：已走波幅 ≥ α×R̂ 且 價格離最高位 ≥ β×R̂。
  B 反射原理：剩餘時間內再創新高的機率 = 2×(1 − Φ(距離 ÷ σ_剩餘))，低於 p 就通知。
      σ_剩餘 = σ_全日 × √(剩餘時段的變異比例)；σ_全日 = R̂ ÷ 1.596 ÷ 昨收（布朗運動：期望波幅 ≈ 1.596σ）；
      各時段的變異比例由之前的交易日估（逐日前推）。
  C 時間點：到 12:00／16:30 時，價格離最高位 ≥ β×R̂ 就通知。

評分（只算有通知的日子）：
  準確率 = 通知之後到收市，高位都沒有再被突破的比例。
  通知率 = 有通知的日子佔全部日子。
  錯的時候平均再突破多少點、通知的中位時間、離真正高位出現的延遲。
  參數在前半段（訓練）挑，後半段（測試）報成績，避免挑參數又在同一批日子評分。

用法：python3 research/hsi_futures_range/high_low_in.py [--ktype K_15M] [--json 本地快取]
"""
import argparse, json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import norm

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest as bt                                   # noqa: E402  逐日前推 HAR


def gcs_session(ctx):
    return ctx.session


def load_gcs(ktype, symbol="HK.HSI_FRONT"):
    sys.path.insert(0, str(REPO / "scripts"))
    import gcp_agent as g
    ctx = g.Ctx(argparse.Namespace(region=None, function=None, bucket=None, project=None))
    s, base = ctx.session, f"https://storage.googleapis.com/storage/v1/b/{ctx.bucket}/o"
    prefix = f"archive/futu_{ktype.lower()}/{symbol}/"
    names, token = [], None
    while True:
        params = {"prefix": prefix, "fields": "items(name),nextPageToken"}
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
    if hh >= 9:
        return d
    from datetime import date, timedelta
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def slot_of(time_key):
    """時段鍵：HH:MM（夜市凌晨也照時鐘），用來估各時段的變異。"""
    return time_key[11:16]


def build(bars, daily):
    by_day = defaultdict(dict)
    for b in bars:
        if b.get("volume"):
            by_day[session_of(b["time_key"])][b["time_key"]] = b
    data = bt.to_rows(daily)
    D, C, r, F = bt.run(data, 60)
    rhat = {D[t]: F["HAR（對數，平均）"][t] * C[t - 1] for t in range(1, len(D)) if not np.isnan(F["HAR（對數，平均）"][t])}
    ref = {D[t]: C[t - 1] for t in range(1, len(D))}
    days = []
    for d in sorted(by_day):
        if d not in rhat:
            continue
        seq = [by_day[d][k] for k in sorted(by_day[d])]
        if len(seq) < 10:
            continue
        days.append({"date": d, "bars": seq, "rhat": rhat[d], "ref": ref[d]})
    return days


def variance_profile(days_before):
    """之前交易日每個時段的平均平方對數報酬 → 各時段佔全日變異的比例。"""
    acc = defaultdict(list)
    for day in days_before:
        prev = day["bars"][0]["open"]
        for b in day["bars"]:
            acc[slot_of(b["time_key"])].append(math.log(b["close"] / prev) ** 2)
            prev = b["close"]
    mean = {k: float(np.mean(v)) for k, v in acc.items() if len(v) >= 5}
    total = sum(mean.values()) or 1.0
    return {k: v / total for k, v in mean.items()}


def session_minutes(hhmm):
    """交易日內的分鐘數（09:00 = 0，翌日 03:00 = 1080），跨午夜也能排序。"""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return ((h - 9) % 24) * 60 + m


def run_day(day, profile, strat, side):
    """回傳 (通知的 K 線序號或 None, 通知時的極值)。side='high' 或 'low'。"""
    bars, R = day["bars"], day["rhat"]
    hs, ls = -math.inf, math.inf
    slots = [slot_of(b["time_key"]) for b in bars]
    shares = [profile.get(s, 0.0) for s in slots]
    remaining = np.cumsum(shares[::-1])[::-1]                      # 含本根之後還剩的變異比例
    sigma_total = R / 1.596 / day["ref"]
    for k, b in enumerate(bars):
        hs, ls = max(hs, b["high"]), min(ls, b["low"])
        p = b["close"]
        ext = hs if side == "high" else ls
        dist = (hs - p) if side == "high" else (p - ls)
        rem = remaining[k + 1] if k + 1 < len(bars) else 0.0
        kind = strat[0]
        if kind == "A":
            _, alpha, beta = strat
            if hs - ls >= alpha * R and dist >= beta * R:
                return k, ext
        elif kind == "B":
            _, pstar = strat
            if rem <= 0:
                return None, ext
            sig = sigma_total * math.sqrt(rem) * p
            prob = 2 * (1 - norm.cdf(dist / sig)) if sig > 0 else 0.0
            if prob < pstar and dist > 0:
                return k, ext
        elif kind == "C":
            _, cut, beta = strat
            if b["time_key"][11:16] == cut and b["time_key"][:10] == day["date"] and dist >= beta * R:
                return k, ext
    return None, None


def score(days, profiles, strat, side):
    hits, wrong_over, times, delays, n_sig = 0, [], [], [], 0
    for day in days:
        k, ext = run_day(day, profiles[day["date"]], strat, side)
        if k is None:
            continue
        n_sig += 1
        bars = day["bars"]
        final = max(b["high"] for b in bars) if side == "high" else min(b["low"] for b in bars)
        later = bars[k + 1:]
        beyond = (max((b["high"] for b in later), default=-math.inf) > ext) if side == "high" else \
                 (min((b["low"] for b in later), default=math.inf) < ext)
        if not beyond:
            hits += 1
        else:
            wrong_over.append(abs(final - ext))
        times.append(bars[k]["time_key"][11:16])
        i_ext = next(i for i, b in enumerate(bars[:k + 1]) if (b["high"] if side == "high" else b["low"]) == ext)
        delays.append((k - i_ext))
    n = len(days)
    return {"strat": strat, "side": side, "days": n, "signals": n_sig, "rate": n_sig / n if n else 0,
            "precision": hits / n_sig if n_sig else float("nan"),
            "over": float(np.mean(wrong_over)) if wrong_over else 0.0,
            "time": sorted(times, key=session_minutes)[len(times) // 2] if times else "—",
            "delay_bars": float(np.median(delays)) if delays else float("nan")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ktype", default="K_15M")
    ap.add_argument("--json", help="本地快取 {bars, daily}；沒有就從 GCS 讀並存到這裡")
    a = ap.parse_args()
    if a.json and Path(a.json).exists():
        cache = json.load(open(a.json))
        bars, daily = cache["bars"], cache["daily"]
    else:
        bars, daily = load_gcs(a.ktype)
        if a.json:
            json.dump({"bars": bars, "daily": daily}, open(a.json, "w"))
    days = build(bars, daily)
    if len(days) < 80:
        sys.exit(f"日內數據只有 {len(days)} 個交易日，不夠回測")
    profiles = {}
    for i, day in enumerate(days):                                 # 逐日前推的時段變異比例
        profiles[day["date"]] = variance_profile(days[max(0, i - 250):i] if i >= 20 else days[:20])
    half = len(days) // 2
    train, test = days[:half], days[half:]
    grid = ([("A", al, be) for al in (0.6, 0.8, 1.0, 1.2) for be in (0.2, 0.3, 0.4, 0.5)]
            + [("B", p) for p in (0.05, 0.10, 0.15, 0.20, 0.30)]
            + [("C", cut, be) for cut in ("12:00", "16:30") for be in (0.2, 0.3, 0.4)])
    print(f"{a.ktype}：{len(days)} 個交易日（{days[0]['date']} 至 {days[-1]['date']}），訓練 {len(train)}／測試 {len(test)}")
    for side in ("high", "low"):
        res = [score(train, profiles, s, side) for s in grid]
        ok = [x for x in res if x["signals"] >= 0.3 * len(train)]   # 至少三成日子有通知才算實用
        best = sorted(ok, key=lambda x: (-x["precision"], -x["rate"]))[:5]
        print(f"\n=== {'高位' if side == 'high' else '低位'}：訓練期最好的 5 組，在測試期的成績 ===")
        print(f"{'策略':<22}{'訓練準確':>8}{'測試準確':>8}{'測試通知率':>10}{'錯時再突破':>10}{'通知中位時間':>12}{'延遲(根)':>8}")
        for x in best:
            t = score(test, profiles, x["strat"], side)
            print(f"{str(x['strat']):<22}{x['precision']:>8.0%}{t['precision']:>8.0%}{t['rate']:>10.0%}"
                  f"{t['over']:>10.0f}{t['time']:>12}{t['delay_bars']:>8.0f}")


if __name__ == "__main__":
    main()
