"""[IDEAS #1261–#1266] 方法 E 第二階段：6 條新日線假設，先喺舊黃金 1975–2004 測（每年 t ≥ 3.0），過咗先用 2005–2026 黃金 M1 嚴格版一次過確認。
規格以 IDEAS 預先登記為準（跑之前 commit；冇網格、冇調參；參數全部教科書預設）。
#1260 見到單條規則一年十幾張、每年 t 好難過 2.5 → 今批有 3 條係「多個週期等權合成」（每個子規則各自一次一張，R 除以子規則數目），目的係靠分散降低年度波動，唔係揀參數。
成交模擬、成本同 #1260 一樣（oldgold_1260）。
用法：python3 research/strategy_search/oldgold2_1261.py → research/strategy_search/OLDGOLD2_1261.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import batch_1019 as B          # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import gate_c_1240 as GC        # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402
import oldgold_1260 as OG       # noqa: E402
import panel2_1252 as PN2       # noqa: E402
import tsmom_1213 as TS         # noqa: E402

OUT = os.path.join(HERE, "OLDGOLD2_1261.md")
T_MIN = 3.0
MB = 250


def state_rule(d, state, k_sl=3.0):
    """state[i]＝+1／−1／0；轉做非零嗰日收市後入，state 唔再同向就平；SL k×ATR14；最多 250 日。"""
    cx = M3.d1ctx(d)
    return GC.edge_sigs(cx, state, k_sl, MB, lambda k, sg: state[k] != sg)


def ensemble(d, makers):
    out = []
    for mk in makers:
        out += [(t, sg, r / len(makers)) for t, sg, r in state_rule(d, mk(M3.d1ctx(d).b))]
    return sorted(out)


def donch(n):
    def mk(b):
        c = b["c"]; s = np.zeros(len(c)); cur = 0; m = n // 2
        for i in range(n, len(c)):
            if cur == 0:
                cur = 1 if c[i] > c[i - n:i].max() else (-1 if c[i] < c[i - n:i].min() else 0)
            elif cur > 0 and c[i] < c[i - m:i].min():
                cur = -1 if c[i] < c[i - n:i].min() else 0
            elif cur < 0 and c[i] > c[i - m:i].max():
                cur = 1 if c[i] > c[i - n:i].max() else 0
            s[i] = cur
        return s
    return mk


def mom(n):
    def mk(b):
        c = b["c"]; s = np.zeros(len(c)); s[n:] = np.sign(c[n:] - c[:-n])
        return s
    return mk


def cross(f, sl):
    def mk(b):
        c = b["c"]; a, bb = F2.sma(c, f), F2.sma(c, sl); s = np.sign(a - bb); s[np.isnan(s)] = 0
        return s
    return mk


def r1261(d):
    """唐奇安合成：收市破 20／55／100／200 日高低入，反向破一半日數嘅高低平；四個週期等權。"""
    return ensemble(d, [donch(20), donch(55), donch(100), donch(200)])


def r1262(d):
    """時間序列動量合成：21／63／126／252 日回報方向，方向變就平；四個週期等權。"""
    return ensemble(d, [mom(21), mom(63), mom(126), mom(252)])


def r1263(d):
    """均線交叉合成：SMA 10／50、20／100、50／200 交叉方向；三組等權。"""
    return ensemble(d, [cross(10, 50), cross(20, 100), cross(50, 200)])


def r1264(d):
    """12 個月動量（每月換倉）：每月最後一個交易日，收市高過 252 日前就買、低過就沽；持到下個月最後一個交易日收市；SL 3×ATR14。"""
    cx = M3.d1ctx(d); b = cx.b; c = b["c"]; a = B.atr(b); n = len(c)
    mk = np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).month for x in b["t"]])
    last = np.r_[mk[1:] != mk[:-1], False]; sigs = []
    for i in range(252, n - 1):
        if last[i] and not np.isnan(a[i]) and c[i] != c[i - 252]:
            sigs.append((i, 1 if c[i] > c[i - 252] else -1, 3 * a[i], None, 25, lambda k, sg: bool(last[k])))
    return M.run_m1(cx, sigs)


def r1265(d):
    """RSI(2) 順勢回調（同 #1252 一模一樣）。"""
    return PN2.r1252(d)


