"""[R377] futu_positions_quote.read_holdings：持倉查詢成功但冇倉 → n_ok > 0（auto_risk 唔當「讀富途失敗」）；查詢失敗 → n_ok = 0。"""
import sys
import types
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gcp_ib"))
if "futu" not in sys.modules:                # CI／雲端冇裝 futu：用假模組頂住 import
    try:
        import futu                          # noqa: F401
    except ImportError:
        sys.modules["futu"] = types.SimpleNamespace(**{k: object for k in (
            "IndexOptionType OpenFutureTradeContext OpenQuoteContext OpenSecTradeContext RET_OK TrdEnv TrdMarket "
            "SecurityType Market OptionType KLType AuType").split()})
import futu_positions_quote as fpq          # noqa: E402

if not hasattr(fpq.TrdEnv, "REAL"):          # 假模組冇 TrdEnv.REAL
    fpq.TrdEnv = types.SimpleNamespace(REAL="REAL")
OK, ERR = fpq.RET_OK, "ERR"


class Ctx:
    def __init__(self, pos_ret, pos_df):
        self.pos_ret, self.pos_df = pos_ret, pos_df

    def accinfo_query(self, **k):
        return OK, pd.DataFrame([{"currency": "HKD", "total_assets": 100.0, "maintenance_margin": 0.0}])

    def position_list_query(self, **k):
        return self.pos_ret, self.pos_df

    def history_deal_list_query(self, **k):
        return OK, pd.DataFrame()

    def close(self):
        pass


def run(ctx):
    fpq.contexts = lambda: iter([("期貨帳戶", ctx)])
    fpq.real_accounts = lambda c: [{"acc_id": 1, "acc_status": "ACTIVE"}]
    return fpq.read_holdings("2026-11-01")


def test_flat_account_is_ok():               # 11-09 15:42：HSI2611 平咗（qty 0）、MNQ 未開
    df = pd.DataFrame([{"code": "HK.HSI2611", "qty": 0.0, "position_side": "SHORT"}])
    rows, accounts, n_ok = run(Ctx(OK, df))
    assert rows == [] and accounts and n_ok == 1


def test_query_failure_is_not_ok():
    rows, accounts, n_ok = run(Ctx(ERR, "频率太高"))
    assert rows == [] and n_ok == 0


def test_position_kept():
    df = pd.DataFrame([{"code": "US.MNQ2612", "qty": 2.0, "position_side": "SHORT", "cost_price": 1.0}])
    rows, _, n_ok = run(Ctx(OK, df))
    assert n_ok == 1 and [(r["code"], r["qty"]) for r in rows] == [("US.MNQ2612", -2.0)]


if __name__ == "__main__":
    for f in (test_flat_account_is_ok, test_query_failure_is_not_ok, test_position_kept):
        f()
    print("ok")
