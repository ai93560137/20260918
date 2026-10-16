"""槓桿／反向 ETF 收市再平衡：恒指期貨收市前有沒有可預測的順勢推動？（結論在 LEVERAGED_ETF_CLOSE.md）

機制：L 倍槓桿 ETF 每天收市要把曝險調回 L × 淨值。當日指數升 r，正向 2 倍要再買 2r × 淨值的期貨，反向 2 倍也要買（回補）；
跌就一起賣。所以理論上「當日走勢」會在收市前最後 15 至 30 分鐘被同方向推一下，第二天開市回吐。

輸入：research/index_arbitrage/hsi_front_close_bars.csv（恒指即月期貨 15 分 K 的開市價、12:00、15:00、15:30、15:45、16:00、16:15、16:30 收市、
      翌日 03:00 夜市收市與各段成交量；來自 GCS archive/futu_k_15m/HK.HSI_FRONT，2023-09-29 起）
用法：python3 research/index_arbitrage/close_rebalance.py [--big 1.0] [--cost 4]
輸出：research/index_arbitrage/CLOSE_REPORT.md
"""
import argparse, csv, math, statistics as st
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent
COLS = ("open0930", "c1200", "c1500", "c1530", "c1545", "c1600", "c1615", "c1630", "night_close")


def corr_beta(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
    vx, vy = st.pvariance(xs), st.pvariance(ys)
    return (cov / math.sqrt(vx * vy) if vx and vy else 0.0), (cov / vx if vx else 0.0)


def tstat(xs):
    return st.mean(xs) / (st.stdev(xs) / math.sqrt(len(xs))) if len(xs) > 2 and st.stdev(xs) else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--big", type=float, default=1.0, help="「大日」門檻：當日到 15:45 的漲跌幅（%）")
    ap.add_argument("--cost", type=float, default=4.0, help="期貨一來一回成本（點）")
    a = ap.parse_args()
    rows = []
    prev = None
    for r in csv.DictReader(open(OUT / "hsi_front_close_bars.csv")):
        d = {k: (float(r[k]) if r.get(k) not in (None, "") else None) for k in COLS}
        d["date"] = r["date"]; d["prev_close"] = prev
        d["vol"] = {k: (int(r[k]) if r.get(k) else None) for k in ("day_vol", "vol_1545", "vol_1600", "vol_1615", "vol_1630")}
        rows.append(d); prev = d["c1630"]
    L = [f"# 恒指期貨收市前順勢效應（自動產生；{rows[0]['date']} 至 {rows[-1]['date']}，{len(rows)} 個交易日）", ""]

    # 一、相關性表：當日走勢（基準→from）對後段走勢（from→to）
    L += ["## 一、當日走勢 vs 收市前後各段走勢", "",
          "x = 基準到 from 的點數（當日走勢）；y = from 到 to 的點數。再平衡假說預測 corr > 0、順勢平均 > 0。", "",
          "| 基準 | 段 | n | corr | β（每 100 點） | 同向比例 | 大日 n | 大日順勢平均（點） | 大日同向比例 | 大日 t |", "|---|---|---|---|---|---|---|---|---|---|"]
    segs = [("c1530", "c1545"), ("c1545", "c1600"), ("c1600", "c1615"), ("c1615", "c1630"), ("c1545", "c1630"), ("c1600", "c1630"), ("c1630", "night_close")]
    for base_name, base in (("09:30 開市", "open0930"), ("前日 16:30", "prev_close")):
        for f, t in segs:
            sel = [r for r in rows if r[base] is not None and r[f] is not None and r[t] is not None]
            xs = [r[f] - r[base] for r in sel]; ys = [r[t] - r[f] for r in sel]
            c, b = corr_beta(xs, ys)
            same = sum(1 for x, y in zip(xs, ys) if x * y > 0) / len(xs)
            big = [(x, y) for r, x, y in zip(sel, xs, ys) if abs(x) / r[base] * 100 >= a.big]
            follow = [math.copysign(1, x) * y for x, y in big]
            L.append(f"| {base_name} | {f[1:3]}:{f[3:]}→{t.replace('c', '')[:2]}:{t.replace('c', '')[2:4] if t != 'night_close' else '夜市收'} | {len(xs)} | {c:+.3f} | {b * 100:+.1f} | {same:.2f} | {len(big)} | "
                     f"{st.mean(follow) if follow else 0:+.1f} | {sum(1 for v in follow if v > 0) / len(follow) if follow else 0:.2f} | {tstat(follow) if len(follow) > 2 else 0:+.2f} |")
    # 二、簡單策略：15:45 當日 |漲跌| ≥ big% 就順勢，16:30 平倉
    L += ["", f"## 二、策略：15:45 當日漲跌幅 ≥ {a.big:.1f}% 就順勢，16:30 平倉，成本 {a.cost:.0f} 點", ""]
    by_year = defaultdict(list)
    for r in rows:
        if r["open0930"] and r["c1545"] and r["c1630"]:
            x = r["c1545"] - r["open0930"]
            if abs(x) / r["open0930"] * 100 >= a.big:
                by_year[r["date"][:4]].append(math.copysign(1, x) * (r["c1630"] - r["c1545"]) - a.cost)
    allp = [p for v in by_year.values() for p in v]
    L += ["| 年 | 筆數 | 淨點數 | 平均 | 勝率 | t |", "|---|---|---|---|---|---|"]
    for y, v in sorted(by_year.items()):
        L.append(f"| {y} | {len(v)} | {sum(v):+.0f} | {st.mean(v):+.1f} | {sum(1 for p in v if p > 0) / len(v):.2f} | {tstat(v):+.2f} |")
    if allp:
        L.append(f"| 合計 | {len(allp)} | {sum(allp):+.0f} | {st.mean(allp):+.1f} | {sum(1 for p in allp if p > 0) / len(allp):.2f} | {tstat(allp):+.2f} |")
    # 反向：16:30 順勢持有到夜市收市／翌日開市回吐？
    L += ["", "## 三、收市後有沒有回吐（16:30 → 夜市收市；大日）", ""]
    for base_name, base in (("09:30 開市", "open0930"), ("前日 16:30", "prev_close")):
        sel = [r for r in rows if r[base] and r["c1630"] and r["night_close"]]
        big = [(r["c1630"] - r[base], r["night_close"] - r["c1630"]) for r in sel if abs(r["c1630"] - r[base]) / r[base] * 100 >= a.big]
        follow = [math.copysign(1, x) * y for x, y in big]
        L.append(f"- 基準 {base_name}：大日 {len(big)} 天，夜市順勢平均 {st.mean(follow):+.1f} 點、同向比例 {sum(1 for v in follow if v > 0) / len(follow):.2f}、t {tstat(follow):+.2f}")
    # 四、成交量：收市前各段佔全日比例，大日 vs 平日
    L += ["", "## 四、收市前成交量佔全日比例（再平衡若顯著，大日最後 30 分鐘成交佔比應明顯高於平日）", "", "| 段 | 平日中位 % | 大日中位 % |", "|---|---|---|"]
    for k, lab in (("vol_1545", "15:30–15:45"), ("vol_1600", "15:45–16:00"), ("vol_1615", "16:00–16:15"), ("vol_1630", "16:15–16:30")):
        normal, big = [], []
        for r in rows:
            if r["vol"][k] and r["vol"]["day_vol"] and r["open0930"] and r["c1545"]:
                share = r["vol"][k] / r["vol"]["day_vol"] * 100
                (big if abs(r["c1545"] - r["open0930"]) / r["open0930"] * 100 >= a.big else normal).append(share)
        L.append(f"| {lab} | {st.median(normal):.1f} | {st.median(big):.1f} |")
    (OUT / "CLOSE_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
