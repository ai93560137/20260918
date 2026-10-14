"""方向一：唔一定週五收市（或週一）開倉，等到週二、週三權利金升高先沽，可唔可行？（2026-10-14 使用者問）

同一個到期日（通常週五）嘅週期權，比較唔同入場日：
  上週五收市（現行）、週一、週二、週三收市；行使價 = 當日遠期 ± 1σ（σ點 = 當日價平 IV × √(剩餘交易日/252) × 遠期），
  收當日真實結算價（O.Q.P.），到期用恒指收市近似結算，每腳 4 點成本。
規則：
  固定日   每週都喺同一日入場
  等權利金 由上週五開始，第一日 1σ 權利金 ≥ 門檻就入場；到週三都未夠 → 唔做（門檻 80 點 = 現行權利金閘）
  等 IV 升 上週五唔入；週一至週三第一日價平 IV 比上週五高 ≥ 1.5 個百分點就入場；冇 → 唔做
  比例門檻 權利金 ÷ σ點 ≥ 上週五嗰個比例（即係「以剩餘日數計，權利金相對變貴」先入）
兩份數據：A 港交所真實 hsiwo（2025-10 至今）；B 合成（VHSI × 0.85，Black-76，2003 至今，點數換算到恒指 25,000）。

用法：python3 research/hsi_futures_range/iv_timing.py --hsi canary/data_external/hsi_daily.csv --vhsi canary/data_external/vhsi_daily.csv
輸出：research/hsi_futures_range/iv_timing/REPORT.md、real_entries.csv、long_entries.csv、manifest.json
"""
import argparse, json, math, sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import vrp_real as vr                                     # noqa: E402
import iv_decide as ivd                                   # noqa: E402

OUT = HERE / "iv_timing"
COST_LEG = 4.0
PREMIUM_GATE = 80.0
IV_JUMP = 1.5
DAY_ZH = {0: "週一", 1: "週二", 2: "週三", 3: "週四", 4: "週五"}


def trade(F, iv, n, s_t, legs):
    """legs(kp_target, kc_target) → (kp, pp, kc, pc)；回傳 dict 或 None。"""
    T = n / 252
    sig = iv / 100 * math.sqrt(T) * F
    got = legs(F - sig, F + sig)
    if not got:
        return None
    kp, pp, kc, pc = got
    pay = max(0, kp - s_t) + max(0, s_t - kc)
    return {"sig": sig, "credit": pp + pc, "net": pp + pc - pay - 2 * COST_LEG, "kp": kp, "kc": kc,
            "out": abs(s_t - F) > sig, "ratio": (pp + pc) / sig if sig else None}


# ---------------------------------------------------------------- A. 真實
def real_entries(hsi, opt_root):
    atm, series = vr.load_opts(opt_root)
    dates = sorted(hsi)
    by_exp = defaultdict(list)                                    # 到期日 → 可入場日（報告日，到期前）
    for (p, d), exps in atm.items():
        if p != "hsiwo" or d not in hsi:
            continue
        for e in exps:
            if d < e <= dates[-1]:
                by_exp[e].append(d)
    weeks = []
    for e in sorted(by_exp):
        sd, s_t = vr.settle(hsi, dates, e)
        if s_t is None:
            continue
        ds = sorted(by_exp[e])
        # 入場日：上週五（到期週之前最後一個交易日）同到期週內、至少剩 2 個交易日嘅日子
        exp_week = vr.week_key(e)
        prior = [d for d in ds if vr.week_key(d) < exp_week]
        cands = ([prior[-1]] if prior else []) + [d for d in ds if vr.week_key(d) == exp_week]
        rows = {}
        for d in cands:
            n = len([x for x in dates if d < x <= sd])
            if n < 2:
                continue
            a = atm[("hsiwo", d)].get(e)
            if not a or not a.get("forward"):
                continue
            srs = series.get(("hsiwo", d, e), {})

            def legs(tp, tc, srs=srs):
                kp, pp = vr.leg(srs, tp, "P", False)
                kc, pc = vr.leg(srs, tc, "C", True)
                return (kp, pp, kc, pc) if kp and kc else None
            iv = (a["iv_call"] + a["iv_put"]) / 2
            t = trade(a["forward"], iv, n, s_t, legs)
            if t:
                slot = "prev" if vr.week_key(d) < exp_week else date.fromisoformat(d).weekday()
                rows[slot] = {"date": d, "n": n, "iv": iv, **t}
        if "prev" in rows:
            weeks.append({"expiry": e, "settle": s_t, "entries": rows})
    return weeks


