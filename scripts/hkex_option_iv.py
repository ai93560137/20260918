"""港交所衍生產品每日報告：恒指期權（含週期權）每個系列的結算價與引伸波幅，給風揚陣方向一（賣波幅）校準用。

Futu 期權歷史 K 線只有十幾根、不含 IV；港交所每日報告（www.hkex.com.hk/eng/stat/dmstat/dayrpt/<產品><yymmdd>.htm）
有每個系列的 OPEN／HIGH／LOW／SETTLE／IV／VOLUME／OI，歷史可回溯多年。雲端工作階段連不到 hkex.com.hk，
由 GitHub Actions（.github/workflows/hkex_option_iv.yml）跑這個腳本，再把結果 commit 回分支。

用法：
  python3 scripts/hkex_option_iv.py probe 2026-10-02            # 試幾個產品代號的網址，存樣本到 data/hkex_options/sample/
  python3 scripts/hkex_option_iv.py fetch 2023-10-01 2026-10-03 # 逐日下載（只存解析後的 CSV，原始檔不進 git）
"""
import argparse, gzip, os, re, sys, time, urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = "https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/"
OUT = Path(__file__).resolve().parents[1] / "data" / "hkex_options"
PRODUCTS = ("hsio", "hsiwo", "hsif", "mhio", "hhio", "dqe")      # 恒指期權、恒指週期權(?)、恒指期貨、小型恒指期權、國指期權、股票期權摘要
UA = {"User-Agent": "Mozilla/5.0 (research; github actions)"}


def yymmdd(d):
    return d.strftime("%y%m%d")


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except Exception as exc:                                        # 連線問題：當作暫時失敗
        return -1, str(exc).encode()


def to_text(raw):
    txt = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    txt = re.sub(r"<[^>]+>", "", txt)                               # 報告是 <pre> 包的純文字
    return txt.replace("&nbsp;", " ").replace("&amp;", "&")


def probe(day):
    d = date.fromisoformat(day)
    (OUT / "sample").mkdir(parents=True, exist_ok=True)
    for p in PRODUCTS:
        url = f"{BASE}{p}{yymmdd(d)}.htm"
        st, raw = get(url)
        print(f"{p}: HTTP {st} {len(raw)} bytes  {url}")
        if st == 200 and len(raw) > 500:
            txt = to_text(raw)
            (OUT / "sample" / f"{p}{yymmdd(d)}.txt").write_text(txt, encoding="utf-8")
            lines = [l for l in txt.splitlines() if l.strip()]
            print("\n".join("   | " + l[:150] for l in lines[:45]))
            print(f"   ... 共 {len(lines)} 行")
        time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("probe"); s.add_argument("day")
    f = sub.add_parser("fetch"); f.add_argument("start"); f.add_argument("end"); f.add_argument("--products", default="hsio")
    a = ap.parse_args()
    if a.cmd == "probe":
        probe(a.day)
    else:
        import hkex_option_parse as hp                                  # 解析器在看過樣本後才寫（第二階段）
        hp.fetch(a.start, a.end, a.products.split(","), OUT, get, to_text)


if __name__ == "__main__":
    main()
