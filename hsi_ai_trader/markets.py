"""各產品規格同交易時段（純邏輯，冇 I/O）。

龍飛陣每隻產品行一個獨立程式（環境變數 PRODUCT），各自有狀態、心跳、STOP／PAUSE 同日蝕上限。
金額一律用 HKD 計：point_value_hkd = 每點價值 × 匯率，所以日蝕上限、止蝕風險同盈虧都可以直接比較。
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Spec:
    product: str          # Futu 代號字頭，例如 HSI、MES
    name: str             # 畀 AI 睇嘅產品描述
    market: str           # "HK" 或 "US"（Futu 代號前綴）
    tz: ZoneInfo          # 交易所時區（判斷時段、報價時間）
    currency: str
    point_value: float    # 每點價值（原幣）
    tick: float           # 最細跳動
    slippage: float       # 可成交限價單加幾多點（要係 tick 嘅倍數）
    fee_per_side_hkd: float
    roll_days: int        # 最後交易日前幾日轉下月（美期成交量喺到期前約一週轉倉）


SPECS = {
    "HSI": Spec("HSI", "Hang Seng Index Futures (HKFE)", "HK", HKT, "HKD", 50, 1, 3, 40, 0),
    "MHI": Spec("MHI", "Mini Hang Seng Index Futures (HKFE)", "HK", HKT, "HKD", 10, 1, 3, 15, 0),
    "MES": Spec("MES", "Micro E-mini S&P 500 Futures (CME)", "US", ET, "USD", 5, 0.25, 1.0, 15, 8),
    "MNQ": Spec("MNQ", "Micro E-mini Nasdaq-100 Futures (CME)", "US", ET, "USD", 2, 0.25, 1.0, 15, 8),
    "MYM": Spec("MYM", "Micro E-mini Dow Jones Futures (CBOT)", "US", ET, "USD", 0.5, 1, 5, 15, 8),
}

FX_TO_HKD = {"HKD": 1.0, "USD": 7.8}


def spec_for(product: str) -> Spec:
    try:
        return SPECS[product]
    except KeyError:
        raise ValueError(f"未支援嘅產品 {product}（支援：{', '.join(SPECS)}）") from None


def _mins(a: time, b: time) -> float:
    return (b.hour * 60 + b.minute + b.second / 60) - (a.hour * 60 + a.minute + a.second / 60)


# ---------- 港期（HKT）----------
HK_DAY_AM = (time(9, 15), time(12, 0))
HK_DAY_PM = (time(13, 0), time(16, 30))
HK_NIGHT_START = time(17, 15)
HK_NIGHT_END = time(3, 0)


def _hk_session(now):
    t = now.astimezone(HKT).timetz().replace(tzinfo=None)
    wd = now.astimezone(HKT).weekday()
    if wd <= 4:
        if HK_DAY_AM[0] <= t < HK_DAY_AM[1]:
            return "DAY_AM", _mins(t, HK_DAY_AM[1])
        if HK_DAY_PM[0] <= t < HK_DAY_PM[1]:
            return "DAY_PM", _mins(t, HK_DAY_PM[1])
        if t >= HK_NIGHT_START:
            return "NIGHT", _mins(t, time(23, 59, 59)) + 1 / 60 + 180
    if 1 <= wd <= 5 and t < HK_NIGHT_END:  # 週二至週六凌晨
        return "NIGHT", _mins(t, HK_NIGHT_END)
    return None, None


# ---------- 美期 CME Globex（美東時間）：週日 18:00 至週五 17:00，週一至四 17:00–18:00 維護 ----------
US_CLOSE = time(17, 0)
US_OPEN = time(18, 0)


def _us_session(now):
    et = now.astimezone(ET)
    t, wd = et.timetz().replace(tzinfo=None), et.weekday()   # 0=Mon … 6=Sun
    if wd == 5 or (wd == 6 and t < US_OPEN) or (wd == 4 and t >= US_CLOSE):
        return None, None
    if US_CLOSE <= t < US_OPEN:                                # 每日維護時段
        return None, None
    if t >= US_OPEN:                                           # 晚上開市，收市係翌日 17:00
        return "GLOBEX", _mins(t, time(23, 59, 59)) + 1 / 60 + 17 * 60
    return "GLOBEX", _mins(t, US_CLOSE)


def session_status(now: datetime, market: str = "HK"):
    """回傳 (時段名, 距離收市分鐘)；唔喺交易時段回傳 (None, None)。假期由「報價過期」檢查處理。"""
    return _us_session(now) if market == "US" else _hk_session(now)


def trading_day_key(now: datetime, market: str = "HK") -> str:
    """港期：17:00 HKT 開始計新一日（夜市屬下一日）；美期：18:00 美東開市開始計新一日。用嚟重置日蝕。"""
    if market == "US":
        return (now.astimezone(ET) + timedelta(hours=6)).date().isoformat()
    return (now.astimezone(HKT) + timedelta(hours=7)).date().isoformat()


def third_friday(y: int, m: int) -> date:
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def quarterly_contracts(product: str, market: str, today: date, n: int = 3):
    """Futu 合約列表攞唔到時嘅後備：CME 股指季月（3、6、9、12）第三個星期五到期。"""
    out, y, m = [], today.year, today.month
    while len(out) < n:
        if m % 3 == 0:
            ltd = third_friday(y, m)
            if ltd >= today:
                out.append((f"{market}.{product}{y % 100:02d}{m:02d}", ltd))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out
