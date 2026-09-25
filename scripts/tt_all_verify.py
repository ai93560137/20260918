#!/usr/bin/env python3
"""月底名單第二來源覆核（在 GitHub Actions 跑；沙盒連不到交易所與 Yahoo）。

    python3 scripts/tt_all_verify.py --market hk sg            # 用 analysis/tt_all/<市場>_latest.json 的日期
    python3 scripts/tt_all_verify.py --request                 # 讀 analysis/tt_all/verify_request.txt（每行 "市場 日期"）
    python3 scripts/tt_all_verify.py --selftest

對名單上每一檔，拿「訊號日收市」跟第二來源比：
- 港：港交所日報表（官方）；美：Nasdaq 歷史 API（同日收市）；台：證交所每日收盤行情（上市 .TW；上櫃 .TWO 無）；
  日：Yahoo!ファイナンス 日線（同日終値；不按拆股還原，整數倍不算錯）
- 韓澳加印新（及上面取不到的）：Yahoo 即時重抓（同一來源，只驗證 Release 快照沒過期、沒縫接、股票還在交易）
狀態：一致（差 ≤ 1%）／不一致（> 1%）／整數倍（拆股未還原，只在日股）／無數據（第二來源沒有：可能停牌、下市、代號改了）
輸出：<市場>_<日期>_verify.csv、<市場>_verify.json、tg_verify.txt（Telegram 一則）
"""
import argparse
import csv
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "analysis" / "tt_all"
NAME = {"hk": "港股", "jp": "日股", "us": "美股", "tw": "台灣", "kr": "韓國", "au": "澳洲", "ca": "加拿大", "in": "印度", "sg": "新加坡"}
TOL = 0.01
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def read_list(mk: str, d: str) -> list[dict]:
    with open(OUT / f"{mk}_{d}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- 第二來源 ----------
def src_hkex(tickers: list[str], d: str) -> tuple[dict[str, float], str]:
    import fetch_hkex_equity as fh
    r = requests.get(fh.URL.format(d=date.fromisoformat(d)), headers=UA, timeout=60)
    r.raise_for_status()
    q = fh.parse_quotations(r.content.decode("utf-8", errors="replace"))
    return {t: q[t]["close"] for t in tickers if t in q and q[t].get("close")}, "港交所日報表"


def src_nasdaq(tickers: list[str], d: str) -> tuple[dict[str, float], str]:
    import fetch_second_source as fs
    s = requests.Session()
    out = {}
    for t in tickers:
        try:
            r = s.get(f"https://api.nasdaq.com/api/quote/{t.replace('-', '.')}/historical", headers=fs.UA, timeout=30,
                      params={"assetclass": "stocks", "limit": "20", "fromdate": (date.fromisoformat(d) - timedelta(days=14)).isoformat(), "todate": d})
            rows = (((r.json().get("data") or {}).get("tradesTable") or {}).get("rows")) or []
        except Exception:
            rows = []
        for x in rows:
            mo, dd, y = x["date"].split("/")
            if f"{y}-{int(mo):02d}-{int(dd):02d}" == d and fs.money(x.get("close", "")):
                out[t] = fs.money(x["close"])
        time.sleep(0.3)
    return out, "Nasdaq 歷史 API"


def src_twse(tickers: list[str], d: str) -> tuple[dict[str, float], str]:
    r = requests.get("https://www.twse.com.tw/exchangeReport/MI_INDEX", headers=UA,
                     params={"response": "json", "date": d.replace("-", ""), "type": "ALLBUT0999"}, timeout=60)
    r.raise_for_status()
    j = r.json()
    tables = list(j.get("tables") or [])
    for i in range(1, 12):
        if j.get(f"fields{i}"):
            tables.append({"fields": j[f"fields{i}"], "data": j.get(f"data{i}", [])})
    q = {}
    for tb in tables:
        f = [str(x) for x in tb.get("fields") or []]
        if "證券代號" in f and "收盤價" in f:
            ic, ip = f.index("證券代號"), f.index("收盤價")
            for row in tb.get("data") or []:
                try:
                    q[f"{str(row[ic]).strip()}.TW"] = float(str(row[ip]).replace(",", ""))
                except ValueError:
                    pass
    return {t: q[t] for t in tickers if t in q and q[t] > 0}, "證交所每日收盤行情（上市）"


def src_yj(tickers: list[str], d: str) -> tuple[dict[str, float], str]:
    import verify_trades as vt
    s = requests.Session()
    out = {}
    dd = date.fromisoformat(d)
    for t in tickers:
        try:
            h = vt.jp_window(s, t, dd - timedelta(days=7), dd)
            if dd in h and h[dd].get("close"):
                out[t] = h[dd]["close"]
        except Exception as exc:
            print(f"WARN {t}: {exc}", file=sys.stderr)
        time.sleep(0.5)
    return out, "Yahoo!ファイナンス 日線"


def src_yahoo(tickers: list[str], d: str) -> tuple[dict[str, float], str]:
    """Yahoo 即時重抓（同來源）：驗 Release 快照是否過期／縫接、股票是否還在交易。"""
    s = requests.Session()
    out = {}
    for t in tickers:
        try:
            r = s.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}", headers=UA, timeout=30,
                      params={"range": "1mo", "interval": "1d", "events": "split"})
            res = r.json()["chart"]["result"][0]
            ts = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
            for k, c in zip(ts, closes):
                if c and date.fromtimestamp(k).isoformat() == d:   # UTC 日期；亞洲市場收市時間對日期無影響
                    out[t] = float(c)
            if t not in out:      # 時區邊界：容許前後一天
                for k, c in zip(ts, closes):
                    if c and abs((date.fromtimestamp(k) - date.fromisoformat(d)).days) <= 1 and t not in out:
                        out[t] = float(c)
        except Exception as exc:
            print(f"WARN {t}: {exc}", file=sys.stderr)
        time.sleep(0.2)
    return out, "Yahoo 即時重抓（同來源）"


