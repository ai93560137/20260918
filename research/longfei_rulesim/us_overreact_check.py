"""[IDEAS #2000] 美股前一晚大變動後，恒指日市開市跳空會唔會即日回吐（Fung、Mok、Lam 2000；Fung、Lam、Lam 2010）。

數據：恒指 1 分鐘 GCS archive/futu_k_1m/HK.HSI_FRONT（日市 09:15–16:30）；ES 日線 GCS ops/longfei/analyst/data/ES.json（d1）。
美股大變動日＝前一個美股交易日 ES 收市對收市 |報酬| ≥ 1.5%。
策略（逆跳空）：恒指日市 09:15 開市價 vs 昨日日市收市；跳空向上就沽、向下就買，開市入、16:29 收市平；成本每邊 2 點。
對照：其他日子同樣逆跳空。

預先登記（11-07，結果出嚟之前寫，唔再改）：
  成立 ＝ 大變動日 ≥ 12 日、逆跳空每筆平均 ≥ +30 點、t ≥ 1.5、前後兩半平均都 > 0，而且大變動日平均高過其他日子。
  成立 → 登記做 MHI 日市開市研究候選（真倉要使用者批）；唔成立 → 記低。

用法：python3 research/longfei_rulesim/us_overreact_check.py（要 GCS 讀權）
"""
import json
import math
import statistics
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rulesim as rs  # noqa: E402


def main():
    store = rs.Store(True)
    es = store.get("ops/longfei/analyst/data/ES.json")["d1"]
    esd = [r[0] for r in es]
    ret = {esd[i]: es[i][4] / es[i - 1][4] - 1 for i in range(1, len(es))}
    days = sorted(n.rsplit("/", 1)[1][:10] for n in store.names("archive/futu_k_1m/HK.HSI_FRONT/"))
    sess = {}
    for d in days:
        b = rs.hsi_bars(store, d)
        if b and len(b) > 200:
            sess[d] = (b[0][1], b[-1][4])
    rows = []
    hd = sorted(sess)
    for k in range(1, len(hd)):
        d, p = hd[k], hd[k - 1]
        prior_us = [x for x in esd if x < d]
        if not prior_us:
            continue
        r = ret.get(prior_us[-1])
        o, c = sess[d]
        gap = o - sess[p][1]
        if r is None or gap == 0:
            continue
        pnl = -math.copysign(1, gap) * (c - o) - 4
        rows.append({"d": d, "us": r, "gap": gap, "pnl": pnl, "big": abs(r) >= 0.015})

    def st(v):
        if len(v) < 2:
            return {"n": len(v)}
        m = statistics.mean(v)
        sd = statistics.stdev(v)
        return {"n": len(v), "mean": round(m, 1), "t": round(m / (sd / math.sqrt(len(v))), 2) if sd else None,
                "win": round(sum(x > 0 for x in v) / len(v), 2)}
    big = [x for x in rows if x["big"]]
    oth = [x["pnl"] for x in rows if not x["big"]]
    h = len(big) // 2
    res = {"from": hd[0], "to": hd[-1], "big": st([x["pnl"] for x in big]), "other": st(oth),
           "big_h1": st([x["pnl"] for x in big[:h]]), "big_h2": st([x["pnl"] for x in big[h:]]),
           "big_days": [(x["d"], round(x["us"] * 100, 2), x["gap"], round(x["pnl"])) for x in big]}
    b = res["big"]
    res["pass"] = bool(b["n"] >= 12 and b.get("mean", -1) >= 30 and (b.get("t") or 0) >= 1.5
                       and res["big_h1"].get("mean", -1) > 0 and res["big_h2"].get("mean", -1) > 0
                       and b.get("mean", -1) > res["other"].get("mean", 0))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
