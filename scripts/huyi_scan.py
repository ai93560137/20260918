#!/usr/bin/env python3
"""虎翼——每日大跌股賣期權掃描（候選表＋紙上紀錄；不出實倉落單指令）。

    python3 scripts/huyi_scan.py --market us     # 美股收市後（GitHub Actions；沙盒擋 Yahoo）
    python3 scripts/huyi_scan.py --market hk     # 港股收市後（港交所股票期權日報出咗之後）
    python3 scripts/huyi_scan.py --selftest      # 離線自檢（用 analysis/opt_snapshot、data/options_equity/live 舊檔）

規格跟 stock_research/BIGDROP_OPTIONS_PREREG.md（已判決：95% put 🔍、105% call 只准紙上）：
- 宇宙：現行 S&P 500（universes/sp500/membership.csv 未完結區間）／現行恒指（scripts/universe_hsi_live.txt）
- 大跌：最後一根日線 AdjClose 報酬 ≤ −8%、收市 ≥ 5；RV63pre＝大跌日之前 63 個報酬（不含大跌日）
- 期權：到期日 20–45 日曆日內最接近 30 日；put 行使價＝≤ 0.95×收市最近一檔，call＝≥ 1.05×收市最近一檔
- ρ＝平值 IV ÷ RV63pre（美：買賣中間價平價求遠期再反推；港：港交所日報平值 C／P 的 IV% 平均）
- 合資格（紙上「會開」）：ρ ≥ 該腿 ρ₂（put 美港 0.95；call 美 1.20／港 1.50）且到期前冇已知業績
- 紙上成交價：美＝買價（bid）；港＝結算價減 1 波動點 × vega（日報冇買賣價；成本同回測）
- 去重：同一股票 30 日曆日內已有紙上紀錄就唔再記（≈ 回測「21 交易日內只取第一次」）
- 紙上損益（到期結算，佔名義 %）：put＝(權利金 − max(K − S_T, 0)) ÷ K；call＝(權利金 − max(S_T − K, 0)) ÷ S₀
- 前向證偽（登記第 7 部分）：合資格 put 前 30 筆平均損益 ≤ 0，或累計虧損 > 已收權利金總和 → 停

輸出 analysis/huyi/：
  <market>/<日期>.csv   當日候選（每個大跌股 × put／call 兩腿）
  latest_<market>.md    當日候選表（人睇）
  paper_log.csv         紙上紀錄（開＋到期結算）
  scan_log.csv          每次掃描一行（冇大跌都記，前向紀錄要完整）
  tg_<market>.txt       Telegram 摘要（workflow 發）
repo 公開：只寫價格、張數、百分比，唔寫金額。
"""
import argparse
import csv
import gzip
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "huyi"
THR = -0.08
MIN_PX = 5.0
RHO2 = {"us": {"put95": 0.95, "call105": 1.20}, "hk": {"put95": 0.95, "call105": 1.50}}
LEGS = {"put95": ("p", 0.95), "call105": ("c", 1.05)}
DTE_LO, DTE_HI, DTE_TGT = 20, 45, 30
DEDUP_DAYS = 30
HK_COST_VOL = 0.01
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
PAPER_COLS = ["open_date", "market", "ticker", "leg", "expiry", "dte", "strike", "spot", "fill", "bid", "ask", "mid",
              "iv_leg", "atm_iv", "rv63pre", "rho", "rho_req", "qualifies", "earnings", "drop_pct",
              "status", "close_at_expiry", "assigned", "pnl_pct", "note"]
CAND_COLS = ["session", "date", "market", "ticker", "name", "drop_pct", "close", "rv63pre", "expiry", "dte", "atm_iv", "rho",
             "leg", "strike", "moneyness", "bid", "ask", "mid", "fill", "iv_leg", "yield_ann_pct", "rho_req",
             "rho_ok", "earnings", "earnings_in_window", "qualifies", "paper", "note"]


# ───────────────────────── BS／IV（純 math，Actions 唔使裝 scipy） ─────────────────────────
def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_fwd(F, K, T, df, v, cp):
    """遠期式 Black：回傳 (價, vega 每 1.00 波動)。"""
    sd = v * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
    call = df * (F * ncdf(d1) - K * ncdf(d1 - sd))
    px = call if cp == "c" else call - df * (F - K)
    vega = df * F * math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) * math.sqrt(T)
    return px, vega


