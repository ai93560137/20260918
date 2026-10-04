"""[R101] 今日／本週／本月高低位是否已出現：A 耗盡回落、B 機率法、C 時間點，通知紀錄與報告。"""
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

# ↑ 與 test_futu_peak.py 相同的假 GCS。
# [R116] 📒 紙上交易：蛇蟠陣通道反手、🅱️／🅰️ 訊號都亮後跟蛇入市、止蝕／止賺／蛇反手離場、通知與頁面。
# [R118] 波幅開閘：R̂ ÷ 250 日中位 ≥ 1.2 → 開閘日入市 2 張，固定 1 張與開閘雙倍兩條並記；預測、報告、通知、頁面顯示開閘與否。
import random
from datetime import date, datetime, timedelta, timezone

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")

client = main.app.test_client()
random.seed(11)
SYM = "HK.HSI_FRONT"
UTC = timezone.utc


def sessions(n, end="2026-10-02"):
    days, d = [], date.fromisoformat(end)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    out, c = [], 24000.0
    for d in reversed(days):
        rng = abs(random.gauss(420, 120)) + 60
        lo = c - rng * random.random()
        out.append({"time_key": f"{d} 00:00:00", "open": c, "high": round(lo + rng), "low": round(lo),
                    "close": round(lo + rng * random.random()), "volume": 1, "source": "futu_opend:HK.HSImain"})
        c = out[-1]["close"]
    return out


def put(name, obj):
    FAKE[name] = (json.dumps(obj, ensure_ascii=False), FAKE.get(name, (None, 0))[1] + 1)


def hk(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=8))).astimezone(UTC)