# ---------------------------------------------------------------- B. 合成
def long_entries(hsi, vhsi):
    dates = sorted(d for d in hsi if d in vhsi)
    fridays = [d for i, d in enumerate(dates) if i + 1 == len(dates) or vr.week_key(dates[i + 1]) != vr.week_key(d)]
    weeks = []
    for j in range(1, len(fridays)):
        prev, e = fridays[j - 1], fridays[j]
        s_t = hsi[e]["close"]
        cands = [prev] + [d for d in dates if prev < d < e]
        rows = {}
        for d in cands:
            n = len([x for x in dates if d < x <= e])
            if n < 2:
                continue
            F = hsi[d]["close"]
            iv = vhsi[d] * ivd.IV_SCALE
            scale = ivd.SCALE_TO / F

            def legs(tp, tc, F=F, n=n, iv=iv):
                T = n / 252
                return (tp, ivd.bs(F, tp, T, iv / 100, "P"), tc, ivd.bs(F, tc, T, iv / 100, "C"))
            t = trade(F, iv, n, s_t, legs)
            t["net"] = (t["net"] + 2 * COST_LEG) * scale - 2 * COST_LEG          # 換算到 25,000 水平，成本固定 8 點
            t["credit"] *= scale
            t["sig"] *= scale
            slot = "prev" if d == prev else date.fromisoformat(d).weekday()
            rows[slot] = {"date": d, "n": n, "iv": iv, **t}
        if "prev" in rows:
            weeks.append({"expiry": e, "settle": s_t, "entries": rows})
    return weeks


# ---------------------------------------------------------------- 規則
def rule_fixed(w, slot):
    r = w["entries"].get(slot)
    return r["net"] if r else None


def rule_wait_premium(w, gate=PREMIUM_GATE):
    for slot in ("prev", 0, 1, 2):
        r = w["entries"].get(slot)
        if r and r["credit"] >= gate:
            return r["net"], slot
    return 0.0, "skip"


def rule_wait_iv(w, jump=IV_JUMP):
    base = w["entries"]["prev"]["iv"]
    for slot in (0, 1, 2):
        r = w["entries"].get(slot)
        if r and r["iv"] >= base + jump:
            return r["net"], slot
    return 0.0, "skip"


def rule_prev_or_iv(w, jump=IV_JUMP):
    """上週五照沽；如果之後 IV 升 ≥ jump，再加沽一張（同到期）——睇「加碼」係咪抵。只計加嗰張。"""
    base = w["entries"]["prev"]["iv"]
    for slot in (0, 1, 2):
        r = w["entries"].get(slot)
        if r and r["iv"] >= base + jump:
            return r["net"], slot
    return None, None


def rule_ratio(w):
    base = w["entries"]["prev"]
    for slot in ("prev", 0, 1, 2):
        r = w["entries"].get(slot)
        if r and slot != "prev" and r["ratio"] and base["ratio"] and r["ratio"] >= base["ratio"] * 1.1:
            return r["net"], slot
    return 0.0, "skip"


def fmt_row(name, vals, extra=""):
    s = ivd.stats([v for v in vals if v is not None])
    return f"| {name} | {ivd.fmt_s(s)} | {s.get('total', 0):+,.0f} | {extra} |"


