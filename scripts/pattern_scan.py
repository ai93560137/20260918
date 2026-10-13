"""pattern_scan.py — 每日早盤形態掃描：期貨＋外匯日線，揀出「今日邊隻可以做」。

平日 07:45 HKT，GitHub Actions `pattern_scan.yml` 跑（雲端工作階段連唔到 Yahoo，所以喺 Actions 抓 yfinance）。
只出資訊、唔落單。

流程
  1. 抓每隻產品約 2 年日線，只用「已收市」嘅 K 線（日期 < 今日香港日期）。
  2. 喺最後一支 K 線偵測形態：吞噬、Pin bar、母子／NR7 收窄、雙頂／雙底、頭肩、20 日區間突破、旗形、三角收斂。
  3. 每個形態畫好入場（突破掛單或開市價）、止蝕（最少 0.5 ATR）、第一目標；出場用移動止蝕（最高收市 − 3 ATR）。
  4. 🟢 可做＝v2 優勢組合：金屬（金、銀、銅）、上升趨勢、收市喺 200 日線上、做好倉「區間上破」或「牛旗」。
     其他形態照評分（形態 + 順勢 + 位置 + R:R + 波動 + 止蝕闊度）≥ 3 分列 🟡 觀察——歷史上冇優勢，只供參考。
     點解咁揀：見 research/pattern_scan/RESEARCH.md（22 隻產品、1995–2026，≤2016 揀、2017+ 驗）。
  5. 寫訊號帳本 research/pattern_scan/signals.csv，並用之後嘅 K 線為舊訊號計成績（前向評分）。
  6. 出 Telegram 一則 + research/pattern_scan/<日>.md、latest.md。

## 預先登記（v1 2026-10-13；v2 2026-10-14 改出場同 🟢 定義，前向成績由 v2 重新累積）

* **入場**：`stop` 類＝之後 3 支 K 線內觸及入場價先算成交（好倉 High ≥ 入場、淡倉 Low ≤ 入場），開市跳空過咗就用開市價；
  3 支內未觸及＝過期。`market` 類＝下一支 K 線開市價。
* **出場**：移動止蝕＝成交後最高收市 − 3 ATR（淡倉相反），每日收市後更新、只收緊唔放鬆；盤中掂到就出，
  跳空穿過用開市價。最多持有 60 支 K 線，到期用收市價按 R 計。
* **成績單位**：R（1R＝入場到止蝕嘅距離）。未計點差、滑價、隔夜息（回測估計成本約 0.05 ATR 來回）。
* **判決**（只計 🟢，已了結 ≥ 60 筆先判）：平均 R > 0 且 t ≥ 2 → 🔍 值得做正式回測；平均 R ≤ 0 → ☠️ 停用「可做」字眼、
  只留觀察；其他 → ⏳ 繼續累積。看完結果唔准改評分規則；要改就換版本號（`VERSION`）重新累積。

用法
    python3 scripts/pattern_scan.py [--dry-run] [--symbols GC=F,EURUSD=X] [--csv-dir data/us_futures] [--today 2026-10-14]
    python3 scripts/pattern_scan.py --backtest --csv-dir data/us_futures   # 歷史逐日重播（事後參考，唔算預先登記）
環境變數：TG_BOT_TOKEN、TG_CHAT_ID（冇就只印）。
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "pattern_scan"
HKT = timezone(timedelta(hours=8))
VERSION = "v2"
FOOTER = "只係形態掃描資訊、唔係落單指令；🟢 規則有回測（research/pattern_scan/RESEARCH.md）但歷史唔代表將來，入場前自己再睇圖、控制注碼。"

# (Yahoo 代號, 名稱, 類別, 小數位)
UNIVERSE = [
    ("GC=F", "黃金", "金屬", 1), ("SI=F", "白銀", "金屬", 3), ("HG=F", "銅", "金屬", 4),
    ("CL=F", "原油", "能源", 2), ("NG=F", "天然氣", "能源", 3),
    ("ES=F", "標普 ES", "指數", 2), ("NQ=F", "納指 NQ", "指數", 2), ("YM=F", "道指 YM", "指數", 0),
    ("RTY=F", "羅素 RTY", "指數", 1), ("NKD=F", "日經 NKD", "指數", 0), ("^HSI", "恒指（指數代期貨）", "指數", 0),
    ("ZN=F", "美債 10 年", "利率", 3),
    ("EURUSD=X", "歐元/美元", "外匯", 5), ("GBPUSD=X", "英鎊/美元", "外匯", 5), ("USDJPY=X", "美元/日圓", "外匯", 3),
    ("AUDUSD=X", "澳元/美元", "外匯", 5), ("NZDUSD=X", "紐元/美元", "外匯", 5), ("USDCAD=X", "美元/加元", "外匯", 5),
    ("USDCHF=X", "美元/瑞郎", "外匯", 5), ("EURJPY=X", "歐元/日圓", "外匯", 3), ("GBPJPY=X", "英鎊/日圓", "外匯", 3),
    ("EURGBP=X", "歐元/英鎊", "外匯", 5),
]
META = {s: (n, c, d) for s, n, c, d in UNIVERSE}

# 形態先驗分（唔係回測出嚟，係教科書可靠度排序；前向評分會話我哋準唔準）
BASE = {"頭肩頂": 3, "頭肩底": 3, "雙頂": 3, "雙底": 3, "牛旗": 3, "熊旗": 3,
        "區間上破": 2, "區間下破": 2, "好倉吞噬": 2, "淡倉吞噬": 2, "錘頭 Pin": 2, "射擊之星 Pin": 2,
        "三角收斂": 2, "收窄 NR7/母子": 1}
REVERSAL = {"頭肩頂", "頭肩底", "雙頂", "雙底", "好倉吞噬", "淡倉吞噬", "錘頭 Pin", "射擊之星 Pin"}
PIV_K = 3          # 擺動高低點：左右各 3 支
TRIGGER_BARS = 3   # 掛單有效 K 線數
HOLD_BARS = 60     # 最長持有
TRAIL_ATR = 3.0    # 移動止蝕：成交後最高收市 − 3 ATR（淡倉相反），每日收市後更新
MIN_RISK_ATR = 0.5 # 止蝕最少離入場 0.5 ATR（太近會俾雜訊掃走、R 數失真）
# v2 🟢 規則（2026-10-14 研究，見 research/pattern_scan/RESEARCH.md）：只有呢個組合喺訓練期同測試期都正
GREEN_CLASSES = {"金屬"}
GREEN_PATTERNS = {"區間上破", "牛旗"}


@dataclass
class Setup:
    pattern: str
    dir: int            # +1 好、-1 淡
    entry_type: str     # stop / market
    entry: float
    stop: float
    target: float
    note: str = ""
    score: int = 0
    grade: str = ""
    why: list = field(default_factory=list)

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / risk if risk > 0 else 0.0


# ---------------------------------------------------------------- 數據
def fetch_yahoo(sym: str) -> pd.DataFrame:
    import yfinance as yf
    df = None
    for attempt in range(3):
        try:
            df = yf.Ticker(sym).history(period="2y", interval="1d", auto_adjust=False, actions=False)
        except Exception as e:  # 網絡間歇
            print(f"  {sym} 第 {attempt + 1} 次失敗：{e}")
            df = None
        if df is not None and len(df):
            break
        time.sleep(4 * (attempt + 1))
    if df is None or not len(df):
        raise RuntimeError(f"{sym}: 冇數據")
    return clean(df)


def file_key(sym: str) -> str:
    return sym.replace("=F", "").replace("=X", "").replace("^", "IDX_")


def load_csv(path: Path) -> pd.DataFrame:
    return clean(pd.read_csv(path, index_col=0, parse_dates=True))


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["Open", "High", "Low", "Close"]].copy()
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df.index = pd.to_datetime(df.index).normalize()
    df = df[(df["High"] > 0) & (df["Low"] > 0) & (df["High"] >= df["Low"])].dropna()
    return df[~df.index.duplicated(keep="last")].sort_index()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["SMA200"] = df["Close"].rolling(200, min_periods=100).mean()
    df["ATRP"] = df["ATR"] / df["Close"]
    df["ATRP_RANK"] = df["ATRP"].rolling(250, min_periods=60).rank(pct=True)
    w = 2 * PIV_K + 1
    df["PH"] = df["High"] == df["High"].rolling(w, center=True).max()
    df["PL"] = df["Low"] == df["Low"].rolling(w, center=True).min()
    return df


def trend_of(row, ema50_prev) -> int:
    c, e20, e50 = row["Close"], row["EMA20"], row["EMA50"]
    if c > e50 and e20 > e50 and e50 > ema50_prev:
        return 1
    if c < e50 and e20 < e50 and e50 < ema50_prev:
        return -1
    return 0


def pivots(df: pd.DataFrame, i: int, col: str, lookback: int = 80) -> list[tuple[int, float]]:
    """i 當日已確認（右邊夠 PIV_K 支）嘅擺動點：[(位置, 價)]，由舊到新。"""
    lo = max(0, i - lookback)
    hi = i - PIV_K  # 之後要有 PIV_K 支 K 線先確認
    price = "High" if col == "PH" else "Low"
    out = []
    flags = df[col].values
    vals = df[price].values
    for j in range(lo, hi + 1):
        if flags[j]:
            out.append((j, float(vals[j])))
    return out


# ---------------------------------------------------------------- 形態偵測（只睇第 i 支同之前）
def detect(df: pd.DataFrame, i: int) -> list[Setup]:
    r, p = df.iloc[i], df.iloc[i - 1]
    O, H, L, C, A = r["Open"], r["High"], r["Low"], r["Close"], r["ATR"]
    if not A or math.isnan(A):
        return []
    b = 0.05 * A
    rng = H - L
    body = abs(C - O)
    out: list[Setup] = []
    ph, pl = pivots(df, i, "PH"), pivots(df, i, "PL")

    def next_level(entry: float, d: int) -> float | None:
        """入場價以外最近嘅擺動阻力（好）／支持（淡），要離入場 ≥ 1 ATR。"""
        if d > 0:
            lv = [v for _, v in ph if v > entry + A]
            return min(lv) if lv else None
        lv = [v for _, v in pl if v < entry - A]
        return max(lv) if lv else None

    def tgt(entry: float, stop: float, d: int) -> float:
        lv = next_level(entry, d)
        return lv if lv is not None else entry + d * 3 * abs(entry - stop)

    # 1. 吞噬
    if rng >= 0.8 * A:
        if p["Close"] < p["Open"] and C > O and C >= p["Open"] and O <= p["Close"] and body > abs(p["Close"] - p["Open"]):
            e, s = H + b, L - b
            out.append(Setup("好倉吞噬", 1, "stop", e, s, tgt(e, s, 1)))
        if p["Close"] > p["Open"] and C < O and C <= p["Open"] and O >= p["Close"] and body > abs(p["Close"] - p["Open"]):
            e, s = L - b, H + b
            out.append(Setup("淡倉吞噬", -1, "stop", e, s, tgt(e, s, -1)))

    # 2. Pin bar（要刺穿近 5 支高／低位）
    if rng >= 0.8 * A:
        lw, uw = min(O, C) - L, H - max(O, C)
        if lw >= 2 / 3 * rng and L <= df["Low"].iloc[i - 5:i].min():
            e, s = H + b, L - b
            out.append(Setup("錘頭 Pin", 1, "stop", e, s, tgt(e, s, 1)))
        if uw >= 2 / 3 * rng and H >= df["High"].iloc[i - 5:i].max():
            e, s = L - b, H + b
            out.append(Setup("射擊之星 Pin", -1, "stop", e, s, tgt(e, s, -1)))

    # 3. 收窄：母子或 NR7（方向由評分順勢決定，兩邊都出，評分會揀）
    inside = H < p["High"] and L > p["Low"]
    nr7 = rng <= (df["High"] - df["Low"]).iloc[i - 6:i + 1].min()
    if inside or nr7:
        mh, ml = (p["High"], p["Low"]) if inside else (H, L)
        tag = "母子" if inside else "NR7"
        for d in (1, -1):
            e, s = (mh + b, ml - b) if d > 0 else (ml - b, mh + b)
            out.append(Setup("收窄 NR7/母子", d, "stop", e, s, tgt(e, s, d), tag))

    # 4. 雙底／雙頂（頸線 = 兩底之間最高位）
    def double(points, d):
        if len(points) < 2:
            return
        (j1, v1), (j2, v2) = points[-2], points[-1]
        if not (5 <= j2 - j1 <= 60) or abs(v1 - v2) > 0.5 * A or i - j2 > 15:
            return
        seg = df.iloc[j1:j2 + 1]
        neck = seg["High"].max() if d > 0 else seg["Low"].min()
        height = abs(neck - (v1 + v2) / 2)
        if height < 1.5 * A:
            return
        extreme = min(v1, v2) if d > 0 else max(v1, v2)
        broke_now = (C > neck >= p["Close"]) if d > 0 else (C < neck <= p["Close"])
        pending = (neck - A < C <= neck) if d > 0 else (neck <= C < neck + A)
        name = "雙底" if d > 0 else "雙頂"
        s = extreme - d * b
        if broke_now:
            out.append(Setup(name, d, "market", C, s, neck + d * height, "今日收破頸線"))
        elif pending:
            e = neck + d * b
            out.append(Setup(name, d, "stop", e, s, neck + d * height, "等破頸線"))

    double(pl, 1)
    double(ph, -1)

    # 5. 頭肩頂／頭肩底
    def hs(points, d):
        # d=-1 頭肩頂用擺動高位；d=+1 頭肩底用擺動低位
        if len(points) < 3:
            return
        (j1, ls), (j2, hd), (j3, rs) = points[-3:]
        if i - j3 > 15 or j3 - j1 > 80:
            return
        ext = (hd - max(ls, rs)) if d < 0 else (min(ls, rs) - hd)
        if ext < 0.5 * A or abs(ls - rs) > 1.0 * A:
            return
        t1 = df.iloc[j1:j2 + 1]["Low" if d < 0 else "High"]
        t2 = df.iloc[j2:j3 + 1]["Low" if d < 0 else "High"]
        neck = (t1.min() + t2.min()) / 2 if d < 0 else (t1.max() + t2.max()) / 2
        height = abs(hd - neck)
        name = "頭肩頂" if d < 0 else "頭肩底"
        s = rs - d * b  # 止蝕放右肩外
        if (d < 0 and C < neck <= p["Close"]) or (d > 0 and C > neck >= p["Close"]):
            out.append(Setup(name, d, "market", C, s, neck + d * height, "今日收破頸線"))
        elif (d < 0 and neck <= C < neck + A) or (d > 0 and neck - A < C <= neck):
            out.append(Setup(name, d, "stop", neck + d * b, s, neck + d * height, "等破頸線"))

    hs(ph, -1)
    hs(pl, 1)

    # 6. 20 日區間突破（收市破前 20 日高／低，而且收喺當日上／下四分一）
    box = df.iloc[i - 20:i]
    bh, bl = box["High"].max(), box["Low"].min()
    if C > bh and (C - L) >= 0.75 * rng:
        s = max(L - b, C - 2 * A)
        out.append(Setup("區間上破", 1, "market", C, s, C + max(bh - bl, 2 * (C - s)), f"箱 {bh - bl:.4g}"))
    if C < bl and (H - C) >= 0.75 * rng:
        s = min(H + b, C + 2 * A)
        out.append(Setup("區間下破", -1, "market", C, s, C - max(bh - bl, 2 * (s - C)), f"箱 {bh - bl:.4g}"))

    # 7. 旗形：旗桿 ≥ 3 ATR（≤ 8 支），之後 3–10 支細整理、回吐 ≤ 50%
    for n in range(3, 11):
        cons = df.iloc[i - n + 1:i + 1]
        pole = df.iloc[i - n + 1 - 8:i - n + 1]
        if len(pole) < 8:
            break
        ch, cl = cons["High"].max(), cons["Low"].min()
        if ch - cl > 2 * A:
            continue
        lo_j, hi_j = pole["Low"].values.argmin(), pole["High"].values.argmax()
        up = pole["High"].max() - pole["Low"].min()
        if up < 3 * A:
            continue
        top, bot = pole["High"].max(), pole["Low"].min()
        if hi_j > lo_j and ch <= top + 0.2 * A and cl >= top - 0.5 * up:
            e, s = ch + b, cl - b
            out.append(Setup("牛旗", 1, "stop", e, s, e + up, f"旗桿 {up / A:.1f} ATR、整理 {n} 支"))
            break
        if lo_j > hi_j and cl >= bot - 0.2 * A and ch <= bot + 0.5 * up:
            e, s = cl - b, ch + b
            out.append(Setup("熊旗", -1, "stop", e, s, e - up, f"旗桿 {up / A:.1f} ATR、整理 {n} 支"))
            break

    # 8. 三角收斂：高點愈來愈低、低點愈來愈高，最新闊度 < 早前 60%
    if len(ph) >= 2 and len(pl) >= 2:
        (a1, h1), (a2, h2) = ph[-2:]
        (c1, l1), (c2, l2) = pl[-2:]
        if h2 < h1 and l2 > l1 and i - min(a1, c1) <= 40 and (h2 - l2) < 0.6 * (h1 - l1) and l2 < C < h2:
            for d in (1, -1):
                e, s = (h2 + b, l2 - b) if d > 0 else (l2 - b, h2 + b)
                out.append(Setup("三角收斂", d, "stop", e, s, e + d * (h1 - l1), "兩邊都可能破"))
    return out


# ---------------------------------------------------------------- 評分
def score(df: pd.DataFrame, i: int, s: Setup, cls: str = "") -> Setup:
    r = df.iloc[i]
    A = r["ATR"]
    if abs(s.entry - s.stop) < MIN_RISK_ATR * A:  # 止蝕太近就推遠
        s.stop = s.entry - s.dir * MIN_RISK_ATR * A
    tr = trend_of(r, df["EMA50"].iloc[i - 10])
    pts = BASE.get(s.pattern, 1)
    why = [f"形態 +{pts}"]
    if tr == s.dir:
        pts += 2; why.append("順勢 +2")
    elif tr == -s.dir:
        if s.pattern in REVERSAL:
            why.append("逆勢反轉 0")
        else:
            pts -= 2; why.append("逆勢 −2")
    else:
        if s.pattern in ("收窄 NR7/母子", "三角收斂"):
            pts -= 1; why.append("冇趨勢、方向未定 −1")
    if s.pattern in REVERSAL:
        lv = [v for _, v in pivots(df, i, "PL" if s.dir > 0 else "PH", 120)]
        probe = r["Low"] if s.dir > 0 else r["High"]
        if any(abs(probe - v) <= 0.5 * A for v in lv) or abs(probe - r["SMA200"]) <= 0.5 * A:
            pts += 1; why.append("喺支持阻力位 +1")
    rr = s.rr
    if rr >= 3:
        pts += 1; why.append(f"R:R {rr:.1f} +1")
    elif rr < 2:
        pts -= 2; why.append(f"R:R {rr:.1f} 不足 −2")
    risk_atr = abs(s.entry - s.stop) / A
    if risk_atr > 3:
        pts -= 1; why.append(f"止蝕闊 {risk_atr:.1f} ATR −1")
    rank = r["ATRP_RANK"]
    if not math.isnan(rank) and rank < 0.2 and s.pattern not in ("收窄 NR7/母子", "三角收斂", "區間上破", "區間下破"):
        pts -= 1; why.append("波動死水 −1")
    s.score, s.why = pts, why
    green = (cls in GREEN_CLASSES and s.pattern in GREEN_PATTERNS and s.dir > 0 and tr == 1
             and not math.isnan(r["SMA200"]) and r["Close"] > r["SMA200"])
    if green:
        why.append("v2 優勢組合：金屬・上升趨勢・200 日線上・做好突破")
    s.grade = "🟢" if green else ("🟡" if pts >= 3 else "")
    return s


def best_setups(df: pd.DataFrame, i: int, cls: str = "") -> list[Setup]:
    if i < 60:
        return []
    found = [score(df, i, s, cls) for s in detect(df, i)]
    found = [s for s in found if s.grade]
    return sorted(found, key=lambda s: (s.grade != "🟢", -s.score, -s.rr))


# ---------------------------------------------------------------- 成績（前向／回測共用）
def evaluate(df: pd.DataFrame, i: int, s) -> tuple[str, float | None]:
    """由第 i 支（訊號日）之後計：回傳（狀態, R）。狀態：未到／過期／持有中／止蝕／到期。
    v2：唔用固定目標，用移動止蝕（TRAIL_ATR）；跳空穿止蝕用開市價計。"""
    d, entry, stop, target = int(s["dir"]), float(s["entry"]), float(s["stop"]), float(s["target"])
    n = len(df)
    if i + 1 >= n:
        return "未到", None
    j0 = None
    if s["entry_type"] == "market":
        j0, fill = i + 1, float(df["Open"].iloc[i + 1])
    else:
        for j in range(i + 1, min(n, i + 1 + TRIGGER_BARS)):
            o, h, l = df["Open"].iloc[j], df["High"].iloc[j], df["Low"].iloc[j]
            if (d > 0 and h >= entry) or (d < 0 and l <= entry):
                j0, fill = j, (max(o, entry) if d > 0 else min(o, entry))
                break
        if j0 is None:
            return ("過期" if i + TRIGGER_BARS < n else "未到"), None
    risk = abs(fill - stop)
    if risk <= 0 or (d > 0 and fill <= stop) or (d < 0 and fill >= stop):
        return "止蝕", -1.0
    O, H, L, C, A = (df[c].values for c in ("Open", "High", "Low", "Close", "ATR"))
    st, best = stop, fill
    for j in range(j0, min(n, j0 + HOLD_BARS)):
        if (d > 0 and L[j] <= st) or (d < 0 and H[j] >= st):
            px = min(O[j], st) if d > 0 else max(O[j], st)
            return "止蝕", d * (px - fill) / risk
        best = max(best, C[j]) if d > 0 else min(best, C[j])
        ts = best - d * TRAIL_ATR * A[j]
        st = max(st, ts) if d > 0 else min(st, ts)
    last = min(n, j0 + HOLD_BARS) - 1
    rr = d * (float(df["Close"].iloc[last]) - fill) / risk
    return ("到期" if j0 + HOLD_BARS <= n else "持有中"), rr


def summarize(rs: list[float]) -> str:
    if not rs:
        return "未有已了結訊號"
    n = len(rs)
    m = sum(rs) / n
    sd = (sum((x - m) ** 2 for x in rs) / (n - 1)) ** 0.5 if n > 1 else 0
    t = m / (sd / n ** 0.5) if sd > 0 else 0
    win = sum(1 for x in rs if x > 0) / n
    return f"{n} 筆、勝率 {win:.0%}、平均 {m:+.2f}R、t {t:.2f}"


def verdict(rs: list[float]) -> str:
    if len(rs) < 60:
        return f"⏳ 累積中（{len(rs)}/60）"
    n, m = len(rs), sum(rs) / len(rs)
    sd = (sum((x - m) ** 2 for x in rs) / (n - 1)) ** 0.5
    t = m / (sd / n ** 0.5) if sd > 0 else 0
    if m > 0 and t >= 2:
        return "🔍 值得正式回測"
    if m <= 0:
        return "☠️ 停用「可做」"
    return "⏳ 繼續累積"


# ---------------------------------------------------------------- 輸出
def fmt(x: float, dp: int) -> str:
    return f"{x:,.{dp}f}"


def trend_word(df, i) -> str:
    return {1: "上升", -1: "下跌", 0: "橫行"}[trend_of(df.iloc[i], df["EMA50"].iloc[i - 10])]


def line_for(sym: str, s: Setup, df, i) -> str:
    name, _, dp = META.get(sym, (sym, "", 4))
    side = "🔺做好" if s.dir > 0 else "🔻做淡"
    how = "突破掛單" if s.entry_type == "stop" else "開市入"
    return (f"{name}｜{side}｜{s.pattern}（{s.note}）\n"
            f"   {how} {fmt(s.entry, dp)}、止蝕 {fmt(s.stop, dp)}、之後移動止蝕（最高收市 − {TRAIL_ATR:g} ATR＝{fmt(TRAIL_ATR * df['ATR'].iloc[i], dp)}）、"
            f"第一目標 {fmt(s.target, dp)}｜趨勢{trend_word(df, i)}")


SIG_FIELDS = ["date", "version", "symbol", "pattern", "dir", "entry_type", "entry", "stop", "target", "rr", "score", "grade", "note"]


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SIG_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in SIG_FIELDS})


def run_scan(a) -> int:
    today = date.fromisoformat(a.today) if a.today else datetime.now(HKT).date()
    syms = [s.strip() for s in a.symbols.split(",")] if a.symbols else [u[0] for u in UNIVERSE]
    data, failed = {}, []
    for sym in syms:
        try:
            if a.csv_dir:
                base = Path(a.csv_dir) / (file_key(sym) + "_daily.csv")
                df = load_csv(base if base.exists() else base.with_suffix(".csv.gz"))
            else:
                df = fetch_yahoo(sym)
            df = df[df.index.date < today]  # 只用已收市 K 線
            if len(df) < 120:
                raise RuntimeError(f"只有 {len(df)} 支 K 線")
            data[sym] = add_indicators(df)
        except Exception as e:
            failed.append(f"{sym}（{e}）")
            print(f"⚠ {sym}: {e}")

    # 今日訊號
    picks: list[tuple[str, Setup]] = []
    asof = {}
    for sym, df in data.items():
        i = len(df) - 1
        asof[sym] = df.index[i].date()
        for s in best_setups(df, i, META.get(sym, ("", ""))[1])[:1]:  # 每隻產品只揀最好嗰個
            picks.append((sym, s))
    picks.sort(key=lambda x: (-x[1].score, -x[1].rr))
    green = [(k, s) for k, s in picks if s.grade == "🟢"]
    amber = [(k, s) for k, s in picks if s.grade == "🟡"]

    # 帳本：加今日、為舊訊號計成績
    ledger_path = OUT / "signals.csv"
    ledger = read_ledger(ledger_path)
    seen = {(r["date"], r["symbol"], r["pattern"], r["dir"]) for r in ledger}
    for sym, s in picks:
        key = (str(asof[sym]), sym, s.pattern, str(s.dir))
        if key not in seen:
            ledger.append({"date": str(asof[sym]), "version": VERSION, "symbol": sym, "pattern": s.pattern, "dir": s.dir,
                           "entry_type": s.entry_type, "entry": f"{s.entry:.6g}", "stop": f"{s.stop:.6g}",
                           "target": f"{s.target:.6g}", "rr": f"{s.rr:.2f}", "score": s.score, "grade": s.grade, "note": s.note})
    graded = {"🟢": [], "🟡": []}
    open_n = 0
    for r in ledger:
        df = data.get(r["symbol"])
        if df is None or r.get("version") != VERSION:
            continue
        idx = df.index.get_indexer([pd.Timestamp(r["date"])])[0]
        if idx < 0:
            continue
        st, rr = evaluate(df, idx, r)
        if st in ("止蝕", "到期"):
            graded.setdefault(r["grade"], []).append(rr)
        elif st == "持有中":
            open_n += 1

    # 訊息
    d0 = max(asof.values()) if asof else today
    msg = [f"🧭 早盤形態掃描 {today}（用 {d0} 收市日線，{len(data)} 隻產品，{VERSION}）", ""]
    if green:
        msg.append(f"🟢 今日可做（{len(green)}）")
        for k, s in green:
            msg.append(line_for(k, s, data[k], len(data[k]) - 1))
    else:
        msg.append("🟢 今日可做：冇。只有「金屬上升趨勢做好突破」歷史上有優勢，今日冇出現，等。")
    watch = []
    for sym, df in data.items():
        name, cls, dp = META.get(sym, (sym, "", 4))
        if cls not in GREEN_CLASSES:
            continue
        i = len(df) - 1
        r = df.iloc[i]
        hi20 = df["High"].iloc[i - 19:i + 1].max()
        ok = trend_of(r, df["EMA50"].iloc[i - 10]) == 1 and r["Close"] > r["SMA200"]
        gap = (hi20 - r["Close"]) / r["ATR"]
        watch.append(f"{name} {fmt(r['Close'], dp)}｜{'✅ 上升趨勢' if ok else '✖ 未符合趨勢'}｜離 20 日高 {fmt(hi20, dp)} 仲差 {gap:.1f} ATR")
    if watch:
        msg += ["", "🔭 金屬盯盤（🟢 只會喺呢度出）"] + ["   " + w for w in watch]
    if amber:
        msg += ["", f"🟡 觀察（{len(amber)}，歷史冇優勢，只供參考）"]
        for k, s in amber[:8]:
            name = META.get(k, (k,))[0]
            msg.append(f"{name}：{'好' if s.dir > 0 else '淡'}・{s.pattern}・{s.score} 分・R:R {s.rr:.1f}")
    msg += ["", f"📒 前向成績（{VERSION}）🟢 {summarize(graded['🟢'])}｜{verdict(graded['🟢'])}",
            f"   🟡 {summarize(graded['🟡'])}｜持有中 {open_n}"]
    if failed:
        msg.append(f"⚠ 抓唔到：{'、'.join(f.split('（')[0] for f in failed)}")
    msg += ["", FOOTER]
    text = "\n".join(msg)
    print(text)

    # 報告
    rep = [f"# 早盤形態掃描 {today}", "", f"版本 {VERSION}；日線截至 {d0}；規則見 `scripts/pattern_scan.py` 檔頭。", "",
           "| 產品 | 收市 | 趨勢 | ATR | 最佳形態 | 方向 | 入場 | 止蝕 | 目標 | R:R | 分 | 評分原因 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    best = dict(picks)
    for sym, df in data.items():
        i = len(df) - 1
        name, _, dp = META.get(sym, (sym, "", 4))
        s = best.get(sym)
        row = df.iloc[i]
        if s:
            rep.append(f"| {name} | {fmt(row['Close'], dp)} | {trend_word(df, i)} | {fmt(row['ATR'], dp)} | {s.grade} {s.pattern} {s.note} | "
                       f"{'好' if s.dir > 0 else '淡'} | {fmt(s.entry, dp)} | {fmt(s.stop, dp)} | {fmt(s.target, dp)} | {s.rr:.1f} | {s.score} | {'；'.join(s.why)} |")
        else:
            rep.append(f"| {name} | {fmt(row['Close'], dp)} | {trend_word(df, i)} | {fmt(row['ATR'], dp)} | — | | | | | | | |")
    rep += ["", "## 前向成績", "", f"- 🟢：{summarize(graded['🟢'])}；判決 {verdict(graded['🟢'])}",
            f"- 🟡：{summarize(graded['🟡'])}", f"- 持有中：{open_n}", ""]
    if failed:
        rep += ["## 抓唔到", ""] + [f"- {f}" for f in failed] + [""]
    rep += ["---", FOOTER, ""]

    if a.dry_run:
        print("（dry-run：唔寫檔、唔發 Telegram）")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    write_ledger(ledger_path, ledger)
    (OUT / f"{today}.md").write_text("\n".join(rep), encoding="utf-8")
    (OUT / "latest.md").write_text("\n".join(rep), encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ops_notify import send_telegram  # noqa: E402
    send_telegram(text)
    return 0 if data else 1


def run_backtest(a) -> int:
    """逐日重播：每日用當時已有嘅數據搵形態、照預先登記規則計成績。事後參考，唔算預先登記。"""
    files = sorted(Path(a.csv_dir).glob("*_daily.csv*"))
    if a.symbols:
        want = {file_key(s) for s in a.symbols.split(",")}
        files = [f for f in files if f.name.split("_daily.csv")[0] in want]
    by_pat: dict[str, list[float]] = {}
    by_grade: dict[str, list[float]] = {"🟢": [], "🟡": []}
    for f in files:
        df = add_indicators(load_csv(f))
        if a.since:
            start = max(250, int(df.index.searchsorted(pd.Timestamp(a.since))))
        else:
            start = 250
        key = f.name.split("_daily.csv")[0]
        cls = next((c for sym, _, c, _ in UNIVERSE if file_key(sym) == key), "")
        n0 = sum(len(v) for v in by_grade.values())
        for i in range(start, len(df) - 1):
            for s in best_setups(df, i, cls)[:1]:
                st, rr = evaluate(df, i, {"dir": s.dir, "entry": s.entry, "stop": s.stop, "target": s.target,
                                          "entry_type": s.entry_type})
                if st in ("止蝕", "到期"):
                    by_grade[s.grade].append(rr)
                    by_pat.setdefault(f"{s.grade} {s.pattern}", []).append(rr)
                    half = "≤2016" if df.index[i].year <= 2016 else "2017+"
                    by_pat.setdefault(f"{s.grade} {key} {half}", []).append(rr)
        print(f"{f.name}: {sum(len(v) for v in by_grade.values()) - n0} 筆已了結")
    print("\n== 按評級 ==")
    for g, rs in by_grade.items():
        print(f"{g}: {summarize(rs)}")
    print("\n== 按形態 ==")
    for k in sorted(by_pat, key=lambda k: -len(by_pat[k])):
        print(f"{k}: {summarize(by_pat[k])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--csv-dir", default="")
    ap.add_argument("--today", default="")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--since", default="", help="回測起始日（YYYY-MM-DD）")
    a = ap.parse_args()
    if a.backtest:
        if not a.csv_dir:
            ap.error("--backtest 要配 --csv-dir")
        return run_backtest(a)
    return run_scan(a)


if __name__ == "__main__":
    sys.exit(main())
