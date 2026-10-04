"""蛇蟠陣分支（claude/gifted-carson-v2tvhw）的 HK50 差價合約 15 分 K → 風揚陣同格式（香港時間、交易日 K）。

來源：data/HK50_M15.csv.gz（MT5 匯出，券商時間；2022-08-05 → 2026-09-18）。
券商時間 = 紐約時間 + 7 小時（冬令 UTC+2、夏令 UTC+3，跟美國夏令時間切換），已用 2024 年 3 月、11 月的開市時間核對：
冬令首根 03:15、夏令首根 04:15，換成香港時間都是 09:15；最後一根 21:45 → 香港翌日 02:45（03:00 收市）。
MT5 的時間是**開市時間**，Futu 15 分 K 是**收市時間**，這裡統一轉成收市時間（+15 分鐘），與 Futu 相同。
交易日 K：香港 09:00 至翌日 09:00（日市＋當晚夜市），與 futu/push_to_gcp.py 的 K_SESSION 相同。
少於 MIN_BARS 根 K 線的交易日（假期的零星 K 線）剔除；平安夜、除夕等半日市（11 根）保留。

用法（模組）：bars, daily = hk50_cfd.load()；或 python3 hk50_cfd.py --out 快取.json
"""
import argparse, csv, gzip, io, json, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
BRANCH = "origin/claude/gifted-carson-v2tvhw"
NY, HK = ZoneInfo("America/New_York"), ZoneInfo("Asia/Hong_Kong")
MIN_BARS = 4                    # 一個交易日少於 4 根 15 分 K 就剔除（半日市有 11 根，保留）


def broker_to_hk(s):
    """'2024.03.04 03:15:00'（券商時間、K 線開市時間）→ 香港時間的收市時間字串。"""
    dt = datetime.strptime(s, "%Y.%m.%d %H:%M:%S") - timedelta(hours=7)
    hk = dt.replace(tzinfo=NY).astimezone(HK).replace(tzinfo=None) + timedelta(minutes=15)
    return hk.strftime("%Y-%m-%d %H:%M:%S")


def session_of(time_key):
    d = datetime.strptime(time_key, "%Y-%m-%d %H:%M:%S")
    return (d - timedelta(hours=9)).strftime("%Y-%m-%d")


def load(path=None):
    if path:
        raw = Path(path).read_bytes()
    else:
        raw = subprocess.run(["git", "-C", str(REPO), "show", f"{BRANCH}:data/HK50_M15.csv.gz"],
                             capture_output=True, check=True).stdout
    rows = csv.DictReader(io.StringIO(gzip.decompress(raw).decode()))
    bars = {}
    for r in rows:
        t = broker_to_hk(r["Time"])
        bars[t] = {"time_key": t, "open": float(r["Open"]), "high": float(r["High"]), "low": float(r["Low"]),
                   "close": float(r["Close"]), "volume": float(r["Volume"]) or 1.0}
    bars = [bars[k] for k in sorted(bars)]
    n = {}
    for b in bars:
        n[session_of(b["time_key"])] = n.get(session_of(b["time_key"]), 0) + 1
    bars = [b for b in bars if n[session_of(b["time_key"])] >= MIN_BARS]       # 剔除假期的零星 K 線（例 2022-10-04 只有 1 根）
    sess = {}
    for b in bars:
        s = sess.setdefault(session_of(b["time_key"]), {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]})
        s["high"], s["low"], s["close"] = max(s["high"], b["high"]), min(s["low"], b["low"]), b["close"]
    daily = [{"time_key": f"{d} 00:00:00", **v} for d, v in sorted(sess.items())]
    return bars, daily


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    bars, daily = load()
    json.dump({"bars": bars, "daily": daily}, open(a.out, "w"))
    print(f"HK50：{len(bars)} 根 15 分 K（{bars[0]['time_key']} → {bars[-1]['time_key']}），{len(daily)} 個交易日")
