#!/usr/bin/env python3
# =============================================================================
# 內部人買入（Form 4）跟單回測
# -----------------------------------------------------------------------------
# 輸入：data/insider/purchases/*.csv.gz（scripts/insider_fetch.py 產生）
# 價格/成分股：gifted-carson 分支（workflow sparse checkout 到 _equities/）
#   _equities/data/equities/us/            美股日線（用 pelosi_backtest 的含息還原讀法）
#   _equities/universes/sp500/membership.csv  S&P 500 point-in-time 成分股區間（ticker,start,end）
#   _equities/universes/us/renames.csv       改代碼對照
#
# 為了不重蹈佩洛西回測的倖存者偏差：
#   * 只用「申報當時是 S&P 500 成分股」的公司（point-in-time），不是用現在的名單回頭挑。
#   * 價格歷史必須在入選日前就存在（防代碼被別家公司重用，同 universe.py 的 GRACE_DAYS 規則），
#     且申報後 7 天內要有成交價。
#   * 主要比較基準是「同一份資料算出的等權 S&P 500（point-in-time）」：大型股等權本身就常贏 SPY，
#     跟它比才看得出內部人訊號有沒有額外價值；缺價格的下市股兩邊一起缺，偏差大致抵銷。
#   * 報告列出涵蓋率：多少訊號因為沒有價格被丟掉。
#
# 訊號（都只算董事/高管，排除只有 10% 大股東身分的基金；單筆 < $10,000 不算）：
#   all       任一董事/高管公開市場買入（同一檔 30 天內只算第一次）
#   cluster   30 天內 ≥3 位不同董事/高管買入同一檔（第 3 位申報時觸發；之後 90 天冷卻）
#   ceo_cfo   CEO / CFO 本人買入（同一檔 30 天內只算第一次）
#   large     單人單次申報買入 ≥ $500,000（同一檔 30 天內只算第一次）
# 進場：申報日「之後」第一個交易日開盤；出場：持有 1/3/6/12 個月後第一個交易日開盤。
#
# 用法：
#   python3 scripts/insider_backtest.py
#   python3 scripts/insider_backtest.py --start 2010-01-01 --equities-root path/to/gifted-carson
# 輸出：data/insider/backtest/README.md、summary.json、trades_<訊號>.csv、equity.svg
# =============================================================================
import argparse
import csv
import glob
import gzip
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pelosi_backtest as bt  # noqa: E402  共用：價格讀取、部位、組合淨值、績效、圖

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PURCHASE_DIR = os.path.join(ROOT, "data", "insider", "purchases")
OUT_DIR = os.path.join(ROOT, "data", "insider", "backtest")
DEFAULT_EQ_ROOT = os.path.join(ROOT, "_equities")
GRACE_DAYS = 7
MIN_VALUE = 10_000
LARGE_VALUE = 500_000
CLUSTER_N, CLUSTER_WINDOW, CLUSTER_COOLDOWN = 3, 30, 90
DEDUPE_DAYS = 30
HOLDS = ["h1m", "h3m", "h6m", "h12m"]
STRATEGIES = ["all", "cluster", "ceo_cfo", "large"]
STRAT_NAMES = {"all": "任一董事/高管買入", "cluster": f"群聚買入（30 天內 ≥{CLUSTER_N} 人）",
               "ceo_cfo": "CEO/CFO 買入", "large": "單次 ≥ $50 萬"}
HOLD_NAMES = {"h1m": "1 個月", "h3m": "3 個月", "h6m": "6 個月", "h12m": "12 個月"}
CEO_CFO_RE = re.compile(r"\b(CEO|CFO|chief\s+executive|chief\s+financial|principal\s+executive)\b", re.I)


# -----------------------------------------------------------------------------
# 成分股與代號
# -----------------------------------------------------------------------------
def norm_ticker(t):
    t = (t or "").strip().upper()
    t = re.split(r"[,;\s]+", t)[0] if t else ""
    if t in ("", "NONE", "N/A", "NA"):
        return ""
    return t.replace(".", "-").replace("/", "-")


def load_renames(eq_root):
    path = os.path.join(eq_root, "universes", "us", "renames.csv")
    out = {}
    if os.path.exists(path):
        for r in bt._read_csv_rows(path):
            if r.get("old") and not r["old"].startswith("#"):
                out[norm_ticker(r["old"])] = norm_ticker(r["new"])
    return out


def canonical(t, renames):
    for _ in range(4):  # 連續改名（A→B→C）
        if t not in renames:
            break
        t = renames[t]
    return t


