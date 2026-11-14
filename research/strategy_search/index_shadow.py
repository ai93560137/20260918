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
    # [IDEAS #1444] 天覆組合 v1：黃金 #1268 雙向（Yahoo GC=F 期貨當代理）＋上面嘅恒指、標普、白銀；每張 1R 相加
    try:
        import multi_1422 as MU
        dg = FY.fetch("GC=F"); gt = MU.run(dg, 0.0005)["#1422"]; gf = [x for x in gt if x[0] >= t0]; go = [x for x in gt if x[0] < t0]
        L.append(f"| 黃金期貨 GC=F（#1268 雙向；組合部件） | {f(dg['t'][-1])} | {len(gf)} | {sum(x[2] for x in gf):+.2f} | {g(gf[-1] if gf else None)} | {g(go[-1] if go else None)} |")
        tot = []
        for title, name, cost, _ in (IX.MKTS[0], IX.MKTS[2]):
            tot += [x for x in IX.sim(IX.load(name), IX.CFG[0], cost)[0] if x[0] >= t0]
        tot += fw + gf
        L.append(f"| **天覆組合 v1（#1444：黃金＋白銀＋標普＋恒指）** | — | {len(tot)} | {sum(x[2] for x in tot):+.2f} | — | — |")
        # [IDEAS #1446] 同一個組合，但金絲雀亮燈（紅／深紅／黃×2）時唔開新倉
        import canary_1446 as CN
        days, rows = CN.lights(); tg = CN.tag(tot, days, rows); kept = [x for x in tg if not (x[3] or x[4] or x[5])]
        L.append(f"| **天覆組合 v1＋金絲雀過濾（#1446：亮燈唔開新倉）** | 燈色到 {f(int(days[-1]) * 86400)} | {len(kept)} | {sum(x[2] for x in kept):+.2f} | 亮燈而冇開 {len(tg) - len(kept)} 張 | — |")
    except Exception as exc:  # noqa: BLE001
        L.append(f"| 天覆組合 v1（#1444） | 計唔到（{type(exc).__name__}） | — | — | — | — |")
    L.append("")
    open(os.path.join(HERE, "INDEX_SHADOW.md"), "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
    try:                                   # 月尾股債再平衡影子（#1481 亞洲＋美歐對照）：每月完結後入賬，順手一齊更新
        import merebal_shadow
        merebal_shadow.main()
    except Exception as exc:  # noqa: BLE001
        print(f"merebal_shadow 失敗：{exc}")
