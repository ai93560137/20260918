#!/usr/bin/env python3
"""外部來源 × 網站數據 抽樣比對（每日，接在 external_data_sync.py 之後）

目的：拿 Futu、IBKR 兩個券商來源，對照各分支從網站抓的數據，逐欄、逐日期比對。
任何一筆「無法解釋」的差異都讓該類數據 FAIL，金絲雀與各分支只取 PASS 的類別。

比對類別（每類各自一個閘門，見 data/external/qc/GATE.json）
  futu_vs_web     Futu 日線／5 分 K 合成日線  ↔ 網站日線（鳥翔分支 claude/gifted-carson-v2tvhw data/equities，Yahoo）
  ibkr_vs_web     IBKR 收市／次日開市／次日收市 ↔ 同上網站日線（每市場每次抽樣 SAMPLE_IBKR 檔）
  web_vs_web      Yahoo 收市 ↔ Nasdaq.com 第二收市源（美股，每次抽樣 SAMPLE_WEB 檔）
  canary_inputs   Futu 恒指 ↔ 金絲雀分支 canary/data_external/hsi_daily.csv（Yahoo ^HSI）
  internal        封存內部一致性：OHLC 關係、重複、交易時段、期權報價清洗規則（金絲雀手冊 §10，只記錄）

判定（預先登記，不事後調整；README「品質閘門」一節）
  ✅ 一致      |a − b| ≤ max(0.0005, 1e−6 × |b|)（吸收 Yahoo float32 尾數，不吸收任何一跳價差）
  ℹ️ 記錄      口徑本來就不同的欄位：5 分 K 合成的開盤（首筆成交 ≠ 開盤競價）、成交量
  ⏭️ 略過      對方沒有該日期（超出對方最新日期）、交易時段不完整、沒有對應數據
  ⚠️ 已知      命中 known_issues.csv 登記的已知原因（登記要寫原因與登記人）
  ❌ 未解釋    其他一切差異，包括「兩邊日期範圍重疊、卻只有一邊有這一天」的日期缺漏
  類別閘門：有 ❌ → FAIL；沒有任何 ✅ → NO_DATA；否則 PASS

抽樣以執行日（UTC）為種子，每天換一批，紀錄寫在報告裡，可重現。
同時產生明天給 Futu 抓日線的抽樣清單 data/external/qc/futu_sample.txt。
"""
import argparse
import csv
import gzip
import io
import json
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
EXT = Path(os.environ.get("EXTERNAL_DIR") or ROOT / "data" / "external")   # 測試時可改到暫存區
QC = EXT / "qc"
WEB_REF = "origin/claude/gifted-carson-v2tvhw"
CANARY_REF = "origin/claude/canary-playbook-final-3um9lp"
SAMPLE_IBKR = 20
SAMPLE_WEB = 30
SAMPLE_FUTU_US = 20
SAMPLE_FUTU_HK = 10
FUTU_ANCHORS = ["HK.800000", "US.SPY", "US.QQQ"]
US_TZ = ZoneInfo("America/New_York")

OK, INFO, SKIP, KNOWN, FAIL = "✅", "ℹ️", "⏭️", "⚠️", "❌"
FIELDS = ["family", "check", "instrument", "date", "field", "a_src", "a", "b_src", "b",
          "diff", "diff_pct", "verdict", "note"]


# ---------------------------------------------------------------- helpers
def tol_ok(a, b):
    return abs(a - b) <= max(0.0005, 1e-6 * abs(b))


def fnum(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def git_show(ref, path):
    try:
        return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True,
                              check=True).stdout.decode("utf-8")
    except subprocess.CalledProcessError:
        return None


def git_ls(ref, path):
    try:
        out = subprocess.run(["git", "ls-tree", "--name-only", ref, path], cwd=ROOT, capture_output=True,
                             check=True).stdout.decode()
    except subprocess.CalledProcessError:
        return []
    return [line.rsplit("/", 1)[-1] for line in out.split()]


