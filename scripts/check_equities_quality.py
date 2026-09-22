#!/usr/bin/env python3
"""美股/日股（v2 格式）每日數據品質檢查——港股版見 scripts/check_data_quality.py。

    python3 scripts/check_equities_quality.py --market us
    python3 scripts/check_equities_quality.py --market us --fetch-names   # Actions 上：抓 yfinance 公司名/行業

輸出 data/equities/<market>/QC_REPORT.md、qc_digest.txt（每次）、qc_alert.txt（有 🔴 才有）。

🔴 嚴重（會直接污染回測/模擬盤）：
- 現任成分股抓不到數據、或最後一根比市場最新交易日落後 > 5 天
- 近 30 天價格 <= 0、High < Low、單日漲跌 > 40%（當天沒拆股）
- 雙來源收市價不符：第二來源（美股 Nasdaq.com / 日股見 fetch_second_source.py）vs
  yfinance 同一交易日收市相差 > 1%
- 公司名變了（第二來源前後兩份快照、或 yfinance 前後兩次）——改名或代碼被重用
- 管線停擺：基準 ETF 超過 6 天沒新數據
🟡 注意：
- 第二來源名字 vs yfinance 名字差很多（可能是代碼對應錯）
- 重算 AdjClose 跟 yfinance 差 > 0.5%（股息數據怪，見 fetch_equities.py）
- 現任成分股沒有第二來源報價
📉 倖存者偏差洞（不是錯誤、是免費數據的極限）：歷史成分股抓不到價格的比例，按年列出——
   回測在那些年等於「只看活下來的公司」，報告必須寫明。

人工確認沒問題的項目寫進 universes/<market>/qc_acks.json（{"<TICKER>:<檢查>": "理由"}）。
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402
from universe import INDICES, Universe  # noqa: E402

RECENT_DAYS = 30
BIG_MOVE = 0.40
STALE_DAYS = 5
PIPELINE_STALE_DAYS = 6
XSRC_TOL = 0.01
XSRC_WINDOW = 20
ADJ_TOL = 0.005
NAME_SIM_MIN = 0.5
BENCH = {"us": "SPY", "jp": "1321.T"}
STOP = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "the",
        "holdings", "holding", "group", "common", "stock", "shares", "share", "class", "ordinary",
        "a", "b", "c", "de", "new", "sa", "nv", "ag", "se", "lp", "llc", "trust", "reit",
        "depositary", "american", "ads", "adr", "each", "representing", "one", "par", "value",
        "kabushiki", "kaisha", "kk"}


def norm_name(s: str) -> str:
    """英文去公司類字；日文（NFKC 全形轉半形後）去 (株)/株式会社 等。\w 含漢字/假名。"""
    s = unicodedata.normalize("NFKC", s).lower().replace("&", " and ")
    for x in ("(株)", "株式会社", "ホールディングス", "グループ"):
        s = s.replace(x, " ")
    return " ".join(t for t in re.findall(r"\w+", s) if t not in STOP)


def name_sim(a: str, b: str) -> float:
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    return max(len(ta & tb) / len(ta | tb), SequenceMatcher(None, na, nb).ratio())


def fetch_yf_info(tickers: list[str], budget_s: float) -> dict[str, dict]:
    import yfinance as yf
    out, started = {}, time.monotonic()
    for t in tickers:
        if time.monotonic() - started > budget_s:
            print(f"WARN 抓公司名超過 {budget_s:.0f}s，只抓了 {len(out)} 檔（下次續抓）", file=sys.stderr)
            break
        try:
            info = yf.Ticker(t).get_info()
        except Exception as exc:
            print(f"WARN {t}: get_info 失敗 {exc}", file=sys.stderr)
            continue
        name = info.get("longName") or info.get("shortName") or ""
        if name:
            out[t] = {"name": name, "sector": info.get("sector") or "", "industry": info.get("industry") or ""}
        time.sleep(0.3)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", choices=["us", "jp"], required=True)
    ap.add_argument("--fetch-names", action="store_true")
    ap.add_argument("--names-budget-min", type=float, default=20)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    m = args.market
    base = md.V2_DIR / m
    today = args.today or datetime.now(timezone.utc).date()
    acks = {}
    ack_path = ROOT / "universes" / m / "qc_acks.json"
    if ack_path.exists():
        acks = {k: v for k, v in json.loads(ack_path.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    status = json.loads((base / "_fetch_status.json").read_text(encoding="utf-8")) \
        if (base / "_fetch_status.json").exists() else {}

    # --- 宇宙：本市場各指數的現任與歷史成分股 ---
    unis = [Universe(k) for k, c in INDICES.items()
            if c["market"] == m and (ROOT / c.get("file", "")).is_file()]
    current: dict[str, list[str]] = {}
    for u in unis:
        for t in u.members_at(today):
            current.setdefault(t, []).append(u.key)

    flags: list[tuple[str, str, str, str]] = []

    def flag(level: str, t: str, check: str, msg: str) -> None:
        flags.append((level, t, check, msg))

    # --- 管線 ---
    bench = BENCH[m]
    try:
        bench_last = md.load_raw(bench)[-1][0]
    except (FileNotFoundError, IndexError):
        bench_last = None
    if bench_last is None or (today - bench_last).days > PIPELINE_STALE_DAYS:
        flag("🔴", bench, "pipeline_stale", f"基準最後數據 {bench_last}，抓取管線可能壞了")
    market_last = bench_last or today

    # --- 逐檔價格 ---
    loaded: dict[str, dict[date, dict]] = {}
    for t in sorted(set(current) | {x for x in status if status[x].get("rows")}):
        if not md.has_v2(t):
            if t in current:
                err = status.get(t, {}).get("error") or "從未抓到"
                flag("🔴", t, "fetch_failed", f"現任成分股（{'/'.join(current[t])}）沒有數據：{err}")
            continue
        rows = md.load_ohlcv(t)
        loaded[t] = {r["Date"]: r for r in rows}
        last = rows[-1]["Date"]
        if t in current and (market_last - last).days > STALE_DAYS:
            flag("🔴", t, "stale", f"現任成分股最後一根 {last}，市場最新 {market_last}")
        _, splits = md.load_actions(t)
        split_days = {d for d, _ in splits}
        cutoff = market_last - timedelta(days=RECENT_DAYS)
        prev = None
        for r in rows:
            # 近期髒值只檢查現任成分股：已出榜的代碼常被重新分配給別家公司（CPWR、SBNY），
            # 那段新價格本來就被防代碼重用檢查擋在回測外，不用每天警報
            if t in current and r["Date"] >= cutoff:
                if r["Close"] <= 0 or (r["Low"] is not None and r["Low"] <= 0):
                    flag("🔴", t, "nonpositive", f"{r['Date']} 價格 <= 0")
                if r["High"] is not None and r["Low"] is not None and r["High"] < r["Low"]:
                    flag("🔴", t, "high_lt_low", f"{r['Date']} High {r['High']} < Low {r['Low']}")
                if prev and prev["Close"] > 0 and r["Date"] not in split_days:
                    mv = r["Close"] / prev["Close"] - 1
                    if abs(mv) > BIG_MOVE:
                        flag("🔴", t, "bigmove", f"{r['Date']} 單日 {mv:+.0%}（當天無拆股紀錄）")
            prev = r
        err = status.get(t, {}).get("adj_err_max")
        if err is not None and err > ADJ_TOL:
            flag("🟡", t, "adj_mismatch", f"重算 AdjClose 與 yfinance 最大差 {err:.2%}")

    # --- 第二來源：收市價與名字 ---
    snaps = sorted((base / "_second").glob("quotes_*.json"))[-XSRC_WINDOW:]
    snap_data = [json.loads(p.read_text(encoding="utf-8")) for p in snaps]
    n_cmp = 0
    for s in snap_data:
        for t, q in s["quotes"].items():
            d = date.fromisoformat(q.get("date") or s["trade_date"])   # 日股每檔自帶前日終値日期
            r = loaded.get(t, {}).get(d)
            if r is None or not q.get("close"):
                continue
            n_cmp += 1
            diff = q["close"] / r["Close"] - 1
            if abs(diff) > XSRC_TOL:
                flag("🔴", t, "xsource", f"{d} 第二來源 {q['close']} vs yfinance {r['Close']}（{diff:+.2%}）")
    if len(snap_data) >= 2:
        a, b = snap_data[-2]["quotes"], snap_data[-1]["quotes"]
        for t in sorted(set(a) & set(b)):
            if a[t].get("name") and b[t].get("name") and norm_name(a[t]["name"]) != norm_name(b[t]["name"]):
                flag("🔴", t, "second_name_changed", f"第二來源名字「{a[t]['name']}」→「{b[t]['name']}」（改名或代碼重用）")
    latest_q = snap_data[-1]["quotes"] if snap_data else {}
    if snap_data:
        for t in sorted(current):
            if t not in latest_q and md.has_v2(t):
                flag("🟡", t, "no_second_source", "現任成分股沒有第二來源報價")

    # --- yfinance 公司名/行業 ---
    names_path = base / "_names.json"
    names = json.loads(names_path.read_text(encoding="utf-8")) if names_path.exists() else {}
    if args.fetch_names:
        # 優先抓從沒抓過的，其餘輪流（每次時間有限）
        todo = sorted((t for t in current if md.has_v2(t)),
                      key=lambda t: (t in names, names.get(t, {}).get("checked", "")))
        fetched = fetch_yf_info(todo, args.names_budget_min * 60)
        for t, info in fetched.items():
            rec = names.setdefault(t, {"name": info["name"], "history": [{"date": today.isoformat(), "name": info["name"]}]})
            if norm_name(rec["name"]) != norm_name(info["name"]):
                flag("🔴", t, "yf_name_changed", f"yfinance 名字「{rec['name']}」→「{info['name']}」（改名或代碼重用）")
                rec["history"].append({"date": today.isoformat(), "name": info["name"]})
            rec["name"] = info["name"]
            rec["checked"] = today.isoformat()
            for k in ("sector", "industry"):
                if info.get(k):
                    rec[k] = info[k]
        names_path.write_text(json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if m == "us":
        # 美股兩邊都是英文名，可以直接比
        for t, q in latest_q.items():
            if t in names and q.get("name") and name_sim(q["name"], names[t]["name"]) < NAME_SIM_MIN:
                flag("🟡", t, "name_mismatch", f"第二來源「{q['name']}」vs yfinance「{names[t]['name']}」")
    else:
        # 日股：yfinance 是英文名，改拿 Yahoo!ファイナンス日文名跟 JPX 官方日文名比
        jpx_path = base / "_jpx_listed.json"
        jpx = json.loads(jpx_path.read_text(encoding="utf-8"))["listed"] if jpx_path.exists() else {}
        for t, q in latest_q.items():
            if t in jpx and q.get("name") and name_sim(q["name"], jpx[t]["name"]) < NAME_SIM_MIN:
                flag("🟡", t, "name_mismatch", f"Yahoo!ファイナンス「{q['name']}」vs JPX「{jpx[t]['name']}」")
        for t in sorted(current):
            if jpx and t not in jpx:
                flag("🔴", t, "not_listed_jpx", "現任日經225成分股不在 JPX 上場銘柄一覧（下市/代碼錯？）")

    # --- 倖存者偏差洞：歷史成分股中沒有價格的比例，按年 ---
    holes = []
    for u in unis:
        for y in range(max(u.first_date().year, 2000), today.year + 1):
            d = date(y, 6, 30)
            if d > today:
                d = today
            mem = u.members_at(d)
            if not mem:
                continue
            miss = [t for t in mem if not md.has_v2(t)]
            holes.append((u.key, y, len(mem), len(miss)))

    # --- 報告 ---
    red = [f for f in flags if f[0] == "🔴" and f"{f[1]}:{f[2]}" not in acks]
    yellow = [f for f in flags if f[0] == "🟡" and f"{f[1]}:{f[2]}" not in acks]
    acked = [f for f in flags if f"{f[1]}:{f[2]}" in acks]
    L = [f"# {m.upper()} 數據品質報告（{today}）\n",
         f"市場最新交易日 {market_last}；現任成分股 {len(current)} 檔（{', '.join(u.key for u in unis)}）；"
         f"有數據 {len(loaded)} 檔；第二來源快照 {len(snap_data)} 份、比對 {n_cmp} 筆收市價。\n",
         f"**🔴 {len(red)} 嚴重 / 🟡 {len(yellow)} 注意 / ✅ {len(acked)} 已確認**\n"]
    for title, fl in (("🔴 嚴重", red), ("🟡 注意", yellow)):
        L.append(f"\n## {title}\n")
        L += [f"- `{t}` {c}：{msg}" for _, t, c, msg in fl] or ["- 無"]
    if acked:
        L.append("\n## ✅ 已確認\n")
        L += [f"- `{t}` {c}：{msg}（{acks[f'{t}:{c}']}）" for _, t, c, msg in acked]
    L.append("\n## 📉 倖存者偏差洞（歷史成分股抓不到價格的比例，每年 6/30）\n")
    L.append("| 指數 | 年 | 成分股 | 無價格 | 比例 |\n|---|---|---|---|---|")
    L += [f"| {k} | {y} | {n} | {miss} | {miss / n:.0%} |" for k, y, n, miss in holes]
    L.append("\n免費來源（Yahoo）不保留已下市股票的歷史——被收購/破產的公司在回測裡消失，"
             "等於只看活下來的公司。洞的比例越高的年份，回測結果越樂觀，判決時要打折。")
    base.mkdir(parents=True, exist_ok=True)
    (base / "QC_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    label = {"us": "🇺🇸 美股", "jp": "🇯🇵 日股"}[m]
    idx_names = "/".join(INDICES[u.key]["name"] for u in unis) or "（無成分股名單）"
    src2 = {"us": "Nasdaq.com", "jp": "Yahoo!ファイナンス"}[m]
    latest2 = snap_data[-1]["trade_date"] if snap_data else "—"
    digest = [f"📊 {label}數據日報 {today}（{idx_names}）",
              f"✅ yfinance {len(loaded)} 檔（現任成分股 {len(current)}），基準 {bench} 最新 {bench_last}",
              f"🏛 第二來源 {src2} 快照 {len(snap_data)} 份，最新 {latest2}（比對 {n_cmp} 筆收市價）",
              f"🔴 {len(red)} ｜ 🟡 {len(yellow)} ｜ ✅ 已確認 {len(acked)}"]
    digest += [f"🔴 {t} {c}：{msg}" for _, t, c, msg in red[:12]]
    if len(red) > 12:
        digest.append(f"……另 {len(red) - 12} 項 🔴 見報告")
    digest.append(f"報告：data/equities/{m}/QC_REPORT.md（分支 claude/gifted-carson-v2tvhw）")
    (base / "qc_digest.txt").write_text("\n".join(digest) + "\n", encoding="utf-8")
    alert = base / "qc_alert.txt"
    if red:
        alert.write_text("\n".join(digest) + "\n", encoding="utf-8")
    elif alert.exists():
        alert.unlink()
    print(digest[0])


if __name__ == "__main__":
    main()
