"""[IDEAS #1000] 市場結構（HH／HL／LH／LL）：D1 定方向、H4 結構入場。規格見 IDEAS #1000（預先登記，跑之前 commit）。
數據：Dukascopy H1（GCS xau/sig/duka_h1/），MT5 伺服器時間（紐約 +7）砌 H4／D1；擺動點分形 k=2，只用已確認點。
用法：python3 research/strategy_search/structure_hhhl.py → STRUCTURE_HHHL.md"""
import bisect
import datetime as dt
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fib_sr as S  # noqa: E402

K = 2
COST = 0.5
HOLD = 30
N_RAND = 20


def agg(st, o, h, l, c, tf):
    keys, bars, idx_of_h1 = [], [], []
    for i in range(len(st)):
        k = S.tf_key(st[i], tf)
        if not keys or keys[-1] != k:
            keys.append(k); bars.append([o[i], h[i], l[i], c[i], st[i]])
        else:
            b = bars[-1]; b[1] = max(b[1], h[i]); b[2] = min(b[2], l[i]); b[3] = c[i]
        idx_of_h1.append(len(bars) - 1)
    a = np.array([b[:4] for b in bars], float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], [b[4] for b in bars], np.array(idx_of_h1)


def pivots(H, L, k=K):
    ph, pl = [], []
    for i in range(k, len(H) - k):
        if H[i] > H[i - k:i].max() and H[i] >= H[i + 1:i + k + 1].max():
            ph.append(i)
        if L[i] < L[i - k:i].min() and L[i] <= L[i + 1:i + k + 1].min():
            pl.append(i)
    return ph, pl


def direction(ph, pl, H, L, last_closed):
    """last_closed：已收市最後一根 index；確認點要 i + K <= last_closed。回傳 1／-1／0。"""
    nh = bisect.bisect_right(ph, last_closed - K); nl = bisect.bisect_right(pl, last_closed - K)
    if nh < 2 or nl < 2:
        return 0
    h1, h2 = H[ph[nh - 2]], H[ph[nh - 1]]; l1, l2 = L[pl[nl - 2]], L[pl[nl - 1]]
    if h2 > h1 and l2 > l1:
        return 1
    if h2 < h1 and l2 < l1:
        return -1
    return 0


def atr(H, L, C, n=14):
    tr = np.maximum(H[1:], C[:-1]) - np.minimum(L[1:], C[:-1])
    out = np.full(len(H), np.nan)
    for j in range(n, len(H)):
        out[j] = tr[j - n:j].mean()
    return out


def run(variant, O, H, L, C, T4, d_of_h4, DH, DL, dph, dpl, hph, hpl, A4, rng=None, entries=None):
    """variant：'S1'（D1 方向）／'S2'（H4 方向）／'S0'（S1 入場、方向隨機）。回傳 [(入場時間, R, side, entry, risk)]。"""
    n = len(O)
    out, pos, used = [], None, set()
    if variant == "S0":
        for (t, side, e, risk, ei) in entries:
            s = rng.choice((1, -1))
            sl = e - s * risk; tp = e + s * 2 * risk; ex = None
            for k2 in range(ei, min(n, ei + HOLD + 1)):
                if k2 - ei >= HOLD:
                    ex = O[k2]; break
                if (L[k2] <= sl) if s > 0 else (H[k2] >= sl):
                    ex = sl; break
                if (H[k2] >= tp) if s > 0 else (L[k2] <= tp):
                    ex = tp; break
            if ex is not None:
                out.append((t, (s * (ex - e) - COST) / risk, s, e, risk))
        return out
    for j in range(K + 2, n - 1):
        dirf = (lambda last: direction(dph, dpl, DH, DL, last)) if variant == "S1" else (lambda last: direction(hph, hpl, H, L, last))
        dlast = (d_of_h4[j] - 1) if variant == "S1" else j            # D1：只用 H4 收市前已收市嘅日線
        if pos is not None:
            s, e, sl, tp, ei, risk = pos
            ex = None
            if j - ei >= HOLD:
                ex = O[j]
            elif (L[j] <= sl) if s > 0 else (H[j] >= sl):
                ex = sl
            elif (H[j] >= tp) if s > 0 else (L[j] <= tp):
                ex = tp
            elif dirf(dlast) != s:                                    # 方向冇咗：下一根開市走
                ex = O[j + 1]
            if ex is not None:
                out.append((T4[ei], (s * (ex - e) - COST) / risk, s, e, risk, ei)); pos = None
            continue
        d = dirf(dlast)
        if d == 0 or np.isnan(A4[j]):
            continue
        nh = bisect.bisect_right(hph, j - K); nl = bisect.bisect_right(hpl, j - K)
        if nh < 1 or nl < 2:
            continue
        if d > 0:
            hl, prev = hpl[nl - 1], hpl[nl - 2]; sh = hph[nh - 1]
            if not (L[hl] > L[prev] and hl > sh and C[j] > H[sh] and C[j - 1] <= H[sh]) or ("L", hl) in used:
                continue
            used.add(("L", hl)); e = O[j + 1]; sl = L[hl] - 0.25 * A4[j]
        else:
            lh, prev = hph[nh - 1], hph[nh - 2] if nh >= 2 else None; sl_i = hpl[nl - 1]
            if prev is None or not (H[lh] < H[prev] and lh > sl_i and C[j] < L[sl_i] and C[j - 1] >= L[sl_i]) or ("H", lh) in used:
                continue
            used.add(("H", lh)); e = O[j + 1]; sl = H[lh] + 0.25 * A4[j]
        risk = (e - sl) * d
        if risk <= 0:
            continue
        pos = (d, e, sl, e + d * 2 * risk, j + 1, risk)
    return out