def read_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class WebDaily:
    """網站日線（鳥翔分支 data/equities/<市場>/<代號>/prices_<年>.csv），按需讀取並快取。"""

    def __init__(self, ref):
        self.ref, self.cache = ref, {}

    def get(self, market, ticker, day):
        key = (market, ticker, day[:4])
        if key not in self.cache:
            text = git_show(self.ref, f"data/equities/{market}/{ticker}/prices_{day[:4]}.csv")
            self.cache[key] = {r["Date"]: r for r in csv.DictReader(io.StringIO(text))} if text else None
        rows = self.cache[key]
        return None if rows is None else rows.get(day)

    def span(self, market, ticker, year):
        self.get(market, ticker, f"{year}-01-01")
        rows = self.cache.get((market, ticker, str(year)))
        return (min(rows), max(rows)) if rows else None

    def has_ticker(self, market, ticker, year):
        return self.span(market, ticker, year) is not None

    def neighbour(self, market, ticker, day, step):
        """前一（step=−1）或後一（+1）個網站有數據的交易日 → (日期, 列)。"""
        self.get(market, ticker, day)
        rows = self.cache.get((market, ticker, day[:4])) or {}
        dates = sorted(rows)
        later = [d for d in dates if d > day] if step > 0 else [d for d in dates if d < day]
        if not later:
            return None, None
        pick = later[0] if step > 0 else later[-1]
        return pick, rows[pick]


def futu_to_web(code):
    """Futu 代號 → (網站市場, 網站代號)。HK.00700 → hk/0700.HK；HK.800000 → hk/_HSI；US.BRK.B → us/BRK-B。"""
    market, _, sym = code.partition(".")
    if market == "US":
        return "us", sym.replace(".", "-")
    if market == "HK":
        if sym == "800000":
            return "hk", "_HSI"
        return "hk", f"{int(sym):04d}.HK" if sym.isdigit() else sym
    return None, None


def web_to_futu(market, ticker):
    if market == "us":
        return "US." + ticker.replace("-", ".")
    if market == "hk" and ticker.endswith(".HK"):
        return f"HK.{int(ticker[:-3]):05d}"
    return None


# ---------------------------------------------------------------- report rows
class Report:
    def __init__(self, known):
        self.rows, self.known = [], known

    def add(self, family, check, instrument, day, field, a_src, a, b_src, b, verdict=None, note="",
            neighbours=None):
        """neighbours = {'前一交易日 MM-DD': 值, ...}：乙方相鄰日期的同欄位值，用來辨認日期錯位。"""
        diff = diff_pct = ""
        if a is not None and b is not None:
            diff = round(a - b, 6)
            diff_pct = round((a - b) / b * 100, 4) if b else ""
            if verdict is None:
                verdict = OK if tol_ok(a, b) else FAIL
            if verdict == FAIL and neighbours:
                for label, value in neighbours.items():
                    if value is not None and tol_ok(a, value):
                        note = (note + "；" if note else "") + f"日期錯位：{a_src} 的值等於 {b_src} 的{label}"
                        break
        if verdict == FAIL:
            cause = self.known.get((instrument, day, field)) or self.known.get((instrument, "*", field)) \
                or self.known.get((family + ":" + check, "*", field))
            if cause:
                verdict, note = KNOWN, (note + "；" if note else "") + "已知：" + cause
        self.rows.append({"family": family, "check": check, "instrument": instrument, "date": day,
                          "field": field, "a_src": a_src, "a": "" if a is None else a, "b_src": b_src,
                          "b": "" if b is None else b, "diff": diff, "diff_pct": diff_pct,
                          "verdict": verdict, "note": note})


def load_known():
    path = QC / "known_issues.csv"
    known = {}
    if path.exists():
        for row in csv.DictReader(path.open(encoding="utf-8")):
            known[(row["instrument"], row["date"], row["field"])] = f"{row['cause']}（{row['added_by']}）"
    return known


# ---------------------------------------------------------------- checks
def col(row, field):
    if row is None:
        return None
    return fnum(row.get(field.capitalize()) if field.capitalize() in row else row.get(field))


def compare_ohlc(rep, family, check, instrument, day, a_src, a_row, b_src, b_row, fields, info_fields=(),
                 prev=(None, None), nxt=(None, None)):
    for field in fields:
        a, b = col(a_row, field), col(b_row, field)
        if a is None or b is None:
            rep.add(family, check, instrument, day, field, a_src, a, b_src, b, SKIP, "一邊缺值")
            continue
        neighbours = {f"前一交易日 {prev[0]}": col(prev[1], field), f"後一交易日 {nxt[0]}": col(nxt[1], field)} \
            if prev[0] or nxt[0] else None
        rep.add(family, check, instrument, day, field, a_src, a, b_src, b,
                INFO if field in info_fields else None,
                "口徑不同，只記錄" if field in info_fields else "", neighbours)