def implied_vol(F, K, T, df, px, cp):
    intrinsic = df * max((F - K) if cp == "c" else (K - F), 0)
    if px <= intrinsic + 1e-9 or T <= 0:
        return None
    lo, hi = 1e-3, 5.0
    for _ in range(80):
        m = (lo + hi) / 2
        if bs_fwd(F, K, T, df, m, cp)[0] > px:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def rv_pre(adj: list[float]) -> float:
    """大跌日之前 63 個對數報酬的年化波動（adj 最後一個係大跌日收市，唔計）。"""
    a = [x for x in adj[:-1] if x and x == x][-64:]
    if len(a) < 61:
        return float("nan")
    lr = [math.log(a[i] / a[i - 1]) for i in range(1, len(a))]
    m = sum(lr) / len(lr)
    return math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1) * 252)


def pick_expiry(expiries: list[date], d0: date) -> date | None:
    ok = [e for e in expiries if DTE_LO <= (e - d0).days <= DTE_HI]
    return min(ok, key=lambda e: abs((e - d0).days - DTE_TGT)) if ok else None


# ───────────────────────── 宇宙與日線 ─────────────────────────
def universe(market: str) -> list[str]:
    if market == "us":
        with open(ROOT / "universes" / "sp500" / "membership.csv", newline="", encoding="utf-8") as f:
            return sorted({r["ticker"] for r in csv.DictReader(f) if not r["end"]})
    return [x.strip() for x in (ROOT / "scripts" / "universe_hsi_live.txt").read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.startswith("#")]


def fetch_prices(tickers: list[str]) -> dict[str, list[tuple]]:
    """{ticker: [(date, close, adjclose, volume), …]}；分批 yf.download。"""
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 100):
        batch = tickers[i:i + 100]
        df = yf.download(batch, period="1y", auto_adjust=False, group_by="ticker", threads=True, progress=False)
        for t in batch:
            try:
                s = df[t] if len(batch) > 1 else df
                s = s.dropna(subset=["Close"])
                out[t] = [(d.date(), float(r["Close"]), float(r.get("Adj Close", r["Close"])), float(r["Volume"] or 0))
                          for d, r in s.iterrows()]
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1)
    return out


def find_drops(px: dict[str, list[tuple]]) -> tuple[date | None, list[dict], list[dict]]:
    """回傳 (最新交易日, 大跌股, 當日跌幅最大 5 隻)。只認最後一根日線＝全宇宙最常見最新日期的股票（防停牌舊價）。"""
    lasts = [v[-1][0] for v in px.values() if len(v) >= 2]
    if not lasts:
        return None, [], []
    d0 = max(set(lasts), key=lasts.count)
    rows = []
    for t, v in px.items():
        if len(v) < 66 or v[-1][0] != d0 or v[-1][3] <= 0:
            continue
        ret = v[-1][2] / v[-2][2] - 1
        rows.append(dict(ticker=t, date=d0, close=v[-1][1], ret=ret, rv63pre=rv_pre([x[2] for x in v])))
    rows.sort(key=lambda r: r["ret"])
    drops = [r for r in rows if r["ret"] <= THR and r["close"] >= MIN_PX]
    return d0, drops, rows[:5]


def fetch_after_hours(tickers: list[str], d0: date) -> dict[str, float]:
    """美股盤後價：d0 美東 16:00 之後（含翌日盤前）最後一根 15 分鐘線收市價（Yahoo prepost）。"""
    import yfinance as yf
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    cut = datetime(d0.year, d0.month, d0.day, 16, 0, tzinfo=ny)
    out = {}
    for i in range(0, len(tickers), 100):
        batch = tickers[i:i + 100]
        try:
            df = yf.download(batch, period="5d", interval="15m", prepost=True, auto_adjust=False, group_by="ticker",
                             threads=True, progress=False)
        except Exception as ex:  # noqa: BLE001
            print("盤後價抓取失敗", repr(ex))
            continue
        for t in batch:
            try:
                s = (df[t] if len(batch) > 1 else df)["Close"].dropna()
                s = s[s.index.tz_convert(ny) >= cut]
                if len(s):
                    out[t] = float(s.iloc[-1])
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1)
    return out


