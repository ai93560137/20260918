"""[IDEAS #227b] A+＋H4 雙向過濾 影子前向（唔落單），同 A+ 影子（即真倉 935 嘅對照）並列。
使用者 11-04 喺總指揮「寫影子」：11-05 00:00 UTC 起入場計；單倉；成份同揀法同 ttm_forward／candle_forward 嘅 A+ 一樣。
H4 斜率同 921 R368（filter_921.H4Slope：最後一根已收市 H4、22:00 UTC 對齊、EMA50 差）；雙向＝斜率 > 0 唔做空、< 0 唔做多；喺揀單倉之前擋。
判：滿 30 張（過濾版）或到 2027-05-01（先到），過濾版 ΣR 同最大回撤都好過 A+ 影子 → 提案改 combo_live（總指揮 dry-run＋使用者批）。
警示：過濾版累計 ≤ −12R 或回撤 ≤ −15R → 即報總指揮。輸出 H4_APLUS_FORWARD.md。
用法：python3 research/strategy_search/h4_aplus_forward.py"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import b_forward as BF  # noqa: E402
import candle_forward as CF  # noqa: E402
import d1_indicators as Q  # noqa: E402
import exits_forward as EF  # noqa: E402
import filter_921 as F  # noqa: E402
import h4_indicators as H  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402

START_TS = int(dt.datetime(2026, 11, 5, tzinfo=dt.timezone.utc).timestamp())
END_DAY = dt.date(2027, 5, 1)
TARGET_N = 30


def blocked(s, slope):
    return (s > 0 and slope < 0) or (s < 0 and slope > 0)


def filt_rows(rows, hs):
    """擋走逆 H4 嘅已平倉同待入場（ts 用入場時間）。"""
    return [(nm, p, [x for x in done if not blocked(x[1], hs.at(x[0]))], [e for e in pend if not blocked(e[1], hs.at(e[0]))])
            for nm, p, done, pend in rows]


def since(rows):
    return [(nm, p, [x for x in done if x[0] >= START_TS], [e for e in pend if e[0] >= START_TS]) for nm, p, done, pend in rows]


def main():
    R.COST = 0.5
    arr, n_new = BF.load_h1()
    frames = {"D1": Q.DI(*arr), "H4": H.H4I(*arr), "W": S2.D2(*arr)}
    hs = F.H4Slope(np.asarray(arr[0], dtype=np.int64), np.asarray(arr[4], dtype=float))
    now = dt.datetime.now(dt.timezone.utc); year = max(now.year, 2026)
    aplus = since(EF.book(frames, year, False) + [CF.candle_row(frames["D1"], year)])
    out = ["# A+＋H4 雙向過濾 影子前向（IDEAS #227b）", "",
           f"- 更新：{now:%Y-%m-%d %H:%M} UTC；最後一根 H1：{dt.datetime.fromtimestamp(int(arr[0][-1]), dt.timezone.utc):%Y-%m-%d %H:%M} UTC（經紀心跳新增 {n_new} 根）；"
           f"而家 H4 斜率 {hs.at(int(arr[0][-1]) + 3600):+.3f}",
           "- 單倉、2026-11-05 起入場、唔落單、每張扣 0.5 美元；A+＝935 真倉嘅影子對照；過濾＝H4 斜率 > 0 唔做空、< 0 唔做多（揀單倉之前擋）",
           f"- 判：滿 {TARGET_N} 張（過濾版）或 {END_DAY}（先到），過濾版 ΣR 同最大回撤都好過 A+ 先提案改 combo_live；警示：過濾版累計 ≤ −12R 或回撤 ≤ −15R",
           "- 回測對照（2009→2026 單倉，#227b）：A+ 981 張 +0.101R PF 1.30 回撤 −25.7R；過濾版 765 張 +0.147R PF 1.45 回撤 −9.2R", ""]
    res = {}
    for label, rows in (("A+＋H4 雙向過濾", filt_rows(aplus, hs)), ("A+（對照）", aplus)):
        tr, pend = EF.single(rows); s, dd, mx = EF.stats(tr); res[label] = (s, dd)
        out += [f"## {label}", "", "| 成份 | 今年揀法 |", "|---|---|", *[f"| {r[0]} | {r[1]} |" for r in rows], ""]
        out += ["持倉中／待入場：" + ("冇" if not pend else "；".join(
            f"{nm} {'多' if e[1] > 0 else '空'} {dt.datetime.fromtimestamp(e[0], dt.timezone.utc):%m-%d %H:%M} 入 {e[2]:.2f} SL {e[2] - e[1] * e[3]:.2f}"
            + (f" TP {e[2] + e[1] * e[4]:.2f}" if e[4] else "") + f" 最多 {e[5]:.0f}h（入場時 H4 斜率 {hs.at(e[0]):+.3f}）" for _, _, e, nm in pend)), ""]
        out += ["| 入場（UTC） | 成份 | 方向 | H4 斜率 | 出場 | R |", "|---|---|---|---|---|---|"]
        out += [f"| {dt.datetime.fromtimestamp(x[0], dt.timezone.utc):%Y-%m-%d %H:%M} | {nm} | {'多' if x[1] > 0 else '空'} | {hs.at(x[0]):+.3f} | "
                f"{dt.datetime.fromtimestamp(x[4], dt.timezone.utc):%m-%d %H:%M} | {x[3]:+.2f} |" for nm, x in tr] or ["| — | — | — | — | — | — |"]
        out += ["", f"- {s['n']} 張；ΣR {s['sum']:+.2f}；" + (f"平均 {s['avg']:+.3f}R PF {s['pf']:.2f}；最大回撤 {dd:+.1f}R；最長連輸 {mx}" if s["n"] else "未有平倉"), ""]
    (sf, df), (sa, da) = res["A+＋H4 雙向過濾"], res["A+（對照）"]
    warn = sf["n"] and (sf["sum"] <= -12 or df <= -15)
    due = sf["n"] >= TARGET_N or now.date() >= END_DAY
    better = sf["sum"] > sa["sum"] and df >= da
    out += ["## 判", "", f"- 過濾版 − A+：ΣR {sf['sum'] - sa['sum']:+.2f}、回撤 {df - da:+.1f}R；進度 {sf['n']}／{TARGET_N} 張",
            "- " + ("⚠ 過濾版觸發警示（累計 ≤ −12R 或回撤 ≤ −15R）→ 報總指揮" if warn else
                    (("✅ 到期：過濾版 ΣR 同回撤都好過 A+ → 提案改 combo_live（總指揮 dry-run＋使用者批）" if better else "❌ 到期：過濾版冇同時好過 A+ → 唔改") if due else "未到期")), ""]
    open(os.path.join(HERE, "H4_APLUS_FORWARD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