def date_gaps(rep, family, check, instrument, a_src, a_dates, b_src, b_dates):
    """兩邊日期範圍重疊的區段內，只有一邊有的日期 = 日期缺漏（❌）。"""
    if not a_dates or not b_dates:
        return
    lo, hi = max(min(a_dates), min(b_dates)), min(max(a_dates), max(b_dates))
    for day in sorted((set(a_dates) ^ set(b_dates))):
        if lo <= day <= hi:
            has = a_src if day in a_dates else b_src
            rep.add(family, check, instrument, day, "date", a_src, None, b_src, None, FAIL,
                    f"日期缺漏：只有 {has} 有這一天")


def futu_intraday_daily(web, rep):
    """Futu 5 分 K 合成日線 ↔ 網站日線。完整交易時段才比最高／最低。"""
    for sym_dir in sorted((EXT / "futu").glob("*/K_5M")):
        code = sym_dir.parent.name
        market, ticker = futu_to_web(code)
        if market != "us":
            continue                                   # 港股時段有午休，另立規則前不合成
        for path in sorted(sym_dir.glob("*/*.csv.gz")):
            day, bars = path.name[:10], read_gz(path)
            bars = [b for b in bars if "09:35:00" <= b["time_key"][11:] <= "16:00:00"]
            if not bars:
                continue
            complete = len(bars) == 78 and bars[0]["time_key"][11:] == "09:35:00" \
                and bars[-1]["time_key"][11:] == "16:00:00"
            web_row = web.get(market, ticker, day)
            if web_row is None:
                rep.add("futu_vs_web", "5分K合成日線", code, day, "close", "futu", None, "web", None, SKIP,
                        "網站還沒有這一天")
                continue
            roll = {"open": bars[0]["open"], "high": max(float(b["high"]) for b in bars),
                    "low": min(float(b["low"]) for b in bars), "close": bars[-1]["close"],
                    "volume": sum(float(b["volume"] or 0) for b in bars)}
            fields = ["close", "high", "low", "open", "volume"] if complete else ["close"]
            compare_ohlc(rep, "futu_vs_web", "5分K合成日線", code, day, "futu_5m", roll, "web_yahoo", web_row,
                         fields, info_fields=("open", "volume"),
                         prev=web.neighbour(market, ticker, day, -1), nxt=web.neighbour(market, ticker, day, 1))
            if not complete:
                rep.add("futu_vs_web", "5分K合成日線", code, day, "open/high/low/volume", "futu_5m", None,
                        "web_yahoo", None, SKIP, f"交易時段不完整（{len(bars)}/78 根），只比收盤")


def futu_kday(web, canary_hsi, rep, today):
    """Futu 日線抽樣（futu/_K_DAY）↔ 網站日線；恒指另對金絲雀的 hsi_daily.csv。"""
    by_code = {}
    for path in sorted((EXT / "futu" / "_K_DAY").glob("*/*.csv.gz")):
        for row in read_gz(path):
            by_code.setdefault(row["code"], {})[row["time_key"][:10]] = row
    for code, days in sorted(by_code.items()):
        market, ticker = futu_to_web(code)
        if market is None:
            continue
        web_dates = set()
        for year in sorted({d[:4] for d in days}):
            span = web.span(market, ticker, year)
            if span:
                web_dates |= {d for d in web.cache[(market, ticker, year)]}
        for day, row in sorted(days.items()):
            web_row = web.get(market, ticker, day)
            if web_row is None:
                rep.add("futu_vs_web", "日線抽樣", code, day, "close", "futu_kday", fnum(row["close"]),
                        "web_yahoo", None, SKIP, "網站沒有這一天（超出網站最新日期或無此代號）")
                continue
            compare_ohlc(rep, "futu_vs_web", "日線抽樣", code, day, "futu_kday", row, "web_yahoo", web_row,
                         ["open", "high", "low", "close", "volume"], info_fields=("volume",),
                         prev=web.neighbour(market, ticker, day, -1), nxt=web.neighbour(market, ticker, day, 1))
        if web_dates:
            date_gaps(rep, "futu_vs_web", "日線抽樣", code, "futu_kday", set(days), "web_yahoo", web_dates)
        if code == "HK.800000" and canary_hsi:
            for day, row in sorted(days.items()):
                c_row = canary_hsi.get(day)
                if c_row is None:
                    rep.add("canary_inputs", "恒指", code, day, "close", "futu_kday", fnum(row["close"]),
                            "canary_hsi", None, SKIP if day > max(canary_hsi) else FAIL,
                            "金絲雀還沒有這一天（亞洲鳥慢一日，見手冊 §9.1）" if day > max(canary_hsi)
                            else "日期缺漏：金絲雀少了這一天")
                    continue
                compare_ohlc(rep, "canary_inputs", "恒指", code, day, "futu_kday", row, "canary_hsi", c_row,
                             ["open", "high", "low", "close"])


