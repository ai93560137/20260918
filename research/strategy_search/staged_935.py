"""[IDEAS #201] 935 每張分兩份、分階段平倉：入場、參數（每年同 935 一樣嘅滾動前向揀法）、單倉規則全部唔變，只改出場。
每份風險一半；成交 R＝0.5×第一份 R＋0.5×第二份 R（以成張風險計）；單倉佔位直到兩份都平。
  主判 S1：第一份 +1R 食糊；之後第二份止蝕搬去入場價（＋0.5 美元成本）、照原本 TP／時間止蝕
  描述 S2：第一份喺原本 TP 一半食糊（星期效應冇 TP → +1R）；之後第二份保本，照原本 TP
  描述 S3：第一份照原本固定出場；第二份冇 TP、追蹤止蝕 3 × ATR（#189 tr3 做法）
同一根 K 線掂 SL 同 TP1 當 SL；跳空過 SL 用開盤；止蝕搬位下一根先生效。
判「比 935 好」同 #192：平均 > +0.083R、PF > 1.24、最近 10 年 ≥ 7/10、最大回撤唔差過 −26.6R、MT5 > 0；另列近 10 年正數月。只係提案。
用法：python3 research/strategy_search/staged_935.py → STAGED_935.md"""
import datetime as dt
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import d1_indicators as Q  # noqa: E402
import exits_a as X  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import portfolio_single as PS  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def sim_staged(D, entries, mode):
    """entries：(a, s, d, tpd|None, mh, atr)。回傳 [(入場 ts, s, d, R, 出場 ts)]，R 以成張計。"""
    t, o, h, l = D.t, D.o, D.h, D.l
    n = len(t); out = []; busy = -1
    for a, s, d, tpd, mh, atr in entries:
        if a <= busy or a >= n or not d or d <= 0 or math.isnan(d):
            continue
        px = o[a]; sl = px - s * d
        if mode == "S1":
            tp1 = px + s * d; tp2 = None if tpd is None else px + s * tpd
        elif mode == "S2":
            tp1 = px + s * (0.5 * tpd if tpd else d); tp2 = None if tpd is None else px + s * tpd
        else:
            tp1 = None if tpd is None else px + s * tpd; tp2 = None
        legs = [None, None]; sls = [sl, sl]; ext = px; xi_last = None
        for j in range(a, n):
            for k in (0, 1):
                if legs[k] is not None:
                    continue
                tp = tp1 if k == 0 else tp2
                if t[j] - t[a] >= mh * 3600:
                    legs[k] = (o[j], j - 1); continue
                if j > a and (o[j] - sls[k]) * s <= 0:
                    legs[k] = (o[j], j); continue
                if (l[j] <= sls[k]) if s > 0 else (h[j] >= sls[k]):
                    legs[k] = (sls[k], j); continue
                if tp is not None and ((h[j] >= tp) if s > 0 else (l[j] <= tp)):
                    legs[k] = (tp, j)
            if legs[0] is not None and legs[1] is not None:
                break
            ext = max(ext, h[j]) if s > 0 else min(ext, l[j])
            if mode in ("S1", "S2") and legs[0] is not None and legs[1] is None:
                be = px + s * R.COST
                if (be - sls[1]) * s > 0:
                    sls[1] = be
            if mode == "S3" and legs[1] is None:
                nsl = ext - s * 3.0 * atr
                if (nsl - sls[1]) * s > 0:
                    sls[1] = nsl
        if legs[0] is None or legs[1] is None:
            break
        r = sum(0.5 * (s * (ex - px) - R.COST) / d for ex, _ in legs)
        xi = max(legs[0][1], legs[1][1])
        out.append((int(t[a]), s, float(d), float(r), int(t[min(xi + 1, n - 1)])))
        busy = xi
    return out


def comp_streams(frames, picks, mode, a_from=None):
    """用 935 每年揀法，將五個指標成份同星期效應改分階段出場。"""
    res = {}
    for name, fam, tf, th in X.COMPS:
        D = frames[tf]; grid = Q.FAMILIES[fam]; tr = []
        for Y, g in picks[name].items():
            if g is None:
                continue
            p = grid[g]; b, x = Q.signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]
            ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], th, D.datr[d])
                   for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0 and R.yr(D.t[D.dfirst[d + 1]]) == Y]
            tr += sim_staged(D, ent, mode)
        res[name] = [z for z in tr if a_from is None or z[0] >= a_from]
    DW = frames["W"]; g6 = S2.FAMILIES["S2 星期效應"]; tr = []
    for Y, g in picks["6 星期效應"].items():
        if g is None:
            continue
        p = g6[g]
        ent = [(int(DW.dfirst[d]), p["dir"], 1.5 * DW.datr[d - 1], None, 24, DW.datr[d - 1]) for d in range(21, len(DW.dc))
               if DW.bwd[d] == p["w"] and R.yr(DW.t[DW.dfirst[d]]) == Y]
        tr += sim_staged(DW, ent, mode)
    res["6 星期效應"] = [z for z in tr if a_from is None or z[0] >= a_from]
    return res


def months(trs):
    mm = {}
    for x in trs:
        t = dt.datetime.fromtimestamp(x[4], dt.timezone.utc)
        if 2017 <= t.year <= 2026:
            mm[(t.year, t.month)] = mm.get((t.year, t.month), 0) + x[3]
    return sum(v > 0 for v in mm.values()), len(mm)


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    fd = {"D1": Q.DI(*gd), "H4": H.H4I(*gd), "W": S2.D2(*gd)}; fm = {"D1": Q.DI(*gm), "H4": H.H4I(*gm), "W": S2.D2(*gm)}
    ds, picks = P.streams(gd); ms, _ = P.streams(gm, picks); keys = [k for k in ds if not k.startswith("7")]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    mpicks = {k: {Y: g for Y, g in v.items() if Y >= 2022} for k, v in picks.items()}
    out = ["# 935 分兩份、分階段平倉（IDEAS #201）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；入場／參數／單倉同 935；R 以成張風險計", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 18 年正 | 兩半 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 近 10 年正數月 | 比 935 好？ |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    vers = [("935 現行", ds, msA)]
    for mode, label in (("S1", "主判 S1：+1R 食一半＋保本"), ("S2", "描述 S2：半個 TP 食一半＋保本"), ("S3", "描述 S3：一半固定、一半追蹤 3ATR")):
        vers.append((label, comp_streams(fd, picks, mode), comp_streams(fm, mpicks, mode, P.A0)))
        print(label, flush=True)
    for label, d_, m_ in vers:
        trs = PS.single(d_, keys); mt = PS.single(m_, keys)
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt); p10, _ = XL.pos10(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0); pm, nm = months(trs)
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pos}/{ny} | {h1['avg']:+.3f}／{h2['avg']:+.3f} | {sw['avg']:+.3f} | "
                   f"{m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | {e1:,.0f}（{m1:.0%}） | {pm}/{nm} | {('✅ 更好' if better else '❌') if label.startswith('主判') else '—'} |")
        print(label, s, p10, dd, flush=True)
    out += ["", "- 「每張 1%」按成張風險計手數（兩份合共 1%）；真倉 0.01 手唔可以再分一半，要 0.02 手先分到兩份。", ""]
    open(os.path.join(HERE, "STAGED_935.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
