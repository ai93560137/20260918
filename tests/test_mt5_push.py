"""[R130] futu/mt5_push.py 的純函數：券商時差、券商時間 → 紐約收市時間、CME 交易日、休市與週末過濾、交易日 K 合成、CSV 離線模式。"""
import csv, os, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "/home/user/20260918/futu")
import mt5_push as m

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

UTC = timezone.utc
def ep(s):                                   # 'YYYY-MM-DD HH:MM' 當作 UTC 的秒數（MT5 的「券商時間當 UTC」）
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp())

print("\n=== 券商時差 ===")
now = ep("2026-10-06 14:00")
check("券商時間比 UTC 快 3 小時（夏令）", m.broker_offset_hours(ep("2026-10-06 17:00") + 20, now) == 3)
check("快 2 小時（冬令）", m.broker_offset_hours(ep("2026-10-06 16:00") - 40, now) == 2)
check("報價太舊（休市）→ None", m.broker_offset_hours(ep("2026-10-06 12:30"), now) is None)

print("\n=== 時間換算與交易日 ===")
# 券商 UTC+3：券商 2026-10-06 01:00 開市的 M5 = UTC 10-05 22:00 = 紐約 10-05 18:00 → 收市時間 18:05，屬 10-06 交易日
tk = m.to_ny_close(ep("2026-10-06 01:00"), 3)
check("券商 01:00（UTC+3）→ 紐約 18:05 收市", tk == "2026-10-05 18:05:00", tk)
check("18:05 屬下一個交易日", m.session_of(tk) == "2026-10-06")
tk2 = m.to_ny_close(ep("2026-10-06 23:55"), 3)
check("券商 23:55 → 紐約 17:00 收市，屬當天", tk2 == "2026-10-06 17:00:00" and m.session_of(tk2) == "2026-10-06", tk2)
check("17:00 那根留下、17:05–18:00 休市略過", m.in_session("2026-10-06 17:00:00") and not m.in_session("2026-10-06 17:05:00")
      and not m.in_session("2026-10-06 18:00:00") and m.in_session("2026-10-06 18:05:00"))
check("週六凌晨的 K（屬週六交易日）略過；週日 18:05 屬週一留下", not m.in_session("2026-10-10 01:00:00") and m.in_session("2026-10-11 18:05:00"))

print("\n=== 交易日 K 合成 ===")
rates = []
t = ep("2026-10-05 01:00")                                   # 券商 UTC+3：10-05 01:00 = 紐約 10-04 18:00（週日晚，屬 10-05）
px = 6700.0
while t < ep("2026-10-07 12:00"):
    rates.append({"time": t, "open": px, "high": px + 2, "low": px - 2, "close": px + 1, "tick_volume": 5})
    t += 300; px += 0.1
bars = m.rates_to_bars(rates, 3)
days = m.session_bars(bars, drop_head=False)
check("兩個完整交易日 + 一個進行中", [d["time_key"][:10] for d in days] == ["2026-10-05", "2026-10-06", "2026-10-07"], [d["time_key"] for d in days])
check("完整交易日 276 根（23 小時 × 12）、第一根 18:05、最後一根 17:00", days[0]["bars"] == 276 and days[0]["first"] == "2026-10-04 18:05:00" and days[0]["last"] == "2026-10-05 17:00:00",
      (days[0]["bars"], days[0]["first"], days[0]["last"]))
check("交易日 K 的高低收", days[0]["high"] == max(b["high"] for b in bars if m.session_of(b["time_key"]) == "2026-10-05")
      and days[0]["close"] == [b for b in bars if m.session_of(b["time_key"]) == "2026-10-05"][-1]["close"])
mid = m.session_bars(bars[100:])
check("由交易日中途開始 → 第一個不完整的交易日不要", [d["time_key"][:10] for d in mid] == ["2026-10-06", "2026-10-07"], [d["time_key"] for d in mid])
check("只有一個交易日時不丟", len(m.session_bars(bars[100:200])) == 1)

