"""0342（Gold Brother）／5117（黃金戰鬥機）影子前向交叉驗證（使用者 10-31「LEVEL 同其他前向測試都做證」）。
同一批歸檔訊號（xau/sig/fwd_archive/，10-29 起），分別用經紀 M1（gb_forward 正式用）、Dukascopy、PAXG、GC=F 行 gb_rulesim.simulate，
睇結果會唔會因數據源而變。另類源用「同分鐘收市價中位差」對齊經紀價（期貨／代幣有基差）。只出數字，唔存訊號原文。
用法：python3 research/student_offline/gb_xval.py"""
import datetime as dt
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
import gb_forward as fw   # noqa: E402
import gb_rulesim as gb   # noqa: E402

SRCS = (("duka", "xau/sig/duka/"), ("paxg", "xau/sig/alt/paxg/"), ("gcf", "xau/sig/alt/gcf/"))


def load_rows(g, prefix, days):
    out = {}
    for d in days:
        rows = g.read_json(f"{prefix}{d}.json") or []
        for t, o, h, lo, c in rows:
            out[int(t)] = {"utc": int(t), "open": o, "high": h, "low": lo, "close": c}
    return [out[k] for k in sorted(out)]


def align(alt, ref):
    rc = {b["utc"]: b["close"] for b in ref}
    diffs = [b["close"] - rc[b["utc"]] for b in alt if b["utc"] in rc]
    if not diffs:
        return alt, None, 0
    off = statistics.median(diffs)
    return [{"utc": b["utc"], "open": b["open"] - off, "high": b["high"] - off, "low": b["low"] - off, "close": b["close"] - off} for b in alt], off, len(diffs)


def sim(bars, sigs, var):
    last = bars[-1]["utc"] if bars else 0
    per = []
    for s in sigs:
        if last - s["ts"] < fw.MIN_AFTER_SEC or not bars or bars[0]["utc"] > s["ts"] - 60:
            per.append(None)
            continue
        win = [b for b in bars if s["ts"] - 3600 <= b["utc"] <= s["ts"] + 24 * 3600]
        per.append(gb.simulate(win, s, **gb.VARIANTS[var]["kw"]))
    return per


def fmt_sum(per):
    got = [r for r in per if r is not None]
    if not got:
        return "冇數"
    s = gb.summarize(got)
    return f"已完 {len(got)}，成交 {s['n']}，ΣR {s['sum_r']:+.2f}，PF {s['pf']}，回撤 {s['max_dd_r']}R"


def main():
    g = gb.Gcs()
    signals = [g.read_json(n) for n in g.list(fw.ARCHIVE)]
    signals = [s for s in signals if isinstance(s, dict) and s.get("ch") in fw.CHANNELS and s.get("utc", "") >= fw.START]
    days = sorted({dt.datetime.fromtimestamp(s["ts"] + k * 86400, dt.timezone.utc).date().isoformat() for s in signals for k in (0, 1)})
    days = sorted(set(days) | {(dt.date.fromisoformat(days[0]) - dt.timedelta(days=1)).isoformat()}) if days else []
    brk = gb.fetch_broker_bars(g, 10)
    srcs = {"經紀": brk}
    info = []
    for name, prefix in SRCS:
        raw = load_rows(g, prefix, days)
        al, off, n = align(raw, brk)
        srcs[name] = al
        info.append(f"{name} {len(raw)} 根（對齊位移 {off:+.2f}，重疊 {n} 分鐘）" if off is not None else f"{name} {len(raw)} 根（同經紀冇重疊）")
    out = ["# 0342／5117 影子前向：數據源交叉驗證（10-31）", "",
           f"- 訊號：歸檔 {len(signals)} 張（{fw.START} 起）；經紀 M1 {len(brk)} 根；" + "；".join(info),
           "- 計法：gb_rulesim.simulate（同 gb_forward），訊號後要 ≥ 6 小時 K 線先計；另類源按同分鐘收市中位差對齊經紀價", ""]
    for ch, meta in fw.CHANNELS.items():
        sigs = sorted([s for s in signals if s["ch"] == ch], key=lambda s: s["ts"])
        vars_ = list(dict.fromkeys(["V0", meta["candidate"], "V6", "V13"]))
        out.append(f"## {meta['name']}（{ch}）{len(sigs)} 張")
        for var in vars_:
            res = {k: sim(b, sigs, var) for k, b in srcs.items()}
            out.append(f"- {var}：" + "｜".join(f"{k} {fmt_sum(v)}" for k, v in res.items()))
            for k in ("duka", "paxg", "gcf"):
                pairs = [(a, b) for a, b in zip(res["經紀"], res[k]) if a is not None and b is not None]
                if pairs:
                    diff = sum(b["r"] - a["r"] for a, b in pairs) / len(pairs)
                    flip = sum(1 for a, b in pairs if (a["r"] > 0.05) != (b["r"] > 0.05) and abs(a["r"] - b["r"]) > 0.1)
                    out.append(f"  - 經紀 vs {k}：同一批 {len(pairs)} 張，R 差平均 {diff:+.3f}，結果唔同 {flip} 張")
        out.append("")
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "gb_xval_out.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
