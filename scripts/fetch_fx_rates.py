#!/usr/bin/env python3
"""各國短期利率（利差策略用）：FRED 上的 OECD 三個月銀行同業拆息（月）與即期／隔夜利率（月），另加幾個日頻政策利率作備援。
另抓新資訊序列（OECD 十年期殖利率、美國 2 年／10 年、VIX／EVZ／VXEEM）→ data_forex_rates/info/；
另抓 BIS 實質有效匯率（價值因子用；FRED 轉載，月，2020=100）：寬口徑 RB<國>BIS（1994 起）與窄口徑 RN<國>BIS（1964 起）→ data_forex_rates/reer/。
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
    # 新興市場／其他 G10（外匯基金新宇宙）：OECD 三個月同業拆息、即期利率；沒有 OECD 的用 IMF 貼現／政策利率（INTDSR）
    "MXN": ["IR3TIB01MXM156N", "IRSTCI01MXM156N", "INTDSRMXM193N"],
    "ZAR": ["IR3TIB01ZAM156N", "IRSTCI01ZAM156N", "INTDSRZAM193N"],
    "TRY": ["IR3TIB01TRM156N", "IRSTCI01TRM156N", "INTDSRTRM193N"],
    "PLN": ["IR3TIB01PLM156N", "IRSTCI01PLM156N", "INTDSRPLM193N"],
    "HUF": ["IR3TIB01HUM156N", "IRSTCI01HUM156N", "INTDSRHUM193N"],
    "CZK": ["IR3TIB01CZM156N", "IRSTCI01CZM156N", "INTDSRCZM193N"],
    "SEK": ["IR3TIB01SEM156N", "IRSTCI01SEM156N", "INTDSRSEM193N"],
    "NOK": ["IR3TIB01NOM156N", "IRSTCI01NOM156N", "INTDSRNOM193N"],
    "DKK": ["IR3TIB01DKM156N", "IRSTCI01DKM156N", "INTDSRDKM193N"],
    "RON": ["IR3TIB01ROM156N", "IRSTCI01ROM156N", "INTDSRROM193N"],
    "ILS": ["IR3TIB01ILM156N", "IRSTCI01ILM156N", "INTDSRILM193N"],
    "THB": ["IR3TIB01THM156N", "IRSTCI01THM156N", "INTDSRTHM193N"],
    "BRL": ["IR3TIB01BRM156N", "IRSTCI01BRM156N", "INTDSRBRM193N"],
    "INR": ["IR3TIB01INM156N", "IRSTCI01INM156N", "INTDSRINM193N"],
    "KRW": ["IR3TIB01KRM156N", "IRSTCI01KRM156N", "INTDSRKRM193N"],
    "CNY": ["IR3TIB01CNM156N", "IRSTCI01CNM156N", "INTDSRCNM193N"],
}
# 新資訊來源（央行路徑／風險情緒）：OECD 十年期公債殖利率（月）、美國 2 年／10 年（日）、VIX、歐元波動指數 EVZ
INFO_SERIES = {
    "10y": [f"IRLTLT01{k}M156N" for k in ["US", "EZ", "GB", "JP", "CH", "AU", "NZ", "CA", "MX", "ZA", "TR", "PL", "HU", "CZ",
                                          "SE", "NO", "DK", "IL", "KR", "IN", "BR", "CN"]],
    "us_daily": ["DGS2", "DGS10", "DGS1", "DFF"],
    "vol": ["VIXCLS", "EVZCLS", "VXEEMCLS", "OVXCLS"],
}
# 貨幣 → BIS 實質有效匯率（寬口徑 broad 61 國、窄口徑 narrow 27 國）；歐元用歐元區 XM
REER_SERIES = {
    "USD": ["RBUSBIS", "RNUSBIS"],
    "EUR": ["RBXMBIS", "RNXMBIS"],
    "GBP": ["RBGBBIS", "RNGBBIS"],
    "JPY": ["RBJPBIS", "RNJPBIS"],
    "CHF": ["RBCHBIS", "RNCHBIS"],
    "AUD": ["RBAUBIS", "RNAUBIS"],
    "NZD": ["RBNZBIS", "RNNZBIS"],
    "CAD": ["RBCABIS", "RNCABIS"],
    "SGD": ["RBSGBIS", "RNSGBIS"],
    "MXN": ["RBMXBIS", "RNMXBIS"], "ZAR": ["RBZABIS", "RNZABIS"], "TRY": ["RBTRBIS", "RNTRBIS"], "PLN": ["RBPLBIS", "RNPLBIS"],
    "HUF": ["RBHUBIS", "RNHUBIS"], "CZK": ["RBCZBIS", "RNCZBIS"], "SEK": ["RBSEBIS", "RNSEBIS"], "NOK": ["RBNOBIS", "RNNOBIS"],
    "DKK": ["RBDKBIS", "RNDKBIS"], "RON": ["RBROBIS", "RNROBIS"], "ILS": ["RBILBIS", "RNILBIS"], "THB": ["RBTHBIS", "RNTHBIS"],
    "BRL": ["RBBRBIS", "RNBRBIS"], "INR": ["RBINBIS", "RNINBIS"], "KRW": ["RBKRBIS", "RNKRBIS"], "CNY": ["RBCNBIS", "RNCNBIS"],
    "HKD": ["RBHKBIS", "RNHKBIS"],
}


def fetch_series(sid: str) -> "pd.DataFrame | None":
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60)
    if r.status_code != 200 or not r.text.startswith("observation_date") and not r.text.startswith("DATE"):
        return None
    s = pd.read_csv(io.StringIO(r.text), na_values=["."])
    s.columns = ["Date", "Value"]
    return s.dropna()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "reer").mkdir(exist_ok=True)
    (OUT / "info").mkdir(exist_ok=True)
    ok, bad = [], []
    for table, out_dir in [(SERIES, OUT), (REER_SERIES, OUT / "reer"), (INFO_SERIES, OUT / "info")]:
        for ccy, ids in table.items():
            for sid in ids:
                try:
                    s = fetch_series(sid)
                    if s is None:
                        bad.append(sid)
                        continue
                    s.to_csv(out_dir / f"{sid}.csv", index=False)
                    ok.append(f"{ccy} {sid} {len(s)} 筆 {s.Date.iloc[0]}→{s.Date.iloc[-1]}")
                except Exception as exc:  # noqa: BLE001
                    bad.append(f"{sid}({exc!r})")
    (OUT / "_status.txt").write_text("\n".join(ok + [f"失敗 {b}" for b in bad]) + "\n", encoding="utf-8")
    print("\n".join(ok))
    print("失敗：", bad)
    sys.exit(0)


if __name__ == "__main__":
    main()
