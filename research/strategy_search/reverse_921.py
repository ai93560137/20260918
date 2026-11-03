"""[IDEAS #225] 921 反向（使用者 11-03 喺總指揮：「根據921做一個完全相反嘅策略，用真倉；921照舊影子測試」）。
兩個計法：
  M 鏡像真倉：921 真倉成交簿 41 張（xau/book_seed.json＋xau/state.json book），反向＝同一入場／出場時間反方向。
    921 成交價已經包咗佢嘅點差；反向要再俾一次 → 反向每盎司損益＝−(921 每盎司淨損益) − c（c＝反向來回成本）。
    921 每盎司淨損益 = side×(exit_est − entry)。R 用兩種單位：921 嘅 R（÷921 初始止蝕距離）同反向自己嘅 R（÷921 止賺距離＝反向止蝕距離；冇 TP 記錄就唔計）。
  D 決策重播：921 決策日誌 OPEN（final＝OPEN_*）共 ~75 個；反向＝相反方向、SL＝921 TP、TP＝921 SL，下一分鐘開盤入、24h、同分鐘當止蝕。
    兩套價位：D1 AI 原值（放闊前）；D2 實際用嘅（R367 之後係 1.5× 放闊後）。R＝反向止蝕距離。
成本：c＝0.5（同其他回測）同 c＝1.0（點差＋滑價保守）；另列 921 自己同一引擎嘅結果做對照（顯示 −0.016R 係已扣 0.5）。
判（預先登記，主判 D2 c＝1.0 同 M c＝1.0）：反向值得上真倉試＝兩個計法平均 R 都 > 0、PF ≥ 1.1、前後半都 > 0。
唔達＝數據唔支持（使用者可以照樣決定試，但要知道期望係負）。
真倉試行嘅停條件（預先登記，唔理回測）：累計 ≤ −5R、連蝕 ≥ 6、滿 15 張 PF < 0.8 → 建議停；滿 30 張平均 R ≥ +0.10 先考慮加手數。
用法：python3 research/strategy_search/reverse_921.py → REVERSE_921.md
"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_921 as F9  # noqa: E402


def live_rows(g):
    seed = [x for x in (g.read_json("xau/book_seed.json") or []) if isinstance(x, dict) and x.get("closed_ts")]
    st = g.read_json("xau/state.json") or {}
    last = max(x["closed_ts"] for x in seed)
    rows = seed + [x for x in (st.get("book") or []) if (x.get("closed_ts") or 0) > last]
    return sorted([r for r in rows if r.get("entry") and r.get("exit_est") and r.get("stop0")], key=lambda r: r["opened_ts"])


def decisions(g):
    out = []
    for nm in sorted(g.list("xau/decisions/")):
        for ln in (g.read_text(nm) or "").splitlines():
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            for x in (o if isinstance(o, list) else [o]):
                if x.get("kind") == "decide" and x.get("final") in ("OPEN_LONG", "OPEN_SHORT") and x.get("stop") and x.get("target"):
                    w = x.get("widen") or {}
                    orig = (w.get("stop"), w.get("target")) if w.get("stop") else (x["stop"], x["target"])
                    out.append(dict(ts=float(x["ts"]), s=1 if x["final"] == "OPEN_LONG" else -1,
                                    orig=tuple(map(float, orig)), used=(float(x["stop"]), float(x["target"]))))
    return sorted(out, key=lambda d: d["ts"])


def replay(m1, ents, cost):
    """ents: [(ts, side, sl, tp)] → [(t_entry, R)]。"""
    t, o, h, l = m1["t"], m1["o"], m1["h"], m1["l"]
    out = []
    for ts, s, sl, tp in ents:
        a = int(np.searchsorted(t, ts, side="right"))
        if a >= len(t) or t[a] - ts > 600:
            continue
        px = o[a]; d = (px - sl) * s
        if d <= 0 or (tp - px) * s <= 0:
            continue
        ex = None
        for j in range(a, len(t)):
            if t[j] - t[a] >= 86400:
                ex = o[j]; break
            if (l[j] <= sl) if s > 0 else (h[j] >= sl):
                ex = sl; break
            if (h[j] >= tp) if s > 0 else (l[j] <= tp):
                ex = tp; break
        if ex is not None:
            out.append((int(t[a]), float((s * (ex - px) - cost) / d)))
    return out


def summ_h(v):
    s = F9.summ([x[1] for x in v])
    mid = v[len(v) // 2][0] if v else 0
    return s, F9.summ([x[1] for x in v if x[0] < mid]), F9.summ([x[1] for x in v if x[0] >= mid])


def ok(s, h1, h2):
    return s["n"] > 0 and s["avg"] > 0 and s["pf"] >= 1.1 and h1["avg"] > 0 and h2["avg"] > 0


def main():
    g = F9.gb.Gcs()
    out = ["# 921 反向（IDEAS #225）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC", ""]
    # M 鏡像
    rows = live_rows(g)
    out += ["## M 鏡像 921 真倉（同時入、同時出、反方向）", "",
            f"- 921 真倉 {len(rows)} 張（{dt.datetime.fromtimestamp(rows[0]['opened_ts'], dt.timezone.utc):%m-%d} → {dt.datetime.fromtimestamp(rows[-1]['opened_ts'], dt.timezone.utc):%m-%d}）；"
            "921 成交價已含佢自己嘅點差，反向再扣 c", "",
            "| 項目 | 921 R 單位 | 每盎司（美元／0.01 手） |", "|---|---|---|"]
    net = [r["side"] * (r["exit_est"] - r["entry"]) for r in rows]
    risk = [abs(r["entry"] - r["stop0"]) for r in rows]
    out.append(f"| 921 自己（已扣佢嘅成本） | 平均 {np.mean([n / k for n, k in zip(net, risk)]):+.3f}R | 平均 {np.mean(net):+.2f}、Σ {sum(net):+.1f} |")
    res = {}
    for c in (0.5, 1.0):
        rv = [(int(r["opened_ts"]), (-n - c) / k) for r, n, k in zip(rows, net, risk)]
        s, h1, h2 = summ_h(rv)
        res[("M", c)] = (s, h1, h2)
        out.append(f"| 反向 c={c} | {F9.fmt(s)}；前半 {h1['avg']:+.3f}、後半 {h2['avg']:+.3f} | 平均 {np.mean([-n - c for n in net]):+.2f}、Σ {sum(-n - c for n in net):+.1f} |")
    out.append("")
    # D 決策重播
    decs = decisions(g)
    m1 = F9.EF6.broker_bars(int(decs[0]["ts"]) - 86400)
    m1, _ = F9.merge_duka(g, m1, dt.datetime.fromtimestamp(decs[0]["ts"] - 86400, dt.timezone.utc).date().isoformat())
    out += ["## D 決策重播（反向 SL＝921 TP、TP＝921 SL，24h）", "",
            f"- 921 OPEN 決定 {len(decs)} 個；R＝反向自己嘅止蝕距離（＝921 止賺距離）", "",
            "| 價位 | 成本 | 921 自己（同引擎） | 反向 | 前半／後半 |", "|---|---|---|---|---|"]
    for key, lab in (("orig", "D1 AI 原值"), ("used", "D2 實際（R367 後放闊）")):
        for c in (0.5, 1.0):
            own = replay(m1, [(d["ts"], d["s"], d[key][0], d[key][1]) for d in decs], c)
            rv = replay(m1, [(d["ts"], -d["s"], d[key][1], d[key][0]) for d in decs], c)
            s, h1, h2 = summ_h(rv)
            res[(key, c)] = (s, h1, h2)
            out.append(f"| {lab} | {c} | {F9.fmt(F9.summ([x[1] for x in own]))} | {F9.fmt(s)} | {h1['avg']:+.3f}／{h2['avg']:+.3f} |")
            print(lab, c, F9.fmt(s), flush=True)
    m_ok, d_ok = ok(*res[("M", 1.0)]), ok(*res[("used", 1.0)])
    out += ["", "## 判（預先登記：M c=1.0 同 D2 c=1.0 都要 平均 > 0、PF ≥ 1.1、前後半 > 0）", "",
            f"- M 鏡像：{'✅' if m_ok else '❌'}；D2 重播：{'✅' if d_ok else '❌'} → "
            + ("✅ 數據支持試真倉" if m_ok and d_ok else "❌ 數據唔支持（反向期望扣完兩次成本係負或者唔穩）；使用者仍可決定細手數試，停條件照下面"),
            "- 停條件（真倉試行，預先登記）：累計 ≤ −5R、連蝕 ≥ 6、滿 15 張 PF < 0.8 → 建議停；滿 30 張平均 ≥ +0.10R 先考慮加手數。",
            "- 點解要扣兩次：921 成交已經付咗一次點差／滑價；反向係另一張單，再付一次。所以 921 打和（扣成本後 ≈ 0）時，反向 ≈ −1 次成本。", ""]
    open(os.path.join(HERE, "REVERSE_921.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
