"""NAS100 差價合約 15 分 K（MT5 匯出，gifted-carson 分支 data/NAS100_M15.csv.gz，2022-08-05 → 2026-09-18）→ CME 全段交易日。

券商時間 = 紐約時間 + 7 小時（冬令 UTC+2、夏令 UTC+3，跟美國夏令時間一起切換）。
每個券商日的 K 線由 01:00 到 23:45（開市時間），即紐約 18:00（前一天）到 16:45，最後一根收市 17:00——正是 CME 一段 23 小時的交易日。
用戶決定「一天 = 整段 23 小時」，所以交易日 = 券商日期（= 收市那天的紐約日期），不用再切。
輸出 time_key 用紐約時間、K 線收市時間（+15 分鐘），與 Futu／HK50 的「收市時間」慣例一致。
用法（模組）：bars, daily = nas100_cfd.load()；daily 的每列 = 一個交易日的 OHLC（time_key = 'YYYY-MM-DD 00:00:00'）。
"""
import csv, gzip, io, subprocess
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BRANCH = "origin/claude/gifted-carson-v2tvhw"
FILE = "data/NAS100_M15.csv.gz"
MIN_BARS = 20                      # 一個交易日少於 20 根 15 分 K（假期零星）就剔除；正常 92 根


def broker_to_ny(s):
    dt = datetime.strptime(s, "%Y.%m.%d %H:%M:%S") - timedelta(hours=7) + timedelta(minutes=15)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def session_of_broker(s):
    return s[:10].replace(".", "-")


def load(path=None):
    raw = Path(path).read_bytes() if path else subprocess.run(["git", "-C", str(REPO), "show", f"{BRANCH}:{FILE}"],
                                                             capture_output=True, check=True).stdout
    rows = list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode())))
    by = {}
    for r in rows:
        d = session_of_broker(r["Time"])
        by.setdefault(d, []).append({"time_key": broker_to_ny(r["Time"]), "open": float(r["Open"]), "high": float(r["High"]),
                                     "low": float(r["Low"]), "close": float(r["Close"]), "volume": float(r["Volume"]) or 1.0, "session": d})
    bars, daily = [], []
    for d in sorted(by):
        seq = sorted(by[d], key=lambda b: b["time_key"])
        if len(seq) < MIN_BARS:
            continue
        bars += seq
        daily.append({"time_key": f"{d} 00:00:00", "open": seq[0]["open"], "high": max(b["high"] for b in seq),
                      "low": min(b["low"] for b in seq), "close": seq[-1]["close"], "volume": sum(b["volume"] for b in seq),
                      "source": "mt5_cfd:NAS100", "bars": len(seq)})
    return bars, daily


if __name__ == "__main__":
    b, d = load()
    print(len(b), "bars", len(d), "days", d[0]["time_key"], "→", d[-1]["time_key"], "bars/day median", sorted(x["bars"] for x in d)[len(d) // 2])
