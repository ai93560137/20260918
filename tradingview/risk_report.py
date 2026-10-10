#!/usr/bin/env python3
"""持倉風險報告：讀 data_external/risk_book.json → 重估 Greeks → 壓力測試 → 對照 HK$750,000 硬止損。
純計算，不連任何券商。用 Black-76（期貨期權），IV 由現價反推（Put 無可靠現價時用 Call IV＋偏斜）。
用法：python3 risk_report.py [--book data_external/risk_book.json] [--md risk_report.md]
"""
import argparse
import json
from datetime import date
from math import erf, exp, log, sqrt
from pathlib import Path

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
HERE = Path(__file__).resolve().parent


def b76(F, K, s, T, cp):
    if T <= 0 or s <= 0:
        return max(F - K, 0) if cp == "call" else max(K - F, 0)
    d1 = (log(F / K) + .5 * s * s * T) / (s * sqrt(T))
    d2 = d1 - s * sqrt(T)
    return F * N(d1) - K * N(d2) if cp == "call" else K * N(-d2) - F * N(-d1)


def implied(price, F, K, T, cp):
    lo, hi = .02, 1.5
    for _ in range(80):
        m = (lo + hi) / 2
        if b76(F, K, m, T, cp) > price:
            hi = m
        else:
            lo = m
    return m


def load(book_path):
    b = json.loads(Path(book_path).read_text(encoding="utf-8"))
    val = date.fromisoformat(b["valuation_date"])
    fx = b["fx"]
    for p in b["positions"]:
        F = b["underlyings"][p["und"]]["F"]
        if p["type"] in ("call", "put"):
            p["T"] = max((date.fromisoformat(p["exp"]) - val).days, 0.5) / 365
            p["iv"] = implied(p["price"], F, p["K"], p["T"], p["type"])
    # Put 現價可能 stale：HSI 月 Put 用 Call IV＋0.7
    ivs = {p["id"]: p for p in b["positions"] if p["type"] != "fut"}
    c, pu = ivs.get("MHI 10/29 C25000"), ivs.get("MHI 10/29 P25000")
    if c and pu:
        pu["iv_raw"] = pu["iv"]
        pu["iv"] = c["iv"] + 0.007
    return b, fx


def value(p, F, iv_shift=0.0):
    if p["type"] == "fut":
        return F
    return b76(F, p["K"], p["iv"] + iv_shift, p["T"], p["type"])


def pnl_hkd(b, fx, shocks, vol_down=0.5, vol_add=0.0):
    """shocks: {'HSI': pct, 'ES': pct}；回傳總盈虧(HKD)、分組盈虧。"""
    tot, grp = 0.0, {}
    for p in b["positions"]:
        F0 = b["underlyings"][p["und"]]["F"]
        r = shocks.get(p["und"], 0.0)
        F = F0 * (1 + r)
        shift = vol_add + (max(0.0, -r) * 100 * vol_down / 100 if p["type"] != "fut" else 0.0)
        v = value(p, F, shift)
        x = (v - p["open"]) * p["qty"] * p["mult"] * fx[p["ccy"]]
        tot += x
        g = p.get("group", p["id"])
        grp[g] = grp.get(g, 0.0) + x
    return tot, grp


