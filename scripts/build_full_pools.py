#!/usr/bin/env python3
"""全市場候選池（VCP_FULLMARKET_BACKTEST.md 預先登記）→ universes/full/<market>_pool.txt（Yahoo 代號，一行一檔）。

    python3 scripts/build_full_pools.py --market hk     # 在 GitHub Actions 上跑（要連港交所/JPX/Nasdaq）

- 港股：港交所證券名單（中文版 xlsx）「股本」類、代號 < 10000
- 日股：JPX 上場銘柄一覧「プライム／スタンダード／グロース（内国株式）」
- 美股：Nasdaq.com screener 全部股票，去掉名稱含 Warrant/Unit/Right/Preferred/Depositary、代號含 ^ 的
- 再加本倉庫已有的指數歷史成分股（含部分下市、Yahoo 仍有數據的）
名單檔頭記錄來源與日期（快照可追溯）。
"""
import argparse
import io
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from universe import INDICES, Universe  # noqa: E402

OUT = ROOT / "universes" / "full"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36", "Accept": "application/json, text/plain, */*",
      "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
US_EXCLUDE = re.compile(r"warrant|\bunits?\b|\brights?\b|preferred|depositary", re.I)


def pool_hk() -> tuple[list[str], str]:
    import fetch_hkex_names as fh
    asof, zh = fh.parse(fh.download(fh.URL_ZH), ("股份代號", "代號"), ("股份名稱", "名稱"))
    out = [t for t, v in zh.items() if v["category"] == "股本" and int(t.split(".")[0]) < 10000]
    return sorted(out), f"港交所證券名單 {asof}（股本類 {len(out)} 檔）"


def pool_jp() -> tuple[list[str], str]:
    import pandas as pd
    r = requests.get(JPX_URL, headers={"User-Agent": UA["User-Agent"]}, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), engine="openpyxl", dtype=str)
    asof = str(df["日付"].iloc[0])
    keep = df["市場・商品区分"].isin(["プライム（内国株式）", "スタンダード（内国株式）", "グロース（内国株式）"])
    out = sorted(f"{c}.T" for c in df.loc[keep, "コード"])
    return out, f"JPX 上場銘柄一覧 {asof}（内国株式 {len(out)} 檔）"


def pool_us() -> tuple[list[str], str]:
    r = requests.get("https://api.nasdaq.com/api/screener/stocks", headers=UA,
                     params={"tableonly": "true", "download": "true"}, timeout=60)
    r.raise_for_status()
    rows = r.json()["data"]["rows"]
    out = set()
    for x in rows:
        sym, name = x["symbol"].strip(), x.get("name", "")
        if "^" in sym or US_EXCLUDE.search(name) or not sym:
            continue
        out.add(sym.replace("/", "-"))
    return sorted(out), f"Nasdaq.com screener {date.today()}（{len(rows)} 檔，去權證/單位/優先股/存託憑證後 {len(out)} 檔）"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=["hk", "jp", "us"])
    args = ap.parse_args()
    listed, src = {"hk": pool_hk, "jp": pool_jp, "us": pool_us}[args.market]()
    hist = set()
    for key, cfg in INDICES.items():
        if cfg["market"] == args.market:
            hist |= set(Universe(key).all_tickers())
    extra = sorted(hist - set(listed))
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{args.market}_pool.txt"
    p.write_text(f"# {src}；另加指數歷史成分股 {len(extra)} 檔（今天不在名單上）\n"
                 + "\n".join(sorted(set(listed) | hist)) + "\n", encoding="utf-8")
    print(f"{args.market}: {src} + 指數歷史 {len(extra)} → {p}")


if __name__ == "__main__":
    main()
