"""[R127][R130] ES 波幅頁：市場設定（紐約時間、CME 全段交易日）、?view=es_range 路由、頂部連結、K_SESSION 封包入庫與開市前紀錄。"""
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


print("\n=== [R130] ES 日內：交易日分鐘、變異比例、C 時間點、5 分 K 跨日讀取、蛇日、頁面 ===")
check("交易日分鐘：US 18:05 = 5、翌日 17:00 = 1380；HK 09:15 = 15 不變", main._session_minutes("2026-10-04 18:05:00", ES) == 5
      and main._session_minutes("2026-10-05 17:00:00", ES) == 1380 and main._session_minutes("2026-10-05 09:15:00") == 15)
check("US 變異比例表 89 格、加總 1；剛開市幾乎全剩、16:45 後所剩無幾", abs(sum(main.PEAK_PROFILE_15M_US.values()) - 1) < 1e-3 and len(main.PEAK_PROFILE_15M_US) == 89
      and main.peak_remaining_share("2026-10-04 18:05:00", ES) > 0.95 and main.peak_remaining_share("2026-10-05 16:45:00", ES) < 0.05,
      (main.peak_remaining_share("2026-10-04 18:05:00", ES), main.peak_remaining_share("2026-10-05 16:45:00", ES)))
check("HK 的剩餘比例照舊用恒指表", abs(main.peak_remaining_share("2026-10-05 09:30:00") - (1 - main.PEAK_PROFILE_15M["09:30"])) < 1e-3)
check("蛇日：US 不分日夜全算 day；HK 夜市仍是 night", main._paper_phase({"time_key": "2026-10-04 20:00:00"}, "2026-10-05", ES) == "day"
      and main._paper_phase({"time_key": "2026-10-05 20:00:00"}, "2026-10-05", "HK.HSI_FRONT") == "night")
check("回測準確率按市場：ES 日 B 高 96.5%、恒指 95.8%", main._peak_acc(ES, "day/high/B") == 0.965 and main._peak_acc("HK.HSI_FRONT", "day/high/B") == 0.958)
# 10-05（週一）交易日：10-04 18:05 起到 10-05 10:00 的 5 分 K，封存按當地日期分兩檔
ref = series[-1]["close"]
five, px, t = [], ref, datetime(2026, 10, 4, 18, 0)
import random as _r; _r.seed(5)
while t < datetime(2026, 10, 5, 10, 0):
    t += timedelta(minutes=5); px += _r.gauss(0, 1.2)
    five.append(bar(t.strftime("%Y-%m-%d %H:%M:%S"), px, px + 1.5, px - 1.5, px + 0.3))
for d in ("2026-10-04", "2026-10-05"):
    put(main.archive_blob_name("futu_k_5m", ES, d), [b for b in five if b["time_key"][:10] == d])
got = main.futu_session_5m(ES, "2026-10-05")
check("5 分 K 跨日讀取：10-05 交易日 = 10-04 18:05 起全部 192 根", len(got) == len(five) == 192 and got[0]["time_key"] == "2026-10-04 18:05:00", (len(got), len(five)))
check("10-04（週日）交易日沒有 K", main.futu_session_5m(ES, "2026-10-04") == [])
st = main.futu_peak_status(ES, now=ny("2026-10-05 10:00"))
per = (st or {}).get("periods", {}).get("day")
check("高低位狀態：今日 10-05、現價 = 最後一根收市、10:00 未到 C 時間點、剩餘比例在 0–1", st and st["today"] == "2026-10-05" and per and st["price"] == five[-1]["close"]
      and per["high"]["C"] is None and 0 < per["rem"] < 1, (st or {}).get("today"))
check("本週卡：10-05 是週首日，段長 = 本週交易日數 5", (st["periods"].get("week") or {}).get("sessions") == 5 and st["periods"]["week"]["first"] == "2026-10-05", st["periods"].get("week"))
# 走到 16:00（RTH 收市）：C 時間點已到
more, t = [], datetime(2026, 10, 5, 10, 0)
while t < datetime(2026, 10, 5, 16, 0):
    t += timedelta(minutes=5); px += _r.gauss(0, 1.2)
    more.append(bar(t.strftime("%Y-%m-%d %H:%M:%S"), px, px + 1.5, px - 1.5, px + 0.3))