def after_hours_drops(px: dict[str, list[tuple]], ah: dict[str, float], d0: date, have: set[str]) -> list[dict]:
    """盤後價對 d0 正式收市 ≤ 門檻（正式時段已入大跌名單嘅唔重複）。RV63pre 包埋 d0（大跌喺收市之後）。"""
    out = []
    for t, p in ah.items():
        v = px.get(t)
        if t in have or not v or len(v) < 66 or v[-1][0] != d0:
            continue
        ret = p / v[-1][1] - 1
        if ret <= THR and p >= MIN_PX:
            adj = [x[2] for x in v]
            out.append(dict(ticker=t, date=d0, close=v[-1][1], ret=ret, rv63pre=rv_pre(adj + [adj[-1]]), ah_px=p,
                            note=f"🌙盤後跌（盤後價 {p:.4g}；期權係收市報價、未反映跌幅，行使價按盤後價揀；下一個交易日收市再按正式規則記紙上）"))
    out.sort(key=lambda r: r["ret"])
    return out


def next_earnings(tk, after: date) -> str:
    """yfinance 下一個業績日（> 大跌日）；冇就回空字串。"""
    try:
        cal = tk.calendar
        eds = cal.get("Earnings Date") if isinstance(cal, dict) else None
        for e in eds or []:
            e = e if isinstance(e, date) else date.fromisoformat(str(e)[:10])
            if e > after:
                return str(e)
    except Exception:  # noqa: BLE001
        pass
    try:
        ed = tk.get_earnings_dates(limit=8)
        fut = sorted(x.date() for x in ed.index if x.date() > after)
        if fut:
            return str(fut[0])
    except Exception:  # noqa: BLE001
        pass
    return ""


# ───────────────────────── 期權腿 ─────────────────────────
def us_legs(chain: list[dict], spot: float, d0: date, exp: date, rate: float, ref: float | None = None) -> dict | None:
    """chain：同一到期日的 dict(cp,strike,bid,ask,last)。回傳平值 IV 與兩腿報價。
    ref：行使價目標的基準價（盤後大跌用盤後價；平值 IV 仍按收市報價嘅 spot）。"""
    T = max((exp - d0).days, 1) / 365
    df = math.exp(-rate * T)
    by_k: dict[float, dict] = {}
    for r in chain:
        bid, ask = float(r["bid"] or 0), float(r["ask"] or 0)
        if bid > 0 and ask >= bid:
            by_k.setdefault(float(r["strike"]), {})[r["cp"]] = (bid, ask, (bid + ask) / 2)
    both = [k for k, v in by_k.items() if "c" in v and "p" in v and (v["c"][1] - v["c"][0]) <= 0.5 * v["c"][2]
            and (v["p"][1] - v["p"][0]) <= 0.5 * v["p"][2]]
    if not both:
        return None
    k0 = min(both, key=lambda k: abs(k - spot))
    F = k0 + (by_k[k0]["c"][2] - by_k[k0]["p"][2]) / df
    ivs = []
    below = [k for k in by_k if k <= F and "p" in by_k[k]]
    above = [k for k in by_k if k >= F and "c" in by_k[k]]
    if below:
        kb = max(below)
        ivs.append(implied_vol(F, kb, T, df, by_k[kb]["p"][2], "p"))
    if above:
        ka = min(above)
        ivs.append(implied_vol(F, ka, T, df, by_k[ka]["c"][2], "c"))
    ivs = [v for v in ivs if v]
    if not ivs:
        return None
    legs = {}
    for leg, (cp, m) in LEGS.items():
        tgt = m * (ref or spot)
        ks = [k for k in by_k if cp in by_k[k] and (k <= tgt if cp == "p" else k >= tgt)]
        if not ks:
            continue
        k = max(ks) if cp == "p" else min(ks)
        bid, ask, mid = by_k[k][cp]
        legs[leg] = dict(strike=k, bid=bid, ask=ask, mid=mid, fill=bid, iv_leg=implied_vol(F, k, T, df, mid, cp))
    return dict(atm_iv=sum(ivs) / len(ivs), F=F, T=T, legs=legs)


