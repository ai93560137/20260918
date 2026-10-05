"""[R127] ES 波幅頁：市場設定（紐約時間、CME 全段交易日）、?view=es_range 路由、頂部連結、K_SESSION 封包入庫與開市前紀錄。"""
import json, os, sys, types
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")
src = open("/home/user/20260918/tests/test_futu_paper.py", encoding="utf-8").read()
exec(compile(src[:src.index("print(\"\\n=== 純函數")], "fake_gcs", "exec"))      # 假 GCS、client、sessions()、put()、hk()
from datetime import datetime, timezone, timedelta

print("\n=== 市場設定 ===")
ES = main.ES_SYMBOL
check("US. 前綴 → 美股市場；其餘 → 恒指", main.futu_market(ES)["view"] == "es_range" and main.futu_market("HK.HSI_FRONT")["view"] == "futu_range"
      and main.futu_market(None)["view"] == "futu_range")
ny = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=main.NY_TZ).astimezone(timezone.utc)
check("ES 交易日：紐約 17:59 仍是當天、18:00 起算下一天；週日 18:00 = 週一", main.futu_session_today(ny("2026-10-05 17:59"), ES) == "2026-10-05"
      and main.futu_session_today(ny("2026-10-05 18:00"), ES) == "2026-10-06" and main.futu_session_today(ny("2026-10-04 18:30"), ES) == "2026-10-05")
check("恒指交易日不受影響（香港 08:59 = 前一天）", main.futu_session_today(hk("2026-10-05 08:59")) == "2026-10-04" and main.futu_session_today(hk("2026-10-05 09:00")) == "2026-10-05")
check("5 分 K → 交易日：US 用 18:00 切", main.futu_session_of("2026-10-05 18:05:00", ES) == "2026-10-06" and main.futu_session_of("2026-10-05 16:55:00", ES) == "2026-10-05"
      and main.futu_session_of("2026-10-05 02:00:00") == "2026-10-04")
check("收市過了沒：US 當天 17:00、HK 翌日 03:00", main.futu_session_end_passed("2026-10-05", ny("2026-10-05 17:00"), ES) and not main.futu_session_end_passed("2026-10-05", ny("2026-10-05 16:59"), ES)
      and main.futu_session_end_passed("2026-10-05", hk("2026-10-06 03:00")) and not main.futu_session_end_passed("2026-10-05", hk("2026-10-06 02:59")))

print("\n=== 封包入庫（K_SESSION）與頁面 ===")
FAKE.clear()
page0 = client.get("/?view=es_range").get_data(as_text=True)
check("沒數據：ES 頁標題與提示", "ES 標普 500 期貨波幅" in page0 and "es_daily_push" in page0, page0[:300])
days = sessions(300, end="2026-10-02")
for b in days:
    b["source"] = "yfinance:ES=F"
r = client.post("/", json={"action": "futu_data", "token": "tok", "symbol": ES, "kline_type": "K_SESSION", "source": "yfinance:ES=F", "data": days})
check("K_SESSION 封包 200", r.status_code == 200, r.get_data(as_text=True)[:200])
series = json.loads(FAKE[main.futu_daily_file(ES)][0])
check("合併進 futu/daily/US.ES_FRONT.json", len(series) == 300 and series[-1]["time_key"] == "2026-10-02", len(series))
page = client.get("/?view=es_range").get_data(as_text=True)
check("ES 頁：標題、CME 全段文字、三張卡、過去 7 次、沒有紙上交易卡", "ES 標普 500 期貨波幅" in page and "CME 全段" in page and ("📅 今日" in page or "📅 下個交易日" in page)
      and "🗓️ 本週" in page and "過去 7 次預測" in page and "🐍 蛇蟠陣" not in page and "暫時只有" in page, [x for x in ("CME 全段", "📅 今日", "過去 7 次預測") if x not in page])
check("ES 頁頂部連結：ES 是目前頁、恒指可點", "nav-current'>🇺🇸 ES 波幅" in page and "href='?view=futu_range'>🌬️ 風揚陣波幅" in page)
check("恒指頁與首頁頂部有 ES 連結", "href='?view=es_range'>🇺🇸 ES 波幅" in client.get("/?view=futu_range").get_data(as_text=True)
      and "href='?view=es_range'>🇺🇸 ES 波幅" in client.get("/?view=welcome").get_data(as_text=True))
js = client.get("/?view=es_range&format=json").get_json()
check("format=json：代號 US.ES_FRONT、有預測", js["symbol"] == ES and js.get("forecast") and js["forecast"].get("range"), js.get("symbol"))
for f in ("gates.html", "order.html", "jinnang_sheet.html", "jinnang_tracker.html"):
    check(f"{f} 有 ES 連結", "es_range" in open(f"/home/user/20260918/{f}", encoding="utf-8").read())

print("\n=== 開市前紀錄：紐約 18:00–19:00 才記 ===")
rep = client.get("/?view=es_range&report=preopen&format=json").get_json()     # 現在時間不一定在時段內 → 只確認回應正常
check("report=preopen 回 ok 或 skip", rep["status"] in ("ok", "skip"), rep)
r2 = main.futu_report(ES, "preopen", now=ny("2026-10-05 18:30"))
check("18:30 紐約：記下 10-06 的預測", r2["status"] == "ok" and r2["date"] == "2026-10-06" and main.futu_logged_forecast(ES, "2026-10-06"), r2.get("date"))
r3 = main.futu_report(ES, "preopen", now=ny("2026-10-06 12:00"))
check("中午只預覽不記錄", r3["status"] == "ok" and not main.futu_logged_forecast(ES, "2026-10-07"))
r4 = main.futu_report(ES, "preopen", now=ny("2026-10-10 18:30"))      # 週六 18:30 → 交易日 10-11（週日）不是交易日
check("週末不是交易日 → skip", r4["status"] == "skip", r4)
check("恒指的開市前時段照舊（香港 07:53）", main.futu_report("HK.HSI_FRONT", "preopen", now=hk("2026-10-05 07:53"))["status"] in ("ok", "skip"))

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