put(main.archive_blob_name("futu_k_5m", ES, "2026-10-05"), [b for b in five if b["time_key"][:10] == "2026-10-05"] + more)
st2 = main.futu_peak_status(ES, now=ny("2026-10-05 16:00"))
check("16:00：C 時間點已判斷（True／False 而不是 None）", st2 and st2["periods"]["day"]["high"]["C"] in (True, False) and st2["periods"]["day"]["low"]["C"] in (True, False))
txt = main._peak_signal_text("day", "high", "B", st2["periods"]["day"], st2["periods"]["day"]["high"], st2["price"], ES)
check("通知文字用 ES 名稱與 ES 回測準確率", "ES 標普 500 期貨" in txt and "96% 準確" in txt and "恒指" not in txt, txt)
r5 = client.post("/", json={"action": "futu_data", "token": "tok", "symbol": ES, "kline_type": "K_5M", "source": "mt5_cfd:US500", "data": five + more})
check("K_5M 封包 200 stored", r5.status_code == 200 and r5.get_json().get("status") == "stored", r5.get_data(as_text=True)[:200])
page5 = client.get("/?view=es_range").get_data(as_text=True)
check("有 5 分 K 快照後：ES 頁顯示現價、合約 US500、紙上交易區，不再說「暫時只有日線」", "💹 現價" in page5 and "US500" in page5
      and "📒 紙上交易" in page5 and "暫時只有日線" not in page5)
lines_c = main._fy_signal_lines("day", st["periods"]["day"], "high", {}, ES)
check("ES 日卡的 C 時間點寫 16:00（恒指 16:30）", any("16:00才判斷" in x for x in lines_c) and any("16:30" in x for x in main._fy_signal_lines("day", st["periods"]["day"], "high", {}, "HK.HSI_FRONT")), lines_c)
check("恒指頁不受影響", "恒指即月期貨波幅" in client.get("/?view=futu_range").get_data(as_text=True))


print("\n=== [R133] ES 四次報告（紐約時間）===")
allbars = five + more                                                   # 10-04 18:05 → 10-05 16:00
rp = main.futu_report(ES, "noon", now=ny("2026-10-05 09:37"))
seg = [b for b in allbars if b["time_key"] <= "2026-10-05 09:30:00"]
check("09:37 隔夜時段檢討：ES 名稱、標題、高低 = 09:30 前的 K", rp["status"] == "ok" and "ES 標普 500 期貨" in rp["text"] and "隔夜時段檢討" in rp["text"]
      and rp["high"] == max(b["high"] for b in seg) and rp["low"] == min(b["low"] for b in seg) and "恒指" not in rp["text"], rp)
rp2 = main.futu_report(ES, "close", now=ny("2026-10-05 16:07"))
check("16:07 RTH 收市檢討", rp2["status"] == "ok" and "RTH 收市檢討" in rp2["text"] and rp2["bars"] == len(allbars), rp2.get("text", rp2)[:200])
rp3 = main.futu_report(ES, "night", now=ny("2026-10-05 17:07"))
check("17:07 全日收市檢討：CME 全段、隔夜／日間分段", rp3["status"] == "ok" and "全日收市檢討（CME 全段）" in rp3["text"] and "隔夜 高" in rp3["text"] and "日間（RTH＋尾段） 高" in rp3["text"], rp3.get("text", rp3)[:300])
check("三次檢討存檔、ES 頁摘要用 ET 時點（頁面只在那天有日線時顯示）", len([e for e in main.gcs_read_json(main.futu_review_file(ES), []) if e["date"] == "2026-10-05"]) == 3
      and main.futu_market(ES)["reviews_zh"] == "09:30／16:00／17:00 ET")
rp4 = main.futu_report(ES, "preopen", now=ny("2026-10-05 18:07"))
check("18:07 開市前預測：記 10-06、CME 全段文字", rp4["status"] == "ok" and rp4["date"] == "2026-10-06" and "開市前預測" in rp4["text"] and "CME 全段 23 小時" in rp4["text"]
      and main.futu_logged_forecast(ES, "2026-10-06"), rp4.get("text", rp4)[:200])
