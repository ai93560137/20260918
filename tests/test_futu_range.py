"""[R97] 即月期貨日線序列 futu/daily/<代號>.json 與 ?view=futu_range 波幅頁。"""
import json, os, sys, types

os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")

import functions_framework                      # noqa: E402  真的載入，別被假模組蓋掉
import google, google.cloud                      # noqa: E402
FAKE = {}
class _Blob:
    def __init__(self, name): self.name = name; self.generation = FAKE.get(name, (None, 0))[1]
    def exists(self): return self.name in FAKE
    def download_as_text(self, *a, **k):
        if self.name not in FAKE: raise KeyError(self.name)
        return FAKE[self.name][0]
    def download_as_bytes(self, *a, **k): return self.download_as_text().encode("utf-8")
    def upload_from_string(self, data, *a, **k):
        gen = FAKE.get(self.name, (None, 0))[1] + 1
        FAKE[self.name] = (data, gen); self.generation = gen
    def reload(self): self.generation = FAKE.get(self.name, (None, 0))[1]
class _Bucket:
    def blob(self, name): return _Blob(name)
    def get_blob(self, name): return _Blob(name) if name in FAKE else None
class _Client:
    def __init__(self, *a, **k): pass
    def bucket(self, name): return _Bucket()
storage_mod = types.ModuleType("google.cloud.storage"); storage_mod.Client = _Client
sys.modules["google.cloud.storage"] = storage_mod; google.cloud.storage = storage_mod
genai = types.ModuleType("google.genai"); genai.Client = lambda *a, **k: None
genai.types = types.SimpleNamespace(); sys.modules["google.genai"] = genai
exc_mod = types.ModuleType("google.api_core.exceptions")
class _PC(Exception): pass
exc_mod.PreconditionFailed = _PC; exc_mod.NotFound = KeyError
api_core = types.ModuleType("google.api_core"); api_core.exceptions = exc_mod
sys.modules["google.api_core"] = api_core; sys.modules["google.api_core.exceptions"] = exc_mod

import main


OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = main.app.test_client()
from datetime import date, timedelta


def day_bars(start, n, base=24000.0, step=10.0, rng=200.0):
    out, d = [], date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            c = base + step * len(out)
            out.append({"time_key": f"{d} 00:00:00", "open": c - 20, "high": c + rng / 2, "low": c - rng / 2,
                        "close": c, "volume": 1000})
        d += timedelta(days=1)
    return out


def packet(bars, source="futu_opend:HK.HSI2610", symbol="HK.HSI_FRONT", kline="K_SESSION"):
    return {"action": "futu_data", "token": "tok", "source": source, "script_version": "7",
            "symbol": symbol, "kline_type": kline, "timestamp": "2026-10-04 01:00:00", "data": bars, "options": []}


print("\n=== R97：交易日 K（K_SESSION）合併成一條序列 ===")
FAKE.clear()
series = main.futu_daily_file("HK.HSI_FRONT")
r = client.post("/", json=packet(day_bars("2026-09-01", 15)))
check("交易日 K 封包 stored", r.get_json().get("status") == "stored", r.get_json())
check("按日封存在 futu_k_session", any(k.startswith("archive/futu_k_session/HK.HSI_FRONT/") for k in FAKE))
rows = json.loads(FAKE[series][0])
check("寫進 futu/daily/HK.HSI_FRONT.json，日期只留年月日", len(rows) == 15 and rows[0]["time_key"] == "2026-09-01", rows[:1])
check("每列記下合約來源", rows[0]["source"] == "futu_opend:HK.HSI2610")
check("交易日 K 不蓋即時快照", main.FUTU_SNAPSHOT_FILE not in FAKE)
upd = day_bars("2026-09-15", 3, base=99999)
client.post("/", json=packet(upd, source="futu_opend:HK.HSI2611"))
rows = json.loads(FAKE[series][0])
by = {r["time_key"]: r for r in rows}
check("同一天後到的蓋掉、不重複", len(rows) == 15 and by["2026-09-15"]["close"] == 99999
      and by["2026-09-15"]["source"].endswith("2611"), len(rows))
