"""指數期貨對 ETF 的基差研究（通用版）：科指期貨對 3033／3067、國指期貨對 2828、恒指期貨對 2800。結論在 HSTECH_BASIS.md。

輸入（都在 repo 內）：
  data/hkex_options/futures/<產品>_<年>.csv.gz   港交所每日報告的期貨結算價（16:30；scripts/hkex_option_iv.py fetch --products htif,hhif …）
  data/hkex_options/yahoo/<ETF>.csv              Yahoo 日線（同一腳本 fetch --products yahoo:3033.HK …）
定義：
  b = ln(期貨結算 ÷ ETF 收市)。ETF 與指數之間有固定倍數（3033 約 1/1000）加慢慢漂移的費用與派息，所以每張合約配 b ≈ c + a·T
  （c 吸收倍數，a 是每日持有成本），殘差 e（以 % 計）當作暫時性偏離。T = 距最後交易日的日曆日數（當月倒數第二個營業日）。
  期貨結算是 16:30、ETF 收市是 16:08–16:10 收市競價：殘差裡含這 20 分鐘的時間差噪音（恒指版量過約 0.15%），比較兩隻同指數 ETF 的殘差
  可以分辨「指數層面」還是「ETF 自己的折溢價」。
用法：python3 research/index_arbitrage/etf_basis.py --fut htif --spot 3033.HK [--spot2 3067.HK] [--enter 0.3] [--cost 0.17]
"""
import argparse, csv, glob, gzip, math, statistics as st
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def second_last_bday(y, m):
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    n = 0
    while True:
        if d.weekday() < 5:
            n += 1
            if n == 2:
                return d
        d -= timedelta(days=1)


def load_fut(product):
    fut = defaultdict(dict)
    for p in sorted(glob.glob(str(ROOT / f"data/hkex_options/futures/{product}_*.csv.gz"))):
        for r in csv.DictReader(gzip.open(p, "rt")):
            if r["product"] == product and int(r["settle"]) > 0:
                fut[r["date"]][r["expiry"]] = r
    return fut


def load_spot(ticker):
    return {r["date"]: float(r["close"]) for r in csv.DictReader(open(ROOT / f"data/hkex_options/yahoo/{ticker}.csv")) if r["close"]}


def build(fut, spot):
    dates = sorted(d for d in fut if d in spot)
    last_seen = {}
    for d in dates:
        for e in fut[d]:
            last_seen[e] = d
    rows = []
    for d in dates:
        dd = date.fromisoformat(d)
        ltd = {}
        for e in fut[d]:
            y, m = map(int, e.split("-"))
            ltd[e] = date.fromisoformat(last_seen[e]) if last_seen[e] != dates[-1] else second_last_bday(y, m)
        live = sorted((e for e in fut[d] if ltd[e] >= dd), key=lambda e: e)
        if not live:
            continue
        e1 = live[0]; f = int(fut[d][e1]["settle"])
        rows.append(dict(date=d, front=e1, fut=f, vol=int(fut[d][e1]["vol"]), spot=spot[d], T=(ltd[e1] - dd).days, b=math.log(f / spot[d])))
    return rows


