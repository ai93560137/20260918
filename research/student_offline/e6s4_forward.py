"""[IDEAS #160] 規則學生「E6 S4 1R」結構影子前向：同一批出區（現行規則參數、60 分鐘冷卻），現行結構（E4 Z2 S6 2R）同新結構（E6 Z2 S4 1R）並排計。
數據＝經紀 M1 GCS xau/sig/bars/<日>.jsonl（2026-11-01 22:00 UTC 起；之前一日做預熱）。判斷以 IDEAS #160 預先登記為準。唔落單、唔寫 GCS。
用法：python3 research/student_offline/e6s4_forward.py [--start 2026-11-01T22:00]"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fit_rules as fr   # noqa: E402

START = "2026-11-01T22:00"
RULES = ("rev15", "level", "rev15x", "swing")
CUR = dict(fr.CUR_COMMON)                                   # E4 Z2 S6 2R 冷卻 60
NEW = {**fr.CUR_COMMON, "E": 6.0, "S": 4.0, "RT": 1.0}      # E6 Z2 S4 1R 冷卻 60
TARGET_N = 30


def _broker_utc(server_t):
    from zoneinfo import ZoneInfo
    guess = dt.datetime.fromtimestamp(int(server_t) - 7200, dt.timezone.utc)
    return int(server_t) - (3 if guess.astimezone(ZoneInfo("America/New_York")).dst() else 2) * 3600


def broker_bars(start_ts):
    sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
    import gb_rulesim as gb   # noqa: E402
    g = gb.Gcs()
    d0 = dt.datetime.fromtimestamp(start_ts - 86400, dt.timezone.utc).date().isoformat()
    names = sorted(n for n in g.list(gb.BARS_PREFIX) if n.rsplit("/", 1)[-1][:10] >= d0)
    import json
    rows = {}
    for nm in names:
        for ln in (g.read_text(nm) or "").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                for b in json.loads(ln):
                    if isinstance(b, dict) and (b.get("time") is not None or b.get("utc") is not None):
                        # 用伺服器時間重算 UTC（週末 server_offset 會計錯、星期五 K 線重複存去週末；同 xau/g7_live.broker_utc）
                        u = _broker_utc(b["time"]) if b.get("time") is not None else int(b["utc"])
                        rows[u] = b
            except ValueError:
                continue
    ks = sorted(rows)
    d = {"t": np.array(ks, dtype=np.int64)}
    for k, n in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
        d[k] = np.array([float(rows[t][n]) for t in ks])
    # 剔休市平盤 K 線（EA 週末心跳照寫、價唔郁；同 research search.load 一樣）
    if len(ks):
        flat = (d["h"] == d["l"]) & (np.r_[np.nan, d["c"][:-1]] == d["c"])
        d = {k: v[~flat] for k, v in d.items()}
    return d


def judge(new, cur):
    ok = {"①≥30張": new["n"] >= TARGET_N,
          "②+0.2R PF1.3": new["n"] > 0 and new["avg"] >= 0.2 and new["pf"] >= 1.3,
          "③連敗≤6": new["streak"] <= 6,
          "④好過現行≥0.1R": new["n"] > 0 and cur["n"] > 0 and new["avg"] - cur["avg"] >= 0.1}
    return ok


def main():
    start = START
    if "--start" in sys.argv:
        start = sys.argv[sys.argv.index("--start") + 1]
    t0 = fr.ts_of(start)
    d = broker_bars(t0)
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    out = ["# IDEAS #160 E6 S4 1R 影子前向（經紀 M1）", ""]
    if len(d["t"]) == 0 or d["t"][-1] < t0:
        out.append(f"- 未有 {start} 之後嘅經紀 K 線")
        print("\n".join(out)); return
    have = int(np.sum(d["t"] >= t0))
    span = (int(d["t"][-1]) + 60 - t0) // 60
    out.append(f"- 由 {start} UTC 到 {dt.datetime.fromtimestamp(int(d['t'][-1]) + 60, dt.timezone.utc):%m-%d %H:%M}；經紀 M1 {have} 根（覆蓋率 {have / max(span, 1):.0%}，含休市）")
    out.append("| 規則 | 出區 | 現行 E4 S6 2R | 新 E6 S4 1R | 判斷 |")
    out.append("|---|---|---|---|---|")
    for rule in RULES:
        raw = fr.raw_signals(d, rule, fr.CURRENT[rule])
        sigs = fr.cooldown(raw, d["t"], 60, t0, now + 60)
        mats = fr.future_mats(d, sigs)
        rc = fr.simulate(mats, CUR["E"], CUR["Z"], CUR["S"], CUR["RT"])
        rn = fr.simulate(mats, NEW["E"], NEW["Z"], NEW["S"], NEW["RT"])
        sc, sn = fr.stats(rc), fr.stats(rn)
        ok = judge(sn, sc)
        verdict = "達標" if all(ok.values()) else ("未夠張數" if not ok["①≥30張"] else "唔達標")
        out.append(f"| {rule} | {len(sigs)} | {fr.fmt(sc)} | {fr.fmt(sn)} | {verdict}（" + "、".join(f"{k}{'✓' if v else '✗'}" for k, v in ok.items()) + "） |")
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "E6S4_FORWARD.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
