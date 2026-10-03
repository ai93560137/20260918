"""[v6] futu/push_to_gcp.py 的即月期貨：選合約、最後交易日轉月、轉月後不蓋舊封存。
用假的 futu 模組與假的 OpenD，不連網、不需裝 futu-api。"""
import importlib.util, sys, types
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---- 假的 futu 模組（repo 的 futu/ 資料夾會被當成命名空間套件，要先蓋掉）
ft = types.ModuleType("futu")
ft.RET_OK, ft.RET_ERROR = 0, -1
ft.KLType = types.SimpleNamespace(K_5M="K_5M", K_15M="K_15M", K_30M="K_30M", K_60M="K_60M", K_DAY="K_DAY")
ft.SubType = types.SimpleNamespace(K_5M="K_5M", K_DAY="K_DAY")
ft.Market = types.SimpleNamespace(HK="HK", US="US")
ft.SecurityType = types.SimpleNamespace(FUTURE="FUTURE", IDX="IDX")
ft.TradeDateMarket = types.SimpleNamespace(HK="HK")
sys.modules["futu"] = ft

spec = importlib.util.spec_from_file_location(
    "push_to_gcp", Path(__file__).resolve().parent.parent / "futu" / "push_to_gcp.py")
push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(push)
push.BACKFILL_PACE_SEC = 0                       # 測試不用等

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")


LISTING = [("HK.HSImain", ""), ("HK.HSI2609", "2026-09-29"), ("HK.HSI2610", "2026-10-29"),
           ("HK.HSI2611", "2026-11-27"), ("HK.HSI2612", "2026-12-30"), ("HK.MHI2610", "2026-10-29"),
           ("HK.HSI261", "2026-10-29")]

print("=== 選合約 ===")
contracts = push.month_contracts(LISTING, "HSI")
check("只留 HSI 月份合約（略過主連、MHI、格式不對的）",
      [c for _, c in contracts] == ["HK.HSI2609", "HK.HSI2610", "HK.HSI2611", "HK.HSI2612"], contracts)
check("最後交易日格式（帶時間、無分隔）都接受",
      push.month_contracts([("HK.HSI2610", "2026-10-29 16:00:00"), ("HK.HSI2611", "20261127")], "HSI")
      == [("2026-10-29", "HK.HSI2610"), ("2026-11-27", "HK.HSI2611")])
check("月中取當月", push.pick_front(contracts, "2026-10-03") == ("HK.HSI2610", "2026-10-29", "2026-09-29"))
check("最後交易日前一天仍是當月", push.pick_front(contracts, "2026-10-28")[0] == "HK.HSI2610")
check("最後交易日當天轉下月", push.pick_front(contracts, "2026-10-29") == ("HK.HSI2611", "2026-11-27", "2026-10-29"))
check("轉月後到月底仍是下月", push.pick_front(contracts, "2026-10-31")[0] == "HK.HSI2611")
check("上一張已下架 → 上一張最後交易日為 None",
      push.pick_front(contracts[1:], "2026-10-30") == ("HK.HSI2611", "2026-11-27", "2026-10-29")
      and push.pick_front(contracts[2:], "2026-10-30")[2] is None)
check("全部過期 → 找不到", push.pick_front(contracts, "2027-01-05") == (None, None, None))
check("上個月份", push.prev_month("HK.HSI2610") == (2026, 9) and push.prev_month("HK.HSI2701") == (2026, 12))
check("別名格式", bool(push.FRONT_RE.match("HK.HSI_FRONT")) and bool(push.FRONT_RE.match("HK.MHI_FRONT"))
      and not push.FRONT_RE.match("HK.800000") and not push.FRONT_RE.match("US.QQQ"))


# ---- 假的 OpenD
def kline(code, dates_times, base):
    rows = [{"time_key": t, "open": base, "high": base + 5, "low": base - 5, "close": base + 1, "volume": 10}
            for t in dates_times]
    return pd.DataFrame(rows)


