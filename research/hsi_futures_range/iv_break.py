"""方向一：週五入場前恒指跌穿（或升穿）20 日低（高）嘅週，1σ 勒式係咪差啲？（2026-10-14，形態研究工作階段 PR #124 轉交：
「恒指收市破 20 日低之後 5 日，走出 ±1σ 機率明顯高：2016 年前 50% 對 37%，2017 年起 55% 對 32%」——佢嘅 1σ 用之前 20 日實際波動，
我哋嘅 1σ 用期權 IV，要用方向一自己嘅數據再驗。）

數據同 iv_decide.py：A 港交所真實週期權（2025-10 至今）；B VHSI × 0.85 合成（2003 至今，點數換算到恒指 25,000）。
條件（全部只用入場當日或之前）：
  low20_close  入場日收市 < 之前 20 個交易日最低收市
  low20_low    入場日收市 < 之前 20 個交易日最低位
  low20_week   入場週（週一至入場日）任何一日收市 < 佢之前 20 日最低收市
  high20_close 對照：入場日收市 > 之前 20 日最高收市
比較：條件成立 vs 唔成立嘅週，1σ／1.5σ／2σ 每週淨利、走出 1σ 比率、到期升定跌；B 分 2016 年前／2017 年起。
規則候選：條件成立就（a）唔做（b）改沽 1.5σ；對比每週都沽 1σ。

用法：python3 research/hsi_futures_range/iv_break.py --hsi canary/data_external/hsi_daily.csv --vhsi canary/data_external/vhsi_daily.csv
輸出：research/hsi_futures_range/iv_break/REPORT.md、real_weeks.csv、long_weeks.csv、manifest.json
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vrp_real as vr                                     # noqa: E402
import iv_decide as ivd                                   # noqa: E402

OUT = HERE / "iv_break"
REPO = HERE.parents[1]
LOOK = 20
CONDS = (("low20_close", "收市跌穿之前 20 日最低收市"), ("low20_low", "收市跌穿之前 20 日最低位"),
         ("low20_week", "入場週內任何一日收市跌穿 20 日低"), ("high20_close", "（對照）收市升穿之前 20 日最高收市"))


def tag(rows, hsi):
    dates = sorted(hsi)
    pos = {d: i for i, d in enumerate(dates)}
    closes = [hsi[d]["close"] for d in dates]
    lows = [hsi[d]["low"] for d in dates]

    def brk(i):
        return i >= LOOK and closes[i] < min(closes[i - LOOK:i])
    for r in rows:
        i = pos.get(r["entry"])
        if i is None or i < LOOK + 5:
            continue
        c = closes[i]
        r["low20_close"] = c < min(closes[i - LOOK:i])
        r["low20_low"] = c < min(lows[i - LOOK:i])
        r["high20_close"] = c > max(closes[i - LOOK:i])
        wk = vr.week_key(r["entry"])
        r["low20_week"] = any(brk(j) for j in range(i - 4, i + 1) if vr.week_key(dates[j]) == wk)
        r["up_move"] = r["settle"] > r["forward"]
    return [r for r in rows if "low20_close" in r]


def line(name, g):
    if not g:
        return f"| {name} | 0 | — | — | — | — | — | — |"
    s1 = ivd.stats([r.get("net_1") for r in g])
    s15 = ivd.stats([r.get("net_1.5") for r in g])
    s2 = ivd.stats([r.get("net_2") for r in g])
    out = np.mean([r["move_sig"] > 1 for r in g]) * 100
    up = np.mean([r["up_move"] for r in g if r["move_sig"] > 1]) * 100 if any(r["move_sig"] > 1 for r in g) else float("nan")
    return (f"| {name} | {len(g)} | {out:.0f}% | {up:.0f}% | **{s1['mean']:+.0f}**（{s1['win']:.0f}%，最差 {s1['worst']:+.0f}） | "
            f"{s15['mean']:+.0f}（最差 {s15['worst']:+.0f}） | {s2['mean']:+.0f} | {s1['total']:+,.0f} |")


def block(rows, cond, label):
    yes = [r for r in rows if r[cond]]
    no = [r for r in rows if not r[cond]]
    L = [f"**{label}**", "", "| 週 | 週數 | 走出 1σ | 走出時向上 | 1σ 每週（賺錢週、最差） | 1.5σ 每週 | 2σ 每週 | 1σ 總點數 |",
         "|---|---|---|---|---|---|---|---|", line("條件成立", yes), line("唔成立", no), ""]
    if yes and no:
        a = np.array([r["net_1"] for r in yes if r.get("net_1") is not None])
        b = np.array([r["net_1"] for r in no if r.get("net_1") is not None])
        if len(a) > 1 and len(b) > 1:
            se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
            L.append(f"1σ 每週差（成立 − 唔成立）{a.mean() - b.mean():+.0f} 點，t {(a.mean() - b.mean()) / se:+.2f}")
        base = [r.get("net_1") for r in rows if r.get("net_1") is not None]
        skip = [0.0 if r[cond] else r.get("net_1") for r in rows if r.get("net_1") is not None]
        wide = [(r.get("net_1.5") if r[cond] else r.get("net_1")) for r in rows if r.get("net_1") is not None]
        L += ["", "| 規則（全部週） | 週數 | **每週平均** | 賺錢週 | 最差一週 | t |", "|---|---|---|---|---|---|",
              f"| 每週都沽 1σ | {ivd.fmt_s(ivd.stats(base))} |",
              f"| 條件成立就唔做 | {ivd.fmt_s(ivd.stats(skip))} |",
              f"| 條件成立就改沽 1.5σ | {ivd.fmt_s(ivd.stats(wide))} |", ""]
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hsi", required=True)
    ap.add_argument("--vhsi", required=True)
    ap.add_argument("--opt", default=str(REPO / "data" / "hkex_options"))
    ap.add_argument("--har", default=str(HERE / "vrp_real" / "weekly.csv"))
    a = ap.parse_args()
    hsi, vhsi = vr.load_hsi(a.hsi), vr.load_vhsi(a.vhsi)
    real = tag(ivd.real_weeks(hsi, vhsi, a.opt, a.har), hsi)
    long = tag(ivd.long_weeks(hsi, vhsi), hsi)
    OUT.mkdir(exist_ok=True)
    ivd.write_csv(OUT / "real_weeks.csv", real)
    ivd.write_csv(OUT / "long_weeks.csv", long)
    L = ["# 方向一：週五入場前跌穿 20 日低嘅週，1σ 勒式係咪差啲？", "",
         f"- 產生：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}；腳本 `iv_break.py`；1σ 用期權 IV（A 真實、B VHSI×0.85）；每腳成本 4 點",
         "- 「走出時向上」= 走出 1σ 嘅週入面，到期價高過遠期嘅比率", ""]
    L += [f"## A. 港交所真實週期權（{len(real)} 週，{real[0]['entry']}–{real[-1]['entry']}）", ""]
    for c, lab in CONDS:
        L += block(real, c, lab)
    early = [r for r in long if r["entry"] < "2017-01-01"]
    late = [r for r in long if r["entry"] >= "2017-01-01"]
    for name, seg in ((f"B. 合成全部（{len(long)} 週）", long), (f"B1. 合成 2016 年或之前（{len(early)} 週）", early),
                      (f"B2. 合成 2017 年起（{len(late)} 週）", late)):
        L += [f"## {name}", ""]
        for c, lab in CONDS:
            L += block(seg, c, lab)
    (OUT / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    json.dump({"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "script_sha256": vr.sha(__file__),
               "inputs": {"hsi": vr.sha(a.hsi), "vhsi": vr.sha(a.vhsi), "atm_iv.csv": vr.sha(Path(a.opt) / "atm_iv.csv")},
               "real_weeks": len(real), "long_weeks": len(long), "lookback": LOOK},
              open(OUT / "manifest.json", "w"), ensure_ascii=False, indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
