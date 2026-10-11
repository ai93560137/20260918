"""港交所衍生產品每日報告：恒指期權（含週期權）每個系列的結算價與引伸波幅，給風揚陣方向一（賣波幅）校準用。

Futu 期權歷史 K 線只有十幾根、不含 IV；港交所每日報告（www.hkex.com.hk/eng/stat/dmstat/dayrpt/<產品><yymmdd>.htm）
有每個系列的 OPEN／HIGH／LOW／SETTLE／IV／VOLUME／OI；**網站只保留約 12 個月**（2026-10 試過：2025-10-02 之前全部 404），
所以 workflow 每週排程續抓，讓數據往後累積。雲端工作階段連不到 hkex.com.hk，
由 GitHub Actions（.github/workflows/hkex_option_iv.yml）跑這個腳本，再把結果 commit 回分支。

用法：
  python3 scripts/hkex_option_iv.py probe 2026-10-02            # 試幾個產品代號的網址，存樣本到 data/hkex_options/sample/
  python3 scripts/hkex_option_iv.py fetch 2023-10-01 2026-10-03 # 逐日下載（只存解析後的 CSV，原始檔不進 git）
"""
import argparse, gzip, os, re, sys, time, urllib.parse, urllib.request
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


def probe(day, products=None):
    d = date.fromisoformat(day)
    (OUT / "sample").mkdir(parents=True, exist_ok=True)
    for p in (products or PRODUCTS):
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


def fetch_yahoo(ticker, start, end):
    """Yahoo Finance 日線（給指數／ETF 現貨：^HSTECH、3033.HK、7200.HK …），存 data/hkex_options/yahoo/<代號>.csv。
    雲端工作階段連不到 Yahoo，所以也放在這個 workflow 跑。期貨對現貨的基差研究（research/index_arbitrage）用。"""
    import json, calendar
    from datetime import datetime, timezone
    t0 = calendar.timegm(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timetuple())
    t1 = calendar.timegm(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timetuple()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
           f"?period1={t0}&period2={t1}&interval=1d&events=div,splits")
    st, raw = get(url)
    if st != 200:
        print(f"yahoo {ticker}: HTTP {st} {raw[:200]!r}"); return
    res = json.loads(raw)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]; adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    divs = {int(k): v.get("amount") for k, v in (res.get("events", {}).get("dividends") or {}).items()}
    (OUT / "yahoo").mkdir(parents=True, exist_ok=True)
    path = OUT / "yahoo" / f"{ticker.replace('^', '_')}.csv"
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("date,open,high,low,close,adjclose,volume,dividend\n")
        for i, ts in enumerate(res["timestamp"]):
            if q["close"][i] is None:
                continue
            day = datetime.fromtimestamp(ts + 8 * 3600, tz=timezone.utc).strftime("%Y-%m-%d")   # 時間戳是 HKT 開市，+8h 取日期
            div = next((v for k, v in divs.items() if abs(k - ts) < 86400), "")
            fh.write(f"{day},{q['open'][i]},{q['high'][i]},{q['low'][i]},{q['close'][i]},{adj[i] if i < len(adj) else ''},{q['volume'][i]},{div}\n")
            n += 1
    print(f"yahoo {ticker}: {n} 列 → {path}")
    time.sleep(1.0)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("probe"); s.add_argument("day"); s.add_argument("--products", default="")
    f = sub.add_parser("fetch"); f.add_argument("start"); f.add_argument("end")
    f.add_argument("--products", default="hsio", help="港交所報告代號，逗號分隔；yahoo:<代號> 代表改抓 Yahoo 日線（例 yahoo:^HSTECH,yahoo:3033.HK）")
    a = ap.parse_args()
    if a.cmd == "probe":
        # workflow 的 probe 步驟只傳日期，但把 inputs.products 放在環境變數 PRODUCTS；兩個來源都接受
        plist = [p for p in (a.products or os.environ.get("PRODUCTS", "")).split(",") if p]
        probe(a.day, plist or None)
    else:
        items = [p for p in a.products.split(",") if p]
        for t in [p[6:] for p in items if p.startswith("yahoo:")]:
            fetch_yahoo(t, a.start, a.end)
        for u in [p[4:] for p in items if p.startswith("url:")]:        # 任意網址：原文存 sample/，用來找報告索引與產品代號
            st_, raw = get(u if u.startswith("http") else "https://" + u)
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", u.split("://")[-1])[:80]
            (OUT / "sample").mkdir(parents=True, exist_ok=True)
            (OUT / "sample" / f"{name}.txt").write_text(to_text(raw) if st_ == 200 else f"HTTP {st_}", encoding="utf-8")
            print(f"url {u}: HTTP {st_} {len(raw)} bytes")
        hkex = [p for p in items if not p.startswith(("yahoo:", "url:"))]
        if hkex:
            import hkex_option_parse as hp                              # 解析器在看過樣本後才寫（第二階段）
            hp.fetch(a.start, a.end, hkex, OUT, get, to_text)


if __name__ == "__main__":
    main()
