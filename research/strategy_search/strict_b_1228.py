"""[IDEAS #1228–#1234] H4／H1 趨勢跟隨＋D1 過濾（B 門檻第二批）。規格以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
B 門檻＝原本三段標準（高頻）＋(B2) 三段剔最好 3 張後平均 > 0＋(B3) ① t ≥ 2.0；判法同 strict_b_1220.judge。
用法：python3 research/strategy_search/strict_b_1228.py → research/strategy_search/STRICT_B_1228.md"""
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
import fade_strict_1143 as F3   # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import strict_b_1220 as SB      # noqa: E402

OUT = os.path.join(HERE, "STRICT_B_1228.md")
H = 3600


def flips_tf(d, sec, state_fn, sma_n, k_sl=2.0, atr_n=14, maxb=60):
    """sec 時框；state_fn(b) 狀態由非 s 轉 s、同 D1 SMA 方向一致、訊號收市 07–20 UTC → 入；狀態離開 s 即平。"""
    cx = M.Ctx(d, sec); b = cx.b; a = B.atr(b, atr_n); s = state_fn(b); tr = F2.d1_trend(d, sma_n); sigs = []
    for i in range(1, len(s) - 1):
        if s[i] == 0 or s[i] == s[i - 1] or np.isnan(a[i]) or not M.liquid(b["t"][i] + sec):
            continue
        if tr.get(int(b["t"][i]) // 86400) != s[i]:
            continue
        sigs.append((i, int(s[i]), k_sl * a[i], None, maxb, (lambda s: lambda k, sg: s[k] != sg)(s)))
    return M.run_m1(cx, sigs)


def st_ema2050(b):
    c = b["c"]; e1, e2 = F3.ema(c, 20), F3.ema(c, 50)
    return np.where(np.isnan(e2), 0, np.where(e1 > e2, 1, np.where(e1 < e2, -1, 0)))


def st_macd0(b):
    c = b["c"]; m = F3.ema(c, 12) - F3.ema(c, 26)
    return np.where(np.isnan(m), 0, np.where(m > 0, 1, np.where(m < 0, -1, 0)))


def breakout(d, sec, n_in, n_out, sma_n, atr_n, maxb):
    """收市高（低）過之前 n_in 根最高（最低）[H1 用 h／l，H4 用收市]；收市穿之前 n_out 根相反極端即平。"""
    cx = M.Ctx(d, sec); b = cx.b; a = B.atr(b, atr_n); h, l, c = b["h"], b["l"], b["c"]; tr = F2.d1_trend(d, sma_n); sigs = []
    use_close = sec == 4 * H
    hi_src, lo_src = (c, c) if use_close else (h, l)
    for i in range(n_in, len(c) - 1):
        if np.isnan(a[i]) or not M.liquid(b["t"][i] + sec):
            continue
        sg = 1 if c[i] > hi_src[i - n_in:i].max() else (-1 if c[i] < lo_src[i - n_in:i].min() else 0)
        if not sg or tr.get(int(b["t"][i]) // 86400) != sg:
            continue
        ex = (lambda k, sg: (c[k] < lo_src[max(0, k - n_out):k].min()) if sg > 0 else (c[k] > hi_src[max(0, k - n_out):k].max()))
        sigs.append((i, sg, 2 * a[i], None, maxb, ex))
    return M.run_m1(cx, sigs)


RULES = [("#1228", "H4 SuperTrend＋D1 SMA50", lambda d: flips_tf(d, 4 * H, SB.st_supertrend, 50), "hf"),
         ("#1229", "H4 EMA20／50 交叉＋D1 SMA100", lambda d: flips_tf(d, 4 * H, st_ema2050, 100), "hf"),
         ("#1230", "H4 55 根突破＋D1 SMA200", lambda d: breakout(d, 4 * H, 55, 20, 200, 20, 60), "hf"),
         ("#1231", "H4 一目穿雲＋D1 SMA50", lambda d: flips_tf(d, 4 * H, SB.st_ichimoku, 50), "hf"),
         ("#1232", "H4 拋物線 SAR＋D1 SMA100", lambda d: flips_tf(d, 4 * H, SB.st_psar, 100), "hf"),
         ("#1233", "H4 MACD 零軸＋D1 SMA50", lambda d: flips_tf(d, 4 * H, st_macd0, 50), "hf"),
         ("#1234", "H1 100 根突破＋D1 SMA50", lambda d: breakout(d, H, 100, 50, 50, 14, 120), "hf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# B 門檻第二批：H4／H1 趨勢跟隨＋D1 過濾（IDEAS #1228–#1234）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；B＝原本三段（高頻）＋三段剔最好 3 張後平均 > 0＋① t ≥ 2.0；M1 嚴格版 0.5 美元", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | 判 |", "|---|---|---|---|---|---|"]
    ok = SB.judge(RULES, sets, L)
    L += ["", f"- B 合格：{'、'.join(ok) if ok else '冇'}（同批 7 條）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
