"""上線前最後檢測：GCP 會不會下出跟 TradingView 一樣的單。

三層：
  ① 訊號層 —— main.py 的 JinnangSession vs 已對過 TradingView 的參考實作
  ② 封包層 —— GCP 實際會送給券商的 JSON
  ③ 期望值 —— 用 TradingView 全期成交明細，不是用我的 Python
"""
import io, json, math, os, sys, types

os.environ.setdefault("GCP_SECRET_TOKEN", "tok")
sys.path.insert(0, "/home/user/20260918")
import functions_framework, google, google.cloud
FAKE = {}
class _B:
    def __init__(s, n): s.name = n; s.generation = FAKE.get(n, (None, 0))[1]
    def exists(s): return s.name in FAKE
    def download_as_text(s, *a, **k):
        if s.name not in FAKE: raise KeyError(s.name)
        return FAKE[s.name][0]
    def download_as_bytes(s, *a, **k): return s.download_as_text().encode()
    def upload_from_string(s, d, *a, **k):
        g = FAKE.get(s.name, (None, 0))[1] + 1; FAKE[s.name] = (d, g); s.generation = g
    def reload(s): s.generation = FAKE.get(s.name, (None, 0))[1]
class _Bk:
    def blob(s, n): return _B(n)
    def get_blob(s, n): return _B(n) if n in FAKE else None
class _C:
    def __init__(s, *a, **k): pass
    def bucket(s, n): return _Bk()
m = types.ModuleType("google.cloud.storage"); m.Client = _C
sys.modules["google.cloud.storage"] = m; google.cloud.storage = m
g = types.ModuleType("google.genai"); g.Client = lambda *a, **k: None; g.types = types.SimpleNamespace()
sys.modules["google.genai"] = g
e = types.ModuleType("google.api_core.exceptions")
class _P(Exception): pass
e.PreconditionFailed = _P; e.NotFound = KeyError
ac = types.ModuleType("google.api_core"); ac.exceptions = e
sys.modules["google.api_core"] = ac; sys.modules["google.api_core.exceptions"] = e

import main
main.macro_news_session.status = lambda now=None: {"locked": False, "known": True,
                                                   "reason": "test", "events": [], "warning": None}
main.ai_review_session.review = lambda meta: (True, "test")
sys.path.insert(0, "/home/user/20260918/tradingview")
import numpy as np, pandas as pd
from jinnang_v4_reconcile import load_m15, trades, BASE_CSV

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name}   {extra}")

CSV = '/root/.claude/uploads/13c02be0-89e0-5e8c-9f33-0cd3bcee9388/3564dfe6-XAUUSD_M15_MAX.csv'
TV  = '/root/.claude/uploads/13c02be0-89e0-5e8c-9f33-0cd3bcee9388/2539b0f0-___v4_VANTAGE_XAUUSD_2026-09-20_1.csv'

print("\n" + "="*68)
print("① 訊號層：GCP 的判定 vs 已對過 TradingView 的參考實作")
print("="*68)
df = load_m15(CSV)
ref = trades(df)
bars = [dict(time=int(t.timestamp()), open=r.Open, high=r.High, low=r.Low, close=r.Close)
        for t, r in df.iterrows()]
WIN = main.MTFDynamicLevelsSession.history_max
need = max(main.JN_LEN_TREND, main.JN_LEN_RANGE, main.JN_ATR_LEN + 1, main.JN_MIN_BARS)
pos = {t: i for i, t in enumerate(df.index)}

# 全部進場根都測；另外隨機抽 3,000 根非進場根，確認不會亂開單
entry_idx = [pos[t] for t in ref.entry_time if pos[t] >= need]
rng = np.random.default_rng(7)
pool = np.array([i for i in range(need, len(bars)) if i not in set(entry_idx)])
sample_idx = sorted(rng.choice(pool, size=min(3000, len(pool)), replace=False).tolist())

def sig(i):
    return main.JinnangSession.evaluate(bars[max(0, i + 1 - WIN):i + 1]).get("signal")

hit = sum(1 for i in entry_idx if sig(i) == "BUY")
false_pos = sum(1 for i in sample_idx if sig(i) == "BUY")
print(f"  參考實作全期 {len(ref)} 筆進場（暖機期之後 {len(entry_idx)} 筆可比）")
check(f"該開的都開了：{hit}/{len(entry_idx)}", hit == len(entry_idx), f"漏 {len(entry_idx)-hit} 筆")
check(f"不該開的沒開：抽查 {len(sample_idx)} 根非進場根，誤開 {false_pos} 次",
      false_pos == 0, f"誤開 {false_pos}")