SOURCES = {"hk": src_hkex, "us": src_nasdaq, "tw": src_twse, "jp": src_yj}


def classify(ours: float, theirs: float | None, mk: str) -> tuple[str, float | None]:
    if theirs is None or theirs <= 0:
        return "無數據", None
    diff = ours / theirs - 1
    if abs(diff) <= TOL:
        return "一致", diff
    ratio = ours / theirs
    for k in (2, 3, 4, 5, 10, 0.5, 1 / 3, 0.25, 0.2, 0.1):
        if abs(ratio / k - 1) <= TOL:
            return "整數倍", diff
    return "不一致", diff


def verify(mk: str, d: str) -> dict:
    rows = read_list(mk, d)
    tickers = [r["ticker"] for r in rows]
    ours = {r["ticker"]: float(r["close"]) for r in rows}
    q, src = {}, ""
    if mk in SOURCES:
        try:
            q, src = SOURCES[mk](tickers, d)
        except Exception as exc:
            print(f"[{mk}] 官方第二來源失敗：{exc}，改用 Yahoo 重抓", file=sys.stderr)
    missing = [t for t in tickers if t not in q]
    q2, src2 = ({}, "")
    if missing:
        try:
            q2, src2 = src_yahoo(missing, d)
        except Exception as exc:
            print(f"[{mk}] Yahoo 重抓失敗：{exc}", file=sys.stderr)
    out_rows, cnt = [], {"一致": 0, "不一致": 0, "整數倍": 0, "無數據": 0}
    for t in tickers:
        theirs, s = (q[t], src) if t in q else (q2.get(t), src2 if t in q2 else "")
        st, diff = classify(ours[t], theirs, mk)
        cnt[st] += 1
        out_rows.append({"ticker": t, "ours": ours[t], "theirs": theirs if theirs is not None else "", "source": s,
                         "diff_pct": f"{diff * 100:+.2f}" if diff is not None else "", "status": st})
    with open(OUT / f"{mk}_{d}_verify.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "ours", "theirs", "source", "diff_pct", "status"], lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    summ = {"market": mk, "date": d, "n": len(tickers), "official_source": src, "fallback_source": src2, **cnt,
            "bad": [r["ticker"] for r in out_rows if r["status"] in ("不一致", "無數據")]}
    (OUT / f"{mk}_verify.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[{mk}] {d} 覆核 {len(tickers)} 檔：一致 {cnt['一致']}、不一致 {cnt['不一致']}、整數倍 {cnt['整數倍']}、無數據 {cnt['無數據']}（{src or src2}）", file=sys.stderr)
    return summ


def write_tg(summaries: list[dict]) -> None:
    lines = ["🔎 鳥翔｜月底名單第二來源覆核", ""]
    for s in summaries:
        src = s["official_source"] or s["fallback_source"]
        flag = "✅" if not s["bad"] else "⚠️"
        lines.append(f"{flag} {NAME[s['market']]} {s['date']}：{s['一致']}/{s['n']} 一致（{src}）"
                     + (f"；整數倍 {s['整數倍']}" if s["整數倍"] else "")
                     + (f"；不一致 {s['不一致']}" if s["不一致"] else "")
                     + (f"；無數據 {s['無數據']}" if s["無數據"] else ""))
        if s["bad"]:
            lines.append("　要查：" + "、".join(s["bad"][:12]) + ("…" if len(s["bad"]) > 12 else ""))
    lines += ["", "一致 = 收市差 ≤ 1%。「無數據」可能是停牌、下市或代號改了——下單前先查。", "明細：analysis/tt_all/<市場>_<日期>_verify.csv；網頁名單有「覆核」欄。"]
    (OUT / "tg_verify.txt").write_text("\n".join(lines)[:3900] + "\n", encoding="utf-8")