def us_quotes(c: dict, rate: float) -> dict | None:
    import yfinance as yf
    tk = yf.Ticker(c["ticker"])
    exps = [date.fromisoformat(e) for e in tk.options]
    exp = pick_expiry(exps, c["date"])
    c["earnings"] = next_earnings(tk, c["date"])
    try:
        c["name"] = (tk.info or {}).get("shortName", "")
    except Exception:  # noqa: BLE001
        c["name"] = ""
    if not exp:
        c["note"] = f"冇 {DTE_LO}–{DTE_HI} 日到期"
        return None
    ch = tk.option_chain(str(exp))
    rows = [dict(cp=cp, strike=r["strike"], bid=r.get("bid"), ask=r.get("ask"), last=r.get("lastPrice"))
            for cp, d in (("c", ch.calls), ("p", ch.puts)) for _, r in d.iterrows()]
    q = us_legs(rows, c["close"], c["date"], exp, rate, c.get("ah_px"))
    if q is None:   # 收市後 Yahoo 有時清零買賣價 → 退用最後成交價（標明，唔當真實買價）
        q = us_legs([dict(r, bid=r["last"], ask=r["last"]) for r in rows], c["close"], c["date"], exp, rate, c.get("ah_px"))
        if q is None:
            c["note"] = "期權鏈冇有效買賣價／成交價"
            return None
        c["note"] = (c.get("note", "") + " 買賣價清零，用最後成交價").strip()
    q["expiry"] = exp
    return q


# ───────────────────────── 港交所股票期權日報 ─────────────────────────
def hk_report(d0: date) -> str | None:
    import requests
    url = f"https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/dqe{d0:%y%m%d}.htm"
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            print(url, r.status_code, len(r.content))
            if r.status_code == 200 and len(r.content) > 10000:
                OUT.joinpath("hk").mkdir(parents=True, exist_ok=True)
                (OUT / "hk" / f"dqe_{d0}.htm.gz").write_bytes(gzip.compress(r.content))
                return r.content.decode("latin-1")
        except Exception as e:  # noqa: BLE001
            print(url, repr(e))
        time.sleep(5 * (i + 1))
    return None


def parse_hkex(html: str) -> dict[str, dict]:
    """{ticker: dict(name, spot, series={expiry: {strike: {'C': (settle, iv), 'P': …}}})}；同一股票只取第一個類別（調整後合約另開類別）。"""
    txt = re.sub(r"<[^>]*>", "", html)
    code_of = {m.group(1): f"{int(m.group(2)):04d}.HK"
               for m in re.finditer(r"^([A-Z0-9]{3}) .{20,40}?\(\s*(\d{5})\)", txt, re.M)}
    out: dict[str, dict] = {}
    for sec in re.split(r"(?=^CLASS [A-Z0-9]{3} - )", txt, flags=re.M):
        h = re.match(r"CLASS ([A-Z0-9]{3}) - (.*?)\s+CLOSING PRICE HK\$\s*([\d.,]+)", sec)
        if not h:
            continue
        tk = code_of.get(h.group(1))
        if not tk or tk in out:
            continue
        ser: dict[date, dict] = {}
        for m in re.finditer(r"^(\d{2}[A-Z]{3}\d{2})\s+([\d.,]+) ([CP])\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s+[-+\d.]+\s+(\d+)",
                             sec, re.M):
            ex = datetime.strptime(m.group(1), "%d%b%y").date()
            ser.setdefault(ex, {}).setdefault(float(m.group(2).replace(",", "")), {})[m.group(3)] = (
                float(m.group(4)), int(m.group(5)) / 100)
        out[tk] = dict(name=h.group(2).strip(), spot=float(h.group(3).replace(",", "")), series=ser)
    return out


def hk_legs(rec: dict, spot: float, d0: date, rate: float = 0.03) -> dict | None:
    exp = pick_expiry(list(rec["series"]), d0)
    if not exp:
        return None
    ser = rec["series"][exp]
    both = [k for k, v in ser.items() if v.get("C", (0, 0))[1] > 0 and v.get("P", (0, 0))[1] > 0]
    if not both:
        return None
    k0 = min(both, key=lambda k: abs(k - spot))
    atm = (ser[k0]["C"][1] + ser[k0]["P"][1]) / 2
    T = max((exp - d0).days, 1) / 365
    df = math.exp(-rate * T)
    F = spot / df
    legs = {}
    for leg, (cp, m) in LEGS.items():
        CP = cp.upper()
        tgt = m * spot
        ks = [k for k, v in ser.items() if CP in v and v[CP][0] > 0 and (k <= tgt if cp == "p" else k >= tgt)]
        if not ks:
            continue
        k = max(ks) if cp == "p" else min(ks)
        settle, iv = ser[k][CP]
        vega = bs_fwd(F, k, T, df, iv, cp)[1] if iv > 0 else 0.0
        legs[leg] = dict(strike=k, bid="", ask="", mid=settle, fill=max(settle - HK_COST_VOL * vega, 0.0), iv_leg=iv)
    return dict(atm_iv=atm, expiry=exp, T=T, legs=legs)


