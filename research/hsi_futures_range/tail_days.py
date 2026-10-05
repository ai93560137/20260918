"""投資人問（2026-10-04）：只針對那一成「價格走出九成範圍」的尾部日子，有什麼策略可以贏錢？

三組測試：
  一、期貨 15 分 K（2024-06 至 2026-10，559 日）：尾部日（當天高或低穿出九成日範圍邊）之後一天——方向有沒有延續／回歸？
      波幅有沒有延續（翌日實際波幅 ÷ 翌日 HAR 預測）？翌日再穿邊界的機會？
  二、真實週期權（2025-10 至 2026-10）：在尾部日收市買價平跨式（當天 O.Q.P.），翌日收市賣出（同行使價、同到期的翌日 O.Q.P.）
      或持有到期；對照非尾部日。沽的版本就是倒轉。每腳成本 4 點。
  三、恒指日線 36 年（1990 起）：尾部日 = 當天收市對昨收的變動超過 1.65 × 過去 20 日標準差（約九成邊）；
      翌日、之後 5 日的回報（分方向）、翌日絕對變動相對平常的倍數，按年代分。
用法：python3 research/hsi_futures_range/tail_days.py --json 15 分 K 快取 --hsi hsi.csv [--opt data/hkex_options]
輸出：research/hsi_futures_range/tail_days/REPORT.md
"""
import argparse, csv, gzip, io, json, math, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import high_low_in as hl                                 # noqa: E402

OUT = HERE / "tail_days"
COST_LEG = 4.0


def st_line(x):
    x = np.array(x, dtype=float)
    if len(x) < 2:
        return "—"
    return f"{len(x)} 筆、平均 {x.mean():+.1f}、賺 {(x > 0).mean():.0%}、t {x.mean() / x.std(ddof=1) * math.sqrt(len(x)):+.2f}"


def part1(days, levels):
    """尾部日之後一天。"""
    rows = []
    for i in range(len(days) - 1):
        d, n = days[i], days[i + 1]
        lv = levels.get(d["date"])
        nlv = levels.get(n["date"])
        if not lv or not nlv:
            continue
        hi = max(b["high"] for b in d["bars"]); lo = min(b["low"] for b in d["bars"]); c = d["bars"][-1]["close"]
        up = hi > lv["high_edge_0.9"]; dn = lo < lv["low_edge_0.9"]
        kind = "up" if up and not dn else "down" if dn and not up else "both" if up and dn else "none"
        nh = max(b["high"] for b in n["bars"]); nl = min(b["low"] for b in n["bars"]); nc = n["bars"][-1]["close"]
        rows.append({"date": d["date"], "kind": kind, "close_out": (c > lv["high_edge_0.9"]) or (c < lv["low_edge_0.9"]),
                     "ret_next": (nc - c) / c * 100, "rng_ratio": (nh - nl) / n["rhat"],
                     "next_tail": nh > nlv["high_edge_0.9"] or nl < nlv["low_edge_0.9"],
                     "dir": 1 if kind == "up" else -1 if kind == "down" else 0})
    L = ["## 一、尾部日之後一天（期貨 15 分 K，2024-06 至 2026-10）", "",
         "| 當天 | 日數 | 翌日順方向收市的比例 | 翌日回報（順方向為正，%） | 翌日實際波幅 ÷ 翌日 HAR 預測 | 翌日再穿邊界 |", "|---|---|---|---|---|---|"]
    for kind, zh in (("none", "沒有穿邊（九成日子）"), ("up", "穿上邊界"), ("down", "穿下邊界"), ("both", "上下都穿")):
        sel = [r for r in rows if r["kind"] == kind]
        if not sel:
            continue
        rr = np.array([r["ret_next"] * (r["dir"] or 1) for r in sel])
        L.append(f"| {zh} | {len(sel)}（{len(sel) / len(rows):.0%}） | {(rr > 0).mean():.0%} | {rr.mean():+.2f} | "
                 f"{np.mean([r['rng_ratio'] for r in sel]):.2f} | {np.mean([r['next_tail'] for r in sel]):.0%} |")
    sel = [r for r in rows if r["kind"] in ("up", "down") and r["close_out"]]
    rr = np.array([r["ret_next"] * r["dir"] for r in sel])
    L.append(f"| 穿邊而且收市仍在邊界外 | {len(sel)} | {(rr > 0).mean():.0%} | {rr.mean():+.2f} | {np.mean([r['rng_ratio'] for r in sel]):.2f} | {np.mean([r['next_tail'] for r in sel]):.0%} |")
    sel = [r for r in rows if r["kind"] in ("up", "down") and not r["close_out"]]
    rr = np.array([r["ret_next"] * r["dir"] for r in sel])
    L.append(f"| 穿邊但收市回到邊界內 | {len(sel)} | {(rr > 0).mean():.0%} | {rr.mean():+.2f} | {np.mean([r['rng_ratio'] for r in sel]):.2f} | {np.mean([r['next_tail'] for r in sel]):.0%} |")
    tail = {r["date"] for r in rows if r["kind"] != "none"}
    return "\n".join(L), tail, {r["date"]: r for r in rows}


