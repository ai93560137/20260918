"""[IDEAS #1251] 方法 D：跨品種樣本外考試（使用者 11-10「繼續做研究搵到三個合格先停，唔好用返之前嘅方法，避免撞彩」）。
規格以 IDEAS #1251 預先登記為準（跑之前 commit；冇網格、冇調參）。
之前所有方法都係喺黃金歷史度揀規則 → 揀得多自然有幾條「過關」。今次將已經揀好嘅 10 條規則（7 本真倉＋2 條影子用到嘅全部規則）
原封不動搬去 14 個**從未用嚟揀規則**嘅品種（券商 MT5 M1，2022-08→2026-11，GCS xau/sig/cache/mt5x/）。
成本：每品種固定＝0.02×（D1 ATR14 中位數）〔M1 嚴格版〕／0.04×〔趨勢 H1 sim〕；最低止蝕 0.3×前一日 ATR14（冇美元下限）。
用法：python3 research/strategy_search/panel_1251.py → research/strategy_search/PANEL_1251.md"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1019 as B          # noqa: E402
import data_cache as DC         # noqa: E402
import h1_lab6 as H6            # noqa: E402
import h1_lab7 as H7            # noqa: E402
import h1_lab8 as H8            # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as MS3  # noqa: E402
import momo_strict_1171 as MS4  # noqa: E402
import momo_strict_1178 as MS5  # noqa: E402
import strict_b_1220 as SB      # noqa: E402
import strict_b_1228 as SB2     # noqa: E402

OUT = os.path.join(HERE, "PANEL_1251.md")
FX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY"]
PANEL = FX + ["NAS100", "GER40", "UK100", "CL-OIL", "BTCUSD"]
REF = ["XAUUSD", "XAGUSD"]                      # 只做參考，唔入判決（黃金用嚟揀過規則）
T0 = int(dt.datetime(2022, 8, 1, tzinfo=dt.timezone.utc).timestamp())
M0, M1_ = (2022, 9), (2026, 10)                 # 完整月份 2022-09 → 2026-10（50 個月）
T_MIN, POS_MIN, N_MIN = 2.58, 9, 100            # Bonferroni：10 條、單邊 5% → z 2.58


def load(sym):
    parts = [DC.get(f"mt5x/{sym}_m1_{y}{'p' if y == 2026 else ''}.npz") for y in range(2022, 2027)]
    return DC.merge(parts, t0=T0)


def trend(fn):
    def run(d):
        out = fn(B.resample(d, 3600)); out = out if isinstance(out, list) else out[0]
        return [(int(a), int(b), float(c)) for a, b, c in out]
    return run


def m1(fn):
    return lambda d: [(int(a), int(b), float(c)) for a, b, c in fn(d)]


RULES = [("#1107", "上季高低突破（926）", trend(H6.r1107)), ("#1113", "低波幅 20 日突破（926）", trend(H7.r1113)),
         ("#1114", "月初三日區間突破（933）", trend(H8.r1114)), ("#1116", "海龜 2（941）", trend(H8.r1116)),
         ("#1165", "D1 急動＋SMA50（937）", m1(MS3.r1165)), ("#1174", "D1 寬幅日（938）", m1(MS4.r1174)),
         ("#1178", "D1 Keltner（939）", m1(MS5.r1178)), ("#1224", "一目穿雲（940）", m1(lambda d: SB.flips(d, SB.st_ichimoku))),
         ("#1232", "H4 SAR＋D1 SMA100（影子）", m1(SB2.RULES[4][2])), ("#1234", "H1 100 根突破＋D1 SMA50（影子）", m1(SB2.RULES[6][2]))]


def inst_mode(d):
    """按品種設成本同最低止蝕；回傳還原函數。"""
    a = B.atr(B.resample(d, 86400)); med = float(np.nanmedian(a))
    saved = (M.COST, M.Ctx.floor)
    M.COST = 0.02 * med
    M.Ctx.floor = lambda self, ts: (None if self.atr_d.get(int(ts) // 86400) is None else 0.3 * self.atr_d[int(ts) // 86400])
    SB.set_trend_cost(0.04 * med)

    def restore():
        M.COST, M.Ctx.floor = saved
        SB.set_trend_cost(0.5)
    return med, restore


def mkey(ts):
    x = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    return x.year * 12 + x.month - 1


K0, K1 = M0[0] * 12 + M0[1] - 1, M1_[0] * 12 + M1_[1] - 1


def monthly(trs):
    tot = np.zeros(K1 - K0 + 1)
    for tr in trs:
        for ts, _, r in tr:
            k = mkey(ts)
            if K0 <= k <= K1:
                tot[k - K0] += r
    return tot


def tstat(x):
    x = np.asarray(x, float); s = x.std(ddof=1)
    return float(x.mean() / (s / np.sqrt(len(x)))) if len(x) > 2 and s > 0 else 0.0


def inwin(tr):
    return [x for x in tr if K0 <= mkey(x[0]) <= K1]


def main():
    res = {k: {} for k, _, _ in RULES}; meds = {}
    for sym in PANEL + REF:
        d = load(sym); med, restore = inst_mode(d); meds[sym] = med
        try:
            for key, _, fn in RULES:
                res[key][sym] = inwin(fn(d))
        finally:
            restore()
        print(sym, len(d["t"]), f"ATR 中位 {med:.5g}", {k: len(res[k][sym]) for k in res}, flush=True)
    L = ["# 方法 D：跨品種樣本外考試（IDEAS #1251）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；14 個從未用嚟揀規則嘅品種（外匯 9、指數 3、原油、BTC），券商 MT5 M1，入場月 2022-09→2026-10（50 個月）",
         "- 規則同參數原封不動；成本每張 0.02×ATR 中位（M1 嚴格版）／0.04×（趨勢 sim）；最低止蝕 0.3×ATR",
         f"- 合格（五樣全過）：(a) 14 品種合計每月 R 平均 > 0 而且 t ≥ {T_MIN}（10 條規則嘅 Bonferroni 校正）；(b) ≥ {POS_MIN}／14 品種每張平均 > 0；"
         f"(c) 剔走 ΣR 最高嗰個品種之後每月平均 > 0 而且 t ≥ 2.0；(d) 外匯 9 隻合計每月平均 > 0；(e) 合計 ≥ {N_MIN} 張", "",
         "| IDEAS | 規則 | 張數 | 每張平均 R | (a) 每月平均／t | (b) 正品種 | (c) 剔最好品種 平均／t | (d) 外匯每月 | 多／空 每張 | 判 |", "|---|---|---|---|---|---|---|---|---|---|"]
    passed = []; detail = ["", "## 各品種每張平均 R（張數）", "", "| 規則 | " + " | ".join(PANEL + [f"{s}（參考）" for s in REF]) + " |", "|---|" + "---|" * (len(PANEL) + len(REF))]
    for key, name, _ in RULES:
        per = res[key]; allr = np.array([x[2] for s in PANEL for x in per[s]]); n = len(allr)
        sg = np.array([x[1] for s in PANEL for x in per[s]])
        mon = monthly([per[s] for s in PANEL]); t_all = tstat(mon)
        pos = sum(1 for s in PANEL if per[s] and np.mean([x[2] for x in per[s]]) > 0)
        best = max(PANEL, key=lambda s: sum(x[2] for x in per[s]))
        loo = monthly([per[s] for s in PANEL if s != best]); fx = monthly([per[s] for s in FX])
        a = mon.mean() > 0 and t_all >= T_MIN; b = pos >= POS_MIN; c = loo.mean() > 0 and tstat(loo) >= 2.0; dd = fx.mean() > 0; e = n >= N_MIN
        ok = a and b and c and dd and e
        lo = allr[sg > 0].mean() if (sg > 0).any() else 0.0; sh = allr[sg < 0].mean() if (sg < 0).any() else 0.0
        mk = lambda v: "✅" if v else "❌"  # noqa: E731
        L.append(f"| {key} | {name} | {n} {mk(e)} | {allr.mean() if n else 0:+.3f} | {mon.mean():+.2f}／{t_all:.2f} {mk(a)} | {pos}／14 {mk(b)} | "
                 f"{loo.mean():+.2f}／{tstat(loo):.2f}（剔 {best}）{mk(c)} | {fx.mean():+.2f}（t {tstat(fx):.2f}）{mk(dd)} | {lo:+.3f}／{sh:+.3f} | {'✅ 合格' if ok else '❌'} |")
        detail.append(f"| {key} | " + " | ".join((f"{np.mean([x[2] for x in per[s]]):+.2f}（{len(per[s])}）" if per[s] else "—") for s in PANEL + REF) + " |")
        if ok:
            passed.append(key)
    allmon = monthly([res[k][s] for k, _, _ in RULES for s in PANEL])
    L += ["", f"- **合格：{'、'.join(passed) if passed else '冇'}**（10 條入面）",
          f"- 10 條規則 × 14 品種等權組合：每月 {allmon.mean():+.2f}R，t {tstat(allmon):.2f}，正數月 {np.mean(allmon > 0):.0%}（描述，唔入判決）"]
    L += detail + [""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
