"""[IDEAS #1027] 組合研究：933 rev15 E6S4 ＋ #1011 50 美元整數關口 E6S4 ＋ #1022 D1 20 日突破，每張固定 1R 風險、規則同各自回測完全一樣（冇改參數）。
規格、成功標準以 IDEAS #1027 預先登記為準（跑之前 commit）。
計法：每條規則嘅每張單 R 記喺入場時間（近似）；逐月 ΣR；組合＝三條相加。最大回撤用按入場時間排序嘅累計 R。
同時持倉（描述）：#1022 持倉窗口用「入場起 5 個交易日」上限（實際出場未記，所以係高估）；數 rev15／#1011 入場時 #1022 有倉、同方向／反方向幾多次。
成功（全部要達到，兩批數據各自計）：
 ① rev15 同 #1022 逐月 ΣR 相關系數 ≤ 0.2；
 ② 組合 ΣR／最大回撤 ≥ rev15 單獨 ΣR／最大回撤；
 ③ 組合蝕錢月份比例 ≤ rev15 單獨。
用法：python3 research/strategy_search/combo_1027.py → research/strategy_search/COMBO_1027.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import round_e6s4 as RD         # noqa: E402
import batch_1019 as B          # noqa: E402
import rev15_session as RS      # noqa: E402


def rev15(d):
    r, ts = RS.run(d, lambda h: np.ones_like(h, bool))
    t, o, c = d["t"], d["o"], d["c"]
    out = []
    for x, s in zip(r, ts):
        if np.isnan(x):
            continue
        i = int(np.searchsorted(t, s - 60))
        mv = c[i] - o[i - 15]
        out.append((int(s), 1 if mv < 0 else -1, float(x)))
    return out


def month(ts):
    u = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    return u.year * 100 + u.month


def monthly(tr, months):
    m = {k: 0.0 for k in months}
    for ts, _, r in tr:
        m[month(ts)] = m.get(month(ts), 0.0) + r
    return np.array([m[k] for k in months])


def mdd(tr):
    r = np.array([x[2] for x in sorted(tr)], float)
    if not len(r):
        return 0.0, 0.0
    eq = np.cumsum(r)
    return float(eq[-1]), float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max())


def overlap(fast, d1):
    """fast 入場時 #1022 有冇倉（入場起 5 日上限）、同方向／反方向。"""
    win = [(ts, ts + 7 * 86400, sg) for ts, sg, _ in d1]          # 5 個交易日約 7 個日曆日
    same = opp = 0; rs, ro = [], []
    for ts, sg, r in fast:
        for a, b, s2 in win:
            if a <= ts < b:
                if s2 == sg:
                    same += 1; rs.append(r)
                else:
                    opp += 1; ro.append(r)
                break
    return same, opp, rs, ro


def section(name, d):
    t15, tr, td = rev15(d), RD.run(d), B.r1022(d)
    allm = sorted({month(x[0]) for x in t15 + tr + td})
    m15, mr, md_ = monthly(t15, allm), monthly(tr, allm), monthly(td, allm)
    combo = m15 + mr + md_
    c15d = float(np.corrcoef(m15, md_)[0, 1]); c15r = float(np.corrcoef(m15, mr)[0, 1]); crd = float(np.corrcoef(mr, md_)[0, 1])
    s15, d15 = mdd(t15); sc, dc = mdd(t15 + tr + td)
    neg15 = float((m15 < 0).mean()); negc = float((combo < 0).mean())
    ratio = lambda s, dd: s / dd if dd > 0 else float("inf")
    rows = [("rev15（933）", t15), ("#1011 整數關口", tr), ("#1022 D1 20 日突破", td), ("組合（三條相加）", t15 + tr + td)]
    out = [f"## {name}", "", "| 規則 | 張數 | ΣR | 最大回撤 R | ΣR／回撤 | 蝕錢月份 |", "|---|---|---|---|---|---|"]
    for nm, x in rows:
        s, dd = mdd(x)
        mm = monthly(x, allm)
        out.append(f"| {nm} | {len(x)} | {s:+.1f} | {dd:.1f} | {ratio(s, dd):.1f} | {(mm < 0).mean():.0%} |")
    same, opp, rs, ro = overlap(t15 + tr, td)
    out += ["", f"- 逐月相關：rev15 對 #1022 **{c15d:+.2f}**；rev15 對 #1011 {c15r:+.2f}；#1011 對 #1022 {crd:+.2f}（共 {len(allm)} 個月）",
            f"- 同時持倉（描述，#1022 窗口高估）：rev15／#1011 入場時 #1022 有倉 {same + opp} 次（同方向 {same}：{A.fmt(A.stats(rs))}；反方向 {opp}：{A.fmt(A.stats(ro))}）"]
    # rev15 最差 5 個月，#1022 同月表現
    worst = np.argsort(m15)[:5]
    out += ["- rev15 最差 5 個月同月 #1022：" + "；".join(f"{allm[k]} rev15 {m15[k]:+.1f}R／#1022 {md_[k]:+.1f}R" for k in worst)]
    ok = {"①相關 ≤ 0.2": c15d <= 0.2, "②組合 ΣR／回撤 ≥ rev15": ratio(sc, dc) >= ratio(s15, d15), "③組合蝕錢月份 ≤ rev15": negc <= neg15}
    out += [*[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], ""]
    return out, ok


def main():
    sets = [("Dukascopy 2015–2022", A.load("duka", "2015-01-01", "2022-12-31")),
            ("MT5 2023-01→2026-10", A.load("mt5", "2023-01-01", "2026-10-30"))]
    out = ["# 組合研究：rev15＋整數關口＋D1 20 日突破（IDEAS #1027）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；每張固定 1R；規則同各自回測一樣；R 記喺入場時間", ""]
    allok = {}
    for name, d in sets:
        sec, ok = section(name, d)
        out += sec
        allok.update({f"{name} {k}": v for k, v in ok.items()})
    out += ["## 判（預先登記 IDEAS #1027）", "", "- " + ("✅ 達標 → 只提案：三條一齊做影子前向，等各自前向達標再逐條上（唔落單）"
                                                  if all(allok.values()) else "❌ 唔達：" + "、".join(k for k, v in allok.items() if not v)), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "COMBO_1027.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