def load_membership(eq_root, renames):
    path = os.path.join(eq_root, "universes", "sp500", "membership.csv")
    mem = {}
    for r in bt._read_csv_rows(path):
        t = canonical(norm_ticker(r["ticker"]), renames)
        start = date.fromisoformat(r["start"])
        end = date.fromisoformat(r["end"]) if r.get("end") else None
        mem.setdefault(t, []).append((start, end))
    return mem


def first_local_date(eq_dir, t):
    """本地日線真正的第一天（防代碼重用要用完整歷史，不是從回測起點截斷後的第一天）。"""
    folder = os.path.join(eq_dir, t)
    years = sorted(n for n in os.listdir(folder) if n.startswith("prices_") and n.endswith(".csv")) \
        if os.path.isdir(folder) else []
    for name in years:
        for r in bt._read_csv_rows(os.path.join(folder, name)):
            try:
                return date.fromisoformat(r["Date"])
            except (KeyError, ValueError):
                continue
    return None


def member_since(mem, t, d):
    """d 當天 t 在 S&P 500 的話，回傳這段區間的起始日；否則 None。"""
    for start, end in mem.get(t, []):
        if start <= d and (end is None or d < end):
            return start
    return None


# -----------------------------------------------------------------------------
# 訊號
# -----------------------------------------------------------------------------
def load_purchases(start=None):
    rows = []
    for path in sorted(glob.glob(os.path.join(PURCHASE_DIR, "*.csv.gz"))):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            rows.extend(csv.DictReader(fh))
    if start:
        rows = [r for r in rows if r["filing_date"] >= start.isoformat()]
    return rows


def insider_events(rows, renames):
    """明細 → 事件（同一人同一檔同一天申報合併）。只留董事/高管、≥ $10,000、Form 4。
    修正申報（4/A）重報的同一筆交易只算最早那份。"""
    seen, ev = set(), {}
    for r in sorted(rows, key=lambda x: x["filing_date"]):
        rel = r.get("relationship", "").lower()
        if "director" not in rel and "officer" not in rel:
            continue  # 只有 10% 大股東（基金）或 Other
        if not r.get("doc_type", "").startswith("4"):
            continue
        t = canonical(norm_ticker(r["ticker"]), renames)
        try:
            price, shares = float(r["price"] or 0), float(r["shares"] or 0)
            fd, td = date.fromisoformat(r["filing_date"]), date.fromisoformat(r["trans_date"])
        except ValueError:
            continue
        if not t or price <= 0 or shares <= 0:
            continue
        key = (r["owner_cik"], t, r["trans_date"], r["shares"], r["price"])
        if key in seen:
            continue
        seen.add(key)
        k = (t, r["owner_cik"], fd)
        e = ev.setdefault(k, {"ticker": t, "owner": r["owner_cik"], "owner_name": r["owner_name"],
                              "title": r.get("title", ""), "filing_date": fd, "trade_date": td,
                              "value": 0.0, "issuer": r["issuer_name"], "accession": r["accession"]})
        e["value"] += shares * price
        e["trade_date"] = min(e["trade_date"], td)
    return [e for e in ev.values() if e["value"] >= MIN_VALUE]


def _dedupe(events, days):
    """同一檔 days 天內只留第一個事件。"""
    out, last = [], {}
    for e in sorted(events, key=lambda x: (x["filing_date"], x["ticker"])):
        prev = last.get(e["ticker"])
        if prev and (e["filing_date"] - prev).days < days:
            continue
        last[e["ticker"]] = e["filing_date"]
        out.append(e)
    return out


def cluster_signals(events):
    by_t = {}
    for e in events:
        by_t.setdefault(e["ticker"], []).append(e)
    out = []
    for t, es in by_t.items():
        es.sort(key=lambda x: x["filing_date"])
        cooldown_until = None
        for i, e in enumerate(es):
            if cooldown_until and e["filing_date"] <= cooldown_until:
                continue
            window = [x for x in es[: i + 1] if (e["filing_date"] - x["filing_date"]).days < CLUSTER_WINDOW]
            owners = {x["owner"] for x in window}
            if len(owners) >= CLUSTER_N:
                out.append({**e, "value": sum(x["value"] for x in window), "n_insiders": len(owners),
                            "trade_date": min(x["trade_date"] for x in window)})
                cooldown_until = e["filing_date"] + timedelta(days=CLUSTER_COOLDOWN)
    return out


def build_strategies(events):
    return {
        "all": _dedupe(events, DEDUPE_DAYS),
        "cluster": cluster_signals(events),
        "ceo_cfo": _dedupe([e for e in events if CEO_CFO_RE.search(e.get("title") or "")], DEDUPE_DAYS),
        "large": _dedupe([e for e in events if e["value"] >= LARGE_VALUE], DEDUPE_DAYS),
    }


