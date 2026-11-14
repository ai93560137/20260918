"""[IDEAS #1509–#1512] 假設 H「月尾再平衡資金流被提前交易而消退」嘅四個測試。規格同門檻以 IDEAS 預先登記為準（11-14 UTC，跑之前 commit）。
用法：python3 research/strategy_search/hypo_1509.py → research/strategy_search/HYPO_1509.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import batch6_1462 as B6     # noqa: E402
import direction_1445 as DR  # noqa: E402
import paper_robust as PR    # noqa: E402
import premia_1453 as PM     # noqa: E402

OUT = os.path.join(HERE, "HYPO_1509.md")
W0, W1 = pd.Period("2010-07", "M"), pd.Period("2026-10", "M")
PERIODS = (("2010–15", 2010, 2015), ("2016–20", 2016, 2020), ("2021–26", 2021, 2026))


def table(tk, zn, lag):
    s = B6.ohlc(tk).c; s = s[(s > 0) & (s.index.dayofweek < 5)]; b = (zn.shift(1) if lag else zn).reindex(s.index, method="ffill")
    z = pd.DataFrame({"s": s, "b": b}).dropna(); gs = [(p, g) for p, g in z.groupby(z.index.to_period("M"))]; out = []
    for i in range(1, len(gs) - 1):
        p, g = gs[i]; p0 = gs[i - 1][1].iloc[-1]; g2 = gs[i + 1][1]
        if len(g) < 16 or len(g2) < 3 or not (W0 <= p <= W1):
            continue
        a11, a6, e = g.iloc[-11], g.iloc[-6], g.iloc[-1]; rel11 = (a11.s / p0.s - 1) - (a11.b / p0.b - 1); rel6 = (a6.s / p0.s - 1) - (a6.b / p0.b - 1)
        s11, s6 = (1.0 if rel11 < 0 else -1.0), (1.0 if rel6 < 0 else -1.0); px = list(g.s.iloc[-11:]) + list(g2.s.iloc[:3])
        row = {"m": p, "rel6": rel6, "full": s11 * (e.s / a11.s - 1), "early": s11 * (a6.s / a11.s - 1), "late": s6 * (e.s / a6.s - 1)}
        for k in range(13):
            row[f"d{k}"] = s11 * (px[k + 1] / px[k] - 1)             # d0＝倒數第 10 日 … d9＝月尾日；d10–d12＝下月頭 3 日
        out.append(row)
    return pd.DataFrame(out).set_index("m")


def per(x, a, b):
    return x[(x.index.year >= a) & (x.index.year <= b)]


def spearman(x, y):
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy(); return float(np.corrcoef(rx, ry)[0, 1])


def main():
    zn = B6.ohlc("ZN=F").c; zn = zn[zn > 0]; T = {tk: table(tk, zn, lag) for _, tk, lag in PR.MK}; pan = lambda c: pd.DataFrame({tk: T[tk][c] for tk in T}).mean(axis=1)  # noqa: E731
    L = ["# #1509–#1512：假設 H 測試（月尾再平衡資金流被提前交易而消退）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；14 個市場；2010-07–2026-10；唔扣成本；只讀研究", ""]
    # ---- 1509
    F, La, E = pan("full"), pan("late"), pan("early"); L += ["## #1509 整體縮細定係只係提前", "", "| 時期 | 成個窗口（倒數第 11 日→月尾，訊號喺第 11 日） | 早段（第 11→6 日） | 尾段（第 6 日→月尾，訊號喺第 6 日） |", "|---|---|---|---|"]
    for nm, a, b in PERIODS:
        L.append(f"| {nm} | {100 * per(F, a, b).mean():+.3f}%（t {PM.tstat(per(F, a, b)):+.2f}） | {100 * per(E, a, b).mean():+.3f}% | {100 * per(La, a, b).mean():+.3f}%（t {PM.tstat(per(La, a, b)):+.2f}） |")
    df = float(per(F, 2021, 2026).mean() - per(F, 2010, 2015).mean()); tf = DR.welch(per(F, 2021, 2026).to_numpy(), per(F, 2010, 2015).to_numpy())
    dl = float(per(La, 2021, 2026).mean() - per(La, 2010, 2015).mean()); tl = DR.welch(per(La, 2021, 2026).to_numpy(), per(La, 2010, 2015).to_numpy())
    v9 = "整體縮細（版本 b：被套利走）" if tf <= -2.0 else ("同假設矛盾" if df > 0 and tf >= 2.0 else ("主要係前移（版本 a）" if tl <= -2.0 else "未能判斷（成個窗口同尾段嘅跌幅都唔顯著）"))
    L += ["", f"- 成個窗口 2021–26 − 2010–15＝{100 * df:+.3f}%（Welch t {tf:+.2f}）；尾段＝{100 * dl:+.3f}%（t {tl:+.2f}）", f"- 判斷：**{v9}**", ""]
    # ---- 1510
    dec = [float(per(T[tk].late, 2010, 2015).mean() - per(T[tk].late, 2021, 2026).mean()) for _, tk, _ in PR.MK]; ris = [float(per(T[tk].early, 2021, 2026).mean() - per(T[tk].early, 2010, 2015).mean()) for _, tk, _ in PR.MK]
    rho = spearman(dec, ris); v10 = "✅ 支持" if rho >= 0.46 else ("❌ 證偽" if rho <= 0 else "未能判斷")
    L += ["## #1510 跌得多嘅市場係咪亦係前移得多", "", "| 市場 | 尾段跌幅 | 早段升幅 |", "|---|---|---|"] + [f"| {nm} | {100 * d:+.3f}% | {100 * r:+.3f}% |" for (nm, _, _), d, r in zip(PR.MK, dec, ris)]
    L += ["", f"- Spearman ρ＝{rho:+.2f}（n＝14；單尾 5% 門檻 0.46）；早段升幅為正嘅市場 {sum(r > 0 for r in ris)}／14 → **{v10}**", ""]
    # ---- 1511
    top_a, top_c, sh = [], [], {nm: [] for nm, _, _ in PERIODS}; mid_a, mid_c = [], []
    for _, tk, _ in PR.MK:
        z = T[tk]; q1, q2 = z.rel6.abs().quantile(1 / 3), z.rel6.abs().quantile(2 / 3); top = z[z.rel6.abs() >= q2]; low = z[z.rel6.abs() < q2]
        top_a += list(per(top.late, 2010, 2015)); top_c += list(per(top.late, 2021, 2026)); mid_a += list(per(low.late, 2010, 2015)); mid_c += list(per(low.late, 2021, 2026))
        for nm, a, b in PERIODS:
            sh[nm].append(len(per(top.late, a, b)) / max(1, len(per(z.late, a, b))))
    d11 = float(np.mean(top_c) - np.mean(top_a)); t11 = DR.welch(np.array(top_c), np.array(top_a)); d11b = float(np.mean(mid_c) - np.mean(mid_a)); t11b = DR.welch(np.array(mid_c), np.array(mid_a))
    v11 = "✅ 最大偏離入面都明顯下跌（唔係訊號組合問題，假設 H 過呢關）" if d11 < 0 and t11 <= -2.0 else "❌ 最大偏離入面冇顯著下跌（假設 H 被削弱；要睇佔比有冇減少）"
    L += ["## #1511 減弱係咪只係因為大偏離月份少咗", "", "- 最大三分一偏離月份佔比：" + "、".join(f"{nm} {100 * np.mean(sh[nm]):.0f}%" for nm, _, _ in PERIODS),
          f"- 最大三分一：尾段方向回報 2010–15 {100 * np.mean(top_a):+.3f}%（{len(top_a)} 個市場月）→ 2021–26 {100 * np.mean(top_c):+.3f}%（{len(top_c)}）；差 {100 * d11:+.3f}%，Welch t {t11:+.2f}",
          f"- 其餘三分二：{100 * np.mean(mid_a):+.3f}% → {100 * np.mean(mid_c):+.3f}%；差 {100 * d11b:+.3f}%，t {t11b:+.2f}", f"- 判斷：**{v11}**", ""]
    # ---- 1512
    lab = [f"倒數第 {10 - k} 日" if k < 9 else "月尾日" for k in range(10)] + ["下月第 1 日", "下月第 2 日", "下月第 3 日"]
    L += ["## #1512 逐日輪廓（描述性；訊號固定喺倒數第 11 日；單位 bp）", "", "| 日 | " + " | ".join(nm for nm, _, _ in PERIODS) + " |", "|---|---|---|---|"]
    for k in range(13):
        x = pan(f"d{k}"); L.append(f"| {lab[k]} | " + " | ".join(f"{1e4 * per(x, a, b).mean():+.1f}" for _, a, b in PERIODS) + " |")
    pa, pb = La[(La.index >= pd.Period("2021-01", "M")) & (La.index <= pd.Period("2025-02", "M"))], La[La.index >= pd.Period("2025-03", "M")]
    L += ["", f"- 發表後：尾段方向回報 2021-01–2025-02 {100 * pa.mean():+.3f}%（{len(pa)} 個月）、2025-03–2026-10 {100 * pb.mean():+.3f}%（{len(pb)} 個月）；差 {100 * (pb.mean() - pa.mean()):+.3f}%，Welch t {DR.welch(pb.to_numpy(), pa.to_numpy()):+.2f}（樣本太短，只報數）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
