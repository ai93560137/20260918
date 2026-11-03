"""[IDEAS #224] 921 規則有冇幫到 AI（使用者 11-03「AI唔應該用規則」）。
決策日誌（xau/decisions/）入面 AI 想開倉（action＝OPEN_LONG／OPEN_SHORT）嘅決定分三組：
  A 規則放行（final＝action）：用 AI 原本 SL／TP（有 widen 用放闊前原值）
  B 規則擋咗（final≠action，有 rejected 原因）：用 ai_stop／ai_target；再按原因分：M1 硬規則／冷靜期／逆 H4／其他
  C 全部（A＋B）＝「冇規則嘅 AI」
重播同 #211 一樣：經紀 M1（缺嘅用 Dukascopy 補），下一分鐘開盤入、24h、同分鐘當止蝕、扣 0.5 美元，R＝AI 原止蝕距離。
B 組 AI 經常喺幾分鐘內重複想做同一個 setup：另列「去重」（同方向 15 分鐘內只計第一個）。
判（預先登記，主判用去重）：某類規則「有用」＝被擋嗰組平均 R < 0 而且比放行組低 ≥ 0.10R（兩樣都要）；
否則「冇證據有用」→ 支持使用者「AI 唔應該用規則」，提案拎走嗰條（921 而家係影子，改 env 照樣要總指揮 dry-run＋使用者批）。
樣本細（10-20→11-03），只係證據唔係定論。
用法：python3 research/strategy_search/rules_921.py → RULES_921.md
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_921 as F9  # noqa: E402


def kind(why):
    w = why or ""
    if "M1 硬規則" in w:
        return "M1 硬規則"
    if "冷靜期" in w:
        return "冷靜期"
    if "逆 H4" in w:
        return "逆 H4"
    return "其他"


def load(g):
    out = []
    for nm in sorted(g.list("xau/decisions/")):
        for ln in (g.read_text(nm) or "").splitlines():
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            for x in (o if isinstance(o, list) else [o]):
                if x.get("kind") != "decide" or x.get("action") not in ("OPEN_LONG", "OPEN_SHORT"):
                    continue
                s = 1 if x["action"] == "OPEN_LONG" else -1
                if x.get("final") == x["action"]:
                    w = x.get("widen") or {}
                    st, tg = (w.get("stop"), w.get("target")) if w.get("stop") else (x.get("stop"), x.get("target"))
                    grp = "A 放行"
                else:
                    st, tg = x.get("ai_stop"), x.get("ai_target")
                    grp = "B " + kind(x.get("rejected"))
                if st and tg:
                    out.append(dict(ts=float(x["ts"]), s=s, sl=float(st), tp=float(tg), grp=grp))
    return sorted(out, key=lambda d: d["ts"])


def dedupe(rows):
    keep, last = [], {}
    for r in rows:
        k = (r["grp"][0], r["s"])
        if r["ts"] - last.get(k, -1e18) >= 900:
            keep.append(r)
        last[k] = r["ts"]
    return keep


def run(m1, rows):
    res = F9.replay(m1, [(r["ts"], r["s"], r["sl"], r["tp"], True) for r in rows])
    by_ts = {}
    for t, s, R in res:
        by_ts.setdefault((t, s), []).append(R)
    out = []
    import numpy as np
    for r in rows:
        a = int(np.searchsorted(m1["t"], r["ts"], side="right"))
        if a < len(m1["t"]):
            v = by_ts.get((int(m1["t"][a]), r["s"]))
            if v:
                out.append((r, v.pop(0)))
    return out


def main():
    g = F9.gb.Gcs()
    rows = load(g)
    m1 = F9.EF6.broker_bars(int(rows[0]["ts"]) - 86400)
    m1, nd = F9.merge_duka(g, m1, dt.datetime.fromtimestamp(rows[0]["ts"] - 86400, dt.timezone.utc).date().isoformat())
    out = ["# 921 規則有冇幫到 AI（IDEAS #224）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；決策日誌 AI 想開倉 {len(rows)} 個（放行 {sum(r['grp'] == 'A 放行' for r in rows)}、被擋 {sum(r['grp'] != 'A 放行' for r in rows)}）；"
           "重播：經紀 M1＋Dukascopy 補、24h、扣 0.5 美元、R＝AI 原止蝕距離", ""]
    verdict = {}
    for lab, rr in (("全部", rows), ("去重（同方向 15 分鐘內只計第一個）", dedupe(rows))):
        res = run(m1, rr)
        groups = sorted({r["grp"] for r, _ in res})
        out += [f"## {lab}", "", "| 組 | 結果 |", "|---|---|"]
        A = F9.summ([R for r, R in res if r["grp"] == "A 放行"])
        for gname in groups:
            out.append(f"| {gname} | {F9.fmt(F9.summ([R for r, R in res if r['grp'] == gname]))} |")
        out.append(f"| C 冇規則（全部 AI 想做） | {F9.fmt(F9.summ([R for _, R in res]))} |")
        out.append("")
        if lab.startswith("去重"):
            for gname in groups:
                if gname.startswith("B"):
                    B = F9.summ([R for r, R in res if r["grp"] == gname])
                    useful = B["n"] > 0 and B["avg"] < 0 and A["avg"] - B["avg"] >= 0.10
                    verdict[gname] = (useful, B, A)
        print(lab, F9.fmt(A), flush=True)
    out += ["## 判（預先登記，用去重）", ""]
    for gname, (u, B, A) in verdict.items():
        out.append(f"- {gname[2:]}：被擋 {F9.fmt(B)}；放行 {A['avg']:+.3f}R → "
                   + ("✅ 有用（被擋嗰啲真係差）" if u else "❌ 冇證據有用 → 支持拎走（提案要總指揮 dry-run＋使用者批）"))
    out += ["", "- 樣本只得 10-20→11-03 兩星期；被擋組張數細，結論只係方向。", ""]
    open(os.path.join(HERE, "RULES_921.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
