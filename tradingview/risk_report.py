#!/usr/bin/env python3
"""持倉風險報告：讀 data_external/risk_book.json（＋可選 futu_positions.json 真實報價）→ 重估 Greeks → 壓力測試 → 對照硬止損。
純計算，不連任何券商。Black-76（期貨期權）。

定價規則（每腿）：
  平倉價：空倉用「賣價」買回、多倉用「買價」沽出（主數字）；「中間價」做對照。
  冇單邊價 → 同行使價另一邊 parity（P = C + (K − F)）→ 最後成交 → 截圖價；每個價都標明來源同報價時間。
  IV 由中間價反推（冇中間價就用平倉價）。
斜率：每個標的用各腿 (ln K/F, IV) 擬合斜率；壓力情景固定行使價 IV 按「IV 變動 = 斜率 × ln(F新/F舊)」（跌市升 vol），
  另列舊規則（每跌 1% 加 0.5 vol）對照。
用法：python3 risk_report.py [--book …] [--quotes data_external/futu_positions.json] [--md out/risk_report_live.md]
"""
import argparse
import json
import os
import re
from datetime import date
from math import erf, log, sqrt
from pathlib import Path

N = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
HERE = Path(__file__).resolve().parent
DEFAULT_UND_CODES = {"HSI": ["HK.MHI2610", "HK.HSImain"], "ES": ["US.ES2612", "US.ESmain", "US.MES2612", "US.MESmain"]}
LOT = {"HSI": ("MHI", 10, "HKD"), "ES": ("MES", 5, "USD")}       # Δ 用嘅「手」單位
# 雲垂陣劇本：月跨式＋對沖 淨 Δ 界線（MHI 手）；book 可用 "playbook" 覆寫
# 止損規則（book 冇寫先用呢度；持倉唔喺 book 就略過）
DEFAULT_STOPS = {"EW P7750": {"credit": 43, "stop_buyback": 86, "legs": ["EW2610 P7750"],
                              "note": "使用者人手開；10/14 03:51 新倉 @43，使用者 10-14 定：買回價 ≥ 86 點（2× 權利金，舊倉 @68 係 136）"}}
PLAYBOOK = {"雲垂陣 HSI 月跨式＋對沖": {"und": "HSI", "groups": ["HSI 月跨式", "MHI2610 對沖"], "band": 0.5}}


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


def derive_code(p):
    """富途代碼：book 有就用；恒指／MHI 按已驗證格式推算；標普期貨期權未知 → None。"""
    if p.get("code"):
        return p["code"]
    if p["und"] == "ES":                 # 富途格式（2026-10-10 API 確認）：US.EW2610P7750x0、US.EX32610C7830x0
        cp, ym, K = "C" if p["type"] == "call" else "P", p["exp"][2:4] + p["exp"][5:7], int(p["K"])
        if p["id"].startswith("EW"):
            return f"US.EW{ym}{cp}{K}x0"
        if p["id"].startswith("MES"):
            wk = (int(p["exp"][8:10]) - 1) // 7 + 1        # 第幾個星期五 → EX1–EX4
            return f"US.EX{wk}{ym}{cp}{K}x0"
        return None
    if p["und"] != "HSI":
        return None
    if p["type"] == "fut":
        m = re.search(r"(MHI|HSI)(\d{4})", p["id"])
        return f"HK.{m.group(1)}{m.group(2)}" if m else None
    root = "MHI" if p["id"].startswith("MHI") else "HSI"
    return f"HK.{root}{p['exp'][2:].replace('-', '')}{'C' if p['type'] == 'call' else 'P'}{int(p['K'] * 1000):08d}"


YAHOO_SYMBOLS = {"ES": "ES=F"}   # [R183] 富途冇 CME 行情時嘅後備；設 ZHUGE_NO_YAHOO=1 停用


