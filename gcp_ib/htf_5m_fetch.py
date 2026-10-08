#!/usr/bin/env python3
"""HTF 盤中研究：抓 entry_date 當天的 5 分 K（RTH、TRADES）。跑在使用者的 GCP VM（IB Gateway 同機），不在沙盒。
需求規格：stock_research/HTF_INTRADAY_REQUEST.md（分支 claude/htf-qullamaggie-research）。只讀行情，不下單。

用法（VM）：
  python3 gcp_ib/htf_5m_fetch.py --req ~/htf_request.csv --probe              # 先 probe：港美台各取新/中/舊 3 檔
  python3 gcp_ib/htf_5m_fetch.py --req ~/htf_request.csv --market hk us tw    # 正式跑（順序 港→美→台，各市場新→舊）

輸入 CSV 欄位：market,ticker,signal_date,entry_date
輸出 data_stock_ibkr/htf_5m/<market>_<ticker>_<entry_date>.csv（time,open,high,low,close,volume；time = 交易所當地時間）
      data_stock_ibkr/htf_5m/_status.txt（每列 ok／失敗原因；追加）
可續抓：已有 csv 的跳過。節流 --pace 秒（預設 2.5）；pacing violation 自動等 60 秒重試。
地平線剪枝：新→舊跑，若同市場連續 --prune-after 次「無數據」且都比最舊成功日更舊，
  判定 IB 這個年限以前沒有 5 分 K，其餘更舊的列標 beyond_horizon 跳過（--no-prune 關閉）。
定時推送：--push-every N 檔 commit+push 一次輸出（失敗不影響抓取）。
"""
import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ib_insync import IB, Stock

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_stock_ibkr" / "htf_5m"
TZ = {"hk": "Asia/Hong_Kong", "us": "America/New_York", "tw": "Asia/Taipei"}
ORDER = ["hk", "us", "tw"]


def to_ib(mk, t):
    """Yahoo 代號 → (symbol, exchange, currency)；同 scripts/ib_stock_verify.py 的 to_ib()。"""
    if mk == "hk":
        return t[:-3].lstrip("0") or "0", "SEHK", "HKD"
    if mk == "us":
        return t.replace("-", " "), "SMART", "USD"
    if mk == "tw":
        return t.rsplit(".", 1)[0], "TWSE", "TWD"
    raise ValueError(mk)


def log(msg):
    line = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "_status.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Fetcher:
    def __init__(self, port, client_id, pace):
        self.port, self.client_id, self.pace = port, client_id, pace
        self.ib = IB()
        self.errors = []          # (code, msg) 最近一次請求期間收到的錯誤
        self.contracts = {}       # (mk, ticker) -> Contract | str(失敗原因)
        self.connect()

    def connect(self):
        for k in range(6):
            try:
                if self.ib.isConnected():
                    self.ib.disconnect()
                self.ib.connect("127.0.0.1", self.port, clientId=self.client_id, readonly=True, timeout=30)
                self.ib.errorEvent += self.on_error
                return
            except Exception as e:
                log(f"connect 失敗（{k + 1}/6）：{e}")
                time.sleep(60)
        sys.exit("連不上 IB Gateway（確認 Gateway 已登入、port 對）")

    def on_error(self, reqId, code, msg, contract=None):
        self.errors.append((code, msg))

    def contract(self, mk, ticker):
        key = (mk, ticker)
        if key in self.contracts:
            return self.contracts[key]
        sym, exch, cur = to_ib(mk, ticker)
        # 台股上櫃（.TWO）：probe 證實 TWSE 找不到，改試 TPEX（櫃買）；都不行就記 no_contract
        cands = [(exch, cur)] if not ticker.endswith(".TWO") else [("TPEX", cur), ("TWSE", cur)]
        c = None
        for ex, cu in cands:
            self.errors.clear()
            try:
                res = self.ib.qualifyContracts(Stock(sym, ex, cu))
                if res:
                    c = res[0]
                    break
                c = f"no_contract: {self.last_error()}"
            except Exception as e:
                c = f"qualify_error: {e}"
        self.contracts[key] = c
        time.sleep(0.3)
        return c

    def last_error(self):
        return "; ".join(f"{c}:{m}" for c, m in self.errors[-2:]) or "unknown"

    def bars(self, mk, contract, entry_date):
        """回傳 (status, rows)。status = ok / no_data / wrong_day / 其他錯誤字串。"""
        end = entry_date.replace("-", "") + "-23:59:59"        # UTC：HK/US/TW 的 RTH 都落在同一 UTC 日
        for attempt in range(4):
            if not self.ib.isConnected():
                self.connect()
            self.errors.clear()
            try:
                bars = self.ib.reqHistoricalData(contract, endDateTime=end, durationStr="1 D",
                                                 barSizeSetting="5 mins", whatToShow="TRADES",
                                                 useRTH=True, formatDate=2)
            except Exception as e:
                bars, err = [], f"exception: {e}"
                self.errors.append((0, err))
            time.sleep(self.pace)
            text = self.last_error()
            if any(c == 162 and "pacing" in m.lower() for c, m in self.errors):
                log(f"  pacing violation，等 60 秒重試（{attempt + 1}/4）")
                time.sleep(60)
                continue
            if not bars:
                if any(c in (162, 165, 366) for c, m in self.errors) or not self.errors:
                    return "no_data: " + text, []
                return "error: " + text, []
            tz = ZoneInfo(TZ[mk])
            rows = []
            for b in bars:
                t = b.date.astimezone(tz) if getattr(b.date, "tzinfo", None) else b.date
                rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), b.open, b.high, b.low, b.close, b.volume))
            days = {r[0][:10] for r in rows}
            if entry_date not in days:
                return f"wrong_day: got {sorted(days)}", []
            rows = [r for r in rows if r[0][:10] == entry_date]
            return "ok", rows
        return "error: pacing retries exhausted", []


