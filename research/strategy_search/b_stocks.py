"""[IDEAS #181] 日線 B 確認（#173，規則一字不改）放落股票：標普 500、納指 100、道指、日經 225、恒指成分股（point-in-time 名單）。
數據：選股陣分支 claude/gifted-carson-v2tvhw 嘅 data/equities/<市場>/<代碼>/prices_<年>.csv（日線、已調整），用 git archive 抽到 /tmp/eq。
只計訊號日當日係成分股嘅訊號（名單：universes/{sp500,ndx,djia,n225}/membership.csv；恒指：scripts/pointintime/hsi_<年>.txt，2026 用 universe_hsi_live.txt）。
成交：日線收市判、下一日開市入；TP 4／SL 2 × ATR20（日線）；20 個曆日時間止蝕；同一日 SL／TP 都掂當 SL；跳空過 SL 用開市；一次一張（每隻股票）。
成本：每張來回 0.1% 價格（換算做 R）。隨機基準：同一隻股票每 10 個交易日入一次、多空各一次、同樣出場。
用法：python3 research/strategy_search/b_stocks.py [--src /tmp/eq] → B_STOCKS.md"""
import argparse
import csv
import datetime as dt
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import combo_tf as CT  # noqa: E402
import d1_indicators as Q  # noqa: E402
import robust_long as R  # noqa: E402

COST_PCT = 0.001
UNIVERSES = (("標普 500", "sp500", "us"), ("納指 100", "ndx", "us"), ("道指", "djia", "us"), ("日經 225", "n225", "jp"), ("恒指", "hsi", "hk"))
FIRST_YEAR = 2005