# ───────────────────────── 紙上紀錄 ─────────────────────────
def is_intraday(market: str, d0: date) -> bool:
    """最新日線係今日而當地未收市（+15 分鐘）→ 盤中。"""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York" if market == "us" else "Asia/Hong_Kong"))
    return d0 == now.date() and (now.hour, now.minute) < (16, 15)


def read_paper() -> list[dict]:
    p = OUT / "paper_log.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(p: Path, cols: list[str], rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def settle_paper(paper: list[dict], market: str, today: date, closes: dict[str, list[tuple]]) -> list[str]:
    """到期日已過（< today）的 open 紀錄按到期日收市結算。closes：{ticker: [(date, close, …)]}。"""
    msgs = []
    for r in paper:
        if r["market"] != market or r["status"] != "open":
            continue
        exp = date.fromisoformat(r["expiry"])
        if exp >= today:
            continue
        v = [x for x in closes.get(r["ticker"], []) if x[0] <= exp]
        if not v:
            continue
        st, K, S0, prem = v[-1][1], float(r["strike"]), float(r["spot"]), float(r["fill"])
        if r["leg"] == "put95":
            pnl, asg = (prem - max(K - st, 0)) / K, st < K
        else:
            pnl, asg = (prem - max(st - K, 0)) / S0, st > K
        r.update(status="closed", close_at_expiry=f"{st:.4g}", assigned="Y" if asg else "N", pnl_pct=f"{pnl * 100:.3f}")
        msgs.append(f"結算 {r['ticker']} {r['leg']} K{K:g} 到期收 {st:.4g} → {pnl * 100:+.2f}%{'（接貨／被call）' if asg else ''}")
    return msgs


def forward_stats(paper: list[dict]) -> str:
    q = [r for r in paper if r["leg"] == "put95" and r["qualifies"] == "Y"]
    done = [r for r in q if r["status"] == "closed"][:30]
    if not done:
        return f"合資格 put 紙上 {len(q)} 筆（未有到期）"
    pnl = [float(r["pnl_pct"]) for r in done]
    prem = sum(float(r["fill"]) / float(r["strike"]) * 100 for r in done)
    loss = -sum(x for x in pnl if x < 0)
    flag = "🔴 觸發證偽" if (len(done) >= 30 and sum(pnl) / len(pnl) <= 0) or loss > prem else "未觸發"
    return f"合資格 put 紙上 {len(q)} 筆、已到期 {len(done)}：平均 {sum(pnl) / len(pnl):+.2f}%、證偽 {flag}"


# ───────────────────────── 主流程 ─────────────────────────
def build_rows(c: dict, q: dict | None, market: str) -> list[dict]:
    base = dict(session="ah" if c.get("ah_px") else "", date=c["date"], market=market, ticker=c["ticker"], name=c.get("name", ""), drop_pct=f"{c['ret'] * 100:.2f}",
                close=f"{c['close']:.4g}", rv63pre=f"{c['rv63pre']:.4f}", earnings=c.get("earnings", ""), note=c.get("note", ""))
    if q is None:
        return [dict(base, leg="—", qualifies="N", paper="N")]
    exp, dte = q["expiry"], (q["expiry"] - c["date"]).days
    rho = q["atm_iv"] / c["rv63pre"] if c["rv63pre"] == c["rv63pre"] and c["rv63pre"] > 0 else float("nan")
    e_in = bool(c.get("earnings")) and c["date"] < date.fromisoformat(c["earnings"]) <= exp
    rows = []
    for leg in LEGS:
        L = q["legs"].get(leg)
        if not L:
            rows.append(dict(base, expiry=exp, dte=dte, atm_iv=f"{q['atm_iv']:.4f}", rho=f"{rho:.3f}", leg=leg,
                             qualifies="N", paper="N", note=(base["note"] + " 冇合適行使價").strip()))
            continue
        req = RHO2[market][leg]
        rho_ok = rho >= req
        den = L["strike"] if leg == "put95" else c.get("ah_px") or c["close"]
        rows.append(dict(base, expiry=exp, dte=dte, atm_iv=f"{q['atm_iv']:.4f}", rho=f"{rho:.3f}", leg=leg,
                         strike=f"{L['strike']:g}", moneyness=f"{L['strike'] / c['close']:.3f}", bid=L["bid"], ask=L["ask"],
                         mid=f"{L['mid']:.4g}", fill=f"{L['fill']:.4g}",
                         iv_leg=f"{L['iv_leg']:.4f}" if L["iv_leg"] else "",
                         yield_ann_pct=f"{L['fill'] / den * 365 / dte * 100:.1f}", rho_req=req, rho_ok="Y" if rho_ok else "N",
                         earnings_in_window="Y" if e_in else ("?" if not c.get("earnings") else "N"),
                         qualifies="Y" if rho_ok and not e_in and not c.get("ah_px") else "N"))
    return rows


