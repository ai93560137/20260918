"""[IDEAS #155 修訂 10-31] 921 真倉單「學生同向」兩個分組：
  A. 原分組＝實時學生 log（GCS xau/sig/student/log/<日>.jsonl，60 分鐘冷卻）開倉前 30 分鐘內有 rule:rev15／level／swing 同方向
  B. 原始出區分組＝經紀 M1（xau/sig/bars/）逐分鐘行 rev15／level／swing 出區規則、唔設冷卻，開倉前 30 分鐘內有同方向
921 單＝GCS xau/state.json book（＋book_seed.json），由 2026-10-30 09:00 UTC 之後開倉起計。R＝成交簿 r（決策價→初始止損）。
判斷以 IDEAS #155 為準（兩個分組都要達到 ①–③）。唔寫 GCS。
用法：python3 research/student_offline/s155_raw.py"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fit_rules as fr   # noqa: E402
import e6s4_forward as ef   # noqa: E402

START = "2026-10-30T09:00"
RULES = ("rev15", "level", "swing")
WIN = 30 * 60


def trades(g):
    rows = (g.read_json("xau/book_seed.json") or []) + ((g.read_json("xau/state.json") or {}).get("book") or [])
    t0 = fr.ts_of(START)
    seen, out = set(), []
    for r in rows:
        k = r.get("ticket") or (r.get("opened_ts"), r.get("side"))
        if k in seen or not r.get("opened_ts") or float(r["opened_ts"]) <= t0 or r.get("r") is None:
            continue
        seen.add(k)
        out.append({"ts": float(r["opened_ts"]), "side": "BUY" if int(r["side"]) > 0 else "SELL", "r": float(r["r"])})
    return sorted(out, key=lambda x: x["ts"])


def student_log(g, days):
    out = []
    for d in days:
        doc = g.read_json(f"xau/sig/student/log/{d}.jsonl")
        if doc is None:
            txt = g.read_text(f"xau/sig/student/log/{d}.jsonl") or ""
            doc = []
            for ln in txt.splitlines():
                try:
                    x = json.loads(ln)
                    doc.extend(x if isinstance(x, list) else [x])
                except ValueError:
                    pass
        out += [x for x in doc if isinstance(x, dict) and x.get("student") in ("rule:rev15", "rule:level", "rule:swing")]
    return out


def grp_stats(rs):
    a = np.array(rs, dtype=float)
    return fr.stats(a) if len(a) else {"n": 0, "avg": None, "pf": None, "streak": 0, "sum": 0.0}


def judge(p, f):
    return {"①兩組各≥8": p["n"] >= 8 and f["n"] >= 8,
            "②通過組+0.1R PF1.2": p["n"] > 0 and p["avg"] >= 0.1 and p["pf"] >= 1.2,
            "③通過組好過≥0.3R": p["n"] > 0 and f["n"] > 0 and p["avg"] - f["avg"] >= 0.3}


def main():
    sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
    import gb_rulesim as gb   # noqa: E402
    g = gb.Gcs()
    tr = trades(g)
    out = ["# IDEAS #155 兩個分組（原分組＝實時學生 log；原始出區＝經紀 M1、唔設冷卻）", ""]
    if not tr:
        out.append("- 未有 921 單"); print("\n".join(out)); return
    t0 = fr.ts_of(START)
    d = ef.broker_bars(t0)
    days = sorted({dt.datetime.fromtimestamp(x["ts"] + k, dt.timezone.utc).date().isoformat() for x in tr for k in (-86400, 0)})
    log = student_log(g, days)
    raw = []
    for rule in RULES:
        raw += [(int(d["t"][i]) + 60, side, rule) for i, side in fr.raw_signals(d, rule, fr.CURRENT[rule])]
    tmin, tmax = (int(d["t"][0]), int(d["t"][-1])) if len(d["t"]) else (0, 0)
    groups = {"A": {True: [], False: []}, "B": {True: [], False: []}}
    out.append("| 開倉 UTC | 方向 | R | 原分組 | 原始出區 | 經紀 K 線 |")
    out.append("|---|---|---|---|---|---|")
    nocov = 0
    for x in tr:
        a = [s["student"][5:] for s in log if s.get("side") == x["side"] and x["ts"] - WIN <= float(s["ts"]) <= x["ts"]]
        b = sorted({r for t, sd, r in raw if sd == x["side"] and x["ts"] - WIN <= t <= x["ts"]})
        cov = int(np.sum((d["t"] >= x["ts"] - WIN - 400 * 60) & (d["t"] < x["ts"]))) if len(d["t"]) else 0
        covered = cov >= 30 and tmin <= x["ts"] - WIN
        groups["A"][bool(a)].append(x["r"])
        if covered:
            groups["B"][bool(b)].append(x["r"])
        else:
            nocov += 1
        out.append(f"| {dt.datetime.fromtimestamp(x['ts'], dt.timezone.utc):%m-%d %H:%M} | {x['side']} | {x['r']:+.2f} | {'通過 ' + '／'.join(sorted(set(a))) if a else '唔通過'} | "
                   f"{('通過 ' + '／'.join(b) if b else '唔通過') if covered else '冇數（唔計）'} | {cov} 根 |")
    out.append("")
    verdicts = []
    for k, name in (("A", "原分組（實時學生 log）"), ("B", "原始出區（唔設冷卻）")):
        p, f = grp_stats(groups[k][True]), grp_stats(groups[k][False])
        ok = judge(p, f)
        verdicts.append(all(ok.values()))
        out.append(f"- {name}：通過 {fr.fmt(p)}｜唔通過 {fr.fmt(f)}｜" + "、".join(f"{kk}{'✓' if v else '✗'}" for kk, v in ok.items()))
    if nocov:
        out.append(f"- 原始出區分組有 {nocov} 張經紀 K 線唔夠（EA 冇開／冇存），唔計")
    out.append(f"- 判斷（兩個分組都要過）：{'達標' if all(verdicts) else '未達標／未夠張數'}")
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "S155_GROUPS.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
