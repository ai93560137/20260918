"""[IDEAS #1005] AI 揀入場（936）唔使 API 嘅回測。規格同成功標準以 IDEAS #1005 預先登記為準（跑之前 commit）。

A：921 已記錄嘅 Opus 決策（xau/decisions/<日>.jsonl，10-20 → 11-06）對 rev15 出區（券商 M1 xau/sig/bars/）：
   A1＝出區後 2 分鐘內 921 同方向開倉 → 用 921 嘅開倉價／止蝕／止賺；A2＝出區後 30 分鐘內 921 同方向開倉。
B：盲測——2026-08-01 → 10-30 MT5 M1 嘅 rev15 出區抽 60 個（固定種子），每題只畀出區前 120 根 M1＋48 根 M15，
   隱藏日期、價格平移（每題唔同），由工作階段子代理答（揀入場／SL／TP 或唔做）；答完先用真價計分。
成交同計分同 ai_entry_forward.sim（掂入場 ±0.3 先成交、TTL 30 分鐘、同一根 SL／TP 都掂當 SL、24 小時未完唔計、每張扣 0.5 美元）。
用法：
  python3 research/student_offline/ai_entry_replay.py a                 → AI_REPLAY_A.md
  python3 research/student_offline/ai_entry_replay.py make <題目目錄>  → 題目 q_*.json（俾子代理）＋答案匙 key.json（唔好俾子代理睇）
  python3 research/student_offline/ai_entry_replay.py score <題目目錄> → AI_REPLAY_B.md（讀 answers_*.json）
[IDEAS #1006] make <目錄> --seed 1006 --exclude-seed 1005 [--hint]：抽另一批題（剔走 #1005 嗰 60 題）；--hint 喺每題加 rev15 歷史提示。
  score <目錄> --out AI_REPLAY_1006_hint.md：指定輸出檔名。"""
import datetime as dt
import glob
import json
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ai_entry_forward as af   # noqa: E402
import e6s4_forward as ef       # noqa: E402
import fit_rules as fr          # noqa: E402

P = fr.CURRENT["rev15"]
N_B = 60
SEED = 1005
MAX_DIST, SL_MIN, SL_MAX = 15.0, 2.0, 15.0


def signals(d, t_from, t_to):
    raw = fr.raw_signals(d, "rev15", P)
    return fr.cooldown(raw, d["t"], 60, t_from, t_to)


def e6s4(d, ts, side, price):
    sgn = 1 if side == "BUY" else -1
    mid = price - sgn * 6.0
    return af.sim(d, ts, side, mid, mid - sgn * 4.0, mid + sgn * 4.0, lo=mid - 2.0, hi=mid + 2.0)


def valid(side, price, e, sl, tp):
    sgn = 1 if side == "BUY" else -1
    if None in (e, sl, tp):
        return False
    risk = (e - sl) * sgn
    return (e - price) * sgn <= 0.3 and abs(price - e) <= MAX_DIST and SL_MIN <= risk <= SL_MAX and (tp - e) * sgn > 0


# ---------------------------------------------------------------- A：921 決策
def load_decisions(g, d0, d1):
    rows = []
    for nm in sorted(g.list("xau/decisions/")):
        day = nm.rsplit("/", 1)[-1][:10]
        if not (d0 <= day <= d1):
            continue
        for ln in (g.read_text(nm) or "").splitlines():
            ln = ln.strip()
            if ln.startswith("["):
                try:
                    rows += json.loads(ln)
                except ValueError:
                    pass
    return sorted([r for r in rows if str(r.get("final") or "").startswith("OPEN") and r.get("stop")], key=lambda r: r["ts"])