def canary_vs_web(web, rep):
    """金絲雀實際使用的指數日線 ↔ 鳥翔分支網站日線（最近 30 個交易日；兩邊都是 Yahoo，查抄錄與日期）。"""
    for fname, market, ticker in (("hsi_daily.csv", "hk", "_HSI"), ("spx_daily.csv", "us", "_GSPC")):
        text = git_show(CANARY_REF, f"canary/data_external/{fname}")
        if not text:
            rep.add("canary_inputs", fname, ticker, "", "all", "canary", None, "web", None, SKIP, "讀不到金絲雀檔案")
            continue
        canary = {r["Date"][:10]: r for r in csv.DictReader(io.StringIO(text))}
        year = max(canary)[:4]
        if not web.has_ticker(market, ticker, year):
            continue
        web_rows = web.cache[(market, ticker, year)]
        window = sorted(web_rows)[-30:]
        c_latest, w_latest = max(canary), max(web_rows)
        for day in window:
            if day not in canary:
                rep.add("canary_inputs", fname, ticker, day, "date", "canary", None, "web_yahoo", None,
                        SKIP if day > c_latest else FAIL,
                        f"金絲雀最新只到 {c_latest}（亞洲鳥慢一日屬手冊 §9.1 已知）" if day > c_latest
                        else "日期缺漏：金絲雀少了這一天")
                continue
            prev, nxt = web.neighbour(market, ticker, day, -1), web.neighbour(market, ticker, day, 1)
            compare_ohlc(rep, "canary_inputs", fname, ticker, day, "canary", canary[day], "web_yahoo",
                         web_rows[day], ["open", "high", "low", "close"], prev=prev, nxt=nxt)
        for day in sorted(d for d in canary if window[0] <= d <= w_latest and d not in web_rows):
            rep.add("canary_inputs", fname, ticker, day, "date", "canary", None, "web_yahoo", None, FAIL,
                    "日期缺漏：網站少了這一天")


def ibkr_vs_web(web, rep, rng):
    for path in sorted((EXT / "ibkr" / "stock_closes").glob("*_*.csv")):
        market = path.name.split("_", 1)[0]
        if market not in ("us", "hk"):
            rep.add("ibkr_vs_web", "股票收市", path.name, "", "all", "ibkr", None, "web", None, SKIP,
                    f"{market} 的網站日線不在鳥翔分支 data/equities（在 GitHub Release），本輪不比")
            continue
        rows = [r for r in csv.DictReader(path.open(encoding="utf-8")) if r.get("status") == "ok"]
        # 只從網站日線也有的代號抽樣，確保每市場每次真的比到 SAMPLE_IBKR 檔
        both = [r for r in rows if web.has_ticker(market, r["ticker"], r["signal_date"][:4])]
        if len(both) < len(rows):
            rep.add("ibkr_vs_web", "股票收市", path.name, "", "coverage", "ibkr", None, "web", None, SKIP,
                    f"{len(rows) - len(both)}／{len(rows)} 檔不在網站日線（鳥翔分支 data/equities），未比")
        for r in sorted(rng.sample(both, min(SAMPLE_IBKR, len(both))), key=lambda x: x["ticker"]):
            ticker = r["ticker"]
            for day, field, value in ((r["signal_date"], "close", r["ib_close"]),
                                      (r["next_date"], "open", r["ib_next_open"]),
                                      (r["next_date"], "close", r["ib_next_close"])):
                web_row = web.get(market, ticker, day)
                a = fnum(value)
                if web_row is None:
                    rep.add("ibkr_vs_web", "股票收市", ticker, day, field, "ibkr", a, "web_yahoo", None, SKIP,
                            "網站沒有這一天" if web.has_ticker(market, ticker, day[:4]) else "網站沒有這個代號")
                    continue
                prev, nxt = web.neighbour(market, ticker, day, -1), web.neighbour(market, ticker, day, 1)
                rep.add("ibkr_vs_web", "股票收市", ticker, day, field, "ibkr", a, "web_yahoo", col(web_row, field),
                        neighbours={f"前一交易日 {prev[0]}": col(prev[1], field),
                                    f"後一交易日 {nxt[0]}": col(nxt[1], field)})