print("\n=== CSV 離線模式（--dry-run，不連 MT5、不連 GCP） ===")
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "m5.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["Time", "Open", "High", "Low", "Close", "Volume"])
        for r in rates:
            w.writerow([datetime.fromtimestamp(r["time"], UTC).strftime("%Y.%m.%d %H:%M:%S"), r["open"], r["high"], r["low"], r["close"], r["tick_volume"]])
    env = {**os.environ, "ZHUGE_GCP_URL": "", "WEBHOOK_SECRET_TOKEN": ""}
    out = subprocess.run([sys.executable, "/home/user/20260918/futu/mt5_push.py", "--csv", path, "--utc-offset", "3", "--dry-run"],
                         capture_output=True, text=True, env=env).stdout
    check("印出 K_5M 與 K_SESSION 的 dry-run 行", "K_5M US.ES_FRONT 120 根" in out and "K_SESSION US.ES_FRONT 3 根" in out, out[-400:])
    out2 = subprocess.run([sys.executable, "/home/user/20260918/futu/mt5_push.py", "--csv", path, "--utc-offset", "3", "--dry-run", "--backfill", "30"],
                          capture_output=True, text=True, env=env).stdout
    check("--backfill：交易日 K 一包、啟動期 5 分 K 分包", "K_SESSION US.ES_FRONT 3 根" in out2 and "K_5M US.ES_FRONT" in out2, out2[-400:])
    check("日誌不含權杖字樣", "token" not in out + out2)

print("\n=== [R141] --export-m1：M1 歷史逐月匯出 ===")
check("紐約 + 7 慣例：夏令券商 01:00 → 紐約 18:01 收市", m.to_ny_close_rule(ep("2026-10-06 01:00"), 1) == "2026-10-05 18:01:00")
check("冬令（1 月）券商 UTC+2 也是紐約 + 7", m.to_ny_close_rule(ep("2026-01-06 01:00"), 1) == "2026-01-05 18:01:00"
      and m.to_ny_close(ep("2026-01-06 01:00"), 2, 1) == "2026-01-05 18:01:00")
check("現時慣例時差：夏令 3、冬令 2", m.ny_rule_offset(datetime(2026, 10, 6, tzinfo=UTC)) == 3 and m.ny_rule_offset(datetime(2026, 1, 6, tzinfo=UTC)) == 2)
check("逐月往前跨年", list(m.months_back("2026-02", 4)) == [(2026, 2), (2026, 1), (2025, 12), (2025, 11)])
def fake_month(y, mo):                        # 2026-09、2026-10 各有兩天 M1；之前沒有
    if (y, mo) not in ((2026, 10), (2026, 9)):
        return []
    out, t = [], ep(f"{y}-{mo:02d}-07 01:00")   # 週三 01:00 券商 = 紐約週二 18:00
    for _ in range(2 * 1440):
        out.append({"time": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "tick_volume": 1}); t += 60
    return out
bars1 = m.rates_to_bars(fake_month(2026, 10), None, minutes=1, ny_rule=True)
check("M1 每個交易日 1380 根（23 小時），休市 17:01–18:00 略過", len(bars1) == 2 * 1380 and not any("17:01:00" <= b["time_key"][11:] <= "18:00:00" for b in bars1), len(bars1))
sent = []
f = m.Feed(dry_run=True)
f.post = lambda pk, quiet=False: sent.append(pk) or True
f.export_m1("US.ES_FRONT", "SP500ft", "2026-10", fake_month)
check("K_1M 每包 ≤ 400 根、全部推出", all(p["kline_type"] == "K_1M" and len(p["data"]) <= 400 for p in sent)
      and sum(len(p["data"]) for p in sent) == 2 * 2 * 1380 and sent[0]["symbol"] == "US.ES_FRONT", len(sent))
calls = []
f.export_m1("US.ES_FRONT", "SP500ft", "2026-10", lambda y, mo: calls.append((y, mo)) or fake_month(y, mo))
check("抓 2026-10、09，再 3 個空月後停", calls == [(2026, 10), (2026, 9), (2026, 8), (2026, 7), (2026, 6)], calls)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