def read_req(path, markets):
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    out = {m: [] for m in ORDER}
    seen = set()
    for r in rows:
        k = (r["market"], r["ticker"], r["entry_date"])
        if r["market"] in out and r["market"] in markets and k not in seen:
            seen.add(k)
            out[r["market"]].append(r)
    for m in out:
        out[m].sort(key=lambda r: r["entry_date"], reverse=True)       # 新 → 舊
    return out


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)


def push(tag):
    try:
        cmds = [["git", "add", "data_stock_ibkr/htf_5m"],
                ["git", "commit", "-q", "-m", f"data: HTF 5 分 K（IBKR，{tag}）"],
                ["git", "pull", "--rebase", "-q", "origin", "claude/dazzling-curie-f3xzb8"],
                ["git", "push", "-q", "origin", "HEAD:claude/dazzling-curie-f3xzb8"]]
        for c in cmds:
            r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
            if r.returncode and c[1] != "commit":
                log(f"  push 步驟失敗 {' '.join(c[:2])}：{r.stderr.strip()[:200]}")
                return
        log(f"  已 push（{tag}）")
    except Exception as e:
        log(f"  push 例外：{e}")


def probe(f, req):
    lines = []
    for mk in ORDER:
        rows = req[mk]
        if not rows:
            continue
        picks = [rows[0], rows[len(rows) // 3], rows[-1]]            # 新 / 中 / 舊
        for r in picks:
            c = f.contract(mk, r["ticker"])
            if isinstance(c, str):
                line = f"{mk} {r['ticker']} {r['entry_date']}: {c}"
            else:
                st, bars = f.bars(mk, c, r["entry_date"])
                span = f"{bars[0][0][11:16]}–{bars[-1][0][11:16]} {len(bars)} 根" if bars else ""
                line = f"{mk} {r['ticker']} {r['entry_date']}: conId={c.conId} {st} {span}"
            log("PROBE " + line)
            lines.append(line)
    print("\n=== probe 結果（請整段貼給 Claude）===\n" + "\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--req", required=True)
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=31)
    ap.add_argument("--pace", type=float, default=2.5)
    ap.add_argument("--market", nargs="+", default=ORDER)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--no-prune", action="store_true")
    ap.add_argument("--prune-after", type=int, default=40)
    ap.add_argument("--push-every", type=int, default=400)
    ap.add_argument("--no-push", action="store_true", help="完全不做 git commit/push（測試／乾跑用）")
    ap.add_argument("--limit", type=int, default=0, help="每市場最多處理幾列（測試用）")
    a = ap.parse_args()

    req = read_req(a.req, a.market)
    f = Fetcher(a.port, a.client_id, a.pace)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.probe:
        probe(f, req)
        return

    done = 0
    for mk in ORDER:
        rows = req.get(mk, [])
        if a.limit:
            rows = rows[:a.limit]
        log(f"== {mk}：{len(rows)} 列（新→舊）==")
        oldest_ok = None
        nodata_run = 0
        init_fail = 0
        horizon = None
        for i, r in enumerate(rows):
            t, d = r["ticker"], r["entry_date"]
            path = OUT / f"{mk}_{t}_{d}.csv"
            if path.exists():
                oldest_ok = d if oldest_ok is None or d < oldest_ok else oldest_ok
                continue
            if horizon and d < horizon:
                log(f"{mk} {t} {d}: beyond_horizon（早於 {horizon}）")
                continue
            c = f.contract(mk, t)
            if isinstance(c, str):
                log(f"{mk} {t} {d}: {c}")
                if oldest_ok is None:
                    init_fail += 1
                    if init_fail >= a.prune_after:
                        log(f"** {mk}：最新的 {init_fail} 列全失敗（沒有任何成功）→ 判定此市場不可用（權限／無合約），跳過整個市場")
                        break
                continue
            st, bars = f.bars(mk, c, d)
            if st == "ok":
                write_csv(path, bars)
                oldest_ok = d if oldest_ok is None or d < oldest_ok else oldest_ok
                nodata_run = 0
                done += 1
                log(f"{mk} {t} {d}: ok {len(bars)} 根  [{i + 1}/{len(rows)}]")
                if not a.no_push and a.push_every and done % a.push_every == 0:
                    push(f"{mk} 累計 {done} 檔")
            else:
                log(f"{mk} {t} {d}: {st}")
                if oldest_ok is None:
                    init_fail += 1
                    if init_fail >= a.prune_after:
                        log(f"** {mk}：最新的 {init_fail} 列全失敗（沒有任何成功）→ 判定此市場不可用（權限／無合約），跳過整個市場")
                        break
                if st.startswith("no_data") and oldest_ok and d < oldest_ok:
                    nodata_run += 1
                    if not a.no_prune and nodata_run >= a.prune_after:
                        horizon = oldest_ok
                        log(f"** {mk}：連續 {nodata_run} 次無數據且都早於最舊成功日 {oldest_ok} → 地平線 = {horizon}，更舊的列跳過")
                elif st == "ok":
                    nodata_run = 0
        if not a.no_push and done:
            push(f"{mk} 完成")
    log("全部完成")


if __name__ == "__main__":
    main()
