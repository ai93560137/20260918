#!/usr/bin/env python3
"""全市場日線品質檢查（VCP_FULLMARKET_BACKTEST.md 第一部分之二，規則寫死）。

    python3 scripts/qc_full_market.py --market hk      # 在 GitHub Actions 上跑（第二來源要連外網）

產出：
- data_full/<m>/_qc_exclude.txt   整檔排除的股票（結構檢查不過）
- data_full/<m>/_qc_zombie.json   殭屍段（連續 20 日收市不變且量 0，之後恢復交易）→ 載入時丟掉
- research/vcp_full/<m>_qc.md      報告（結構、跟指數版對照、最新一日第二來源）
回傳碼：跟指數版對照或最新一日第二來源超出門檻 → 2（流程要先查清楚，不要判決）
"""
import argparse
import json
import random
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import marketdata as md  # noqa: E402

SPIKE_UP, SPIKE_DN = 1.6, 0.625      # 單日 >60% 且隔日反向 >37.5%（一來一回）
ZOMBIE_DAYS = 20


def structural(df: pd.DataFrame) -> tuple[list[str], list[tuple[str, str]]]:
    """回傳 (嚴重問題列表, 殭屍段 [(起, 迄)])。"""
    bad = []
    if df["Date"].duplicated().any():
        bad.append("重複日期")
    if (df["Close"] <= 0).any():
        bad.append("收市≤0")
    ratio = df["AdjClose"] / df["Close"]
    if ((ratio > 1.05) | (ratio <= 0)).any():
        bad.append("還原比例異常")
    hl = (df["High"] < df["Low"]) | (df["Close"] > df["High"] * 1.01) | (df["Close"] < df["Low"] * 0.99)
    if hl.mean() > 0.01:
        bad.append(f"高低價矛盾 {hl.mean():.1%}")
    c = df["Close"].to_numpy()
    r1 = c[1:-1] / c[:-2]
    r2 = c[2:] / c[1:-1]
    spikes = int(((r1 > SPIKE_UP) & (r2 < SPIKE_DN)).sum() + ((r1 < SPIKE_DN) & (r2 > SPIKE_UP)).sum())
    if spikes >= 3:
        bad.append(f"尖刺 {spikes} 次")
    zombies = []
    same = np.r_[False, c[1:] == c[:-1]] & (df["Volume"].fillna(0).to_numpy() == 0)
    i, n = 0, len(c)
    while i < n:
        if same[i]:
            j = i
            while j < n and same[j]:
                j += 1
            if j - i >= ZOMBIE_DAYS and j < n:          # 之後有恢復交易
                zombies.append((str(df["Date"].iloc[i]), str(df["Date"].iloc[j - 1])))
            i = j
        else:
            i += 1
    return bad, zombies


