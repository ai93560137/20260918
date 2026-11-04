"""[IDEAS #227b] 935 A+ 單倉版加 H4 趨勢過濾（使用者 11-04 喺總指揮「做 #227b」）。
A+＝組合 A 六個成份（portfolio.streams）＋D1 C3 內包線突破（candle_ind，同 vol_ind.py／真倉一樣滾動揀）；同時只得一張（入場時有倉就略過）。
H4 斜率同 921 R368（filter_921.H4Slope：最後一根已收市 H4、22:00 UTC 對齊、EMA50 差）。雙向過濾＝斜率 > 0 唔做空、< 0 唔做多；喺揀單倉之前擋（被擋嘅唔佔倉位）。
判（沿用 #227）：①平均 R 唔差過唔過濾 ②PF ≥ 唔過濾 +0.10 ③累計 R 最大回撤細過 ④按時間對半兩半平均 R 都唔差過；四樣都要。
另列 MT5 2022-10→、0.01 手 HKD、正數年、分成份（特別標 D1 Keltner 突破）、「只擋逆勢做多」做描述。
用法：python3 research/strategy_search/h4_filter_aplus.py → H4_FILTER_APLUS.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candle_ind as C  # noqa: E402
import d1_indicators as Q  # noqa: E402
import filter_921 as F  # noqa: E402
import portfolio as P  # noqa: E402
import robust_long as R  # noqa: E402

HKD = 7.8
KELT = "1 D1 Keltner 突破"
C3 = "7 D1 內包線突破"


def c3_stream(arrs, picks=None):
    D = Q.DI(*arrs); Q.T_H = 480
    T = [C.run(D, "C3 內包線突破", p, 480) for p in C.GRID]
    if picks is None:
        return P.wf_stream(lambda p: T[C.GRID.index(p)], C.GRID)
    return [x for Y, g in picks.items() if g is not None and Y >= 2022 for x in T[g] if R.yr(x[0]) == Y], picks


def tagged(ds, keys, slope):
    return [{"ts": int(x[0]), "s": int(x[1]), "d": float(x[2]), "r": float(x[3]), "exit": int(x[4]), "comp": k, "h4": slope.at(int(x[0]))}
            for k in keys for x in ds[k] if R.yr(x[0]) >= 2009]


def single(rows):
    out, busy = [], -1
    for x in sorted(rows, key=lambda z: (z["ts"], z["comp"])):
        if x["ts"] < busy:
            continue
        out.append(x); busy = x["exit"]
    return out


def both(x):
    return not ((x["s"] > 0 and x["h4"] < 0) or (x["s"] < 0 and x["h4"] > 0))


def longonly(x):
    return not (x["s"] > 0 and x["h4"] < 0)


def st(rows):
    rs = [x["r"] for x in rows]; s = F.summ(rs)
    eq = np.cumsum(rs) if rs else np.zeros(1)
    s["mdd"] = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if rs else 0.0
    s["hkd"] = sum(x["r"] * x["d"] * 100 * 0.01 * HKD for x in rows)
    yy = {}
    for x in rows:
        yy.setdefault(R.yr(x["ts"]), 0.0); yy[R.yr(x["ts"])] += x["r"]
    s["pos"] = f"{sum(1 for v in yy.values() if v > 0)}/{len(yy)}"
    return s


def fmt(s):
    return f"{s['n']} 張 平均 {s['avg']:+.3f}R PF {s['pf']:.2f} ΣR {s['sum']:+.1f} 回撤 {s['mdd']:+.1f}R" if s["n"] else "0 張"


def main():
    R.COST = 0.5
    gd = R.load_duka(); gm = R.load_mt5_spliced(gd)
    ds, pA = P.streams(gd); ms, _ = P.streams(gm, pA)
    keys = [k for k in ds if not k.startswith("7")]
    ds[C3], pc = c3_stream(gd); ms[C3], _ = c3_stream(gm, pc)
    keys.append(C3)
    sd = F.H4Slope(np.asarray(gd[0], dtype=np.int64), np.asarray(gd[4], dtype=float))
    sm = F.H4Slope(np.asarray(gm[0], dtype=np.int64), np.asarray(gm[4], dtype=float))
    allD = tagged(ds, keys, sd); allM = [x for x in tagged(ms, keys, sm) if x["ts"] >= P.A0]
    V = {"唔過濾（A+ 現行）": (single(allD), single(allM)),
         "雙向過濾（主判）": (single([x for x in allD if both(x)]), single([x for x in allM if both(x)])),
         "只擋逆勢做多（描述）": (single([x for x in allD if longonly(x)]), single([x for x in allM if longonly(x)]))}
    out = ["# 935 A+ 單倉加 H4 趨勢過濾（IDEAS #227b）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；A+＝組合 A 六成份＋D1 內包線突破，滾動前向樣本外 2009→2026（Dukascopy H1），同時一張、每張扣 0.5 美元",
           "- H4 斜率同 921 R368；過濾喺揀單倉之前做（被擋嘅訊號唔佔倉位，會騰出位畀之後嘅訊號）；HKD＝固定 0.01 手（935 真倉手數）", "",
           "| 版本 | Dukascopy 2009→2026 | 做多 | 做空 | 正數年 | 0.01 手 HKD | MT5 2022-10→ |", "|---|---|---|---|---|---|---|"]
    for k, (d, m) in V.items():
        s = st(d)
        out.append(f"| {k} | {fmt(s)} | {fmt(st([x for x in d if x['s'] > 0]))} | {fmt(st([x for x in d if x['s'] < 0]))} | {s['pos']} | {s['hkd']:+,.0f} | {fmt(st(m))} |")
    base, filt = V["唔過濾（A+ 現行）"][0], V["雙向過濾（主判）"][0]
    sb, sf = st(base), st(filt)
    mid = base[len(base) // 2]["ts"]
    b1, b2 = F.summ([x["r"] for x in base if x["ts"] < mid]), F.summ([x["r"] for x in base if x["ts"] >= mid])
    f1, f2 = F.summ([x["r"] for x in filt if x["ts"] < mid]), F.summ([x["r"] for x in filt if x["ts"] >= mid])
    ok = {"①平均": sf["avg"] >= sb["avg"], "②PF+0.1": sf["pf"] >= sb["pf"] + 0.10, "③回撤": sf["mdd"] > sb["mdd"],
          "④兩半": f1["avg"] >= b1["avg"] and f2["avg"] >= b2["avg"]}
    out += ["", f"- 前後半（以 {dt.datetime.fromtimestamp(mid, dt.timezone.utc):%Y-%m} 分）：唔過濾 {b1['avg']:+.3f}／{b2['avg']:+.3f}；雙向過濾 {f1['avg']:+.3f}／{f2['avg']:+.3f}",
            f"- 判（沿用 #227）：{'✅ 達標' if all(ok.values()) else '❌ 唔達'}：" + "、".join(f"{k}{'✅' if v else '❌'}" for k, v in ok.items()), "",
            "## 分成份（單倉入面實際做咗嘅單）", "", "| 成份 | 唔過濾 | 雙向過濾 | 原始訊號被擋（未揀單倉前） |", "|---|---|---|---|"]
    for k in keys:
        raw_block = [x for x in allD if x["comp"] == k and not both(x)]
        tag = " ⭐（11-04 K1）" if k == KELT else ""
        out.append(f"| {k}{tag} | {fmt(st([x for x in base if x['comp'] == k]))} | {fmt(st([x for x in filt if x['comp'] == k]))} | {fmt(st(raw_block))} |")
    kel = [x for x in allD if x["comp"] == KELT]
    agree = sum(1 for x in kel if both(x))
    k1 = int(dt.datetime(2026, 11, 1, 23, tzinfo=dt.timezone.utc).timestamp())
    out += ["", f"- D1 Keltner 突破原始訊號 {len(kel)} 個，其中 {agree} 個唔會被擋（{agree / max(len(kel), 1):.0%}）——突破本身多數順勢，過濾差唔多擋唔到佢；"
            f"11-04 K1（SELL，11-01 23:01 入場）嗰陣 Dukascopy H4 斜率 {sd.at(k1):+.3f}（數據到 {dt.datetime.fromtimestamp(int(gd[0][-1]), dt.timezone.utc):%Y-%m-%d}）",
            "", "- 只係研究；達標先講影子前向方案（同 TTM／CANDLE_FORWARD 一樣並列 A+），改 combo_live 要總指揮 dry-run＋使用者批。", ""]
    open(os.path.join(HERE, "H4_FILTER_APLUS.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
