"""股息點數期貨（DHS 恒指、DHH 國指）一年結算價：市場對全年股息的預測怎麼走、有沒有成交、對比實際結算。結論在 DIVIDEND_FUTURES.md。

輸入：data/hkex_options/futures/dividend_<年>.csv.gz（港交所 dividend 報告；scripts/hkex_option_iv.py fetch --products dividend）
      data/hkex_options/yahoo/_HSI.csv、_HSCE.csv（指數收市，算隱含股息率）
用法：python3 research/index_arbitrage/dividend_futures.py
輸出：research/index_arbitrage/DIVIDEND_REPORT.md、dividend_daily.csv
"""
import csv, glob, gzip, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def main():
    rows = []
    for p in sorted(glob.glob(str(ROOT / "data/hkex_options/futures/dividend_*.csv.gz"))):
        rows += list(csv.DictReader(gzip.open(p, "rt")))
    idx = {"dhs": {r["date"]: float(r["close"]) for r in csv.DictReader(open(ROOT / "data/hkex_options/yahoo/_HSI.csv"))},
           "dhh": {r["date"]: float(r["close"]) for r in csv.DictReader(open(ROOT / "data/hkex_options/yahoo/_HSCE.csv"))}}
    by = defaultdict(lambda: defaultdict(dict))             # product → expiry → date → row
    for r in rows:
        by[r["product"]][r["expiry"]][r["date"]] = r
    L = [f"# 股息點數期貨結算價統計（自動產生；{min(r['date'] for r in rows)} 至 {max(r['date'] for r in rows)}，{len({r['date'] for r in rows})} 個交易日）", ""]
    daily = []
    for prod, name in (("dhs", "恒指股息點數期貨 DHS"), ("dhh", "國指股息點數期貨 DHH")):
        L += [f"## {name}", "", "| 合約 | 天數 | 首日結算 | 末日結算 | 最高 | 最低 | 日變動 σ（點） | 成交 > 0 的天數 | 總成交（張） | 末日 OI | 末日隱含股息率 % |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for exp, days in sorted(by[prod].items()):
            ds = sorted(days)
            s = [float(days[d]["settle"]) for d in ds]
            chg = [s[i + 1] - s[i] for i in range(len(s) - 1)]
            vol = [int(days[d]["vol"]) for d in ds]
            last = ds[-1]; spot = idx[prod].get(last)
            y = f"{s[-1] / spot * 100:.2f}" if spot else ""
            L.append(f"| {exp} | {len(ds)} | {s[0]:.2f} | {s[-1]:.2f} | {max(s):.2f} | {min(s):.2f} | {st.pstdev(chg) if len(chg) > 1 else 0:.2f} | "
                     f"{sum(v > 0 for v in vol)} | {sum(vol):,} | {int(days[last]['oi']):,} | {y} |")
            for d in ds:
                daily.append(dict(date=d, product=prod, expiry=exp, settle=days[d]["settle"], vol=days[d]["vol"], oi=days[d]["oi"],
                                  spot=idx[prod].get(d, ""), yield_pct=round(float(days[d]["settle"]) / idx[prod][d] * 100, 3) if d in idx[prod] else ""))
        # 月末快照：每個月最後一天各合約的結算，看預測怎麼修正
        L += ["", f"### {name}：每月月底各合約結算價（市場對該年全年股息點數的預測）", ""]
        exps = sorted(by[prod])
        L += ["| 月底 | " + " | ".join(exps) + " | 指數收市 |", "|---|" + "---|" * (len(exps) + 1)]
        dates = sorted({d for e in by[prod].values() for d in e})
        month_end = {}
        for d in dates:
            month_end[d[:7]] = d
        for m, d in sorted(month_end.items()):
            vals = [f"{float(by[prod][e][d]['settle']):.2f}" if d in by[prod][e] else "" for e in exps]
            L.append(f"| {d} | " + " | ".join(vals) + f" | {idx[prod].get(d, ''):.0f} |" if idx[prod].get(d) else f"| {d} | " + " | ".join(vals) + " | |")
        L.append("")
    with open(OUT / "dividend_daily.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(daily[0].keys())); w.writeheader(); w.writerows(daily)
    (OUT / "DIVIDEND_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