def web_vs_web(web, rep, rng):
    files = [f for f in git_ls(WEB_REF, "data/equities/us/_second/") if f.startswith("quotes_")]
    if not files:
        rep.add("web_vs_web", "Yahoo↔Nasdaq", "", "", "close", "web_yahoo", None, "web_nasdaq", None, SKIP,
                "找不到第二來源快照")
        return
    for name in sorted(files)[-5:]:                  # 最近 5 份快照，每份抽 SAMPLE_WEB 檔
        snap = json.loads(git_show(WEB_REF, f"data/equities/us/_second/{name}") or "{}")
        day = snap.get("trade_date") or name[7:17]
        quotes = snap.get("quotes") or {}
        for ticker in sorted(rng.sample(sorted(quotes), min(SAMPLE_WEB, len(quotes)))):
            web_row = web.get("us", ticker, day)
            a = fnum(quotes[ticker].get("close"))
            if web_row is None:
                rep.add("web_vs_web", "Nasdaq↔Yahoo", ticker, day, "close", "web_nasdaq", a, "web_yahoo", None,
                        SKIP, "Yahoo 沒有這一天" if web.has_ticker("us", ticker, day[:4]) else "Yahoo 沒有這個代號")
                continue
            prev, nxt = web.neighbour("us", ticker, day, -1), web.neighbour("us", ticker, day, 1)
            rep.add("web_vs_web", "Nasdaq↔Yahoo", ticker, day, "close", "web_nasdaq", a, "web_yahoo",
                    col(web_row, "close"), note=f"快照 {name}",
                    neighbours={f"前一交易日 {prev[0]}": col(prev[1], "close"),
                                f"後一交易日 {nxt[0]}": col(nxt[1], "close")})


def internal_checks(rep):
    # Futu 5 分 K：OHLC 關係
    for path in sorted((EXT / "futu").glob("*/K_5M/*/*.csv.gz")):
        code, day, bad = path.parts[-4], path.name[:10], 0
        for b in read_gz(path):
            o, h, l, c = (fnum(b[k]) for k in ("open", "high", "low", "close"))
            if None in (o, h, l, c) or l > min(o, c) + 1e-9 or h < max(o, c) - 1e-9:
                bad += 1
        rep.add("internal", "5分K OHLC", code, day, "ohlc", "futu_5m", None, "", None, FAIL if bad else OK,
                f"{bad} 根高低不合" if bad else "全部合理")
    # MT5 M1：OHLC 關係、呆值（四價相同）
    for path in sorted((EXT / "mt5").glob("*/M1/*/*.csv.gz")):
        inst, day = path.parts[-4], path.name[:10]
        rows = read_gz(path)
        bad = sum(1 for b in rows if fnum(b["low"]) > min(fnum(b["open"]), fnum(b["close"])) + 1e-9
                  or fnum(b["high"]) < max(fnum(b["open"]), fnum(b["close"])) - 1e-9)
        flat = sum(1 for b in rows if b["open"] == b["high"] == b["low"] == b["close"])
        rep.add("internal", "MT5 M1 OHLC", inst, day, "ohlc", "mt5", None, "", None, FAIL if bad else OK,
                f"{len(rows)} 根，高低不合 {bad}，四價相同 {flat}")
    # 期權：金絲雀手冊 §10 的清洗規則，只記錄通過率（不設閘門）
    for path in sorted((EXT / "futu").glob("*/options/*/*.csv.gz")):
        code, day = path.parts[-4], path.name[:10]
        rows = read_gz(path)
        checks = {"bid>0": 0, "價差≤20%中價": 0, "|delta| 0.10–0.90": 0}
        for r in rows:
            bid, ask, delta = fnum(r["bid"]), fnum(r["ask"]), fnum(r["delta"])
            checks["bid>0"] += bool(bid and bid > 0)
            if bid and ask and bid > 0:
                checks["價差≤20%中價"] += (ask - bid) <= 0.2 * (ask + bid) / 2
            checks["|delta| 0.10–0.90"] += bool(delta is not None and 0.10 <= abs(delta) <= 0.90)
        note = "；".join(f"{k} {v}/{len(rows)}" for k, v in checks.items())
        rep.add("internal", "期權清洗規則（手冊 §10）", code, day, "rules", "futu_options", None, "", None, INFO, note)