def r1266(d):
    """週線 4／2 突破：週尾收市高過之前 4 個週尾收市 → 買，跌穿之前 2 個週尾收市最低 → 平（反之沽）；SL 3×ATR14。"""
    cx = M3.d1ctx(d); b = cx.b; c = b["c"]; n = len(c); wk = np.array([TS.wkey(x) for x in b["t"]])
    ends = [j for j in range(n) if j + 1 == n or wk[j + 1] != wk[j]]; wc = c[ends]; s = np.zeros(n); cur = 0; prev = 0
    for k, j in enumerate(ends):
        if k >= 4:
            if cur == 0:
                cur = 1 if wc[k] > wc[k - 4:k].max() else (-1 if wc[k] < wc[k - 4:k].min() else 0)
            elif cur > 0 and wc[k] < wc[k - 2:k].min():
                cur = -1 if wc[k] < wc[k - 4:k].min() else 0
            elif cur < 0 and wc[k] > wc[k - 2:k].max():
                cur = 1 if wc[k] > wc[k - 4:k].max() else 0
        s[prev:j] = s[prev - 1] if prev else 0; s[j] = cur; prev = j + 1
    return GC.edge_sigs(cx, s, 3.0, MB, lambda k, sg: s[k] != sg)


RULES = [("#1261", "唐奇安合成（20／55／100／200）", r1261), ("#1262", "時間序列動量合成（21／63／126／252）", r1262), ("#1263", "均線交叉合成", r1263),
         ("#1264", "12 個月動量（每月換倉）", r1264), ("#1265", "RSI(2) 順勢回調", r1265), ("#1266", "週線 4／2 突破", r1266)]


def run_all(kind, name, start, y0):
    d = OG.load(name, start); restore = OG.patch(kind)
    try:
        return {k: [(int(a), int(b), float(c)) for a, b, c in fn(d) if OG.year(a) >= y0] for k, _, fn in RULES}
    finally:
        restore()


def confirm(fn):
    cells, ok, allr = [], True, []
    for src, a, b_ in (("duka", "2015-01-01", "2022-12-31"), ("mt5", "2023-01-01", "2026-10-30"), ("duka", "2010-01-01", "2014-12-31")):
        tr = fn(A.load(src, a, b_)); r = np.array([x[2] for x in tr]); ok = ok and len(r) >= 5 and r.mean() > 0; allr += list(r)
        cells.append(f"{len(r)} 筆 {r.mean() if len(r) else 0:+.3f}R")
    r = np.array(allr); pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum()); ok = ok and pf >= 1.15
    return " ｜ ".join(cells) + f" ｜ 合併 PF {pf:.2f}", ok


def main():
    gold = run_all("gold", "xauusd", "1973-01-01", 1975); silver = run_all("silver", "xagusd", "1968-01-01", 1970)
    L = ["# 方法 E 第二階段：舊黃金揀、新黃金確認（IDEAS #1261–#1266）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；第一關＝stooq 日線黃金 1975–2004（成交模擬、成本同 #1260）；白銀 1970–2004 副判",
         f"- 第一關（四樣全過）：(a) 每年 ΣR 平均 > 0 而且 t ≥ {T_MIN}；(b) 1975–89、1990–2004 兩半每張平均都 > 0；(c) PF ≥ 1.15 而且 ≥ 60 張；(d) 白銀每張平均 > 0",
         "- 第二關（只有過第一關先跑，一次過）：2005 年後黃金 M1 嚴格版三段（Duka 2015–22、MT5 2023–26、Duka 2010–14）每段平均 > 0、合併 PF ≥ 1.15", ""]
    stage1 = OG.table(gold, 1975, 1990, L, rules=RULES, t_min=T_MIN, silver=silver)
    L += ["", f"- 第一關過：{'、'.join(stage1) if stage1 else '冇'}", ""]
    passed = []
    if stage1:
        L += ["## 第二關：2010–2026 黃金 M1 嚴格版（一次過）", "", "| IDEAS | ① Duka 2015–22 ｜ ② MT5 2023–26 ｜ ③ Duka 2010–14 ｜ 合併 | 判 |", "|---|---|---|"]
        fns = {k: f for k, _, f in RULES}
        for key in stage1:
            txt, ok = confirm(fns[key]); L.append(f"| {key} | {txt} | {'✅ 合格' if ok else '❌'} |")
            if ok:
                passed.append(key)
    L += ["", f"- **兩關都過（合格）：{'、'.join(passed) if passed else '冇'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
