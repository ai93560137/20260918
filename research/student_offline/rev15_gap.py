"""rev15 離線 vs 實時差距拆解（總指揮 10-31 轉使用者「離線回測結果係 −0.06R，搞清楚」）。
同一套 features.rule_candidates（60 分鐘冷卻）＋ signals.evaluate（同一分鐘 SL／TP 都掂當 SL）＋ 學生計 R
（實際成交價、2R 全平、扣 STUDENT_COST），分別喺：
  A. Dukascopy M1（GCS xau/sig/duka/<日>.json）全期／實時開始前／實時同期
  B. 經紀 M1（GCS xau/sig/bars/<日>.jsonl，EA 心跳存檔）同 Dukascopy 同日
  C. 實時影子（GCS xau/sig/student/log/<日>.jsonl 出區紀錄＋ student/state.json 結果）
逐張對帳（同方向、±5 分鐘）。只輸出數字，唔存價格以外嘅資料。用法：python3 research/student_offline/rev15_gap.py"""
import collections
import datetime as dt
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("XAU_SYMBOL", "XAUUSD")
os.environ.setdefault("XAU_BOOK", "signal")
sys.path.insert(0, os.path.join(ROOT, "xau"))
sys.path.insert(0, os.path.join(ROOT, "research", "gb_rulesim"))
import types   # noqa: E402
try:
    import anthropic   # noqa: F401
except ImportError:
    _an = types.ModuleType("anthropic"); _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = Exception; sys.modules["anthropic"] = _an
import config, features, signals   # noqa: E402
import gb_rulesim as gb            # noqa: E402

RULE = "rule:" + (sys.argv[1] if len(sys.argv) > 1 else "rev15")
MATCH_SEC = 300
G = gb.Gcs()


def _bars(rows):
    out = {}
    for b in rows or []:
        if isinstance(b, (list, tuple)):
            t, o, h, l, c = int(b[0]), *map(float, b[1:5])
        else:
            t = int(b.get("utc") if b.get("utc") is not None else b["time"]); o, h, l, c = (float(b[k]) for k in ("open", "high", "low", "close"))
        out[t] = {"time": t, "open": o, "high": h, "low": l, "close": c}
    return out


def load(prefix, days, ext):
    bars = {}
    for d in days:
        doc = G.read_json(f"{prefix}{d}.{ext}")
        if doc is None:
            continue
        bars.update(_bars(doc.get("bars") if isinstance(doc, dict) else doc))
    return [bars[k] for k in sorted(bars)]


def run(m1, t_from, t_to):
    """逐分鐘行規則學生（同 student.rule_tick：每條規則 60 分鐘冷卻），只留 RULE。"""
    last, preds = 0, []
    for i, b in enumerate(m1):
        now = b["time"] + 60
        if not (t_from <= now < t_to) or now - last < 3600:
            continue
        win = m1[max(0, i - 419):i + 1]
        if len(win) < 30:
            continue
        for c in features.rule_candidates(win, 0, now, None):
            if "rule:" + c["rule"] != RULE:
                continue
            mid = (c["entry_low"] + c["entry_high"]) / 2; sgn = 1 if c["side"] == "BUY" else -1
            preds.append({"ts": now, "side": c["side"], "entry_low": c["entry_low"], "entry_high": c["entry_high"], "sl": c["sl"],
                          "tp": [round(mid + sgn * config.STUDENT_R_TARGET * features.STRUCT_SL, 2)]})
            last = now
    return preds


def r_of(p, o):
    """同 student.score_pending：實際成交價、2R 全平、扣 STUDENT_COST；未成交／未完回 None。"""
    if not isinstance(o, dict) or not o.get("filled_ts") or o.get("final") not in ("all_tp", "sl"):
        return None
    sgn = 1 if p["side"] == "BUY" else -1
    mid = (p["entry_low"] + p["entry_high"]) / 2; risk = abs(mid - p["sl"]) or 1e-9
    fill = o.get("fill_px") or mid
    ex = p["tp"][0] if o["final"] == "all_tp" else p["sl"]
    return (sgn * (ex - fill) - config.STUDENT_COST) / risk


def score(preds, m1):
    T = [b["time"] for b in m1]
    import bisect
    for p in preds:
        i = bisect.bisect_left(T, p["ts"] - 60)
        fut = m1[i:i + 24 * 60]
        view = {"side": p["side"], "entry_low": p["entry_low"], "entry_high": p["entry_high"], "sl": p["sl"], "tp": p["tp"], "msg_ts": p["ts"], "order_type": None}
        p["outcome"] = signals.evaluate(view, fut, 0, None, p["ts"] + 24 * 3600 + 60)
        p["r"] = r_of(p, p["outcome"])
    return preds


