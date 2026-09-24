#!/usr/bin/env python3
"""樣本外驗證（OOS_VALIDATION.md）新市場候選池 → universes/full/<market>_pool.txt（Yahoo 代號，一行一檔）。

    python3 scripts/build_oos_pools.py --market tw     # 在 GitHub Actions 上跑（要連交易所網站）

- 台灣：證交所 ISIN 清單（上市 strMode=2 → .TW；上櫃 strMode=4 → .TWO），CFI 代碼 ESVUFR（普通股）、4 位數代號
- 韓國：KRX KIND 上市公司清單（KOSPI → .KS、KOSDAQ → .KQ；不含 KONEX），去掉 SPAC（스팩）；失敗改用 FinanceDataReader
- 澳洲：ASX 上市公司清單（ASXListedCompanies.csv；失敗改用 ASX 研究 API 的公司目錄）
- 第二輪：加拿大 TSX 公司目錄 → .TO；印度 NSE EQUITY_L.csv（SERIES EQ）→ .NS；新加坡 SGX 證券 API（股票＋REIT）→ .SI
- 另加基準 ETF 與指數一起抓（見 EXTRA）
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
EXTRA = {"tw": ["0050.TW", "^TWII"], "kr": ["069500.KS", "^KS11"], "au": ["STW.AX", "^AXJO"],
         # 第二輪（OOS_VALIDATION.md 第三部分）
         "ca": ["XIU.TO", "^GSPTSE"], "in": ["NIFTYBEES.NS", "^NSEI"], "sg": ["ES3.SI", "^STI"]}
CA_EXCLUDE = re.compile(r"\bETF\b|\bfund\b|\bindex\b|portfolio|\bnotes?\b|warrant|debenture|preferred|\bpref\b|\bsplit\b", re.I)


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


def pool_ca() -> tuple[list[str], str]:
    """TSX 主板公司目錄（JSON）；代號 BBD.B → BBD-B.TO、REI.UN → REI-UN.TO；去掉 ETF／基金／優先股／權證／債券／美元線。"""
    r = get("https://www.tsx.com/json/company-directory/search/tsx/%5E*")
    res = r.json().get("results", [])
    out = set()
    for co in res:
        for ins in co.get("instruments") or [{"symbol": co.get("symbol"), "name": co.get("name")}]:
            sym, nm = str(ins.get("symbol") or "").strip(), str(ins.get("name") or co.get("name") or "")
            if not sym or CA_EXCLUDE.search(nm) or re.search(r"\.(PR|DB|WT|NT|RT|U|WS)(\.|$)", sym):
                continue
            out.add(sym.replace(".", "-") + ".TO")
    print(f"加拿大：公司 {len(res)} → {len(out)} 個代號（例：{sorted(out)[:5]}）", file=sys.stderr)
    return sorted(out), f"TSX 公司目錄 {date.today()}（{len(out)} 個代號）"


def pool_in() -> tuple[list[str], str]:
    last = None
    for url in ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
                "https://www1.nseindia.com/content/equities/EQUITY_L.csv"):
        try:
            r = get(url)
            df = pd.read_csv(io.StringIO(r.content.decode("utf-8", errors="replace")))
            df.columns = [str(c).strip() for c in df.columns]
            eq = df[df["SERIES"].astype(str).str.strip() == "EQ"]
            out = sorted({f"{x.strip()}.NS" for x in eq["SYMBOL"].astype(str)})
            print(f"印度：{len(df)} 列 → EQ {len(out)} 檔（{url}）", file=sys.stderr)
            return out, f"NSE EQUITY_L.csv {date.today()}（SERIES EQ {len(out)} 檔）"
        except Exception as exc:
            last = exc
            print(f"WARN {url} 失敗（{exc}）", file=sys.stderr)
    raise SystemExit(f"印度候選池全部來源失敗：{last}")


def pool_sg() -> tuple[list[str], str]:
    last = None
    for host in ("https://api.sgx.com", "https://api2.sgx.com"):
        try:
            r = get(f"{host}/securities/v1.1", params={"excludetypes": "bonds", "params": "nc,n,type"})
            rows = (r.json().get("data") or {}).get("prices") or []
            kinds = {}
            out = set()
            for x in rows:
                kinds[x.get("type")] = kinds.get(x.get("type"), 0) + 1
                if str(x.get("type", "")).lower() in ("stocks", "reits") and x.get("nc"):
                    out.add(f"{str(x['nc']).strip()}.SI")
            print(f"新加坡：{len(rows)} 列、類別 {kinds} → {len(out)} 檔（{host}）", file=sys.stderr)
            return sorted(out), f"SGX 證券 API {date.today()}（股票＋REIT {len(out)} 檔）"
        except Exception as exc:
            last = exc
            print(f"WARN {host} 失敗（{exc}）", file=sys.stderr)
    raise SystemExit(f"新加坡候選池全部來源失敗：{last}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=list(EXTRA))
    m = ap.parse_args().market
    pool, src = {"tw": pool_tw, "kr": pool_kr, "au": pool_au, "ca": pool_ca, "in": pool_in, "sg": pool_sg}[m]()
    if len(pool) < (150 if m == "sg" else 300):
        raise SystemExit(f"{m} 候選池只有 {len(pool)} 檔，來源可能改版，先查清楚")
    pool = sorted(set(pool) | set(EXTRA[m]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{m}_pool.txt").write_text(f"# {src}；另加基準 {'、'.join(EXTRA[m])}\n" + "\n".join(pool) + "\n",
                                       encoding="utf-8")
    print(f"{m}：候選池 {len(pool)} 檔 → universes/full/{m}_pool.txt")


if __name__ == "__main__":
    main()
