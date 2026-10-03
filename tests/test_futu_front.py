"""[v6] futu/push_to_gcp.py 的即月期貨：選合約、最後交易日轉月、轉月後不蓋舊封存。
用假的 futu 模組與假的 OpenD，不連網、不需裝 futu-api。"""
import importlib.util, sys, types
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---- 假的 futu 模組（repo 的 futu/ 資料夾會被當成命名空間套件，要先蓋掉）
ft = types.ModuleType("futu")
ft.RET_OK, ft.RET_ERROR = 0, -1
ft.KLType = types.SimpleNamespace(K_5M="K_5M", K_DAY="K_DAY")
ft.SubType = types.SimpleNamespace(K_5M="K_5M", K_DAY="K_DAY")
ft.Market = types.SimpleNamespace(HK="HK", US="US")
ft.SecurityType = types.SimpleNamespace(FUTURE="FUTURE", IDX="IDX")
ft.TradeDateMarket = types.SimpleNamespace(HK="HK")
sys.modules["futu"] = ft

spec = importlib.util.spec_from_file_location(
    "push_to_gcp", Path(__file__).resolve().parent.parent / "futu" / "push_to_gcp.py")
push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(push)

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
    def __init__(self, day):
        self.day = day

    def now(self, tz=None):
        return datetime.fromisoformat(f"{self.day} 09:30:00").replace(tzinfo=tz)


def run(pusher, day):
    push.datetime = type("DT", (), {"now": staticmethod(Clock(day).now),
                                    "fromisoformat": staticmethod(datetime.fromisoformat)})
    sent = []
    pusher.post = lambda packet, quiet=False: sent.append(packet) or True
    ok = pusher.run_front("HK.HSI_FRONT")
    return ok, sent


print("=== 推送（最後交易日 2026-10-29 轉月）===")
pusher = push.FutuPusher()
pusher.ctx = FakeCtx(LISTING)
ok, sent = run(pusher, "2026-10-28")
k5 = [p for p in sent if p["kline_type"] == "K_5M"]
kd = [p for p in sent if p["kline_type"] == "K_DAY"]
check("轉月前一天：送當月合約、固定代號", ok and k5 and k5[0]["symbol"] == "HK.HSI_FRONT"
      and k5[0]["source"] == "futu_opend:HK.HSI2610", sent)
check("轉月前：從上一張最後交易日起的 K 線都送（舊合約期間不重疊）",
      [b["time_key"] for b in k5[0]["data"]][0] == "2026-10-28 15:55:00")
check("日 K 也用固定代號推送", kd and kd[0]["symbol"] == "HK.HSI_FRONT" and len(kd[0]["data"]) == 3)
check("期貨不送期權", all(p["options"] == [] for p in sent))
check("訂閱 5 分 K 與日 K", (("HK.HSI2610",), ("K_5M",)) in pusher.ctx.subs
      and (("HK.HSI2610",), ("K_DAY",)) in pusher.ctx.subs)

ok, sent = run(pusher, "2026-10-29")
k5 = [p for p in sent if p["kline_type"] == "K_5M"]
kd = [p for p in sent if p["kline_type"] == "K_DAY"]
check("最後交易日當天：改送下月合約", ok and k5[0]["source"] == "futu_opend:HK.HSI2611", sent)
check("轉月後只送轉月日起的 5 分 K（不蓋掉 10-28 舊合約封存）",
      all(b["time_key"] >= "2026-10-29" for b in k5[0]["data"]) and len(k5[0]["data"]) == 2, k5[0]["data"])
check("轉月後日 K 也只送轉月日起", [b["time_key"][:10] for b in kd[0]["data"]] == ["2026-10-29"])
check("舊合約退訂", any(c == ("HK.HSI2610",) for c, _ in pusher.ctx.unsubs), pusher.ctx.unsubs)

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

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
