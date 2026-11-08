"""[IDEAS #1004] rev15 E6S4 MT5 未用過嘅兩段：2022-08-03→2022-12-31 同 2026-01-01→2026-07-23（#159 擬合段之前）。
規格、成功標準以 IDEAS #1004 預先登記為準（跑之前 commit）。兩段分開載入、分開模擬（唔會跨段計出場），之後合併判斷。
用法：python3 research/student_offline/rev15_history_1004.py → research/student_offline/REV15_HISTORY_1004.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = [sys.argv[0], "--src", "mt5"]
sys.path.insert(0, HERE)
import rev15_history as rh   # noqa: E402
fr = rh.fr

SEGS = (("2022-08-03", "2022-12-31"), ("2026-01-01", "2026-07-23"))


def seg_run(a, b):
    rh.A, rh.B, rh.CACHE = a, b, f"/tmp/rev15_history_mt5_{a}_{b}.npz"
    d = rh.load()
    t0, t1 = fr.ts_of(a), fr.ts_of(b) + 86400 - 2 * 86400      # 最後兩日唔出新訊號（未完單唔計，免得截斷偏差）
    rn, ts, mats = rh.run(d, rh.NEW, t0, t1)
    rc = fr.simulate(mats, rh.CUR["E"], rh.CUR["Z"], rh.CUR["S"], rh.CUR["RT"])
    return rn, rc, ts, len(d["t"])


def main():
    out = ["# rev15 E6S4 MT5 未用過兩段（IDEAS #1004）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；券商 MT5 M1（UltimaMarkets）；計法同 #1001／#1002（E6 Z2 S4 1R 對 E4 Z2 S6 2R，每張扣 0.5 美元）", "",
           "| 段 | M1 根數 | 新 E6S4 | 現行 E4S6 2R |", "|---|---|---|---|"]
    alln, allc, months = [], [], {}
    for a, b in SEGS:
        rn, rc, ts, nb = seg_run(a, b)
        out.append(f"| {a}→{b} | {nb:,} | {fr.fmt(fr.stats(rn))} | {fr.fmt(fr.stats(rc))} |")
        alln.append(rn); allc.append(rc)
        for x, r in zip(ts, rn):
            months.setdefault(dt.datetime.fromtimestamp(int(x), dt.timezone.utc).strftime("%Y-%m"), []).append(r)
    rn, rc = np.concatenate(alln), np.concatenate(allc)
    sn, sc = fr.stats(rn), fr.stats(rc)
    ms = {k: fr.stats(np.array(v)) for k, v in sorted(months.items())}
    pos = sum(1 for v in ms.values() if v["n"] and v["avg"] > 0)
    mdd, trips = rh.dd_stats(rn)
    out += [f"| **合計** | — | {fr.fmt(sn)} | {fr.fmt(sc)} |", "", "## 每月（新結構）", ""] + [f"- {k}：{fr.fmt(v)}" for k, v in ms.items()]
    r_all = rn[~np.isnan(rn)]
    if len(r_all):
        out += ["", f"- 勝率 {(r_all > 0).mean():.0%}；最大 R 回撤 {mdd:.1f}R；933 停線（−8R／10R）觸發 {trips} 次；打和總成本約 {0.5 + sn['avg'] * 4:.2f} 美元"]
    ok = {"①合計≥+0.10R且PF≥1.15": sn["n"] > 0 and sn["avg"] >= 0.10 and sn["pf"] >= 1.15,
          "②月份≥60%正數": len(ms) > 0 and pos / len(ms) >= 0.6,
          "③高過現行≥0.10R": sn["n"] > 0 and sc["n"] > 0 and sn["avg"] - sc["avg"] >= 0.10}
    out += ["", "## 判（預先登記 IDEAS #1004）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            f"- 月份正數 {pos}／{len(ms)}",
            "- " + ("✅ 達標：同 #1001 一齊，支持 933 重新提上實倉（仍要使用者決定；#1002 2023–2025 未過要一齊睇）" if all(ok.values())
                    else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；933 繼續延遲，唔准改參數再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "REV15_HISTORY_1004.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