def fit(rows):
    """每張合約 b ≈ c + a·T（最小平方）；殘差以 % 計。"""
    by_c = defaultdict(list)
    for r in rows:
        by_c[r["front"]].append(r)
    out = []
    for c, rs in sorted(by_c.items()):
        xs = [r["T"] for r in rs]; ys = [r["b"] for r in rs]
        mx, my = st.mean(xs), st.mean(ys)
        vx = sum((x - mx) ** 2 for x in xs)
        a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else 0.0
        c0 = my - a * mx
        for r in rs:
            r["resid"] = (r["b"] - (c0 + a * r["T"])) * 100
        res = [r["resid"] for r in rs]
        out.append(dict(contract=c, days=len(rs), carry_ann_pct=round(a * 365 * 100, 2), resid_sd=round(st.pstdev(res), 3) if len(res) > 1 else 0,
                        resid_min=round(min(res), 2), resid_max=round(max(res), 2), vol_med=int(st.median(r["vol"] for r in rs))))
    return by_c, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fut", default="htif"); ap.add_argument("--spot", default="3033.HK"); ap.add_argument("--spot2", default="")
    ap.add_argument("--enter", type=float, default=0.3, help="殘差進場門檻（%）")
    ap.add_argument("--cost", type=float, default=0.17, help="一來一回成本（%）")
    a = ap.parse_args()
    fut = load_fut(a.fut)
    rows = build(fut, load_spot(a.spot))
    by_c, contracts = fit(rows)
    res = [r["resid"] for r in rows]
    sd = st.pstdev(res)
    pairs = [(rows[i]["resid"], rows[i + 1]["resid"]) for i in range(len(rows) - 1) if rows[i]["front"] == rows[i + 1]["front"]]
    mx = st.mean(p[0] for p in pairs); my = st.mean(p[1] for p in pairs)
    phi = sum((x - mx) * (y - my) for x, y in pairs) / sum((x - mx) ** 2 for x, y in pairs)
    tag = f"{a.fut}_{a.spot}"
    L = [f"# {a.fut} 期貨結算對 {a.spot} 收市的基差（自動產生；{rows[0]['date']} 至 {rows[-1]['date']}，{len(rows)} 個交易日）", "",
         "## 每張前月合約", "", "| 合約 | 天數 | 年化持有成本 % | 殘差σ % | 殘差最小 % | 殘差最大 % | 前月日成交中位 |", "|---|---|---|---|---|---|---|"]
    for c in contracts:
        L.append("| " + " | ".join(str(c[k]) for k in c) + " |")
    L += ["", f"- 全部殘差 σ = {sd:.3f}%；|e| > 2σ 的日子 {sum(abs(e) > 2 * sd for e in res)} 天；≥ {a.enter}% 的日子 {sum(e >= a.enter for e in res)}、≤ −{a.enter}% {sum(e <= -a.enter for e in res)}（共 {len(res)} 天）",
          f"- AR(1) φ = {phi:.2f}", f"- 年化持有成本中位 {st.median(c['carry_ann_pct'] for c in contracts):+.2f}%（期貨相對 ETF；含 ETF 費用與派息的影響）"]
    # 模擬
    trades = []
    for c, rs in sorted(by_c.items()):
        i = 0
        while i < len(rs) - 1:
            r = rs[i]
            if r["T"] >= 2 and abs(r["resid"]) >= a.enter:
                sign = 1 if r["resid"] > 0 else -1
                j = i + 1
                while j < len(rs) - 1 and sign * rs[j]["resid"] > 0:
                    j += 1
                x = rs[j]
                trades.append(dict(entry=r["date"], exit=x["date"], hold=j - i, side="沽期買 ETF" if sign > 0 else "買期沽 ETF",
                                   resid_in=round(r["resid"], 2), resid_out=round(x["resid"], 2), net=round(sign * (r["resid"] - x["resid"]) - a.cost, 2)))
                i = j + 1
            else:
                i += 1
    L += ["", f"## 模擬：|殘差| ≥ {a.enter}% 進場、回到 0 或到期出場、成本 {a.cost}%（全樣本斜率，有前視；只能證偽）", ""]
    if trades:
        L += ["| 進場 | 出場 | 持有日 | 方向 | 進場殘差 | 出場殘差 | 淨 % |", "|---|---|---|---|---|---|---|"]
        for t in trades:
            L.append("| " + " | ".join(str(t[k]) for k in t) + " |")
        net = [t["net"] for t in trades]
        L.append(f"\n- {len(trades)} 筆、淨 {sum(net):+.2f}%、賺 {sum(n > 0 for n in net)} 筆、平均持有 {st.mean(t['hold'] for t in trades):.1f} 日")
    else:
        L.append("- 沒有任何一天達到門檻")
    if a.spot2:
        rows2 = build(fut, load_spot(a.spot2)); fit(rows2)
        r2 = {r["date"]: r["resid"] for r in rows2}
        common = [(r["resid"], r2[r["date"]]) for r in rows if r["date"] in r2]
        m1 = st.mean(p[0] for p in common); m2 = st.mean(p[1] for p in common)
        cov = sum((x - m1) * (y - m2) for x, y in common) / len(common)
        corr = cov / (st.pstdev([p[0] for p in common]) * st.pstdev([p[1] for p in common]))
        diff = [x - y for x, y in common]
        L += ["", f"## 對照 {a.spot2}：兩隻 ETF 殘差的相關係數 {corr:.2f}；殘差差值 σ {st.pstdev(diff):.3f}%（這是 ETF 自己的折溢價噪音）",
              f"- 相關係數高 → 偏離在指數層面（含 16:30 對 16:08 的時間差噪音）；低 → 是個別 ETF 的折溢價"]
    with open(OUT / f"etf_basis_{tag}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()})
    (OUT / f"ETF_REPORT_{tag}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