class FakeCtx:
    def __init__(self, listing, trading_days=None):
        self.listing, self.trading_days = listing, trading_days or []
        self.subs, self.unsubs = [], []

    def get_stock_basicinfo(self, market, kind):
        return ft.RET_OK, pd.DataFrame([{"code": c, "last_trade_time": t, "name": c} for c, t in self.listing])

    def request_trading_days(self, market, start, end):
        return ft.RET_OK, [{"time": d, "trade_date_type": "WHOLE"} for d in self.trading_days if start <= d <= end]

    def subscribe(self, codes, subtypes, subscribe_push=False):
        self.subs.append((tuple(codes), tuple(subtypes)))
        return ft.RET_OK, ""

    def unsubscribe(self, codes, subtypes):
        self.unsubs.append((tuple(codes), tuple(subtypes)))
        return ft.RET_OK, ""

    def get_cur_kline(self, code, num, ktype):
        base = 24000 if code.endswith("2610") else 24100
        if ktype == "K_5M":
            return ft.RET_OK, kline(code, ["2026-10-28 15:55:00", "2026-10-28 16:00:00", "2026-10-28 23:55:00",
                                           "2026-10-29 09:20:00", "2026-10-29 09:25:00"], base)
        return ft.RET_OK, kline(code, ["2026-10-27 00:00:00", "2026-10-28 00:00:00", "2026-10-29 00:00:00"], base)

    def close(self):
        pass


class Clock:
    """把腳本的 datetime.now 換成固定的香港時間。"""
    def __init__(self, day, hhmm="09:30"):
        self.day, self.hhmm = day, hhmm

    def now(self, tz=None):
        return datetime.fromisoformat(f"{self.day} {self.hhmm}:00").replace(tzinfo=tz)


def run(pusher, day, hhmm="09:30"):
    push.datetime = type("DT", (), {"now": staticmethod(Clock(day, hhmm).now),
                                    "fromisoformat": staticmethod(datetime.fromisoformat)})
    sent = []
    pusher.post = lambda packet, quiet=False: sent.append(packet) or True
    ok = pusher.run_front("HK.HSI_FRONT")
    return ok, sent


print("=== [v7] 交易日 = 09:00 至翌日 09:00 ===")
check("夜市 00:00–03:00 算前一個交易日", push.session_date("2026-10-03 02:55:00") == "2026-10-02"
      and push.session_date("2026-10-02 23:55:00") == "2026-10-02" and push.session_date("2026-10-05 09:20:00") == "2026-10-05")
B = lambda t, o, h, l, c, v=10: {"time_key": t, "open": o, "high": h, "low": l, "close": c, "volume": v}
sess = push.session_bars([B("2026-10-02 09:20:00", 100, 105, 99, 101), B("2026-10-02 16:30:00", 101, 103, 98, 102),
                          B("2026-10-02 17:20:00", 102, 104, 100, 103), B("2026-10-03 02:55:00", 103, 110, 97, 108),
                          B("2026-10-05 09:20:00", 108, 108, 108, 108, 0)])
check("日市＋當晚夜市合成一根：開＝日市開、收＝夜市收、高低含夜市",
      sess == [{"time_key": "2026-10-02 00:00:00", "open": 100, "high": 110, "low": 97, "close": 108, "volume": 40}], sess)
check("開市前的佔位 K 線（成交量 0）不算", all(not x["time_key"].startswith("2026-10-05") for x in sess))
cut = push.session_bars([B("2026-10-02 23:00:00", 1, 2, 0.5, 1), B("2026-10-05 09:20:00", 5, 6, 4, 5)])
check("視窗最前面被切掉一截的交易日丟掉（不蓋完整封存）", [x["time_key"][:10] for x in cut] == ["2026-10-05"], cut)
check("回補模式不丟", len(push.session_bars([B("2026-10-02 23:00:00", 1, 2, 0.5, 1)], complete_only=False)) == 1)

print("=== 推送（最後交易日 2026-10-29 轉月）===")
pusher = push.FutuPusher()
pusher.ctx = FakeCtx(LISTING)
ok, sent = run(pusher, "2026-10-28")
k5 = [p for p in sent if p["kline_type"] == "K_5M"]
kd = [p for p in sent if p["kline_type"] == "K_SESSION"]
check("轉月前一天：送當月合約、固定代號", ok and k5 and k5[0]["symbol"] == "HK.HSI_FRONT"
      and k5[0]["source"] == "futu_opend:HK.HSI2610", sent)
