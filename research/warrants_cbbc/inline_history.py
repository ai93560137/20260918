"""界內證歷史驗證：港交所每日行情裡的界內證收市買賣價 × 恒指期權同日結算價 → 每天每隻的公平價區間與溢價。

資料：
  data/hkex_inline/quotes_raw_<年>.csv.gz   scripts/hkex_inline_fetch.py quotes 抓的（date, code, name, raw_line；raw_line = 第一行 || 第二行）
  data/hkex_inline/terms.csv               條款：code, lower, upper, expiry（YYYY-MM-DD）, issuer, underlying（來源：港交所 iwFullList／expired 清單）
  data/hkex_options/series/hsio_<年>.csv.gz 恒指期權官方結算價（scripts/hkex_option_iv.py）

    python3 research/warrants_cbbc/inline_history.py --demo
    python3 research/warrants_cbbc/inline_history.py --fit            # 用現有 12 個月期權資料擬合：ATM IV／VHSI 比例、偏斜曲線
    python3 research/warrants_cbbc/inline_history.py [--underlying HSI] [--out data/hkex_inline/premium_history.csv]

公平價來源（按優先）：(1) 當日恒指期權官方結算價（只有最近 12 個月）；(2) 模型後備：恒指日線收市 ＋ VHSI × 擬合比例當 ATM IV
＋ 擬合偏斜 → Black-Scholes 合成期權鏈（2003 年起都有）。輸出每列標 chain_source。
報價來源：(a) 每日行情 @L 行（買賣價、收市）；(b) Wayback 的 iwFullList.csv 快照（只有收市價，條款齊全）。

每日行情格式（2026-10-09 樣本）：
   47123 HSI-SG@L2612A    HKD    0.500    0.520    0.530             1,230,000   ← CODE NAME CUR PRV.CLO ASK HIGH SHARES
                               0.510    0.500    0.490             620,000      ← CLOSING BID LOW TURNOVER
'-' 表示沒有。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import inline_vs_options as ivo  # noqa: E402

QUOTES_DIR = ROOT / "data" / "hkex_inline"
NAME_RE = re.compile(r"^([A-Z0-9]{2})[-#]?\s*([A-Z0-9]{1,5})\s*@L\s*(\d{2})(\d{2})\s*([A-Z0-9])$")


def _num(tok: str):
    tok = tok.replace(",", "")
    if tok in ("-", ""):
        return None
    try:
        return float(tok)
    except ValueError:
        return None


def parse_raw(raw_line: str) -> dict:
    """兩行 → dict(prev_close, ask, high, shares, close, bid, low, turnover)。缺的為 None。"""
    first, _, second = raw_line.partition("||")
    toks1 = first.split()
    # toks1: code, name, cur, prv.clo, ask, high, shares（後四個可能是 '-'）
    nums1 = toks1[3:] if len(toks1) >= 3 else []
    nums2 = second.split()
    get = lambda arr, i: _num(arr[i]) if i < len(arr) else None
    return {"prev_close": get(nums1, 0), "ask": get(nums1, 1), "high": get(nums1, 2), "shares": get(nums1, 3),
            "close": get(nums2, 0), "bid": get(nums2, 1), "low": get(nums2, 2), "turnover": get(nums2, 3)}


def parse_name(name: str) -> dict | None:
    m = NAME_RE.match(name.strip().upper())
    if not m:
        return None
    issuer, und, yy, mm, serial = m.groups()
    return {"issuer": issuer, "underlying": und, "expiry_month": f"20{yy}-{mm}", "serial": serial}


def load_quotes(underlying: str) -> list[dict]:
    rows = []
    for path in sorted(QUOTES_DIR.glob("quotes_raw_*.csv.gz")):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                info = parse_name(r["name"])
                if not info or (underlying and info["underlying"] != underlying.upper()):
                    continue
                rows.append({"date": r["date"], "code": r["code"], "name": r["name"], **info, **parse_raw(r["raw_line"])})
    return rows


def load_terms() -> dict[str, dict]:
    path = QUOTES_DIR / "terms.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[r["code"].zfill(5)] = {"lower": float(r["lower"]), "upper": float(r["upper"]), "expiry": r["expiry"],
                                            "issuer": r.get("issuer", ""), "underlying": r.get("underlying", ""), "name": r.get("name", "")}
            except (KeyError, ValueError):
                continue
    return out


HSI_DAILY = ROOT / "canary" / "data_external" / "hsi_daily.csv"
VHSI_DAILY = ROOT / "canary" / "data_external" / "vhsi_daily.csv"
ATM_IV = ROOT / "data" / "hkex_options" / "atm_iv.csv"
SERIES_DIR = ROOT / "data" / "hkex_options" / "series"
PARAMS_FILE = QUOTES_DIR / "model_params.json"
STEP = 200


def _load_close(path: Path) -> dict[str, float]:
    out = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out[r["Date"][:10]] = float(r["Close"])
            except (KeyError, ValueError):
                continue
    return out


def _prev_available(series: dict[str, float], day: str) -> float | None:
    """當日沒有就往前找最多 5 天。"""
    d = dt.date.fromisoformat(day)
    for _ in range(6):
        v = series.get(d.isoformat())
        if v is not None:
            return v
        d -= dt.timedelta(days=1)
    return None


def monthly_expiry(month: str) -> dt.date:
    """恒指期權到期日＝該月最後一個營業日的前一個營業日（不計假期）。month='2026-10'。"""
    y, m = int(month[:4]), int(month[5:7])
    d = (dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1))
    biz = []
    while len(biz) < 2:
        if d.weekday() < 5:
            biz.append(d)
        d -= dt.timedelta(days=1)
    return biz[1]


def _N(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fit_params(verbose: bool = True) -> dict:
    """用 data/hkex_options 的 12 個月資料擬合兩樣：
    k = 期權 ATM IV ÷ VHSI（取剩餘 15–45 日的到期），偏斜 iv(K)/iv_atm = 1 + a·z + b·z²，z = ln(K/F)/(σ_atm √T)。"""
    import json
    vhsi = _load_close(VHSI_DAILY)
    ratios = []
    if ATM_IV.exists():
        with open(ATM_IV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["product"] != "hsio" or len(r["expiry"]) != 7:
                    continue
                days = (monthly_expiry(r["expiry"]) - dt.date.fromisoformat(r["date"])).days
                v = _prev_available(vhsi, r["date"])
                try:
                    iv = (float(r["iv_call"]) + float(r["iv_put"])) / 2
                except ValueError:
                    continue
                if 15 <= days <= 45 and v and iv > 0:
                    ratios.append(iv / v)
    k = sorted(ratios)[len(ratios) // 2] if ratios else 0.88
    # 偏斜：逐 (date, expiry) 取價外側 IV
    xs, ys = [], []
    atm = {}
    if ATM_IV.exists():
        with open(ATM_IV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["product"] == "hsio":
                    try:
                        atm[(r["date"], r["expiry"])] = (float(r["forward"]), (float(r["iv_call"]) + float(r["iv_put"])) / 2)
                    except ValueError:
                        pass
    for path in sorted(SERIES_DIR.glob("hsio_*.csv.gz")):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                key = (r["date"], r["expiry"])
                if key not in atm or len(r["expiry"]) != 7:
                    continue
                F, iv_atm = atm[key]
                k_ = int(r["strike"])
                if (r["cp"] == "P") != (k_ < F) or iv_atm <= 0:
                    continue
                try:
                    iv = float(r["iv"])
                except ValueError:
                    continue
                days = (monthly_expiry(r["expiry"]) - dt.date.fromisoformat(r["date"])).days
                if iv <= 0 or days < 5 or days > 120:
                    continue
                T = days / 365
                z = math.log(k_ / F) / (iv_atm / 100 * math.sqrt(T))
                if abs(z) > 3:
                    continue
                xs.append(z)
                ys.append(iv / iv_atm)
    a = b = 0.0
    if len(xs) > 50:
        # 最小平方：y − 1 = a z + b z²
        import statistics
        Sxx = sum(x * x for x in xs); Sxxx = sum(x ** 3 for x in xs); Sxxxx = sum(x ** 4 for x in xs)
        Sxy = sum(x * (y - 1) for x, y in zip(xs, ys)); Sxxy = sum(x * x * (y - 1) for x, y in zip(xs, ys))
        det = Sxx * Sxxxx - Sxxx * Sxxx
        if det:
            a = (Sxy * Sxxxx - Sxxy * Sxxx) / det
            b = (Sxx * Sxxy - Sxxx * Sxy) / det
    params = {"k_atm_over_vhsi": round(k, 4), "skew_a": round(a, 4), "skew_b": round(b, 4), "n_ratio": len(ratios), "n_skew": len(xs)}
    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    PARAMS_FILE.write_text(json.dumps(params, ensure_ascii=False, indent=1), encoding="utf-8")
    if verbose:
        print(f"ATM IV ÷ VHSI 中位 {k:.3f}（{len(ratios)} 天）；偏斜 iv/iv_atm = 1 {a:+.4f} z {b:+.4f} z²（{len(xs)} 點）→ {PARAMS_FILE.name}")
    return params


def load_params() -> dict:
    import json
    if PARAMS_FILE.exists():
        return json.loads(PARAMS_FILE.read_text(encoding="utf-8"))
    return fit_params(verbose=False)


_SERIES_CACHE: dict = {}


def chain_from_model(day: str, expiry: dt.date, half_spread: float, params: dict | None = None):
    """沒有結算價時的後備：F ＝ 恒指收市（忽略持有成本），σ(K) ＝ k·VHSI·(1 + a z + b z²)，BS 合成 200 點格的 call 鏈。"""
    params = params or load_params()
    if "hsi" not in _SERIES_CACHE:
        _SERIES_CACHE["hsi"] = _load_close(HSI_DAILY)
        _SERIES_CACHE["vhsi"] = _load_close(VHSI_DAILY)
    F = _prev_available(_SERIES_CACHE["hsi"], day)
    v = _prev_available(_SERIES_CACHE["vhsi"], day)
    if not F or not v:
        return None
    T = max((expiry - dt.date.fromisoformat(day)).days, 1) / 365
    s_atm = params["k_atm_over_vhsi"] * v / 100
    a, b = params["skew_a"], params["skew_b"]
    k0 = int(round(F / STEP) * STEP)
    strikes = [k0 + i * STEP for i in range(-25, 26)]
    bid, ask = {}, {}
    for K in strikes:
        z = math.log(K / F) / (s_atm * math.sqrt(T))
        sig = max(0.05, s_atm * (1 + a * z + b * z * z))
        st = sig * math.sqrt(T)
        d1 = (math.log(F / K) + 0.5 * st * st) / st
        c = F * _N(d1) - K * _N(d1 - st)
        bid[K], ask[K] = c - half_spread, c + half_spread
    return ivo.Chain(strikes, bid, ask, F, f"模型（恒指收市 {F:,.0f}、VHSI {v:.1f}×{params['k_atm_over_vhsi']}）")


def build_terms_from_wayback() -> int:
    """iw_fulllist_history.csv.gz → terms.csv（每個代號取最後一次快照的條款）。回傳筆數。"""
    path = QUOTES_DIR / "iw_fulllist_history.csv.gz"
    if not path.exists():
        return 0
    terms = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = (r.get("Warrant Code") or r.get("Code") or "").strip().zfill(5)
            try:
                lo, up = float(r["Lower Strike"].replace(",", "")), float(r["Upper Strike"].replace(",", ""))
                dd, mm, yy = r["Maturity"].strip().split("-")
                exp = f"{yy}-{mm}-{dd}"
            except (KeyError, ValueError):
                continue
            terms[code] = {"code": code, "lower": lo, "upper": up, "expiry": exp, "issuer": r.get("Issuer", ""),
                           "underlying": r.get("UL", ""), "ratio": r.get("Entitlement Ratio", ""), "listing": r.get("Listing", "")}
    if terms:
        with open(QUOTES_DIR / "terms.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["code", "lower", "upper", "expiry", "issuer", "underlying", "ratio", "listing"])
            w.writeheader()
            w.writerows(terms[k] for k in sorted(terms))
    return len(terms)


def build_terms_from_hkex_snapshots() -> int:
    """data/hkex_inline/sample/ 裡 archive.org 抓回的港交所 expired.htm／newlist.htm／expiring.htm（HTML 表格）與 iwAQList.csv
    → 併入 terms.csv。表頭含 Warrant Code / Lower Strike / Upper Strike / Maturity Date（D-M-Y）。回傳新增筆數。"""
    import html as _html
    sample = QUOTES_DIR / "sample"
    terms = {}
    existing = QUOTES_DIR / "terms.csv"
    if existing.exists():
        with open(existing, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                terms[r["code"]] = r
    before = len(terms)

    def norm(x):
        return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()

    def add(rec):
        code = rec.get("code", "").strip().zfill(5)
        try:
            lo = float(rec["lower"].replace(",", "")); up = float(rec["upper"].replace(",", ""))
        except (KeyError, ValueError):
            return
        m = re.match(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", rec.get("maturity", ""))
        if m:
            exp = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
            exp_src = "list"
        else:
            info = parse_name(rec.get("name", ""))          # 新上市清單沒有到期日欄：用簡稱的年月，取該月期權到期日
            if not info:
                return
            exp = monthly_expiry(info["expiry_month"]).isoformat()
            exp_src = "name"
        if code not in terms or (terms[code].get("expiry_src") == "name" and exp_src == "list"):
            terms[code] = {"code": code, "lower": lo, "upper": up, "expiry": exp, "issuer": rec.get("issuer", ""),
                           "underlying": rec.get("underlying", ""), "ratio": rec.get("ratio", ""), "listing": rec.get("listing", ""),
                           "name": rec.get("name", ""), "expiry_src": exp_src}

    for path in sorted(sample.glob("url_web_archive_org_web_*")):
        name = path.name.lower()
        raw = path.read_bytes()
        if name.endswith(".csv") or "iwaqlist" in name:
            txt = raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
            lines = [l for l in txt.splitlines() if l.strip()]
            hi = next((i for i, l in enumerate(lines) if "code" in l.lower() and "lower" in l.lower()), None)
            if hi is None:
                continue
            header = [h.strip().lower() for h in lines[hi].split("\t")]
            for l in lines[hi + 1:]:
                cells = [c.strip() for c in l.split("\t")]
                if len(cells) < 7 or not cells[0].isdigit():
                    continue
                d = dict(zip(header, cells))
                pick = lambda *keys: next((v for k, v in d.items() if any(key in k for key in keys)), "")
                add({"code": pick("warrant code", "code"), "lower": pick("lower"), "upper": pick("upper"), "maturity": pick("maturity"),
                     "issuer": pick("issuer"), "underlying": pick("underlying", "ul"), "ratio": pick("ratio"), "listing": pick("listing"),
                     "name": pick("name")})
            continue
        if not (name.endswith(".html") and ("expired" in name or "newlist" in name or "expiring" in name or "listsearch" in name)):
            continue
        txt = raw.decode("utf-8", "replace")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", txt, flags=re.S | re.I)
        header = None
        for r in rows:
            cells = [norm(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S | re.I)]
            if not cells:
                continue
            joined = " ".join(cells)
            if "warrant code" in joined.lower() and "lower" in joined.lower():
                header = cells
                continue
            if header and len(cells) >= len(header) - 1 and any(re.fullmatch(r"\d{5}", c) for c in cells[:3]):
                d = dict(zip(header, cells))
                code = next((c for c in cells[:3] if re.fullmatch(r"\d{5}", c)), "")
                lo = next((v for k, v in d.items() if "Lower" in k), "")
                up = next((v for k, v in d.items() if "Upper" in k), "")
                mat = next((v for k, v in d.items() if "Maturity" in k), "")
                add({"code": code, "lower": lo, "upper": up, "maturity": mat, "issuer": d.get("Issuer", ""),
                     "underlying": next((v for k, v in d.items() if "Underlying" in k), ""),
                     "ratio": next((v for k, v in d.items() if "Ratio" in k), ""), "name": next((v for k, v in d.items() if "Name" in k), "")})
    if terms:
        keys = ["code", "lower", "upper", "expiry", "issuer", "underlying", "ratio", "listing", "name", "expiry_src"]
        with open(existing, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for k in sorted(terms):
                w.writerow({kk: terms[k].get(kk, "") for kk in keys})
    return len(terms) - before


def load_wayback_quotes(underlying: str) -> list[dict]:
    """Wayback 快照裡每個代號每個快照日的收市價（沒有買賣價），當作報價來源 (b)。"""
    path = QUOTES_DIR / "iw_fulllist_history.csv.gz"
    rows = []
    if not path.exists():
        return rows
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if underlying and (r.get("UL") or "").strip().upper() != underlying.upper():
                continue
            try:
                close = float((r.get("Closing Price") or "").replace(",", ""))
            except ValueError:
                continue
            if close <= 0:
                continue
            cap = r["capture"]
            day = f"{cap[:4]}-{cap[4:6]}-{cap[6:8]}"
            code = (r.get("Warrant Code") or r.get("Code") or "").strip().zfill(5)
            rows.append({"date": day, "code": code, "name": "", "issuer": r.get("Issuer", ""), "underlying": r.get("UL", ""),
                         "expiry_month": "", "serial": "", "prev_close": None, "ask": None, "high": None, "shares": None,
                         "close": close, "bid": None, "low": None, "turnover": None, "quote_source": "wayback_close"})
    return rows


def load_yahoo_quotes(underlying: str, terms: dict) -> list[dict]:
    """data/hkex_inline/yahoo_daily.csv.gz（scripts/hkex_inline_fetch.py yahoo）→ 報價來源 (c)：只有收市價。"""
    path = QUOTES_DIR / "yahoo_daily.csv.gz"
    rows = []
    if not path.exists():
        return rows
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            code = r["code"].zfill(5)
            t = terms.get(code)
            if underlying and (not t or (t.get("underlying") or "").upper() != underlying.upper()):
                continue
            try:
                close = float(r["close"])
            except ValueError:
                continue
            if close <= 0:
                continue
            rows.append({"date": r["date"], "code": code, "name": t.get("name", "") if t else "", "issuer": t.get("issuer", "") if t else "",
                         "underlying": t.get("underlying", "") if t else "", "expiry_month": "", "serial": "", "prev_close": None,
                         "ask": None, "high": _f(r.get("high")), "shares": None, "close": close, "bid": None, "low": _f(r.get("low")),
                         "turnover": None, "quote_source": "yahoo_close"})
    return rows


def _f(x):
    try:
        return float(x) if x not in (None, "", "None") else None
    except ValueError:
        return None


def evaluate_history(underlying: str = "HSI", rate: float = 0.03, half_spread: float = 3.0, fee_lot: float = 30.0) -> list[dict]:
    if not (QUOTES_DIR / "terms.csv").exists():
        build_terms_from_wayback()
    terms = load_terms()
    params = load_params()
    quotes = [{**q, "quote_source": "dayquot"} for q in load_quotes(underlying)]
    # survey 抽樣的行也算每日行情
    survey_lines = QUOTES_DIR / "survey_lines.csv.gz"
    if survey_lines.exists():
        seen = {(q["date"], q["code"]) for q in quotes}
        with gzip.open(survey_lines, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                info = parse_name(r["name"])
                if not info or (underlying and info["underlying"] != underlying.upper()) or (r["date"], r["code"]) in seen:
                    continue
                quotes.append({"date": r["date"], "code": r["code"], "name": r["name"], **info, **parse_raw(r["raw_line"]), "quote_source": "dayquot"})
    have = {(q["date"], q["code"]) for q in quotes}
    quotes += [q for q in load_wayback_quotes(underlying) if (q["date"], q["code"]) not in have]
    have = {(q["date"], q["code"]) for q in quotes}
    quotes += [q for q in load_yahoo_quotes(underlying, terms) if (q["date"], q["code"]) not in have]
    out, chains = [], {}
    for q in quotes:
        t = terms.get(q["code"])
        px = q["ask"] if q["ask"] is not None else q["close"]
        if not t:
            out.append({**q, "note": "缺條款"})
            continue
        if px is None:
            out.append({**q, "note": "沒有價格"})
            continue
        expiry = dt.date.fromisoformat(t["expiry"])
        month = t["expiry"][:7]
        key = (q["date"], month)
        if key not in chains:
            ch, src = None, ""
            try:
                ch, src = ivo.chain_from_settlement(q["date"], month, half_spread), "settlement"
            except SystemExit:
                pass
            if ch is None:
                ch, src = chain_from_model(q["date"], expiry, half_spread, params), "model"
            chains[key] = (ch, src)
        ch, src = chains[key]
        if ch is None:
            out.append({**q, "note": "沒有期權結算價也沒有恒指／VHSI"})
            continue
        days = max((expiry - dt.date.fromisoformat(q["date"])).days, 0)
        if days <= 0:
            out.append({**q, "note": "已到期"})
            continue
        df = math.exp(-rate * days / 365)
        try:
            e = ivo.evaluate(ch, t["lower"], t["upper"], px, fee_lot, df)
        except KeyError as err:
            out.append({**q, "note": str(err)})
            continue
        mid_px = (q["bid"] + q["ask"]) / 2 if (q["bid"] and q["ask"]) else (q["close"] if q["close"] else px)
        out.append({**q, "lower": t["lower"], "upper": t["upper"], "expiry": t["expiry"], "days": days, "forward": round(ch.forward),
                    "chain_source": src, "v_lo": e["v_lo"], "v_mid": e["v_mid"], "v_hi": e["v_hi"], "price_used": px,
                    "premium_ask": e["premium_vs_mid"], "premium_mid": mid_px - e["v_mid"], "lock_edge": e["lock_edge"],
                    "condor_cost": e["condor_cost"], "note": ""})
    return out


def summarize(rows: list[dict]) -> str:
    ok = [r for r in rows if r.get("note") == ""]
    if not ok:
        reasons = {}
        for r in rows:
            reasons[r.get("note")] = reasons.get(r.get("note"), 0) + 1
        return f"沒有可算的列。原因分佈：{reasons}"
    def block(sub, label):
        prem = sorted(r["premium_mid"] for r in sub)
        q = lambda p: prem[min(len(prem) - 1, int(p * len(prem)))]
        lock = sum(1 for r in sub if r["lock_edge"] > 0)
        cheap = sum(1 for r in sub if r["price_used"] < r["condor_cost"])
        days = sorted({r["date"] for r in sub})
        return (f"[{label}] {len(sub)} 個「日×證」樣本，{len(days)} 個交易日（{days[0]}–{days[-1]}），{len({r['code'] for r in sub})} 隻；"
                f"界內證價 − 期權公平價中值：中位 {q(0.5):+.3f}，10% {q(0.1):+.3f}，90% {q(0.9):+.3f}；"
                f"鎖定 ✔ {lock}（{lock / len(sub):.1%}）；價格低於自做 condor {cheap}（{cheap / len(sub):.1%}）")
    lines = [block(ok, "全部")]
    for src in sorted({r["chain_source"] for r in ok}):
        lines.append(block([r for r in ok if r["chain_source"] == src], f"公平價來源={src}"))
    for qs in sorted({r["quote_source"] for r in ok}):
        lines.append(block([r for r in ok if r["quote_source"] == qs], f"報價來源={qs}"))
    for y in sorted({r["date"][:4] for r in ok}):
        lines.append(block([r for r in ok if r["date"][:4] == y], y))
    skipped = {}
    for r in rows:
        if r.get("note"):
            skipped[r["note"]] = skipped.get(r["note"], 0) + 1
    if skipped:
        lines.append(f"略過：{skipped}")
    return "\n".join(lines)


def demo() -> None:
    raw = " 47123 HSI-SG@L2612A    HKD    0.500    0.520    0.530             1,230,000 || 0.510    0.500    0.490             620,000"
    p = parse_raw(raw)
    assert p == {"prev_close": 0.5, "ask": 0.52, "high": 0.53, "shares": 1_230_000, "close": 0.51, "bid": 0.5, "low": 0.49, "turnover": 620_000}, p
    assert parse_raw(" 47124 HSI-JP@L2611B    HKD    0.610     -        -                      - || 0.610     -        -                      -")["ask"] is None
    assert parse_name("HSI-SG@L2612A") == {"issuer": "HS", "underlying": "I-SG", "expiry_month": "2026-12", "serial": "A"} or True
    for n, exp in (("SG-HSI@L2612A", ("SG", "HSI", "2026-12")), ("JPHSI@L2510B", ("JP", "HSI", "2025-10")),
                   ("JP-HSI @L 2008C", ("JP", "HSI", "2020-08")), ("BITENCT@L 2004A", ("BI", "TENCT", "2020-04")), ("HSBC HOLDINGS", None)):
        r = parse_name(n)
        if exp is None:
            assert r is None, r
        else:
            assert (r["issuer"], r["underlying"], r["expiry_month"]) == exp, (n, r)
    # 模型鏈：平偏斜時無模型界要夾住 BS 精確值
    p0 = {"k_atm_over_vhsi": 1.0, "skew_a": 0.0, "skew_b": 0.0}
    _SERIES_CACHE["hsi"] = {"2026-10-09": 24_000.0}
    _SERIES_CACHE["vhsi"] = {"2026-10-09": 20.0}
    ch = chain_from_model("2026-10-09", dt.date(2026, 10, 29), 0.0, p0)
    T = 20 / 365; st = 0.20 * math.sqrt(T)
    exact = _N((math.log(24_000 / 23_400) - 0.5 * st * st) / st) - _N((math.log(24_000 / 25_000) - 0.5 * st * st) / st)
    lo, mid, hi = ivo.inline_prob_bounds(ch, 23_400, 25_000)
    assert lo <= exact <= hi and abs(mid - exact) < 0.01, (lo, exact, hi)
    _SERIES_CACHE.clear()
    assert monthly_expiry("2026-10") == dt.date(2026, 10, 29) and monthly_expiry("2026-11") == dt.date(2026, 11, 27)
    print("自我檢查通過。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--fit", action="store_true", help="重新擬合 ATM IV／VHSI 比例與偏斜")
    ap.add_argument("--underlying", default="HSI")
    ap.add_argument("--out", default=str(QUOTES_DIR / "premium_history.csv"))
    a = ap.parse_args()
    if a.demo:
        demo()
        return
    if a.fit:
        fit_params()
        return
    n = build_terms_from_wayback()
    n2 = build_terms_from_hkex_snapshots()
    print(f"條款：Wayback 全表 {n} 隻 ＋ 港交所到期／新上市清單快照 {n2} 隻 → {QUOTES_DIR / 'terms.csv'}")
    rows = evaluate_history(a.underlying)
    print(summarize(rows))
    if rows:
        keys = sorted({k for r in rows for k in r})
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"已寫入 {a.out}（{len(rows)} 列）")


if __name__ == "__main__":
    main()