def yahoo_last(sym, timeout=6):
    """Yahoo Finance 延遲最後價（唔使金鑰）；失敗回 None，唔影響報告其他部分。"""
    if os.environ.get("ZHUGE_NO_YAHOO") == "1":
        return None
    import urllib.request
    try:
        req = urllib.request.Request(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            meta = json.loads(r.read().decode("utf-8"))["chart"]["result"][0]["meta"]
        px = meta.get("regularMarketPrice")
        return float(px) if px and px > 0 else None
    except Exception:
        return None


CME_MAX_AGE_S = 90 * 60   # [R184] IB 延遲報價（ib-data VM 經 Cloud Run）超過 90 分鐘當過期唔用


def merge_cme_quotes(Q, path, now_ts=None):
    """[R184] 用 ib-data VM 嘅 IB 延遲報價補富途冇權限嘅 CME 合約（只補冇買賣價嘅代碼）。"""
    import time
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return 0
    if (now_ts or time.time()) - float(doc.get("received_ts") or 0) > CME_MAX_AGE_S:
        return 0
    n = 0
    for code, q in (doc.get("quotes") or {}).items():
        have = Q.get(code) or {}
        if (have.get("bid") or 0) > 0 and (have.get("ask") or 0) > 0:
            continue
        bid, ask = q.get("bid"), q.get("ask")
        mid = (bid + ask) / 2 if bid and ask else None
        Q[code] = {"bid": bid, "ask": ask, "mid": mid, "last": q.get("last") or q.get("close"),
                   "quote_time": f"{q.get('quote_time') or doc.get('fetched_utc')} UTC（IB 延遲約 15 分鐘）"}
        n += 1
    return n


def load(book_path, quotes_path=None):
    b = json.loads(Path(book_path).read_text(encoding="utf-8"))
    qf = json.loads(Path(quotes_path).read_text(encoding="utf-8")) if quotes_path else {}
    Q = dict(qf.get("quotes", {}))
    for r in qf.get("positions", []):          # 舊格式：只有 positions 行
        Q.setdefault(r["code"], {k: r.get(k) for k in ("bid", "ask", "mid", "last", "quote_time")})
    FP = {r["code"]: r for r in qf.get("positions", [])}
    merge_cme_quotes(Q, Path(book_path).with_name("cme_quotes.json"))
    # 富途實際恒指期貨淨手數 vs book（例如人手即日 MHI）：多出／少咗嘅當一條「人手」期貨腿計入模型
    b["fut_lots"] = {}
    for code, r in FP.items():
        m = re.match(r"^HK\.(MHI|HSI)\d{4}$", code)
        if not m or not r.get("qty"):
            continue
        b["fut_lots"][code] = r["qty"]
        booked = sum(p["qty"] for p in b["positions"] if p["type"] == "fut" and derive_code(p) == code)
        extra = r["qty"] - booked
        if extra:
            b["positions"].append({"id": f"{code[3:]} 人手（富途實際 {r['qty']:+g}、book {booked:+g}）", "und": "HSI",
                                   "type": "fut", "qty": extra, "mult": 10 if m.group(1) == "MHI" else 50, "ccy": "HKD",
                                   "open": r.get("open_price") or r.get("last") or 0, "price": r.get("last") or 0,
                                   "code": code, "group": "恒指期貨人手"})
    # [R182] 富途實際標普期貨（ES／MES，例如使用者人手對沖 EW put）：book 冇就當一條「標普期貨人手」腿計入模型
    for code, r in FP.items():
        m = re.match(r"^US\.(ES|MES)\d{4}$", code)
        if not m or not r.get("qty"):
            continue
        booked = sum(p["qty"] for p in b["positions"] if p.get("code") == code)
        extra = r["qty"] - booked
        if extra:
            b["positions"].append({"id": f"{code[3:]} 人手（富途實際 {r['qty']:+g}）", "und": "ES", "type": "fut", "qty": extra,
                                   "mult": 50 if m.group(1) == "ES" else 5, "ccy": "USD",
                                   "open": r.get("open_price") or r.get("last") or 0, "price": r.get("last") or r.get("open_price") or 0,
                                   "code": code, "group": "標普期貨人手"})
    b["quotes_fetched"] = qf.get("fetched_hkt")
    b["accounts"] = qf.get("accounts", [])
    val = date.fromisoformat(b["valuation_date"])
    for u, d in b["underlyings"].items():
        d["F_src"] = f"截圖／book（{d.get('note', '')}）"
        for c in d.get("codes", DEFAULT_UND_CODES.get(u, [])):
            q = Q.get(c) or {}
            px, lab = (q.get("mid"), "中間價") if q.get("mid") else (q.get("last"), "最後成交")
            if px:
                d["F"], d["F_src"] = px, f"{c} {lab} @ {q.get('quote_time')}"
                break
        else:
            # [R183] 冇期貨報價（CME 冇行情權限）：先試 Yahoo 延遲報價（ES=F 連續合約，約延遲 10 分鐘）
            yp = yahoo_last(YAHOO_SYMBOLS.get(u)) if YAHOO_SYMBOLS.get(u) else None
            if yp:
                d["F"], d["F_src"] = yp, f"Yahoo {YAHOO_SYMBOLS[u]} 延遲報價（約 10 分鐘）"
                continue
            # [R182] 再唔得：有標普期貨持倉就由富途持倉盈虧反推富途用緊嘅期貨價
            for c, r in FP.items():
                fm = re.match(r"^US\.(ES|MES)\d{4}$", c) if u == "ES" else None
                if fm and r.get("qty") and r.get("futu_pl") is not None and r.get("open_price"):
                    mult = 50 if fm.group(1) == "ES" else 5
                    d["F"] = r["open_price"] + r["futu_pl"] / (r["qty"] * mult)
                    d["F_src"] = f"{c} 富途持倉估值（由持倉盈虧反推；冇行情權限）"
                    break
    by_id = {p["id"]: p for p in b["positions"]}
    for p in b["positions"]:
        p["code"] = derive_code(p)
        q = Q.get(p["code"]) or {} if p["code"] else {}
        ok = lambda x: x if x and x > 0 else None          # 冇行情權限時富途回傳 0
        p.update(bid=ok(q.get("bid")), ask=ok(q.get("ask")), mid=ok(q.get("mid")), last=ok(q.get("last")), qtime=q.get("quote_time") or None)
        if p["type"] in ("call", "put"):
            p["T"] = max((date.fromisoformat(p["exp"]) - val).days, 0.5) / 365
    for p in b["positions"]:
        side = p["ask"] if p["qty"] < 0 else p["bid"]
        if side:
            p["close_px"], p["basis"] = side, ("賣價" if p["qty"] < 0 else "買價") + f" @ {p['qtime']}"
            continue
        stale = any(w in p.get("flag", "") for w in ("冇賣價", "冇買價", "stale"))
        other = next((o for o in b["positions"] if o is not p and o["und"] == p["und"] and o.get("K") == p.get("K")
                      and o.get("exp") == p.get("exp") and o["type"] in ("call", "put") and o["type"] != p["type"]), None)
        has_q = bool(p["bid"] or p["ask"] or p["last"])           # 有報價但欠一邊
        if p["type"] in ("call", "put") and other and (has_q or stale):
            F = b["underlyings"][p["und"]]["F"]
            o_px = (other["ask"] if other["qty"] < 0 else other["bid"]) or other.get("mid") or other.get("last") or other["price"]
            p["close_px"] = o_px + (p["K"] - F) if p["type"] == "put" else o_px - (p["K"] - F)
            p["basis"] = f"parity（冇{'賣' if p['qty'] < 0 else '買'}價；{other['id']} {o_px:g}）"
        elif p["last"]:
            p["close_px"], p["basis"] = p["last"], f"最後成交（冇{'賣' if p['qty'] < 0 else '買'}價）@ {p['qtime']}"
        elif (FP.get(p["code"]) or {}).get("futu_pl") is not None:
            # 冇報價（例如 CME 期權冇行情權限）：由富途持倉盈虧反推富途用緊嘅估值
            pl = FP[p["code"]]["futu_pl"]
            p["close_px"] = p["open"] - pl / (abs(p["qty"]) * p["mult"]) * (1 if p["qty"] < 0 else -1)
            p["basis"] = "富途持倉估值（由持倉盈虧反推；冇行情權限）"
        else:
            p["close_px"], p["basis"] = p["price"], "截圖價" + ("（冇富途代碼）" if not p["code"] else "")
    for p in b["positions"]:
        if p["type"] in ("call", "put"):
            F = b["underlyings"][p["und"]]["F"]
            p["iv"] = implied(p["mid"] or p["close_px"], F, p["K"], p["T"], p["type"])
            p["iv_src"] = "中間價" if p["mid"] else "平倉價"
    b["skew"] = {}
    for u in b["underlyings"]:
        F = b["underlyings"][u]["F"]
        pts = [(log(p["K"] / F), p["iv"]) for p in b["positions"] if p["und"] == u and p["type"] != "fut"]
        xs = {round(x, 6) for x, _ in pts}
        if len(xs) >= 2:
            mx, my = sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
            sl = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
            b["skew"][u] = (min(0.0, max(-3.0, sl)), f"擬合 {len(pts)} 腿")
        else:
            b["skew"][u] = (-0.5, "預設")
    return b, b["fx"]


def value(p, F, iv_shift=0.0, days=0.0):
    if p["type"] == "fut":
        return F
    return b76(F, p["K"], max(p["iv"] + iv_shift, p["iv"] * 0.5), p["T"] - days / 365, p["type"])


def pnl_hkd(b, fx, shocks, vol_add=0.0, days=0.0, skew="fit", px="close"):
    """shocks: {'HSI': pct, 'ES': pct}。skew='fit' 用擬合斜率；'old' 用每跌 1% 加 0.5 vol；px='close'/'mid' 現況標價。"""
    tot, grp = 0.0, {}
    for p in b["positions"]:
        F0 = b["underlyings"][p["und"]]["F"]
        r = shocks.get(p["und"], 0.0)
        if not shocks and not vol_add and not days:          # 現況：直接用報價
            v = p["close_px"] if px == "close" else (p["mid"] or p["close_px"])
        else:
            if skew == "fit":
                sh = b["skew"][p["und"]][0] * log(1 + r)
            else:
                sh = max(0.0, -r) * 0.5
            v = value(p, F0 * (1 + r), vol_add + sh, days)
            v += p["close_px"] - value(p, F0)                # 模型同平倉價之間嘅差（買賣差）保留
        x = (v - p["open"]) * p["qty"] * p["mult"] * fx[p["ccy"]]
        tot += x
        g = p.get("group", p["id"])
        grp[g] = grp.get(g, 0.0) + x
    return tot, grp


def greeks(b, fx):
    out, grp = {}, {}
    for p in b["positions"]:
        F0 = b["underlyings"][p["und"]]["F"]
        h = 0.005
        up = (value(p, F0 * (1 + h)) - value(p, F0 * (1 - h))) / (2 * F0 * h)
        gam = (value(p, F0 * (1 + h)) - 2 * value(p, F0) + value(p, F0 * (1 - h))) / ((F0 * h) ** 2)
        veg = (value(p, F0, 0.01) - value(p, F0)) if p["type"] != "fut" else 0.0
        th = (value(p, F0, 0, 1) - value(p, F0)) if p["type"] != "fut" else 0.0
        k = p["qty"] * p["mult"] * fx[p["ccy"]]
        o = out.setdefault(p["und"], {"d1pct": 0.0, "dpts": 0.0, "vega": 0.0, "gamma1pct": 0.0, "theta": 0.0})
        o["dpts"] += up * k
        o["d1pct"] += up * k * F0 * 0.01
        o["vega"] += veg * k
        o["theta"] += th * k
        o["gamma1pct"] += gam * k * (F0 * 0.01) ** 2 * 0.5
        unit, m, cur = LOT[p["und"]]
        g = p.get("group", p["id"])
        grp[g] = grp.get(g, (p["und"], 0.0))[0], grp.get(g, (p["und"], 0.0))[1] + up * k / (m * fx[cur])
    return out, grp


def group_delta_at(b, fx, und, groups, r):
    """標的變動 r 之後，指定組別嘅淨 Δ（手）。"""
    unit, m, cur = LOT[und]
    tot = 0.0
    for p in b["positions"]:
        if p["und"] != und or p.get("group", p["id"]) not in groups:
            continue
        F = b["underlyings"][und]["F"] * (1 + r)
        sh = b["skew"][und][0] * log(1 + r)
        h = 0.005
        d = (value(p, F * (1 + h), sh) - value(p, F * (1 - h), sh)) / (2 * F * h)
        tot += d * p["qty"] * p["mult"] / m
    return tot


def f(x, nd=2):
    return "—" if x is None else (f"{x:,.{nd}f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x))


def build(book, quotes=None, combined_equity=None):
    """出報告。回傳 (報告文字, 主要指標 dict)；auto_risk.py 用指標判斷警報。"""
    b, fx = load(book, quotes or None)
    M = {"stop_use": {}, "delta": {}, "margin_hit": {}}
    nav, hs = b["nav_hkd"], b["hard_stop_equity_hkd"]
    tot0, grp0 = pnl_hkd(b, fx, {})
    totm, _ = pnl_hkd(b, fx, {}, px="mid")
    acc = next((x for x in b["accounts"] if (x.get("total_assets") or 0) > 0 and x.get("currency", "HKD") == "HKD"), None)
    eq0 = combined_equity if combined_equity else nav + tot0
    budget = eq0 - hs
    M.update(quotes_fetched=b["quotes_fetched"], pnl=tot0, equity=eq0, hard_stop=hs, gap=budget)
    L = []
    P = L.append
    P(f"# 持倉風險報告")
    P(f"持倉：{b['asof']}（{b['source']}）")
    P(f"報價：{'富途 OpenD 快照 ' + b['quotes_fetched'] + ' HKT' if b['quotes_fetched'] else '冇報價檔 → 用截圖價（未係真實買賣價）'}")
    P(f"硬止損：權益 < HK${hs:,.0f}。"
      + (f"**合計權益（你提供）HK${eq0:,.0f}**" if combined_equity else f"合計權益＝假設 NAV HK${nav:,.0f}＋持倉盈虧 = HK${eq0:,.0f}（用 --combined-equity 填實數）")
      + f"；離硬止損 HK${budget:,.0f}；USD/HKD {fx['USD']}")
    if acc:
        cush = acc["total_assets"] - (acc.get("maintenance_margin") or 0)
        M.update(futu_equity=acc["total_assets"], cushion=cush, maintenance_margin=acc.get("maintenance_margin"))
        P(f"富途期貨戶口：權益 HK${acc['total_assets']:,.0f}，維持保證金 HK${acc.get('maintenance_margin') or 0:,.0f}，"
          f"**保證金緩衝 HK${cush:,.0f}**（跌穿 0 會被追保證金／斬倉；跌市時保證金通常再加）")
    M["mhi_lots"] = dict(b["fut_lots"]) or {
        derive_code(p): p["qty"] for p in b["positions"] if p["type"] == "fut" and derive_code(p)}
    P("恒指期貨淨手數（富途實際）：" + "、".join(f"{c} {q:+g}" for c, q in M["mhi_lots"].items()))
    P("")

    P("## 1. 價格來源（每腿）")
    P("| 持倉 | 富途代碼 | 買價 | 賣價 | 中間價 | 最後成交 | 報價時間 HKT | 用嚟平倉嘅價 | 來源 |")
    P("|---|---|---:|---:|---:|---:|---|---:|---|")
    for p in b["positions"]:
        P(f"| {p['id']} | {p['code'] or '未知'} | {f(p['bid'])} | {f(p['ask'])} | {f(p['mid'])} | {f(p['last'])} | {p['qtime'] or '—'} "
          f"| {p['close_px']:,.2f} | {p['basis']} |")
    for u, d in b["underlyings"].items():
        P(f"- 標的 {u}：F = {d['F']:,.2f}（{d['F_src']}）")
    P("")

    P("## 2. 現況盈虧（由開倉起計）")
    for g, v in grp0.items():
        P(f"- {g}：{v:+,.0f} HKD")
    P(f"- **合共（空倉用賣價買回）{tot0:+,.0f} HKD**；用中間價 {totm:+,.0f} HKD（差額＝買賣差成本 {totm - tot0:,.0f}）")
    fs = b.get("futu_screenshot", {}).get("holding_pl_hkd") or 12770.97
    P(f"- 對照：Futu 截圖持倉盈虧 +{fs:,.0f}（Futu 用最後成交價計，唔係平倉價）")
    if acc:
        P(f"- 保證金（富途）：初始 {f(acc.get('initial_margin'), 0)}、維持 {f(acc.get('maintenance_margin'), 0)}、現金 {f(acc.get('cash'), 0)}"
          + (f"；權益 / 維持保證金 = {acc['total_assets'] / acc['maintenance_margin']:.2f} 倍" if acc.get("maintenance_margin") else ""))
    else:
        P("- 保證金：未攞到（要 OpenD 登入 ID 改啱後先讀到富途資金）")
    P("")

    P("## 3. 名義值、到期、交收")
    for p in b["positions"]:
        if p["type"] == "fut":
            continue
        n = p["K"] * p["mult"] * fx[p["ccy"]]
        P(f"- {p['id']}：名義 HK${n:,.0f}（{n / eq0:.1f}× 合計權益），{p['exp']}（{round(p['T'] * 365)} 天），IV {p['iv'] * 100:.1f}%（{p['iv_src']}）"
          + (f"；{p['settle']}" if p.get("settle") else (
              "；到期 ITM 交收成期貨（實物）" if p["und"] == "ES" else "；現金結算")))
    P("")

    P("## 4. IV 斜率")
    for u, (sl, src) in b["skew"].items():
        P(f"- {u}：dIV/dln(K/F) = {sl:+.2f}（{src}）→ 標的每跌 1%，固定行使價 IV 約升 {-sl * 1:.2f} vol pt（舊規則 0.5）")
    P("- ⚠ 擬合混合咗唔同到期日（週權／月權），期限結構會令斜率偏大或偏細；只作近似。\n")

    P("## 5. Greeks（合共，HKD）")
    gk, gd = greeks(b, fx)
    for u, o in gk.items():
        unit, m, cur = LOT[u]
        P(f"- {u}：Δ 每 1% {o['d1pct']:+,.0f}；＝ {o['dpts'] / (m * fx[cur]):+.2f} 手 {unit}；Γ 效應（1%）{o['gamma1pct']:+,.0f}；"
          f"Vega 每 +1 vol {o['vega']:+,.0f}；Θ 每日 {o['theta']:+,.0f}")
    P("- 分組 Δ（手）：" + "；".join(f"{g} {d:+.2f} {LOT[u][0]}" for g, (u, d) in gd.items()))
    P("")

    P("## 6. 止損線（買回總價 ≥ 2×權利金，用平倉價）")
    px = {p["id"]: p["close_px"] for p in b["positions"]}
    byid = {p["id"]: p for p in b["positions"]}
    stops = {**{k: v for k, v in DEFAULT_STOPS.items() if all(l in byid for l in v["legs"])}, **b["stops"]}
    for name, s in stops.items():
        bb = sum(px[i] for i in s["legs"])
        M["stop_use"][name] = bb / s["stop_buyback"]
        und = byid[s["legs"][0]]["und"]
        F0 = b["underlyings"][und]["F"]
        trig = []
        for sign, lab in ((-1, "跌"), (1, "升")):          # 標的郁幾多，模型買回價會到止損（固定斜率、即時重估）
            for k in range(1, 301):
                r = sign * k / 1000
                v = sum(value(byid[i], F0 * (1 + r), b["skew"][und][0] * log(1 + r)) + byid[i]["close_px"] - value(byid[i], F0)
                        for i in s["legs"])
                if v >= s["stop_buyback"]:
                    trig.append(f"{und} {lab} {k / 10:.1f}%（≈ {F0 * (1 + r):,.0f}）")
                    break
        P(f"- {name}：買回 {bb:,.1f} 點 vs 止損 {s['stop_buyback']} 點（用咗 {bb / s['stop_buyback'] * 100:.0f}%）"
          + (f"；觸發約需 {'、或 '.join(trig)}" if trig else "；標的升跌 30% 內唔觸發")
          + (f"（{s['note']}）" if s.get("note") else ""))
    P("- HSI 週權 strangle：風揚陣「方向一」（每週五沽下週 1σ 勒式，**持有到期、唔止損、唔對沖**；"
      "research/hsi_futures_range/STRANGLE_1SIGMA.md）\n")

    P("## 7. 壓力測試")
    P("即時重估；買賣差保留（平倉價 − 模型價）。主欄＝擬合斜率；對照欄＝舊規則（跌 1% 加 0.5 vol）。權益＝現時權益＋變動。\n")
    P("| 情景 | 盈虧變動 HKD | 合計權益 HKD | 離硬止損 | 舊規則權益 | 富途保證金緩衝* | 備註 |")
    P("|---|---:|---:|---:|---:|---:|---|")
    cush0 = (acc["total_assets"] - (acc.get("maintenance_margin") or 0)) if acc else None
    for name, sh, va, dd in (
        ("ES −2%", {"ES": -.02}, 0, 0), ("ES −3%", {"ES": -.03}, 0, 0), ("ES −5%", {"ES": -.05}, 0, 0),
        ("ES +3%", {"ES": .03}, 0, 0),
        ("HSI +2%", {"HSI": .02}, 0, 0), ("HSI +3%", {"HSI": .03}, 0, 0), ("HSI +5%", {"HSI": .05}, 0, 0),
        ("HSI −3%", {"HSI": -.03}, 0, 0), ("HSI −5%", {"HSI": -.05}, 0, 0),
        ("兩邊同跌 −3%", {"HSI": -.03, "ES": -.03}, 0, 0),
        ("HSI +3%、ES −3%", {"HSI": .03, "ES": -.03}, 0, 0),
        ("IV 全面 +5 vol", {}, .05, 0),
        ("ES −3% 且 IV +5 vol", {"ES": -.03}, .05, 0),
        ("價不變，過 3 日（週一收市）", {}, 0, 3),
        ("價不變，過 6 日（10/16 到期）", {}, 0, 6),
        ("過 3 日且 ES −3%", {"ES": -.03}, 0, 3),
    ):
        t, _ = pnl_hkd(b, fx, sh, vol_add=va, days=dd)
        t_old, _ = pnl_hkd(b, fx, sh, vol_add=va, days=dd, skew="old")
        d, eq = t - tot0, eq0 + t - tot0
        gap = eq - hs
        note = "⚠ 已觸硬止損" if gap < 0 else ("⚠ 近硬止損" if gap < 0.3 * budget else "")
        cu = "—" if cush0 is None else f"{cush0 + d:,.0f}"
        P(f"| {name} | {d:+,.0f} | {eq:,.0f} | {gap:+,.0f} | {eq0 + t_old - tot0:,.0f} | {cu} | {note} |")
    P("\n*富途保證金緩衝＝富途戶口權益＋變動 − 現時維持保證金；未計保證金本身隨市況上升，實際更緊。\n")

    P("## 8. 觸及硬止損所需變動（單一市場）")
    for und, sign, lab in (("ES", -1, "ES 下跌"), ("ES", 1, "ES 上升"), ("HSI", 1, "HSI 上升"), ("HSI", -1, "HSI 下跌")):
        hit = None
        for k in range(1, 101):
            r = sign * k / 200
            t, _ = pnl_hkd(b, fx, {und: r})
            if eq0 + t - tot0 < hs:
                hit = r
                break
        F0 = b["underlyings"][und]["F"]
        P(f"- {lab}：" + (f"約 {abs(hit) * 100:.1f}%（{und} ≈ {F0 * (1 + hit):,.0f}）" if hit else "50% 內唔觸及"))
    if acc and acc.get("maintenance_margin"):
        cush0 = acc["total_assets"] - acc["maintenance_margin"]
        P(f"\n富途保證金緩衝（HK${cush0:,.0f}）跌穿 0 所需變動（保證金當不變；實際會更早）：")
        for und, sign, lab in (("ES", -1, "ES 下跌"), ("HSI", 1, "HSI 上升"), ("HSI", -1, "HSI 下跌")):
            hit = None
            for k in range(1, 101):
                r = sign * k / 200
                t, _ = pnl_hkd(b, fx, {und: r})
                if cush0 + t - tot0 < 0:
                    hit = r
                    break
            F0 = b["underlyings"][und]["F"]
            M["margin_hit"][lab] = hit
            P(f"- {lab}：" + (f"約 {abs(hit) * 100:.1f}%（{und} ≈ {F0 * (1 + hit):,.0f}）" if hit else "50% 內唔跌穿"))
    P("")

    P("## 9. 雙市場格（權益 HKD；✗＝低於硬止損）")
    steps = (-.05, -.04, -.03, -.02, -.01, 0, .01, .02, .03)
    P("| HSI ＼ ES | " + " | ".join(f"{s * 100:+.0f}%" for s in steps) + " |")
    P("|---|" + "---:|" * len(steps))
    for h in (-.05, -.03, -.01, 0, .01, .03, .05):
        cells = []
        for e in steps:
            t, _ = pnl_hkd(b, fx, {"HSI": h, "ES": e}) if (h or e) else (tot0, None)
            eq = eq0 + t - tot0
            cells.append(f"{eq / 1000:,.0f}k" + (" ✗" if eq < hs else ""))
        P(f"| HSI {h * 100:+.0f}% | " + " | ".join(cells) + " |")
    P("")

    P("## 10. 同劇本衝突")
    pb = b.get("playbook", PLAYBOOK)
    for name, r in pb.items():
        d0 = group_delta_at(b, fx, r["und"], r["groups"], 0)
        M["delta"][name] = (d0, r["band"])
        st = "❌ 超出" if abs(d0) > r["band"] else ("⚠ 接近" if abs(d0) > 0.8 * r["band"] else "✅ 界線內")
        P(f"- {name}：淨 Δ {d0:+.2f} 手（界線 ±{r['band']}）{st}")
        for sign, lab in ((1, "上升"), (-1, "下跌")):
            hit = next((sign * k / 1000 for k in range(1, 201) if abs(group_delta_at(b, fx, r["und"], r["groups"], sign * k / 1000)) > r["band"]), None)
            P(f"  - {r['und']} {lab}" + (f" {abs(hit) * 100:.1f}%（≈ {b['underlyings'][r['und']]['F'] * (1 + hit):,.0f}）就超出界線" if hit else " 20% 內唔超出"))
    hs_all = gk["HSI"]["dpts"] / 10
    M["delta_parts"] = {"straddle": group_delta_at(b, fx, "HSI", ["HSI 月跨式"], 0),     # [R154] 雲垂月跨式 Δ（唔含對沖）
                        "net_with_hedge": next(iter(M["delta"].values()), (None,))[0],   # 含對沖淨 Δ
                        "hsi_all": hs_all}                                               # 恒指全部淨 Δ（連週權、人手倉）
    P(f"- 恒指全部（連週權）Δ {hs_all:+.2f} 手 MHI：週權唔屬雲垂陣，但同一個戶口、同一個硬止損，Δ 會互相抵消或疊加。")
    ew = next((p for p in b["positions"] if p["id"].startswith("EW")), None)
    P(f"- 標普：Δ {gk['ES']['dpts'] / (5 * fx['USD']):+.2f} 手 MES，冇任何對沖規則"
      + (f"；EW P7750 名義 {ew['K'] * ew['mult'] * fx[ew['ccy']] / eq0:.1f}× 合計權益，ES 下跌係硬止損同富途保證金嘅主要風險。" if ew else "。"))
    P("")

    P("## 11. 假設與限制")
    P("- 模型同報價之間嘅差（買賣差）喺壓力情景保留不變；夜市買賣差通常較闊。")
    P("- 冇計保證金追繳時點、滑價、跳空；MES／EW 到期 ITM 交收成期貨。")
    P("- 只計持倉由開倉起嘅盈虧；已平倉嘅已實現盈虧（例如 10/6 對沖 10/7 以 23,987 買回）唔計，查成交用 --deals。")
    P("- 冇報價嘅腿（例如 CME 期權冇行情權限）用富途持倉估值或截圖價，即係上一個收市價，唔係即時價。")
    return "\n".join(L), M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=str(HERE / "data_external" / "risk_book.json"))
    dq = HERE / "data_external" / "futu_positions.json"
    ap.add_argument("--quotes", default=str(dq) if dq.exists() else "", help="futu_positions_quote.py 輸出（真實買賣價）")
    ap.add_argument("--combined-equity", type=float, default=None,
                    help="幾個戶口合計權益 HKD（硬止損按合計計）；唔填＝book 假設 NAV＋持倉盈虧")
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    txt, _ = build(a.book, a.quotes, a.combined_equity)
    print(txt)
    if a.md:
        Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md).write_text(txt + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
