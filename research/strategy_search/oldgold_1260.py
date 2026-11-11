"""[IDEAS #1260] 方法 E：黃金自己嘅舊歷史樣本外考試（使用者 11-11「繼續做研究搵到三個合格先停，唔好用返之前嘅方法，避免撞彩」＋「點解跨品種都要合格？」）。
規格以 IDEAS #1260 預先登記為準（跑之前 commit；冇網格、冇調參）。
數據：stooq 日線 OHLC（使用者 11-11 上載，research/macro_data/stooq_*.csv）。黃金 1975-01→2004-12（30 年，包 1980–2000 熊市）係主判；白銀 1970-01→2004-12 係副判。
呢兩段從未用嚟揀任何規則（之前黃金由 2005 起、白銀由 2010 起）。規則＝7 本真倉用嘅 8 條，訊號邏輯原封不動（直接叫返原本函數）。
只有日線 → 成交用日線模擬：下一日開市入；當日開市已經穿止蝕 → 用開市價出（跳空蝕多啲）；當日低／高掂止蝕 → 止蝕價出；規則出場用當日收市。
成本＝入場價嘅 0.05%（黃金；即 4,000 美元時 2 美元）／0.12%（白銀），按價格比例（舊年代金價細，用固定美元唔合理）；最低止蝕 0.3×前一日 ATR14。
用法：python3 research/strategy_search/oldgold_1260.py → research/strategy_search/OLDGOLD_1260.md"""
import csv
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import h1_lab3 as L3            # noqa: E402
import h1_lab6 as H6            # noqa: E402
import h1_lab7 as H7            # noqa: E402
import h1_lab8 as H8            # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as MS3  # noqa: E402
import momo_strict_1171 as MS4  # noqa: E402
import momo_strict_1178 as MS5  # noqa: E402
import strict_b_1220 as SB      # noqa: E402

OUT = os.path.join(HERE, "OLDGOLD_1260.md")
MD = os.path.join(HERE, "..", "macro_data")
RATE = {"gold": 0.0005, "silver": 0.0012}
T_MIN, PF_MIN, N_MIN = 2.5, 1.15, 60          # Bonferroni：8 條、單邊 5% → z 2.50
_rate = [0.0005]


def ts(s):
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())


def load(name, start):
    t, o, h, l, c = [], [], [], [], []
    with open(os.path.join(MD, f"stooq_{name}_d.csv")) as fh:
        r = csv.reader(fh); next(r)
        for row in r:
            if row[0] < start or row[0] > "2004-12-31":
                continue
            t.append(ts(row[0])); o.append(float(row[1])); h.append(float(row[2])); l.append(float(row[3])); c.append(float(row[4]))
    return {"t": np.array(t, np.int64), "o": np.array(o), "h": np.array(h), "l": np.array(l), "c": np.array(c)}


def trade_d1(cx, i, sg, risk, tp_r, mb, ex=None):
    """同 momo_strict_1157.trade_m1 一樣嘅介面，但用日線判出場（跳空穿止蝕用開市價）、成本按入場價比例。"""
    b = cx.b; e = i + 1
    if e >= len(b["c"]):
        return None
    fl = cx.floor(b["t"][i])
    if fl is None:
        return None
    risk = max(risk, fl); en = b["o"][e]; sl = en - sg * risk; tp = None if tp_r is None else en + sg * tp_r * risk; cost = _rate[0] * en
    last = min(len(b["c"]) - 1, e + mb - 1)
    for k in range(e, last + 1):
        o, hh, ll = b["o"][k], b["h"][k], b["l"][k]
        if k > e and ((o <= sl) if sg > 0 else (o >= sl)):
            return int(b["t"][e]), sg, (sg * (o - en) - cost) / risk, k
        if (ll <= sl) if sg > 0 else (hh >= sl):
            return int(b["t"][e]), sg, (sg * (sl - en) - cost) / risk, k
        if tp is not None and ((hh >= tp) if sg > 0 else (ll <= tp)):
            return int(b["t"][e]), sg, (sg * (tp - en) - cost) / risk, k
        if ex is not None and ex(k, sg):
            return int(b["t"][e]), sg, (sg * (b["c"][k] - en) - cost) / risk, k
    return int(b["t"][e]), sg, (sg * (b["c"][last] - en) - cost) / risk, last


