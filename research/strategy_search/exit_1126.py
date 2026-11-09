"""[IDEAS #1126] 趨勢簿兩條規則（#1107 上季突破、#1113 低波幅 20 日突破）加止賺／移動止蝕：同一批入場，只改出場。
變體（預先登記，冇網格）：
  base：原版（SL 或到期收市）；TP2：止賺 2R；TP3：止賺 3R；
  BE2：浮賺到 2R 之後止蝕移去成本價；TR2：浮賺到 2R 之後，止蝕跟住最高（低）位減（加）2R（只升唔跌）。
細節：入場、SL、到期同原版一樣；每根 H1 先查止蝕再查止賺（保守）；入場嗰根唔查止賺；BE／TR 由觸發嗰根之後下一根先生效；每張扣 0.5 美元。
數據：Dukascopy H1 A＝2005–2014、B＝2015–2026-10。兩條規則合併計（同真倉一樣）。
成功（預先登記）：變體要喺 A 同 B 都 ① 平均 R ≥ 原版 ② ΣR／最大回撤 ≥ 原版，先可以提案改真倉；幾個都過就揀 B 段 ΣR／回撤最高嗰個。
用法：python3 research/strategy_search/exit_1126.py → research/strategy_search/EXIT_1126.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import h1_lab as L              # noqa: E402
import h1_lab3 as L3            # noqa: E402
import h1_lab6 as H6            # noqa: E402
import h1_lab7 as H7            # noqa: E402

COST = L3.COST
VARIANTS = ("base", "TP2", "TP3", "BE2", "TR2")
MODE = ["base"]


def trade_break(g, s, e, hi, lo, sl_fn, tp_mult, allow):
    """同 h1_lab3.trade_break 一樣嘅入場；出場按 MODE。"""
    o, h, l, c, t = g["o"], g["h"], g["l"], g["c"], g["t"]
    mode = MODE[0]
    for j in range(s, e):
        if not allow(j):
            continue
        up, dn = h[j] >= hi, l[j] <= lo
        if not (up or dn):
            continue
        sg = 1 if up else -1
        en = max(hi, o[j]) if sg > 0 else min(lo, o[j]); sl = sl_fn(sg); risk = (en - sl) * sg
        if risk <= 0.5:
            return None
        if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
            return (int(t[j]), sg, (sg * (sl - en) - COST) / risk)
        tp = en + sg * {"TP2": 2, "TP3": 3}[mode] * risk if mode in ("TP2", "TP3") else None
        peak = h[j] if sg > 0 else l[j]
        armed = (peak - en) * sg >= 2 * risk
        ex = None
        for k in range(j + 1, e):
            if mode in ("BE2", "TR2") and armed:
                nsl = en if mode == "BE2" else peak - sg * 2 * risk
                sl = max(sl, nsl) if sg > 0 else min(sl, nsl)
            if (l[k] <= sl) if sg > 0 else (h[k] >= sl):
                ex = sl; break
            if tp is not None and ((h[k] >= tp) if sg > 0 else (l[k] <= tp)):
                ex = tp; break
            peak = max(peak, h[k]) if sg > 0 else min(peak, l[k])
            armed = armed or (peak - en) * sg >= 2 * risk
        if ex is None:
            ex = c[e - 1]
        return (int(t[j]), sg, (sg * (ex - en) - COST) / risk)
    return None


L3.trade_break = trade_break


def st(tr):
    r = np.array([x[2] for x in sorted(tr)], float)
    if not len(r):
        return {"n": 0, "avg": -9, "sum": 0, "dd": 0, "ratio": 0, "pf": 0}
    eq = np.cumsum(r); dd = float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max())
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": len(r), "avg": float(r.mean()), "sum": float(r.sum()), "dd": dd, "ratio": float(r.sum() / dd) if dd else 99.0, "pf": float(w / ls) if ls else 99.0}


def main():
    gA, gB = L.h1("xau/sig/duka_h1/", 2005, 2014), L.h1("xau/sig/duka_h1/", 2015, 2026)
    res = {}
    for v in VARIANTS:
        MODE[0] = v
        for seg, g in (("A", gA), ("B", gB)):
            q, lv = H6.r1107(g), H7.r1113(g)
            res[(v, seg)] = {"qbrk": st(q), "lvbrk": st(lv), "合併": st(q + lv)}
    f = lambda s: f"{s['n']} 張 {s['avg']:+.3f}R PF {s['pf']:.2f} ΣR {s['sum']:+.1f} 回撤 {s['dd']:.1f} ΣR÷回撤 {s['ratio']:.1f}"
    out = ["# 趨勢簿出場：止賺／移動止蝕（IDEAS #1126）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Dukascopy H1 A＝2005–2014、B＝2015–2026-10；同一批入場只改出場；兩條合併為主判", ""]
    for part in ("合併", "qbrk", "lvbrk"):
        out += [f"## {part}", "", "| 變體 | A 2005–2014 | B 2015–2026 |", "|---|---|---|"]
        out += [f"| {v} | {f(res[(v, 'A')][part])} | {f(res[(v, 'B')][part])} |" for v in VARIANTS]
        out.append("")
    b = {seg: res[("base", seg)]["合併"] for seg in "AB"}
    passed = []
    out += ["## 判（預先登記 IDEAS #1126；合併）", ""]
    for v in VARIANTS[1:]:
        ok = all(res[(v, seg)]["合併"]["avg"] >= b[seg]["avg"] and res[(v, seg)]["合併"]["ratio"] >= b[seg]["ratio"] for seg in "AB")
        out.append(f"- {v}：{'✅' if ok else '❌'}")
        if ok:
            passed.append(v)
    best = max(passed, key=lambda v: res[(v, "B")]["合併"]["ratio"]) if passed else None
    out += ["", "- " + (f"✅ {best} 兩段都唔差過原版 → 只提案：趨勢簿改用 {best}（要使用者批，先影子對照）" if best else "❌ 冇變體兩段都贏原版 → 趨勢簿照原版（冇 TP、到期平）；唔准改參數再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "EXIT_1126.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
