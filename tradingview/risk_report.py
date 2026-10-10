#!/usr/bin/env python3
"""持倉風險報告：讀 data_external/risk_book.json → 重估 Greeks → 壓力測試 → 對照 HK$750,000 硬止損。
純計算，不連任何券商。用 Black-76（期貨期權），IV 由現價逐腿反推（每腿各自 IV＝現時嘅斜率快照）。
現價唔可靠嘅腿可以喺 book 寫 "mark": {"method": "parity", "call": "<同行使價 Call id>"}，改用 put-call parity 定價。
用法：python3 risk_report.py [--book data_external/risk_book.json] [--md risk_report.md]
"""
import argparse
import json
from datetime import date
from math import erf, log, sqrt
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
    by_id = {p["id"]: p for p in b["positions"]}
    for p in b["positions"]:
        p["mark_px"] = p["price"]
        if p["type"] in ("call", "put"):
            p["T"] = max((date.fromisoformat(p["exp"]) - val).days, 0.5) / 365
    for p in b["positions"]:
        mk = p.get("mark")
        if mk and mk.get("method") == "parity":
            # 期貨期權 parity（折現 < 0.5%，忽略）：P = C + (K − F)；C = P − (K − F)
            F = b["underlyings"][p["und"]]["F"]
            other = by_id[mk["call"]]["price"]
            p["mark_px"] = other + (p["K"] - F) if p["type"] == "put" else other - (p["K"] - F)
    for p in b["positions"]:
        if p["type"] in ("call", "put"):
            F = b["underlyings"][p["und"]]["F"]
            p["iv"] = implied(p["mark_px"], F, p["K"], p["T"], p["type"])
            if p["mark_px"] != p["price"]:
                p["iv_raw"] = implied(p["price"], F, p["K"], p["T"], p["type"])
    return b, fx


def value(p, F, iv_shift=0.0, days=0.0):
    if p["type"] == "fut":
        return F
    return b76(F, p["K"], p["iv"] + iv_shift, p["T"] - days / 365, p["type"])


