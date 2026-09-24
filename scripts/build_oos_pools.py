#!/usr/bin/env python3
"""樣本外驗證（OOS_VALIDATION.md）新市場候選池 → universes/full/<market>_pool.txt（Yahoo 代號，一行一檔）。

    python3 scripts/build_oos_pools.py --market tw     # 在 GitHub Actions 上跑（要連交易所網站）

- 台灣：證交所 ISIN 清單（上市 strMode=2 → .TW；上櫃 strMode=4 → .TWO），CFI 代碼 ESVUFR（普通股）、4 位數代號
- 韓國：KRX KIND 上市公司清單（KOSPI → .KS、KOSDAQ → .KQ；不含 KONEX），去掉 SPAC（스팩）；失敗改用 FinanceDataReader
- 澳洲：ASX 上市公司清單（ASXListedCompanies.csv；失敗改用 ASX 研究 API 的公司目錄）
- 另加基準 ETF 與指數（0050.TW／^TWII、069500.KS／^KS11、STW.AX／^AXJO）一起抓
名單檔頭記錄來源與日期。
"""
import argparse
import io
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "universes" / "full"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
EXTRA = {"tw": ["0050.TW", "^TWII"], "kr": ["069500.KS", "^KS11"], "au": ["STW.AX", "^AXJO"]}


def get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=90, **kw)
    r.raise_for_status()
    return r


def pool_tw() -> tuple[list[str], str]:
    out, n = [], {}
    for mode, suf in ((2, ".TW"), (4, ".TWO")):
        r = get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}")
        html = r.content.decode("cp950", errors="replace")
        tabs = pd.read_html(io.StringIO(html), header=0)
        df = max(tabs, key=len)
        df.columns = [str(c).strip() for c in df.columns]
        first = df.columns[0]                      # 「有價證券代號及名稱」
        cfi = next(c for c in df.columns if "CFI" in c)
        k = 0
        for name, code in zip(df[first].astype(str), df[cfi].astype(str)):
            m = re.match(r"^(\d{4})[\s　]", name)
            if m and code.strip() == "ESVUFR":
                out.append(m.group(1) + suf)
                k += 1
        n[suf] = k
        print(f"台灣 strMode={mode}：{len(df)} 列 → 普通股 {k} 檔（例：{out[-3:]}）", file=sys.stderr)
    return sorted(set(out)), f"證交所 ISIN 清單 {date.today()}（上市 {n['.TW']}、上櫃 {n['.TWO']} 檔普通股）"


def pool_kr() -> tuple[list[str], str]:
    out = []
    try:
        for mkt, suf in (("stockMkt", ".KS"), ("kosdaqMkt", ".KQ")):
            r = get("https://kind.krx.co.kr/corpgeneral/corpList.do",
                    params={"method": "download", "searchType": "13", "marketType": mkt})
            html = r.content.decode("euc-kr", errors="replace")
            df = pd.read_html(io.StringIO(html), header=0)[0]
            code = next(c for c in df.columns if "종목코드" in str(c))
            name = next(c for c in df.columns if "회사명" in str(c))
            k = 0
            for nm, c in zip(df[name].astype(str), df[code]):
                if "스팩" in nm:
                    continue
                out.append(f"{int(c):06d}{suf}")
                k += 1
            print(f"韓國 {mkt}：{len(df)} 列 → {k} 檔（例：{out[-3:]}）", file=sys.stderr)
        src = "KRX KIND 上市公司清單"
    except Exception as exc:      # 後備：FinanceDataReader（KRX 資料 API）
        print(f"WARN KIND 失敗（{exc}），改用 FinanceDataReader", file=sys.stderr)
        import FinanceDataReader as fdr
        out = []
        for mkt, suf in (("KOSPI", ".KS"), ("KOSDAQ", ".KQ")):
            df = fdr.StockListing(mkt)
            code = next(c for c in ("Code", "Symbol") if c in df.columns)
            nm = next((c for c in ("Name",) if c in df.columns), None)
            for i, c in enumerate(df[code].astype(str)):
                if nm and "스팩" in str(df[nm].iloc[i]):
                    continue
                if re.fullmatch(r"\d{6}", c) and c.endswith("0"):      # 普通股代號尾數 0（優先股 5/7/9 等）
                    out.append(c + suf)
            print(f"韓國 {mkt}（FDR）：{len(df)} 列", file=sys.stderr)
        src = "FinanceDataReader StockListing"
    ks, kq = sum(t.endswith(".KS") for t in out), sum(t.endswith(".KQ") for t in out)
    return sorted(set(out)), f"{src} {date.today()}（KOSPI {ks}、KOSDAQ {kq} 檔，去掉 SPAC）"


def pool_au() -> tuple[list[str], str]:
    codes = []
    try:
        r = get("https://www.asx.com.au/asx/research/ASXListedCompanies.csv")
        text = r.content.decode("utf-8", errors="replace")
        lines = text.splitlines()
        start = next(i for i, l in enumerate(lines) if "ASX code" in l)
        df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
        codes = df["ASX code"].astype(str).str.strip().tolist()
        src = "ASX ASXListedCompanies.csv"
    except Exception as exc:
        print(f"WARN ASXListedCompanies.csv 失敗（{exc}），改用 ASX 研究 API", file=sys.stderr)
        r = get("https://asx.api.markitdigital.com/asx-research/1.0/companies/directory/file",
                params={"access_token": "83ff96335c2d45a094df02a206a39ff4"})
        df = pd.read_csv(io.StringIO(r.content.decode("utf-8", errors="replace")))
        col = next(c for c in df.columns if str(c).strip().lower() in ("asx code", "code", "symbol"))
        codes = df[col].astype(str).str.strip().tolist()
        src = "ASX 研究 API 公司目錄"
    out = sorted({f"{c}.AX" for c in codes if re.fullmatch(r"[A-Z0-9]{3}", c)})
    print(f"澳洲：{len(codes)} 列 → {len(out)} 檔（例：{out[:3]}）", file=sys.stderr)
    return out, f"{src} {date.today()}（{len(out)} 檔）"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=["tw", "kr", "au"])
    m = ap.parse_args().market
    pool, src = {"tw": pool_tw, "kr": pool_kr, "au": pool_au}[m]()
    if len(pool) < 300:
        raise SystemExit(f"{m} 候選池只有 {len(pool)} 檔，來源可能改版，先查清楚")
    pool = sorted(set(pool) | set(EXTRA[m]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{m}_pool.txt").write_text(f"# {src}；另加基準 {'、'.join(EXTRA[m])}\n" + "\n".join(pool) + "\n",
                                       encoding="utf-8")
    print(f"{m}：候選池 {len(pool)} 檔 → universes/full/{m}_pool.txt")


if __name__ == "__main__":
    main()