print("\n" + "="*68)
print("② 封包層：GCP 實際會送給券商的 JSON")
print("="*68)
FAKE.clear()
main.GoldIndicatorSession.is_gold_market_open = staticmethod(lambda now=None: True)
# 用一個真實的進場點，把它前面 200 根 M15 灌進 GCP 的歷史
i0 = entry_idx[-1]
hist = bars[max(0, i0 + 1 - WIN):i0 + 1]
forming = dict(hist[-1]); forming["time"] += 900          # 再加一根「正在形成」的
main.gcs_write_text(main.M15_HISTORY_FILE, json.dumps(hist + [forming]))
px = hist[-1]["close"]
atr = main.JinnangSession._atr_series(hist, main.JN_ATR_LEN)[-1]
payload = {"action": "check_gate", "token": "tok", "equity": 20000.0, "balance": 20000.0,
           "daily_pnl": 0.0, "net_lots": 0.0, "buy_lots": 0.0, "sell_lots": 0.0,
           "currency": "HKD",
           "m15_ohlc": {"time": forming["time"], "open": forming["open"], "high": forming["high"],
                        "low": forming["low"], "close": forming["close"], "atr_m15": atr}}
main.apply_risk_to_gate(payload, False)
cand = main.jinnang_entry(payload, main.now_ts(), frozenset(), main.read_order_params()[0])
check("真實進場點會產生候選單", isinstance(cand, dict), cand)
if isinstance(cand, dict):
    order = main.build_order(cand, main.read_order_params()[0])
    order["api_key"] = main.mask_secret(order["api_key"])
    print("\n  GCP 會送出的封包：")
    for k, v in order.items(): print(f"    {k:<24} {v}")
    tpf = main.distance_fields(main.read_order_params()[0])["tp"]
    slf = main.distance_fields(main.read_order_params()[0])["sl"]
    print()
    check("方向 = BUY（TradingView v4 只做多）", order["action"] == "BUY", order["action"])
    check("手數 = 0.01（= 1 盎司 = TradingView 的 1 數量）",
          float(order["size"]) == 0.01, order["size"])
    check("沒有 TP 欄位（出場交給 EA 定時）", tpf not in order, list(order))
    check("SL = ATR × 8 災難停損", abs(float(order[slf]) - max(main.MIN_SL_DISTANCE,
          round(atr * main.JN_DISASTER_SL_ATR, 2))) < 0.01, order[slf])
    check("商品 = 送單參數頁設定的代號", order["symbol"] == main.read_order_params()[0]["symbol"],
          order["symbol"])

print("\n  ── 兩邊的規格對照 ──")
rows = [("方向", "只做多", "LONG_ONLY=1 ＋ 錦囊只出 BUY"),
        ("每單大小", "1 數量 = 1 盎司", f"{main.ORDER_SIZE} 手 × {main.CONTRACT_SIZE:.0f} oz = 1 盎司"),
        ("進場", "確認根收盤後下一根", "M15 收盤觸發 → EA 收到 200 後下單"),
        ("持倉", "10 根 M15 = 150 分鐘", f"EA InpHoldMinutes；GCP JN_HOLD_BARS={main.JN_HOLD_BARS}"),
        ("價格停損", "無", f"只掛 ATR × {main.JN_DISASTER_SL_ATR:g} 災難停損"),
        ("止盈", "無（時間到就出）", "不送 TP 欄位"),
        ("加碼", "pyramiding = 0", "有持倉就不再進場"),
        ("波動門檻", "ATR(14)÷價 ≥ 0.10%", f"VOL_FLOOR_ATR_PCT={main.VOL_FLOOR_ATR_PCT:g}%")]
print(f"  {'項目':<12}{'TradingView v4':<24}{'GCP'}")
for a, b, c in rows: print(f"  {a:<12}{b:<24}{c}")

print("\n" + "="*68)
print("③ 期望值：用 TradingView 全期成交明細（不是我的 Python）")
print("="*68)
d = pd.read_csv(TV); d.columns = [c.strip('﻿') for c in d.columns]
en = d[d['類型'].str.contains('進場')].copy()
en['t'] = pd.to_datetime(en['日期和時間']); en['pnl'] = en['淨損益 HKD'].astype(float)
cut = pd.Timestamp('2022-08-03')
def stat(x, lab, yrs):
    h = x.pnl; t = h.mean()/(h.std(ddof=1)/math.sqrt(len(h)))
    sv = np.sort(h.values)[::-1]; k = int(len(h)*0.05)
    print(f"  {lab:<24}{len(x):>4} 筆  每筆 HK${h.mean():>+7.2f}  總 HK${h.sum():>+8,.0f}"
          f"  t={t:>+5.2f}  年化 {h.sum()/20000/yrs*100:>+6.2f}%  去最賺5% {sv[k:].sum():>+8,.0f}")
    return h.mean()
full = stat(en, "全期 2018-04→2026-09", 8.46)
out  = stat(en[en.t < cut], "樣本外 2018-04→2022-08", 4.33)
ins  = stat(en[en.t >= cut], "樣本內 2022-08→2026-09", 4.13)
print()
check(f"全期期望值為正（+HK${full:.2f}/筆）", full > 0, full)
check(f"⚠️ 樣本外期望值【為負】（HK${out:.2f}/筆）—— 這是事實，不是測試失敗",
      out < 0, "如果這行變成 ❌，代表樣本外轉正了，是好消息")

print("\n" + "="*68)
print(f"通過 {OK} / 失敗 {FAIL}")
print("="*68)
sys.exit(1 if FAIL else 0)
