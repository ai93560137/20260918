"""VCP（波動收縮形態）偵測——回測（vcp_backtest.py）與每日篩選（scripts/daily_topdown.py）共用同一套。
定義與參數見 stock_research/VCP_BACKTEST.md 第一部分（預先登記，寫死）。

analyze(high, low, close, vol, alow, t) 只看 t 之前的底部 + t 當天的突破；價格形態用原始價
（按拆股還原、不按股息），alow 是還原最低價（給停損位用）。回傳 dict（形態資料）或 None（形態不成立）。
r、D 兩個鄰域參數不在這裡判，交給 passes()，所以一次偵測可以評估 9 格。
"""
import numpy as np
import pandas as pd

ZIGZAG = 0.03          # v1 擺動點：反向走 ≥ 3%（三地樣本不足，見 stock_research/VCP_BACKTEST.md 第一部分之二）
FRACTAL_N = 5          # v2 擺動點：前後各 N 日內的最高價（碎形高點）
BASE_LOOKBACK = 252    # H₀ = t 之前 252 日最高價
MIN_BASE_DAYS = 15     # 底部 ≥ 3 週
MIN_T, MAX_T = 2, 6    # 收縮次數
MAX_FIRST = 0.35       # 第一次收縮 ≤ 35%
MIN_LAST_DAYS = 5      # 最後一次收縮 ≥ 5 日
RIGHT_SIDE = 1.02      # 擺動高點不抬頭
VOL_DRY = 0.7          # 最後收縮平均量 < 50 日均量 × 0.7
VOL_BREAK = 1.4        # 突破量 ≥ 50 日均量 × 1.4
DEFAULT_R, DEFAULT_D = 0.8, 0.10


def trend_template(adj: pd.Series) -> pd.Series:
    """Minervini 趨勢模板第 1 條除相對強度以外的部分（還原收市）：收市 > 50 日線 > 150 日線 > 200 日線、
    200 日線 > 21 日前、收市 ≥ 252 日最低 × 1.3、收市 ≥ 252 日最高 × 0.75。相對強度要跟宇宙比，另外算。"""
    ma50, ma150, ma200 = (adj.rolling(k).mean() for k in (50, 150, 200))
    return ((adj > ma50) & (ma50 > ma150) & (ma150 > ma200) & (ma200 > ma200.shift(21))
            & (adj >= adj.rolling(252).min() * 1.30) & (adj >= adj.rolling(252).max() * 0.75))


RS_MIN = 70            # 相對強度：252 日報酬在 PIT 成分股中的百分位 ≥ 70


def swing_highs(high: np.ndarray, low: np.ndarray, start: int, end: int) -> tuple[list[int], float | None]:
    """ZigZag：由 start（視為第一個擺動高點）掃到 end（含），回傳 (已確認的擺動高點索引, 期末仍在追蹤的上升高點或 None)。"""
    sh = [start]
    mode, lo_v, hi_v, hi_i = "down", np.inf, None, None
    for i in range(start + 1, end + 1):
        if mode == "down":
            if low[i] < lo_v:
                lo_v = low[i]
            if high[i] >= lo_v * (1 + ZIGZAG):
                mode, hi_v, hi_i = "up", high[i], i
        else:
            if high[i] > hi_v:
                hi_v, hi_i = high[i], i
            if low[i] <= hi_v * (1 - ZIGZAG):
                sh.append(hi_i)
                mode, lo_v = "down", low[i]
    return sh, (hi_v if mode == "up" else None)


def swing_highs_fractal(high: np.ndarray, start: int, end: int, n: int = FRACTAL_N) -> list[int]:
    """v2：start（H₀）之後，最高價嚴格高於前 n 日、且不低於後 n 日的日子 = 擺動高點；只看到 end（含）為止，
    所以最後一個擺動高點之後至少有 n 日。"""
    sh = [start]
    for i in range(start + 1, end - n + 1):
        left = high[max(start, i - n):i]
        if high[i] > left.max() and high[i] >= high[i + 1:i + n + 1].max():
            sh.append(i)
    return sh


def base_info(high, low, vol, alow, end: int, version: int = 2, n: int = FRACTAL_N) -> dict | None:
    """以 end（含）為止的底部：第 2–10 條（底部起點、擺動點、收縮、右側、量縮、樞紐點）。不含 r、D 與突破。"""
    if end < BASE_LOOKBACK:
        return None
    lo = end + 1 - BASE_LOOKBACK
    h0 = lo + int(np.argmax(high[lo:end + 1]))
    if end - h0 < MIN_BASE_DAYS:
        return None
    sh = swing_highs(high, low, h0, end)[0] if version == 1 else swing_highs_fractal(high, h0, end, n)
    if not (MIN_T <= len(sh) <= MAX_T):
        return None
    depths = []
    for k, a in enumerate(sh):
        b = sh[k + 1] if k + 1 < len(sh) else end + 1      # 到下一個擺動高點（不含）或 end（含）
        if a + 1 >= b:
            return None
        seg = low[a + 1:b]
        depths.append((high[a] - seg.min()) / high[a])
        if k + 1 < len(sh) and high[sh[k + 1]] > high[a] * RIGHT_SIDE:
            return None
    last = sh[-1]
    if end - last < MIN_LAST_DAYS:
        return None
    if high[last + 1:end + 1].max() > high[last]:          # 右側在 SH_last 之後又抬頭
        return None
    if depths[0] > MAX_FIRST:
        return None
    avg50 = vol[end - 49:end + 1].mean()
    if not avg50 > 0:
        return None
    dry = vol[last:end + 1].mean() / avg50
    if dry >= VOL_DRY:
        return None
    return {"n_t": len(sh), "depths": depths, "pivot": float(high[last]), "sh": sh, "dry": float(dry),
            "stop_adj": float(alow[last + 1:end + 1].min()), "base_days": end - h0, "avg50": float(avg50)}


def analyze(high, low, close, vol, alow, t: int, version: int = 2, n: int = FRACTAL_N) -> dict | None:
    """t = 突破日（收市後判斷）：t−1 為止的底部成立 + t 收市突破樞紐點且放量（第 11 條）。不含 r、D 判斷。"""
    if t < 1:
        return None
    info = base_info(high, low, vol, alow, t - 1, version, n)
    if not info or not (close[t] > info["pivot"] and vol[t] >= VOL_BREAK * info["avg50"]):
        return None
    return info


def passes(info: dict | None, r: float = DEFAULT_R, D: float = DEFAULT_D) -> bool:
    if not info:
        return False
    d = info["depths"]
    return all(d[k + 1] <= r * d[k] for k in range(len(d) - 1)) and d[-1] <= D
