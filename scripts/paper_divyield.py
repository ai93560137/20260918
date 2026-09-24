#!/usr/bin/env python3
"""高息股前向模擬盤（規則寫死：DIVYIELD_CC_BACKTEST.md 第二部分）——HKD／USD 高息、HKC／USC 高息＋賣 5% 價外 call。

由 scripts/paper_trade.py 每天呼叫（.github/workflows/fetch_stock_data.yml 內）：
- 每市場：新月份第一個交易日的數據到了（且本月未換倉）→ 結算上月、按上月最後交易日訊號建本月籃子
- 賣 call：建倉後抓**真實**報價（港股：港交所股票期權日報結算價；美股：yfinance 期權鏈中間價），記下行使價、到期、權利金；
  同時記模型權利金（ρ × RV63），報「實收 ÷ 模型」；到期後用日線結算，除淨前按美式提前行使條件判斷
- 只記錄不下單；首次啟動不回補已過去的月份；錯過一天下一次補做（選股只用訊號日以前的數據）

本機驗證（不需網路）：
    python3 scripts/paper_divyield.py --check-selection hk 2024-06-28   # 選股 = 回測引擎該期持倉
    python3 scripts/paper_divyield.py --check-selection us 2024-06-28
    python3 scripts/paper_divyield.py --offline                          # 不抓期權報價，只跑換倉／結算
"""
import argparse
import bisect
import gzip
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import marketdata as md  # noqa: E402
import options_equity as oe  # noqa: E402
import stock_momentum_backtest as eng  # noqa: E402

PAPER_DIR = ROOT / "paper"
LEDGER = PAPER_DIR / "divyield_ledger.json"
REPORT = PAPER_DIR / "DIVYIELD_PAPER.md"
OPT_RAW = PAPER_DIR / "divyield_options_raw"
LIVE_HSI = ROOT / "scripts" / "universe_hsi_live.txt"

W, K = 12, 10
KC = 1.05
MKT = {
    "hk": dict(bench="2800.HK", cost_bps=15.0, rho=0.93, cv=1.0, name="港股高息（HKD）", cc="港股高息＋賣 call（HKC）"),
    "us": dict(bench="SPY", cost_bps=5.0, rho=0.95, cv=0.5, name="美股高息（USD）", cc="美股高息＋賣 call（USC）"),
}
STOP_DD, ALPHA_WIN = -0.35, 24
UA = {"User-Agent": "Mozilla/5.0 (research; github-actions)"}


# ───────────────────────── 數據 ─────────────────────────
class Prices:
    def __init__(self):
        self._c = {}

    def series(self, t):
        if t not in self._c:
            self._c[t] = eng.load_series(t) if md.has_data(t) else None
        return self._c[t]

    def divs(self, t):
        s = self.series(t)
        return eng.derive_dividends(s) if s else []


def month_starts(px: Prices, bench: str):
    cal = sorted(px.series(bench))
    return [(cal[i - 1], cal[i]) for i in range(1, len(cal)) if cal[i].month != cal[i - 1].month]


def members(market: str, on: date) -> tuple[list[str], str]:
    if market == "hk":
        ts = [l.strip() for l in LIVE_HSI.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        return ts, "現行恒指成分股（scripts/universe_hsi_live.txt）"
    from universe import Universe
    return sorted(Universe("sp500").members_at(on)), "S&P 500 名單（universes/sp500/membership.csv）"


def select(px: Prices, tickers: list[str], signal: date) -> list[str]:
    """同 stock_momentum_backtest.run_backtest 的 divyield 打分（W=12、K=10）。"""
    window = timedelta(days=round(W * 30.4375))
    scored = []
    for t in tickers:
        s = px.series(t)
        if not s or min(s) > signal - window or signal not in s:
            continue
        ttm = sum(x for d, x in px.divs(t) if signal - window < d <= signal)
        close = s[signal][2]
        if ttm > 0 and close > 0:
            scored.append((ttm / (W / 12) / close, t))
    scored.sort(reverse=True)
    return sorted(t for _, t in scored[:K])


def stock_ret(px: Prices, t: str, e0: date, e1: date):
    s = px.series(t) or {}
    if e0 not in s:
        return None, f"{t} 建倉日無報價，不計"
    if e1 in s:
        return s[e1][0] / s[e0][0] - 1, None
    last = [d for d in s if e0 <= d < e1]
    if not last:
        return None, f"{t} 持有期無報價，不計"
    return s[max(last)][1] / s[e0][0] - 1, f"{t} 持有期中斷，以 {max(last)} 收市價結算"


def raw_open(px, t, d):
    ao, ac, c = px.series(t)[d]
    return ao * c / ac


def rv63(px, t, d):
    s = px.series(t)
    ds = sorted(x for x in s if x <= d)[-64:]
    a = [s[x][1] for x in ds if s[x][1] > 0]
    if len(a) < 61:
        return None
    lr = [math.log(a[i] / a[i - 1]) for i in range(1, len(a))]
    m = sum(lr) / len(lr)
    return math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1)) * math.sqrt(252)


