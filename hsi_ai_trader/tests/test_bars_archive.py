"""[R218] 1 分鐘 K 線存檔：分日、分頁、只上載有改動嘅日子。執行：python -m pytest tests -q"""
import json
import sys
import types
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "futu" not in sys.modules:                     # 本機冇 futu-api：用假模組
    class _C:
        def __getattr__(self, n):
            return n
    fake = types.ModuleType("futu")
    for n in ("OpenQuoteContext", "OpenFutureTradeContext", "OpenSecTradeContext", "Market", "SecurityType",
              "KLType", "AuType", "TrdEnv", "TrdSide", "TrdMarket", "OrderType", "ModifyOrderOp", "OrderStatus",
              "SecurityFirm", "PositionSide"):
        setattr(fake, n, _C())
    fake.RET_OK = 0
    sys.modules["futu"] = fake
import bars_archive as ba  # noqa: E402


def _df(keys):
    return pd.DataFrame([{"time_key": k, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10} for k in keys])


class FakeQuote:
    def __init__(self):
        self.calls = []

    def request_history_kline(self, code, start=None, end=None, ktype=None, autype=None, max_count=1000,
                              page_req_key=None, extended_time=False):
        self.calls.append((code, page_req_key, extended_time))
        if page_req_key is None:
            return 0, _df(["2026-10-15 20:00:00", "2026-10-16 04:00:00"]), "p2"
        return 0, _df(["2026-10-16 04:01:00", "2026-10-16 04:00:00"]), None


def test_codes_and_products(monkeypatch):
    assert ba.quote_code("SPY") == "US.SPY" and ba.quote_code("HSI") == "HK.HSImain"
    monkeypatch.setenv("LONGFEI_EXTRA_PRODUCTS", "spy,QQQ,XXX")
    monkeypatch.setenv("LONGFEI_REAL_PRODUCTS", "SPY,HSI")
    assert ba.products_from_env() == ["HSI", "SPY", "QQQ"]


def test_run_pages_splits_days_and_uploads_only_changes(tmp_path, monkeypatch):
    q, sent = FakeQuote(), []
    monkeypatch.setattr(ba, "REQ_GAP_SEC", 0)
    monkeypatch.setattr(ba, "upload", lambda url, tok, p, d, bars: sent.append((p, d, bars)) or True)
    s = ba.run(q, ["SPY"], 6, tmp_path, "https://x", "tok", today=date(2026, 10, 17))
    assert [c[1] for c in q.calls] == [None, "p2"] and q.calls[0][2] is True     # 分頁、美股包盤前盤後
    assert [(p, d) for p, d, _ in sent] == [("SPY", "2026-10-15"), ("SPY", "2026-10-16")]
    assert [b[0] for b in sent[1][2]] == ["04:00", "04:01"]                          # 排序、同一分鐘去重
    assert json.loads((tmp_path / "SPY" / "2026-10-16.json").read_text())[0] == ["04:00", 1.0, 2.0, 0.5, 1.5, 10.0]
    assert s["SPY"].startswith("4 條")
    sent.clear()
    ba.run(q, ["SPY"], 6, tmp_path, "https://x", "tok", today=date(2026, 10, 17))
    assert sent == []                                                                # 冇改動唔再上載
    ba.run(FakeQuote(), ["HSI"], 6, tmp_path, "", "", today=date(2026, 10, 17))
    assert (tmp_path / "HSI" / "2026-10-15.json").exists() and sent == []           # 冇網址：只寫部機
