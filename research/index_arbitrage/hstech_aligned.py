"""科指期貨（Futu HK.HTI_FRONT 15 分 K）對 3033／3067 收市的基差：用同一時刻的價消掉時間差噪音。結論在 HSTECH_BASIS.md 第五節。

輸入：research/index_arbitrage/hti_front_1600.csv（每天 16:00／16:15／16:30 收市、3033 與 3067 收市；GCS archive/futu_k_15m/HK.HTI_FRONT）
定義：b = ln(期貨 ÷ ETF)；每張合約配 b ≈ c + a·T（T = 距最後交易日的日曆日數，當月倒數第二個營業日）；殘差以 % 計。
用法：python3 research/index_arbitrage/hstech_aligned.py → HSTECH_ALIGNED_REPORT.md
"""
import csv, math, statistics as st
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
LTD_OVERRIDE = {"2024-03": date(2024, 3, 27), "2025-01": date(2025, 1, 27)}


def second_last_bday(y, m):
    key = f"{y:04d}-{m:02d}"
    if key in LTD_OVERRIDE:
        return LTD_OVERRIDE[key]
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    n = 0
    while True:
        if d.weekday() < 5:
            n += 1
            if n == 2:
                return d
        d -= timedelta(days=1)


def front(d):
    ltd = second_last_bday(d.year, d.month)
    if d < ltd:
        return f"{d.year}-{d.month:02d}", ltd
    y, m = (d.year + (d.month == 12), d.month % 12 + 1)
    return f"{y}-{m:02d}", second_last_bday(y, m)


def residuals(rows, price, etf):
    by = defaultdict(list)
    for r in rows:
        f = (float(r["f1600"]) + float(r["f1615"])) / 2 if price == "mid" else float(r[price])
        if not r[etf] or f <= 0:
            continue
        d = date.fromisoformat(r["date"]); c, ltd = front(d)
        by[c].append(dict(date=r["date"], front=c, T=(ltd - d).days, b=math.log(f / float(r[etf]))))
    out = []
    for c, rs in sorted(by.items()):
        xs = [x["T"] for x in rs]; ys = [x["b"] for x in rs]
        mx, my = st.mean(xs), st.mean(ys); vx = sum((x - mx) ** 2 for x in xs)
        a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else 0.0
        for x in rs:
            x["resid"] = (x["b"] - (my - a * mx + a * x["T"])) * 100
            out.append(x)
    return out


def ar1(res):
    pairs = [(res[i]["resid"], res[i + 1]["resid"]) for i in range(len(res) - 1) if res[i]["front"] == res[i + 1]["front"]]
    mx = st.mean(p[0] for p in pairs); my = st.mean(p[1] for p in pairs)
    return sum((x - mx) * (y - my) for x, y in pairs) / sum((x - mx) ** 2 for x, y in pairs)


def main():
    rows = [r for r in csv.DictReader(open(OUT / "hti_front_1600.csv")) if r["f1615"] and r["f1630"]]
    L = [f"# 科指期貨對 ETF 的基差，按期貨取價時刻（自動產生；{rows[0]['date']} 至 {rows[-1]['date']}，{len(rows)} 個交易日）", "",
         "| 期貨取價 | 對 3033：殘差 σ % | φ | |e| ≥ 0.3% 天數 | 對 3067：殘差 σ % | φ | 兩 ETF 殘差相關 | 殘差差值 σ %（ETF 自己的噪音） |",
         "|---|---|---|---|---|---|---|---|"]
    for price, lab in (("mid", "16:00 與 16:15 平均（≈16:08）"), ("f1600", "16:00"), ("f1615", "16:15"), ("f1630", "16:30（≈港交所結算）")):
        r1 = residuals(rows, price, "etf3033"); r2 = residuals(rows, price, "etf3067")
        m2 = {x["date"]: x["resid"] for x in r2}
        common = [(x["resid"], m2[x["date"]]) for x in r1 if x["date"] in m2]
        a1 = st.mean(p[0] for p in common); a2 = st.mean(p[1] for p in common)
        cov = sum((p[0] - a1) * (p[1] - a2) for p in common) / len(common)
        corr = cov / (st.pstdev([p[0] for p in common]) * st.pstdev([p[1] for p in common]))
        s1 = [x["resid"] for x in r1]; s2 = [x["resid"] for x in r2]
        L.append(f"| {lab} | {st.pstdev(s1):.3f} | {ar1(r1):+.2f} | {sum(abs(e) >= 0.3 for e in s1)} | {st.pstdev(s2):.3f} | {ar1(r2):+.2f} | {corr:.2f} | {st.pstdev([p[0] - p[1] for p in common]):.3f} |")
    # 對指數本身（Futu HK.800700 60 分 K 的 16:00 收市；2024-11 起）：指數層面 vs ETF 層面的拆分
    sub = [r for r in rows if r.get("idx1600")]
    if sub:
        L += ["", f"## 對恒生科技指數本身（{sub[0]['date']} 至 {sub[-1]['date']}，{len(sub)} 個交易日，三者同一區間）", "",
              "| 期貨取價 | 期貨對指數：殘差 σ % | φ | 期貨對 3033：殘差 σ % | 期貨對 3067：殘差 σ % |", "|---|---|---|---|---|"]
        for price, lab in (("f1600", "16:00"), ("mid", "16:00 與 16:15 平均"), ("f1630", "16:30")):
            ri = residuals(sub, price, "idx1600"); r1 = residuals(sub, price, "etf3033"); r2 = residuals(sub, price, "etf3067")
            L.append(f"| {lab} | {st.pstdev([x['resid'] for x in ri]):.3f} | {ar1(ri):+.2f} | {st.pstdev([x['resid'] for x in r1]):.3f} | {st.pstdev([x['resid'] for x in r2]):.3f} |")
        for etf, lab in (("etf3033", "3033"), ("etf3067", "3067")):
            ratio = [math.log(float(r[etf]) / float(r["idx1600"])) for r in sub if r[etf]]
            dl = [ratio[i + 1] - ratio[i] for i in range(len(ratio) - 1)]
            L.append(f"- {lab} 對指數的比率日變動 σ {st.pstdev(dl) * 100:.3f}%（ETF 折溢價自己的日噪音；含派息日跳動）")
    n1615 = [float(r["f1615"]) - float(r["f1600"]) for r in rows]; n1630 = [float(r["f1630"]) - float(r["f1600"]) for r in rows]
    spot = st.mean(float(r["f1600"]) for r in rows)
    L += ["", f"- 期貨自己 16:00→16:15 的移動 σ {st.pstdev(n1615):.1f} 點（{st.pstdev(n1615) / spot * 100:.3f}%）、16:00→16:30 σ {st.pstdev(n1630):.1f} 點（{st.pstdev(n1630) / spot * 100:.3f}%）",
          f"- 殘差 σ 對 3033 隨時間差變化的幅度，就是時間差噪音；剩下的底是 ETF 折溢價加真正的基差偏離。"]
    (OUT / "HSTECH_ALIGNED_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