def bar(t, o, h, l, c, v=10):
    return {"time_key": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


def state():
    return json.loads(FAKE[main.futu_paper_file(SYM)][0])


def arch(day):
    return main.archive_blob_name("futu_k_5m", SYM, day)


def quiet_session(day, hi=24600, lo=24300, nhi=24550, nlo=24350, day_hi=None, day_lo=None):
    """一個交易日的 5 分 K：日市 4 根（屬當天蛇日）＋夜市 2 根（屬下一個蛇日）。"""
    dh, dl = day_hi or hi, day_lo or lo
    return [bar(f"{day} 09:20:00", 24450, dh, dl, 24400), bar(f"{day} 11:00:00", 24400, 24480, 24380, 24420),
            bar(f"{day} 14:00:00", 24420, 24500, 24390, 24450), bar(f"{day} 16:30:00", 24450, 24470, 24400, 24440),
            bar(f"{day} 17:20:00", 24440, nhi, nlo, 24450), bar(f"{day} 23:00:00", 24450, 24500, 24400, 24480)]


print("\n=== 純函數：離場規則與統計 ===")
tr = {"side": 1, "stop": 100.0, "target": 130.0, "rr": 3.0}
check("開市已低過止蝕 → 跳空止蝕", main._paper_exit(tr, bar("t", 95, 99, 90, 92), []) == (95, "止蝕（跳空）"))
check("開市已過目標 → 開市價止賺", main._paper_exit(tr, bar("t", 131, 135, 130, 133), []) == (131, "3R 止賺"))
check("K 線內碰止蝕", main._paper_exit(tr, bar("t", 110, 112, 99, 105), []) == (100.0, "止蝕"))
check("K 線內碰目標", main._paper_exit(tr, bar("t", 110, 131, 108, 125), []) == (130.0, "3R 止賺"))
check("蛇反手（做多時反手做空）→ 反手價平倉", main._paper_exit(tr, bar("t", 110, 112, 105, 108), [(-1, 107.0, None)]) == (107.0, "蛇反手"))
check("同根碰止蝕又蛇反手 → 取較差的價", main._paper_exit(tr, bar("t", 110, 112, 99, 108), [(-1, 107.0, None)]) == (100.0, "止蝕"))
check("同方向的反手不理", main._paper_exit(tr, bar("t", 110, 112, 105, 108), [(1, 107.0, None)]) is None)
s = main._paper_stats([{"net": 100, "r_multiple": 1.0}, {"net": -50, "r_multiple": -0.5}, {"net": -50, "r_multiple": -0.5}, {"net": 200, "r_multiple": 2.0}])
check("統計：4 筆、勝率 50%、每筆 +50、RRR 3、回撤 100、R +0.5", s["n"] == 4 and s["win"] == 0.5 and s["mean"] == 50 and s["rrr"] == 3.0
      and s["dd"] == 100 and s["R"] == 0.5, s)
check("沒交易 → n 0", main._paper_stats([]) == {"n": 0})
s = main._paper_stats([{"net": 100, "lots": 2, "r_multiple": 1.0}, {"net": -50, "r_multiple": -0.5}, {"net": -50, "lots": 1, "r_multiple": -0.5}])
check("[R118] 統計兩條並記：固定 1 張 0、開閘雙倍 +100、開閘日 1 筆 +100、其餘 −100、雙倍回撤 100", s["total"] == 0 and s["total_tilt"] == 100
      and s["gate_n"] == 1 and s["gate_total"] == 100 and s["rest_total"] == -100 and s["dd"] == 100 and s["dd_tilt"] == 100, s)
check("[R118] 張數：開閘 2 張、未開閘 1 張、沒指標 1 張", main._paper_lots({"gate_open": True, "gate_ratio": 1.3}) == (2, 1.3)
      and main._paper_lots({"gate_open": False, "gate_ratio": 0.9}) == (1, 0.9) and main._paper_lots(None) == (1, None))
check("[R118] 開閘文字", "⚡ 今日開閘" in main._paper_gate_text({"gate_open": True, "gate_ratio": 1.3}) and "2 張" in main._paper_gate_text({"gate_open": True, "gate_ratio": 1.3})
      and "未開閘" in main._paper_gate_text({"gate_open": False, "gate_ratio": 0.9}) and "未有" in main._paper_gate_text({}))
check("蛇日：日市屬當天、夜市屬下一個", main._paper_phase(bar("2026-10-05 16:30:00", 1, 1, 1, 1), "2026-10-05") == "day"
      and main._paper_phase(bar("2026-10-05 17:20:00", 1, 1, 1, 1), "2026-10-05") == "night"
      and main._paper_phase(bar("2026-10-06 02:00:00", 1, 1, 1, 1), "2026-10-05") == "night")

print("\n=== 開市前預測多記九成日範圍邊 ===")
FAKE.clear()
put(main.futu_daily_file(SYM), sessions(300))
rows = main.futu_series_rows(SYM)
fc = main.futu_day_forecast(rows, "2026-10-05")
check("high_edge95 ≥ high_hi、low_edge95 ≤ low_lo", fc["high_edge95"] >= fc["high_hi"] and fc["low_edge95"] <= fc["low_lo"], fc)
check("[R118] 預測多記 250 日中位、R̂ 比值、開閘", fc.get("rhat_med250", 0) > 0 and abs(fc["gate_ratio"] - fc["range"] / fc["rhat_med250"]) < 0.01
      and fc["gate_open"] == (fc["range"] >= main.PAPER_GATE_TH * fc["rhat_med250"]) and isinstance(fc["gate_open"], bool),
      {k: fc.get(k) for k in ("range", "rhat_med250", "gate_ratio", "gate_open")})
fc_short = main.futu_day_forecast(rows[-80:], "2026-10-05")
check("[R118] 歷史預測不足 60 天 → 沒有開閘指標", fc_short and "gate_ratio" not in fc_short, fc_short and fc_short.keys())
txt = main.futu_preopen_text(fc, "2026-10-05", "HSI2610", None, [])
check("[R118] 開市前預測文字有開閘一行", "波幅開閘：" in txt and ("今日開閘" in txt or "今日未開閘" in txt) and "250 日 R̂ 中位" in txt, txt)
check("[R118] 沒指標時預測文字不出開閘行", "波幅開閘" not in main.futu_preopen_text(fc_short, "2026-10-05", "", None, []))

print("\n=== 第一次啟動：用之前的交易日算出蛇的持倉（啟動期不記交易、不發通知） ===")
put(main.FUTU_CALENDAR_FILE, {"from": "2026-10-05", "to": "2026-11-13", "days": ["2026-10-05", "2026-10-06", "2026-10-07"]})
boot_days = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]
for d in boot_days:
    put(arch(d), quiet_session(d, day_hi=24650 if d == "2026-10-01" else None,         # 10-01 日市升破 24600 → 蛇做多
                               day_lo=24400 if d >= "2026-10-01" else None))            # 之後日市不再碰下軌 24,300