def stat(rs):
    rs = [r for r in rs if r is not None]
    if not rs:
        return "n=0"
    w = [r for r in rs if r > 0]; l = [-r for r in rs if r < 0]
    pf = sum(w) / sum(l) if l else float("inf")
    s = mx = 0
    for r in rs:
        s = s + 1 if r < 0 else 0; mx = max(mx, s)
    return f"n={len(rs)} 平均 {sum(rs) / len(rs):+.3f}R ΣR {sum(rs):+.1f} PF {pf:.2f} 勝率 {len(w) / len(rs):.0%} 最大連敗 {mx}"


def match(a, b):
    """a、b 兩組 preds：同方向、ts 差 ≤ MATCH_SEC 算同一張。回傳 (配對, 只喺 a, 只喺 b)。"""
    used, pairs, only_a = set(), [], []
    for p in a:
        q = next((j for j, x in enumerate(b) if j not in used and x["side"] == p["side"] and abs(x["ts"] - p["ts"]) <= MATCH_SEC), None)
        if q is None:
            only_a.append(p)
        else:
            used.add(q); pairs.append((p, b[q]))
    return pairs, only_a, [x for j, x in enumerate(b) if j not in used]


def days_between(a, b):
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [(d0 + dt.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]


def ts_of(d):
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp())


def live_preds(days):
    st = G.read_json(config.PREFIX + "student/state.json") or {}
    outcome = {p["id"]: p for p in st.get("preds") or []}
    rows = []
    for d in days:
        doc = G.read_json(f"{config.PREFIX}student/log/{d}.jsonl")
        for p in doc if isinstance(doc, list) else []:
            if p.get("student") == RULE:
                full = outcome.get(p["id"], p)
                rows.append({**p, "outcome": full.get("outcome"), "r": r_of(p, full.get("outcome")), "in_state": p["id"] in outcome})
    return sorted(rows, key=lambda p: p["ts"])


