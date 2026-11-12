"""[IDEAS #1353–#1361] 日線方向＋極短 TP、極大 SL（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準（跑之前 commit；參數固定）。
用法：python3 research/strategy_search/scalp_1353.py → research/strategy_search/SCALP_1353.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intraday_1323 as I  # noqa: E402

OUT = os.path.join(HERE, "SCALP_1353.md")
TPS, SLS = (0.05, 0.10, 0.20), (1.0, 2.0, 3.0)


def first_hit(mask_fn, s0, s1):
    """喺 [s0, s1) 分段搵第一個 True（避免成段計）。"""
    step = 240; a = s0
    while a < s1:
        b = min(s1, a + step); m = mask_fn(a, b)
        if m.any():
            return a + int(np.argmax(m))
        a = b; step = min(step * 4, 200000)
    return None


def run(d, st, fl, tp_k, sl_k):
    t, o, h, l, c = d["t"], d["o"], d["h"], d["l"], d["c"]; day = t // 86400
    ud, first = np.unique(day, return_index=True); sd = np.array([st.get(int(x), 0) for x in ud]); ad = np.array([fl.get(int(x), np.nan) for x in ud])
    hours = np.flatnonzero((t % 3600 == 0) & (t % 86400 >= 7 * 3600) & (t % 86400 < 20 * 3600))   # H1 開市嗰根 M1
    out = []; p = 0; n = len(t)
    while p < len(hours):
        s0 = int(hours[p]); di = int(np.searchsorted(ud, day[s0])); sg = int(sd[di]); a = ad[di]
        if sg == 0 or np.isnan(a):
            p += 1; continue
        k = di + 1
        while k < len(ud) and sd[k] == sg:
            k += 1
        s1 = int(first[k]) if k < len(ud) else n                      # 方向變咗嗰日第一根 M1
        en = o[s0]; tp = en + sg * tp_k * a; sl = en - sg * sl_k * a
        if sg > 0:
            x = first_hit(lambda i, j: (h[i:j] >= tp) | (l[i:j] <= sl), s0, s1)
        else:
            x = first_hit(lambda i, j: (l[i:j] <= tp) | (h[i:j] >= sl), s0, s1)
        if x is None:
            x = min(s1, n - 1); px = o[x] if s1 < n else c[x]; why = "flip"
        else:
            hit_sl = (l[x] <= sl) if sg > 0 else (h[x] >= sl); px = sl if hit_sl else tp; why = "sl" if hit_sl else "tp"
        out.append((int(t[s0]), int(t[x]), sg, (sg * (px - en) - I.COST) / a, why))
        p = int(np.searchsorted(hours, x, "right"))
    return out


def main():
    d = I.load(); st, fl, bench = I.daily(d); m0, m1 = I.month(bench[0][0]), I.month(bench[-1][0])
    bx = I.monthly(bench, m0, m1) * 3                                  # 基準轉做 D1 ATR 倍數
    L = ["# #1353–#1361：日線方向＋極短 TP、極大 SL", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；數據 Dukascopy M1 2010–2022＋MT5 M1 2023–2026-10；只讀研究，唔改真倉",
         "- 窗口有方向就不停順方向做（H1 開市入，07–20 UTC）；TP／SL 用前一日 D1 ATR 倍數；方向變就平；每張扣 0.5 美元；損益單位＝D1 ATR 倍數",
         f"- 日線基準（同期）：總 {bx.sum():+.1f} ATR、每月最大回撤 {I.dd(bx):.1f} ATR、總 ÷ 回撤 {bx.sum() / I.dd(bx):.2f}", "",
         "| # | TP | SL | 張數 | 勝率 | 打和所需勝率 | 每張平均 | 2010–14 | 2015–22 | 2023–26 | 多 | 空 | 最差一張 | SL 次數 | 總 | 回撤 | 總÷回撤 | 截距 t | 過關 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    idea = 1353; npass = 0
    for sl_k in SLS:
        for tp_k in TPS:
            tr = run(d, st, fl, tp_k, sl_k); r = np.array([q[3] for q in tr]); n = len(r)
            seg = [np.mean([q[3] for q in tr if I.ts(a) <= q[0] < I.ts(b)]) for _, a, b in I.SEGS]
            lo = np.mean([q[3] for q in tr if q[2] > 0]); sh = np.mean([q[3] for q in tr if q[2] < 0])
            y = I.monthly([(q[1], q[3]) for q in tr], m0, m1); _, _, t0 = I.alpha_t(y, bx); ratio = y.sum() / I.dd(y)
            g1 = r.mean() > 0 and all(v > 0 for v in seg) and lo > 0 and sh > 0; g2 = t0 >= 2.0; g3 = ratio > bx.sum() / I.dd(bx)
            ok = g1 and g2 and g3; npass += ok
            wins = [q[3] for q in tr if q[3] > 0]; loss = [q[3] for q in tr if q[3] <= 0]
            be = (-np.mean(loss)) / (np.mean(wins) - np.mean(loss)) if wins and loss else float("nan")
            L.append(f"| {idea} | {tp_k:.2f} | {sl_k:.0f} | {n} | {100 * (r > 0).mean():.1f}% | {100 * be:.1f}% | {r.mean():+.4f} | {seg[0]:+.4f} | {seg[1]:+.4f} | {seg[2]:+.4f} | {lo:+.4f} | {sh:+.4f} | "
                     f"{r.min():+.2f} | {sum(q[4] == 'sl' for q in tr)} | {y.sum():+.1f} | {I.dd(y):.1f} | {ratio:.2f} | {t0:+.2f} | {''.join('✓' if g else '✗' for g in (g1, g2, g3))} {'✅' if ok else '❌'} |")
            print(L[-1], flush=True); idea += 1
    L += ["", f"- 過關欄三格＝①平均、三段、多空全部正 ②截距 t ≥ 2 ③總÷回撤 > 日線基準。**全過：{npass}／9**", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L[:6]), L[-2])


if __name__ == "__main__":
    main()
