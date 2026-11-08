"""[R372] futu_positions_quote.expired：已到期期權／月份合約唔計入持倉（11-07 週權殘留事故）。"""
import datetime as dt
import sys
import types

sys.path.insert(0, "/home/user/20260918/gcp_ib")
if "futu" not in sys.modules:                # CI／雲端冇裝 futu：只測純函數，用假模組頂住 import
    try:
        import futu                          # noqa: F401
    except ImportError:
        sys.modules["futu"] = types.SimpleNamespace(**{k: object for k in (
            "IndexOptionType OpenFutureTradeContext OpenQuoteContext OpenSecTradeContext RET_OK TrdEnv TrdMarket "
            "SecurityType Market OptionType KLType AuType").split()})
import futu_positions_quote as fpq          # noqa: E402

T = dt.date(2026, 11, 7)
CASES = [
    ("HK.HSI261030C23750000", True), ("HK.HSI261023P23700000", True),   # 事故嗰幾隻
    ("HK.HSI261107P25000000", False),                                    # 今日到期：仲計
    ("HK.HSI261127C26000000", False), ("US.RDDT261127P80000", False),
    ("US.QQQ261102C688000", True),
    ("HK.MHI2610", True), ("HK.MHI2611", False),
    ("US.EW2610P7750x0", True), ("US.EW2611P7700x0", False), ("US.EX12611C7800x0", False),
    ("US.ES2609", True), ("US.MES2612", False),
    ("US.QQQ", False), ("US.SPY", False), ("HK.800000", False), ("", False),
]


def test_expired():
    bad = [(c, want) for c, want in CASES if fpq.expired(c, T) != want]
    assert not bad, bad


STOCKS = [("US.SPCX", True), ("US.QQQ", True), ("HK.00700", True), ("HK.800000", True),
          ("HK.HSI2611", False), ("HK.MHI2611", False), ("US.RDDT261127P80000", False), ("US.EW2611P7700x0", False),
          ("US.MES2612", False), ("", False)]


def test_is_stock():                         # [R376] 正股先略過負數成交淨計
    bad = [(c, want) for c, want in STOCKS if fpq.is_stock(c) != want]
    assert not bad, bad


if __name__ == "__main__":
    test_expired()
    test_is_stock()
    print(f"OK {len(CASES)}＋{len(STOCKS)}")