def main():
    out = []
    pr = lambda s="": (out.append(s), print(s))   # noqa: E731
    duka_days = days_between("2026-07-24", "2026-10-31")
    print("讀 Dukascopy…", file=sys.stderr)
    duka = load(config.PREFIX + "duka/", duka_days, "json")
    print("讀經紀 M1…", file=sys.stderr)
    brk = load(config.PREFIX + "bars/", days_between("2026-10-20", "2026-10-31"), "jsonl")
    live = live_preds(days_between("2026-10-20", "2026-10-31"))
    live_t0 = min(p["ts"] for p in live) if live else ts_of("2026-10-22")
    duka_t1 = duka[-1]["time"] + 60 if duka else 0
    brk_t0, brk_t1 = (brk[0]["time"], brk[-1]["time"] + 60) if brk else (0, 0)
    fmt = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%m-%d %H:%M")   # noqa: E731
    pr(f"# {RULE} 離線 vs 實時差距（數據：Dukascopy {fmt(duka[0]['time'])}–{fmt(duka_t1)}；經紀 M1 {fmt(brk_t0)}–{fmt(brk_t1)}；實時影子 {len(live)} 條出區，最早 {fmt(live_t0)}）")
    pr()
    print("跑 Dukascopy…", file=sys.stderr)
    d_all = score(run(duka, duka[0]["time"] + 2 * 86400, duka_t1), duka)
    pr("## ① 時期效應（Dukascopy）")
    pr(f"- 全期：{stat([p['r'] for p in d_all])}")
    pr(f"- 實時開始前（< {fmt(live_t0)}）：{stat([p['r'] for p in d_all if p['ts'] < live_t0])}")
    pr(f"- 實時同期（{fmt(live_t0)}–{fmt(duka_t1)}）：{stat([p['r'] for p in d_all if p['ts'] >= live_t0])}")
    by_month = collections.defaultdict(list)
    for p in d_all:
        by_month[dt.datetime.utcfromtimestamp(p["ts"]).strftime("%Y-%m")].append(p["r"])
    for k in sorted(by_month):
        pr(f"  - {k}：{stat(by_month[k])}")
    by_wk = collections.defaultdict(list)
    for p in d_all:
        by_wk[dt.datetime.utcfromtimestamp(p["ts"]).strftime("%G-W%V")].append(p["r"])
    pr("- 每週 ΣR：" + "、".join(f"{k[-3:]} {sum(r for r in v if r is not None):+.1f}（{len([r for r in v if r is not None])}）" for k, v in sorted(by_wk.items())))
    live_same = [p for p in live if p["ts"] < duka_t1]
    pr(f"- 實時影子同期（< {fmt(duka_t1)}）：{stat([p['r'] for p in live_same])}；實時全部：{stat([p['r'] for p in live])}")
    pr()
    pr("## ② 數據源（同期：經紀 M1 有數嗰段）")
    if brk:
        b_pr = score(run(brk, brk_t0 + 7 * 3600, brk_t1), brk)
        lo, hi = brk_t0 + 7 * 3600, min(brk_t1, duka_t1)
        d_seg = [p for p in d_all if lo <= p["ts"] < hi]; b_seg = [p for p in b_pr if lo <= p["ts"] < hi]
        l_seg = [p for p in live if lo <= p["ts"] < hi]
        pr(f"- 時段 {fmt(lo)}–{fmt(hi)}：Dukascopy {stat([p['r'] for p in d_seg])}")
        pr(f"- 同時段 經紀 M1：{stat([p['r'] for p in b_seg])}")
        pr(f"- 同時段 實時影子：{stat([p['r'] for p in l_seg])}")
        pairs, od, ob = match(d_seg, b_seg)
        same = sum(1 for a, b in pairs if a["r"] is not None and b["r"] is not None and (a["r"] > 0) == (b["r"] > 0))
        pr(f"- Dukascopy vs 經紀逐張：配對 {len(pairs)}（結果同向 {same}）、只 Dukascopy {len(od)}、只經紀 {len(ob)}")
        bs = [b["r"] - a["r"] for a, b in pairs if a["r"] is not None and b["r"] is not None]
        if bs:
            pr(f"- 配對單 R 差（經紀−Dukascopy）平均 {sum(bs) / len(bs):+.3f}R")
        pr(f"- 經紀 M1 全段（{fmt(brk_t0 + 7 * 3600)}–{fmt(brk_t1)}）：{stat([p['r'] for p in b_pr])}；同段實時：{stat([p['r'] for p in live if p['ts'] >= brk_t0 + 7 * 3600])}")
    pr()
    pr("## ③ 逐張對帳（Dukascopy 離線 vs 實時影子，同期）")
    d_same = [p for p in d_all if live_t0 <= p["ts"] < duka_t1]
    pairs, od, ol = match(d_same, live_same)
    pr(f"- 配對 {len(pairs)}：離線 {stat([a['r'] for a, b in pairs])}｜實時 {stat([b['r'] for a, b in pairs])}")
    diff = [(b["r"] or 0) - (a["r"] or 0) for a, b in pairs if a["r"] is not None and b["r"] is not None]
    flip = sum(1 for a, b in pairs if a["r"] is not None and b["r"] is not None and (a["r"] > 0) != (b["r"] > 0))
    if diff:
        pr(f"  - 配對單 R 差（實時−離線）平均 {sum(diff) / len(diff):+.3f}R；輸贏相反 {flip} 張")
    pr(f"- 只喺離線：{len(od)} 張 {stat([p['r'] for p in od])}")
    pr(f"- 只喺實時：{len(ol)} 張 {stat([p['r'] for p in ol])}")
    gaps = collections.Counter()
    for p in od:
        near = [b for b in duka if p["ts"] - 120 <= b["time"] + 60 <= p["ts"]]
        gaps["Dukascopy 有、實時心跳冇（實時嗰陣冇 bar／冷卻錯開）" if near else "其他"] += 1
    for k, v in gaps.items():
        pr(f"  - {k}：{v}")
    pr()
    pr("## ④ 成交／成本模型")
    pr(f"- 兩邊同一個 signals.evaluate：入場區（±SIG_FILL_TOL={config.SIG_FILL_TOL}）碰到先成交，成交價＝實際去到嘅近邊／開盤；同一根 K 線 SL 同 TP 都掂當 SL；2R 全平；每張扣 STUDENT_COST={config.STUDENT_COST:.2f} 美元")
    unfilled = lambda ps: sum(1 for p in ps if not (p.get("outcome") or {}).get("filled_ts"))   # noqa: E731
    pr(f"- 未成交：離線同期 {unfilled(d_same)}／{len(d_same)}；實時同期 {unfilled(live_same)}／{len(live_same)}；實時有 {sum(1 for p in live if not p['in_state'])} 條已跌出 state（冇結果，唔計）")
    path = os.path.join(os.path.dirname(__file__), f"{RULE.split(':')[1]}_gap_out.md")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"寫咗 {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