def main():
    t, o, h, l, c = S.G7.load_h1_duka()
    st = [S.server_dt(x) for x in t]
    O, H, L, C, T4, h4_of_h1 = agg(st, o, h, l, c, "H4")
    DO, DH, DL, DC, TD, d_of_h1 = agg(st, o, h, l, c, "D")
    first_h1 = np.searchsorted(h4_of_h1, np.arange(len(O)))          # 每根 H4 第一根 H1
    d_of_h4 = d_of_h1[first_h1]
    dph, dpl = pivots(DH, DL); hph, hpl = pivots(H, L)
    A4 = atr(H, L, C)
    end = dt.datetime(2026, 11, 1)
    res = {}
    for v in ("S1", "S2"):
        tr = [x for x in run(v, O, H, L, C, T4, d_of_h4, DH, DL, dph, dpl, hph, hpl, A4) if S.SEGS[0][1] <= x[0] < end]
        res[v] = tr
        print(v, S.fmt(S.summ([x[1] for x in tr])), flush=True)
    ent = [(x[0], x[2], x[3], x[4], x[5]) for x in res["S1"]]
    rs_all, rs_seg = [], []
    for seed in range(N_RAND):
        tr = run("S0", O, H, L, C, T4, d_of_h4, DH, DL, dph, dpl, hph, hpl, A4, rng=random.Random(seed), entries=ent)
        rs_all.append(S.summ([x[1] for x in tr])); rs_seg.append(S.segs([(x[0], x[1]) for x in tr]))
    ravg = float(np.mean([s["avg"] for s in rs_all]))
    names = {"S1": "S1 D1 方向＋H4 入場（主判）", "S2": "S2 只用 H4 結構"}
    out = ["# 市場結構 HH／HL（IDEAS #1000）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Dukascopy H1 {len(t)} 根 → H4 {len(O)} 根、D1 {len(DO)} 根；MT5 伺服器時間；規格見 IDEAS #1000", "",
           "| 組 | 全期 | " + " | ".join(s[0] for s in S.SEGS) + " | 做多 | 做空 |", "|---|---|---|---|---|---|---|"]
    for v in ("S1", "S2"):
        tr = res[v]; sg = S.segs([(x[0], x[1]) for x in tr])
        out.append(f"| {names[v]} | {S.fmt(S.summ([x[1] for x in tr]))} | " + " | ".join(S.fmt(x) for x in sg)
                   + f" | {S.fmt(S.summ([x[1] for x in tr if x[2] > 0]))} | {S.fmt(S.summ([x[1] for x in tr if x[2] < 0]))} |")
    segm = [float(np.mean([x[k]["avg"] for x in rs_seg])) for k in range(3)]
    out.append(f"| S0 隨機方向（S1 同入場，{N_RAND} 種子） | 平均 {ravg:+.3f}R | " + " | ".join(f"平均 {x:+.3f}R" for x in segm) + " | — | — |")
    m = S.summ([x[1] for x in res["S1"]]); sg = S.segs([(x[0], x[1]) for x in res["S1"]])
    ok = {"①最後一段≥30張": sg[2]["n"] >= 30, "②最後一段平均R≥+0.15": sg[2]["avg"] >= 0.15, "③最後一段PF≥1.3": sg[2]["pf"] >= 1.3,
          "④三段平均R都>0": all(x["n"] > 0 and x["avg"] > 0 for x in sg), "⑤全期高過隨機≥0.10R": m["avg"] - ravg >= 0.10}
    out += ["", "## 判（預先登記 IDEAS #1000；主判 S1）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            "- " + ("✅ 合格 → 影子前向 30 張先可以提實倉" if all(ok.values())
                    else "❌ 唔合格：" + "、".join(k for k, v in ok.items() if not v) + "；唔做、唔准改參數再試同一批數據；S2 只作描述"), ""]
    open(os.path.join(HERE, "STRUCTURE_HHHL.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