def run(market: str) -> int:
    import yfinance as yf
    OUT.mkdir(parents=True, exist_ok=True)
    tick = universe(market)
    px = fetch_prices(tick)
    d0, drops, worst = find_drops(px)
    if d0 is None:
        print("冇日線")
        return 1
    ah_drops = []
    if market == "us":
        ah_drops = after_hours_drops(px, fetch_after_hours([t for t, v in px.items() if v and v[-1][0] == d0], d0), d0,
                                     {c["ticker"] for c in drops})
    print(f"{market} {d0}：宇宙 {len(tick)}、有日線 {len(px)}、大跌 {len(drops)}、盤後大跌 {len(ah_drops)}")
    rate = 0.04
    if market == "us":
        try:
            irx = yf.Ticker("^IRX").history(period="10d")["Close"].dropna()
            rate = float(irx.iloc[-1]) / 100
        except Exception:  # noqa: BLE001
            pass
    hkex = None
    if market == "hk" and drops:  # 港股冇盤後時段
        html = hk_report(d0)
        hkex = parse_hkex(html) if html else None
    paper = read_paper()
    rows = []
    for c in drops + ah_drops:
        q = None
        try:
            if market == "us":
                q = us_quotes(c, rate)
            elif hkex is None:
                c["note"] = "港交所日報未出／抓唔到"
            elif c["ticker"] not in hkex:
                c["note"] = "冇股票期權"
            else:
                c["name"] = hkex[c["ticker"]]["name"]
                c["earnings"] = next_earnings(yf.Ticker(c["ticker"]), c["date"])
                q = hk_legs(hkex[c["ticker"]], c["close"], d0)
                if q is None:
                    c["note"] = f"冇 {DTE_LO}–{DTE_HI} 日到期／平值冇 IV"
        except Exception as ex:  # noqa: BLE001
            c["note"] = f"抓報價失敗 {ex!r}"[:120]
        rows += build_rows(c, q, market)
        time.sleep(0.5)
    # 紙上：去重後每條有報價嘅腿都記（qualifies 標明係咪「會開」）；盤中跑（測試）只出表唔記
    intraday = is_intraday(market, d0)
    recent = {r["ticker"] for r in paper if r["market"] == market
              and (d0 - date.fromisoformat(r["open_date"])).days <= DEDUP_DAYS and r["open_date"] != str(d0)}
    already = {(r["ticker"], r["leg"]) for r in paper if r["open_date"] == str(d0) and r["market"] == market}
    for r in rows:
        if r["leg"] not in LEGS or not r.get("strike"):
            continue
        if r.get("session") == "ah":
            r["paper"] = "N"
            continue
        if intraday:
            r["paper"], r["note"] = "N", (r["note"] + " 盤中價，唔記紙上").strip()
            continue
        if r["ticker"] in recent:
            r["paper"], r["note"] = "N", (r["note"] + f" {DEDUP_DAYS} 日內已記").strip()
            continue
        r["paper"] = "Y"
        if (r["ticker"], r["leg"]) in already:
            continue
        paper.append(dict(open_date=str(d0), market=market, ticker=r["ticker"], leg=r["leg"], expiry=str(r["expiry"]), dte=r["dte"],
                          strike=r["strike"], spot=r["close"], fill=r["fill"], bid=r["bid"], ask=r["ask"], mid=r["mid"],
                          iv_leg=r["iv_leg"], atm_iv=r["atm_iv"], rv63pre=r["rv63pre"], rho=r["rho"], rho_req=r["rho_req"],
                          qualifies=r["qualifies"], earnings=r["earnings"], drop_pct=r["drop_pct"], status="open", note=r["note"]))
    # 到期結算：用今次抓到嘅日線（宇宙外／已剔除嘅另抓）
    need = {r["ticker"] for r in paper if r["market"] == market and r["status"] == "open"
            and date.fromisoformat(r["expiry"]) < d0 and r["ticker"] not in px}
    if need:
        px.update(fetch_prices(sorted(need)))
    settled = settle_paper(paper, market, d0, px)
    if not intraday:
        write_csv(OUT / "paper_log.csv", PAPER_COLS, paper)
    write_csv(OUT / market / f"{d0}.csv", CAND_COLS, rows)
    log_p = OUT / "scan_log.csv"
    new = not log_p.exists()
    with open(log_p, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["run_utc", "market", "trade_date", "universe", "with_px", "drops", "qualifying_put", "settled", "intraday",
                        "ah_drops"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), market, d0, len(tick), len(px), len(drops),
                    sum(1 for r in rows if r["leg"] == "put95" and r["qualifies"] == "Y"), len(settled), "Y" if intraday else "N",
                    len(ah_drops)])
    md_txt, tg = report(market, d0, len(tick), rows, worst, settled, forward_stats(paper), intraday)
    (OUT / f"latest_{market}.md").write_text(md_txt, encoding="utf-8")
    (OUT / f"tg_{market}.txt").write_text(tg, encoding="utf-8")
    print(tg)
    return 0