# ───────────────────────── 真實期權報價 ─────────────────────────
def capture_us(tickers: list[str], day: date) -> dict:
    import yfinance as yf
    out = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t.replace(".", "-"))
            spot = float(tk.fast_info["last_price"])
            exps = [e for e in tk.options if 20 <= (date.fromisoformat(e) - day).days <= 45]
            if not exps:
                out[t] = {"status": "無 20–45 日到期系列"}
                continue
            e = min(exps, key=lambda x: abs((date.fromisoformat(x) - day).days - 30))
            calls = tk.option_chain(e).calls
            cands = calls[calls["strike"] >= KC * spot].sort_values("strike")
            got = None
            for _, r in cands.iterrows():
                bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
                if bid > 0 and ask > 0:
                    got = dict(strike=float(r["strike"]), bid=bid, ask=ask, premium=(bid + ask) / 2)
                    break
            if not got:
                out[t] = {"status": "行使價 ≥ 1.05 倍沒有有效買賣價"}
                continue
            out[t] = dict(status="ok", expiry=e, spot=spot, source="yfinance 中間價",
                          captured_utc=datetime.now(timezone.utc).isoformat(timespec="minutes"), **got)
        except Exception as ex:  # noqa: BLE001
            out[t] = {"status": f"抓取失敗 {ex!r}"[:120]}
    return out


def capture_hk(tickers: list[str], day: date) -> dict | None:
    """港交所股票期權每日市場報告；報告未出（404）回 None，下次再試。"""
    import requests
    url = f"https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/dqe{day:%y%m%d}.htm"
    r = requests.get(url, headers=UA, timeout=60)
    if r.status_code != 200 or len(r.content) < 10000:
        print(f"港交所報告 {url} → {r.status_code}（未出，下次再試）")
        return None
    OPT_RAW.mkdir(parents=True, exist_ok=True)
    (OPT_RAW / f"hk_dqe_{day}.htm.gz").write_bytes(gzip.compress(r.content))
    txt = re.sub(r"<[^>]*>", "", r.content.decode("latin-1"))
    code_of = {m.group(1): f"{int(m.group(2)):04d}.HK"
               for m in re.finditer(r"^([A-Z0-9]{3}) .{20,40}?\(\s*(\d{5})\)", txt, re.M)}
    classes = {}
    for sec in re.split(r"(?=^CLASS [A-Z0-9]{3} - )", txt, flags=re.M):
        h = re.match(r"CLASS ([A-Z0-9]{3}) - .*?CLOSING PRICE HK\$\s*([\d.,]+)", sec)
        if not h:
            continue
        tk = code_of.get(h.group(1))
        if tk in classes or tk not in tickers:
            continue
        rows = []
        for m in re.finditer(r"^(\d{2}[A-Z]{3}\d{2})\s+([\d.,]+) C\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s+[-+\d.]+\s+(\d+)", sec, re.M):
            rows.append((datetime.strptime(m.group(1), "%d%b%y").date(), float(m.group(2).replace(",", "")),
                         float(m.group(3)), int(m.group(4))))
        classes[tk] = (float(h.group(2).replace(",", "")), rows)
    out = {}
    for t in tickers:
        if t not in classes:
            out[t] = {"status": "沒有股票期權"}
            continue
        spot, rows = classes[t]
        exps = sorted({e for e, *_ in rows if 20 <= (e - day).days <= 45})
        if not exps:
            out[t] = {"status": "無 20–45 日到期系列"}
            continue
        e = min(exps, key=lambda x: abs((x - day).days - 30))
        cands = sorted((k, p, iv) for ee, k, p, iv in rows if ee == e and k >= KC * spot and p > 0)
        if not cands:
            out[t] = {"status": "行使價 ≥ 1.05 倍沒有結算價"}
            continue
        k, p, iv = cands[0]
        out[t] = dict(status="ok", expiry=str(e), spot=spot, strike=k, premium=p, hkex_iv=iv / 100,
                      source="港交所結算價", captured_utc=datetime.now(timezone.utc).isoformat(timespec="minutes"))
    return out


