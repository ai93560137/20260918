"""[11-12] 對拍：真倉 xau/trend_d1rules.py 嘅 tdrsi／tdsurge／tdx50／tdflip（每日只用最近 420 日）對研究版 frame_1272（全歷史）。
數據：stooq 日線黃金 1973–2026。用法：python3 research/strategy_search/parity_frame.py → research/strategy_search/PARITY_FRAME.md"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import frame_1272 as FR        # noqa: E402
import robust_1270 as RB       # noqa: E402
import trend_d1rules as D1R    # noqa: E402

WIN = 420
MAP = (("tdrsi", 1273), ("tdsurge", 1285), ("tdx50", 1290), ("tdflip", 1300))


def main():
    d = RB.load(); cx = FR.M3.d1ctx(d); b = cx.b; a = FR.B.atr(b); n = len(b["c"])
    days = [(i, {"o": float(b["o"][i]), "h": float(b["h"][i]), "l": float(b["l"][i]), "c": float(b["c"][i])}) for i in range(n)]
    L = ["# 對拍：長線框架四條真倉規則（420 日窗）對研究版 frame_1272（全歷史）", "",
         f"- stooq 日線黃金 1973–2026，每條檢查 {n - WIN - 250} 個交易日；入場＝當日有冇訊號同方向；出場＝假設揸住嗰邊，當日判唔判平",
         "", "| 簿規則 | 想法 | 研究版入場 | 真倉版入場 | 同日同方向 | 風險（3×ATR）最大相差 | 出場檢查日數 | 出場唔一致 |", "|---|---|---|---|---|---|---|---|"]
    bad = 0
    for name, idea in MAP:
        rule = next(r for r in FR.RULES if str(r[0]).lstrip("#") == str(idea)); key, fn, p = rule[3], rule[4], rule[5]
        side = {}
        for sg, q in ((1, b), (-1, FR.neg(b))):
            md = FR.sma(q["c"], 200)
            trig = fn(q, a, p) if key in ("E", "B") else FR.e_base(q, a)
            mk = fn(q, a, md, p) if key == "X" else FR.x_base(q, a, md, 10 if key == "B" else 20)
            side[sg] = (q, md, trig, mk(0))
        nf = nl = both = nchk = xd = 0; rd = 0.0
        for i in range(WIN + 250, n):
            w = days[i - WIN + 1:i + 1]; f = 0
            for s in (1, -1):
                q, md, trig, _ = side[s]
                if not np.isnan(md[i]) and q["c"][i] > md[i] and trig[i] and not np.isnan(a[i]):
                    f = s; break
            sig = D1R.signal(name, w); lv = sig["side"] if sig else 0
            nf += f != 0; nl += lv != 0; both += (f != 0 and f == lv)
            if f and lv:
                rd = max(rd, abs(sig["risk"] - 3 * a[i]) / (3 * a[i]))
            for s in (1, -1):
                nchk += 1
                xd += bool(side[s][3](i)) != (D1R.exit_hit(name, s, w) is not None)
        bad += (nf != both or nl != both or xd)
        L.append(f"| {name} | #{idea} | {nf} | {nl} | {both} | {rd * 100:.2f}% | {nchk} | {xd} |")
    L += ["", f"- 結論：{'四條全部一致' if not bad else '有唔一致，唔可以上真倉'}", ""]
    open(os.path.join(HERE, "PARITY_FRAME.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
