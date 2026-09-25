#!/usr/bin/env python3
"""各國短期利率（利差策略用）：FRED 上的 OECD 三個月銀行同業拆息（月）與即期／隔夜利率（月），另加幾個日頻政策利率作備援。
輸出 data_forex_rates/<系列>.csv（Date,Value；小檔，進 git）。沙盒連不到 FRED，在 GitHub Actions（fetch_fx_rates.yml）跑。

    python3 scripts/fetch_fx_rates.py
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_forex_rates"
# 貨幣 → (三個月同業拆息 月, 即期利率 月, 日頻備援)
SERIES = {
    "USD": ["IR3TIB01USM156N", "IRSTCI01USM156N", "DTB3", "FEDFUNDS"],
    "EUR": ["IR3TIB01EZM156N", "IRSTCI01EZM156N", "ECBDFR", "ECBMRRFR"],
    "GBP": ["IR3TIB01GBM156N", "IRSTCI01GBM156N", "IUDSOIA", "BOERUKM"],
    "JPY": ["IR3TIB01JPM156N", "IRSTCI01JPM156N", "IRSTCB01JPM156N"],
    "CHF": ["IR3TIB01CHM156N", "IRSTCI01CHM156N", "IRSTCB01CHM156N"],
    "AUD": ["IR3TIB01AUM156N", "IRSTCI01AUM156N", "IRSTCB01AUM156N"],
    "NZD": ["IR3TIB01NZM156N", "IRSTCI01NZM156N", "IRSTCB01NZM156N"],
    "CAD": ["IR3TIB01CAM156N", "IRSTCI01CAM156N", "IRSTCB01CAM156N"],
    "SGD": ["IR3TIB01SGM156N", "IRSTCI01SGM156N"],
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    ok, bad = [], []
    for ccy, ids in SERIES.items():
        for sid in ids:
            try:
                r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60)
                if r.status_code != 200 or not r.text.startswith("observation_date") and not r.text.startswith("DATE"):
                    bad.append(sid)
                    continue
                s = pd.read_csv(io.StringIO(r.text), na_values=["."])
                s.columns = ["Date", "Value"]
                s = s.dropna()
                s.to_csv(OUT / f"{sid}.csv", index=False)
                ok.append(f"{ccy} {sid} {len(s)} 筆 {s.Date.iloc[0]}→{s.Date.iloc[-1]}")
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{sid}({exc!r})")
    (OUT / "_status.txt").write_text("\n".join(ok + [f"失敗 {b}" for b in bad]) + "\n", encoding="utf-8")
    print("\n".join(ok))
    print("失敗：", bad)
    sys.exit(0)


if __name__ == "__main__":
    main()