# 09-25 只有 15 分 K 封存（5 分 K 推送還沒開始）
put(main.archive_blob_name("futu_k_15m", SYM, "2026-09-25"), quiet_session("2026-09-25"))
check("啟動期 5 分 K 不夠 → 用 15 分 K 封存", len(main._paper_session_bars(SYM, "2026-09-25", True)) == 6)
check("非啟動期不用 15 分 K", main._paper_session_bars(SYM, "2026-09-25", False) == [])
put(arch("2026-10-05"), [bar("2026-10-05 09:20:00", 24450, 24500, 24400, 24480)])
check("還沒狀態 → 報告 empty、頁面顯示等待", main.futu_paper_report(SYM)["status"] == "empty"
      and "等第一包" in client.get("/?view=futu_range").get_data(as_text=True))
main.futu_paper_update(SYM, now=hk("2026-10-05 09:25"))
st = state()
check("狀態建立、處理到 10-05 09:20", st["version"] == main.PAPER_VERSION and st["last_bar"] == "2026-10-05 09:20:00" and st["last_session"] == "2026-10-05", st.get("last_bar"))
check("蛇：10-01 升破通道 → 做多 24,600（啟動期入市）", st["snake"]["pos"] == 1 and st["snake"]["px"] == 24600 and st["snake"]["boot"] is True, st["snake"])
check("通道 = 前 3 個蛇日：上 24,650、下 24,300", st["snake"]["upper"] == 24650 and st["snake"]["lower"] == 24300 and len(st["snake"]["hist"]) == 3, st["snake"])
check("啟動期不記交易、不發通知", st["trades"] == [] and st["notices"] == [])
check("今日還沒有九成範圍邊（沒有紀錄、新版即時算）→ 有 levels", (st["day"].get("levels") or {}).get("high_edge95") is not None, st["day"])

print("\n=== 今日：蛇反手做空、🅱️ 兩邊都亮 → 下一根開市跟蛇沽、3R 止賺 ===")
put(main.futu_forecast_file(SYM), [{"date": "2026-10-05", "range": 500, "lo": 300, "hi": 800, "ref_close": 24440,
                                    "high": 24650, "high_lo": 24550, "high_hi": 24680, "low": 24250, "low_lo": 24000, "low_hi": 24350,
                                    "high_edge95": 24700, "low_edge95": 23900, "made_utc": "x",
                                    "rhat_med250": 400, "gate_ratio": 1.25, "gate_open": True}])        # [R118] 今日開閘
put(main.futu_paper_file(SYM), {**st, "day": {"date": "2026-10-05", "levels": None, "done": []}})   # 模擬沒算到 → 這包補上紀錄的值
today = [bar("2026-10-05 09:20:00", 24450, 24500, 24400, 24480),
         bar("2026-10-05 09:40:00", 24400, 24450, 24250, 24300),       # 跌穿 24,300 → 蛇反手做空 24,300
         bar("2026-10-05 10:00:00", 24300, 24350, 24280, 24320),       # B 高位已現 asof
         bar("2026-10-05 11:00:00", 24320, 24330, 24200, 24220)]       # B 低位已現 asof
put(arch("2026-10-05"), today)
put(main.futu_signal_file(SYM), [{"id": "day:2026-10-05:high:B", "asof": "2026-10-05 10:00:00", "sent": False, "text": "高位 B", "ext": 24500},
                                 {"id": "day:2026-10-05:low:B", "asof": "2026-10-05 11:00:00", "sent": True, "text": "低位 B", "ext": 24200}])