def trade_break_d1(g, s, e, hi, lo, sl_fn, tp_mult, allow):
    """同 h1_lab3.trade_break 一樣，但成本按比例、風險下限按比例、跳空穿止蝕用開市價。"""
    o, h, l, c, t = g["o"], g["h"], g["l"], g["c"], g["t"]
    for j in range(s, e):
        if not allow(j):
            continue
        up, dn = h[j] >= hi, l[j] <= lo
        if not (up or dn):
            continue
        sg = 1 if up else -1                                   # 同一日兩邊都掂：照原本保守當做多再止蝕
        en = max(hi, o[j]) if sg > 0 else min(lo, o[j]); sl = sl_fn(sg); risk = (en - sl) * sg; cost = _rate[0] * en
        if risk <= 0.000125 * en:                              # 原本「≤ 0.5 美元」＝ 4,000 美元時 0.0125%
            return None
        if (l[j] <= sl) if sg > 0 else (h[j] >= sl):
            return (int(t[j]), sg, (sg * (sl - en) - cost) / risk)
        tp = None if tp_mult is None else en + sg * tp_mult * risk; ex = None
        for k in range(j + 1, e):
            if (o[k] <= sl) if sg > 0 else (o[k] >= sl):
                ex = o[k]; break
            if (l[k] <= sl) if sg > 0 else (h[k] >= sl):
                ex = sl; break
            if tp is not None and ((h[k] >= tp) if sg > 0 else (l[k] <= tp)):
                ex = tp; break
        if ex is None:
            ex = c[e - 1]
        return (int(t[j]), sg, (sg * (ex - en) - cost) / risk)
    return None


def r1116(g):
    """h1_lab8.r1116（海龜 2）原樣，只係成本按比例、跳空穿止蝕用開市價。"""
    d = g; c = d["c"]; a = B.atr(d, 20); out, i = [], 56
    while i < len(c) - 1:
        if np.isnan(a[i]) or a[i] <= 0:
            i += 1; continue
        sg = 1 if c[i] > c[i - 55:i].max() else (-1 if c[i] < c[i - 55:i].min() else 0)
        if not sg:
            i += 1; continue
        ei = i + 1; en = d["o"][ei]; risk = 2 * a[i]; sl = en - sg * risk; ex = None; j = ei
        while j < min(len(c), ei + 120):
            if j > ei and ((d["o"][j] <= sl) if sg > 0 else (d["o"][j] >= sl)):
                ex = d["o"][j]; break
            if (d["l"][j] <= sl) if sg > 0 else (d["h"][j] >= sl):
                ex = sl; break
            if j >= 20 and ((c[j] < c[j - 20:j].min()) if sg > 0 else (c[j] > c[j - 20:j].max())):
                ex = c[j]; break
            j += 1
        if ex is None:
            j = min(len(c), ei + 120) - 1; ex = c[j]
        out.append((int(d["t"][ei]), sg, (sg * (ex - en) - _rate[0] * en) / risk)); i = j + 1
    return out


def tup(fn):
    def run(d):
        out = fn(d); out = out if isinstance(out, list) else out[0]
        return [(int(a), int(b), float(c)) for a, b, c in out]
    return run


RULES = [("#1107", "上季高低突破（926）", tup(H6.r1107)), ("#1113", "低波幅 20 日突破（926）", tup(H7.r1113)),
         ("#1114", "月初三日區間突破（933）", tup(H8.r1114)), ("#1116", "海龜 2（941）", tup(r1116)),
         ("#1165", "D1 急動＋SMA50（937）", tup(MS3.r1165)), ("#1174", "D1 寬幅日（938）", tup(MS4.r1174)),
         ("#1178", "D1 Keltner（939）", tup(MS5.r1178)), ("#1224", "一目穿雲（940）", tup(lambda d: SB.flips(d, SB.st_ichimoku)))]


