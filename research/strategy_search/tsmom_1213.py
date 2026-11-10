"""[IDEAS #1213–#1219] 時間序列動量／定期再平衡 嚴格 M1 版 第一批。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.run_m1（D1 K 線，下一根開市入、M1 判出場、到期收市平、扣 0.5 美元、一次一張）。
期間：週＝交易週（星期日晚市歸下一週）；月＝UTC 曆月。訊號喺期間最後一根 D1 收市，下一根開市入，揸到下一期最後一根收市。
用法：python3 research/strategy_search/tsmom_1213.py → research/strategy_search/TSMOM_1213.md"""
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
import fade_strict_1129 as F    # noqa: E402
import fade_strict_1136 as F2   # noqa: E402
import fade_strict_1143 as F3   # noqa: E402
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402

OUT = os.path.join(HERE, "TSMOM_1213.md")


def wkey(t):
    return (int(t) // 86400 + 4) // 7                       # 星期日晚市歸下一週


def mkey(t):
    x = dt.datetime.fromtimestamp(int(t), dt.timezone.utc)
    return x.year * 12 + x.month - 1


def periodic(d, keyf, sigf, k_atr, max_bars):
    """sigf(i, b, extra) → +1／−1／0；i＝今期最後一根 D1。揸到下一期最後一根。"""
    cx = M3.d1ctx(d); b = cx.b; t = b["t"]; a = B.atr(b); keys = np.array([keyf(x) for x in t]); sigs = []
    ends = [i for i in range(len(t) - 1) if keys[i + 1] != keys[i]]
    for n, i in enumerate(ends):
        if np.isnan(a[i]) or n + 1 >= len(ends):
            continue
        sg = sigf(i, b, keys)
        if not sg:
            continue
        mb = min(max_bars, ends[n + 1] - i)
        sigs.append((i, sg, k_atr * a[i], None, mb, None))
    return M.run_m1(cx, sigs)


def ret_sign(lb):
    def f(i, b, keys):
        if i < lb:
            return 0
        mv = b["c"][i] - b["c"][i - lb]
        return 0 if mv == 0 else (1 if mv > 0 else -1)
    return f


def r1213(d):
    return periodic(d, mkey, ret_sign(63), 2.5, 23)


def r1214(d):
    return periodic(d, mkey, ret_sign(252), 2.5, 23)


def r1215(d):
    cache = {}

    def f(i, b, keys):
        if "m" not in cache:
            cache["s"] = F2.sma(b["c"], 20); cache["m"] = F2.sma(b["c"], 100)
        s, m = cache["s"][i], cache["m"][i]
        return 0 if np.isnan(m) or s == m else (1 if s > m else -1)
    return periodic(d, wkey, f, 2.0, 6)


def r1216(d):
    def f(i, b, keys):
        if i < 252:
            return 0
        hh, ll = b["h"][i - 251:i + 1].max(), b["l"][i - 251:i + 1].min()
        if hh <= ll:
            return 0
        pos = (b["c"][i] - ll) / (hh - ll)
        return 1 if pos >= 0.8 else (-1 if pos <= 0.2 else 0)
    return periodic(d, wkey, f, 2.0, 6)


def r1217(d):
    cache = {}

    def f(i, b, keys):
        if "a20" not in cache:
            cache["a20"] = B.atr(b, 20); cache["a100"] = B.atr(b, 100)
        a20, a100 = cache["a20"][i], cache["a100"][i]
        if i < 63 or np.isnan(a100) or a100 <= 0 or a20 / a100 >= 1.0:
            return 0
        return ret_sign(63)(i, b, keys)
    return periodic(d, mkey, f, 2.5, 23)


def r1218(d):
    def f(i, b, keys):
        k = keys[i]; idx1 = np.nonzero(keys == k)[0]; idx0 = np.nonzero(keys == k - 1)[0]
        if not len(idx0) or not len(idx1):
            return 0
        u1 = b["c"][idx1[-1]] - b["o"][idx1[0]]; u0 = b["c"][idx0[-1]] - b["o"][idx0[0]]
        return 1 if (u1 > 0 and u0 > 0) else (-1 if (u1 < 0 and u0 < 0) else 0)
    return periodic(d, mkey, f, 2.5, 23)


def r1219(d):
    cache = {}

    def f(i, b, keys):
        if "map" not in cache:
            uk = []; wc = []
            for j in range(len(keys)):                              # 交易週收市＝該週最後一根 D1 收市（冇偷睇）
                if j + 1 == len(keys) or keys[j + 1] != keys[j]:
                    uk.append(int(keys[j])); wc.append(b["c"][j])
            wc = np.array(wc); mac = F3.ema(wc, 12) - F3.ema(wc, 26); sg = F3.ema(np.nan_to_num(mac, nan=0.0), 9)
            cache["map"] = {uk[j]: (0 if np.isnan(mac[j]) or j < 35 else (1 if mac[j] > sg[j] else -1)) for j in range(len(uk))}
        return cache["map"].get(int(keys[i]), 0)
    return periodic(d, wkey, f, 2.0, 6)


RULES = [("#1213", "3 個月時間序列動量（每月）", r1213, "lf"), ("#1214", "12 個月時間序列動量（每月）", r1214, "lf"),
         ("#1215", "SMA20／SMA100 每週再平衡", r1215, "lf"), ("#1216", "52 週區間位置（每週）", r1216, "lf"),
         ("#1217", "平靜趨勢月動量", r1217, "lf"), ("#1218", "連續兩個月同向", r1218, "lf"), ("#1219", "週線 MACD 方向（每週）", r1219, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 時間序列動量／定期再平衡 嚴格 M1 版 第一批（IDEAS #1213–#1219）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；下一根開市市價入場、M1 逐根判出場、最低止蝕 max(3 美元, 0.3×ATR D1)、每張扣 0.5 美元、一次一張", "",
         "| IDEAS | 規則 | ① Duka 2015–22 | ② MT5 2023–26 | ③ Duka 2010–14 | 判 | 剔最好 3 張後平均（①／②／③） |", "|---|---|---|---|---|---|---|"]
    passed = []
    for key, name, fn, kind in RULES:
        cells, ok, rob = [], True, []
        for seg, crit in zip(("d15", "m23", "d10"), F.CRIT[kind]):
            tr = fn(sets[seg]); r = [x[2] for x in tr]; st = A.stats(r)
            n = st["n"]; avg = st.get("avg", 0.0); pf = st.get("pf", 0.0)
            good = n >= crit[0] and avg >= crit[1] and pf >= crit[2]
            extra = ""
            if seg == "d15":
                yp, yn = F.yearly_pos(tr); extra = f"，正年 {yp}／{yn}"; good = good and yp >= 5
            ok = ok and good
            cells.append(f"{n} 張 {avg:+.3f}R PF {pf:.2f}{extra} {'✅' if good else '❌'}" if n else "0 張 ❌")
            rob.append(f"{np.mean(sorted(r)[:-3]):+.3f}" if n > 3 else "—")
        L.append(f"| {key} | {name} | " + " | ".join(cells) + f" | {'✅ 合格' if ok else '❌'} | {'／'.join(rob)} |")
        if ok:
            passed.append(key)
    L += ["", f"- 合格：{'、'.join(passed) if passed else '冇'}（同批 7 條，三段都要過）；最後一欄只作穩健度描述，唔影響判決", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
