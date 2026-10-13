"""pattern_data.py — 抓 pattern_scan 產品池全部歷史日線（yfinance max），存 data/pattern_scan/<代號>_daily.csv.gz。

畀 `pattern_scan.py --backtest --csv-dir data/pattern_scan` 做多市場回測（雲端工作階段連唔到 Yahoo，所以喺 Actions 抓）。
用法：python3 scripts/pattern_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pattern_scan import UNIVERSE, clean, file_key  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "pattern_scan"


def main() -> int:
    import yfinance as yf
    OUT.mkdir(parents=True, exist_ok=True)
    bad = []
    for sym, name, _, _ in UNIVERSE:
        try:
            df = clean(yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=False, actions=False))
            df = df[(df["High"] > df["Low"])]  # 去掉早年只有收市價嘅日子
            path = OUT / (file_key(sym) + "_daily.csv.gz")
            df.to_csv(path, float_format="%.6g", date_format="%Y-%m-%d", compression="gzip")
            print(f"{sym} {name}: {len(df)} 列 {df.index[0].date()} → {df.index[-1].date()}")
        except Exception as e:
            bad.append(sym)
            print(f"⚠ {sym}: {e}")
    return 1 if len(bad) > len(UNIVERSE) // 2 else 0


if __name__ == "__main__":
    sys.exit(main())
