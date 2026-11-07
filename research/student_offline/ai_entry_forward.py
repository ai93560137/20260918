"""[IDEAS #1003] AI 揀入場 影子前向：讀 GCS xau/sig/aientry/log/<日>.jsonl（服務記錄嘅 AI 計劃），用券商 M1（xau/sig/bars/）計成績，
同一批 rev15 出區嘅 E6S4（933 方法）並排。判斷以 IDEAS #1003 預先登記為準。唔落單、唔寫 GCS。
成交規則（兩邊一樣，同 fit_rules／signals.evaluate）：出區後 TTL 分鐘內價掂入場（±SIG_FILL_TOL）先成交，成交價＝入場價或者更好嘅開市價；
成交嗰根起計 SL／TP，同一根都掂當 SL；24 小時未完唔計；R＝(方向×(出場−成交) − 成本) ／ 止蝕距離（AI：入場→SL；E6S4：4 美元）。
用法：python3 research/student_offline/ai_entry_forward.py [--start 2026-11-09] → research/student_offline/AI_ENTRY_FORWARD.md"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e6s4_forward as ef   # noqa: E402
import fit_rules as fr      # noqa: E402

START = "2026-11-07"
TARGET_N = 30
COST, TOL, TTL, HORIZON = fr.COST, fr.TOL, fr.TTL, fr.HORIZON * 60


def sim(d, ts, side, entry, sl, tp, lo=None, hi=None):
    """回傳 R 或 None（未成交／未完）。lo／hi＝入場區（E6S4）；冇就用 entry 單點。"""
    t, o, h, l = d["t"], d["o"], d["h"], d["l"]
    sgn = 1 if side == "BUY" else -1
    lo = entry if lo is None else lo; hi = entry if hi is None else hi
    a = int(np.searchsorted(t, ts))           # 計劃時間之後第一根（ts＝出區分鐘收市＋60）
    fill = fi = None
    for j in range(a, len(t)):
        if t[j] - ts > TTL:
            break
        if l[j] <= hi + TOL and h[j] >= lo - TOL:
            near = hi if sgn > 0 else lo
            fill = min(o[j], max(near, l[j])) if sgn > 0 else max(o[j], min(near, h[j]))
            fi = j
            break
    if fi is None:
        return None
    risk = abs(fill - sl) if lo == hi else abs((lo + hi) / 2 - sl)
    for j in range(fi, len(t)):
        if t[j] - t[fi] > HORIZON:
            return None
        if (l[j] <= sl) if sgn > 0 else (h[j] >= sl):
            return (sgn * (sl - fill) - COST) / risk
        if (h[j] >= tp) if sgn > 0 else (l[j] <= tp):
            return (sgn * (tp - fill) - COST) / risk
    return None


def load_plans(start_ts):
    sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
    import gb_rulesim as gb   # noqa: E402
    g = gb.Gcs()
    out = []
    for nm in sorted(g.list("xau/sig/aientry/log/")):
        for ln in (g.read_text(nm) or "").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and float(r.get("ts") or 0) >= start_ts:
                out.append(r)
    return sorted(out, key=lambda r: r["ts"])


def main():
    start = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else START
    t0 = fr.ts_of(start)
    plans = load_plans(t0)
    out = ["# IDEAS #1003 AI 揀入場 影子前向（券商 M1）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；由 {start} 起；AI 問咗 {len(plans)} 次"]
    if not plans:
        out.append("- 未有 AI 計劃（服務 SIG_AIENTRY 未開或者未有 rev15 出區）")
        md = "\n".join(out) + "\n"; print(md); open(os.path.join(HERE, "AI_ENTRY_FORWARD.md"), "w", encoding="utf-8").write(md); return
    d = ef.broker_bars(t0)
    ai, e6, rows = [], [], []
    for p in plans:
        side, price, ts = p.get("side"), p.get("price"), float(p["ts"])
        sgn = 1 if side == "BUY" else -1
        mid = price - sgn * 6.0
        r_e6 = sim(d, ts, side, mid, mid - sgn * 4.0, mid + sgn * 4.0, lo=mid - 2.0, hi=mid + 2.0)
        r_ai = sim(d, ts, side, p["entry"], p["sl"], p["tp"]) if p.get("valid") else None
        if r_e6 is not None:
            e6.append(r_e6)
        if r_ai is not None:
            ai.append(r_ai)
        rows.append((p.get("utc"), side, price, p.get("entry") if p.get("valid") else (p.get("why") or "唔做"), r_ai, r_e6))
    sa, se = fr.stats(np.array(ai, float)), fr.stats(np.array(e6, float))
    valid = sum(1 for p in plans if p.get("valid"))
    cost = sum(float(p.get("cost_usd") or 0) for p in plans)
    ok = {"①≥30張": sa["n"] >= TARGET_N,
          "②+0.2R PF1.3": sa["n"] > 0 and sa["avg"] >= 0.2 and sa["pf"] >= 1.3,
          "③連敗≤6": sa["streak"] <= 6,
          "④高過E6S4≥0.10R且ΣR唔少過": sa["n"] > 0 and se["n"] > 0 and sa["avg"] - se["avg"] >= 0.10 and sa["sum"] >= se["sum"]}
    verdict = "達標" if all(ok.values()) else ("未夠張數" if not ok["①≥30張"] else "唔達標")
    out += [f"- AI 揀咗做 {valid} 次（其餘唔做／唔合格）；API 成本約 ${cost:.2f}", "",
            "| 方法 | 成績 |", "|---|---|", f"| AI 揀入場 | {fr.fmt(sa)} |", f"| E6S4（同一批出區） | {fr.fmt(se)} |", "",
            f"## 判（預先登記 IDEAS #1003）：{verdict}", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()], "",
            "## 最近 20 次", "", "| 時間 UTC | 方向 | 出區價 | AI 入場 | AI R | E6S4 R |", "|---|---|---|---|---|---|"]
    f = lambda x: "—" if x is None else f"{x:+.2f}"
    out += [f"| {u} | {s} | {pr} | {e} | {f(ra)} | {f(re)} |" for u, s, pr, e, ra, re in rows[-20:][::-1]]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "AI_ENTRY_FORWARD.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