def part_a():
    sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
    import gb_rulesim as gb   # noqa: E402
    g = gb.Gcs()
    d0, d1 = "2026-10-20", "2026-11-06"
    opens = load_decisions(g, d0, d1)
    d = ef.broker_bars(fr.ts_of(d0) + 86400)
    sigs = signals(d, fr.ts_of(d0), fr.ts_of(d1) + 86400)
    ots = np.array([o["ts"] for o in opens])
    res = {"E6S4（全部出區）": [], "A1 921（2 分鐘內同向開）": [], "E6S4（A1 同一批）": [], "A2 921（30 分鐘內同向開）": [], "E6S4（A2 同一批）": []}
    for i, side in sigs:
        ts = int(d["t"][i]) + 60; price = float(d["c"][i])
        r6 = e6s4(d, ts, side, price)
        if r6 is not None:
            res["E6S4（全部出區）"].append(r6)
        want = "OPEN_LONG" if side == "BUY" else "OPEN_SHORT"
        for key, win, base in (("A1 921（2 分鐘內同向開）", 120, "E6S4（A1 同一批）"), ("A2 921（30 分鐘內同向開）", 1800, "E6S4（A2 同一批）")):
            j = int(np.searchsorted(ots, ts - 5))
            hit = next((o for o in opens[j:] if o["ts"] <= ts + win and o["final"] == want), None)
            if hit is None:
                continue
            e, sl, tp = float(hit["price"]), float(hit["stop"]), hit.get("target")
            tp = float(tp) if tp else e + (1 if side == "BUY" else -1) * 2 * abs(e - sl)
            r = af.sim(d, float(hit["ts"]), side, e, sl, tp)
            if r is not None:
                res[key].append(r)
                if r6 is not None:
                    res[base].append(r6)
    out = ["# IDEAS #1005 A：921 已記錄決策 對 rev15 出區", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{d0}→{d1}；rev15 出區 {len(sigs)} 次；921 開倉決定 {len(opens)} 次（券商 M1）", "",
           "| 組 | 成績 |", "|---|---|"] + [f"| {k} | {fr.fmt(fr.stats(np.array(v, float)))} |" for k, v in res.items()]
    sa, sb = fr.stats(np.array(res["A2 921（30 分鐘內同向開）"], float)), fr.stats(np.array(res["E6S4（A2 同一批）"], float))
    out += ["", "## 判（只作描述；預先登記 IDEAS #1005 A）", "",
            f"- A2 對同一批 E6S4：{(sa['avg'] - sb['avg']) if sa['n'] and sb['n'] else float('nan'):+.3f}R（張數 {sa['n']}）",
            "- 921 唔係為 rev15 揀位（自己揀時機），重疊張數少，只係粗略參考；唔改任何嘢。", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "AI_REPLAY_A.md"), "w", encoding="utf-8").write(md)


# ---------------------------------------------------------------- B：盲測
def load_mt5(a, b):
    sys.argv = [sys.argv[0], "--src", "mt5"]
    import rev15_history as rh   # noqa: E402
    rh.A, rh.B, rh.CACHE = a, b, f"/tmp/rev15_history_mt5_{a}_{b}.npz"
    return rh.load()


def m15(d, i, n=48):
    t = d["t"][: i + 1]; k = t // 900
    out = []
    for kk in sorted(set(k[-n * 15 - 15:]))[-n:]:
        idx = np.nonzero(k == kk)[0]
        out.append([float(d["o"][idx[0]]), float(d["h"][idx].max()), float(d["l"][idx].min()), float(d["c"][idx[-1]])])
    return out


HINT = ("Historical statistics for THIS rule (rev15) over many years of data: entries that waited for a DEEPER pullback "
        "(roughly 4-8 dollars beyond the signal price), with the stop about 4 dollars beyond the entry and a SMALL target "
        "equal to the stop distance (1R), had a high win rate (~85-89%) and positive expectancy. Shallow entries close to "
        "the signal price with larger targets lost money. Use this as background; you may still skip or adjust.")


def _pick(n_sigs, seed, exclude_seed=None):
    """exclude_seed：單一種子（#1006）或者逗號串（#1007：1005,1006 按次序重現之前抽過嘅題，全部剔走）。"""
    excl = set()
    if exclude_seed is not None:
        seeds = [int(x) for x in str(exclude_seed).split(",")]
        for k, sd in enumerate(seeds):
            pool0 = [j for j in range(n_sigs) if j not in excl]
            if k == 0:
                excl |= set(random.Random(sd).sample(range(n_sigs), min(N_B, n_sigs)))
            else:
                excl |= set(random.Random(sd).sample(pool0, min(N_B, len(pool0))))
    rng = random.Random(seed)
    pool = [k for k in range(n_sigs) if k not in excl]
    return sorted(rng.sample(pool, min(N_B, len(pool)))), rng


