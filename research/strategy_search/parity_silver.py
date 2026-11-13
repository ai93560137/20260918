"""[IDEAS #1442] 對拍：真倉規則 xau/trend_d1rules.py 嘅 tdsurge（只做多、420 日窗、最低止蝕 0）對研究版 index_1427.sim（#1285 只做多，全歷史）。
數據：白銀 stooq 日線 1968–2026。逐日比：有冇入場訊號、風險（3×ATR）、假設揸住時判唔判出場。
用法：python3 research/strategy_search/parity_silver.py → research/strategy_search/PARITY_SILVER.md"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import index_1427 as IX        # noqa: E402
import multi_1422 as MU        # noqa: E402
import trend_d1rules as D1R    # noqa: E402

WIN = 420


def main():
    d = MU.stooq("xagusd"); FR, M3, OG = IX.FR, IX.M3, IX.OG; restore = OG.patch("gold")
    try:
        cx = M3.d1ctx(d); b = cx.b; a = FR.B.atr(b); n = len(b["c"]); _, tf, xf = IX.CFG[2]; md = FR.sma(b["c"], 200); trig = tf(b, a); mk = xf(b, a, md)(0)
    finally:
        restore()
    days = [(i, {"o": float(b["o"][i]), "h": float(b["h"][i]), "l": float(b["l"][i]), "c": float(b["c"][i])}) for i in range(n)]
    nf = nl = both = xd = nx = short = 0; rd = 0.0
    for i in range(WIN + 250, n):
        w = days[i - WIN + 1:i + 1]; f = bool(not np.isnan(md[i]) and b["c"][i] > md[i] and trig[i] and not np.isnan(a[i]))
        po = D1R.plan_open("tdsurge", w, float(b["c"][i]), long_only=True, min_abs=0.0, digits=3); lv = bool(po)
        raw = D1R.signal("tdsurge", w); short += bool(raw and raw["side"] < 0 and not po)
        nf += f; nl += lv; both += f and lv
        if f and lv:
            rd = max(rd, abs(po["risk"] - 3 * a[i]) / (3 * a[i]))
        nx += 1; xd += bool(mk(i)) != (D1R.exit_hit("tdsurge", 1, w) is not None)
    bad = nf != both or nl != both or xd
    L = ["# 對拍：白銀真倉規則（tdsurge 只做多）對研究版 #1442（#1285 只做多）", "",
         f"- stooq 日線白銀 1968–2026，檢查 {n - WIN - 250:,} 個交易日；真倉版每日只用最近 {WIN} 日", "",
         "| 研究版入場 | 真倉版入場 | 同日一致 | 風險（3×ATR）最大相差 | 出場檢查日數 | 出場唔一致 | 被「只做多」擋走嘅做空訊號 |", "|---|---|---|---|---|---|---|",
         f"| {nf} | {nl} | {both} | {rd * 100:.2f}% | {nx:,} | {xd} | {short} |", "", f"- 結論：{'完全一致' if not bad else '有唔一致，唔可以上真倉'}", ""]
    open(os.path.join(HERE, "PARITY_SILVER.md"), "w").write("\n".join(L) + "\n"); print("\n".join(L)); return bad


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