def latest_second_source(market: str, last: dict[str, tuple[str, float]]) -> tuple[str, int, int]:
    """最新一日第二來源：回傳 (說明, 比對檔數, 差 >1% 檔數)。"""
    import requests
    if market == "us":
        import fetch_second_source as fs
        r = requests.get("https://api.nasdaq.com/api/screener/stocks", headers=fs.UA,
                         params={"tableonly": "true", "download": "true"}, timeout=60)
        r.raise_for_status()
        theirs = {x["symbol"].strip().replace("/", "-"): fs.money(x.get("lastsale", ""))
                  for x in r.json()["data"]["rows"]}
        d_max = max(d for d, _ in last.values())
        pairs = [(v[1], theirs.get(t)) for t, v in last.items() if v[0] == d_max and theirs.get(t)]
        src = f"Nasdaq screener 最後成交價 vs 我們 {d_max} 收市"
    elif market == "hk":
        import fetch_hkex_equity as fh
        d_max = max(d for d, _ in last.values())
        r = requests.get(fh.URL.format(d=date.fromisoformat(d_max)), headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        r.raise_for_status()
        q = fh.parse_quotations(r.content.decode("utf-8", errors="replace"))
        pairs = [(v[1], q[t]["close"]) for t, v in last.items() if v[0] == d_max and t in q and q[t].get("close")]
        src = f"港交所日報表 {d_max}"
    else:
        import fetch_second_source as fs
        d_max = max(d for d, _ in last.values())
        sample = sorted(t for t, v in last.items() if v[0] == d_max)
        random.Random(0).shuffle(sample)
        got = fs.fetch_jp(sample[:200])
        pairs = [(last[t][1], v["close"]) for t, v in got.items() if v.get("date") == d_max and v.get("close")]
        src = f"Yahoo!ファイナンス 前日終値（抽 200 檔）{d_max}"
    n_bad = sum(1 for a, b in pairs if abs(a / b - 1) > 0.01)
    return src, len(pairs), n_bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=["hk", "jp", "us"])
    ap.add_argument("--no-network", action="store_true", help="不做最新一日第二來源（本機測試用）")
    args = ap.parse_args()
    m = args.market
    base = ROOT / "data_full" / m
    files = sorted(base.glob("*.csv.gz"))
    exclude, zombies, reasons = [], {}, {}
    overlap_n = overlap_bad = 0
    overlap_examples = []
    last = {}
    for p in files:
        t = p.name[:-7]
        df = pd.read_csv(p, compression="gzip")
        if df.empty:
            continue
        bad, zb = structural(df)
        if bad:
            exclude.append(t)
            reasons[t] = bad
        if zb:
            zombies[t] = zb
        last[t] = (str(df["Date"].iloc[-1]), float(df["Close"].iloc[-1]))
        # 跟指數版（data/equities，已第二來源檢查）對照
        if md.has_v2(t):
            ours = {r["Date"].isoformat(): (r["Close"], r["AdjClose"]) for r in md.load_ohlcv(t, apply_adjustments=False)}
            j = df[df["Date"].isin(ours)]
            if len(j) > 50:
                oc = np.array([ours[d][0] for d in j["Date"]])
                oa = np.array([ours[d][1] for d in j["Date"]])
                diff = (np.abs(j["Close"].to_numpy() / oc - 1) > 0.005) | (np.abs(j["AdjClose"].to_numpy() / oa - 1) > 0.005)
                overlap_n += 1
                if diff.mean() > 0.01:
                    overlap_bad += 1
                    if len(overlap_examples) < 10:
                        overlap_examples.append(f"{t}（{diff.mean():.1%} 的日子差 >0.5%）")
    (base / "_qc_exclude.txt").write_text("\n".join(sorted(exclude)) + "\n", encoding="utf-8")
    (base / "_qc_zombie.json").write_text(json.dumps(zombies, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")

    L = [f"# 全市場數據品質檢查：{m}（{date.today()}）\n",
         "規則見 VCP_FULLMARKET_BACKTEST.md 第一部分之二。\n",
         f"## 1. 結構檢查\n\n{len(files)} 檔 → 整檔排除 **{len(exclude)}** 檔、有殭屍段 {len(zombies)} 檔"
         f"（共 {sum(len(v) for v in zombies.values())} 段，載入時丟掉）。\n"]
    kinds = {}
    for v in reasons.values():
        for x in v:
            k = re.sub(r"[\d.%]+.*", "", x).strip()
            kinds[k] = kinds.get(k, 0) + 1
    L.append("排除原因：" + ("、".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])) or "無") + "\n")
    L.append("例：" + ("；".join(f"{t}：{'、'.join(v)}" for t, v in list(reasons.items())[:10]) or "無") + "\n")
    rate = overlap_bad / overlap_n if overlap_n else 0
    ok2 = rate <= 0.02
    L.append(f"## 2. 跟指數版數據對照\n\n{overlap_n} 檔同時在兩邊；差異 >0.5% 的日子佔比 >1% 的有 **{overlap_bad}** 檔"
             f"（{rate:.1%}；門檻 2%）→ {'✅ 通過' if ok2 else '❌ 超出門檻，先查抓取流程'}\n")
    if overlap_examples:
        L.append("例：" + "、".join(overlap_examples) + "\n")
    ok3 = True
    if not args.no_network:
        try:
            src, n_cmp, n_bad = latest_second_source(m, last)
            r3 = n_bad / n_cmp if n_cmp else 0
            ok3 = r3 <= 0.05
            L.append(f"## 3. 最新一日第二來源\n\n{src}：比對 {n_cmp} 檔、差 >1% 的 **{n_bad}** 檔（{r3:.1%}；門檻 5%）→ "
                     f"{'✅ 通過' if ok3 else '❌ 超出門檻，先查清楚'}\n")
        except Exception as exc:
            L.append(f"## 3. 最新一日第二來源\n\n⚠ 抓取失敗：{str(exc)[:200]}（不擋判決，但要在結果裡註明）\n")
    out = ROOT / "research" / "vcp_full"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{m}_qc.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    sys.exit(0 if ok2 and ok3 else 2)


if __name__ == "__main__":
    main()
