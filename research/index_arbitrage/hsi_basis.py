"""恒指期貨對現貨的基差研究：基差偏離有沒有值得等的時段？（結論在 HSI_BASIS.md）

輸入（都在 repo 內，不連網）：
  research/index_arbitrage/hsi_front_1600.csv   恒指即月期貨（Futu HK.HSI_FRONT，GCS archive/futu_k_15m 的 15 分 K）每天 16:00／16:15／16:30
                                                  三根 K 的收市 ＋ 恒指收市（canary/data_external/hsi_daily.csv）。2023-09-29 起。
                                                  Futu 序列在最後交易日當天就轉下月；非轉倉日 16:30 收市 ＝ 港交所結算價（已核對）。
  data/hkex_options/futures/hsif_<年>.csv.gz     港交所每日報告的恒指期貨結算價（2025-10-02 起），用來對照「結算價對收市」的噪音
  canary/data_external/hsi_daily.csv

定義：
  基差 B = 前月期貨價 − 恒指收市；T = 距最後交易日的日曆日數（最後交易日 = 當月倒數第二個營業日）
  公允部分：每張合約 B ≈ a·T（通過原點的最小平方；a = 每日持有成本，利息減股息）
  殘差 e = B − a·T，視為「暫時性錯價」
用法：python3 research/index_arbitrage/hsi_basis.py [--price f1600|f1615|f1630] [--enter 40] [--cost 45]
輸出：research/index_arbitrage/REPORT.md、basis_daily.csv、contracts.csv
"""
import argparse, csv, glob, gzip, math, statistics as st
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
# 港交所實際最後交易日與「倒數第二個平日」不同的月份（月底有公眾假期）
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


def front_contract(d):
    ltd = second_last_bday(d.year, d.month)
    if d < ltd:
        return f"{d.year:04d}-{d.month:02d}", ltd
    y, m = (d.year + (d.month == 12), d.month % 12 + 1)
    return f"{y:04d}-{m:02d}", second_last_bday(y, m)


def fit_contracts(rows):
    by_c = defaultdict(list)
    for r in rows:
        by_c[r["front"]].append(r)
    contracts = []
    for c, rs in sorted(by_c.items()):
        fit = [r for r in rs if r["T"] >= 1]
        den = sum(r["T"] ** 2 for r in fit)
        slope = sum(r["basis"] * r["T"] for r in fit) / den if den else 0.0
        for r in rs:
            r["fair"] = slope * r["T"]
            r["resid"] = r["basis"] - r["fair"]
            r["carry_ann"] = (r["basis"] / r["spot"]) * 365 / r["T"] * 100 if r["T"] >= 5 else None
        res = [r["resid"] for r in rs]
        contracts.append(dict(contract=c, days=len(rs), slope_pts_per_day=round(slope, 3),
                              carry_ann_pct=round(slope * 365 / st.mean(r["spot"] for r in rs) * 100, 2),
                              basis_mean=round(st.mean(r["basis"] for r in rs), 1), basis_min=round(min(r["basis"] for r in rs), 1),
                              basis_max=round(max(r["basis"] for r in rs), 1), resid_sd=round(st.pstdev(res), 1),
                              resid_min=round(min(res), 1), resid_max=round(max(res), 1)))
    return by_c, contracts


def oos_residuals(by_c):
    """把 resid 換成樣本外殘差：第 k 天的斜率只用同一張合約第 1..k-1 天（T>=1）估；不足 5 天就用上一張合約的全樣本斜率。"""
    prev = None
    for c, rs in sorted(by_c.items()):
        num = den = 0.0
        for k, r in enumerate(rs):
            if k >= 5 and den > 0:
                slope = num / den
            elif prev is not None:
                slope = prev
            else:
                slope = None
            if slope is None:
                r["resid"] = 0.0; r["fair"] = None
            else:
                r["fair"] = slope * r["T"]; r["resid"] = r["basis"] - r["fair"]
            if r["T"] >= 1:
                num += r["basis"] * r["T"]; den += r["T"] ** 2
        fit = [r for r in rs if r["T"] >= 1]
        d2 = sum(r["T"] ** 2 for r in fit)
        prev = sum(r["basis"] * r["T"] for r in fit) / d2 if d2 else prev