def verify_ibkr(mk: str, d: str) -> dict | None:
    """把雲垂分支交回的 IBKR 收市（data_stock_ibkr/<mk>_<d>.csv）當第三把尺；同時把下一交易日開市存為執行基準。"""
    p = ROOT / "data_stock_ibkr" / f"{mk}_{d}.csv"
    if not p.exists():
        return None
    with open(p, newline="", encoding="utf-8") as f:
        ib = {r["ticker"]: r for r in csv.DictReader(f)}
    rows = read_list(mk, d)
    out, cnt = [], {"一致": 0, "不一致": 0, "整數倍": 0, "無數據": 0}
    for r in rows:
        x = ib.get(r["ticker"], {})
        theirs = float(x["ib_close"]) if x.get("status") == "ok" and x.get("ib_close") else None
        st, diff = classify(float(r["close"]), theirs, mk)
        cnt[st] += 1
        out.append({"ticker": r["ticker"], "ours": r["close"], "ibkr_close": x.get("ib_close", ""), "next_date": x.get("next_date", ""),
                    "ibkr_next_open": x.get("ib_next_open", ""), "diff_pct": f"{diff * 100:+.2f}" if diff is not None else "", "status": st,
                    "ib_status": x.get("status", "missing"), "note": x.get("note", "")})
    with open(OUT / f"{mk}_{d}_verify_ibkr.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()) if out else ["ticker"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    summ = {"market": mk, "date": d, "n": len(rows), "source": "IBKR 日線 TRADES", **cnt,
            "bad": [r["ticker"] for r in out if r["status"] in ("不一致", "無數據")]}
    (OUT / f"{mk}_verify_ibkr.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[{mk}] {d} IBKR 覆核 {len(rows)} 檔：一致 {cnt['一致']}、不一致 {cnt['不一致']}、整數倍 {cnt['整數倍']}、無數據 {cnt['無數據']}", file=sys.stderr)
    return summ


def selftest() -> None:
    assert classify(10.0, 10.05, "hk")[0] == "一致"
    assert classify(10.0, 10.5, "hk")[0] == "不一致"
    assert classify(30.0, 10.0, "jp")[0] == "整數倍"
    assert classify(10.0, None, "sg")[0] == "無數據"
    print("selftest ok")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", nargs="*", default=[])
    a.add_argument("--request", action="store_true")
    a.add_argument("--selftest", action="store_true")
    a.add_argument("--ibkr", action="store_true", help="用 data_stock_ibkr/ 的 IBKR 收市作第三把尺（雲垂分支交回後）")
    args = a.parse_args()
    if args.selftest:
        selftest()
        return
    if args.ibkr:
        summaries = []
        for p in sorted(OUT.glob("*_latest.json")):
            meta = json.loads(p.read_text(encoding="utf-8"))
            if args.market and meta["market"] not in args.market:
                continue
            s = verify_ibkr(meta["market"], meta["date"])
            if s:
                summaries.append(s)
        if summaries:
            lines = ["🔎 鳥翔｜IBKR 第三來源覆核", ""] + [
                f"{'✅' if not s['bad'] else '⚠️'} {NAME[s['market']]} {s['date']}：{s['一致']}/{s['n']} 一致；無數據 {s['無數據']}、不一致 {s['不一致']}"
                + (("；要查：" + "、".join(s["bad"][:10])) if s["bad"] else "") for s in summaries]
            (OUT / "tg_verify_ibkr.txt").write_text("\n".join(lines)[:3900] + "\n", encoding="utf-8")
        return
    jobs = []
    if args.request:
        p = OUT / "verify_request.txt"
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = ln.split()
            if len(parts) == 2:
                jobs.append((parts[0], parts[1]))
    for mk in args.market:
        meta = json.loads((OUT / f"{mk}_latest.json").read_text(encoding="utf-8"))
        jobs.append((mk, meta["date"]))
    summaries = []
    for mk, d in jobs:
        try:
            summaries.append(verify(mk, d))
        except Exception as exc:
            print(f"[{mk}] 覆核失敗：{exc}", file=sys.stderr)
    if summaries:
        write_tg(summaries)


if __name__ == "__main__":
    main()