def patch(kind):
    saved = (M.trade_m1, M.Ctx.floor, L3.trade_break)
    _rate[0] = RATE[kind]
    M.trade_m1 = trade_d1; L3.trade_break = trade_break_d1
    M.Ctx.floor = lambda self, t_: (None if self.atr_d.get(int(t_) // 86400) is None else 0.3 * self.atr_d[int(t_) // 86400])
    return lambda: (setattr(M, "trade_m1", saved[0]), setattr(M.Ctx, "floor", saved[1]), setattr(L3, "trade_break", saved[2]))


def year(t_):
    return dt.datetime.fromtimestamp(int(t_), dt.timezone.utc).year


def stats(tr):
    r = np.array([x[2] for x in tr], float)
    if not len(r):
        return 0, 0.0, 0.0
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    return len(r), float(r.mean()), float(w / ls) if ls else 99.0


def yearly(tr, y0, y1):
    tot = np.zeros(y1 - y0 + 1)
    for t_, _, r in tr:
        tot[year(t_) - y0] += r
    return tot


def tstat(x):
    s = x.std(ddof=1)
    return float(x.mean() / (s / np.sqrt(len(x)))) if len(x) > 2 and s > 0 else 0.0


def run_all(kind, name, start, y0):
    d = load(name, start); restore = patch(kind)
    try:
        return {k: [x for x in fn(d) if year(x[0]) >= y0] for k, _, fn in RULES}, d
    finally:
        restore()


def table(res, y0, split, L, rules=RULES, t_min=T_MIN, silver=None):
    L += ["| IDEAS | 規則 | 張數 | 每張平均 R | PF | (a) 每年 ΣR 平均／t | (b) 前半／後半 每張 | 多／空 每張 | (d) 白銀 | 判 |", "|---|---|---|---|---|---|---|---|---|---|"]
    passed = []; mk = lambda v: "✅" if v else "❌"  # noqa: E731
    for key, nm, _ in rules:
        tr = res[key]; n, avg, pf = stats(tr); yr = yearly(tr, y0, 2004); t_ = tstat(yr)
        a1 = stats([x for x in tr if year(x[0]) < split])[1]; a2 = stats([x for x in tr if year(x[0]) >= split])[1]
        lo = stats([x for x in tr if x[1] > 0])[1]; sh = stats([x for x in tr if x[1] < 0])[1]
        a = yr.mean() > 0 and t_ >= t_min; b = a1 > 0 and a2 > 0; c = pf >= PF_MIN and n >= N_MIN
        if silver is not None:
            sn, sa, sp = stats(silver[key]); dd = sa > 0; stxt = f"{sn} 張 {sa:+.3f}R PF {sp:.2f} {mk(dd)}"
        else:
            dd, stxt = True, "—"
        ok = a and b and c and dd
        L.append(f"| {key} | {nm} | {n} | {avg:+.3f} | {pf:.2f} {mk(c)} | {yr.mean():+.2f}／{t_:.2f} {mk(a)} | {a1:+.3f}／{a2:+.3f} {mk(b)} | {lo:+.3f}／{sh:+.3f} | {stxt} | {'✅ 合格' if ok else '❌'} |")
        if ok:
            passed.append(key)
    return passed


def main():
    gold, dg = run_all("gold", "xauusd", "1973-01-01", 1975)
    silver, ds = run_all("silver", "xagusd", "1968-01-01", 1970)
    L = ["# 方法 E：黃金舊歷史樣本外考試（IDEAS #1260）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；stooq 日線；黃金 1975–2004（{int((dg['t'] >= ts('1975-01-01')).sum())} 根，主判）、白銀 1970–2004（副判）；兩段都從未用嚟揀規則",
         "- 8 條真倉規則訊號原封不動；日線成交模擬（跳空穿止蝕用開市價）；成本＝入場價 0.05%（黃金）／0.12%（白銀）；最低止蝕 0.3×ATR",
         f"- 合格（四樣全過）：(a) 黃金每年 ΣR 平均 > 0 而且 t ≥ {T_MIN}（8 條規則嘅 Bonferroni 校正）；(b) 1975–89 同 1990–2004 兩半每張平均都 > 0；(c) PF ≥ {PF_MIN} 而且 ≥ {N_MIN} 張；(d) 白銀 1970–2004 每張平均 > 0", ""]
    passed = table(gold, 1975, 1990, L, silver=silver)
    comb = np.sum([yearly(gold[k], 1975, 2004) for k, _, _ in RULES], axis=0)
    L += ["", f"- **合格：{'、'.join(passed) if passed else '冇'}**（8 條入面）",
          f"- 8 條等權組合（黃金 1975–2004）：每年 {comb.mean():+.2f}R，t {tstat(comb):.2f}，正數年 {int((comb > 0).sum())}／30（描述，唔入判決）",
          "- 每 5 年 8 條合計 ΣR：" + "、".join(f"{y}–{y + 4} {comb[y - 1975:y - 1970].sum():+.1f}" for y in range(1975, 2005, 5)), ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
