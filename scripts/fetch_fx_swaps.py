#!/usr/bin/env python3
"""公開的券商外匯隔夜利息（swap／financing）表——用來反算「券商加價 = 券商 swap（年化%）− 銀行間三個月利差」。
沙盒連不到，這個在 GitHub Actions（fetch_fx_swaps.yml）跑；抓到的原始回應存 data_forex_rates/swaps/<來源>_<日期>.*，之後再解析。

來源（能抓到甚麼就存甚麼，失敗不中斷）：
- Dukascopy Bank：市場觀察 overnight（swap points）幾個候選端點
- Interactive Brokers：外匯基準利率與分層加減碼頁（HTML）
- OANDA：融資利率頁（HTML／JSON 候選）
- Saxo、IG、Pepperstone：swap 頁候選（多為 JS 動態，先探）
"""
import datetime as dt
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_forex_rates" / "swaps"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "text/html,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
CANDIDATES = {
    "dukascopy_overnights_plugin": "https://www.dukascopy.com/plugins/fxMarketWatch/?type=overnights",
    "dukascopy_overnights_page": "https://www.dukascopy.com/swiss/english/marketwatch/overnights/",
    "dukascopy_freeserv_overnights": "https://freeserv.dukascopy.com/2.0/index.php?path=common/overnights&jsonp=",
    "dukascopy_freeserv_instruments": "https://freeserv.dukascopy.com/2.0/index.php?path=common/instruments&jsonp=",
    "dukascopy_swap_policy": "https://www.dukascopy.com/swiss/english/forex/trading/rollover/",
    "ibkr_interest_rates": "https://www.interactivebrokers.com/en/accounts/fees/pricing-interest-rates.php",
    "ibkr_benchmark": "https://www.interactivebrokers.com/en/trading/margin-rates.php",
    "oanda_financing": "https://www.oanda.com/us-en/trading/spreads-margin/financing-rates/",
    "oanda_financing_api": "https://www.oanda.com/bvi-ft/trading/spreads-margin/",
    "saxo_swap": "https://www.home.saxo/rates-and-conditions/forex/spreads-and-commissions",
    "ig_swap": "https://www.ig.com/uk/forex/spread-betting-forex-rates",
    "pepperstone_swap": "https://pepperstone.com/en/trading-conditions/swap-rates/",
    "icmarkets_swap": "https://www.icmarkets.com/global/en/trading-conditions/swap-rates",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    log = []
    for name, url in CANDIDATES.items():
        try:
            r = requests.get(url, headers=UA, timeout=60, allow_redirects=True)
            ct = r.headers.get("content-type", "")
            ext = "json" if "json" in ct or r.text.lstrip().startswith(("{", "[")) else "html"
            (OUT / f"{name}_{today}.{ext}").write_bytes(r.content)
            log.append(f"{name}: HTTP {r.status_code} {len(r.content)} bytes {ct[:40]} → {r.url[:90]}")
        except Exception as exc:  # noqa: BLE001
            log.append(f"{name}: 失敗 {exc!r}")
    (OUT / f"_probe_{today}.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    sys.exit(0)


if __name__ == "__main__":
    main()