main.futu_paper_update(SYM, now=hk("2026-10-05 11:05"))
st = state()
check("補上紀錄的九成邊 24,700／23,900", st["day"]["levels"]["high_edge95"] == 24700 and st["day"]["levels"]["low_edge95"] == 23900, st["day"])
check("[R118] 紀錄的開閘指標也補上", st["day"]["levels"]["gate_open"] is True and st["day"]["levels"]["gate_ratio"] == 1.25, st["day"])
check("蛇反手做空 24,300；多倉平掉 −303（啟動期入市那筆）", st["snake"]["pos"] == -1 and st["snake"]["px"] == 24300 and len(st["trades"]) == 1
      and st["trades"][0]["net"] == -303 and st["trades"][0]["boot"] is True and st["trades"][0]["exit_reason"] == "蛇反手", st["trades"])
check("[R118] 啟動期入的多倉 1 張；開閘日反手的新空倉 2 張", st["trades"][0]["lots"] == 1 and st["snake"]["lots"] == 2 and st["snake"]["gate"] == 1.25, st["snake"])
check("反手有通知", len(st["notices"]) == 1 and "反手做空 24,300" in st["notices"][0]["text"] and st["notices"][0]["id"].startswith("paper:SNAKE:flip:"), st["notices"])
check("[R118] 反手通知寫 ×2 張與開閘", "×2 張" in st["notices"][0]["text"] and "⚡ 今日開閘" in st["notices"][0]["text"], st["notices"][0]["text"])
check("兩邊 11:00 才都亮 → 還沒入市", not st["open"])
put(arch("2026-10-05"), today + [bar("2026-10-05 12:00:00", 24220, 24260, 24150, 24180)])
main.futu_paper_update(SYM, now=hk("2026-10-05 12:05"))
st = state()
tr = st["open"].get("B_S_R3")
check("12:00 開市跟蛇沽 24,220；止蝕 24,700；目標 24,220 − 3×480 = 22,780", tr and tr["side"] == -1 and tr["entry_price"] == 24220
      and tr["stop"] == 24700 and tr["target"] == 22780 and tr["snake_at_entry"] == -1, tr)
check("入市通知", any(e["kind"] == "entry" and "做空 24,220" in e["text"] and "3R" in e["text"] for e in st["notices"]), [e["text"] for e in st["notices"]])
check("[R118] 開閘日入市 2 張、通知寫明", tr["lots"] == 2 and tr["gate"] == 1.25
      and any(e["kind"] == "entry" and "×2 張" in e["text"] and "今日開閘" in e["text"] for e in st["notices"]), tr)
check("🅰️ 沒訊號 → 空手", "A_S_R2" not in st["open"])
rep = client.get("/?view=futu_range&report=signals").get_json()
ids = {s["id"] for s in rep["signals"]}
check("report=signals 同時給高低位通知與紙上交易通知", "day:2026-10-05:high:B" in ids and any(i.startswith("paper:") for i in ids)
      and "day:2026-10-05:low:B" not in ids, ids)
pid = next(i for i in ids if i.startswith("paper:B_S_R3:entry"))
client.get(f"/?view=futu_range&report=signals&ack={pid},day:2026-10-05:high:B")
rep2 = client.get("/?view=futu_range&report=signals").get_json()
check("ack 兩種都標記已發", not {pid, "day:2026-10-05:high:B"} & {s["id"] for s in rep2["signals"]}
      and next(e for e in state()["notices"] if e["id"] == pid)["sent"] is True)
put(arch("2026-10-05"), today + [bar("2026-10-05 12:00:00", 24220, 24260, 24150, 24180), bar("2026-10-05 14:00:00", 24180, 24200, 22700, 22900)])
main.futu_paper_update(SYM, now=hk("2026-10-05 14:05"))
st = state()
t3 = [t for t in st["trades"] if t["strat"] == "B_S_R3"]
check("14:00 碰 22,780 → 3R 止賺 +1,437（+2.99R）", len(t3) == 1 and t3[0]["exit_price"] == 22780 and t3[0]["net"] == 1437
      and abs(t3[0]["r_multiple"] - 2.994) < 0.01 and t3[0]["exit_reason"] == "3R 止賺", t3)
