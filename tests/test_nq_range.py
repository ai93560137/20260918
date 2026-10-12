"""[R158] NQ 波幅頁：US.NQ 前綴 → NQ 市場設定（共用美股時區／交易日）、?view=nq_range 路由、頂部連結、方向一文字用 NQ 單位。"""
import json, os, sys, types
os.environ.setdefault("WEBHOOK_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")
src = open("/home/user/20260918/tests/test_futu_paper.py", encoding="utf-8").read()
exec(compile(src[:src.index("print(\"\\n=== 純函數")], "fake_gcs", "exec"))      # 假 GCS、client、sessions()、put()、hk()
from datetime import datetime, timezone, timedelta

print("\n=== [R158] NQ 市場設定 ===")
NQ, ES = main.NQ_SYMBOL, main.ES_SYMBOL
m = main.futu_market(NQ)
check("US.NQ 前綴 → NQ 設定；US.MNQ 也是；ES 不受影響", m["view"] == "nq_range" and main.futu_market("US.MNQ2612")["view"] == "nq_range"
      and main.futu_market(ES)["view"] == "es_range" and main.futu_market("HK.HSI_FRONT")["view"] == "futu_range")
check("NQ 共用美股邏輯（key US、紐約時區、18:00 切日）", m["key"] == "US" and m["tz"] is main.NY_TZ and m["start_hour"] == 18
      and main.futu_session_today(datetime.strptime("2026-10-05 18:00", "%Y-%m-%d %H:%M").replace(tzinfo=main.NY_TZ), NQ) == "2026-10-06")
check("NQ 文字：標題、每點 US$20、行使價間距 100、VXN", "NQ 納指 100 期貨波幅" in m["title"] and m["pt_zh"] == "US$20" and m["step"] == 100
      and m["iv_ref"].startswith("VXN") and main.futu_market(ES)["step"] == 25)
check("高低位分布與準確率仍查得到（用 ES 的 US 表）", main.peak_remaining_share("12:00", NQ) == main.peak_remaining_share("12:00", ES))

print("\n=== 頁面與路由 ===")
FAKE.clear()
page0 = client.get("/?view=nq_range").get_data(as_text=True)
check("沒數據：NQ 頁標題與 mt5_push 提示", "NQ 納指 100 期貨波幅" in page0 and "NAS100ft:US.NQ_FRONT" in page0, page0[:300])
for v in ("futu_range", "es_range", "welcome"):
    check(f"{v} 頁頂有 NQ 連結", "href='?view=nq_range'>🇺🇸 NQ 波幅" in client.get(f"/?view={v}").get_data(as_text=True))
check("NQ 頁頂目前頁是 NQ、有 ES 連結", "nav-current'>🇺🇸 NQ 波幅" in page0 and "href='?view=es_range'>🇺🇸 ES 波幅" in page0)
days = sessions(300, end="2026-10-09")
for b in days:
    b["source"] = "mt5_cfd:NAS100ft"
r = client.post("/", json={"action": "futu_data", "token": "tok", "symbol": NQ, "kline_type": "K_SESSION", "source": "mt5_cfd:NAS100ft", "data": days})
check("NQ K_SESSION 封包 200", r.status_code == 200, r.get_data(as_text=True)[:200])
js = client.get("/?view=nq_range&format=json").get_json()
check("JSON 代號是 US.NQ_FRONT、有 200 天以上、有預測", js["symbol"] == NQ and len(js["rows"]) >= 200 and bool(js.get("forecast")), str(js)[:200])
check("ES 的日線沒被 NQ 封包影響", client.get("/?view=es_range&format=json").get_json()["status"] == "empty")
page = client.get("/?view=nq_range").get_data(as_text=True)
check("NQ 頁：標題、US$20 文字、列印按鈕", "NQ 納指 100 期貨波幅" in page and "US$20" in page and "列印" in page, page[:200])
check("頁上沒有 ES 的名字殘留在 NQ 專屬文字", "ES 暫時只有" not in page and "NQ 暫時只有" in page)

print("\n=== 方向一文字（5 分 K 後）===")
five = [{"time_key": "2026-10-09 15:55:00", "open": 31100, "high": 31120, "low": 31080, "close": 31100, "volume": 100}]
r = client.post("/", json={"action": "futu_data", "token": "tok", "symbol": NQ, "kline_type": "K_5M", "data": five})
check("NQ 5 分 K 封包 200", r.status_code == 200, r.get_data(as_text=True)[:200])
data = main.futu_range_data(NQ)
now = datetime.strptime("2026-10-09 16:30", "%Y-%m-%d %H:%M").replace(tzinfo=main.NY_TZ).astimezone(timezone.utc)
p = main._strangle_plan(data, NQ, now)
check("勒式行使價以 100 取整", p and p.get("put") and p["put"] % 100 == 0 and p["call"] % 100 == 0 and p["step"] == 100, str(p)[:300])
how = main._fy_howto(data, NQ, now)
check("操作箱用 NQ 週期權、US$20", "每週沽 NQ 週期權 1σ 勒式" in how and "NQ 週期權（週五到期，每點 US$20）" in how and "每點賠 US$20" in how and "US$50" not in how)
money = main._fy_money(data, NQ)
check("方向一卡：VXN、NQ、每點 US$20", "VXN" in money and "NQ 期權" in money and "每點 US$20" in money and "ES 未回測" not in money)
how_es = main._fy_howto(main.futu_range_data(ES) if client.get("/?view=es_range&format=json").get_json()["status"] == "ok" else data, ES, now)
check("ES 操作箱不受影響（仍是 ES、US$50）", "每週沽 ES 週期權 1σ 勒式" in how_es and "US$50" in how_es)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
