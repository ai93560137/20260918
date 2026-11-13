"""IDEAS #5001：方向一 Call 側 200 日線過濾（預先登記 2026-11-12，只跑一次）。

基準 B：每週最後一個有報告交易日收市，沽下一個到期 HSIWO 1σ 勒式（Put F−σ 往下取、Call F+σ 往上取）。
變體 V：入場日恒指收市 > 200 日均線（含入場日之前 200 個交易日）→ Call 改 F+1.3σ（往上取），其餘同 B。
成交價＝港交所 O.Q.P.；結算＝到期日恒指收市；每腳 4 點。σ＝價平 IV（C／P 平均）×√(交易日÷252)×遠期（同 vrp_real.py）。

用法：python3 research/hsi_futures_range/call_sma200.py --hsi hsi_daily.csv [--opt data/hkex_options]
輸入 hsi_daily.csv：canary 分支 canary/data_external/hsi_daily.csv（Date,Open,High,Low,Close）。
輸出：research/hsi_futures_range/call_sma200/weekly.csv、REPORT.md、manifest.json
"""
import argparse, csv, math, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import vrp_real as vr                                    # noqa: E402

OUT = HERE / "call_sma200"
COST_LEG = 4.0
WIDE = 1.3
SMA_N = 200


def sma_map(hsi):
    dates = sorted(hsi)
    out = {}
    for i in range(SMA_N - 1, len(dates)):
        out[dates[i]] = sum(hsi[d]["close"] for d in dates[i - SMA_N + 1:i + 1]) / SMA_N
    return out


def run(atm, series, hsi, cost):
    dates = sorted(hsi)
    sma = sma_map(hsi)
    by_week = defaultdict(list)
    for (p, d) in atm:
        if p == "hsiwo" and d in hsi:
            by_week[vr.week_key(d)].append(d)
    rows = []
    for wk in sorted(by_week):
        d = max(by_week[wk])
        e = vr.nearest_expiry(atm[("hsiwo", d)], d)
        if not e or e > dates[-1]:
            continue
        a = atm[("hsiwo", d)][e]
        sd, s_t = vr.settle(hsi, dates, e)
        if s_t is None or sd <= d:
            continue
        F = a["forward"]
        iv = (a["iv_call"] + a["iv_put"]) / 2
        n_days = len([x for x in dates if d < x <= sd])
        sig = iv / 100 * math.sqrt(n_days / 252) * F
        srs = series.get(("hsiwo", d, e), {})
        kp, pp = vr.leg(srs, F - sig, "P", False)
        kc, pc = vr.leg(srs, F + sig, "C", True)
        kcw, pcw = vr.leg(srs, F + WIDE * sig, "C", True)
        if not (kp and kc and kcw and sig > 0) or d not in sma:
            continue
        above = hsi[d]["close"] > sma[d]
        kv, pv = (kcw, pcw) if above else (kc, pc)
        put_pay = max(0.0, kp - s_t)
        call_b, call_v = max(0.0, s_t - kc), max(0.0, s_t - kv)
        rows.append({"entry": d, "expiry": e, "settle": round(s_t, 2), "forward": F, "iv": iv, "sigma": round(sig, 1),
                     "close": hsi[d]["close"], "sma200": round(sma[d], 2), "above": int(above),
                     "kp": kp, "put": pp, "kc_b": kc, "call_b": pc, "kc_v": kv, "call_v": pv,
                     "credit_b": pp + pc, "credit_v": pp + pv, "put_pay": round(put_pay, 2),
                     "call_pay_b": round(call_b, 2), "call_pay_v": round(call_v, 2),
                     "net_b": round(pp + pc - put_pay - call_b - 2 * cost, 2),
                     "net_v": round(pp + pv - put_pay - call_v - 2 * cost, 2)})
    return rows


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def judge(rows):
    nb, nv = [r["net_b"] for r in rows], [r["net_v"] for r in rows]
    up = [r for r in rows if r["above"]]
    hit_b = sum(1 for r in rows if r["call_pay_b"] > 0)
    hit_v = sum(1 for r in rows if r["call_pay_v"] > 0)
    pay_b, pay_v = sum(r["call_pay_b"] for r in up), sum(r["call_pay_v"] for r in up)
    h = len(rows) // 2
    halves = [(mean([r["net_b"] for r in part]), mean([r["net_v"] for r in part])) for part in (rows[:h], rows[h:])]
    c1 = mean(nv) >= mean(nb)
    c2 = (min(nv) >= min(nb) + 50) or (hit_b > 0 and hit_v <= hit_b * 2 / 3)
    c3 = pay_v <= 0.7 * pay_b if pay_b > 0 else True
    c4 = all(v >= b - 5 for b, v in halves)
    return {"weeks": len(rows), "above_weeks": len(up), "mean_b": mean(nb), "mean_v": mean(nv), "worst_b": min(nb),
            "worst_v": min(nv), "hit_b": hit_b, "hit_v": hit_v, "call_pay_up_b": pay_b, "call_pay_up_v": pay_v,
            "halves": halves, "c1": c1, "c2": c2, "c3": c3, "c4": c4, "pass": c1 and c2 and c3 and c4,
            "gate80_b": sum(1 for r in rows if r["credit_b"] < 80), "gate80_v": sum(1 for r in rows if r["credit_v"] < 80),
            "sum_b": sum(nb), "sum_v": sum(nv), "pos_b": sum(1 for x in nb if x > 0), "pos_v": sum(1 for x in nv if x > 0)}