check("依日期排序", [r["time_key"] for r in rows] == sorted(r["time_key"] for r in rows))
client.post("/", json=packet(day_bars("2026-09-01", 3), symbol="US.AAPL"))
check("非 _FRONT 代號不建序列", main.futu_daily_file("US.AAPL") not in FAKE)
client.post("/", json=packet(day_bars("2026-10-01", 2, base=11111), kline="K_DAY"))
check("Futu 自己的日 K（前一晚夜市算今天）不進序列", all(r["close"] != 11111 for r in json.loads(FAKE[series][0])))
client.post("/", json=packet(day_bars("2026-09-01", 3), kline="K_5M"))
check("5 分 K 不進日線序列", len(json.loads(FAKE[series][0])) == 15)

FAKE.clear()
r = client.post("/", json=packet([{"time_key": "2026-10-02 09:30:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3}],
                                 kline="K_15M"))
check("[R100] 15 分 K 歷史：stored、只封存", r.get_json()["status"] == "stored"
      and "archive/futu_k_15m/HK.HSI_FRONT/2026-10-02.json" in FAKE)
check("[R100] 15 分 K 不蓋即時快照、不進交易日序列", main.FUTU_SNAPSHOT_FILE not in FAKE
      and main.futu_symbol_file("HK.HSI_FRONT") not in FAKE and main.futu_daily_file("HK.HSI_FRONT") not in FAKE)
client.post("/", json=packet([{"time_key": "2026-10-02 09:30:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3}],
                             kline="K_5M"))
check("[R100] 5 分 K 照樣更新即時快照", main.futu_symbol_file("HK.HSI_FRONT") in FAKE)

print("\n=== R97：波幅統計 ===")
bars = day_bars("2025-09-01", 300)
stats = main.futu_range_stats(bars, "2026-10-04")
rows, s = stats["rows"], stats["summary"]
check("只留過去一年", rows[0]["date"] >= "2025-10-04" and all(r["date"] >= "2025-10-04" for r in rows), rows[0]["date"])
check("波幅 = 高 − 低", all(abs(r["range"] - 200) < 1e-9 for r in rows))
check("真實波幅含昨收跳空", rows[1]["true_range"] == 200.0)
check("波幅% = 波幅 ÷ 昨收", abs(rows[1]["range_pct"] - round(200 / rows[0]["close"] * 100, 3)) < 1e-9)
check("一年平均、20 日、ATR14", s["avg_range"] == 200 and s["avg_range_20"] == 200 and s["atr_14"] == 200, s)
gap = [dict(b) for b in day_bars("2026-09-01", 3)]
gap[2].update(open=25000, high=25100, low=24950, close=25050)          # 跳空高開
g = main.futu_range_stats(gap, "2026-10-04")["rows"]
check("跳空：真實波幅 > 波幅", g[2]["true_range"] == 25100 - gap[1]["close"] and g[2]["range"] == 150, g[2])
part = main.futu_range_stats(day_bars("2026-09-28", 6), "2026-10-04")      # 最後一根 10-05 > 今天
check("目前交易日以後的一根算交易中、不進平均", part["partial"] and part["summary"]["last_date"] == "2026-10-02"
      and part["rows"][-1]["date"] == "2026-10-05", part["summary"])
check("百分位在 0–100", 0 <= part["summary"]["last_range_percentile"] <= 100)
check("沒有數據不會壞", main.futu_range_stats([], "2026-10-04")["summary"]["avg_range"] is None)
bad = main.futu_range_stats([{"time_key": "x", "open": 1}, *day_bars("2026-09-01", 2)], "2026-10-04")
check("壞列略過", len(bad["rows"]) == 2)

print("\n=== R97：頁面與 JSON ===")
FAKE.clear()
r = client.get("/?view=futu_range")
check("沒數據時頁面 200 並說明怎麼補", r.status_code == 200 and "--backfill" in r.get_data(as_text=True))
client.post("/", json=packet(day_bars("2025-10-01", 260)))
client.post("/", json=packet([{"time_key": "2026-10-03 02:55:00", "open": 1, "high": 2, "low": 0.5,
                                "close": 23845, "volume": 5}], kline="K_5M"))
r = client.get("/?view=futu_range")
html_text = r.get_data(as_text=True)
check("頁面 200", r.status_code == 200, r.status_code)
check("有最新 OHLC、圖、表", "最新交易日" in html_text and "<svg" in html_text and "每日 OHLC 與波幅" in html_text)
check("顯示合約與最新 5 分 K", "HK.HSI2610" in html_text and "23,845" in html_text)
check("hsi_range 是同一頁", client.get("/?view=hsi_range").status_code == 200)
j = client.get("/?view=futu_range&format=json").get_json()
check("JSON 有 rows 與 summary", j["status"] == "ok" and j["rows"] and j["summary"]["avg_range"] == 200, j.get("summary"))
check("JSON 帶合約與最新 5 分 K", j["contract"] == "HK.HSI2610" and j["latest_5m"]["close"] == 23845)
client.post("/", json=packet([{"time_key": "2026-10-03 02:55:00", "open": 1, "high": 2, "low": 0.5, "close": 23845, "volume": 5},
                              {"time_key": "2026-10-05 09:20:00", "open": 23845, "high": 23845, "low": 23845, "close": 23845,
                               "volume": 0}], kline="K_5M"))
j = client.get("/?view=futu_range&format=json").get_json()
check("最新 5 分 K 略過開市前的佔位 K 線", j["latest_5m"]["time_key"] == "2026-10-03 02:55:00", j["latest_5m"])
check("控制台的 Futu 區塊連到波幅頁", "?view=futu_range" in main.futu_dashboard_html())
check("導覽列有風揚陣（R105，使用者要求每頁頂都有）", ("futu_range", "🌬️ 風揚陣波幅") in main.PAGE_LINKS)
e = client.get("/?view=futu_range&symbol=<script>").get_data(as_text=True)
check("代號會跳脫", "<script>" not in e)

print("\n=== R98：HAR 波幅預測 ===")
import random as _rnd
_rnd.seed(7)
def noisy(n, start="2025-01-02"):
    out, d, c = [], date.fromisoformat(start), 24000.0
    while len(out) < n:
        if d.weekday() < 5:
            rng = abs(_rnd.gauss(400, 120)) + 50
            lo = c - rng * _rnd.random(); out.append({"time_key": f"{d} 00:00:00", "open": c, "high": lo + rng,
                                                      "low": lo, "close": lo + rng * _rnd.random(), "volume": 1})
            c = out[-1]["close"]
        d += timedelta(days=1)
    return out
rows = main.futu_range_rows(noisy(120))
har = main.har_forecasts(rows)
check("不足 60 天不預測", main.har_forecasts(rows[:50]) == {})
check("60 天後每天都有預測，下一天也有", 100 in har and len(rows) in har and 30 not in har, sorted(har)[:3])
check("區間包住預測", all(lo < f < hi for f, lo, hi in har.values()))
changed = [dict(r) for r in rows]; changed[110] = dict(changed[110], range_pct=changed[110]["range_pct"] * 5)
har2 = main.har_forecasts(changed)
check("逐日前推：改第 110 天不影響之前的預測", all(har[t] == har2[t] for t in har if t <= 110)
      and har[111] != har2[111])
check("last_n 只算最後幾天、結果一樣", main.har_forecasts(rows, last_n=5) == {t: v for t, v in har.items() if t >= len(rows) - 4})
z = [dict(r) for r in rows]; z[80] = dict(z[80], range_pct=0.0, range=0.0)
check("波幅 0 的日子略過、不出錯", len(rows) in main.har_forecasts(z))
st = main.futu_range_stats(noisy(120), "2026-01-01")
check("統計帶預測與回測", st["forecast"] and st["forecast"]["date"] == "next" and st["backtest"]["days"] > 0
      and 0 <= st["backtest"]["coverage_80"] <= 100, st["backtest"])

FAKE.clear()
today = main.futu_session_today()
hist = noisy(100, "2025-12-01")
hist = [b for b in hist if b["time_key"][:10] < today][-90:]
client.post("/", json=packet(hist))
fk = main.futu_forecast_file("HK.HSI_FRONT")
check("回補舊日子不寫實時紀錄", fk not in FAKE)
live = [{"time_key": f"{today} 00:00:00", "open": 24000, "high": 24100, "low": 23950, "close": 24050, "volume": 5}]
client.post("/", json=packet(live))
log1 = json.loads(FAKE[fk][0])
check("當天第一包交易日 K 寫入預測", len(log1) == 1 and log1[0]["date"] == today and log1[0]["lo"] < log1[0]["range"] < log1[0]["hi"], log1)
client.post("/", json=packet([dict(live[0], high=26000)]))
check("同一天不重寫（記錄不因之後的數據改變）", json.loads(FAKE[fk][0]) == log1)
j = client.get("/?view=futu_range&format=json").get_json()
check("頁面用已記錄的預測", j["forecast"]["logged"] and j["forecast"]["range"] == log1[0]["range"], j.get("forecast"))
h = client.get("/?view=futu_range").get_data(as_text=True)
check("頁面有預測卡、準確度卡、預測欄與預測線", "🔮 預測波幅" in h and "預測準確度" in h and "HAR 預測</th>" in h
      and "stroke-dasharray" in h)

from datetime import datetime as _dt, timezone as _tz
check("交易日：香港 08:59 算前一天、09:00 起算當天",
      main.futu_session_today(_dt(2026, 10, 6, 0, 59, tzinfo=_tz.utc)) == "2026-10-05"     # 香港 08:59
      and main.futu_session_today(_dt(2026, 10, 6, 1, 0, tzinfo=_tz.utc)) == "2026-10-06"  # 香港 09:00
      and main.futu_session_today(_dt(2026, 10, 5, 18, 30, tzinfo=_tz.utc)) == "2026-10-05")  # 香港 02:30 夜市

# ---- [R104] 日／週／月過去每一次預測的誤差與命中率 ----
long_rows = main.futu_range_rows(noisy(420, "2024-06-03"))
lhar = main.har_forecasts(long_rows)
acc = main.futu_accuracy(long_rows, lhar)
d = acc["day"]
check("日：每個有預測的交易日一筆", len(d["records"]) == len([t for t in lhar if t < len(long_rows)]), len(d["records"]))
check("日：波幅差距 = 實際 − 預測、波幅落在範圍另計",
      all(r["err"] == round(r["actual"] - r["forecast"], 1) and r["hit_range"] == (r["lo"] <= r["actual"] <= r["hi"]) for r in d["records"]))
check("[R109] 日：高、低都落在各自預計範圍才算 ✅",
      all(r["hit"] == ((r["high_lo"] <= r["actual_high"] <= r["high_hi"]) and (r["low_lo"] <= r["actual_low"] <= r["low_hi"]))
          for r in d["records"] if r["hit"] is not None)
      and all(r["hit"] is None for r in d["records"][:main.HL_MIN_DAYS]))
check("日：比率與次數一致；波幅另計全部日子", d["n"] == len(d["records"]) - main.HL_MIN_DAYS
      and d["hit_rate"] == round(d["hits"] / d["n"] * 100) and d["hit_range_n"] == len(d["records"])
      and d["hit_rate"] <= min(d["hit_high_rate"], d["hit_low_rate"]))
check("日：高位、低位平均差", d["mae_high"] == round(sum(abs(r["err_high"]) for r in d["records"] if r["err_high"] is not None) / d["n"], 1))
check("日：近 7 次是最後 7 筆", d["recent"] == d["records"][-7:] and d["recent_hits"] == sum(bool(r["hit"]) for r in d["recent"]))
hl = [r for r in d["records"] if r["hit_high"] is not None]
check("日：高低位要累積 120 天才評分", len(hl) == len(d["records"]) - main.HL_MIN_DAYS and d["hit_high_n"] == len(hl), len(hl))
w = acc["week"]
scored = [r for r in w["records"] if r["hit"] is not None]
check("週：前 12 段只估比例、不評分", len(w["records"]) - len(scored) == main.PERIOD_CAL_MIN and w["n"] == len(scored))
check("週：預測 = 第一天 HAR × √日數 × 之前的比例中位數",
      all(r["lo"] <= r["forecast"] <= r["hi"] and r["hit_range"] == (r["lo"] <= r["actual"] <= r["hi"]) for r in scored), scored[:1])
whl = [r for r in scored if r.get("high") is not None]
check("[R120] 週：有預測高位／低位與預計範圍，✅ = 兩邊都落在範圍", len(whl) >= len(scored) - 1
      and all(r["high_lo"] <= r["high"] <= r["high_hi"] and r["low_lo"] <= r["low"] <= r["low_hi"]
              and r["hit"] == ((r["high_lo"] <= r["actual_high"] <= r["high_hi"]) and (r["low_lo"] <= r["actual_low"] <= r["low_hi"])) for r in whl)
      and w["hit_high_n"] == len(whl) and w.get("cal") and len(w["cal"]["ups"]) >= main.PERIOD_CAL_MIN, whl[:1])
check("月：有紀錄", acc["month"]["records"] and all(len(r["key"]) == 7 for r in acc["month"]["records"]))
late = [dict(r) for r in long_rows]; late[-1] = dict(late[-1], high=late[-1]["high"] + 5000, range=late[-1]["range"] + 5000)
acc2 = main.futu_accuracy(late, main.har_forecasts(late))
check("逐日前推：改最後一天不影響之前的預測", [r["forecast"] for r in acc2["day"]["records"][:-1]]
      == [r["forecast"] for r in d["records"][:-1]] and
      [r.get("forecast") for r in acc2["week"]["records"][:-1]] == [r.get("forecast") for r in w["records"][:-1]])
last_week = w["records"][-1]["key"]
check("還沒結束的那段不計分", all(r["key"] != last_week for r in
                                 main.futu_accuracy(long_rows, lhar, open_keys={"week": last_week})["week"]["records"]))
day0 = d["records"][-1]["key"]
acc3 = main.futu_accuracy(long_rows, lhar, [{"date": day0, "range": 1.0, "lo": 0.5, "hi": 2.0}])
r3 = acc3["day"]["records"][-1]
check("有開市前實時紀錄就用紀錄", r3["live"] and r3["forecast"] == 1.0 and r3["hit_range"] is False
      and not acc3["day"]["records"][-2]["live"], r3)
acc4 = main.futu_accuracy(long_rows, lhar, [{"date": day0, "range": 1.0, "lo": 0.5, "hi": 2.0, "high": 1, "low": 0,
                                             "high_lo": 0, "high_hi": 2, "low_lo": -1, "low_hi": 1, "band_q": main.HL_BAND_Q}])
check("[R109] 實時紀錄的高低位範圍也照用（實際高位超出 → ❌）", acc4["day"]["records"][-1]["high_hi"] == 2
      and acc4["day"]["records"][-1]["hit"] is False)
acc5 = main.futu_accuracy(long_rows, lhar, [{"date": day0, "range": 1.0, "lo": 0.5, "hi": 2.0, "high": 1, "low": 0,
                                             "high_lo": 0, "high_hi": 2, "low_lo": -1, "low_hi": 1}])
check("[R119] 舊紀錄沒有 band_q（80% 範圍）→ 高低位範圍改用逐日前推重算", acc5["day"]["records"][-1]["high_hi"] != 2
      and acc5["day"]["records"][-1]["live"] is True, acc5["day"]["records"][-1])
hh = main._fy_history("day", d)
check("[R109] 今日表：高、低都落在預計範圍的比率（白話）", "過去 7 次預測" in hh and f"高、低都落在預計範圍：{d['hit_rate']}%" in hh
      and f"中 {d['hits']} 次" in hh and hh.count("<tr>") == 8 and "各自計：高位" in hh and "命中" not in hh
      and "約九成" in hh)
r0 = d["recent"][-1]
check("[R109] 今日表每列有預測高／低與各自預計範圍", f"{r0['high_lo']:,.0f}–{r0['high_hi']:,.0f}" in hh
      and f"{r0['low_lo']:,.0f}–{r0['low_hi']:,.0f}" in hh and "二十次有十九次" in hh and hh.count("class='fy-rng'") == 16
      and "實際高" in hh and "實際低" in hh)
check("[R121] 表：中的綠字 ✓、跑出的紅字 ↑／↓、沒有結果欄", "<th>結果</th>" not in hh and "class='pos'>" in hh and " ✓" in hh
      and hh.count("<b class='pos'>") + hh.count("<b class='neg'>") == 2 * len(d["recent"])
      and hh.count("<b class='pos'>") == sum(bool(r["hit_high"]) + bool(r["hit_low"]) for r in d["recent"]), hh[:400])
hw = main._fy_history("week", w)
r1 = w["recent"][-1]
check("[R120] 週表與今日表同一格式：預測高／實際高／預測低／實際低、全週波幅", f"{r1['high_lo']:,.0f}–{r1['high_hi']:,.0f}" in hw
      and "實際高" in hw and "實際低" in hw and "全週波幅" in hw and "高、低都落在預計範圍" in hw
      and hw.count("class='fy-rng'") == 2 * len(w["recent"]) + 2, hw[:300])
check("頁面：沒數據就不顯示", main._fy_history("day", {"n": 0}) == "")
check("[R120] 月表同一格式", "實際高" in main._fy_history("month", acc["month"]) and "全月波幅" in main._fy_history("month", acc["month"]))
FAKE.clear()
client.post("/", json=packet([b for b in noisy(420, "2024-06-03") if b["time_key"][:10] < today]))
ja = client.get("/?view=futu_range&report=accuracy").get_json()
check("?report=accuracy 給全部紀錄", ja["status"] == "ok" and ja["day"]["n"] > 100 and ja["week"]["records"]
      and ja["day"]["recent"] is None, {k: ja.get(k) for k in ("status",)})
hp = client.get("/?view=futu_range").get_data(as_text=True)
check("波幅頁三張卡都有過去幾次預測", hp.count("📜 過去 ") == 3 and "📜 過去 7 次預測" in hp, hp.count("📜 過去"))
check("JSON 不帶內部欄位", "_har" not in client.get("/?view=futu_range&format=json").get_json())

# ---- [R105] 卡片標題日期、每頁導覽列有風揚陣 ----
check("日期：今日／本週（週一至五）／本月",
      main._fy_period_dates("day", "2026-10-05") == "10月5日（一）"
      and main._fy_period_dates("week", "2026-10-04") == "9月28日（一） 至 10月2日（五）"
      and main._fy_period_dates("month", "2026-10-02") == "2026年10月" and main._fy_period_dates("day", "next") == "")
check("波幅頁三張卡片標題都有日期", hp.count("class='fy-date'") == 3, hp.count("fy-date"))
check("波幅頁導覽列：風揚陣是目前這頁", "nav-current'>🌬️ 風揚陣波幅<" in hp)
for v in ("welcome", "info", "dashboard", "jinnang_sheet", "jinnang_tracker"):
    page = client.get(f"/?view={v}").get_data(as_text=True)
    check(f"?view={v} 導覽列有風揚陣連結", "?view=futu_range" in page and "🌬️ 風揚陣波幅" in page)

# ---- [R106] 💰 四個方向 ----
check("波幅頁有四個方向與方向二結論", "💰 怎樣用來賺錢（四個方向）" in hp and hp.count("方向") >= 4
      and "回測不賺錢" in hp and "MONEY_REPORT.md" in hp)
from datetime import datetime as _dt2, timezone as _tz2
def opt_snap(time_key):
    opts = [{"code": f"HK.HSI261009{t}{k}000", "option_type": t, "expiry": "2026-10-09", "strike": k, "iv": iv}
            for k, ivs in ((23900, (20.0, 22.0)), (24000, (24.0, 26.0))) for t, iv in zip(("CALL", "PUT"), ivs)]
    main.gcs_write_text(main.futu_symbol_file("HK.800000"), json.dumps(
        {"symbol": "HK.800000", "bars": [{"time_key": time_key, "close": 23940}], "options": opts,
         "received_ts": 0, "received_utc": "x"}))
fc0 = {"range": 400.0, "ref_close": 24000.0}
opt_snap("2026-10-05 10:30:00")
ivc = main.futu_iv_compare(fc0, now=_dt2(2026, 10, 5, 2, 40, tzinfo=_tz2.utc))          # 香港 10:40
har_vol = 400 / 1.596 / 24000 * 252 ** 0.5 * 100
check("方向一：取最近行使價的 Call／Put 平均 IV、預測換成年化", ivc["strike"] == 23900 and ivc["iv"] == 21.0
      and abs(ivc["har_vol"] - round(har_vol, 1)) < 1e-9 and ivc["ratio"] == round(21.0 / har_vol, 2) and ivc["fresh"], ivc)
check("方向一：最新 K 線超過 20 分鐘（休市）→ 不比較",
      main.futu_iv_compare(fc0, now=_dt2(2026, 10, 5, 9, 0, tzinfo=_tz2.utc))["fresh"] is False)
check("方向一：沒有預測 → 只有 IV", main.futu_iv_compare(None)["har_vol"] is None)
money = main._fy_money({"forecast": fc0, "summary": {"avg_range": 460}, "rows": [{"forecast": x} for x in (300, 350, 500, 600)],
                        "iv_compare": ivc})
check("方向一卡：沒有 VHSI → 提示加 HK.800125；週期權 IV 只作參考", "HK.800125" in money and "21.0%" in money
      and "合成回測" in money)
main.gcs_write_text(main.futu_symbol_file("HK.800125"), json.dumps(
    {"symbol": "HK.800125", "bars": [{"time_key": "2026-10-05 10:30:00", "close": 25.0}], "options": []}))
ivv = main.futu_iv_compare(fc0, now=_dt2(2026, 10, 5, 2, 40, tzinfo=_tz2.utc))
check("方向一：讀 VHSI 快照，算 VHSI ÷ 預測", ivv["vhsi"] == 25.0 and ivv["vhsi_ratio"] == round(25.0 / ivv["har_vol"], 2), ivv)
m_hi = main._fy_money({"forecast": fc0, "summary": {}, "rows": [], "iv_compare": ivv})
check("方向一：比值 ≥ 1.2 → 達到合成回測的賣出條件（R117 字眼）", ivv["vhsi_ratio"] >= 1.2 and "合成回測的賣出條件" in m_hi and "VHSI ÷ 預測" in m_hi)
m_lo = main._fy_money({"forecast": fc0, "summary": {}, "rows": [], "iv_compare": dict(ivv, vhsi_ratio=1.05)})
check("方向一：比值 < 1.2 → 不賣", "回測中這種週不賣" in m_lo)
main.gcs_write_text(main.futu_symbol_file("HK.800000"), json.dumps({"symbol": "HK.800000", "bars": [], "options": []}))
check("方向一：只有 VHSI、沒有期權也能比較", main.futu_iv_compare(fc0)["vhsi"] == 25.0)
check("方向三：止蝕 ½ 預測、倉位係數", "200 點" in money and "1.15 倍" in money)
check("方向四：預測在一年中的位置", "50%" in money and "不是小波幅日" in money)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
