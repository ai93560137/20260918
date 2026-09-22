#!/usr/bin/env python3
"""v2 格式日線抓取（美股/日股；格式見 marketdata.py）——在 GitHub Actions 上跑。

    python3 scripts/fetch_equities.py universes/us/fetch_list.txt
    python3 scripts/fetch_equities.py --shares universes/jp/fetch_list.txt   # 連流通股數一起抓

每檔 yfinance history(1995 起, actions=True)，但**只重寫內容有變的檔**：
- prices_<YYYY>.csv：平常只有今年那個檔多一行；拆股（Close 全段回溯）或 Yahoo
  修正舊數據時舊年份才會變
- actions.csv：新除淨/拆股才變
- shares.csv：--shares 時才抓（慢，週一跑一次就夠）
每檔都用存下來的原始價+股息重算 AdjClose，跟 yfinance 的 Adj Close 比對，最大相對誤差
記在 data/equities/<market>/_fetch_status.json（QC 會看），證明「不存 AdjClose」不失真。

抓不到的代碼（已下市/被收購——Yahoo 不留下市股歷史）：連續失敗 3 次後平日跳過、
只在週一重試，省時間；失敗本身記在狀態檔，QC 報告會列出（那就是倖存者偏差的洞）。
"""
import argparse
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import marketdata as md  # noqa: E402

SKIP_AFTER_FAILS = 3


def read_list(paths: list[Path]) -> list[str]:
    out = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line not in out:
                out.append(line)
    return out


def fmt(x) -> str:
    if x is None or x != x:  # NaN
        return ""
    # 低價（拆股還原後的早年價格常只有幾分錢）多留位數，否則重算 AdjClose 的相對誤差會放大
    s = f"{float(x):.{6 if abs(float(x)) < 10 else 4}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def to_csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def save_history(ticker: str, hist) -> dict:
    d = md.v2_dir(ticker)
    by_year: dict[int, list[list]] = {}
    act_rows = []
    for idx, r in hist.iterrows():
        day = idx.date()
        if r["Close"] != r["Close"]:  # NaN 收市（Yahoo 偶有的空行）不存
            continue
        vol = r.get("Volume", 0)
        by_year.setdefault(day.year, []).append(
            [day.isoformat(), fmt(r["Open"]), fmt(r["High"]), fmt(r["Low"]), fmt(r["Close"]),
             int(vol) if vol == vol else 0])
        div = float(r.get("Dividends", 0) or 0)
        spl = float(r.get("Stock Splits", 0) or 0)
        if div or spl:
            act_rows.append([day.isoformat(), f"{div:.6f}".rstrip("0").rstrip(".") if div else "",
                             f"{spl:g}" if spl else ""])
    changed = 0
    for y, rows in by_year.items():
        changed += write_if_changed(d / f"prices_{y}.csv",
                                    to_csv(["Date", "Open", "High", "Low", "Close", "Volume"], rows))
    # 某年份整年消失（極少見：Yahoo 砍掉錯誤數據）也要同步刪掉舊檔
    for p in d.glob("prices_*.csv"):
        if int(p.stem.split("_")[1]) not in by_year:
            p.unlink()
            changed += 1
    changed += write_if_changed(d / "actions.csv", to_csv(["Date", "Dividend", "Split"], act_rows))

    # 用剛存的檔重算 AdjClose，跟 yfinance 比
    loaded = md.load_ohlcv(ticker)
    yf_adj = {idx.date(): float(v) for idx, v in hist["Adj Close"].items() if v == v}
    errs = [abs(r["AdjClose"] / yf_adj[r["Date"]] - 1) for r in loaded
            if r["Date"] in yf_adj and yf_adj[r["Date"]] > 0]
    return {"rows": len(loaded), "first": loaded[0]["Date"].isoformat(), "last": loaded[-1]["Date"].isoformat(),
            "files_changed": changed, "adj_err_max": round(max(errs), 6) if errs else None}


def save_shares(ticker: str, yf) -> int:
    try:
        s = yf.Ticker(ticker).get_shares_full(start="2000-01-01")
    except Exception as exc:
        print(f"WARN {ticker}: 股數抓取失敗 {exc}", file=sys.stderr)
        return 0
    if s is None or s.empty:
        return 0
    last: dict[str, int] = {}
    for idx, v in s.items():
        if v == v:
            last[idx.date().isoformat()] = int(v)   # 同一天多筆取最後一筆
    rows = [[k, v] for k, v in sorted(last.items())]
    write_if_changed(md.v2_dir(ticker) / "shares.csv", to_csv(["Date", "Shares"], rows))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lists", nargs="+", type=Path)
    ap.add_argument("--shares", action="store_true", help="也抓流通股數歷史（慢）")
    ap.add_argument("--budget-min", type=float, default=45, help="總時間上限（分鐘），超過就停、下輪續抓")
    args = ap.parse_args()
    import yfinance as yf

    tickers = read_list(args.lists)
    markets = {md.market_of(t) for t in tickers}
    status: dict[str, dict] = {}
    for m in markets:
        p = md.V2_DIR / m / "_fetch_status.json"
        if p.exists():
            status.update(json.loads(p.read_text(encoding="utf-8")))
    today = datetime.now(timezone.utc).date()
    is_retry_day = today.weekday() == 0
    started = time.monotonic()
    n_ok = n_fail = n_skip = 0
    # 很久沒抓的排前面：時間不夠被截斷時，下一輪先補它們
    tickers.sort(key=lambda t: status.get(t, {}).get("fetched", ""))
    for t in tickers:
        if time.monotonic() - started > args.budget_min * 60:
            print(f"WARN 超過 {args.budget_min} 分鐘，停在 {t}（下輪續抓）", file=sys.stderr)
            break
        st = status.setdefault(t, {})
        if st.get("fails", 0) >= SKIP_AFTER_FAILS and not is_retry_day:
            n_skip += 1
            continue
        try:
            hist = yf.Ticker(t).history(start="1995-01-01", auto_adjust=False, actions=True)
            if hist.empty:
                raise RuntimeError("空資料（已下市/代碼錯/暫時 rate limit）")
            st.update(save_history(t, hist), fails=0, fetched=today.isoformat(), error=None)
            if args.shares:
                st["shares_rows"] = save_shares(t, yf)
            n_ok += 1
            if st["adj_err_max"] is not None and st["adj_err_max"] > 1e-3:
                print(f"WARN {t}: 重算 AdjClose 與 yfinance 最大差 {st['adj_err_max']:.2%}", file=sys.stderr)
        except Exception as exc:
            st["fails"] = st.get("fails", 0) + 1
            st["error"] = str(exc)[:160]
            st["last_fail"] = today.isoformat()
            n_fail += 1
            print(f"ERROR {t}: {exc}", file=sys.stderr)
        time.sleep(0.3)

    for m in markets:
        sub = {t: v for t, v in status.items() if md.market_of(t) == m}
        p = md.V2_DIR / m / "_fetch_status.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sub, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"成功 {n_ok}、失敗 {n_fail}、跳過（連續失敗） {n_skip}，共 {len(tickers)} 檔")


if __name__ == "__main__":
    main()
