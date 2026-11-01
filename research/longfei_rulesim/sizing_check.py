"""[IDEAS #165] MHI 張數規則：R305 階梯（賺 +1 張、蝕 −1 張）vs 固定張數 vs 按波幅定張數（MILESTONES「張數升級規則」研究，限期 11-07）。

文獻：Harvey 等 2018「The Impact of Volatility Targeting」（JPM）—— 股票類按波幅調倉，夏普較高、回撤較細；
Ginyard 2014（47 隻期貨）—— 目標波幅最好，冇證據支持按連贏連輸加減注。

交易來源：swing_check 嘅「順日線隨機入場」（每日 1 次，13:00–16:00／17:15–23:30 5 分鐘收市，方向跟日線），
波段出場（止蝕 120、1R 保本、165 點後 165 點移動止蝕、最多 3 日），每邊成本 2 點。20 個隨機種子。
數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，含夜市）。

張數規則（全部上限 10 張、下限 1 張）：
  F   固定 1 張
  L   R305 階梯：由 1 張起，上一筆淨賺 +1、淨蝕 −1、打和不變
  V   按波幅：張數 ＝ round(中位數 ATR ÷ 當日 ATR × 3)，夾喺 1–10（ATR＝14 日日市幅度；中位數用全期，3 張係基準）
比較前先將每個規則除以佢自己嘅平均張數（等同用同樣平均風險），睇時機有冇加值。

預先登記（11-01，結果出嚟之前寫，唔再改）：
  量度（每個種子）：標準化後合計點數、最大回撤（點）、合計 ÷ |最大回撤|。
  L 或 V「成立」＝ 20 個種子入面 ≥ 15 個：標準化合計 ≥ F × 1.10（或者 F ≤ 0 時要 > F + 10% × |F|），而且 合計／回撤 ≥ F。
用途（只係提案，真倉要使用者批）：L 唔成立而 V 成立 → 提案 MHI 改按波幅定張數；L、V 都唔成立 → 提案改固定張數（或者維持，交使用者揀）；
L 成立 → 維持 R305。

用法：python3 research/longfei_rulesim/sizing_check.py [--out 結果.json]（要 GCS 讀權）
"""
import argparse
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402
import swing_check as sc  # noqa: E402

MAXQ = 10


def sizes_L(pts):
    q, out = 1, []
    for p in pts:
        out.append(q)
        q = min(MAXQ, q + 1) if p > 0 else max(1, q - 1) if p < 0 else q
    return out


def metrics(pts, qs):
    avg_q = statistics.mean(qs)
    eq = peak = dd = 0.0
    for p, q in zip(pts, qs):
        eq += p * q / avg_q
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"total": round(eq, 1), "max_dd": round(dd, 1), "ratio": round(eq / abs(dd), 3) if dd else None,
            "avg_q": round(avg_q, 2)}


def better(x, f):
    need = f["total"] * 1.10 if f["total"] > 0 else f["total"] + 0.10 * abs(f["total"])
    return x["total"] >= need and (x["ratio"] or -9) >= (f["ratio"] or -9)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    from google.cloud import storage
    b = storage.Client().bucket(um.GCS_BUCKET)
    raw = {}
    for x in b.list_blobs(prefix=um.GCS_BARS):
        try:
            raw[x.name.rsplit("/", 1)[1][:10]] = json.loads(x.download_as_bytes())
        except Exception:  # noqa: BLE001
            continue
    bars = um.load(raw)
    dkeys, ctx = um.daily(bars)
    keys = sc.day_keys(bars)
    by_day = {}
    for i, (t, *_r) in enumerate(bars):
        if t.minute % 5 == 4 and any(x <= t.time() < y for x, y in sc.WINDOWS):
            sd = um.session_date(t)
            x = ctx.get(sd)
            if x:
                by_day.setdefault(sd, []).append((i, 1 if x["pdc"] > x["sma"] else -1))
    med_atr = statistics.median(ctx[d]["atr"] for d in by_day)
    seeds, wins = [], {"L": 0, "V": 0}
    for seed in range(20):
        rnd = random.Random(seed)
        pts, atr = [], []
        for sd in sorted(by_day):
            i, s = rnd.choice(by_day[sd])
            pts.append(sc.run(bars, keys, i, s, bars[i][4], "S"))
            atr.append(ctx[sd]["atr"])
        qF = [1] * len(pts)
        qL = sizes_L(pts)
        qV = [min(MAXQ, max(1, round(med_atr / x * 3))) for x in atr]
        m = {"F": metrics(pts, qF), "L": metrics(pts, qL), "V": metrics(pts, qV), "n": len(pts),
             "lag1_corr_win": None}
        w = [1 if p > 0 else 0 for p in pts]
        if len(w) > 2 and statistics.pstdev(w[:-1]) and statistics.pstdev(w[1:]):
            m["lag1_corr_win"] = round(statistics.correlation(w[:-1], w[1:]), 3)
        for k in ("L", "V"):
            if better(m[k], m["F"]):
                wins[k] += 1
        seeds.append(m)
    res = {"from": str(bars[0][0]), "to": str(bars[-1][0]), "median_atr": round(med_atr, 1), "seeds": seeds,
           "wins_vs_F": wins, "L_pass": wins["L"] >= 15, "V_pass": wins["V"] >= 15,
           "mean": {k: {f: round(statistics.mean(s[k][f] for s in seeds), 2) for f in ("total", "max_dd", "ratio", "avg_q")}
                    for k in ("F", "L", "V")},
           "lag1_corr_win_mean": round(statistics.mean(s["lag1_corr_win"] for s in seeds if s["lag1_corr_win"] is not None), 3)}
    text = json.dumps(res, ensure_ascii=False, indent=1, default=str)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