check("平倉後空手、今日不再入", "B_S_R3" not in st["open"] and "B_S_R3" in st["day"]["done"])
check("出場通知含累計", any(e["kind"] == "exit" and "+1,437" in e["text"] and "累計 1 筆" in e["text"] for e in st["notices"]))
check("[R118] 出場紀錄 2 張、通知寫雙倍 +2,874", t3[0]["lots"] == 2
      and any(e["kind"] == "exit" and "×2 張 = +2,874" in e["text"] and "開閘雙倍 +2,874" in e["text"] for e in st["notices"]),
      [e["text"] for e in st["notices"] if e["kind"] == "exit"])
n_before = (len(st["notices"]), len(st["trades"]))
main.futu_paper_update(SYM, now=hk("2026-10-05 14:10"))
check("同樣的 K 線再跑一次 → 不變（冪等）", (len(state()["notices"]), len(state()["trades"])) == n_before)

print("\n=== 🅰️ 入市後蛇反手 → 跟著平倉 ===")
sig = json.loads(FAKE[main.futu_signal_file(SYM)][0])
sig += [{"id": "day:2026-10-05:high:A", "asof": "2026-10-05 12:00:00", "sent": True, "text": "", "ext": 24500},
        {"id": "day:2026-10-05:low:A", "asof": "2026-10-05 14:00:00", "sent": True, "text": "", "ext": 22700}]
put(main.futu_signal_file(SYM), sig)
bars2 = today + [bar("2026-10-05 12:00:00", 24220, 24260, 24150, 24180), bar("2026-10-05 14:00:00", 24180, 24200, 22700, 22900),
                 bar("2026-10-05 16:30:00", 24180, 24200, 24100, 24150)]
put(arch("2026-10-05"), bars2)
main.futu_paper_update(SYM, now=hk("2026-10-05 16:35"))
st = state()
tr = st["open"].get("A_S_R2")
check("16:30 開市跟蛇沽 24,180；止蝕 24,700；目標 24,180 − 2×520 = 23,140", tr and tr["side"] == -1 and tr["entry_price"] == 24180
      and tr["target"] == 23140, tr)
put(arch("2026-10-05"), bars2 + [bar("2026-10-05 17:20:00", 24200, 24680, 24150, 24600)])    # 夜市升破 24,650 → 蛇反手做多
main.futu_paper_update(SYM, now=hk("2026-10-05 17:25"))
st = state()
ta = [t for t in st["trades"] if t["strat"] == "A_S_R2"]
check("日市收完換蛇日：通道仍 24,650／改 22,700", st["snake"]["upper"] == 24650 and st["snake"]["lower"] == 22700, st["snake"])
check("蛇反手做多 24,650；🅰️ 跟著平倉 −473（蛇反手）", st["snake"]["pos"] == 1 and st["snake"]["px"] == 24650 and len(ta) == 1
      and ta[0]["exit_reason"] == "蛇反手" and ta[0]["exit_price"] == 24650 and ta[0]["net"] == -473, ta)
sn_tr = [t for t in st["trades"] if t["strat"] == "SNAKE"]
check("蛇第二筆：空 24,300 → 24,650 = −353", len(sn_tr) == 2 and sn_tr[1]["net"] == -353, sn_tr)

print("\n=== 報告、頁面、四次報告的一行 ===")
rep = client.get("/?view=futu_range&report=paper").get_json()
check("report=paper：三條統計、逐筆、持倉", rep["status"] == "ok" and rep["stats"]["SNAKE"]["n"] == 2 and rep["stats"]["B_S_R3"]["total"] == 1437
      and rep["stats"]["A_S_R2"]["n"] == 1 and len(rep["trades"]) == 4 and rep["snake"]["pos"] == 1, rep.get("stats"))
