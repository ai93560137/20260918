"""被收回恒指牛熊證（過去 12 個月，港交所 mcehistical）× 恒指日線高低 → 「收回後觀察期再走多遠」的分佈。
這就是 E 類交易（買折讓牛熊證＋沽期指）的真正風險：收回時期指平倉價 C′ 與觀察期極值 L 之差。

    python3 research/warrants_cbbc/cbbc_mce_analysis.py

近似：收回日 D 的觀察期取 D 與 D+1 兩個交易日（恒指牛熊證的觀察期由收回起至下一個交易時段完結）。
  牛證：L ＝ min(D 低位, D+1 低位)，再走距離 ＝ 收回價 − max(行使價, L)（跌穿行使價就封頂在緩衝區）。
  熊證：H ＝ max(D 高位, D+1 高位)，再走距離 ＝ min(行使價, H) − 收回價。
用日線高低會**高估**（極值不一定在收回之後發生），所以結果是保守上界；用 GCS 的 5 分 K 封存可以算得更準（下一步）。
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCE = ROOT / "data" / "hkex_sp" / "mce_history.csv.gz"
HSI = ROOT / "canary" / "data_external" / "hsi_daily.csv"


def load_hsi():
    out = {}
    with open(HSI, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[r["Date"][:10]] = (float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]))
            except ValueError:
                pass
    return out


def next_day(days: list[str], d: str) -> str | None:
    import bisect
    i = bisect.bisect_right(days, d)
    return days[i] if i < len(days) else None


def q(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else None


def main():
    rows = list(csv.reader(gzip.open(MCE, "rt", encoding="utf-8")))
    data = [r for r in rows if len(r) >= 11 and r[0].strip().isdigit()]
    hsi = load_hsi()
    days = sorted(hsi)
    recs = []
    for r in data:
        if r[3].strip().upper() != "HSI":
            continue
        try:
            K, C = float(r[7]), float(r[8])
            d = r[10].replace("/", "-")
        except ValueError:
            continue
        bull = r[4].strip().lower() == "bull"
        if d not in hsi:
            continue
        o, h, l, c = hsi[d]
        d2 = next_day(days, d)
        h2, l2 = (hsi[d2][1], hsi[d2][2]) if d2 else (h, l)
        buffer = abs(C - K)
        if bull:
            L = min(l, l2)
            beyond = C - max(K, L)
            same_day = C - max(K, l)
        else:
            H = max(h, h2)
            beyond = min(K, H) - C
            same_day = min(K, h) - C
        beyond = max(0.0, beyond)
        same_day = max(0.0, same_day)
        recs.append({"code": r[0], "bull": bull, "K": K, "C": C, "buffer": buffer, "date": d, "beyond": beyond, "same_day": same_day,
                     "gap_open": (C - o) if bull else (o - C)})
    print(f"過去 12 個月被收回的恒指牛熊證：{len(recs)} 隻（有恒指日線的），牛 {sum(1 for x in recs if x['bull'])} 熊 {sum(1 for x in recs if not x['bull'])}")
    by_day = defaultdict(int)
    for x in recs:
        by_day[x["date"]] += 1
    print(f"有收回事件的交易日 {len(by_day)} 天；單日最多 {max(by_day.values())} 隻（{max(by_day, key=by_day.get)}）")
    bufs = [x["buffer"] for x in recs]
    print(f"緩衝區（|收回價−行使價|）：中位 {q(bufs, .5):.0f} 點，10% {q(bufs, .1):.0f}，90% {q(bufs, .9):.0f}")
    for label, key in (("觀察期（收回日＋次日）再走距離", "beyond"), ("只算收回當日", "same_day")):
        v = [x[key] for x in recs]
        frac = [x[key] / x["buffer"] for x in recs if x["buffer"] > 0]
        print(f"{label}：中位 {q(v, .5):.0f} 點，75% {q(v, .75):.0f}，90% {q(v, .9):.0f}，最大 {max(v):.0f}；"
              f"佔緩衝區比例 中位 {q(frac, .5):.0%}，90% {q(frac, .9):.0%}；跌穿行使價（吃光緩衝）{sum(1 for f_ in frac if f_ >= 0.999) / len(frac):.1%}")
    print("按緩衝區大小分組（觀察期再走距離，點）：")
    for lo_, hi_ in ((0, 100), (100, 200), (200, 400), (400, 800), (800, 100_000)):
        sub = [x for x in recs if lo_ <= x["buffer"] < hi_]
        if sub:
            v = [x["beyond"] for x in sub]
            print(f"  緩衝 {lo_}–{hi_ if hi_ < 100_000 else '∞'}：{len(sub)} 隻，再走 中位 {q(v, .5):.0f}，90% {q(v, .9):.0f}，吃光 {sum(1 for x in sub if x['beyond'] >= x['buffer'] - 1e-9) / len(sub):.0%}")
    gap = [x for x in recs if x["gap_open"] > 0]
    print(f"開市即跳空穿過收回價（開市價已越過）：{len(gap)} 隻（{len(gap) / len(recs):.1%}），跳空幅度中位 {q([x['gap_open'] for x in gap], .5):.0f} 點")
    print("\n解讀：E 類交易的損失 ＝ 折讓 − 再走距離。折讓若只有 20–50 點，而再走距離中位已是幾十點、九成分位幾百點，"
          "貼近收回價的折讓根本不夠補；只有緩衝小（再走距離被封頂）或距離收回價遠（不會被收回）的才算得過。")
    import sys
    if "--csv" in sys.argv:
        out = ROOT / "research" / "warrants_cbbc" / "cbbc_mce_analysis.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
            w.writeheader()
            w.writerows(recs)
        print(f"已寫入 {out}")


if __name__ == "__main__":
    main()