check("轉月前：從上一張最後交易日起的 K 線都送（舊合約期間不重疊）",
      [b["time_key"] for b in k5[0]["data"]][0] == "2026-10-28 15:55:00")
check("交易日 K（K_SESSION）用固定代號推送，被視窗切掉的 10-28 不送", kd and kd[0]["symbol"] == "HK.HSI_FRONT"
      and [x["time_key"][:10] for x in kd[0]["data"]] == ["2026-10-29"], kd)
check("不再送 Futu 日 K", not any(p["kline_type"] == "K_DAY" for p in sent))
check("期貨不送期權", all(p["options"] == [] for p in sent))
check("只訂 5 分 K", pusher.ctx.subs == [(("HK.HSI2610",), ("K_5M",))], pusher.ctx.subs)

p2 = push.FutuPusher(); p2.ctx = FakeCtx(LISTING)
run(p2, "2026-10-29", "01:00")
check("最後交易日凌晨 01:00 的夜市仍屬前一交易日 → 還是舊合約", p2.front["HK.HSI_FRONT"]["code"] == "HK.HSI2610", p2.front)

ok, sent = run(pusher, "2026-10-29")
k5 = [p for p in sent if p["kline_type"] == "K_5M"]
kd = [p for p in sent if p["kline_type"] == "K_SESSION"]
check("最後交易日當天：改送下月合約", ok and k5[0]["source"] == "futu_opend:HK.HSI2611", sent)
check("轉月後只送轉月日起的 5 分 K（不蓋掉 10-28 舊合約封存）",
      all(b["time_key"] >= "2026-10-29" for b in k5[0]["data"]) and len(k5[0]["data"]) == 2, k5[0]["data"])
check("轉月後日 K 也只送轉月日起", [b["time_key"][:10] for b in kd[0]["data"]] == ["2026-10-29"])
check("舊合約退訂", any(c == ("HK.HSI2610",) for c, _ in pusher.ctx.unsubs), pusher.ctx.unsubs)

print("=== [v8] 交易日曆 ===")
pc = push.FutuPusher(); pc.ctx = FakeCtx(LISTING, trading_days=["2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"])
ok, sent = run(pc, "2026-10-28")
cal = sent[0].get("trading_calendar") if sent else None
check("封包附上港股交易日曆（今天起 40 天）", cal and cal["from"] == "2026-10-28" and cal["to"] == "2026-12-07"
      and cal["days"] == ["2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"], cal)
calls = []
pc.ctx.request_trading_days = lambda **k: calls.append(1) or (ft.RET_OK, [])
run(pc, "2026-10-28")
check("同一天只查一次", calls == [])
pb = push.FutuPusher(); pb.ctx = FakeCtx(LISTING)
pb.ctx.request_trading_days = lambda **k: (ft.RET_ERROR, "no permission")
ok, sent = run(pb, "2026-10-28")
check("查不到日曆照樣推送、不附日曆", ok and sent and "trading_calendar" not in sent[0])

print("=== 即時視窗只有 60 根：交易日 K 用歷史 5 分 K ===")
class Win60(FakeCtx):
    def get_cur_kline(self, code, num, ktype):             # 即時視窗只剩下午，日市開盤已被切掉
        return ft.RET_OK, kline(code, ["2026-10-28 14:00:00", "2026-10-28 15:00:00"], 24000)

    def request_history_kline(self, code, start, end, ktype, max_count=None):
        self.hist_args = (start, end, ktype)
        return ft.RET_OK, kline(code, ["2026-10-27 23:00:00", "2026-10-28 09:20:00", "2026-10-28 14:00:00",
                                       "2026-10-28 15:00:00"], 24000), None