# ---------------------------------------------------------------- third-source votes
def canonical(instrument):
    if "." in instrument and instrument.split(".", 1)[0] in ("US", "HK"):
        market, ticker = futu_to_web(instrument)
        return f"{market}/{ticker}"
    return instrument if "/" in instrument else ("hk/" if instrument.endswith(".HK") or instrument == "_HSI"
                                                  else "us/") + instrument


def add_votes(rows):
    """同一代號、同一天、同一欄，若還有第三個來源的值，寫進 ❌ 的說明，讓人判斷誰錯。"""
    votes = {}
    for r in rows:
        if "日期錯位" in r["note"]:                     # 已知錯位的那一列，數值不能拿來投票
            continue
        key = (canonical(r["instrument"]), r["date"], r["field"])
        for src, val in ((r["a_src"], r["a"]), (r["b_src"], r["b"])):
            if src and val != "":
                votes.setdefault(key, {})[src.split("_")[0] if src.startswith("futu") else src] = val
    for r in rows:
        if r["verdict"] != FAIL:
            continue
        mine = {r["a_src"].split("_")[0] if r["a_src"].startswith("futu") else r["a_src"], r["b_src"]}
        others = {k: v for k, v in votes.get((canonical(r["instrument"]), r["date"], r["field"]), {}).items()
                  if k not in mine}
        if others:
            r["note"] = (r["note"] + "；" if r["note"] else "") + "第三來源：" + "、".join(
                f"{k} {v}" for k, v in sorted(others.items()))


def cause_of(note):
    for tag in ("日期錯位", "日期缺漏"):
        if tag in note:
            return tag
    return "數值不同"


# ---------------------------------------------------------------- outputs
def gates(rows):
    out = {}
    for fam in ("futu_vs_web", "ibkr_vs_web", "web_vs_web", "canary_inputs", "internal"):
        fr = [r for r in rows if r["family"] == fam]
        count = {v: sum(1 for r in fr if r["verdict"] == v) for v in (OK, INFO, SKIP, KNOWN, FAIL)}
        status = "FAIL" if count[FAIL] else ("PASS" if count[OK] else "NO_DATA")
        out[fam] = {"status": status, "match": count[OK], "info": count[INFO], "skip": count[SKIP],
                    "known": count[KNOWN], "fail": count[FAIL]}
    return out


def write_sample(rng, run_day, rows):
    us = [t for t in git_ls(WEB_REF, "data/equities/us/") if not t.startswith("_")]
    hk = [t for t in git_ls(WEB_REF, "data/equities/hk/") if t.endswith(".HK")]
    # 今天「數值不同」的爭議代號優先：明天讓 Futu 當第三來源投票（最多 20 個）
    disputes = []
    for r in rows:
        if r["verdict"] == FAIL and cause_of(r["note"]) == "數值不同":
            market, _, ticker = canonical(r["instrument"]).partition("/")
            code = "HK.800000" if ticker == "_HSI" else web_to_futu(market, ticker)
            if code and code not in disputes:
                disputes.append(code)
    picks = rng.sample(us, min(SAMPLE_FUTU_US, len(us))) + rng.sample(hk, min(SAMPLE_FUTU_HK, len(hk)))
    codes = list(dict.fromkeys(FUTU_ANCHORS + disputes[:20] + [c for c in (web_to_futu("us" if t in us else "hk", t)
                                                                            for t in picks) if c]))
    (QC / "futu_sample.txt").write_text(
        f"# Futu 日線抽樣清單（{run_day} UTC 產生，external_qc.py；種子 = 產生日）\n"
        "# 本地 push_to_gcp.py 每天 16:30–21:00（香港時間）讀這份清單抓日線\n" + "\n".join(codes) + "\n",
        encoding="utf-8")
    return codes


