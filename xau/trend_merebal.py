"""[IDEAS #1463／#1466／#1469，使用者 11-13「第一條同第二條轉真倉」] 月尾股債再平衡（純計算，冇 I/O）。
規則 merebal：每月倒數第 6 個交易日（訊號日）睇「指數當月至今回報 − 美債 10 年期貨當月至今回報」：< 0（股票跑輸）→ 做多，≥ 0 → 做空；
揸到當月最後一個交易日平。一個月一次、一次一張。回測（research/strategy_search/batch6_1462.py、fund_1467.py）用日收市入／出；
真倉用訊號日同月尾日嘅固定 UTC 時間（預設 21:05，美股收市後）入／出。
交易日曆：平日減去美國／英國喺月尾會撞到嘅假期（規則計，唔靠外部數據）；對拍見 research/strategy_search/parity_merebal.py。"""
import datetime as dt

NAMES = {"merebal": "月尾股債再平衡（#1463）"}
RULES = tuple(NAMES)
N_BACK = 6            # 倒數第 6 個交易日
ACT_UTC_MIN = 21 * 60 + 5


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    j, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7
    n = (h - m + r + 90) // 25
    p = (h - m + r + n + 19) % 32
    return dt.date(y, n, p)


def _nth(y, m, wd, n):
    d = dt.date(y, m, 1); d += dt.timedelta(days=(wd - d.weekday()) % 7); return d + dt.timedelta(days=7 * (n - 1))


def _last(y, m, wd):
    d = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1); return d - dt.timedelta(days=(d.weekday() - wd) % 7)


def _obs(d):
    """美國：假期喺星期六 → 星期五補；星期日 → 星期一補。"""
    return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d


def holidays(cal, y):
    """cal＝"US"（紐約交易所）或 "UK"（倫敦交易所）嗰年全日休市嘅日子。"""
    e = easter(y); gf = e - dt.timedelta(days=2)
    if cal == "US":
        out = {_obs(dt.date(y, 1, 1)), _nth(y, 1, 0, 3), _nth(y, 2, 0, 3), gf, _last(y, 5, 0), _obs(dt.date(y, 7, 4)), _nth(y, 9, 0, 1),
               _nth(y, 11, 3, 4), _obs(dt.date(y, 12, 25))}
        if y >= 2022:
            out.add(_obs(dt.date(y, 6, 19)))
        if dt.date(y + 1, 1, 1).weekday() == 5:            # 下年元旦喺星期六：紐約交易所唔補假（12-31 照開）
            out.discard(dt.date(y, 12, 31))
        return out
    x = dt.date(y, 12, 25); b = dt.date(y, 12, 26)
    if x.weekday() == 5:
        x, b = dt.date(y, 12, 27), dt.date(y, 12, 28)
    elif x.weekday() == 6:
        x, b = dt.date(y, 12, 27), dt.date(y, 12, 26)
    elif b.weekday() == 5:
        b = dt.date(y, 12, 28)
    ny = dt.date(y, 1, 1); ny = ny + dt.timedelta(days=(7 - ny.weekday()) % 7 if ny.weekday() >= 5 else 0)
    may1 = _nth(y, 5, 0, 1) if y not in (2020,) else dt.date(2020, 5, 8)
    return {ny, gf, e + dt.timedelta(days=1), may1, _last(y, 5, 0), _last(y, 8, 0), x, b}


def trading_days(cal, y, m):
    hol = holidays(cal, y); d = dt.date(y, m, 1); out = []
    while d.month == m:
        if d.weekday() < 5 and d not in hol:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def key_days(cal, y, m):
    """→ (訊號日＝倒數第 6 個交易日, 月尾最後一個交易日)。"""
    td = trading_days(cal, y, m)
    return td[-N_BACK], td[-1]


def side(idx_mtd, bond_mtd):
    """股票跑輸債券 → +1 做多；否則 −1 做空。"""
    return 1 if (idx_mtd - bond_mtd) < 0 else -1


def phase(cal, now_ts, act_min=ACT_UTC_MIN):
    """→ ("enter", 月 key) 喺訊號日 act_min 之後至當日完；("exit", 月 key) 喺月尾日 act_min 之後；否則 (None, 月 key)。月 key＝年×12＋月−1。"""
    t = dt.datetime.fromtimestamp(int(now_ts), dt.timezone.utc); d = t.date(); mk = d.year * 12 + d.month - 1
    sig, last = key_days(cal, d.year, d.month); late = t.hour * 60 + t.minute >= act_min
    if d == sig and late:
        return "enter", mk
    if (d == last and late) or d > last:
        return "exit", mk
    return None, mk
