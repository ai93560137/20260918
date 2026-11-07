"""[IDEAS #1001] rev15 E6S4 長歷史回測（Dukascopy M1 2015–2022）。規格、成功標準以 IDEAS #1001 預先登記為準（跑之前 commit）。
引擎＝fit_rules.py（同 #160 前向一樣）；主判固定美元參數（同 933 實倉一樣），按價格縮放版只作描述。唔落單、唔寫 GCS。
用法：python3 research/student_offline/rev15_history.py → research/student_offline/REV15_HISTORY.md"""
import collections
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fit_rules as fr   # noqa: E402

A, B = "2015-01-01", "2022-12-31"
CACHE = "/tmp/rev15_history_duka.npz"
NEW = {**fr.CUR_COMMON, "E": 6.0, "S": 4.0, "RT": 1.0}     # E6 Z2 S4 1R 冷卻 60
CUR = dict(fr.CUR_COMMON)                                   # E4 Z2 S6 2R 冷卻 60
P = fr.CURRENT["rev15"]


def load():
    if os.path.exists(CACHE):
        z = np.load(CACHE)
        return {k: z[k] for k in ("t", "o", "h", "l", "c")}
    from concurrent.futures import ThreadPoolExecutor
    g = fr.g
    days = g.days_between(A, B)
    pre = fr.config.PREFIX + "duka/"

    def one(d):
        doc = g.G.read_json(f"{pre}{d}.json")
        return g._bars(doc.get("bars") if isinstance(doc, dict) else doc) if doc is not None else {}
    bars = {}
    with ThreadPoolExecutor(16) as ex:
        for k, part in enumerate(ex.map(one, days)):
            bars.update(part)
            if k % 250 == 0:
                print(f"  載入 {days[k]}（{len(bars)} 根）", flush=True)
    ks = sorted(bars)
    d = {"t": np.array([bars[k]["time"] for k in ks], dtype=np.int64)}
    for k, n in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
        d[k] = np.array([bars[t][n] for t in ks], dtype=np.float64)
    np.savez(CACHE, **d)
    return d


def scaled(d):
    """按價格縮放：每根 K 線 × 4000 ÷ 前一個 UTC 日收市（第一日用當日開市）。"""
    day = d["t"] // 86400
    f = np.ones(len(day))
    last_close, cur, ref = None, None, None
    for i in range(len(day)):
        if day[i] != cur:
            ref = last_close if last_close else d["o"][i]
            cur = day[i]
        f[i] = 4000.0 / ref
        last_close = d["c"][i]
    return {"t": d["t"], **{k: d[k] * f for k in ("o", "h", "l", "c")}}


def run(d, cp, t_from, t_to, offset_min=0):
    raw = fr.raw_signals(d, "rev15", P)
    sigs = fr.cooldown(raw, d["t"], cp["CD"], t_from + offset_min * 60, t_to)
    mats = fr.future_mats(d, sigs)
    r = fr.simulate(mats, cp["E"], cp["Z"], cp["S"], cp["RT"])
    ts = np.array([int(d["t"][i]) + 60 for i, _ in sigs], dtype=np.int64)
    return r, ts, mats


def dd_stats(r):
    """最大 R 回撤；照 933 停線（由起點累計 ≤ −8R 或由高位回撤 ≥ 10R → 停，之後重新起計）數觸發次數。"""
    r = r[~np.isnan(r)]
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(np.r_[0.0, eq])[1:]
    mdd = float((peak - eq).max()) if len(r) else 0.0
    trips, cum, pk = 0, 0.0, 0.0
    for x in r:
        cum += x; pk = max(pk, cum)
        if cum <= -8 or pk - cum >= 10:
            trips += 1; cum = pk = 0.0
    return mdd, trips