def pnl_hkd(b, fx, shocks, vol_down=0.5, vol_add=0.0, days=0.0):
    """shocks: {'HSI': pct, 'ES': pct}；days：時間前推日數。回傳總盈虧(HKD)、分組盈虧。"""
    tot, grp = 0.0, {}
    for p in b["positions"]:
        F0 = b["underlyings"][p["und"]]["F"]
        r = shocks.get(p["und"], 0.0)
        F = F0 * (1 + r)
        shift = vol_add + (max(0.0, -r) * vol_down if p["type"] != "fut" else 0.0)
        v = value(p, F, shift, days)
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
        th = (value(p, F0, 0, 1) - value(p, F0)) if p["type"] != "fut" else 0.0    # 每過 1 曆日
        k = p["qty"] * p["mult"] * fx[p["ccy"]]
        o = out.setdefault(p["und"], {"d1pct": 0.0, "dpts": 0.0, "vega": 0.0, "gamma1pct": 0.0, "theta": 0.0})
        o["dpts"] += up * k
        o["d1pct"] += up * k * F0 * 0.01
        o["vega"] += veg * k
        o["theta"] += th * k
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
    P(f"NAV 假設 HK${nav:,.0f}；硬止損權益 < HK${hs:,.0f}（可承受總虧損 HK${budget:,.0f}）；USD/HKD {fx['USD']}\n")

    P("## 1. 現況盈虧")
    tot, grp = pnl_hkd(b, fx, {})
    raw_hkd = sum((p["price"] - p["open"]) * p["qty"] * p["mult"] for p in b["positions"] if p["ccy"] == "HKD")
    raw_usd = sum((p["price"] - p["open"]) * p["qty"] * p["mult"] for p in b["positions"] if p["ccy"] == "USD")
    for g, v in grp.items():
        P(f"- {g}：{v:+,.0f} HKD")
    P(f"- **模型標價合共 {tot:+,.0f} HKD**（stale 腿用 parity）")
    P(f"- 純用 Futu 最後成交價：HKD 腿 {raw_hkd:+,.0f}、USD 腿 {raw_usd:+,.2f} USD → @{fx['USD']} 合共 {raw_hkd + raw_usd * fx['USD']:+,.0f} HKD")
    fs = b.get("futu_screenshot", {}).get("holding_pl_hkd")
    if fs and raw_usd:
        P(f"- 對帳：Futu 截圖 {fs:+,.2f}；用最後成交價反推 Futu 匯率 ≈ {(fs - raw_hkd) / raw_usd:.4f}。"
          "差額全部來自 ① stale 腿改用模型標價 ② 匯率")
    for p in b["positions"]:
        if p["mark_px"] != p["price"]:
            P(f"  - {p['id']}：最後成交 {p['price']:g} → 標價 {p['mark_px']:g}（{p['mark']['method']}；"
              f"影響 {(p['mark_px'] - p['price']) * p['qty'] * p['mult'] * fx[p['ccy']]:+,.0f} HKD）")
    P("")

    P("## 2. 名義值、到期、交收")
    for p in b["positions"]:
        if p["type"] == "fut":
            continue
        n = p["K"] * p["mult"] * fx[p["ccy"]]
        iv = f"IV {p['iv'] * 100:.1f}%" + (f"（stale 價反推 {p['iv_raw'] * 100:.1f}%）" if "iv_raw" in p else "")
        P(f"- {p['id']}：名義 HK${n:,.0f}（{n / nav:.1f}× NAV），{p['exp']}（{round(p['T'] * 365)} 天），{iv}"
          + (f"；交收 {p['settle']}" if p.get("settle") else "")
          + (f"  ⚠ {p['flag']}" if p.get("flag") else ""))
    P("")
    ew = next((p for p in b["positions"] if p["id"].startswith("EW")), None)
    if ew:
        P("### 2b. EW 到期日合理性（同一現價、唔同到期日反推 IV）")
        F = b["underlyings"][ew["und"]]["F"]
        val = date.fromisoformat(b["valuation_date"])
        ref = [f"{p['id']} {p['iv'] * 100:.1f}%" for p in b["positions"] if p["und"] == ew["und"] and p is not ew and p["type"] != "fut"]
        for d in ("2026-10-16", "2026-10-23", "2026-10-30", "2026-11-20"):
            T = (date.fromisoformat(d) - val).days / 365
            P(f"- 若到期 {d}：IV {implied(ew['price'], F, ew['K'], T, ew['type']) * 100:.1f}%")
        P(f"- 參考同標的：{'、'.join(ref)}。價外 1.4% 嘅 put 有正斜率，IV 應略高於價平但唔會翻倍 → 10/30 最吻合；"
          "Δ 對到期日唔敏感（價格固定時 σ√T 不變），所以 Futu Δ 不能用嚟分辨到期日。\n")

    P("## 3. Greeks（合共，HKD）")
    for u, o in greeks(b, fx).items():
        P(f"- {u}：Δ 每 1% 變動 {o['d1pct']:+,.0f}；每點 {o['dpts']:+,.1f}；Γ 效應（1% 變動）{o['gamma1pct']:+,.0f}；"
          f"Vega 每 +1 vol {o['vega']:+,.0f}；Θ 每日 {o['theta']:+,.0f}")
    P("")

    P("## 4. 止損線（買回總價 ≥ 2×權利金）")
    px = {p["id"]: p["mark_px"] for p in b["positions"]}
    for name, s in b["stops"].items():
        bb = sum(px[i] for i in s["legs"])
        P(f"- {name}：買回約 {bb:.1f} 點 vs 止損 {s['stop_buyback']} 點（用咗 {bb / s['stop_buyback'] * 100:.0f}%；權利金 {s['credit']}）")
    P("- HSI 週權 strangle、EW P7750：**冇登記止損規則**（開倉計劃喺其他分支，見 RISK_HANDOFF）")
    P("")

    P("## 5. 壓力測試（即時重估）")
    P("下跌時每跌 1% 加 0.5 vol pt（偏斜近似）。**總盈虧＝由開倉起計；權益＝NAV＋總盈虧。**\n")
    P("| 情景 | 總盈虧 HKD | 權益 HKD | 離硬止損 | 備註 |")
    P("|---|---:|---:|---:|---|")
    for name, sh, va, dd in (
        ("現況", {}, 0, 0),
        ("ES −2%", {"ES": -.02}, 0, 0), ("ES −3%", {"ES": -.03}, 0, 0), ("ES −5%", {"ES": -.05}, 0, 0),
        ("ES +3%", {"ES": .03}, 0, 0),
        ("HSI +2%", {"HSI": .02}, 0, 0), ("HSI +3%", {"HSI": .03}, 0, 0), ("HSI +5%", {"HSI": .05}, 0, 0),
        ("HSI −3%", {"HSI": -.03}, 0, 0), ("HSI −5%", {"HSI": -.05}, 0, 0),
        ("兩邊同跌 −3%", {"HSI": -.03, "ES": -.03}, 0, 0),
        ("兩邊同跌 −5%", {"HSI": -.05, "ES": -.05}, 0, 0),
        ("HSI +3%、ES −3%", {"HSI": .03, "ES": -.03}, 0, 0),
        ("IV 全面 +5 vol", {}, .05, 0),
        ("ES −3% 且 IV +5 vol", {"ES": -.03}, .05, 0),
        ("價不變，過 3 日（週一收市）", {}, 0, 3),
        ("價不變，過 6 日（10/16 週權到期）", {}, 0, 6),
        ("過 3 日且 ES −3%", {"ES": -.03}, 0, 3),
    ):
        t, _ = pnl_hkd(b, fx, sh, vol_add=va, days=dd)
        gap = nav + t - hs
        note = "⚠ 已觸硬止損" if gap < 0 else ("⚠ 近硬止損" if gap < 0.3 * budget else "")
        P(f"| {name} | {t:+,.0f} | {nav + t:,.0f} | {gap:+,.0f} | {note} |")
    P("")

    P("## 6. 觸及硬止損所需變動（逐單一市場掃描）")
    for und, sign, lab in (("ES", -1, "ES 下跌"), ("ES", 1, "ES 上升"), ("HSI", 1, "HSI 上升"), ("HSI", -1, "HSI 下跌")):
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

    P("## 7. 雙市場格（權益 HKD；✗＝低於硬止損）")
    steps = (-.05, -.04, -.03, -.02, -.01, 0, .01, .02, .03)
    P("| HSI ＼ ES | " + " | ".join(f"{s * 100:+.0f}%" for s in steps) + " |")
    P("|---|" + "---:|" * len(steps))
    for h in (-.05, -.03, -.01, 0, .01, .03, .05):
        cells = []
        for e in steps:
            t, _ = pnl_hkd(b, fx, {"HSI": h, "ES": e})
            cells.append(f"{(nav + t) / 1000:,.0f}k" + (" ✗" if nav + t < hs else ""))
        P(f"| HSI {h * 100:+.0f}% | " + " | ".join(cells) + " |")
    P("")

    P("## 8. 假設與限制")
    P("- 每腿 IV 由現價各自反推（已包含當刻斜率）；壓力情景用固定斜率近似（跌 1% 加 0.5 vol），未模擬 sticky-delta。")
    P("- 冇計保證金追繳（SPAN 由交易所／券商計，請以富途「維持保證金」為準）、冇計滑價及夜市流動性。")
    P("- MES／EW 到期 ITM 會交收成期貨（實物），唔係現金結算；到期前要決定平倉或轉倉。")
    P("- 對沖腳舊倉買回價未知 → 已實現盈虧未計（見 position.json hedge_history）。")
    txt = "\n".join(L)
    print(txt)
    if a.md:
        Path(a.md).write_text(txt + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