def to_bt_signal(e):
    return {"ticker": e["ticker"], "side": "buy", "trade_date": e["trade_date"],
            "filing_date": e["filing_date"], "lag_days": (e["filing_date"] - e["trade_date"]).days,
            "weight_amount": e["value"], "asset": e["issuer"], "doc_id": e["accession"],
            "n_insiders": e.get("n_insiders", 1)}


# -----------------------------------------------------------------------------
# 等權 S&P 500（point-in-time）基準
# -----------------------------------------------------------------------------
def ew_index(mem, prices, calendar, first_price):
    """每天：當天是成分股、且前一日與當天都有價格的股票，收盤對收盤報酬取平均。
    回傳 Prices（open = 前一日指數水位，模擬開盤進場；close = 當日水位）。"""
    level, opens, closes, prev_day = 1.0, [], [], None
    members = [(t, s, e) for t, iv in mem.items() for s, e in iv if t in prices]
    for d in calendar:
        rets = []
        if prev_day is not None:
            for t, s, e in members:
                if not (s <= d and (e is None or d < e)):
                    continue
                if first_price[t] > s + timedelta(days=GRACE_DAYS):
                    continue  # 價格屬於後來拿到代碼的公司
                p = prices[t]
                i, j = p.idx.get(d), p.idx.get(prev_day)
                if i is not None and j is not None and p.close[j] > 0:
                    rets.append(p.close[i] / p.close[j] - 1)
        opens.append(level)
        if rets:
            level *= 1 + sum(rets) / len(rets)
        closes.append(level)
        prev_day = d
    return bt.Prices(list(calendar), opens, closes)


# -----------------------------------------------------------------------------
# 統計
# -----------------------------------------------------------------------------
def tstat(xs):
    n = len(xs)
    if n < 3:
        return None
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))
    return mu / (sd / math.sqrt(n)) if sd > 0 else None


