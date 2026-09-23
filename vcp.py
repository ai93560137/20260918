"""VCP（波動收縮形態）偵測——回測（vcp_backtest.py）與每日篩選（scripts/daily_topdown.py）共用同一套。
定義與參數見 VCP_BACKTEST.md 第一部分（預先登記，寫死）。

analyze(high, low, close, vol, alow, t) 只看 t 之前的底部 + t 當天的突破；價格形態用原始價
（按拆股還原、不按股息），alow 是還原最低價（給停損位用）。回傳 dict（形態資料）或 None（形態不成立）。
r、D 兩個鄰域參數不在這裡判，交給 passes()，所以一次偵測可以評估 9 格。
"""
import numpy as np

ZIGZAG = 0.03          # 擺動點：反向走 ≥ 3%
BASE_LOOKBACK = 252    # H₀ = t 之前 252 日最高價
MIN_BASE_DAYS = 15     # 底部 ≥ 3 週
MIN_T, MAX_T = 2, 6    # 收縮次數
MAX_FIRST = 0.35       # 第一次收縮 ≤ 35%
MIN_LAST_DAYS = 5      # 最後一次收縮 ≥ 5 日
RIGHT_SIDE = 1.02      # 擺動高點不抬頭
VOL_DRY = 0.7          # 最後收縮平均量 < 50 日均量 × 0.7
VOL_BREAK = 1.4        # 突破量 ≥ 50 日均量 × 1.4
DEFAULT_R, DEFAULT_D = 0.8, 0.10


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


def analyze(high, low, close, vol, alow, t: int) -> dict | None:
    """t = 突破日（收市後判斷）。回傳形態資料（不含 r、D 判斷）或 None。"""
    if t < BASE_LOOKBACK + 1:
        return None
    lo = t - BASE_LOOKBACK
    h0 = lo + int(np.argmax(high[lo:t]))
    if (t - 1) - h0 < MIN_BASE_DAYS:
        return None
    sh, _ = swing_highs(high, low, h0, t - 1)
    if not (MIN_T <= len(sh) <= MAX_T):
        return None
    depths = []
    for k, a in enumerate(sh):
        b = sh[k + 1] if k + 1 < len(sh) else t          # 到下一個擺動高點（不含）或 t（不含）
        if b - a < 1 or a + 1 >= b:
            return None
        seg = low[a + 1:b]
        depths.append((high[a] - seg.min()) / high[a])
        if k + 1 < len(sh) and high[sh[k + 1]] > high[a] * RIGHT_SIDE:
            return None
    last = sh[-1]
    if (t - 1) - last < MIN_LAST_DAYS:
        return None
    if high[last + 1:t].max() > high[last]:                # 右側在 SH_last 之後又抬頭
        return None
    if depths[0] > MAX_FIRST:
        return None
    avg50 = vol[t - 50:t].mean()
    if not avg50 > 0:
        return None
    dry = vol[last:t].mean() / avg50
    if dry >= VOL_DRY:
        return None
    pivot = high[last]
    if not (close[t] > pivot and vol[t] >= VOL_BREAK * avg50):
        return None
    return {"n_t": len(sh), "depths": depths, "pivot": float(pivot), "sh": sh, "dry": float(dry),
            "stop_adj": float(alow[last + 1:t].min()), "base_days": (t - 1) - h0}


def passes(info: dict | None, r: float = DEFAULT_R, D: float = DEFAULT_D) -> bool:
    if not info:
        return False
    d = info["depths"]
    return all(d[k + 1] <= r * d[k] for k in range(len(d) - 1)) and d[-1] <= D