def greeks(b, fx):
    out = {}
    for p in b["positions"]:
        F0 = b["underlyings"][p["und"]]["F"]
        h = 0.005
        up = (value(p, F0 * (1 + h)) - value(p, F0 * (1 - h))) / (2 * F0 * h)      # 每點價格變動 Δ
        gam = (value(p, F0 * (1 + h)) - 2 * value(p, F0) + value(p, F0 * (1 - h))) / ((F0 * h) ** 2)
        veg = (value(p, F0, 0.01) - value(p, F0)) if p["type"] != "fut" else 0.0   # 每 +1 vol pt
        k = p["qty"] * p["mult"] * fx[p["ccy"]]
        o = out.setdefault(p["und"], {"d1pct": 0.0, "dpts": 0.0, "vega": 0.0, "gamma1pct": 0.0})
        o["dpts"] += up * k
        o["d1pct"] += up * k * F0 * 0.01
        o["vega"] += veg * k
        o["gamma1pct"] += gam * k * (F0 * 0.01) ** 2 * 0.5
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=str(HERE / "data_external" / "risk_book.json"))
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    b, fx = load(a.book)
    nav, hs = b["nav_hkd"], b["hard_stop_equity_hkd"]
    budget = nav - hs
    L = []
    P = L.append
    P(f"# 持倉風險報告（資料時點 {b['asof']}）")
    P(f"NAV 假設 HK${nav:,.0f}；硬止損權益 < HK${hs:,.0f}（可承受總虧損 HK${budget:,.0f}）；USD/HKD {fx['USD']}")
    if b.get("nav_note"):
        P(f"⚠ {b['nav_note']}")
    P("")

    P("## 1. 現況盈虧（Futu 現價＝最後成交）")
    tot, grp = pnl_hkd(b, fx, {})
    for g, v in grp.items():
        P(f"- {g}：{v:+,.0f} HKD")
    P(f"- **合共 {tot:+,.0f} HKD**（Futu 截圖 +12,771）\n")

    P("## 2. 名義值與到期")
    notl = {}
    for p in b["positions"]:
        if p["type"] == "fut":
            continue
        n = p["K"] * p["mult"] * fx[p["ccy"]]
        P(f"- {p['id']}：名義 HK${n:,.0f}（{n / nav:.1f}× NAV），{round(p['T'] * 365)} 天到期，IV {p['iv'] * 100:.1f}%"
          + (f"  ⚠ {p['flag']}" if p.get("flag") else ""))
    P("")

    P("## 3. Greeks（合共，HKD）")
    for u, o in greeks(b, fx).items():
        P(f"- {u}：Δ 每 1% 變動 {o['d1pct']:+,.0f}；每點 {o['dpts']:+,.1f}；Γ 效應（1% 變動）{o['gamma1pct']:+,.0f}；Vega 每 +1 vol {o['vega']:+,.0f}")
    P("")

    P("## 4. 止損線（買回總價 ≥ 2×權利金）")
    px = {p["id"]: p["price"] for p in b["positions"]}
    for name, s in b["stops"].items():
        bb = sum(px[i] for i in s["legs"])
        P(f"- {name}：買回約 {bb:.1f} 點 vs 止損 {s['stop_buyback']} 點（用咗 {bb / s['stop_buyback'] * 100:.0f}%；權利金 {s['credit']}）")
    P("")

    P("## 5. 壓力測試（即時重估，唔計時間流逝）")
    P("下跌時 IV 每跌 1% 加 0.5 vol pt（偏斜近似）。**總盈虧＝由開倉起計；權益＝NAV＋總盈虧。**\n")
    mg = b.get("margin")
    buf0 = (mg["equity_hkd"] - mg["maintenance_hkd"]) if mg else None
    t0, _ = pnl_hkd(b, fx, {})
    P("| 情景 | 總盈虧 HKD | 權益 HKD | 離硬止損 | 保證金緩衝 | 備註 |")
    P("|---|---:|---:|---:|---:|---|")
    rows = []
    for name, sh, va in (
        ("現況", {}, 0),
        ("ES −2%", {"ES": -.02}, 0), ("ES −3%", {"ES": -.03}, 0), ("ES −5%", {"ES": -.05}, 0),
        ("ES +3%", {"ES": .03}, 0),
        ("HSI +2%", {"HSI": .02}, 0), ("HSI +3%", {"HSI": .03}, 0), ("HSI +5%", {"HSI": .05}, 0),
        ("HSI −3%", {"HSI": -.03}, 0), ("HSI −5%", {"HSI": -.05}, 0),
        ("兩邊同跌 −3%", {"HSI": -.03, "ES": -.03}, 0),
        ("兩邊同跌 −5%", {"HSI": -.05, "ES": -.05}, 0),
        ("HSI +3%、ES −3%", {"HSI": .03, "ES": -.03}, 0),
        ("IV 全面 +5 vol（價平）", {}, .05),
        ("ES −3% 且 IV +5 vol", {"ES": -.03}, .05),
    ):
        t, _ = pnl_hkd(b, fx, sh, vol_add=va)
        eq = nav + t
        gap = eq - hs
        note = "⚠ 已觸硬止損" if gap < 0 else ("⚠ 近硬止損" if gap < 0.3 * budget else "")
        buf = (buf0 + t - t0) if buf0 is not None else None
        if buf is not None and buf < 0:
            note = (note + " " if note else "") + "⚠ 保證金緩衝蝕光"
        rows.append((name, t, eq, gap))
        P(f"| {name} | {t:+,.0f} | {eq:,.0f} | {gap:+,.0f} | {'-' if buf is None else format(buf, '+,.0f')} | {note} |")
    P("")

    P("## 6. 觸及硬止損所需變動（逐單一市場掃描）")
    for und, sign, lab in (("ES", -1, "ES 下跌"), ("HSI", 1, "HSI 上升"), ("HSI", -1, "HSI 下跌")):
        hit = None
        for k in range(1, 101):
            r = sign * k / 200
            t, _ = pnl_hkd(b, fx, {und: r})
            if nav + t < hs:
                hit = r
                break
        F0 = b["underlyings"][und]["F"]
        P(f"- {lab}：" + (f"約 {abs(hit) * 100:.1f}%（{und} ≈ {F0 * (1 + hit):,.0f}）觸硬止損" if hit else "50% 內唔觸及"))
    P("")
    if buf0 is not None:
        P(f"## 6b. 觸及保證金緩衝所需變動（緩衝 HK${buf0:,.0f}，保證金假設不變；跌市時保證金會加，實際更早）")
        for und, sign, lab in (("ES", -1, "ES 下跌"), ("HSI", 1, "HSI 上升"), ("HSI", -1, "HSI 下跌")):
            hit = None
            for k in range(1, 101):
                r_ = sign * k / 200
                t, _ = pnl_hkd(b, fx, {und: r_})
                if buf0 + t - t0 < 0:
                    hit = r_
                    break
            F0 = b["underlyings"][und]["F"]
            P(f"- {lab}：" + (f"約 {abs(hit) * 100:.1f}%（{und} ≈ {F0 * (1 + hit):,.0f}）蝕光緩衝" if hit else "50% 內唔蝕光"))
        P("")
    P("## 7. 假設與限制")
    P("- 壓力測試只做即時重估，冇計時間價值消耗、冇計保證金追繳、冇計滑價及夜市流動性。")
    P("- Put 現價 stale、EW 到期日待確認、對沖腳開倉價待確認（見 risk_book.json 各 flag）。")
    P("- IV 由現價反推，單一 IV 未計斜率；下跌時 Put 實際價格可能更高。")
    txt = "\n".join(L)
    print(txt)
    if a.md:
        Path(a.md).write_text(txt + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
