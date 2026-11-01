"""[IDEAS #178] 日線 B 確認（#173，規則一字不改）放落多個市場：使用者 11-01 上載嘅券商 MT5 *_MAX（GCS xau/data/mt5/max/MAX.zip），
用 H1（伺服器時間按 UTC+2／美國夏令時 UTC+3 轉 UTC）合成 D1（22:00 UTC 日界）。TP 4／SL 2 × D1 ATR20、20 日、下一日第一根 H1 開盤入、
同一根都掂當 SL、一次一張。成本＝每個品種一個點差估計（COSTS）。黃金同白銀已經睇過，只作描述；主判＝其餘 14 個市場合計。
用法：python3 research/strategy_search/b_multi.py → B_MULTI.md"""
import io
import os
import sys
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_combo as C  # noqa: E402
import d1_indicators as Q  # noqa: E402
import import_mt5 as I  # noqa: E402
import robust_long as R  # noqa: E402

ZIP_GCS = "xau/data/mt5/max/MAX.zip"
ZIP_LOCAL = "/tmp/maxdl/MAX.zip"
COSTS = {"EURUSD": 0.0001, "GBPUSD": 0.00015, "AUDUSD": 0.00012, "NZDUSD": 0.00015, "USDCAD": 0.00015, "USDCHF": 0.00015,
         "USDJPY": 0.012, "EURJPY": 0.02, "GBPJPY": 0.03, "NAS100": 2.0, "GER40": 2.0, "UK100": 1.5, "CL-OIL": 0.04, "BTCUSD": 30.0,
         "XAUUSD": 0.5, "XAGUSD": 0.03}
SEEN = {"XAUUSD", "XAGUSD"}


def load_zip():
    if not os.path.exists(ZIP_LOCAL):
        from google.cloud import storage
        os.makedirs(os.path.dirname(ZIP_LOCAL), exist_ok=True)
        storage.Client().bucket("zhuge-risk-manager-bucket").blob(ZIP_GCS).download_to_filename(ZIP_LOCAL)
    return zipfile.ZipFile(ZIP_LOCAL)


def h1_of(z, sym):
    nm = next(f.filename for f in z.infolist() if f.filename.split("/")[-1] == f"{sym}_H1_MAX.csv")
    rows = [ln.split(",") for ln in io.TextIOWrapper(z.open(nm), encoding="utf-8").read().splitlines()[1:] if ln.strip()]
    t = np.array([I.server_to_utc(r[0]) for r in rows], dtype=np.int64)
    a = np.array([[float(v) for v in r[1:5]] for r in rows])
    o = np.argsort(t, kind="stable"); t, a = t[o], a[o]
    keep = np.r_[True, t[1:] != t[:-1]]
    return t[keep], a[keep, 0], a[keep, 1], a[keep, 2], a[keep, 3]


def b_trades(D):
    b5, x5 = Q.signals(D, "J5", C.P5)
    tu, td = D.dc > D.s200, D.dc < D.s200
    return R.simulate(D, C.ents(D, b5 & D.sar_up & tu, x5 & ~D.sar_up & td))


def main():
    z = load_zip()
    syms = sorted({f.filename.split("/")[-1].rsplit("_", 2)[0] for f in z.infolist() if f.filename.endswith("_H1_MAX.csv")})
    out = ["# 日線 B 確認放落多個市場（IDEAS #178）", "",
           "- 券商 MT5 2022-08→2026-10（BTC 2020-08 起）；規則同 #173 B 一字不改；SMA200 要 200 日預熱，所以大部分市場由 2023 年中先有訊號",
           "- 主判＝黃金、白銀以外 14 個市場合計；成本用每個品種嘅點差估計", "",
           "| 品種 | 張數 | 勝率 | 隨機基準 | 平均 R | PF | ΣR |", "|---|---|---|---|---|---|---|"]
    pool, pool_b, per = [], [], {}
    for s in syms:
        R.COST = COSTS.get(s, 0.0)
        D = Q.DI(*h1_of(z, s))
        tr = b_trades(D); bw = C.base_win(D)
        rs = np.array([x[3] for x in tr]); st = R.summ(rs)
        win = float((rs > 0).mean()) if len(rs) else 0.0
        bwin = float(np.mean([bw.get(R.yr(x[0]), np.nan) for x in tr])) if tr else float("nan")
        per[s] = st
        out.append(f"| {s}{'（已睇過）' if s in SEEN else ''} | {st['n']} | {win:.0%} | {bwin:.0%} | {st['avg']:+.3f} | {st['pf']:.2f} | {rs.sum():+.1f} |")
        if s not in SEEN:
            pool += tr; pool_b += [bw.get(R.yr(x[0]), np.nan) for x in tr]
        print(s, R.fmt(st), flush=True)
    rs = np.array([x[3] for x in pool]); st = R.summ(rs)
    win = float((rs > 0).mean()) if len(rs) else 0.0; bwin = float(np.nanmean(pool_b)) if pool_b else 0.0
    yy = {}
    for x in pool:
        yy.setdefault(R.yr(x[0]), []).append(x[3])
    pos_sym = sum(1 for s, v in per.items() if s not in SEEN and v["n"] and v["avg"] > 0)
    nsym = sum(1 for s, v in per.items() if s not in SEEN and v["n"])
    pos_y = sum(1 for v in yy.values() if np.mean(v) > 0)
    ok = dict(n=st["n"] >= 100, avg=st["avg"] >= 0.05, pf=st["pf"] >= 1.15, edge=win - bwin >= 0.02,
              syms=nsym > 0 and pos_sym >= 0.6 * nsym, yrs=len(yy) >= 3 and pos_y >= len(yy) - 1)
    out += ["", "## 主判：14 個市場合計", "",
            f"- {st['n']} 張 平均 {st['avg']:+.3f}R PF {st['pf']:.2f}；勝率 {win:.1%}（隨機基準 {bwin:.1%}，{100 * (win - bwin):+.1f}pp）",
            f"- 正數市場 {pos_sym}/{nsym}；逐年：" + "、".join(f"{y} {np.mean(v):+.3f}（{len(v)} 張）" for y, v in sorted(yy.items())),
            f"- 判：{'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)}", "",
            "- 合格 → 多市場 B 一齊加入影子前向（加張數）；真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "B_MULTI.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[-8:]))


if __name__ == "__main__":
    main()