check("週日 17:07 沒有 K → skip；週六晚 18:07 的開市前（交易日 = 週日）→ skip", main.futu_report(ES, "night", now=ny("2026-10-04 17:07"))["status"] == "skip"
      and main.futu_report(ES, "preopen", now=ny("2026-10-03 18:07"))["status"] == "skip")
check("恒指檢討標題不變", main.futu_market("HK.HSI_FRONT")["reviews"]["close"][1] == "日市收市檢討" and main.futu_market("HK.HSI_FRONT")["reviews"]["noon"][2] == "12:00")


print("\n=== [R134] ES 頁四個方向 ===")
page_m = client.get("/?view=es_range").get_data(as_text=True)
check("ES 頁有四個方向、方向二用 ES 回測、單位 US$50、方向一寫未回測", "怎樣用來賺錢（四個方向）" in page_m and "fade_us" in page_m
      and "ES 每點 US$50" in page_m and "ES 未回測" in page_m and "VHSI 明顯高於" not in page_m)
sec_h = main._fy_money({"forecast": {}, "summary": {}, "rows": []}, "HK.HSI_FRONT")
check("恒指的四個方向照舊（VHSI 規則、恒指回測），並加 1σ 勒式規則書連結", "STRANGLE_1SIGMA" in sec_h and "VHSI 明顯高於" in sec_h
      and main.MONEY_FADE["status"] in sec_h and "fade_us" not in sec_h and "US$50" not in sec_h)


print("\n=== [R135] 方向一實際操作箱、頁頂更新時間 ===")
HK = "HK.HSI_FRONT"
base = {"calendar": {}, "latest_5m": {"close": 24144.0, "time_key": "2026-10-08 14:35:00"}, "rows": [], "forecast": {"range": 420.0, "ref_close": 24100.0},
        "iv_compare": {"iv": 18.3, "fresh": True, "expiry": "2026-10-17", "har_vol": 19.0}, "accuracy": {}}
pl = main._strangle_plan(base, HK, now=hk("2026-10-08 14:00"))
check("週四：下次操作週五 10-09、沽 10-16 到期、5 個交易日", pl["op"] == "2026-10-09" and not pl["op_is_today"] and pl["expiry"] == "2026-10-16" and pl["n"] == 5, pl)
check("σ點 = 0.183×√(5/252)×24,144 ≈ 622；Put 往下取 23,500、Call 往上取 24,800", abs(pl["sigma"] - 622) < 2 and pl["put"] == 23500 and pl["call"] == 24800, (pl.get("sigma"), pl.get("put"), pl.get("call")))
pl2 = main._strangle_plan(base, HK, now=hk("2026-10-09 10:00"))
pl3 = main._strangle_plan(base, HK, now=hk("2026-10-09 17:00"))
check("週五 10:00 = 今天操作日；16:30 後 → 下次是 10-16、沽 10-23 到期", pl2["op_is_today"] and pl3["op"] == "2026-10-16" and pl3["expiry"] == "2026-10-23", (pl2["op"], pl3["op"], pl3["expiry"]))
stale = {**base, "iv_compare": {"iv": 18.3, "fresh": False, "har_vol": 19.0}}
pl4 = main._strangle_plan(stale, HK, now=hk("2026-10-08 14:00"))
check("期權報價不新鮮 → 改用風揚陣預測年化 19.0%", pl4["iv"] is None and pl4["vol"] == 19.0 and "風揚陣" in pl4["vol_src"])
html_h = main._fy_howto(base, HK, now=hk("2026-10-08 14:00"))
check("恒指操作箱：六步、下次操作日、建議行使價、資金、規則書", all(x in html_h for x in ("第 1 步", "第 6 步", "下次操作：10-09（五） 16:30", "23,500", "24,800", "HK$250,000", "STRANGLE_1SIGMA")), html_h[:300])
page_box = client.get("/?view=es_range").get_data(as_text=True)
check("ES 頁有操作箱（標明未回測）與頁頂日期時間", "方向一實際操作：每週沽 ES 週期權" in page_box and "ES 未回測" in page_box and "更新（" in page_box and "⏱️ 10-05（一） 16:00 更新" in page_box)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
