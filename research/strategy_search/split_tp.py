"""[IDEAS #1013] 分段止賺：E6S4 一半喺 TP1（1R）走，另一半追 TP2（2R），TP1 之後餘下一半止蝕移去成交價（保本）。
主判：rev15 E6S4；描述：#1011 整數關口 E6S4、同埋「分段但唔移保本」。
同一批訊號、同一套成交規則（ai_entry_forward.sim 嘅成交法），只係出場唔同。規格、成功標準以 IDEAS #1013 預先登記為準（跑之前 commit）。
細節（預先定）：同一根掂 SL 同 TP1 當 SL；TP1 嗰根唔再查餘下一半（由下一根先查）；24 小時內 TP1 都未掂又未止蝕 → 唔計（同原版）；
TP1 之後 24 小時（由成交起計）餘下一半未完 → 用最後一根收市平；成本每張 0.5 美元（兩半合共一次）。
用法：python3 research/strategy_search/split_tp.py → research/strategy_search/SPLIT_TP.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import ai_entry_forward as af   # noqa: E402
import round_e6s4 as RD         # noqa: E402

fr = af.fr
COST, TOL, TTL, HORIZON = af.COST, af.TOL, af.TTL, af.HORIZON
LB, TH = 15, 3.0


def sim_split(d, ts, sgn, mid, be=True):
    """回傳 (原版 R, 分段 R)；任何一個未完就係 None。入場區 mid±2、SL mid−4、TP1 mid+4、TP2 mid+8（以 sgn 方向）。"""
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]
    lo, hi = mid - 2.0, mid + 2.0
    sl, tp1, tp2 = mid - sgn * 4.0, mid + sgn * 4.0, mid + sgn * 8.0
    a = int(np.searchsorted(t, ts))
    fi = None
    for j in range(a, len(t)):
        if t[j] - ts > TTL:
            break
        if l[j] <= hi + TOL and h[j] >= lo - TOL:
            near = hi if sgn > 0 else lo
            fill = min(o[j], max(near, l[j])) if sgn > 0 else max(o[j], min(near, h[j]))
            fi = j
            break
    if fi is None:
        return None, None
    hit = lambda j, px, stop: ((l[j] <= px) if sgn > 0 else (h[j] >= px)) if stop else ((h[j] >= px) if sgn > 0 else (l[j] <= px))
    k = None
    for j in range(fi, len(t)):
        if t[j] - t[fi] > HORIZON:
            return None, None
        if hit(j, sl, True):
            r = (sgn * (sl - fill) - COST) / 4.0
            return r, r
        if hit(j, tp1, False):
            k = j; break
    if k is None:
        return None, None
    base = (sgn * (tp1 - fill) - COST) / 4.0
    stop2 = fill if be else sl
    ex2 = None
    last = k
    for j in range(k + 1, len(t)):
        if t[j] - t[fi] > HORIZON:
            break
        last = j
        if hit(j, stop2, True):
            ex2 = stop2; break
        if hit(j, tp2, False):
            ex2 = tp2; break
    if ex2 is None:
        ex2 = c[last]
    split = (0.5 * sgn * (tp1 - fill) + 0.5 * sgn * (ex2 - fill) - COST) / 4.0
    return base, split


def rev15_sigs(d):
    t, o, c = d["t"], d["o"], d["c"]
    n = len(t)
    mv = np.full(n, np.nan); mv[LB:] = c[LB:] - o[:-LB]
    ok = (np.abs(mv) >= TH) & (np.arange(n) >= 29)
    raw = [(int(i), "BUY" if mv[i] < 0 else "SELL") for i in np.nonzero(ok)[0]]
    sigs = fr.cooldown(raw, t, 60, int(t[0]), int(t[-1]) + 60)
    out = []
    for i, side in sigs:
        sg = 1 if side == "BUY" else -1
        out.append((int(t[i]) + 60, sg, float(c[i]) - sg * 6.0))
    return out


def round_sigs(d):
    """同 round_e6s4.run 一樣嘅觸發（唔計結果）。"""
    t, h, l, c = d["t"], d["h"], d["l"], d["c"]
    day = t // 86400; hour = (t // 3600) % 24
    out, used = [], set()
    for i in range(1, len(t)):
        if not (RD.HOURS[0] <= hour[i] < RD.HOURS[1]):
            continue
        pc = c[i - 1]
        up = np.floor(pc / RD.STEP) * RD.STEP + RD.STEP
        dn = np.ceil(pc / RD.STEP) * RD.STEP - RD.STEP
        for sg, lvl, ht in ((-1, up, h[i] >= up), (1, dn, l[i] <= dn)):
            key = (int(day[i]), sg, lvl)
            if not ht or key in used:
                continue
            used.add(key)
            out.append((int(t[i]) + 60, sg, lvl - sg * 6.0))
    return out


def evaluate(d, sigs):
    rows = []
    for ts, sg, mid in sigs:
        b, s = sim_split(d, ts, sg, mid, be=True)
        if b is None:
            continue
        _, s2 = sim_split(d, ts, sg, mid, be=False)
        rows.append((ts, b, s, s2 if s2 is not None else np.nan))
    return rows


def mdd(r):
    eq = np.cumsum(r)
    return float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max()) if len(r) else 0.0


def yearly(rows, col):
    ys = {}
    for x in rows:
        ys.setdefault(dt.datetime.fromtimestamp(x[0], dt.timezone.utc).year, []).append(x[col])
    return {y: np.array(v, float) for y, v in sorted(ys.items())}


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    sets = [("Dukascopy 2015–2022", duka), ("MT5 2023-01→2026-10", mt5)]
    out = ["# 分段止賺（IDEAS #1013）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；E6S4：入場區 ±2、SL 4；原版全部喺 TP1（1R）走；"
           "分段＝一半 TP1、一半追 TP2（2R），TP1 之後餘下一半止蝕移去成交價；同一批訊號同成交", "",
           "| 規則 | 數據 | 原版（全部 1R） | 分段＋保本（主判） | 分段唔保本（描述） |", "|---|---|---|---|---|"]
    res = {}
    for rule, gen in (("rev15 E6S4", rev15_sigs), ("#1011 整數關口", round_sigs)):
        for name, d in sets:
            rows = evaluate(d, gen(d))
            res[(rule, name)] = rows
            cols = [np.array([x[k] for x in rows], float) for k in (1, 2, 3)]
            cells = [f"{fr.fmt(fr.stats(v))} 最大回撤 {mdd(v[~np.isnan(v)]):.1f}R" for v in cols]
            out.append(f"| {rule} | {name} | " + " | ".join(cells) + " |")
    out += ["", "## rev15 Dukascopy 每年（原版 對 分段＋保本）", "", "| 年 | 原版 | 分段＋保本 |", "|---|---|---|"]
    rd = res[("rev15 E6S4", sets[0][0])]; rm = res[("rev15 E6S4", sets[1][0])]
    yb, ys = yearly(rd, 1), yearly(rd, 2)
    out += [f"| {y} | {fr.fmt(fr.stats(yb[y]))} | {fr.fmt(fr.stats(ys[y]))} |" for y in yb]
    g = lambda rows, k: float(np.mean([x[k] for x in rows])) if rows else -9
    dd = lambda rows, k: mdd(np.array([x[k] for x in rows], float))
    better = sum(1 for y in yb if ys[y].mean() >= yb[y].mean())
    ok = {"①rev15 Duka 分段平均 − 原版 ≥ +0.02R": g(rd, 2) - g(rd, 1) >= 0.02,
          "②rev15 MT5 分段平均 − 原版 ≥ +0.02R": g(rm, 2) - g(rm, 1) >= 0.02,
          "③Duka 8 年 ≥ 5 年分段唔差過原版": better >= 5,
          "④兩批數據分段最大 R 回撤 ≤ 原版 × 1.1": dd(rd, 2) <= dd(rd, 1) * 1.1 and dd(rm, 2) <= dd(rm, 1) * 1.1}
    out += ["", "## 判（預先登記 IDEAS #1013；主判 rev15 分段＋保本）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            f"- Duka 分段唔差過原版嘅年份 {better}／{len(yb)}",
            "- " + ("✅ 達標 → 只提案：rev15／933 影子加分段版並排前向（唔落單）" if all(ok.values())
                    else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔准改 TP2／保本位再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "SPLIT_TP.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
