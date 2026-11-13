"""[IDEAS #1421] 對拍：真倉規則 xau/trend_h4rules.py（h4macd；每次只用最近 400 根 H4、420 日日線）對研究版 h4wide_1402（MACD／X4，全歷史）。
數據：黃金 M1 2010–2026（Dukascopy＋MT5）。逐根 H4 比：有冇訊號同方向、風險、追蹤出場條件；逐日比日線狀態。
用法：python3 research/strategy_search/parity_h4macd.py → research/strategy_search/PARITY_H4MACD.md"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import h4wide_1402 as H       # noqa: E402
import intraday_1323 as I     # noqa: E402
import trend_h4rules as H4R   # noqa: E402

WIN_D, WIN_B = 420, H4R.KEEP


def main():
    E, _, tl = H.eng(); b = E.b; n = E.n
    cand = E.elig & (((E.st > 0) & tl[1]["MACD"]) | ((E.st < 0) & tl[-1]["MACD"]))
    trail = {sg: set(int(x) for x in E.trail[sg]) for sg in (1, -1)}
    db = I.B.resample(E.d, 86400)
    days = [(int(t) // 86400, {"o": float(o), "h": float(h), "l": float(l), "c": float(c)}) for t, o, h, l, c in zip(db["t"], db["o"], db["h"], db["l"], db["c"])]
    ctx = {}                                                   # day → (狀態, 上日 ATR)：真倉做法（只用之前最多 420 日）
    for k in range(1, len(days)):
        ctx[days[k][0]] = H4R.day_ctx(days[max(0, k - WIN_D):k])
    bars = [(int(t) // H4R.H4, {"o": float(o), "h": float(h), "l": float(l), "c": float(c)}) for t, o, h, l, c in zip(b["t"], b["o"], b["h"], b["l"], b["c"])]
    start = max(WIN_B, int(np.searchsorted(b["t"], (days[WIN_D + 250][0]) * 86400)))
    nr = nl = both = st_bad = tr_bad = nchk = 0; rd = 0.0; miss = []
    for i in range(start, n - 1):
        day = int(b["t"][i]) // 86400; st, fa = ctx.get(day, (0, None)); done = bars[i - WIN_B + 1:i + 1]
        st_bad += int(st != int(E.st[i]))
        sig = H4R.signal("h4macd", done, st, fa); f = bool(cand[i]); lv = bool(sig)
        nr += f; nl += lv; ok = f and lv and sig["side"] == int(E.st[i]); both += ok
        if f != lv and len(miss) < 8:
            miss.append((int(b["t"][i]), f, lv, int(E.st[i]), st))
        if ok:
            rd = max(rd, abs(sig["risk"] - float(E.risk[i])) / float(E.risk[i]))
        for sg in (1, -1):
            nchk += 1; tr_bad += int(H4R.trail_hit(sg, done, done[-1][0]) != (i in trail[sg]))
    bad = nr != both or nl != both or tr_bad
    L = ["# 對拍：#1421 真倉規則（h4macd）對研究版 h4wide_1402（MACD 柱轉正／穿 20 根或方向變出場）", "",
         f"- 黃金 M1 2010–2026 砌 H4，檢查 {n - 1 - start:,} 根 H4；真倉版每次只用最近 {WIN_B} 根 H4 同最多 {WIN_D} 日日線", "",
         "| 研究版訊號 | 真倉版訊號 | 同根同方向 | 風險最大相差 | 日線狀態唔一致（根） | 追蹤出場檢查 | 追蹤出場唔一致 |", "|---|---|---|---|---|---|---|",
         f"| {nr} | {nl} | {both} | {rd * 100:.3f}% | {st_bad} | {nchk:,} | {tr_bad} |", ""]
    if miss:
        L += ["- 唔一致例子（UTC 秒、研究、真倉、研究狀態、真倉狀態）：" + "；".join(str(m) for m in miss), ""]
    L += [f"- 結論：{'完全一致' if not bad else '有唔一致（見上），要逐項解釋先可以上真倉'}", ""]
    open(os.path.join(HERE, "PARITY_H4MACD.md"), "w").write("\n".join(L) + "\n"); print("\n".join(L)); return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
