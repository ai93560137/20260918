"""rev15 離線用另類數據源再驗（使用者 10-31「rev15 離線用其他數據源再試」）。
讀 GCS xau/sig/alt/<src>/（由 .github/workflows/xau_alt_m1.yml 拎），用同 rev15_gap.py 一樣嘅規則／成交／R 計法，
同 Dukascopy 同日、實時影子比較。paxg 係 24／7：剔走週五 21:00–週日 22:00 UTC（同 MT5 休市一致）。
用法：python3 research/student_offline/rev15_alt.py paxg [rev15]"""
import datetime as dt
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "paxg"
RULE_ARG = sys.argv[2] if len(sys.argv) > 2 else "rev15"
sys.argv = [sys.argv[0], RULE_ARG]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rev15_gap as g   # noqa: E402


def closed(t):
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    wd, h = d.weekday(), d.hour
    return (wd == 4 and h >= 21) or wd == 5 or (wd == 6 and h < 22)


def main():
    out = []
    pr = lambda s="": (out.append(s), print(s))   # noqa: E731
    alt = [b for b in g.load(f"{g.config.PREFIX}alt/{SRC}/", g.days_between("2026-07-20", "2026-11-30"), "json") if not closed(b["time"])]
    if not alt:
        print(f"GCS {g.config.PREFIX}alt/{SRC}/ 冇數據——先跑 GitHub Actions「天覆陣 另類黃金 M1 數據」", file=sys.stderr)
        sys.exit(1)
    t0, t1 = alt[0]["time"], alt[-1]["time"] + 60
    fmt = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%m-%d %H:%M")   # noqa: E731
    day = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()   # noqa: E731
    duka = g.load(g.config.PREFIX + "duka/", g.days_between(day(t0), day(t1)), "json")
    live = g.live_preds(g.days_between("2026-10-20", "2026-11-30"))
    live_t0 = min(p["ts"] for p in live) if live else t1
    a_pr = g.score(g.run(alt, t0 + 2 * 86400, t1), alt)
    lo = t0 + 2 * 86400
    d_pr = g.score(g.run(duka, lo, min(t1, duka[-1]["time"] + 60)), duka) if duka else []
    hi = min(t1, duka[-1]["time"] + 60) if duka else t1
    pr(f"# {g.RULE} 離線：{SRC} vs Dukascopy（{SRC} {fmt(t0)}–{fmt(t1)}，{len(alt)} 根；已剔週末）")
    pr(f"- {SRC} 全段：{g.stat([p['r'] for p in a_pr])}")
    pr(f"- {SRC} 同 Dukascopy 重疊段（{fmt(lo)}–{fmt(hi)}）：{g.stat([p['r'] for p in a_pr if p['ts'] < hi])}")
    pr(f"- Dukascopy 同段：{g.stat([p['r'] for p in d_pr])}")
    pairs, oa, od = g.match([p for p in a_pr if p["ts"] < hi], d_pr)
    same = sum(1 for a, b in pairs if a["r"] is not None and b["r"] is not None and (a["r"] > 0) == (b["r"] > 0))
    pr(f"- {SRC} vs Dukascopy 逐張：配對 {len(pairs)}（結果同向 {same}）、只 {SRC} {len(oa)}、只 Dukascopy {len(od)}")
    pr(f"- {SRC} 實時同期（≥ {fmt(live_t0)}）：{g.stat([p['r'] for p in a_pr if p['ts'] >= live_t0])}；實時影子同期：{g.stat([p['r'] for p in live if p['ts'] < t1])}")
    by = {}
    for p in a_pr:
        by.setdefault(dt.datetime.fromtimestamp(p["ts"], dt.timezone.utc).strftime("%Y-%m"), []).append(p["r"])
    for k in sorted(by):
        pr(f"  - {k}：{g.stat(by[k])}")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{g.RULE.split(':')[1]}_{SRC}_out.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"寫咗 {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