def make(qdir, seed=SEED, exclude_seed=None, hint=False):
    os.makedirs(qdir, exist_ok=True)
    a, b = "2026-08-01", "2026-10-30"
    d = load_mt5(a, b)
    sigs = signals(d, fr.ts_of(a), fr.ts_of(b) + 86400 - 2 * 86400)
    pick, rng = _pick(len(sigs), seed, exclude_seed)
    if exclude_seed is None:
        rng = random.Random(seed); pick = sorted(rng.sample(range(len(sigs)), min(N_B, len(sigs))))
    key = []
    for qn, si in enumerate(pick):
        i, side = sigs[si]
        off = round(rng.uniform(300, 700), 2)
        sh = lambda x: round(float(x) - off, 2)
        lo = max(0, i - 119)
        q = {"id": f"q{qn:03d}", "side": side, "price": sh(d["c"][i]),
             "utc_hour": dt.datetime.fromtimestamp(int(d["t"][i]) + 60, dt.timezone.utc).hour,
             "rule": "rev15：前 15 分鐘走咗 ≥3 美元，規則要做相反方向（方向已定）",
             "limits": {"entry": "限價，只准等回調（BUY 入場價 ≤ 現價；SELL ≥ 現價），離現價 ≤ 15", "stop_distance": "入場→止蝕 2–15", "valid_minutes": 30},
             "m1": [[sh(d["o"][j]), sh(d["h"][j]), sh(d["l"][j]), sh(d["c"][j])] for j in range(lo, i + 1)],
             "m15": [[round(x - off, 2) for x in r] for r in m15(d, i)]}
        if hint:
            q["background"] = HINT
        json.dump(q, open(os.path.join(qdir, f"q_{qn:03d}.json"), "w"), ensure_ascii=False)
        key.append({"id": q["id"], "ts": int(d["t"][i]) + 60, "side": side, "price": float(d["c"][i]), "off": off})
    json.dump(key, open(os.path.join(qdir, "key.json"), "w"))
    print(f"題目 {len(key)} 條 → {qdir}（出區 {len(sigs)} 次抽 {len(key)}）")


def score(qdir, outname="AI_REPLAY_B.md"):
    a, b = "2026-08-01", "2026-10-30"
    d = load_mt5(a, b)
    key = {k["id"]: k for k in json.load(open(os.path.join(qdir, "key.json")))}
    ans = {}
    for f in sorted(glob.glob(os.path.join(qdir, "answers_*.json"))):
        for x in json.load(open(f)):
            ans[x["id"]] = x
    ai, e6, ai_sum_all, e6_sum_all, rows = [], [], 0.0, 0.0, []
    took = bad = 0
    for qid, k in sorted(key.items()):
        r6 = e6s4(d, k["ts"], k["side"], k["price"])
        if r6 is not None:
            e6.append(r6)
        x = ans.get(qid) or {}
        ra = None
        if x.get("take"):
            e, sl, tp = (None if x.get(n) is None else float(x[n]) + k["off"] for n in ("entry", "sl", "tp"))
            if valid(k["side"], k["price"], e, sl, tp):
                took += 1
                ra = af.sim(d, k["ts"], k["side"], e, sl, tp)
                if ra is not None:
                    ai.append(ra)
            else:
                bad += 1
        rows.append((qid, k["side"], x.get("take"), ra, r6))
    sa, se = fr.stats(np.array(ai, float)), fr.stats(np.array(e6, float))
    ok = {"①AI平均R高過E6S4≥0.10R": sa["n"] > 0 and se["n"] > 0 and sa["avg"] - se["avg"] >= 0.10,
          "②AI ΣR唔少過E6S4": sa["sum"] >= se["sum"]}
    out = ["# IDEAS #1005 B：盲測 AI 揀入場（工作階段子代理，冇 API）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；MT5 M1 {a}→{b} rev15 出區抽 {len(key)} 題；答咗 {len(ans)} 題，揀做 {took}、唔合規 {bad}", "",
           "| 方法 | 成績 |", "|---|---|", f"| AI 揀入場 | {fr.fmt(sa)} |", f"| E6S4（同 {len(key)} 題） | {fr.fmt(se)} |", "",
           "## 判（預先登記 IDEAS #1005 B；只作參考，唔改 936 前向判斷）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
           "- 題目格式同 936 實盤唔完全一樣（冇產品資料／lessons），只係近似；樣本細。", "",
           "## 逐題", "", "| 題 | 方向 | AI 做唔做 | AI R | E6S4 R |", "|---|---|---|---|---|"]
    f = lambda v: "—" if v is None else f"{v:+.2f}"
    out += [f"| {q} | {s} | {'做' if t else '唔做'} | {f(ra)} | {f(r6)} |" for q, s, t, ra, r6 in rows]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, outname), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "a":
        part_a()
    elif cmd == "make":
        arg = lambda k, dflt=None: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else dflt
        ex = arg("--exclude-seed")
        make(sys.argv[2], seed=int(arg("--seed", SEED)), exclude_seed=(ex if ex else None), hint="--hint" in sys.argv)
    elif cmd == "score":
        score(sys.argv[2], sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "AI_REPLAY_B.md")