def load_prices(path):
    rows = {}
    for f in sorted(glob.glob(os.path.join(path, "prices_*.csv"))):
        with open(f) as fh:
            for r in csv.DictReader(fh):
                try:
                    o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
                except (ValueError, KeyError, TypeError):
                    continue
                if min(o, h, l, c) <= 0:
                    continue
                rows[r["Date"]] = (o, h, l, c)
    if len(rows) < 260:
        return None
    ks = sorted(rows)
    t = np.array([int(dt.datetime.strptime(k, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()) for k in ks], dtype=np.int64)
    a = np.array([rows[k] for k in ks])
    return {"t": t, "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


def membership(src, key):
    out = {}
    if key == "hsi":
        for y in range(2010, 2027):
            f = os.path.join(src, "scripts", "pointintime", f"hsi_{y}.txt") if y < 2026 else os.path.join(src, "scripts", "universe_hsi_live.txt")
            if not os.path.exists(f):
                continue
            for ln in open(f):
                s = ln.strip()
                if s and not s.startswith("#"):
                    out.setdefault(s, []).append((dt.date(y, 1, 1), dt.date(y + 1, 1, 1)))
        return out
    for r in csv.DictReader(open(os.path.join(src, "universes", key, "membership.csv"))):
        st = dt.date.fromisoformat(r["start"]); en = dt.date.fromisoformat(r["end"]) if r.get("end") else dt.date(2100, 1, 1)
        out.setdefault(r["ticker"], []).append((st, en))
    return out


def member(spans, ts):
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
    return any(a <= d < b for a, b in spans)


def b_signals(B):
    b5, x5 = Q.signals(B, "J5", dict(ex=2))
    tu, td = B.c > B.s200, B.c < B.s200
    return b5 & B.sar_up & tu, x5 & ~B.sar_up & td


def net(B, tr):
    """扣 0.1% 成本：R − 0.1% × 入場價 ÷ 止蝕距離。"""
    idx = {int(t): i for i, t in enumerate(B.t)}
    return [(x[0], x[1], x[2], x[3] - COST_PCT * B.o[idx[x[0]]] / x[2], x[4]) for x in tr]


def run_ticker(d, spans):
    B = CT.Bars(d, 86400)
    b, x = b_signals(B)
    ok = np.array([member(spans, int(t)) and dt.datetime.fromtimestamp(int(t), dt.timezone.utc).year >= FIRST_YEAR for t in B.t])
    R.COST = 0.0
    tr = net(B, R.simulate(B, CT.ents(B, b & ok, x & ok)))
    base = []
    for s in (1, -1):
        ent = [(i + 1, s, CT.SL * B.datr[i], CT.TP * B.datr[i], CT.NBARS * 24) for i in range(210, len(B.c) - 1, 10) if ok[i] and B.datr[i] > 0]
        base += net(B, R.simulate(B, ent))
    return tr, base


def judge(tr, base):
    rs = np.array([x[3] for x in tr]); s = R.summ(rs)
    win = float((rs > 0).mean()) if len(rs) else 0.0
    bwin = float(np.mean([x[3] > 0 for x in base])) if base else 0.0
    yy = {}
    for x in tr:
        yy.setdefault(R.yr(x[0]), []).append(x[3])
    pos = sum(1 for v in yy.values() if np.mean(v) > 0)
    h1 = R.summ([x[3] for x in tr if R.yr(x[0]) <= 2015]); h2 = R.summ([x[3] for x in tr if R.yr(x[0]) >= 2016])
    lo = R.summ([x[3] for x in tr if x[1] > 0]); sh = R.summ([x[3] for x in tr if x[1] < 0])
    ok = dict(n=s["n"] >= 300, avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, edge=win - bwin >= 0.02,
              yrs=len(yy) > 0 and pos >= 0.6 * len(yy), halves=h1["avg"] > 0 and h2["avg"] > 0)
    txt = (f"{s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f}｜勝率 {win:.1%}（基準 {bwin:.1%}，{100 * (win - bwin):+.1f}pp）｜"
           f"{pos}/{len(yy)} 年正｜前半 {h1['avg']:+.3f}、後半 {h2['avg']:+.3f}｜做多 {lo['n']} 張 {lo['avg']:+.3f}、做空 {sh['n']} 張 {sh['avg']:+.3f}")
    return ok, txt, yy


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--src", default="/tmp/eq"); a = ap.parse_args()
    out = ["# 日線 B 確認放落股票（IDEAS #181）", "",
           "- 規則同 #173 B 一字不改；日線收市判、下一日開市入；TP 4／SL 2 × ATR20；20 個曆日；每張扣 0.1%；只計訊號日係成分股嘅訊號（point-in-time）",
           f"- 數據：選股陣分支 data/equities（已調整日線）；{FIRST_YEAR} 年起（恒指 2010 年起）", "",
           "| 指數 | 有數據／名單 | 結果 | 判 |", "|---|---|---|---|"]
    cache = {}
    detail = []
    for name, key, mkt in UNIVERSES:
        mem = membership(a.src, key)
        trs, bases, have = [], [], 0
        per = {}
        for tk, spans in mem.items():
            p = os.path.join(a.src, "data", "equities", mkt, tk)
            if not os.path.isdir(p):
                continue
            if (mkt, tk) not in cache:
                cache[(mkt, tk)] = load_prices(p)
            d = cache[(mkt, tk)]
            if d is None:
                continue
            have += 1
            tr, base = run_ticker(d, spans)
            trs += tr; bases += base
            if tr:
                per[tk] = np.mean([x[3] for x in tr])
        ok, txt, yy = judge(trs, bases)
        pos_tk = sum(1 for v in per.values() if v > 0)
        out.append(f"| {name} | {have}／{len(mem)} | {txt}｜賺錢股票 {pos_tk}/{len(per)} | {'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        detail += ["", f"### {name} 逐年", "", "、".join(f"{y} {np.mean(v):+.3f}（{len(v)}）" for y, v in sorted(yy.items()))]
        print(name, txt, flush=True)
    out += ["", "## 逐年平均 R（張數）", *detail, "",
            "- 注意：名單入面已下市而冇數據嘅股票會缺（標普 500 名單 1,262 隻有數據 702 隻），有倖存者偏差，結果會偏好睇。",
            "- 合格嘅指數 → 每日掃描影子前向，同龍飛陣、鳥翔陣核對重覆；真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "B_STOCKS.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
