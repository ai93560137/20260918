#!/usr/bin/env python3
"""建美股指數 point-in-time 成分股區間檔 universes/<index>/membership.csv（ticker,start,end）
與抓取清單 universes/us/fetch_list.txt。

S&P 500：fja05680/sp500（MIT，Clenow《Trading Evolved》原始名單 1996–2019 + 作者依
Wikipedia 逐次更新）的逐日名單，轉成每檔的在榜區間。
    git clone --depth 1 https://github.com/fja05680/sp500 /tmp/sp500
    python3 scripts/build_universe_us.py --sp500-csv "/tmp/sp500/S&P 500 Historical Components & Changes (Updated).csv"

代碼轉 Yahoo 格式（BRK.B -> BRK-B）；改代碼的公司（FB -> META：Yahoo 只用新代碼保留
整段歷史）用 universes/us/renames.csv（old,new,note）對照，舊代碼的區間改掛新代碼、
與新代碼的區間相接就合併。
"""
import argparse
import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIV = ROOT / "universes"
FETCH_SINCE = date(2008, 1, 1)     # 抓取清單：2008 後仍在榜的（輪動檢測 2010 起，多留暖身）
BENCHMARKS = ["SPY", "QQQ", "DIA", "^GSPC", "^NDX", "^DJI", "RSP"]


def yahoo(t: str) -> str:
    return t.replace(".", "-")


def load_renames() -> dict[str, str]:
    p = UNIV / "us" / "renames.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {r["old"]: r["new"] for r in csv.DictReader(f) if not r["old"].startswith("#")}


def runs_from_snapshots(rows: list[tuple[date, set[str]]]) -> list[tuple[str, date, date | None]]:
    """逐次名單 -> 每檔連續在榜區間 [start, end)。"""
    out = []
    open_since: dict[str, date] = {}
    for d, members in rows:
        for t in members:
            open_since.setdefault(t, d)
        for t in [t for t in open_since if t not in members]:
            out.append((t, open_since.pop(t), d))
    out += [(t, a, None) for t, a in open_since.items()]
    return out


def merge(intervals: list[tuple[str, date, date | None]]) -> list[tuple[str, date, date | None]]:
    by_t: dict[str, list] = {}
    for t, a, b in intervals:
        by_t.setdefault(t, []).append([a, b])
    out = []
    for t, iv in by_t.items():
        iv.sort(key=lambda x: x[0])
        cur = iv[0]
        for a, b in iv[1:]:
            if cur[1] is None or a <= cur[1]:   # 相接或重疊（改代碼當天新舊交接）就合併
                cur[1] = None if b is None or cur[1] is None else max(cur[1], b)
            else:
                out.append((t, cur[0], cur[1]))
                cur = [a, b]
        out.append((t, cur[0], cur[1]))
    return sorted(out, key=lambda x: (x[0], x[1]))


def write_membership(index: str, intervals, source_note: str) -> None:
    d = UNIV / index
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "membership.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["ticker", "start", "end"])
        for t, a, b in intervals:
            w.writerow([t, a.isoformat(), b.isoformat() if b else ""])
    print(f"{index}: {len(intervals)} 個區間、{len({t for t, _, _ in intervals})} 檔 -> {d / 'membership.csv'}"
          f"（{source_note}）")


def build_sp500(csv_path: Path, renames: dict[str, str]) -> list:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            mem = {renames.get(yahoo(t), yahoo(t)) for t in r["tickers"].split(",") if t}
            rows.append((date.fromisoformat(r["date"]), mem))
    rows.sort(key=lambda x: x[0])
    return merge(runs_from_snapshots(rows))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sp500-csv", type=Path)
    args = ap.parse_args()
    renames = load_renames()

    if args.sp500_csv:
        write_membership("sp500", build_sp500(args.sp500_csv, renames), "fja05680/sp500")

    # 抓取清單：所有美股指數 membership 的聯集（2008 後仍在榜）+ 基準
    tickers = set()
    for idx in ("sp500", "ndx", "djia"):
        p = UNIV / idx / "membership.csv"
        if not p.exists():
            continue
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r["end"] or date.fromisoformat(r["end"]) >= FETCH_SINCE:
                    tickers.add(r["ticker"])
    out = UNIV / "us" / "fetch_list.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 自動產生（scripts/build_universe_us.py）：美股指數 PIT 成分股聯集 + 基準\n"
                   + "\n".join(BENCHMARKS + sorted(tickers - set(BENCHMARKS))) + "\n", encoding="utf-8")
    print(f"抓取清單 {len(tickers)} 檔 + {len(BENCHMARKS)} 基準 -> {out}")


if __name__ == "__main__":
    main()
