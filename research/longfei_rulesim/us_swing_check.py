"""[IDEAS #141] 美股模擬：同一批入場，「波段出場」對「即日出場」（使用者 10-27「模擬美股點樣可以進步」）。

恒指一年回測（#135，swing_check.py）見到波段出場三批入場都好過即日。呢度驗美股係咪一樣。
數據：yfinance 1 小時 K 線（約 730 日），23 隻美股 ETF／股票；日線算 ATR14 同趨勢。

入場（兩批）：
  T  順日線隨機：每個交易日喺第 2 至倒數第 2 支 1 小時 K 線隨機揀一支收市，方向跟日線（昨收 vs 20 日均線）；
     固定種子重複 10 次取平均
  O  開市區間突破順勢（同 #131 A1）：第一支 1 小時 K 線做區間，之後第一支順日線方向收市突破
出場（止蝕距離兩邊一樣，只係揸幾耐唔同）：
  S  波段：止蝕 0.35 ATR；浮賺 ≥ 1R 移開倉價；浮賺 ≥ 0.5 ATR 後 0.5 ATR 移動止蝕（只收緊）；最多揸 3 個交易日，第 3 日最後一支收市平；過夜跳空照計
  D  即日：同一個止蝕同保本，當日最後一支 K 線收市平
成本每邊 0.015%。

預先登記（10-27）成功標準：T 同 O 兩批都係 S 平均 R − D 平均 R ≥ +0.05，而且 S 本身平均 ≥ +0.03R、
前後兩半 S 都 ≥ D。過咗先將即日回測（rulesim）美股出場改波段做紙上前向測試；唔過就棄用。只係研究，唔落單。

用法：python3 research/longfei_rulesim/us_swing_check.py [--no-upload]
"""
import argparse
import json
import math
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fade_check import daily_closes, load_1h  # noqa: E402
from rulesim import US, us_trend  # noqa: E402

COST = 0.00015


def daily_atr(yf, ticker):
    df = yf.download(ticker, period="5y", interval="1d", progress=False, auto_adjust=False)
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    rng = (df["High"] - df["Low"]).dropna()
    out, vals = {}, list(rng.items())
    for i in range(14, len(vals)):
        out[vals[i][0].strftime("%Y-%m-%d")] = float(sum(v for _, v in vals[i - 14:i]) / 14)
    return out


def run(seq, i, side, entry, atr, mode):
    """seq：[(day_idx, t, o, h, l, c)]，由 i+1 開始行；回傳 R。"""
    risk = 0.35 * atr
    stop, mfe = entry - side * risk, 0.0
    d0 = seq[i][0]
    for j in range(i + 1, len(seq)):
        di, _, o, h, lo, c = seq[j]
        if mode == "D" and di != d0:                         # 即日：日尾已經平（上一支）
            prev = seq[j - 1][5]
            return ((prev - entry) * side - 2 * COST * entry) / risk
        if (side > 0 and lo <= stop) or (side < 0 and h >= stop):
            px = min(stop, o) if side > 0 else max(stop, o)
            return ((px - entry) * side - 2 * COST * entry) / risk
        mfe = max(mfe, (h - entry) if side > 0 else (entry - lo))
        if mfe >= risk:
            stop = max(stop, entry) if side > 0 else min(stop, entry)
        if mode == "S" and mfe >= 0.5 * atr:
            tr = entry + side * (mfe - 0.5 * atr)
            stop = max(stop, tr) if side > 0 else min(stop, tr)
        last_of_day = j + 1 >= len(seq) or seq[j + 1][0] != di
        if mode == "S" and di - d0 >= 2 and last_of_day:
            return ((c - entry) * side - 2 * COST * entry) / risk
    return ((seq[-1][5] - entry) * side - 2 * COST * entry) / risk


def stats(rs):
    n = len(rs)
    if n < 2:
        return {"n": n}
    m = sum(rs) / n
    sd = statistics.stdev(rs)
    return {"n": n, "avg_r": round(m, 3), "win": round(sum(r > 0 for r in rs) / n, 3),
            "t": round(m / (sd / math.sqrt(n)), 2) if sd else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    rows = {k: [] for k in ("T_S", "T_D", "O_S", "O_D")}
    for p in US:
        days, closes, atrs = load_1h(yf, p, "America/New_York"), daily_closes(yf, p), daily_atr(yf, p)
        dkeys = sorted(days)
        seq = [(di, *b) for di, d in enumerate(dkeys) for b in days[d]]
        start = {}
        for k, x in enumerate(seq):
            start.setdefault(x[0], k)
        for di, d in enumerate(dkeys):
            trend, atr = us_trend(closes, d), atrs.get(d)
            bars = days[d]
            if not trend or not atr or len(bars) < 4:
                continue
            s0 = start[di]
            # O：開市區間突破順勢
            orh, orl = bars[0][2], bars[0][3]
            for k in range(1, len(bars) - 1):
                c = bars[k][4]
                if (trend > 0 and c > orh) or (trend < 0 and c < orl):
                    for m in ("S", "D"):
                        rows[f"O_{m}"].append({"date": d, "p": p, "r": run(seq, s0 + k, trend, c, atr, m)})
                    break
            # T：順日線隨機（10 個種子各揀一支）
            for seed in range(10):
                k = random.Random(f"{seed}-{p}-{d}").randrange(1, len(bars) - 1)
                for m in ("S", "D"):
                    rows[f"T_{m}"].append({"date": d, "p": p, "seed": seed,
                                           "r": run(seq, s0 + k, trend, bars[k][4], atr, m)})
        print(p, len(dkeys), "日", {k: len(v) for k, v in rows.items()}, flush=True)

    alld = sorted({x["date"] for x in rows["O_S"]})
    split = alld[len(alld) // 2] if alld else ""
    rep = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "split": split,
           "period": [alld[0], alld[-1]] if alld else None,
           "rule": "IDEAS #141：T、O 兩批都 S−D ≥ +0.05R，S ≥ +0.03R，前後兩半 S ≥ D", "results": {}}
    for k, v in rows.items():
        rep["results"][k] = {"all": stats([x["r"] for x in v]),
                             "h1": stats([x["r"] for x in v if x["date"] < split]),
                             "h2": stats([x["r"] for x in v if x["date"] >= split])}
    ok = True
    for e in ("T", "O"):
        s, d = rep["results"][f"{e}_S"], rep["results"][f"{e}_D"]
        cond = (s["all"].get("avg_r", -9) - d["all"].get("avg_r", 9) >= 0.05 and s["all"].get("avg_r", -9) >= 0.03
                and s["h1"].get("avg_r", -9) >= d["h1"].get("avg_r", 9) and s["h2"].get("avg_r", -9) >= d["h2"].get("avg_r", 9))
        rep["results"][f"{e}_pass"] = cond
        ok = ok and cond
    rep["pass"] = ok
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/rulesim_oos/us_swing_report.json").upload_from_string(
            json.dumps(rep, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