check("[R118] 兩條帳：蛇 固定 −656／雙倍 −1,009（第二筆 2 張）；🅱️ +1,437／+2,874；🅰️ −473／−946",
      rep["stats"]["SNAKE"]["total"] == -656 and rep["stats"]["SNAKE"]["total_tilt"] == -1009 and rep["stats"]["SNAKE"]["gate_n"] == 1
      and rep["stats"]["B_S_R3"]["total_tilt"] == 2874 and rep["stats"]["A_S_R2"]["total_tilt"] == -946, rep["stats"])
check("[R118] report=paper 給今日開閘", rep["gate"]["gate_open"] is True and rep["gate"]["gate_ratio"] == 1.25 and rep["gate"]["threshold"] == 1.2
      and "今日開閘" in rep["gate"]["text"], rep["gate"])
page = client.get("/?view=futu_range").get_data(as_text=True)
check("頁面有紙上交易區、三條策略、最近交易", all(x in page for x in ("📒 紙上交易", "🐍 蛇蟠陣", "🅱️＋跟蛇＋3R", "🅰️＋跟蛇＋2R", "3R 止賺", "最新處理到 10-05 17:20")))
check("[R118] 頁面顯示今日開閘、兩條帳、張數欄", all(x in page for x in ("⚡ 今日開閘（R̂ ÷ 250 日中位 1.25 ≥ 1.2）→ 2 張", "開閘雙倍累計", "累計（固定 1 張）",
                                                                 "+2,874", "<th>張</th>", "⚡2")), [x for x in ("⚡ 今日開閘", "開閘雙倍累計", "+2,874", "⚡2") if x not in page])
lines = main.futu_paper_lines(SYM, 24700.0)
check("報告一行：三條持倉與累計", len(lines) == 1 and "🐍 蛇蟠陣 做多 24,650" in lines[0] and "浮動 +50" in lines[0] and "🅱️＋跟蛇＋3R 空手；累計 1 筆 +1,437" in lines[0], lines)
check("[R118] 報告一行有今日開閘、張數、雙倍累計", "⚡ 今日開閘" in lines[0] and "做多 24,650×2 張" in lines[0] and "（開閘雙倍 +2,874）" in lines[0], lines)
rev = main.futu_report(SYM, "close", now=hk("2026-10-05 16:37"))
check("16:30 檢討含紙上交易一行", rev["status"] == "ok" and "📒 紙上交易" in rev["text"], rev.get("text", "")[-200:])

print("\n=== 新交易日：今日紀錄重設、舊倉續持 ===")
put(arch("2026-10-06"), [bar("2026-10-06 09:20:00", 24600, 24620, 24550, 24580)])
main.futu_paper_update(SYM, now=hk("2026-10-06 09:25"))
st = state()
check("換日：day.date 10-06、done 清空、蛇仍做多", st["day"]["date"] == "2026-10-06" and st["day"]["done"] == [] and st["snake"]["pos"] == 1
      and st["last_session"] == "2026-10-06", st["day"])
check("空手策略沒有新訊號 → 沒入市", not st["open"])
lv6 = st["day"]["levels"]
check("[R118] 新交易日沒有紀錄 → 即時算的 levels 含開閘指標", lv6 and "gate_ratio" in lv6 and lv6.get("rhat_med250"), lv6)
# R118 之前的狀態：今日 levels 沒有開閘欄 → 下一包補上（舊 edge95 由即時算的取代）
put(main.futu_paper_file(SYM), {**st, "day": {"date": "2026-10-06", "levels": {"high_edge95": 1, "low_edge95": 2}, "done": []}})
put(arch("2026-10-06"), [bar("2026-10-06 09:20:00", 24600, 24620, 24550, 24580), bar("2026-10-06 09:25:00", 24580, 24600, 24560, 24590)])
main.futu_paper_update(SYM, now=hk("2026-10-06 09:30"))
lv6b = state()["day"]["levels"]
check("[R118] 舊版 levels 沒有開閘欄 → 補上", "gate_ratio" in lv6b and lv6b["high_edge95"] == lv6["high_edge95"], lv6b)

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
