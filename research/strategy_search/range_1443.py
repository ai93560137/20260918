"""[IDEAS #1443] 方向過濾＋波幅範圍：200 日線上面／下面，價格穿「k×ATR14×√H」範圍嘅機會同賠付（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準。
冇期權價：只驗證範圍被穿嘅機會同嚴重程度。用法：python3 research/strategy_search/range_1443.py → research/strategy_search/RANGE_1443.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import index_1427 as IX   # noqa: E402
import multi_1422 as MU   # noqa: E402

OUT = os.path.join(HERE, "RANGE_1443.md")
MKTS = [("黃金", lambda: MU.stooq("xauusd", "1973-01-01")), ("白銀", lambda: MU.stooq("xagusd")), ("恒指", lambda: IX.load("HSI")), ("標普", lambda: IX.load("GSPC")), ("納指", lambda: IX.load("NDX"))]
HS, KS = (5, 20), (1.0, 1.5, 2.0)


def samples(d, H):
    """每隔 H 日一個樣本 → DataFrame：t、regime(+1/−1)、到期／途中相對當日收市嘅變動（ATR×√H 倍數）。"""
    c, h, l = d["c"], d["h"], d["l"]; n = len(c)
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    a = pd.Series(tr).rolling(14).mean().to_numpy(); md = pd.Series(c).rolling(200).mean().to_numpy(); rows = []
    for i in range(200, n - H, H):
        if np.isnan(a[i]) or a[i] <= 0 or c[i] == md[i]:
            continue
        u = a[i] * np.sqrt(H)
        rows.append((int(d["t"][i]), 1 if c[i] > md[i] else -1, (c[i + H] - c[i]) / u, (l[i + 1:i + H + 1].min() - c[i]) / u, (h[i + 1:i + H + 1].max() - c[i]) / u))
    return pd.DataFrame(rows, columns=["t", "reg", "end", "lo", "hi"])


def z2(x1, n1, x2, n2):
    if not n1 or not n2:
        return float("nan")
    p = (x1 + x2) / (n1 + n2); se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return float((x1 / n1 - x2 / n2) / se) if se > 0 else float("nan")


def cell(df, k, side):
    """side 'dn'：下方穿（賣跌期權）；'up'：上方穿（賣升期權）。回傳市況上／下各自 (n, 到期穿數, 途中掂數, 平均賠付, 最差賠付)。"""
    out = {}
    for reg in (1, -1):
        g = df[df.reg == reg]
        if side == "dn":
            br = g.end < -k; tc = g.lo < -k; pay = np.maximum(0, -k - g.end)
        else:
            br = g.end > k; tc = g.hi > k; pay = np.maximum(0, g.end - k)
        out[reg] = (len(g), int(br.sum()), int(tc.sum()), float(pay.mean()) if len(g) else float("nan"), float(pay.max()) if len(g) else float("nan"))
    return out


def judge(dfs, side):
    """safe＝假說入面較安全嘅市況（dn：上；up：下）。回傳 (五關, 明細行)。"""
    safe, risky = (1, -1) if side == "dn" else (-1, 1); lines = []; cells_ok = 0; g = {}
    for H in HS:
        allm = pd.concat([dfs[(m, H)] for m, _ in MKTS]); mid = allm.t.median()
        for k in KS:
            per = {m: cell(dfs[(m, H)], k, side) for m, _ in MKTS}; pool = cell(allm, k, side)
            rs, rr = pool[safe], pool[risky]; ok = rs[1] / rs[0] < rr[1] / rr[0]; cells_ok += ok
            lines.append(f"| {H} | {k:.1f} | " + " | ".join(f"{100 * per[m][safe][1] / max(per[m][safe][0], 1):.1f}%／{100 * per[m][risky][1] / max(per[m][risky][0], 1):.1f}%" for m, _ in MKTS)
                         + f" | **{100 * rs[1] / rs[0]:.1f}%／{100 * rr[1] / rr[0]:.1f}%** | {z2(rs[1], rs[0], rr[1], rr[0]):+.2f} | {100 * rs[2] / rs[0]:.1f}%／{100 * rr[2] / rr[0]:.1f}% | {rs[3]:.3f}／{rr[3]:.3f} | {rs[4]:.1f}／{rr[4]:.1f} | {rs[0]}／{rr[0]} |")
            if H == 20 and k == 1.5:
                h1, h2 = cell(allm[allm.t < mid], k, side), cell(allm[allm.t >= mid], k, side)
                g = {"mk": sum(1 for m, _ in MKTS if per[m][safe][1] / max(per[m][safe][0], 1) < per[m][risky][1] / max(per[m][risky][0], 1)),
                     "z": z2(rs[1], rs[0], rr[1], rr[0]), "h1": h1[safe][1] / h1[safe][0] < h1[risky][1] / h1[risky][0], "h2": h2[safe][1] / h2[safe][0] < h2[risky][1] / h2[risky][0],
                     "pay": rs[3] < rr[3], "h1v": (h1[safe][1] / h1[safe][0], h1[risky][1] / h1[risky][0]), "h2v": (h2[safe][1] / h2[safe][0], h2[risky][1] / h2[risky][0])}
    gates = [g["mk"] >= 4, g["z"] <= -2.0, g["h1"] and g["h2"], g["pay"], cells_ok >= 5]
    return gates, g, cells_ok, lines


def main():
    dfs = {}
    for m, fn in MKTS:
        d = fn()
        for H in HS:
            dfs[(m, H)] = samples(d, H)
    L = ["# #1443：方向過濾＋波幅範圍（200 日線上面／下面，價格穿 ATR 範圍嘅機會）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；黃金、白銀 stooq；恒指／標普／納指 Yahoo 現貨指數；每隔 H 日一個樣本（唔重疊）；只讀研究",
         "- 範圍＝k × ATR14 × √H；「到期穿」＝H 日後收市超出範圍；「賠付」＝到期超出範圍嘅幅度（ATR×√H 倍數）。**冇期權價：唔代表賣期權有錢賺**", ""]
    for side, title, sname, rname in (("dn", "H1：下方（賣跌期權）——市況「上」（收市 > SMA200）對「下」", "上", "下"), ("up", "H2：上方（賣升期權）——市況「下」對「上」", "下", "上")):
        gates, g, cells_ok, lines = judge(dfs, side)
        L += [f"## {title}", "", f"每格「{sname}／{rname}」＝假說較安全嘅市況／另一邊。", "",
              "| H | k | " + " | ".join(m for m, _ in MKTS) + " | 五市場合併到期穿率 | z | 途中掂率 | 平均賠付 | 最差賠付 | 樣本數 |", "|---|---|" + "---|" * (len(MKTS) + 6)] + lines
        L += ["", f"- 主格（H＝20、k＝1.5）：方向一致市場 {g['mk']}／5；合併 z {g['z']:+.2f}；前半 {100 * g['h1v'][0]:.1f}%／{100 * g['h1v'][1]:.1f}%、後半 {100 * g['h2v'][0]:.1f}%／{100 * g['h2v'][1]:.1f}%；6 格方向一致 {cells_ok}／6",
              f"- 五關（≥4 市場｜z ≤ −2｜前後半｜賠付｜≥5 格）：{''.join('✓' if x else '✗' for x in gates)} → **{'✅ 合格' if all(gates) else '❌ 唔合格'}**", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
