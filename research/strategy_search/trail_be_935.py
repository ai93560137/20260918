"""[IDEAS #203] 935 追蹤止蝕＋保本：入場、每年參數（同 935 滾動前向揀法）、單倉規則唔變，只改五個指標成份嘅出場；星期效應唔變。
模式：fix＝935 現行（固定 TP／SL）；be＝固定 TP，+1R 後止蝕搬入場價；tr2／tr3＝冇 TP、追蹤 2／3 × ATR；
      主判 betr3＝冇 TP、追蹤 3 × ATR，另外浮盈到 +1R 後止蝕最少喺入場價（保本＋追蹤）；描述 betr2 同理用 2 × ATR。
止蝕更新喺每根 H1 收市後、下一根生效（同 #189）。判「比 935 好」同 #192；另列近 10 年正數月、每張 1%。
用法：python3 research/strategy_search/trail_be_935.py → TRAIL_BE_935.md"""
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
import robust_long as R  # noqa: E402
import xag_lead as XL  # noqa: E402

MODES = {"fix": (False, None, True), "be": (True, None, True), "tr2": (False, 2.0, False), "tr3": (False, 3.0, False),
         "betr2": (True, 2.0, False), "betr3": (True, 3.0, False)}          # (保本, 追蹤倍數, 有 TP)
A_SINGLE = dict(avg=0.083, pf=1.24, yrs10=7, dd=-26.6)


def sim(D, entries, mode):
    be_on, k, use_tp = MODES[mode]
    t, o, h, l = D.t, D.o, D.h, D.l
    n = len(t); out = []; busy = -1
    for a, s, d, tpd, mh, atr in entries:
        if a <= busy or a >= n or not d or d <= 0 or math.isnan(d):
            continue
        px = o[a]; sl = px - s * d; tp = px + s * tpd if (use_tp and tpd) else None; ext = px; ex = None
        for j in range(a, n):
            if t[j] - t[a] >= mh * 3600:
                ex, xi = o[j], j - 1; break
            if j > a and (o[j] - sl) * s <= 0:
                ex, xi = o[j], j; break
            if (l[j] <= sl) if s > 0 else (h[j] >= sl):
                ex, xi = sl, j; break
            if tp is not None and ((h[j] >= tp) if s > 0 else (l[j] <= tp)):
                ex, xi = tp, j; break
            ext = max(ext, h[j]) if s > 0 else min(ext, l[j])
            cand = []
            if be_on and (ext - px) * s >= d:
                cand.append(px + s * R.COST)
            if k:
                cand.append(ext - s * k * atr)
            for c in cand:
                if (c - sl) * s > 0:
                    sl = c
        if ex is None:
            break
        out.append((int(t[a]), s, float(d), float((s * (ex - px) - R.COST) / d), int(t[min(xi + 1, n - 1)])))
        busy = xi
    return out


def streams(frames, picks, mode, base, a_from=None):
    res = dict(base)
    for name, fam, tf, th in X.COMPS:
        D = frames[tf]; grid = Q.FAMILIES[fam]; tr = []
        for Y, g in picks[name].items():
            if g is None:
                continue
            p = grid[g]; b, x = Q.signals(D, fam, p); tp, sl = Q.EXITS[p["ex"]]
            ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, sl * D.datr[d], tp * D.datr[d], th, D.datr[d])
                   for d in np.flatnonzero(b | x) if 210 <= d < len(D.dc) - 1 and D.datr[d] > 0 and R.yr(D.t[D.dfirst[d + 1]]) == Y]
            tr += sim(D, ent, mode)
        res[name] = [z for z in tr if a_from is None or z[0] >= a_from]
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
    fd = {"D1": Q.DI(*gd), "H4": H.H4I(*gd)}; fm = {"D1": Q.DI(*gm), "H4": H.H4I(*gm)}
    ds, picks = P.streams(gd); ms, _ = P.streams(gm, picks); keys = [k for k in ds if not k.startswith("7")]
    msA = {k: [x for x in ms[k] if x[0] >= P.A0] for k in keys}
    mpicks = {k: {Y: g for Y, g in v.items() if Y >= 2022} for k, v in picks.items()}
    out = ["# 935 追蹤止蝕＋保本（IDEAS #203）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；入場／參數／單倉同 935，只改五個指標成份出場", "",
           "| 版本 | 張數 | 平均 R | PF | 合計 R | 近 10 年正 | 18 年正 | 隔夜息後 | MT5 | 最大回撤 R | 每張 1%（30,000） | 近 10 年正數月 | 比 935 好？ |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    labels = {"fix": "935 現行（固定 TP／SL）", "be": "描述：保本（+1R）＋固定 TP", "tr2": "描述：追蹤 2ATR", "tr3": "描述：追蹤 3ATR",
              "betr2": "描述：保本＋追蹤 2ATR", "betr3": "主判：保本＋追蹤 3ATR"}
    for mode in ("fix", "betr3", "betr2", "be", "tr2", "tr3"):
        d_ = ds if mode == "fix" else streams(fd, picks, mode, ds)
        m_ = msA if mode == "fix" else streams(fm, mpicks, mode, msA, P.A0)
        trs = PS.single(d_, keys); mt = PS.single(m_, keys); label = labels[mode]
        ok, s, pos, ny, h1, h2, sw, m, yy = P.report(label, trs, mt); p10, _ = XL.pos10(trs)
        eq = np.cumsum([x[3] for x in trs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min())
        e1, m1, _, _ = P.equity(trs, 30000, 1.0); pm, nm = months(trs)
        better = s["avg"] > A_SINGLE["avg"] and s["pf"] > A_SINGLE["pf"] and p10 >= A_SINGLE["yrs10"] and dd >= A_SINGLE["dd"] and m["n"] > 0 and m["avg"] > 0
        out.append(f"| {label} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['sum']:+.1f} | {p10}/10 | {pos}/{ny} | {sw['avg']:+.3f} | {m['n']} 張 {m['avg']:+.3f} | {dd:+.1f} | "
                   f"{e1:,.0f}（{m1:.0%}） | {pm}/{nm} | {('✅ 更好' if better else '❌') if label.startswith('主判') else '—'} |")
        print(label, s, p10, dd, flush=True)
    out += ["", "- 參數用 935 每年揀法（唔重新揀），所以差異只嚟自出場；#189 係連出場一齊滾動揀（另一個問題）。", ""]
    open(os.path.join(HERE, "TRAIL_BE_935.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
