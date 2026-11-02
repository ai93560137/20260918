"""[IDEAS #212] 921 止蝕止賺同比例放闊（總指揮 11-02 加：「止蝕止賺同比例放闊（例如 1.5×）」）。
樣本：921 決策日誌全部 OPEN_LONG／OPEN_SHORT（同 #211 樣本 B，xau/decisions，經紀 M1＋Dukascopy 補缺）；
下一分鐘開盤入，SL／TP 距離（由入場價計）× k，k ∈ {1.0（現行）, 1.25, 1.5（主判）, 2.0}；同一分鐘都掂當止蝕、24 小時到鐘市價走、
每張扣 0.5 美元；R 用放闊後嘅風險計（按風險計手數＝放闊後手數自動細，風險金額唔變）。每個決定獨立計（唔理同時持倉、唔計 AI 之後改 SL）。
判（預先登記）：見 IDEAS #212。用法：python3 research/strategy_search/widen_921.py → WIDEN_921.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_921 as F  # noqa: E402

KS = (1.0, 1.25, 1.5, 2.0)
FWD_TS = int(dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.timezone.utc).timestamp())   # 前向影子由呢刻起（#212 判完之後）


def replay_k(m1, decs, k):
    t, o, h, l = m1["t"], m1["o"], m1["h"], m1["l"]
    out = []
    for ts, s, sl0, tp0, _ in decs:
        a = int(np.searchsorted(t, ts, side="right"))
        if a >= len(t) or t[a] - ts > 600:
            continue
        px = o[a]; d0 = (px - sl0) * s; g0 = (tp0 - px) * s
        if d0 <= 0 or g0 <= 0:
            continue
        d = k * d0; sl = px - s * d; tp = px + s * k * g0
        ex, how = None, None
        for j in range(a, len(t)):
            if t[j] - t[a] >= 86400:
                ex, how = o[j], "時間"; break
            if (l[j] <= sl) if s > 0 else (h[j] >= sl):
                ex, how = sl, "止蝕"; break
            if (h[j] >= tp) if s > 0 else (l[j] <= tp):
                ex, how = tp, "止賺"; break
        if ex is None:
            continue
        out.append((int(t[a]), s, float((s * (ex - px) - F.COST) / d), how))
    return out


def main():
    g = F.gb.Gcs()
    decs = F.load_decisions(g)
    m1 = F.EF6.broker_bars(int(decs[0][0]) - 86400)
    m1, nd = F.merge_duka(g, m1, dt.datetime.fromtimestamp(decs[0][0] - 86400, dt.timezone.utc).date().isoformat())
    mid = decs[len(decs) // 2][0]
    out = ["# 921 止蝕止賺同比例放闊（IDEAS #212）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；決策 OPEN {len(decs)} 個（經紀 M1，缺嘅 {nd} 分鐘用 Dukascopy 補）；"
           f"前半／後半以 {dt.datetime.fromtimestamp(mid, dt.timezone.utc):%m-%d %H:%M} UTC 分", "",
           "| k | 全部 | 前半 | 後半 | 止蝕／止賺／到鐘 | 做多 | 做空 |", "|---|---|---|---|---|---|---|"]
    res, fw = {}, {}
    for k in KS:
        tr = replay_k(m1, decs, k)
        s = F.summ([x[2] for x in tr]); h1 = F.summ([x[2] for x in tr if x[0] < mid]); h2 = F.summ([x[2] for x in tr if x[0] >= mid])
        res[k] = (s, h1, h2)
        fw[k] = F.summ([x[2] for x in tr if x[0] >= FWD_TS])
        hw = {w: sum(1 for x in tr if x[3] == w) for w in ("止蝕", "止賺", "時間")}
        out.append(f"| {k:g}× | {F.fmt(s)} | {F.fmt(h1)} | {F.fmt(h2)} | {hw['止蝕']}／{hw['止賺']}／{hw['時間']} | "
                   f"{F.fmt(F.summ([x[2] for x in tr if x[1] > 0]))} | {F.fmt(F.summ([x[2] for x in tr if x[1] < 0]))} |")
        print(k, F.fmt(s), flush=True)
    out += ["", f"## 前向影子（11-02 09:00 UTC 之後嘅新決定；目標 30 張）", "",
            *[f"- {k:g}×：{F.fmt(fw[k])}" for k in KS],
            "- 手數換算（風險金額唔變）：1.5× 手數＝現行手數 ÷ 1.5，向下取到 0.01、夾 921 上限 0.05、最少 0.01（0.01 嗰張放闊後風險會大 1.5 倍）",
            f"- 進度 {fw[1.0]['n']}／30；夠 30 張時 1.5× 平均 R 要高過 1.0× ≥ 0.10 先提案" + ("（**已夠，照判**）" if fw[1.0]["n"] >= 30 else "")]
    b, w = res[1.0], res[1.5]
    ok = {"①平均R +0.10": w[0]["avg"] - b[0]["avg"] >= 0.10, "②PF≥1.1": w[0]["pf"] >= 1.1,
          "③前後半都改善": w[1]["avg"] > b[1]["avg"] and w[2]["avg"] > b[2]["avg"], "④ΣR 改善": w[0]["sum"] > b[0]["sum"]}
    out += ["", "## 判（預先登記 IDEAS #212；主判 1.5×，其他 k 只作描述）", "",
            f"- 1.5× 對 1.0×：平均 R {w[0]['avg'] - b[0]['avg']:+.3f}；"
            + ("✅ 達標 → 提案：先前向影子（921 新單按 1.5× 重播並列）30 張再決定" if all(ok.values()) else "❌ 唔達：" + "、".join(x for x, v in ok.items() if not v)),
            "- 樣本只得兩星期、同一段市況（金價由高位回落）；AI 之後收緊 SL 冇計；只係提案，改 921 要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "WIDEN_921.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
