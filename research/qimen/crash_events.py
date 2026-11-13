"""大股災名單（死規則，使用者 2026-11-14 揀「用死規則揀，加埋納指」）。

規則：恒指、標普 500、納指 100 任何一個，喺 21 個交易日內（收市對收市）跌 ≥ 20%。
同一指數：符合條件嘅窗口重疊或者相隔 ≤ 60 日曆日就合併做一段；唔同指數嘅段重疊或相隔 ≤ 60 日曆日，合併做同一次事件。
每次事件記：開始（段內最早窗口起點）、急跌前高位（開始日前 60 個交易日至段尾之間，最低位之前嘅最高收市）、最低收市、邊啲指數入選。

用法：python3 research/qimen/crash_events.py   → 印表，並寫 research/qimen/crash_events.csv
"""
import csv
import os
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
FILES = {"恒指": "canary/data_external/hsi_daily.csv", "標普500": "data/us_futures/IDX_GSPC_daily.csv",
         "納指100": "data/us_futures/IDX_NDX_daily.csv"}
START, WIN, DROP, GAP = "1987-01-01", 21, -0.20, 60


def load(path):
    out = []
    for r in csv.DictReader(open(os.path.join(ROOT, path), encoding="utf-8")):
        try:
            out.append((r["Date"][:10], float(r["Close"])))
        except (ValueError, KeyError):
            pass
    return [x for x in out if x[0] >= START]


def od(s):
    return date.fromisoformat(s).toordinal()


def segments(d):
    """回傳 [(起, 止)]：符合條件窗口合併後嘅段。"""
    wins = [(d[i][0], d[i + WIN][0]) for i in range(len(d) - WIN) if d[i + WIN][1] / d[i][1] - 1 <= DROP]
    segs = []
    for a, b in wins:
        if segs and od(a) - od(segs[-1][1]) <= GAP:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return segs


def main():
    data = {n: load(p) for n, p in FILES.items()}
    allseg = sorted((a, b, n) for n, d in data.items() for a, b in segments(d))
    events = []
    for a, b, n in allseg:
        if events and od(a) - od(events[-1]["end"]) <= GAP:
            events[-1]["end"] = max(events[-1]["end"], b)
            events[-1]["idx"].add(n)
        else:
            events.append({"start": a, "end": b, "idx": {n}})
    rows = []
    for e in events:
        parts = []
        peak_first = None
        for n in ("恒指", "標普500", "納指100"):
            d = data[n]
            i0 = next((i for i, x in enumerate(d) if x[0] >= e["start"]), None)
            if i0 is None:
                continue
            seg = [x for x in d[max(0, i0 - 60):] if x[0] <= e["end"]]
            low = min(seg, key=lambda x: x[1])
            pk = max((x for x in seg if x[0] <= low[0]), key=lambda x: x[1])
            if n in e["idx"]:
                parts.append(f"{n} {pk[0]}→{low[0]} {low[1] / pk[1] - 1:+.0%}")
                peak_first = min(peak_first, pk[0]) if peak_first else pk[0]
        rows.append({"start": e["start"], "end": e["end"], "peak": peak_first, "indices": "、".join(sorted(e["idx"])), "detail": "；".join(parts)})
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash_events.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for i, r in enumerate(rows, 1):
        print(f"{i:2d} {r['start']}→{r['end']} 高位 {r['peak']}｜{r['detail']}")


if __name__ == "__main__":
    main()