def report(rows, j, man):
    ok = lambda b: "✅" if b else "❌"
    up = [r for r in rows if r["above"]]
    lines = [
        "# IDEAS #5001：方向一 Call 側 200 日線過濾（線上 Call 1.3σ）",
        "",
        f"預先登記 2026-11-12（`IDEAS.md` #5001），只跑一次。產生 {man['generated_utc']} UTC。逐週底稿 `weekly.csv`。",
        "",
        f"**判決：{'✅ 合格（只升紙上）' if j['pass'] else '❌ 唔合格'}**",
        "",
        "| 預先登記標準 | 基準 B | 變體 V | 結果 |",
        "|---|---|---|---|",
        f"| ① 全期平均每週淨利 V ≥ B | {j['mean_b']:+.1f} | {j['mean_v']:+.1f} | {ok(j['c1'])} |",
        f"| ② 最差一週 V ≥ B＋50，或 Call 被打穿週數少 ≥ 1／3 | 最差 {j['worst_b']:+.0f}；打穿 {j['hit_b']} 週 | 最差 {j['worst_v']:+.0f}；打穿 {j['hit_v']} 週 | {ok(j['c2'])} |",
        f"| ③ 線上週 Call 賠付合計 V ≤ B × 70% | {j['call_pay_up_b']:.0f} | {j['call_pay_up_v']:.0f} | {ok(j['c3'])} |",
        f"| ④ 前後兩半每半 V ≥ B − 5 | {j['halves'][0][0]:+.1f}／{j['halves'][1][0]:+.1f} | {j['halves'][0][1]:+.1f}／{j['halves'][1][1]:+.1f} | {ok(j['c4'])} |",
        "",
        "## 概覽",
        "",
        f"- 週數 {j['weeks']}（{rows[0]['entry']} 至 {rows[-1]['entry']} 入場），其中入場日喺 200 日線上面 {j['above_weeks']} 週。",
        f"- 總淨利：B {j['sum_b']:+.0f} 點、V {j['sum_v']:+.0f} 點；賺錢週 B {j['pos_b']}、V {j['pos_v']}。",
        f"- 次要（唔計判決）：合計權利金 < 80 點嘅週，B {j['gate80_b']} 週、V {j['gate80_v']} 週（V 收少咗 Call 權利金，會多咗週數唔夠閘）。",
        f"- 線上週：B 平均 {mean([r['net_b'] for r in up]):+.1f}、V 平均 {mean([r['net_v'] for r in up]):+.1f}；"
        f"Call 權利金 B 平均 {mean([r['call_b'] for r in up]):.1f}、V 平均 {mean([r['call_v'] for r in up]):.1f}。",
        "",
        "## 線上週逐週（Call 部分）",
        "",
        "| 入場 | 收市／200 日線 | 結算 | B Call @ 權利金 → 賠 | V Call @ 權利金 → 賠 | 淨 B | 淨 V |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in up:
        lines.append(f"| {r['entry']} | {r['close']:,.0f}／{r['sma200']:,.0f} | {r['settle']:,.0f} | {r['kc_b']:,} @ {r['call_b']:g} → {r['call_pay_b']:.0f} | "
                     f"{r['kc_v']:,} @ {r['call_v']:g} → {r['call_pay_v']:.0f} | {r['net_b']:+.0f} | {r['net_v']:+.0f} |")
    lines += ["", "## 限制", "",
              "- 樣本只有約一年（港交所 HSIWO 報告由 2025-10 起有），統計力弱；合格亦只升紙上，唔直接改實倉規則。",
              "- 結算用到期日恒指收市近似 EAS；成交價用 O.Q.P.（實際沽出按買價，會少啲）。",
              "- 200 日線用 canary 分支 `hsi_daily.csv`（Yahoo ^HSI）；入場日當日收市計入。",
              "", "## 輸入雜湊", "", "```", json.dumps(man["inputs"], ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hsi", required=True)
    ap.add_argument("--opt", default=str(REPO / "data" / "hkex_options"))
    ap.add_argument("--cost", type=float, default=COST_LEG)
    a = ap.parse_args()
    hsi = vr.load_hsi(a.hsi)
    atm, series = vr.load_opts(a.opt)
    rows = run(atm, series, hsi, a.cost)
    j = judge(rows)
    OUT.mkdir(exist_ok=True)
    with open(OUT / "weekly.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    man = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "cost_leg": a.cost, "wide": WIDE,
           "sma_n": SMA_N, "script_sha256": vr.sha(__file__), "weeks": len(rows),
           "inputs": {"hsi": vr.sha(a.hsi), "atm_iv.csv": vr.sha(Path(a.opt) / "atm_iv.csv"),
                      "series": {f.name: vr.sha(f) for f in sorted((Path(a.opt) / "series").glob("hsiwo_*.csv.gz"))}},
           "judge": {k: v for k, v in j.items() if k != "halves"} | {"halves": j["halves"]}}
    (OUT / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(report(rows, j, man), encoding="utf-8")
    print(json.dumps(man["judge"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