def model_premium(px, t, day, spot, strike, expiry, rho, base):
    rv = rv63(px, t, day)
    if rv is None:
        return None
    T = max((date.fromisoformat(expiry) - day).days, 1) / 365
    irx = oe.read_series("IRX")
    r = (oe.asof(irx, sorted(irx), day) or 0) / 100
    q = sum(x for d, x in px.divs(t) if 0 < (day - d).days <= 365) / spot
    F = spot * math.exp((r - q) * T)
    m = math.log(strike / F) / math.sqrt(T)
    v = max(rho * rv + base["s_call"] * 0.5 * m, 0.05)
    return oe.bs(spot, strike, T, r, q, v, "c")[0]


def settle_option(px, t, o, entry, exit_, stock_r):
    """到期（或除淨前提前行使）後，回傳該檔「賣 call 版」的持有期報酬與說明；未到期／無數據回 None。
    - 提前行使（登記規則）：股票在除淨前一日以 K 被接走、拿不到股息，之後持現金 → 報酬 = (K + 權利金) ÷ 建倉原始開市 − 1
    - 到期：按現金結算等值 → 正股報酬 + (權利金 − max(S_到期 − K, 0)) ÷ 建倉原始開市（到期在換倉日之後也一樣）"""
    s = px.series(t) or {}
    x = date.fromisoformat(o["expiry"])
    if not s or max(s) < x or entry not in s:
        return None
    K_, prem = o["strike"], o["premium"]
    ro = raw_open(px, t, entry)
    v = o.get("model_iv") or o.get("hkex_iv") or 0.3
    for d, D in px.divs(t):
        if entry < d <= x:
            prev = [y for y in s if entry <= y < d]
            if not prev:
                continue
            dp = max(prev)
            Sp = s[dp][2]
            tau = max((x - dp).days, 1) / 365
            put, _ = oe.bs(Sp, K_, tau, 0.04, 0.0, max(v, 0.05), "p")
            if Sp > K_ and D > put + K_ * (1 - math.exp(-0.04 * tau)):
                return (K_ + prem) / ro - 1, f"{t} 除淨前 {dp} 提前行使"
    SX = s[max(y for y in s if y <= x)][2]
    return stock_r + (prem - max(SX - K_, 0.0)) / ro, (f"{t} 到期被行使" if SX > K_ else None)


# ───────────────────────── 帳本 ─────────────────────────
def load():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"rules": "DIVYIELD_CC_BACKTEST.md 第二部分", "started": {}, "periods": {"hk": [], "us": []}}