def write_outputs(rows, gate, run_day, sample_codes):
    QC.mkdir(parents=True, exist_ok=True)
    with (QC / "results_latest.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    hist = QC / "history.csv"
    new = not hist.exists()
    with hist.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        if new:
            writer.writerow(["run_date", "family", "status", "match", "info", "skip", "known", "fail"])
        for fam, g in gate.items():
            writer.writerow([run_day, fam, g["status"], g["match"], g["info"], g["skip"], g["known"], g["fail"]])
    (QC / "GATE.json").write_text(json.dumps({"run_date": run_day, "families": gate}, ensure_ascii=False,
                                             indent=2) + "\n", encoding="utf-8")
    icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "NO_DATA": "⏭️ NO_DATA"}
    lines = [f"# 數據品質比對報告（{run_day} UTC）", "",
             "每類數據各一個閘門。**只取 PASS 的類別**；FAIL 先看下面「未解釋的差異」。規則見 `data/external/README.md` 第六節。", "",
             "| 類別 | 閘門 | ✅ 一致 | ℹ️ 記錄 | ⏭️ 略過 | ⚠️ 已知 | ❌ 未解釋 |", "|---|---|---:|---:|---:|---:|---:|"]
    lines += [f"| `{fam}` | {icon[g['status']]} | {g['match']} | {g['info']} | {g['skip']} | {g['known']} | {g['fail']} |"
              for fam, g in gate.items()]
    fails = [r for r in rows if r["verdict"] == FAIL]
    lines += ["", "## 未解釋的差異（按原因歸類，每類最多列 8 筆，全部見 results_latest.csv）", ""]
    if fails:
        groups = {}
        for r in fails:
            groups.setdefault((r["family"], r["check"], cause_of(r["note"])), []).append(r)
        for (fam, check, cause), items in sorted(groups.items()):
            lines += [f"### {fam}｜{check}｜{cause}：{len(items)} 筆", "",
                      "| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % | 說明 |", "|---|---|---|---|---|---:|---|"]
            lines += [f"| {r['instrument']} | {r['date']} | {r['field']} | {r['a_src']} {r['a']} | "
                      f"{r['b_src']} {r['b']} | {r['diff_pct']} | {r['note']} |" for r in items[:8]]
            lines += [""]
        lines += ["查明原因後，把 `代號,日期,欄位,原因,登記人` 加進 `known_issues.csv`（代號或日期可填 `*`），"
                  "下次就會列為 ⚠️ 已知。查不出原因的不要登記，數據先不要用。"]
    else:
        lines += ["無。"]
    info = [r for r in rows if r["verdict"] == INFO and r["field"] in ("open", "volume")
            and r["diff"] not in ("", 0, 0.0)][:20]
    if info:
        lines += ["", "## 口徑不同、只記錄的欄位", "", "| 代號 | 日期 | 欄位 | 甲 | 乙 | 差 % |", "|---|---|---|---|---|---:|"]
        lines += [f"| {r['instrument']} | {r['date']} | {r['field']} | {r['a']} | {r['b']} | {r['diff_pct']} |"
                  for r in info]
    rules = [r for r in rows if r["check"].startswith("期權清洗規則") or r["check"].startswith("MT5")]
    if rules:
        lines += ["", "## 封存內部檢查", ""] + [f"- `{r['instrument']}` {r['date']}：{r['check']}，{r['note']}"
                                          for r in rules[-20:]]
    lines += ["", "## 抽樣", "",
              f"- 種子 = {run_day}；IBKR 每市場 {SAMPLE_IBKR} 檔、Yahoo↔Nasdaq {SAMPLE_WEB} 檔。明細：`results_latest.csv`。",
              f"- 明天給 Futu 抓日線的清單（`futu_sample.txt`）：{len(sample_codes)} 個代號，含錨點 {', '.join(FUTU_ANCHORS)}。", ""]
    (QC / "QC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = parser.parse_args()
    QC.mkdir(parents=True, exist_ok=True)
    rep = Report(load_known())
    web = WebDaily(WEB_REF)
    canary_text = git_show(CANARY_REF, "canary/data_external/hsi_daily.csv")
    canary_hsi = {r["Date"]: {k.lower(): v for k, v in r.items()} for r in csv.DictReader(io.StringIO(canary_text))} \
        if canary_text else {}
    futu_intraday_daily(web, rep)
    futu_kday(web, canary_hsi, rep, args.run_date)
    canary_vs_web(web, rep)
    ibkr_vs_web(web, rep, random.Random(args.run_date + "ibkr"))
    web_vs_web(web, rep, random.Random(args.run_date + "web"))
    internal_checks(rep)
    add_votes(rep.rows)
    gate = gates(rep.rows)
    sample = write_sample(random.Random(args.run_date + "futu"), args.run_date, rep.rows)
    write_outputs(rep.rows, gate, args.run_date, sample)
    print((QC / "QC_REPORT.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