pw = push.FutuPusher(); pw.ctx = Win60(LISTING)
ok, sent = run(pw, "2026-10-28", "15:05")
kd = [p for p in sent if p["kline_type"] == "K_SESSION"]
check("交易日 K 由歷史 5 分 K 合成（日市開盤仍在）", ok and kd and [x["time_key"][:10] for x in kd[0]["data"]] == ["2026-10-28"], sent)
check("歷史範圍 = 前一天到後一天、5 分 K", pw.ctx.hist_args == ("2026-10-27", "2026-10-29", "K_5M"), pw.ctx.hist_args)
pw2 = push.FutuPusher(); pw2.ctx = Win60(LISTING)
pw2.ctx.request_history_kline = lambda *a, **k: (ft.RET_ERROR, "quota", None)
ok, sent = run(pw2, "2026-10-28", "15:05")
check("歷史拿不到 → 退回即時視窗（被切掉的一天不送）", ok and not any(p["kline_type"] == "K_SESSION" for p in sent), sent)

print("=== 上一張已下架：用交易日曆推轉月日 ===")
pusher = push.FutuPusher()
pusher.ctx = FakeCtx([x for x in LISTING if x[0] != "HK.HSI2610"],
                     trading_days=["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"])
ok, sent = run(pusher, "2026-10-30")
check("轉月日 = 上月倒數第二個交易日", pusher.front["HK.HSI_FRONT"]["start"] == "2026-10-29",
      pusher.front)
pusher = push.FutuPusher()
pusher.ctx = FakeCtx([x for x in LISTING if x[0] != "HK.HSI2610"], trading_days=[])
ok, sent = run(pusher, "2026-10-30")
check("交易日曆也拿不到 → 只送今天", pusher.front["HK.HSI_FRONT"]["start"] == "2026-10-30")

print("=== 沒有合適合約 ===")
pusher = push.FutuPusher()
pusher.ctx = FakeCtx([("HK.HSImain", "")])
ok, sent = run(pusher, "2026-10-03")
check("找不到合約 → 這一輪失敗、不推送", ok is False and sent == [])

print("=== [v7] 補一年歷史 ===")
from datetime import date as _date, timedelta as _td
WEEKDAYS = [(_date(2026, 7, 1) + _td(days=i)).isoformat() for i in range(0, 100)
            if (_date(2026, 7, 1) + _td(days=i)).weekday() < 5]


class HistCtx(FakeCtx):
    def request_history_kline(self, code, start, end, ktype, max_count=None):
        self.hist = getattr(self, "hist", []) + [code]
        if code == "HK.HSI2608":
            return ft.RET_ERROR, "no data for expired", None
        assert ktype == "K_60M", ktype
        base = {"HK.HSImain": 30000, "HK.HSI2609": 26000, "HK.HSI2610": 24000}[code]
        rows = []
        for d in WEEKDAYS:                                   # 每個交易日：日市、晚上夜市、翌日凌晨夜市各一根
            nxt = (_date.fromisoformat(d) + _td(days=1)).isoformat()
            for t, bump in ((f"{d} 10:15:00", 0), (f"{d} 18:15:00", 50), (f"{nxt} 01:15:00", 80)):
                if start <= t[:10] <= end and d <= "2026-10-02":
                    rows.append({"time_key": t, "open": base, "high": base + 5 + bump, "low": base - 5,
                                 "close": base + 1, "volume": 10})
        return ft.RET_OK, pd.DataFrame(rows), None


check("平日近似最後交易日", push.second_last_weekday(2026, 8) == "2026-08-28"
      and push.second_last_weekday(2026, 10) == "2026-10-29")
segs = push.backfill_segments("HSI", [(2026, 8), (2026, 9), (2026, 10)], push.second_last_weekday,
                              ("HK.HSI2610", "2026-10-29"))
check("每張合約管上一張最後交易日到自己最後交易日",
      segs == [("HK.HSI2608", "2026-07-30", "2026-08-28"), ("HK.HSI2609", "2026-08-28", "2026-09-29"),
               ("HK.HSI2610", "2026-09-29", "2026-10-29")], segs)

pusher = push.FutuPusher()
pusher.ctx = HistCtx(LISTING, trading_days=WEEKDAYS)
push.datetime = type("DT", (), {"now": staticmethod(Clock("2026-10-04").now),
                                "fromisoformat": staticmethod(datetime.fromisoformat)})
