#!/usr/bin/env python3
"""日線 B 規則掃描（唔係回測）：最新一個收市日，現有成分股邊隻出 B 訊號，列出唔同 ATR 組合嘅止蝕／止賺價。

規則同天覆陣 IDEAS #181 一字不改（重用佢 research/strategy_search 模組，預設分支 3e540bb19）：
收市由 Keltner 上軌（EMA20 + 2×ATR20）下面升穿上軌 ＋ 拋物線 SAR 向上 ＋ 收市 > SMA200 → 做多；做空相反。
入場參考 = 下一個交易日開市。⚠️ 回測判決 ☠️（#181、B_STOCKS_ATR_GRID_PREREG.md）：訊號唔勝隨機入場——名單只供參考，唔係落單指令。

    python3 stock_research/b_rule_scan.py --src /tmp/eq --ss /tmp/ss/research/strategy_search
輸出 analysis/b_scan/<日期>.csv、<日期>.md、latest.md。
"""
import argparse
import csv
import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "b_scan"
UNIVERSES = (("標普 500", "sp500", "us"), ("納指 100", "ndx", "us"), ("道指", "djia", "us"), ("日經 225", "n225", "jp"), ("恒指", "hsi", "hk"))
COMBOS = [(1.5, 3.0), (2.0, 4.0), (3.0, 6.0)]          # (SL, TP) × ATR20


def current_members(BS, src, key, last):
    mem = BS.membership(src, key)
    d = dt.date.fromisoformat(last)
    return sorted(tk for tk, spans in mem.items() if any(a <= d < b for a, b in spans))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/eq")
    ap.add_argument("--ss", default="/tmp/ss/research/strategy_search")
    a = ap.parse_args()
    sys.path.insert(0, a.ss)
    import b_stocks as BS  # noqa: E402
    import combo_tf as CT  # noqa: E402

    rows, seen, dates = [], {}, set()
    for name, key, mkt in UNIVERSES:
        # 用市場最新日期（AAPL／7203／0700 之類大股做參考）判斷「最新收市日」
        tks = BS.membership(a.src, key)
        for tk in sorted(tks):
            p = os.path.join(a.src, "data", "equities", mkt, tk)
            if not os.path.isdir(p):
                continue
            if (mkt, tk) not in seen:
                d = BS.load_prices(p)
                seen[(mkt, tk)] = None
                if d is None:
                    continue
                B = CT.Bars(d, 86400)
                b, x = BS.b_signals(B)
                i = len(B.c) - 1
                last = dt.datetime.fromtimestamp(int(B.t[i]), dt.timezone.utc).date().isoformat()
                seen[(mkt, tk)] = (B, b, x, i, last)
            if seen[(mkt, tk)] is None:
                continue
            B, b, x, i, last = seen[(mkt, tk)]
            dates.add((mkt, last))
            if not (b[i] or x[i]) or not (B.datr[i] > 0):
                continue
            if tk not in current_members(BS, a.src, key, last):
                continue
            s = 1 if b[i] else -1
            c, atr = float(B.c[i]), float(B.datr[i])
            r = dict(指數=name, 市場=mkt, 代號=tk, 日期=last, 方向="做多" if s > 0 else "做空", 收市=round(c, 2),
                     ATR20=round(atr, 2), ATR佔價=f"{atr / c:.1%}", SMA200=round(float(B.s200[i]), 2), Keltner上軌=round(float(B.ku[i]), 2))
            for sl, tp in COMBOS:
                r[f"SL{sl:g}"] = round(c - s * sl * atr, 2)
                r[f"TP{tp:g}"] = round(c + s * tp * atr, 2)
            rows.append(r)
    mkt_last = {}
    for m, d in dates:
        mkt_last[m] = max(mkt_last.get(m, ""), d)
    # 只留每個市場最新收市日嘅訊號（停牌／過時數據唔算）
    rows = [r for r in rows if r["日期"] == mkt_last[r["市場"]]]
    day = max(mkt_last.values())
    OUT.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys()) if rows else ["指數"]
    with open(OUT / f"{day}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    L = [f"# 日線 B 規則掃描 {day}（收市判、下一交易日開市入）", "",
         "⚠️ 只係掃描、唔係落單指令：回測判 ☠️（天覆陣 #181；ATR 網格重測 B_STOCKS_ATR_GRID_PREREG.md）——訊號唔勝同出場嘅隨機入場。",
         f"各市場最新收市日：{'、'.join(f'{m} {d}' for m, d in sorted(mkt_last.items()))}。止蝕／止賺以收市價 ± 倍數 × ATR20 估（實際以開市價計）。", ""]
    for name, key, mkt in UNIVERSES:
        sub = [r for r in rows if r["指數"] == name]
        L += [f"## {name}：做多 {sum(r['方向'] == '做多' for r in sub)}、做空 {sum(r['方向'] == '做空' for r in sub)}", ""]
        if not sub:
            L += ["（冇訊號）", ""]
            continue
        hdr = ["代號", "方向", "收市", "ATR20", "ATR佔價"] + [f"SL{sl:g}／TP{tp:g}" for sl, tp in COMBOS]
        L += ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
        for r in sorted(sub, key=lambda r: (r["方向"], r["代號"])):
            L.append("| " + " | ".join([r["代號"], r["方向"], f"{r['收市']}", f"{r['ATR20']}", r["ATR佔價"]]
                                     + [f"{r[f'SL{sl:g}']}／{r[f'TP{tp:g}']}" for sl, tp in COMBOS]) + " |")
        L.append("")
    md = "\n".join(L) + "\n"
    (OUT / f"{day}.md").write_text(md, encoding="utf-8")
    (OUT / "latest.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
