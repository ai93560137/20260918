"""[IDEAS #1199–#1205] 時段／日曆效應家族 嚴格 M1 版 第一批。規格、成功標準以 IDEAS 預先登記為準（跑之前 commit；冇網格）。
執行用 momo_strict_1157.trade_m1／run_m1：下一根開市市價入場；出場逐根 M1 判；到期收市平；每張扣 0.5 美元；一次一張；最低止蝕 max(3 美元, 0.3×ATR14 D1)。
用法：python3 research/strategy_search/session_1199.py → research/strategy_search/SESSION_1199.md"""
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
import momo_strict_1157 as M    # noqa: E402
import momo_strict_1164 as M3   # noqa: E402

OUT = os.path.join(HERE, "SESSION_1199.md")
H = 3600
D = 86400


def wd(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).weekday()


def at_hour(cx, hour, days=None):
    """H1：回傳 i（訊號 K 線），令 i+1 係 UTC hour:00 開市，而且 i 同 i+1 連續；days＝限星期幾。"""
    t = cx.b["t"]; out = []
    for i in range(1, len(t) - 1):
        if int(t[i + 1]) % D == hour * H and t[i + 1] - t[i] == H and (days is None or wd(t[i + 1]) in days):
            out.append(i)
    return out


def fixed(d, hour, sg, mb, k_atr, days=None):
    cx = M.Ctx(d, H); sigs = []
    for i in at_hour(cx, hour, days):
        ad = cx.atr_d.get(int(cx.b["t"][i + 1]) // D)
        if ad is None:
            continue
        sigs.append((i, sg, k_atr * ad, None, mb, None))
    return M.run_m1(cx, sigs)


def r1199(d):
    return fixed(d, 0, 1, 6, 0.5, (0, 1, 2, 3, 4))


def r1200(d):
    return fixed(d, 13, -1, 3, 0.5, (0, 1, 2, 3, 4))


def r1201(d):
    cx = M.Ctx(d, H); b = cx.b; t = b["t"]; sigs = []
    for i in at_hour(cx, 14, (4,)):
        x = dt.datetime.fromtimestamp(int(t[i + 1]), dt.timezone.utc)
        if x.day > 7:
            continue                                                      # 每月第一個星期五
        j = np.searchsorted(t, (int(t[i + 1]) // D) * D + 12 * H)
        if j >= len(t) or int(t[j]) != (int(t[i + 1]) // D) * D + 12 * H:
            continue
        mv = b["c"][i] - b["o"][j]; ad = cx.atr_d.get(int(t[i + 1]) // D)
        if mv == 0 or ad is None:
            continue
        sigs.append((i, 1 if mv > 0 else -1, 0.5 * ad, None, 6, None))
    return M.run_m1(cx, sigs)


def r1202(d):
    cx = M3.d1ctx(d); b = cx.b; a = B.atr(b); t = b["t"]; sigs = []
    for i in range(15, len(t) - 1):
        if wd(t[i]) != 0 or wd(t[i + 1]) != 1 or np.isnan(a[i]) or b["c"][i] == b["o"][i]:
            continue
        sigs.append((i, 1 if b["c"][i] > b["o"][i] else -1, a[i], None, 4, None))
    return M.run_m1(cx, sigs)


def r1203(d):
    return fixed(d, 17, -1, 3, 0.5, (4,))


def r1204(d):
    cx = M.Ctx(d, H); b = cx.b; t = b["t"]; sigs = []
    for i in at_hour(cx, 19, (0, 1, 2, 3, 4)):
        day = (int(t[i + 1]) // D) * D; j = np.searchsorted(t, day)
        ad = cx.atr_d.get(day // D)
        if ad is None or j >= i:
            continue
        mv = b["c"][i] - b["o"][j]
        if abs(mv) < 0.5 * ad:
            continue
        sigs.append((i, 1 if mv > 0 else -1, 0.3 * ad, None, 1, None))
    return M.run_m1(cx, sigs)


def r1205(d):
    cx = M.Ctx(d, H); b = cx.b; t = b["t"]; sigs = []
    sun = np.array([wd(x) == 6 and int(x) % D >= 21 * H for x in t]); fri = np.array([wd(x) == 4 for x in t])
    for i in range(1, len(t) - 1):
        if not sun[i] or sun[i - 1]:
            continue                                                      # i＝每週第一根真開市（星期日 21:00 UTC 後；Duka 星期日早段係平盤 bar）
        fr = np.nonzero(fri[:i])[0]
        if not len(fr) or t[i] - t[fr[-1]] > 4 * D:
            continue
        ad = cx.atr_d.get(int(t[fr[-1]]) // D)
        if ad is None:
            continue
        fclose = b["c"][fr[-1]]; gap = b["o"][i] - fclose
        if abs(gap) < 0.3 * ad:
            continue
        sg = -1 if gap > 0 else 1; en = b["o"][i + 1]; dist = (fclose - en) * sg
        fl = cx.floor(t[i])
        if fl is None or dist <= 0:
            continue
        risk = max(abs(gap), fl)
        sigs.append((i, sg, risk, dist / risk, 24, None))
    return M.run_m1(cx, sigs)


RULES = [("#1199", "亞洲時段做多", r1199, "hf"), ("#1200", "倫敦下午至紐約早段做空", r1200, "hf"), ("#1201", "非農日順勢", r1201, "lf"),
         ("#1202", "星期一方向延續到週五", r1202, "lf"), ("#1203", "星期五下午做空", r1203, "lf"), ("#1204", "收市前一小時順當日方向", r1204, "hf"),
         ("#1205", "週一開市跳空回補", r1205, "lf")]


def main():
    sets = {"d15": A.load("duka", "2015-01-01", "2022-12-31"), "m23": A.load("mt5", "2023-01-01", "2026-10-30"), "d10": A.load("duka", "2010-01-01", "2014-12-31")}
    L = ["# 時段／日曆效應家族 嚴格 M1 版 第一批（IDEAS #1199–#1205）", "",
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