sent = []
pusher.post = lambda packet, quiet=False: sent.append(packet) or True
ok = pusher.backfill_front("HK.HSI_FRONT", 40)
rows = [(b["time_key"][:10], p["source"]) for p in sent for b in p["data"]]
dates = [d for d, _ in rows]
src = dict(rows)
check("回補成功、全部是交易日 K、固定代號", ok and sent and all(p["kline_type"] == "K_SESSION" and p["symbol"] == "HK.HSI_FRONT"
                                            for p in sent), len(sent))
check("日期不重複、由 40 天前到最新", len(dates) == len(set(dates)) and dates[0] == "2026-08-25"
      and dates[-1] == "2026-10-02", (dates[:2], dates[-2:]))
hi = {b["time_key"][:10]: b["high"] for p in sent for b in p["data"]}
check("交易日高位含翌日凌晨的夜市", hi["2026-09-29"] == 24000 + 85 and hi["2026-09-25"] == 26000 + 85, hi.get("2026-09-29"))
check("轉月邊界正確（最後交易日當天屬下一張）",
      src["2026-08-27"].endswith("HK.HSImain(代2608)") and src["2026-08-28"] == "futu_opend:HK.HSI2609"
      and src["2026-09-28"] == "futu_opend:HK.HSI2609" and src["2026-09-29"] == "futu_opend:HK.HSI2610", src)
check("過期合約拿不到 → 用主連代替該段", "HK.HSImain" in pusher.ctx.hist)
check("每包不超過 15 根、同一包只有一張合約", all(len(p["data"]) <= push.BACKFILL_CHUNK for p in sent))

print("=== [v9] 匯出日內 K 線 ===")
class IntraCtx(HistCtx):
    def request_history_kline(self, code, start, end, ktype, max_count=None):
        self.kt = ktype
        if code == "HK.HSI2608":
            return ft.RET_ERROR, "Unknown stock", None
        base = {"HK.HSImain": 30000, "HK.HSI2609": 26000, "HK.HSI2610": 24000}[code]
        rows = []
        for d in WEEKDAYS:
            if d > "2026-10-02":
                continue
            nxt = (_date.fromisoformat(d) + _td(days=1)).isoformat()
            for t, v in ((f"{d} 09:15:00", 0), (f"{d} 09:30:00", 5), (f"{d} 12:00:00", 5), (f"{d} 16:30:00", 5),
                         (f"{d} 23:00:00", 5), (f"{nxt} 03:00:00", 5)):
                if start <= t[:10] <= end:
                    rows.append({"time_key": t, "open": base, "high": base + 9, "low": base - 9, "close": base, "volume": v})
        return ft.RET_OK, pd.DataFrame(rows), None

pi = push.FutuPusher(); pi.ctx = IntraCtx(LISTING, trading_days=WEEKDAYS)
push.datetime = type("DT", (), {"now": staticmethod(Clock("2026-10-04").now),
                                "fromisoformat": staticmethod(datetime.fromisoformat)})
sent = []
pi.post = lambda packet, quiet=False: sent.append(packet) or True
ok = pi.export_intraday("HK.HSI_FRONT", 40, "K_15M")
bars = [(b["time_key"], p["source"]) for p in sent for b in p["data"]]
check("匯出成功、kline_type 是 K_15M、向 Futu 要 15 分 K", ok and all(p["kline_type"] == "K_15M" for p in sent) and pi.ctx.kt == "K_15M")
check("每包 ≤ 400 根", all(len(p["data"]) <= push.INTRADAY_CHUNK for p in sent))
check("成交量 0 的 K 線不送", not any(t.endswith("09:15:00") for t, _ in bars))
src = dict(bars)
check("轉月按交易日：09-29 凌晨 03:00 屬 09-28 交易日 → 2609；09-29 日市 → 2610",
      src["2026-09-29 03:00:00"] == "futu_opend:HK.HSI2609" and src["2026-09-29 09:30:00"] == "futu_opend:HK.HSI2610", 
      (src.get("2026-09-29 03:00:00"), src.get("2026-09-29 09:30:00")))
check("過期合約那段用主連", src["2026-08-27 12:00:00"].endswith("HK.HSImain(代2608)"))
check("40 天前的交易日之前不送", min(t for t, _ in bars) >= "2026-08-25")

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