def ar1(rows):
    pairs = [(rows[i]["resid"], rows[i + 1]["resid"]) for i in range(len(rows) - 1) if rows[i]["front"] == rows[i + 1]["front"]]
    mx = st.mean(p[0] for p in pairs); my = st.mean(p[1] for p in pairs)
    phi = sum((x - mx) * (y - my) for x, y in pairs) / sum((x - mx) ** 2 for x, y in pairs)
    return phi, (math.log(0.5) / math.log(phi) if 0 < phi < 1 else float("inf"))


def simulate(by_c, enter, cost):
    trades = []
    for c, rs in sorted(by_c.items()):
        i = 0
        while i < len(rs):
            r = rs[i]
            if r["T"] >= 2 and abs(r["resid"]) >= enter and i < len(rs) - 1:
                sign = 1 if r["resid"] > 0 else -1
                j = i + 1
                while j < len(rs) - 1 and sign * rs[j]["resid"] > 0:
                    j += 1
                x = rs[j]
                pnl = sign * (r["resid"] - x["resid"])
                trades.append(dict(contract=c, side="沽期買現" if sign > 0 else "買期沽現", entry=r["date"], exit=x["date"], hold=j - i,
                                   resid_in=round(r["resid"], 1), resid_out=round(x["resid"], 1),
                                   gross_basis_chg=round(sign * (r["basis"] - x["basis"]), 1), resid_pnl=round(pnl, 1), net=round(pnl - cost, 1)))
                i = j + 1
            else:
                i += 1
    return trades


def write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})


