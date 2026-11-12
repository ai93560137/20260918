"""[11-12 使用者「利用複式策略」] 趨勢簿複利手數模擬：① 固定 0.01；② 棘輪（使用者版本：手數跟權益最高水位，贏加注、輸唔減）；③ 對稱（跟而家權益，跌會減）。手數＝floor(本 ÷ unit) × 0.01（最少 0.01、上限 cap），只喺新開倉時計。
unit＝該戶口全部趨勢簿 0.01 手時嘅歷史最大回落 × 1.5。數據：2010–2026 M1 嚴格版回測（shadow_board 嘅規則函數）；每 R 折港幣用而家 ATR（固定），
即係「將來每張嘅 R 分佈同過去一樣、波幅同而家一樣」嘅假設。成交次序用入場時間、損益即時入賬（近似）。只讀研究。
用法：python3 research/strategy_search/compound_sim.py --start63 <HKD> --start69 <HKD> [--cap 0.05]（本金只喺命令列，唔寫入檔案；輸出 COMPOUND_SIM.md 只有倍數同百分比）"""
import datetime as dt
import os
import sys

import numpy as np

ARGV = list(sys.argv); sys.argv = [sys.argv[0]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intraday_1323 as I   # noqa: E402
import shadow_board as SB   # noqa: E402

HK = 7.8
ACCTS = {"…63": ["fr1300"], "…69": ["mobrk", "mom1165", "mom1178", "fr1285", "td1268"]}
K_ATR = {"fr1300": 3.0, "td1268": 3.0, "fr1285": 3.0, "mom1165": 2.0, "mom1178": 2.0, "mobrk": 1.5}   # 每 R＝幾多倍 D1 ATR（mobrk 係假設）


def arg(name, default=None):
    return float(ARGV[ARGV.index(name) + 1]) if name in ARGV else default


def ddpct(eq):
    eq = np.asarray(eq); pk = np.maximum.accumulate(eq); return float(((pk - eq) / pk).max())


def sim(trades, start, unit, cap, mode):
    """trades＝[(ts, R, 每 R HKD@0.01)]（已排序）→ 權益序列 [(ts, eq)]。mode：fixed／ratchet（跟最高水位，只升唔跌）／sym（跟而家權益）。"""
    eq = peak = start; out = [(trades[0][0] - 1, eq)]
    for ts, r, hk in trades:
        ref = peak if mode == "ratchet" else eq
        n = 1 if mode == "fixed" else max(1, min(int(ref / unit + 1e-9), int(round(cap * 100))))
        eq += r * hk * n; peak = max(peak, eq); out.append((ts, eq))
        if eq <= 0:
            out[-1] = (ts, 0.0); break
    return out


def summarize(curve, years_mark=10):
    t0 = curve[0][0]; eq = [e for _, e in curve]
    at = lambda y: next((e for t, e in reversed(curve) if t <= t0 + y * 365.25 * 86400), eq[0])  # noqa: E731
    me = {}
    for t, e in curve:
        x = dt.datetime.fromtimestamp(t, dt.timezone.utc); me[x.year * 12 + x.month] = e
    ks = sorted(me); full = []
    last = eq[0]
    for k in range(ks[0], ks[-1] + 1):
        last = me.get(k, last); full.append(last)
    w12 = min((full[i + 12] / full[i] - 1) for i in range(len(full) - 12) if full[i] > 0)
    yrs = (curve[-1][0] - t0) / (365.25 * 86400)
    return {"x10": at(years_mark) / eq[0], "xend": eq[-1] / eq[0], "cagr": (eq[-1] / eq[0]) ** (1 / yrs) - 1 if eq[-1] > 0 else -1.0, "dd": ddpct(eq), "w12": w12, "bust": eq[-1] <= 0}


def main():
    cap = arg("--cap", 0.05); starts = {"…63": arg("--start63"), "…69": arg("--start69")}
    d = I.load(); S = {s[0]: s for s in SB.STRATS}; A = float(I.atr(I.B.resample(d, 86400))[-1])
    L = ["# 趨勢簿複利手數模擬（使用者 11-12「利用複式策略」）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；2010–2026 M1 嚴格版回測；每 R 折港幣用而家 D1 ATR14≈{A:.0f} 美元（固定）；只讀研究",
         f"- 手數＝floor(本 ÷ unit) × 0.01，最少 0.01、上限 {cap:.2f}；棘輪版「本」＝權益最高水位（只升唔跌），對稱版「本」＝而家權益；unit＝該戶口全部趨勢簿 0.01 手時嘅歷史最大回落 × 1.5；只喺新開倉時計",
         "- 「回報打五折」＝每條規則每張 R 減去佢平均 R 嘅一半（平均回報減半、波動唔變）；本金以 unit 嘅倍數表示（實數唔寫入檔案）", "",
         "| 戶口 | 簿 | 情景 | 起始（unit 倍數） | 版本 | 10 年後（倍） | 16 年後（倍） | 年複合 | 最大回落 | 最差連續 12 個月 | 爆倉 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for ac, keys in ACCTS.items():
        raw = {k: sorted((int(t), float(r)) for t, s, r in S[k][3](d)) for k in keys}
        base = sorted((t, r, K_ATR[k] * A * HK) for k in keys for t, r in raw[k])
        v = np.cumsum([r * hk for _, r, hk in base]); dd0 = float((np.maximum.accumulate(np.r_[0, v]) - np.r_[0, v]).max()); unit = dd0 * 1.5
        start = starts[ac] if starts[ac] else unit
        print(f"{ac} 0.01 手歷史最大回落 HKD {dd0:,.0f}；unit HKD {unit:,.0f}；起始 HKD {start:,.0f}", flush=True)
        for label, adj in (("回測原樣", 0.0), ("回報打五折", 0.5)):
            tr = sorted((t, r - adj * float(np.mean([x[1] for x in raw[k]])), K_ATR[k] * A * HK) for k in keys for t, r in raw[k])
            for ver, comp in (("① 固定 0.01", "fixed"), ("② 棘輪（贏加、輸唔減）", "ratchet"), ("③ 對稱（跌會減）", "sym")):
                cv = sim(tr, start, unit, cap, comp); s = summarize(cv)
                L.append(f"| {ac} | {len(keys)} 本 | {label} | {start / unit:.2f} | {ver} | {s['x10']:.2f} | {s['xend']:.2f} | {s['cagr'] * 100:+.1f}% | {s['dd'] * 100:.0f}% | {s['w12'] * 100:+.0f}% | {'⚠ 輸晒' if s['bust'] else '冇'} |")
                print(f"  {label} {ver}: 10 年後 HKD {s['x10'] * start:,.0f}、16 年後 {s['xend'] * start:,.0f}、年複合 {s['cagr'] * 100:+.1f}%、最大回落 {s['dd'] * 100:.0f}%、最差 12 月 {s['w12'] * 100:+.0f}%{'、⚠ 輸晒' if s['bust'] else ''}", flush=True)
    L += ["", "- 限制：unit 同規則都係喺同一批數據上定嘅（樣本內），將來回落好可能更大；冇計隔夜利息同跳空滑價；每條規則每 R 嘅港幣數用而家波幅，過去波幅細啲。", ""]
    open(os.path.join(HERE, "COMPOUND_SIM.md"), "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