def report(market, d0, n_univ, rows, worst, settled, fwd, intraday=False) -> tuple[str, str]:
    mk = {"us": "美股 S&P 500 ", "hk": "港股恒指 "}[market]
    L = [f"# 🐯 虎翼｜{mk}大跌股候選 {d0}", "",
         "**紙上紀錄階段——實倉規則未定，以下唔係落單指令。**", "",
         f"宇宙 {n_univ}；大跌門檻 ≤ {THR:.0%}、收市 ≥ {MIN_PX:g}；到期 {DTE_LO}–{DTE_HI} 日最近 {DTE_TGT} 日；"
         "🌙＝盤後大跌（盤後價對正式收市 ≤ −8%；只預警，期權係收市報價，下一交易日收市再按正式規則判）；"
         f"合資格＝ρ ≥ ρ₂（put {RHO2[market]['put95']}、call {RHO2[market]['call105']}，call 只准紙上）且到期前冇已知業績。", ""]
    T = ["🐯 虎翼｜" + mk + f"{d0}（{'盤中測試，' if intraday else ''}紙上，非落單指令）"]
    if not rows:
        L.append("今日冇大跌股。")
        T.append("今日冇 ≤ −8% 大跌股。")
    else:
        L += ["| 股票 | 跌幅 | 收市 | RV63 | 到期（日） | 平值IV | ρ | 腿 | 行使價 | 買／賣／中 | 紙上價 | 年化% | 業績 | 合資格 | 備註 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['ticker']} {r.get('name', '')} | {r['drop_pct']}% | {r['close']} | {r['rv63pre']} | {r.get('expiry', '')}"
                     f"（{r.get('dte', '')}） | {r.get('atm_iv', '')} | {r.get('rho', '')} | {r['leg']} | {r.get('strike', '')} | "
                     f"{r.get('bid', '')}／{r.get('ask', '')}／{r.get('mid', '')} | {r.get('fill', '')} | {r.get('yield_ann_pct', '')} | "
                     f"{r.get('earnings', '')}{'（窗內）' if r.get('earnings_in_window') == 'Y' else ''} | "
                     f"{'✅' if r['qualifies'] == 'Y' else '—'} | {r.get('note', '')} |")
        seen = set()
        for r in rows:
            if r["ticker"] in seen:
                continue
            seen.add(r["ticker"])
            mine = [x for x in rows if x["ticker"] == r["ticker"]]
            head = (f"• 🌙{r['ticker']} 盤後 {r['drop_pct']}%（收 {r['close']}）" if r.get("session") == "ah"
                    else f"• {r['ticker']} {r['drop_pct']}% 收 {r['close']}")
            if mine[0]["leg"] == "—":
                T.append(f"{head}｜{r.get('note', '')}")
                continue
            head += f"｜ρ {r.get('rho', '')}（到期 {r.get('expiry', '')}）"
            for x in mine:
                if x.get("strike"):
                    head += f"｜{'P' if x['leg'] == 'put95' else 'C'}{x['strike']} @{x['fill']} 年化{x['yield_ann_pct']}%{'✅' if x['qualifies'] == 'Y' else ''}"
            if r.get("session") == "ah":
                head += "｜收市期權價未反映跌幅，明日收市再確認"
            if r.get("earnings_in_window") == "Y":
                head += "｜⚠️業績窗內"
            elif r.get("earnings_in_window") == "?":
                head += "｜業績日未知"
            T.append(head)
    L += ["", "當日跌幅最大 5 隻：" + "、".join(f"{w['ticker']} {w['ret'] * 100:+.1f}%" for w in worst), ""]
    if settled:
        L += ["## 紙上到期結算", ""] + [f"- {s}" for s in settled] + [""]
        T += settled
    L += ["## 前向紀錄", "", fwd, ""]
    T.append(fwd)
    return "\n".join(L), "\n".join(T)