def main():
    d = load()
    t0, t1 = fr.ts_of(A), fr.ts_of(B) + 86400
    print(f"M1 {len(d['t'])} 根", flush=True)
    rn, ts, mats = run(d, NEW, t0, t1)
    rc = fr.simulate(mats, CUR["E"], CUR["Z"], CUR["S"], CUR["RT"])
    sn, sc = fr.stats(rn), fr.stats(rc)
    yrs = sorted({dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year for x in ts})
    yr = {y: fr.stats(rn[np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year == y for x in ts])]) for y in yrs}
    yr_c = {y: fr.stats(rc[np.array([dt.datetime.fromtimestamp(int(x), dt.timezone.utc).year == y for x in ts])]) for y in yrs}
    last3 = fr.stats(rn[ts >= fr.ts_of("2020-01-01")])
    mdd, trips = dd_stats(rn)
    fill = float(np.mean(~np.isnan(rn))) if len(rn) else 0.0

    ok = {"①全期≥+0.10R且PF≥1.15": sn["n"] > 0 and sn["avg"] >= 0.10 and sn["pf"] >= 1.15,
          "②8年≥6年正數": sum(1 for y in yrs if yr[y]["n"] and yr[y]["avg"] > 0) >= 6,
          "③2020–2022≥+0.10R": last3["n"] > 0 and last3["avg"] >= 0.10,
          "④高過現行≥0.10R": sn["n"] > 0 and sc["n"] > 0 and sn["avg"] - sc["avg"] >= 0.10}

    out = ["# rev15 E6S4 長歷史回測（IDEAS #1001）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Dukascopy M1 {A}→{B}，{len(d['t']):,} 根；出區 {len(ts):,} 條，成交並完單 {sn['n']:,} 張（{fill:.0%}）",
           "- 規則：前 15 根 M1 走 ≥ 3 美元 → 反向；60 分鐘冷卻。新結構 E6 Z2 S4 1R（同 933 實倉）；現行 E4 Z2 S6 2R 並排；每張扣 0.5 美元", "",
           "## 全期", "", f"- 新 E6S4：{fr.fmt(sn)}", f"- 現行 E4S6 2R：{fr.fmt(sc)}",
           f"- 新結構最大 R 回撤 {mdd:.1f}R；照 933 停線（−8R／由高位回撤 10R）歷史觸發 {trips} 次（每次觸發後重新起計）", "",
           "## 每年", "", "| 年 | 新 E6S4 | 現行 E4S6 2R |", "|---|---|---|"]
    out += [f"| {y} | {fr.fmt(yr[y])} | {fr.fmt(yr_c[y])} |" for y in yrs]

    hrs = collections.defaultdict(list)
    for x, r in zip(ts, rn):
        if not np.isnan(r):
            hrs[dt.datetime.fromtimestamp(int(x), dt.timezone.utc).hour].append(r)
    out += ["", "## 每個 UTC 鐘（新結構，只作描述）", "", "| 鐘 | 張數 | 平均 R |", "|---|---|---|"]
    out += [f"| {h:02d} | {len(v)} | {np.mean(v):+.3f} |" for h, v in sorted(hrs.items())]

    out += ["", "## 冷卻起點錯開（只作描述；REV15_GAP 見過相位影響）", ""]
    for off in (10, 20, 30, 40, 50):
        r2, _, _ = run(d, NEW, t0, t1, off)
        out.append(f"- 錯開 {off} 分鐘：{fr.fmt(fr.stats(r2))}")

    ds = scaled(d)
    r3, _, m3 = run(ds, NEW, t0, t1)
    r3c = fr.simulate(m3, CUR["E"], CUR["Z"], CUR["S"], CUR["RT"])
    out += ["", "## 按價格縮放版（全部價 ÷ 前日收市 × 4000；只作描述）", "",
            "- 2015–2022 金價大約 1,050–2,070，固定 3／6／4 美元相對波幅大好多；縮放版當全部年份都喺 4,000 水平",
            f"- 新 E6S4：{fr.fmt(fr.stats(r3))}", f"- 現行 E4S6 2R：{fr.fmt(fr.stats(r3c))}"]

    out += ["", "## 判（預先登記 IDEAS #1001；主判固定美元）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            "- " + ("✅ 達標 → 11-08 照計劃開 933" if all(ok.values())
                    else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + " → 即報總指揮同使用者，建議 933 延遲上實倉（使用者決定）；唔准改參數再試同一批數據"),
            "- 2023–2025 冇數據（容器連唔到 Dukascopy）；2015–2022 金價水平同而家差好遠，見縮放版。", ""]
    md = "\n".join(out) + "\n"
    open(os.path.join(HERE, "REV15_HISTORY.md"), "w", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    main()