def table(L, rows, keys, head):
    L += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        L.append("| " + " | ".join("" if r[k] is None else str(r[k]) for k in keys) + " |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--price", default="mid", choices=["f1600", "f1615", "f1630", "mid"], help="期貨價：16:00／16:15／16:30 收市，或 mid = 16:00 與 16:15 的平均（近似恒指 16:08–16:10 收市時刻）")
    ap.add_argument("--oos", action="store_true", help="樣本外：公允斜率只用進場日之前的資料估（前 5 天用上一張合約的斜率）")
    ap.add_argument("--enter", type=float, default=40, help="殘差進場門檻（點）")
    ap.add_argument("--cost", type=float, default=45, help="一來一回總成本（指數點，見 HSI_BASIS.md）")
    a = ap.parse_args()
    raw = list(csv.DictReader(open(OUT / "hsi_front_1600.csv")))
    rows = []
    for r in raw:
        if a.price == "mid":
            if not (r["f1600"] and r["f1615"]):
                continue
            f = (float(r["f1600"]) + float(r["f1615"])) / 2
        else:
            if not r[a.price]:
                continue
            f = float(r[a.price])
        d = date.fromisoformat(r["date"]); c, ltd = front_contract(d)
        s = float(r["spot"])
        rows.append(dict(date=r["date"], spot=round(s, 1), front=c, fut=f, T=(ltd - d).days, basis=f - s,
                         noise_1615_1600=(float(r["f1615"]) - float(r["f1600"])) if r["f1615"] else None,
                         noise_1630_1600=(float(r["f1630"]) - float(r["f1600"])) if r["f1630"] else None))
    by_c, contracts = fit_contracts(rows)
    if a.oos:
        oos_residuals(by_c)
    res = [r["resid"] for r in rows if r["T"] >= 1]
    sd = st.pstdev(res); phi, half = ar1(rows)
    n1615 = [r["noise_1615_1600"] for r in rows if r["noise_1615_1600"] is not None]
    n1630 = [r["noise_1630_1600"] for r in rows if r["noise_1630_1600"] is not None]
    season = defaultdict(list)
    for r in rows:
        if r["carry_ann"] is not None:
            season[r["front"][5:]].append(r["carry_ann"])
    trades = simulate(by_c, a.enter, a.cost)
    b = [r["basis"] for r in rows]
    write_csv(OUT / "basis_daily.csv", rows); write_csv(OUT / "contracts.csv", contracts)

    L = [f"# 恒指期貨基差統計（自動產生；期貨價 = {a.price}；{'樣本外斜率' if a.oos else '全樣本斜率'}；{rows[0]['date']} 至 {rows[-1]['date']}，{len(rows)} 個交易日）", "",
         "## 時間戳噪音：同一天不同時刻的期貨價差（點）", "",
         f"- 16:15 − 16:00：σ {st.pstdev(n1615):.1f}、|差| > 40 點的日子 {sum(abs(x) > 40 for x in n1615)}／{len(n1615)}",
         f"- 16:30 − 16:00：σ {st.pstdev(n1630):.1f}、|差| > 40 點的日子 {sum(abs(x) > 40 for x in n1630)}／{len(n1630)}",
         "", "## 每張前月合約（基差 = 期貨 − 恒指收市）", ""]
    table(L, contracts, list(contracts[0].keys()), ["合約", "當前月天數", "斜率 點/日", "年化持有成本 %", "基差均值", "最小", "最大", "殘差σ", "殘差最小", "殘差最大"])
    L += ["", "## 殘差（扣掉每張合約自己的公允斜率後的暫時性偏離）", "",
          f"- 全部殘差 σ = {sd:.1f} 點；|e| > 1σ 的日子 {sum(abs(e) > sd for e in res)} 天、> 2σ {sum(abs(e) > 2 * sd for e in res)} 天、> 3σ {sum(abs(e) > 3 * sd for e in res)} 天（共 {len(res)} 天）",
          f"- AR(1) φ = {phi:.2f} → 半衰期 {half:.1f} 個交易日（φ ≈ 0 表示偏離隔天就消失，分不出是錯價還是噪音）",
          f"- 殘差 ≥ +{a.enter:.0f} 點的日子 {sum(e >= a.enter for e in res)} 天；≤ −{a.enter:.0f} 點 {sum(e <= -a.enter for e in res)} 天",
          "", "## 季節性：前月年化持有成本（基差 ÷ 現貨 × 365 ÷ T，T ≥ 5），按合約月份合併各年", ""]
    L += ["| 合約月 | 天數 | 中位 % | 25% | 75% |", "|---|---|---|---|---|"]
    for m, v in sorted(season.items()):
        q = st.quantiles(v, n=4) if len(v) >= 4 else [min(v), st.median(v), max(v)]
        L.append(f"| {m} | {len(v)} | {st.median(v):.2f} | {q[0]:.2f} | {q[2]:.2f} |")
    L += ["", f"## 模擬：|殘差| ≥ {a.enter:.0f} 點進場，殘差回到 0 或到期出場，成本 {a.cost:.0f} 點", ""]
    if trades:
        table(L, trades, list(trades[0].keys()), ["合約", "方向", "進場", "出場", "持有日", "進場殘差", "出場殘差", "基差變動（毛）", "殘差變動", "淨"])
        net = [t["net"] for t in trades]
        yrs = sorted({t["entry"][:4] for t in trades})
        L += ["", "- 按年：" + "；".join(f"{y} {sum(1 for t in trades if t['entry'][:4] == y)} 筆、淨 {sum(t['net'] for t in trades if t['entry'][:4] == y):.0f} 點" for y in yrs)]
        L += [f"- {len(trades)} 筆；殘差變動合計 {sum(t['resid_pnl'] for t in trades):.0f} 點、淨 {sum(net):.0f} 點；賺錢 {sum(n > 0 for n in net)} 筆；平均持有 {st.mean(t['hold'] for t in trades):.1f} 日；最差 {min(net):.0f} 點"]
    else:
        L += ["- 沒有任何一天達到門檻"]
    L += ["", "## 原始基差分佈（前月，點，未扣公允）", "",
          f"- 均值 {st.mean(b):.1f}、中位 {st.median(b):.1f}、σ {st.pstdev(b):.1f}、最小 {min(b):.1f}、最大 {max(b):.1f}",
          f"- 基差 > +{a.cost:.0f} 點的日子 {sum(x > a.cost for x in b)} 天；< −{a.cost:.0f} 點 {sum(x < -a.cost for x in b)} 天"]
    # 年化：基差 > cost 的日子，持有到期能拿到的毛利（= 基差，未計股息與利息）
    pos = [r for r in rows if r["basis"] > a.cost and r["T"] >= 2]
    if pos:
        L.append(f"- 這 {len(pos)} 天若沽期買現持有到期：平均毛利 {st.mean(r['basis'] for r in pos):.0f} 點、平均持有 {st.mean(r['T'] for r in pos):.0f} 個日曆日；年份分佈 " +
                 ", ".join(f"{y}:{n}" for y, n in sorted(defaultdict(int, {y: sum(1 for r in pos if r['date'][:4] == y) for y in {r['date'][:4] for r in pos}}).items())))
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