def section(weeks, title):
    L = [f"## {title}", "", f"週數：{len(weeks)}（{weeks[0]['expiry']}–{weeks[-1]['expiry']} 到期）", "",
         "### 固定喺同一日入場（同一個到期日）", "",
         "| 入場日 | 週數 | **每週平均（點）** | 賺錢週 | 最差一週 | t | 總點數 | 平均權利金／σ點／走出 1σ |", "|---|---|---|---|---|---|---|---|"]
    for slot, name in (("prev", "上週五收市（現行）"), (0, "週一收市"), (1, "週二收市"), (2, "週三收市")):
        rs = [w["entries"][slot] for w in weeks if slot in w["entries"]]
        extra = (f"{np.mean([r['credit'] for r in rs]):.0f}／{np.mean([r['sig'] for r in rs]):.0f}／"
                 f"{np.mean([r['out'] for r in rs]) * 100:.0f}%") if rs else ""
        L.append(fmt_row(name, [r["net"] for r in rs], extra))
    L += ["", "### 等權利金／等 IV 升（同一批週，做唔到就當 0）", "",
          "| 規則 | 週數 | **每週平均（點）** | 賺錢週 | 最差一週 | t | 總點數 | 喺邊日入場 |", "|---|---|---|---|---|---|---|---|"]
    base = [w["entries"]["prev"]["net"] for w in weeks]
    L.append(fmt_row("上週五照沽（基準）", base, f"全部 {len(base)} 週"))
    for gate in (80, 100, 120):
        res = [rule_wait_premium(w, gate) for w in weeks]
        cnt = defaultdict(int)
        for _, s in res:
            cnt[s] += 1
        L.append(fmt_row(f"等權利金 ≥ {gate}：上週五起第一日夠就沽，週三仲未夠唔做", [v for v, _ in res],
                         "、".join(f"{'上週五' if k == 'prev' else ('唔做' if k == 'skip' else DAY_ZH[k])} {c}" for k, c in cnt.items())))
    res = [rule_wait_iv(w) for w in weeks]
    cnt = defaultdict(int)
    for _, s in res:
        cnt[s] += 1
    L.append(fmt_row(f"上週五唔沽；週一至三 IV 比上週五高 ≥ {IV_JUMP} 先沽", [v for v, _ in res],
                     "、".join(f"{'唔做' if k == 'skip' else DAY_ZH[k]} {c}" for k, c in cnt.items())))
    res = [rule_ratio(w) for w in weeks]
    cnt = defaultdict(int)
    for _, s in res:
        cnt[s] += 1
    L.append(fmt_row("上週五唔沽；權利金÷σ點 比上週五高 10% 先沽", [v for v, _ in res],
                     "、".join(f"{'唔做' if k == 'skip' else DAY_ZH[k]} {c}" for k, c in cnt.items())))
    add = [rule_prev_or_iv(w) for w in weeks]
    add_v = [v for v, s in add if v is not None]
    L += ["", "### 加碼：上週五照沽一張，之後 IV 升 ≥ 1.5 個百分點再加沽一張（只計加嗰張）", "",
          "| 規則 | 週數 | **每張平均（點）** | 賺錢 | 最差 | t | 總點數 | |", "|---|---|---|---|---|---|---|---|",
          fmt_row("加嗰張", add_v, f"{len(add_v)} 次"), ""]
    # IV 升嘅週，上週五嗰張表現（等於「等」嘅機會成本）
    up = [w for w in weeks if any(w["entries"].get(s) and w["entries"][s]["iv"] >= w["entries"]["prev"]["iv"] + IV_JUMP for s in (0, 1, 2))]
    L += [f"IV 之後升 ≥ {IV_JUMP} 嘅週（{len(up)} 週）：上週五嗰張平均 {np.mean([w['entries']['prev']['net'] for w in up]):+.0f} 點、"
          f"走出 1σ {np.mean([w['entries']['prev']['out'] for w in up]) * 100:.0f}%；"
          f"其餘週平均 {np.mean([w['entries']['prev']['net'] for w in weeks if w not in up]):+.0f} 點。" if up else "", ""]
    return L


def dump(path, weeks):
    rows = []
    for w in weeks:
        for slot, r in w["entries"].items():
            rows.append({"expiry": w["expiry"], "slot": "prev_fri" if slot == "prev" else DAY_ZH[slot], **r})
    ivd.write_csv(path, rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hsi", required=True)
    ap.add_argument("--vhsi", required=True)
    ap.add_argument("--opt", default=str(REPO / "data" / "hkex_options"))
    a = ap.parse_args()
    hsi, vhsi = vr.load_hsi(a.hsi), vr.load_vhsi(a.vhsi)
    real, long = real_entries(hsi, a.opt), long_entries(hsi, vhsi)
    OUT.mkdir(exist_ok=True)
    dump(OUT / "real_entries.csv", real)
    dump(OUT / "long_entries.csv", long)
    L = ["# 方向一：等週二、週三權利金升高先沽，可唔可行？", "",
         f"- 產生：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}；腳本 `iv_timing.py`；每腳成本 {COST_LEG:g} 點；統計估計，唔係交易建議",
         "- 全部係同一個到期日（到期週嘅最後一個交易日）；入場日行使價 = 當日遠期 ± 1σ（用當日 IV 同剩餘交易日計），至少剩 2 個交易日",
         "- B 合成冇偏斜、點數換算到恒指 25,000；絕對值偏低，睇相對高低", ""]
    L += section(real, "A. 港交所真實週期權")
    L += section(long, "B. 長期合成（VHSI × 0.85，2003 起）")
    (OUT / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    json.dump({"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "script_sha256": vr.sha(__file__),
               "inputs": {"hsi": vr.sha(a.hsi), "vhsi": vr.sha(a.vhsi), "atm_iv.csv": vr.sha(Path(a.opt) / "atm_iv.csv")},
               "real_weeks": len(real), "long_weeks": len(long), "premium_gate": PREMIUM_GATE, "iv_jump": IV_JUMP},
              open(OUT / "manifest.json", "w"), ensure_ascii=False, indent=1)
    print("\n".join(L))


if __name__ == "__main__":
    main()
