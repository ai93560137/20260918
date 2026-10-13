#!/usr/bin/env python3
"""HTF／ORB 5 分 K 批次覆蓋率：讀請求清單 CSV + data_stock_ibkr/htf_5m/ 輸出 + _status.txt，印出 Markdown 一節
（各清單：請求列、取得、成功率、最舊成功日、缺失原因、美股按年覆蓋），可貼入 HTF_DATA_SCOPE.md。純本機讀檔，不連 IB。

用法（repo 根目錄）：
  python3 gcp_ib/htf_scope_batch.py --label "第 3 批" \
      --req hk=~/orb_req/ibkr_request_hk.csv hk_nonmom=~/orb_req/ibkr_request_hk_nonmom.csv \
            us=~/orb_req/ibkr_request_us.csv us_nonmom=~/orb_req/ibkr_request_us_nonmom.csv
  （--req 後每個 名稱=路徑；名稱隨意，只用作表格列名；市場由 CSV 內 market 欄決定）
"""
import argparse
import csv
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_stock_ibkr" / "htf_5m"
LINE = re.compile(r"^\S+ \S+ (hk|us|tw) (\S+) (\d{4}-\d{2}-\d{2}): (\S+)(.*)$")


def last_status():
    """(market,ticker,entry_date) -> (status, detail)；同一列多次記錄取最後一次。"""
    st = {}
    p = OUT / "_status.txt"
    if not p.exists():
        return st
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if " PROBE " in ln:
            continue
        m = LINE.match(ln.strip())
        if m:
            st[(m.group(1), m.group(2), m.group(3))] = (m.group(4), m.group(5).strip())
    return st


def read_req(path):
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)]


def section(label, reqs):
    st = last_status()
    out = [f"## {label}（動能股 ORB 研究；IB Gateway paper 只讀，entry_date 當天 5 mins／TRADES／RTH）", "",
           "| 清單 | 市場 | 請求列 | 取得 | 成功率 | 最舊成功日 | 缺失原因 |", "|---|---|---:|---:|---:|---|---|"]
    year_cov = defaultdict(lambda: [0, 0])
    for name, path in reqs:
        rows = read_req(path)
        if not rows:
            continue
        mk = rows[0]["market"]
        got, oldest, miss = 0, None, Counter()
        for r in rows:
            t, d = r["ticker"], r["entry_date"]
            ok = (OUT / f"{mk}_{t}_{d}.csv").exists()
            if mk == "us":
                year_cov[(name, d[:4])][1] += 1
            if ok:
                got += 1
                oldest = d if oldest is None or d < oldest else oldest
                if mk == "us":
                    year_cov[(name, d[:4])][0] += 1
            else:
                s = st.get((mk, t, d))
                miss[s[0] if s else "未處理"] += 1
        pct = got / len(rows) * 100
        why = "、".join(f"{k} {v}" for k, v in miss.most_common()) or "—"
        out.append(f"| {name} | {mk} | {len(rows):,} | {got:,} | {pct:.1f}% | {oldest or '—'} | {why} |")
    for name in sorted({n for n, _ in year_cov}):
        ys = sorted(y for n, y in year_cov if n == name)
        out += ["", f"{name} 按年覆蓋（取得／請求）：" + "、".join(f"{y} {year_cov[(name, y)][0]}/{year_cov[(name, y)][1]}" for y in ys)]
    out += ["", "缺失原因說明：no_data＝IB 無該日 5 分 K（退市／改代號／年限以前）；no_contract＝找不到合約；"
            "beyond_horizon＝早於 IB 5 分 K 地平線（美股 2004-01-26），未請求；未處理＝尚未跑到。"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="第 3 批")
    ap.add_argument("--req", nargs="+", required=True, help="名稱=路徑 …")
    a = ap.parse_args()
    reqs = [tuple(x.split("=", 1)) for x in a.req]
    print(section(a.label, reqs))


if __name__ == "__main__":
    main()