# ───────────────────────── 自檢（離線） ─────────────────────────
def selftest() -> None:
    F, K, T, df = 100.0, 95.0, 30 / 365, math.exp(-0.04 * 30 / 365)
    p, _ = bs_fwd(F, K, T, df, 0.35, "p")
    assert abs(implied_vol(F, K, T, df, p, "p") - 0.35) < 1e-5
    c, _ = bs_fwd(F, 105, T, df, 0.3, "c")
    assert abs(implied_vol(F, 105, T, df, c, "c") - 0.3) < 1e-5
    # rv_pre：常數報酬 → 0；大跌日唔計
    adj = [100 * 1.001 ** i for i in range(70)] + [50.0]
    assert rv_pre(adj) < 1e-9
    assert pick_expiry([date(2026, 11, 6), date(2026, 11, 27), date(2026, 12, 18)], date(2026, 10, 29)) == date(2026, 11, 27)
    # 美股：2026-10-29 GOOG 快照（handoff：11-20 平值 IV ≈ 31.4%）
    snap = ROOT / "analysis" / "opt_snapshot" / "2026-10-29"
    if (snap / "GOOG_chain.csv").exists():
        with open(snap / "GOOG_chain.csv", newline="", encoding="utf-8") as f:
            ch = [r for r in csv.DictReader(f) if r["expiry"] == "2026-11-20"]
        q = us_legs(ch, 280.985, date(2026, 10, 29), date(2026, 11, 20), 0.04)
        print("GOOG 11-20：平值 IV", round(q["atm_iv"], 4), {k: (v["strike"], v["bid"], v["ask"]) for k, v in q["legs"].items()})
        assert 0.25 < q["atm_iv"] < 0.40 and q["legs"]["put95"]["strike"] <= 0.95 * 280.985 and q["legs"]["call105"]["strike"] >= 1.05 * 280.985
        with open(snap / "GOOG_px.csv", newline="", encoding="utf-8") as f:
            adj = [float(r["adjclose"]) for r in csv.DictReader(f)]
        print("GOOG RV63pre（不含 10-29）", round(rv_pre(adj), 4))
    # 港股：港交所日報解析
    live = sorted((ROOT / "data" / "options_equity" / "live").glob("hk_dqe_*.htm.gz"))
    if live:
        rec = parse_hkex(gzip.decompress(live[-1].read_bytes()).decode("latin-1"))
        d = date.fromisoformat(live[-1].name[7:17])
        t = rec["0700.HK"]
        q = hk_legs(t, t["spot"], d)
        print(f"港交所 {d}：{len(rec)} 隻；0700.HK spot {t['spot']} 到期 {q['expiry']} 平值 IV {q['atm_iv']:.3f}",
              {k: (v["strike"], v["mid"], round(v["fill"], 3)) for k, v in q["legs"].items()})
        assert 0.1 < q["atm_iv"] < 1.0 and q["legs"]["put95"]["fill"] < q["legs"]["put95"]["mid"]
    # 結算
    paper = [dict(market="us", ticker="X", leg="put95", status="open", expiry="2026-01-16", strike="95", spot="100", fill="2"),
             dict(market="us", ticker="X", leg="call105", status="open", expiry="2026-01-16", strike="105", spot="100", fill="1.5")]
    settle_paper(paper, "us", date(2026, 1, 20), {"X": [(date(2026, 1, 16), 90.0, 90.0, 1)]})
    assert abs(float(paper[0]["pnl_pct"]) - (2 - 5) / 95 * 100) < 1e-3 and paper[0]["assigned"] == "Y"
    assert abs(float(paper[1]["pnl_pct"]) - 1.5) < 1e-3 and paper[1]["assigned"] == "N"
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["us", "hk"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.market:
        selftest()
        sys.exit(0)
    sys.exit(run(a.market))