def run_market(led, px, market, offline):
    cfg = MKT[market]
    base = oe.MARKETS[market]
    starts = month_starts(px, cfg["bench"])
    signal, entry = starts[-1]
    month = entry.strftime("%Y-%m")
    latest = max(px.series(cfg["bench"]))
    per = led["periods"][market]
    done = {p["month"] for p in per}
    # 補抓本月期權報價（建倉後）
    if per and per[-1]["month"] == month and not offline:
        capture(per[-1], px, market, base)
    if month in done or latest < entry:
        return f"{market}：{month} 已換倉或未到換倉日（最新 {latest}）"
    if not led["started"].get(market) and latest > entry:
        return f"{market}：尚未開始，{month} 換倉日 {entry} 已過；等下個月第一個交易日"
    msgs = []
    if per and "ret" not in per[-1]:
        last = per[-1]
        e0 = date.fromisoformat(last["entry"])
        prev_b = per[-2]["basket"] if len(per) > 1 else []
        rets, notes, cc = [], [], []
        opts = last.get("options", {})
        for t in last["basket"]:
            r, n = stock_ret(px, t, e0, entry)
            if n:
                notes.append(n)
            if r is None:
                continue
            rets.append(r)
            o = opts.get(t)
            if o and o.get("status") == "ok":
                st = settle_option(px, t, o, e0, entry, r)
                if st is None:
                    cc.append(None)
                    continue
                o["cc_ret"], note = st
                if note:
                    notes.append(note)
                cc.append(st[0])
            else:
                cc.append(r)
        chg = len(set(prev_b) ^ set(last["basket"])) if prev_b else len(last["basket"])
        cost = chg * (1 / K) * cfg["cost_bps"] / 1e4
        last["cost"] = cost
        last["ret"] = sum(rets) / len(rets) - cost if rets else -cost
        b = px.series(cfg["bench"])
        last["bench"] = b[entry][0] / b[e0][0] - 1
        last["exit"] = entry.isoformat()
        last["notes"] = notes
        if all(x is not None for x in cc):
            last["cc_ret"] = sum(cc) / len(cc) - cost if cc else -cost
            last.pop("cc_pending", None)
        else:
            last["cc_pending"] = True          # 有期權未到期／無數據：下次再結算賣 call 版
        msgs.append(f"{market} 結算 {last['month']}：高息 {last['ret']:+.2%}、基準 {last['bench']:+.2%}"
                    + (f"、賣 call {last['cc_ret']:+.2%}" if "cc_ret" in last else ""))
    mem, src = members(market, entry)
    basket = select(px, mem, signal)
    p = {"month": month, "signal_date": signal.isoformat(), "entry": entry.isoformat(), "universe": src,
         "n_members": len(mem), "basket": basket, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    per.append(p)
    led["started"][market] = led["started"].get(market) or month
    if not offline:
        capture(p, px, market, base)
    msgs.append(f"{market} 建倉 {month}：{basket}")
    return "；".join(msgs)


def capture(p, px, market, base):
    if p.get("options_done"):
        return
    day = date.fromisoformat(p["entry"])
    got = capture_hk(p["basket"], day) if market == "hk" else capture_us(p["basket"], day)
    if got is None:
        return
    for t, o in got.items():
        if o.get("status") == "ok" and px.series(t) and day in px.series(t):
            mp = model_premium(px, t, day, o["spot"], o["strike"], o["expiry"], MKT[market]["rho"], base)
            rv = rv63(px, t, day)
            if rv:
                o["model_iv"] = MKT[market]["rho"] * rv
            if mp:
                o["model_premium"] = mp
                o["real_over_model"] = o["premium"] / mp
    p["options"] = got
    p["options_done"] = True


def finish_pending(led, px):
    """賣 call 版有期權到期日在換倉日之後：數據到了再結算。"""
    for market, per in led["periods"].items():
        for p in per:
            if not p.get("cc_pending"):
                continue
            e0, e1 = date.fromisoformat(p["entry"]), date.fromisoformat(p["exit"])
            cc, ready = [], True
            for t in p["basket"]:
                r, _ = stock_ret(px, t, e0, e1)
                if r is None:
                    continue
                o = p.get("options", {}).get(t)
                if o and o.get("status") == "ok":
                    st = settle_option(px, t, o, e0, e1, r)
                    if st is None:
                        ready = False
                        break
                    o["cc_ret"] = st[0]
                    cc.append(st[0])
                else:
                    cc.append(r)
            if ready:
                p["cc_ret"] = (sum(cc) / len(cc) if cc else 0.0) - p.get("cost", 0.0)
                p.pop("cc_pending")


def report(led):
    lines = ["# 高息股前向模擬盤（HKD／USD 高息、HKC／USC 高息＋賣 call）", "",
             "規則見 `DIVYIELD_CC_BACKTEST.md` 第二部分；由 `scripts/paper_divyield.py` 每天自動執行，只記錄不下單。", ""]
    for market, per in led["periods"].items():
        cfg = MKT[market]
        s = [p for p in per if "ret" in p]
        eq = eqb = eqc = 1.0
        peak, mdd = 1.0, 0.0
        for p in s:
            eq *= 1 + p["ret"]
            eqb *= 1 + p["bench"]
            eqc *= 1 + p.get("cc_ret", p["ret"])
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        ratios = [o["real_over_model"] for p in per for o in p.get("options", {}).values() if "real_over_model" in o]
        med = sorted(ratios)[len(ratios) // 2] if ratios else None
        red = []
        if mdd <= STOP_DD:
            red.append("回撤觸及 −35%")
        if len(s) >= 6 and med is not None and med < 0.85:
            red.append("實收權利金 ÷ 模型中位 < 0.85")
        if len(s) >= 12 and eqc < eq:
            red.append("賣 call 累計落後不賣 call")
        lines += [f"## {cfg['name']} ／ {cfg['cc']}", "",
                  f"已結算 {len(s)} 期（開始 {led['started'].get(market) or '未開始'}）：高息 {eq - 1:+.2%}（回撤 {mdd:.1%}）｜"
                  f"賣 call {eqc - 1:+.2%}｜基準 {cfg['bench']} {eqb - 1:+.2%}",
                  f"實收 ÷ 模型權利金中位：{med:.2f}（{len(ratios)} 筆）" if med else "實收 ÷ 模型權利金：尚無數據",
                  f"證偽：{'🔴 ' + '、'.join(red) if red else '🟢 未觸發'}", "",
                  "| 月份 | 建倉日 | 結算日 | 高息 | 賣 call | 基準 | 有期權報價 |", "|---|---|---|---|---|---|---|"]
        for p in per:
            n_ok = sum(1 for o in p.get("options", {}).values() if o.get("status") == "ok")
            f = lambda x: f"{x:+.2%}" if isinstance(x, float) else "—"  # noqa: E731
            lines.append(f"| {p['month']} | {p['entry']} | {p.get('exit', '—')} | {f(p.get('ret'))} | {f(p.get('cc_ret'))} | "
                         f"{f(p.get('bench'))} | {n_ok}/{len(p['basket'])} |")
        lines += [""]
        for p in per[-1:]:
            lines += [f"**{p['month']} 持倉**：" + "、".join(p["basket"]), ""]
            for t, o in sorted(p.get("options", {}).items()):
                if o.get("status") == "ok":
                    rm = f"、實收÷模型 {o['real_over_model']:.2f}" if "real_over_model" in o else ""
                    lines.append(f"- {t}：{o['expiry']} 到期、行使價 {o['strike']}、權利金 {o['premium']:.3f}（{o['source']}）{rm}")
                else:
                    lines.append(f"- {t}：{o.get('status')}")
            lines.append("")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_irx() -> None:
    """模型權利金用的 ^IRX：data/options_equity/IRX.csv 由研究分支一次性抓取，模擬盤每天順手補最近一個月。"""
    import yfinance as yf
    p = ROOT / "data" / "options_equity" / "IRX.csv"
    old = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines()[1:]:
            d, v = line.split(",")
            old[d] = v
    h = yf.Ticker("^IRX").history(period="1mo", auto_adjust=False)
    for d, v in h["Close"].items():
        old[d.strftime("%Y-%m-%d")] = f"{float(v):.6g}"
    p.write_text("Date,Close\n" + "".join(f"{d},{v}\n" for d, v in sorted(old.items())), encoding="utf-8")


def run(offline: bool = False) -> None:
    PAPER_DIR.mkdir(exist_ok=True)
    if not offline:
        try:
            update_irx()
        except Exception as ex:  # noqa: BLE001
            print(f"^IRX 更新失敗（模型權利金用舊利率）：{ex!r}")
    led = load()
    px = Prices()
    for market in ("hk", "us"):
        try:
            print(run_market(led, px, market, offline))
        except Exception as ex:  # noqa: BLE001
            print(f"{market} 高息模擬盤出錯（不影響其他）：{ex!r}")
    finish_pending(led, px)
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    report(led)


def check_selection(market: str, signal: date) -> None:
    """用回測的歷史成分股，選股必須等於 run_backtest 該期持倉。"""
    import divyield_cc as dc
    px = Prices()
    pool, snaps = dc.hk_universe() if market == "hk" else dc.us_universe()
    snap = [m for d, m in snaps if d <= signal][-1]
    if market == "hk":
        first = {t: min(px.series(t)) for t in snap if px.series(t)}
        snap_d = [d for d, _ in snaps if d <= signal][-1]
        snap = {t for t in snap if t in first and first[t] <= snap_d}
    mine = select(px, sorted(snap), signal)
    res = dc.run(market, W, K, pool, snaps)
    entry = [e for s, e in month_starts(px, MKT[market]["bench"]) if s == signal][0]
    theirs = sorted([b for d, b in res["baskets"] if d == entry][0])
    ok = mine == theirs
    print(f"{market} {signal}：{'一致' if ok else '不一致!'}\n  模擬盤 {mine}\n  回測   {theirs}")
    sys.exit(0 if ok else 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--check-selection", nargs=2, metavar=("MARKET", "SIGNAL_DATE"))
    a = ap.parse_args()
    if a.check_selection:
        check_selection(a.check_selection[0], date.fromisoformat(a.check_selection[1]))
    else:
        run(a.offline)


if __name__ == "__main__":
    main()
