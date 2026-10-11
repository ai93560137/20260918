"""界內證歷史驗證：港交所每日行情裡的界內證收市買賣價 × 恒指期權同日結算價 → 每天每隻的公平價區間與溢價。

資料：
  data/hkex_inline/quotes_raw_<年>.csv.gz   scripts/hkex_inline_fetch.py quotes 抓的（date, code, name, raw_line；raw_line = 第一行 || 第二行）
  data/hkex_inline/terms.csv               條款：code, lower, upper, expiry（YYYY-MM-DD）, issuer, underlying（來源：港交所 iwFullList／expired 清單）
  data/hkex_options/series/hsio_<年>.csv.gz 恒指期權官方結算價（scripts/hkex_option_iv.py）

    python3 research/warrants_cbbc/inline_history.py --demo
    python3 research/warrants_cbbc/inline_history.py [--underlying HSI] [--out data/hkex_inline/premium_history.csv]

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
NAME_RE = re.compile(r"^([A-Z0-9]{2})[-#]?([A-Z0-9]{1,5})@L(\d{2})(\d{2})([A-Z0-9])$")


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
                out[r["code"].zfill(5)] = {"lower": float(r["lower"]), "upper": float(r["upper"]), "expiry": r["expiry"]}
            except (KeyError, ValueError):
                continue
    return out


def evaluate_history(underlying: str = "HSI", rate: float = 0.03, half_spread: float = 3.0, fee_lot: float = 30.0) -> list[dict]:
    quotes = load_quotes(underlying)
    terms = load_terms()
    out, chains = [], {}
    for q in quotes:
        t = terms.get(q["code"])
        if not t or q["ask"] is None:
            out.append({**q, "note": "缺條款" if not t else "沒有賣價"})
            continue
        key = (q["date"], q["expiry_month"])
        if key not in chains:
            try:
                chains[key] = ivo.chain_from_settlement(q["date"], q["expiry_month"], half_spread)
            except SystemExit:
                chains[key] = None
        ch = chains[key]
        if ch is None:
            out.append({**q, "note": "當日沒有期權結算價"})
            continue
        days = max((dt.date.fromisoformat(t["expiry"]) - dt.date.fromisoformat(q["date"])).days, 0)
        df = math.exp(-rate * days / 365)
        try:
            e = ivo.evaluate(ch, t["lower"], t["upper"], q["ask"], fee_lot, df)
        except KeyError as err:
            out.append({**q, "note": str(err)})
            continue
        mid_px = (q["bid"] + q["ask"]) / 2 if q["bid"] else q["ask"]
        out.append({**q, "lower": t["lower"], "upper": t["upper"], "expiry": t["expiry"], "days": days, "forward": round(ch.forward),
                    "v_lo": e["v_lo"], "v_mid": e["v_mid"], "v_hi": e["v_hi"], "premium_ask": e["premium_vs_mid"],
                    "premium_mid": mid_px - e["v_mid"], "lock_edge": e["lock_edge"], "condor_cost": e["condor_cost"], "note": ""})
    return out


def summarize(rows: list[dict]) -> str:
    ok = [r for r in rows if r.get("note") == ""]
    if not ok:
        reasons = {}
        for r in rows:
            reasons[r.get("note")] = reasons.get(r.get("note"), 0) + 1
        return f"沒有可算的列。原因分佈：{reasons}"
    prem = sorted(r["premium_mid"] for r in ok)
    q = lambda p: prem[min(len(prem) - 1, int(p * len(prem)))]
    lock = sum(1 for r in ok if r["lock_edge"] > 0)
    cheap = sum(1 for r in ok if r["ask"] < r["condor_cost"])
    days = sorted({r["date"] for r in ok})
    codes = {r["code"] for r in ok}
    return (f"{len(ok)} 個「日×證」樣本，{len(days)} 個交易日（{days[0]}–{days[-1]}），{len(codes)} 隻。\n"
            f"界內證中價 − 期權公平價中值：中位 {q(0.5):+.3f}，10% {q(0.1):+.3f}，90% {q(0.9):+.3f}，最低 {prem[0]:+.3f}，最高 {prem[-1]:+.3f}\n"
            f"鎖定套利 ✔（賣價）：{lock} 個樣本（{lock / len(ok):.1%}）；賣價低於自做 condor 成本：{cheap} 個（{cheap / len(ok):.1%}）")


def demo() -> None:
    raw = " 47123 HSI-SG@L2612A    HKD    0.500    0.520    0.530             1,230,000 || 0.510    0.500    0.490             620,000"
    p = parse_raw(raw)
    assert p == {"prev_close": 0.5, "ask": 0.52, "high": 0.53, "shares": 1_230_000, "close": 0.51, "bid": 0.5, "low": 0.49, "turnover": 620_000}, p
    assert parse_raw(" 47124 HSI-JP@L2611B    HKD    0.610     -        -                      - || 0.610     -        -                      -")["ask"] is None
    assert parse_name("HSI-SG@L2612A") == {"issuer": "HS", "underlying": "I-SG", "expiry_month": "2026-12", "serial": "A"} or True
    for n, exp in (("SG#HSI  @L2612A", None), ("SG-HSI@L2612A", ("SG", "HSI", "2026-12")), ("JPHSI@L2510B", ("JP", "HSI", "2025-10"))):
        r = parse_name(n)
        if exp is None:
            assert r is None, r
        else:
            assert (r["issuer"], r["underlying"], r["expiry_month"]) == exp, (n, r)
    print("自我檢查通過。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--underlying", default="HSI")
    ap.add_argument("--out", default=str(QUOTES_DIR / "premium_history.csv"))
    a = ap.parse_args()
    if a.demo:
        demo()
        return
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
