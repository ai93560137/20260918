"""[IDEAS #1427] 影子前向：#1268 事件版（雙向）喺恒指／標普（合格市場）同納指（參考）——只計入場日 ≥ START 嘅單；只係紙上，唔落單。
數據：GCS longfei/daily/（要龍飛陣嘅 daily_archive 更新先有新日子）。用法：python3 research/strategy_search/index_shadow.py → INDEX_SHADOW.md"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import index_1427 as IX  # noqa: E402

START = "2026-11-12"


def main():
    t0 = IX.OG.ts(START); f = lambda t: dt.datetime.fromtimestamp(int(t), dt.timezone.utc).strftime("%Y-%m-%d")  # noqa: E731
    L = ["# 影子前向：#1427（#1268 事件版，雙向）恒指／標普／納指；#1442 白銀只做多", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；由 {START} 起計；每張 1R；唔落單。恒指、標普係合格市場；納指只作參考（回測做空腳唔過）", "",
         "| 市場 | 日線到 | 前向張數 | ΣR | 最近一張（入場日／方向／R，未平用最新收市計） | 起計日前最後一張（唔計分） |", "|---|---|---|---|---|---|"]
    for title, name, cost, _ in IX.MKTS[:3]:
        d = IX.load(name); tr, _ = IX.sim(d, IX.CFG[0], cost); fw = [x for x in tr if x[0] >= t0]; old = [x for x in tr if x[0] < t0]
        g = lambda x: f"{f(x[0])}／{'多' if x[1] > 0 else '空'}／{x[2]:+.2f}R" if x else "—"  # noqa: E731
        L.append(f"| {title} | {f(d['t'][-1])} | {len(fw)} | {sum(x[2] for x in fw):+.2f} | {g(fw[-1] if fw else None)} | {g(old[-1] if old else None)} |")
    # [IDEAS #1442] 白銀只做多：#1285（單日升 ≥ 1.5×ATR，收市 > SMA200 先做）；數據即時由 Yahoo SI=F 攞（攞唔到就跳過）
    try:
        import fetch_yahoo_daily as FY
        d = FY.fetch("SI=F")
        tr, _ = IX.sim(d, IX.CFG[2], 0.0012, long_only=True); fw = [x for x in tr if x[0] >= t0]; old = [x for x in tr if x[0] < t0]
        L.append(f"| 白銀期貨 SI=F（#1442：#1285 只做多） | {f(d['t'][-1])} | {len(fw)} | {sum(x[2] for x in fw):+.2f} | {g(fw[-1] if fw else None)} | {g(old[-1] if old else None)} |")
    except Exception as exc:  # noqa: BLE001
        L.append(f"| 白銀期貨 SI=F（#1442） | 攞唔到數據（{type(exc).__name__}） | — | — | — | — |")
    L.append("")
    open(os.path.join(HERE, "INDEX_SHADOW.md"), "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