def excess_stats(lots):
    """逐筆超額報酬（相對等權 S&P 500 同期）。t 值另算「按進場月份分組」版本：
    同月份的部位高度相關，逐筆 t 值會高估顯著性，月份平均再算 t 比較保守。"""
    ex = [x["ret"] - x["ew"] for x in lots if x.get("ew") is not None]
    if not ex:
        return {}
    by_month = {}
    for x in lots:
        if x.get("ew") is not None:
            by_month.setdefault(x["entry_day"].strftime("%Y-%m"), []).append(x["ret"] - x["ew"])
    monthly = [sum(v) / len(v) for v in by_month.values()]
    s = sorted(ex)
    return {"n": len(ex), "mean_ret": sum(x["ret"] for x in lots) / len(lots),
            "mean_excess": sum(ex) / len(ex), "median_excess": s[len(s) // 2],
            "hit": sum(1 for v in ex if v > 1e-9) / len(ex), "t": tstat(ex),
            "t_month": tstat(monthly), "months": len(monthly)}


# -----------------------------------------------------------------------------
# 報告
# -----------------------------------------------------------------------------
def fmt_t(v):
    return "—" if v is None else f"{v:.2f}"


def render(res, cov, bench, cal, by_year, args):
    pct = bt.pct
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    o = [
        "# 內部人買入（Form 4）跟單回測", "",
        f"更新：{now}　｜　期間 {cal[0]} ～ {cal[-1]}　｜　範圍：申報當時的 S&P 500 成分股（point-in-time）", "",
        "規則：申報日之後第一個交易日**開盤**進場，持有固定期間後開盤出場；等權、含息還原價，未計手續費與滑價。"
        "只算董事/高管的公開市場買入（交易代碼 P），排除只有 10% 大股東身分者、單筆 < $10,000。", "",
        "**超額報酬的比較對象是同期「等權 S&P 500」**（同一份價格資料算的 point-in-time 指數）："
        "大型股等權本身就常贏 SPY，要贏它才代表內部人訊號有額外價值。", "",
        "![淨值](equity.svg)", "",
        "## 逐筆超額報酬（相對等權 S&P 500 同期）", "",
        "| 訊號 | 持有 | 筆數 | 平均報酬 | 平均超額 | 中位數超額 | 贏基準比例 | t 值 | t 值（按月分組） |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in STRATEGIES:
        for h in HOLDS:
            e = res[s][h]["excess"]
            if not e:
                continue
            o.append(f"| {STRAT_NAMES[s]} | {HOLD_NAMES[h]} | {e['n']} | {pct(e['mean_ret'])} "
                     f"| {pct(e['mean_excess'])} | {pct(e['median_excess'])} | {e['hit'] * 100:.0f}% "
                     f"| {fmt_t(e['t'])} | {fmt_t(e['t_month'])}（{e['months']} 個月） |")
    o += ["", "t 值（按月分組）> 2 才算大致顯著；逐筆 t 值因同期部位高度相關，會高估。", "",
          "## 組合績效（持有期間內等權持有所有未平倉部位，空倉為現金）", "",
          "| 訊號 | 持有 | 年化 | 最大回撤 | 波動 | Sharpe | 持倉時間 |", "|---|---|---:|---:|---:|---:|---:|"]
    for s in STRATEGIES:
        for h in HOLDS:
            p = res[s][h]["port"]
            if not p:
                continue
            sh = "—" if p.get("sharpe") is None else f"{p['sharpe']:.2f}"
            o.append(f"| {STRAT_NAMES[s]} | {HOLD_NAMES[h]} | {pct(p.get('cagr'))} | {pct(p.get('mdd'))} "
                     f"| {p.get('vol', 0) * 100:.1f}% | {sh} | {p.get('invested', 0) * 100:.0f}% |")
    for name, st in bench.items():
        if st:
            sh = "—" if st.get("sharpe") is None else f"{st['sharpe']:.2f}"
            o.append(f"| **{name}** | — | {pct(st['cagr'])} | {pct(st['mdd'])} | {st['vol'] * 100:.1f}% | {sh} | 100% |")
    o += ["", "## 逐年穩定性（群聚買入、持有 3 個月）", "",
          "| 年份 | 筆數 | 平均超額 | 贏基準比例 |", "|---|---:|---:|---:|"]
    for y, v in sorted(by_year.items()):
        o.append(f"| {y} | {v['n']} | {pct(v['mean'])} | {v['hit'] * 100:.0f}% |")
    o += ["", "## 資料涵蓋率", "",
          f"- SEC 買入明細：{cov['rows']:,} 筆 → 董事/高管、≥ $10,000 的申報事件：{cov['events']:,} 個",
          f"- 申報當時是 S&P 500 成分股：{cov['in_sp500']:,} 個（{cov['in_sp500'] / max(cov['events'], 1) * 100:.1f}%）",
          f"- 其中有可用價格：{cov['priced']:,} 個（{cov['priced'] / max(cov['in_sp500'], 1) * 100:.1f}%）"
          "——沒有價格的多半是已下市/被併購的公司，這部分仍有倖存者偏差，但基準也缺同一批股票。",
          f"- 價格資料缺漏的代號（前 30 個）：{', '.join(cov['missing'][:30]) or '無'}", "",
          "## 限制", "",
          "- 只看 S&P 500：學術研究多發現內部人買入訊號在小型股較強，大型股的效果可能偏小。",
          "- 申報日只到「日」：盤後申報的訊號，這裡用隔天開盤進場（保守）。",
          "- 未計交易成本；持有 1 個月的策略換手高，成本影響較大。",
          f"- 參數（群聚 {CLUSTER_N} 人/{CLUSTER_WINDOW} 天、大額 ${LARGE_VALUE:,}）是事先選定的常見設定，沒有最佳化；"
          "不要拿這份報告反覆調參數再挑最好的，會過度擬合。", ""]
    return "\n".join(o)


# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="內部人買入（Form 4）跟單回測")
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--equities-root", default=os.environ.get("EQUITIES_ROOT", DEFAULT_EQ_ROOT),
                    help="gifted-carson 分支的根目錄（含 data/equities/us 與 universes/）")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    start = date.fromisoformat(args.start)
    eq_dir = os.path.join(args.equities_root, "data", "equities", "us")
    if not os.path.isdir(eq_dir):
        print(f"找不到本地美股資料：{eq_dir}")
        return 1

    renames = load_renames(args.equities_root)
    mem = load_membership(args.equities_root, renames)
    rows = load_purchases(start)
    events = insider_events(rows, renames)
    print(f"買入明細 {len(rows):,} 筆 → 事件 {len(events):,} 個")

    in_sp = [e for e in events if member_since(mem, e["ticker"], e["filing_date"])]
    print(f"S&P 500 成分股事件 {len(in_sp):,} 個；載入價格 {len(mem)} 檔…")
    sources = {}
    # 研究只用本地資料（不混 Yahoo），缺的代號就是缺，記在涵蓋率裡
    prices = bt.load_all_prices(set(mem) | {"SPY"}, start - timedelta(days=10), None, eq_dir, sources, yahoo=False)
    first_price = {t: first_local_date(eq_dir, t) or p.days[0] for t, p in prices.items()}
    spy = prices.get("SPY")
    if not spy:
        print("缺 SPY，無法建立交易日曆")
        return 1

    def priced(e):
        t = e["ticker"]
        s = member_since(mem, t, e["filing_date"])
        return t in prices and first_price[t] <= s + timedelta(days=GRACE_DAYS)

    usable = [e for e in in_sp if priced(e)]
    missing = sorted({e["ticker"] for e in in_sp if e["ticker"] not in prices})
    cov = {"rows": len(rows), "events": len(events), "in_sp500": len(in_sp), "priced": len(usable),
           "missing": missing}
    print(f"有價格 {len(usable):,} 個；缺價格代號 {len(missing)} 個")

    cal = [d for d in spy.days if d >= start]
    ew = ew_index(mem, prices, cal, first_price)
    bench = {"SPY 買入持有": bt.stats(bt.bench_curve(spy, cal)),
             "等權 S&P 500（point-in-time）": bt.stats([(d, v, True) for d, v in zip(ew.days, ew.close)])}

    strat = build_strategies(usable)
    res = {}
    os.makedirs(args.out, exist_ok=True)
    for s in STRATEGIES:
        sigs = [to_bt_signal(e) for e in strat[s]]
        res[s] = {}
        for h in HOLDS:
            lots, _ = bt.make_lots(sigs, prices, h, "equal")
            for x in lots:
                exit_open = not x["open"]
                x["ew"] = bt.bench_return(ew, x["entry_day"], x["exit_day"], exit_open)
                x["spy"] = bt.bench_return(spy, x["entry_day"], x["exit_day"], exit_open)
            curve = bt.portfolio_curve(lots, prices, [d for d in cal if lots and d >= min(x["entry_day"] for x in lots)]) if lots else []
            res[s][h] = {"lots": lots, "curve": curve, "port": bt.stats(curve), "excess": excess_stats(lots)}
            e = res[s][h]["excess"]
            if e:
                print(f"  {s:>8} {h:>4}：{e['n']:>5} 筆  平均超額 {bt.pct(e['mean_excess'])}  "
                      f"t(月)={fmt_t(e['t_month'])}")
        with open(os.path.join(args.out, f"trades_{s}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ticker", "issuer", "trade_date", "filing_date", "entry_day", "exit_day", "ret_3m",
                        "ew_3m", "excess_3m", "value", "n_insiders", "accession"])
            for x in sorted(res[s]["h3m"]["lots"], key=lambda x: x["entry_day"]):
                w.writerow([x["ticker"], x["asset"], x["trade_date"], x["filing_date"], x["entry_day"],
                            x["exit_day"], f"{x['ret']:.4f}", "" if x["ew"] is None else f"{x['ew']:.4f}",
                            "" if x["ew"] is None else f"{x['ret'] - x['ew']:.4f}", f"{x['weight_amount']:.0f}",
                            x.get("n_insiders", 1), x["doc_id"]])

    by_year = {}
    for x in res["cluster"]["h3m"]["lots"]:
        if x["ew"] is None:
            continue
        v = by_year.setdefault(x["entry_day"].year, {"n": 0, "sum": 0.0, "win": 0})
        v["n"] += 1
        v["sum"] += x["ret"] - x["ew"]
        v["win"] += (x["ret"] - x["ew"]) > 1e-9
    by_year = {y: {"n": v["n"], "mean": v["sum"] / v["n"], "hit": v["win"] / v["n"]} for y, v in by_year.items()}

    best = res["cluster"]["h3m"]["curve"]
    c0 = best[0][0] if best else cal[0]
    ew_sub = [(d, v) for d, v in zip(ew.days, ew.close) if d >= c0]
    bt.svg_chart([("群聚買入 3M", "--s1", [(d, v) for d, v, _ in best]),
                  ("SPY", "--s2", [(d, v) for d, v, _ in bt.bench_curve(spy, [d for d in cal if d >= c0])]),
                  ("等權S&P500", "--s3", [(d, v / ew_sub[0][1]) for d, v in ew_sub])],
                 os.path.join(args.out, "equity.svg"),
                 "淨值（對數軸）：內部人群聚買入・持有 3 個月 vs SPY／等權 S&P 500")

    summary = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "coverage": cov,
               "benchmarks": bench, "by_year_cluster_3m": by_year,
               "results": {s: {h: {"port": res[s][h]["port"], "excess": res[s][h]["excess"]} for h in HOLDS}
                           for s in STRATEGIES}}
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, default=str)
    with open(os.path.join(args.out, "README.md"), "w", encoding="utf-8") as f:
        f.write(render(res, cov, bench, cal, by_year, args))
    print(f"報告：{os.path.join(args.out, 'README.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
