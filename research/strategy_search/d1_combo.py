"""[IDEAS #173] D1 三指標合用：J5 Keltner 突破＋J7 拋物線 SAR 轉向＋J8 威廉 %R 回歸（#172 揀出，參數固定：全部 TP 4／SL 2 × D1 ATR、20 日；
J7 同 J8 用 SMA200 過濾、J8 門檻 20）。三種合法（預先登記）：
  A 組合：三條規則各自獨立一次一張，成交合埋計；
  B 確認：Keltner 突破做觸發，要拋物線 SAR 同方向而且收市喺 SMA200 同邊；
  C 投票：三個訊號入面 ≥ 2 個喺最近 3 日（今日 + 前兩日）同方向，而且今日至少有一個新訊號。
主判＝白銀 XAGUSD Dukascopy H1 2005→2026（呢三個指標未見過）；黃金 Dukascopy 同 MT5 只作描述（黃金係揀指標嗰份數據）。
用法：python3 research/strategy_search/d1_combo.py → D1_COMBO.md
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import robust_long as R  # noqa: E402
import silver_friday as F  # noqa: E402

TP, SL, T_H = 4.0, 2.0, 20 * 24
P5, P7, P8 = dict(ex=2), dict(filt=True, ex=2), dict(th=20, filt=True, ex=2)


def ents(D, b, x):
    return [(int(D.dfirst[d + 1]), 1 if b[d] else -1, SL * D.datr[d], TP * D.datr[d], T_H)
            for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0]


def combo(D, mode):
    b5, x5 = Q.signals(D, "J5", P5); b7, x7 = Q.signals(D, "J7", P7); b8, x8 = Q.signals(D, "J8", P8)
    if mode == "A":
        tr = []
        for b, x in ((b5, x5), (b7, x7), (b8, x8)):
            tr += R.simulate(D, ents(D, b, x))
        return sorted(tr)
    if mode == "B":
        tu, td = D.dc > D.s200, D.dc < D.s200
        return R.simulate(D, ents(D, b5 & D.sar_up & tu, x5 & ~D.sar_up & td))
    win = lambda a: a | np.r_[False, a[:-1]] | np.r_[False, False, a[:-2]]   # noqa: E731
    vb = win(b5).astype(int) + win(b7) + win(b8); vs = win(x5).astype(int) + win(x7) + win(x8)
    newb, news = b5 | b7 | b8, x5 | x7 | x8
    b = (vb >= 2) & newb & (vs < 2); x = (vs >= 2) & news & (vb < 2)
    return R.simulate(D, ents(D, b, x))


def base_win(D):
    yy = {}
    for s in (1, -1):
        ent = [(int(D.dfirst[d + 1]), s, SL * D.datr[d], TP * D.datr[d], T_H) for d in range(210, len(D.dc) - 1) if D.datr[d] > 0]
        for t_ in R.simulate(D, ent):
            yy.setdefault(R.yr(t_[0]), []).append(t_[3] > 0)
    return {y: float(np.mean(v)) for y, v in yy.items()}


def judge(tr, bw):
    rs = np.array([x[3] for x in tr]); s = R.summ(rs); yy = {}
    for x in tr:
        yy.setdefault(R.yr(x[0]), []).append(x[3])
    pos = sum(1 for v in yy.values() if np.mean(v) > 0)
    win = float((rs > 0).mean()) if len(rs) else 0.0
    bwin = float(np.mean([bw.get(R.yr(x[0]), np.nan) for x in tr])) if tr else 0.0
    h1 = R.summ([x[3] for x in tr if R.yr(x[0]) <= 2015]); h2 = R.summ([x[3] for x in tr if R.yr(x[0]) >= 2016])
    ok = dict(n=s["n"] >= 100, avg=s["avg"] >= 0.05, pf=s["pf"] >= 1.15, edge=win - bwin >= 0.02,
              yrs=len(yy) >= 12 and pos >= 0.6 * len(yy), halves=h1["avg"] > 0 and h2["avg"] > 0)
    txt = (f"{s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f}；勝率 {win:.1%}（基準 {bwin:.1%}，{100 * (win - bwin):+.1f}pp）；"
           f"{pos}/{len(yy)} 年正；2005–15 {h1['avg']:+.3f}、2016–26 {h2['avg']:+.3f}")
    return ok, txt, yy


def main():
    out = ["# D1 三指標合用（IDEAS #173）", "",
           "- 規則固定：Keltner 突破（J5）、拋物線 SAR 轉向＋SMA200（J7）、威廉 %R 20／80 回歸＋SMA200（J8）；TP 4／SL 2 × D1 ATR、20 日；一次一張",
           "- 主判＝白銀（未見）；黃金只作描述（揀指標嗰份數據，結果偏好睇）", ""]
    R.COST = 0.03
    S = Q.DI(*F.load("xau/sig/duka_h1_xagusd/")); bws = base_win(S)
    out += ["## 白銀 XAGUSD Dukascopy 2005→2026（主判，每張扣 0.03 美元）", "", "| 合法 | 結果 | 判 |", "|---|---|---|"]
    verdict = {}
    for m, name in (("A", "A 組合（三條各自做）"), ("B", "B 確認（Keltner＋SAR＋SMA200）"), ("C", "C 投票（3 揀 2）")):
        ok, txt, _ = judge(combo(S, m), bws); verdict[m] = ok
        out.append(f"| {name} | {txt} | {'✅ 合格' if all(ok.values()) else '❌ ' + '、'.join(k for k, v in ok.items() if not v)} |")
        print(name, txt, flush=True)
    R.COST = 0.5
    duka = R.load_duka(); Gd = Q.DI(*duka); bwg = base_win(Gd)
    out += ["", "## 黃金 Dukascopy 2005→2026（描述，唔算數）", ""]
    for m in "ABC":
        _, txt, yy = judge(combo(Gd, m), bwg)
        out.append(f"- {m}：{txt}")
    try:
        Mx = Q.DI(*R.load_mt5_spliced(duka)); a0 = 1664582400
        out += ["", "## 黃金券商 MT5 2022-10→2026-10（描述）", ""]
        for m in "ABC":
            rs = [x[3] for x in combo(Mx, m) if x[0] >= a0]
            out.append(f"- {m}：{R.fmt(R.summ(rs))}")
    except Exception as e:                                   # noqa: BLE001
        out.append(f"- MT5 讀唔到：{e}")
    passed = [m for m, ok in verdict.items() if all(ok.values())]
    out += ["", "## 判", "", f"- 白銀合格：{'、'.join(passed) if passed else '冇'}",
            "- 白銀合格先升做黃金影子前向候選（真倉要使用者經總指揮批）；唔合格就唔用。", ""]
    open(os.path.join(HERE, "D1_COMBO.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