def load_opts(root):
    atm = defaultdict(dict)
    for r in csv.DictReader(open(Path(root) / "atm_iv.csv", encoding="utf-8")):
        atm[r["date"]][r["expiry"]] = r
    oqp = defaultdict(dict)
    for f in sorted((Path(root) / "series").glob("hsiwo_*.csv.gz")):
        with io.TextIOWrapper(gzip.open(f, "rb"), encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                oqp[(r["date"], r["expiry"])][(int(r["strike"]), r["cp"])] = float(r["oqp"])
    return atm, oqp


def part2(tail, info, atm, oqp, hsi):
    dates = sorted(d for d in atm if d in info)
    out = []
    for i, d in enumerate(dates[:-1]):
        n = dates[i + 1]
        exps = sorted(e for e in atm[d] if e > n)                 # 翌日仍未到期
        if not exps:
            continue
        e = exps[0]
        a = atm[d][e]
        K = int(float(a["atm_strike"]))
        s0 = oqp.get((d, e), {}); s1 = oqp.get((n, e), {})
        if (K, "C") not in s0 or (K, "P") not in s0 or (K, "C") not in s1 or (K, "P") not in s1:
            continue
        p0 = s0[(K, "C")] + s0[(K, "P")]; p1 = s1[(K, "C")] + s1[(K, "P")]
        settle = hsi.get(e)
        out.append({"date": d, "tail": d in tail, "kind": info[d]["kind"], "iv": (float(a["iv_call"]) + float(a["iv_put"])) / 2,
                    "one_day": p1 - p0 - 4 * COST_LEG, "to_expiry": (abs(settle - K) - p0 - 2 * COST_LEG) if settle else None,
                    "days_to_exp": None})
    L = ["", "## 二、尾部日收市買價平跨式（真實週期權結算價，2025-10 至 2026-10）", "",
         "| 當天 | 日數 | 價平 IV | 買跨式持 1 日（點） | 買跨式持到期（點） |", "|---|---|---|---|---|"]
    for name, sel in (("非尾部日", [r for r in out if not r["tail"]]), ("尾部日（穿出九成邊）", [r for r in out if r["tail"]]),
                      ("　穿上邊界", [r for r in out if r["kind"] == "up"]), ("　穿下邊界", [r for r in out if r["kind"] == "down"])):
        if len(sel) < 2:
            continue
        L.append(f"| {name} | {len(sel)} | {np.mean([r['iv'] for r in sel]):.1f}% | {st_line([r['one_day'] for r in sel])} | "
                 f"{st_line([r['to_expiry'] for r in sel if r['to_expiry'] is not None])} |")
    L.append("\n買跨式賺 = 沽跨式蝕；持 1 日成本 4 腳、到期 2 腳，每腳 4 點。")
    return "\n".join(L)


def part3(hsi_path):
    rows = [r for r in csv.DictReader(open(hsi_path, encoding="utf-8")) if float(r["High"]) != float(r["Low"])]
    rows = [r for r in rows if r["Date"] >= "1990-01-01"]
    c = np.array([float(r["Close"]) for r in rows]); dates = [r["Date"] for r in rows]
    ret = np.diff(np.log(c)); ret = np.r_[np.nan, ret]
    sig = np.array([np.std(ret[max(1, i - 20):i], ddof=1) if i > 21 else np.nan for i in range(len(ret))])
    out = []
    for i in range(22, len(ret) - 6):
        z = ret[i] / sig[i]
        if abs(z) >= 1.65:
            d = 1 if z > 0 else -1
            out.append({"date": dates[i], "dir": d, "r1": ret[i + 1] * d * 100, "r5": (np.log(c[i + 5] / c[i])) * d * 100,
                        "abs1_ratio": abs(ret[i + 1]) / sig[i], "z": z})
    norm_abs = np.nanmean(np.abs(ret[22:]) / sig[22:])
    L = ["", "## 三、恒指日線 36 年：收市變動超過 1.65σ 的尾部日之後", "",
         f"- 1990 起 {len(ret) - 22} 日，尾部日 {len(out)} 日（{len(out) / (len(ret) - 22):.1%}）；平常日翌日 |變動| ÷ σ 平均 {norm_abs:.2f}", "",
         "| 時段 | 尾部日 | 翌日順方向的比例 | 翌日回報（順方向為正，%） | 5 日回報（%） | 翌日 |變動| ÷ σ | 上升尾部翌日 | 下跌尾部翌日 |", "|---|---|---|---|---|---|---|---|"]
    for a, b, zh in (("1990", "2000", "1990s"), ("2000", "2010", "2000s"), ("2010", "2020", "2010s"), ("2020", "2027", "2020s"), ("1990", "2027", "全期")):
        sel = [r for r in out if a <= r["date"][:4] < b]
        if not sel:
            continue
        r1 = np.array([r["r1"] for r in sel]); r5 = np.array([r["r5"] for r in sel])
        up = np.array([r["r1"] for r in sel if r["dir"] > 0]); dn = np.array([r["r1"] for r in sel if r["dir"] < 0])
        L.append(f"| {zh} | {len(sel)} | {(r1 > 0).mean():.0%} | {r1.mean():+.2f}（t {r1.mean() / r1.std(ddof=1) * math.sqrt(len(r1)):+.1f}） | {r5.mean():+.2f} | "
                 f"{np.mean([r['abs1_ratio'] for r in sel]):.2f} | {up.mean():+.2f}（{len(up)}） | {dn.mean():+.2f}（{len(dn)}） |")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True); ap.add_argument("--hsi", required=True)
    ap.add_argument("--opt", default=str(REPO / "data" / "hkex_options"))
    a = ap.parse_args()
    cache = json.load(open(a.json))
    days = hl.build_days(cache["bars"], cache["daily"])
    levels = {r["date"]: {k: float(v) for k, v in r.items() if k != "date"} for r in csv.DictReader(open(HERE / "r_sweep" / "futu" / "levels_daily.csv"))}
    hsi = {r["Date"]: float(r["Close"]) for r in csv.DictReader(open(a.hsi, encoding="utf-8")) if float(r["High"]) != float(r["Low"])}
    t1, tail, info = part1(days, levels)
    atm, oqp = load_opts(a.opt)
    t2 = part2(tail, info, atm, oqp, hsi)
    t3 = part3(a.hsi)
    OUT.mkdir(exist_ok=True)
    text = "# 只針對尾部日（走出九成範圍）的策略（tail_days.py）\n\n" + t1 + "\n" + t2 + "\n" + t3 + "\n"
    (OUT / "REPORT.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
