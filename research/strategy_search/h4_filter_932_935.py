"""[IDEAS #227] 932 跟單／935 組合 A 加 H4 趨勢過濾（使用者 11-04 喺總指揮「932／935 加 H4 趨勢過濾，登記回測」）。
H4 斜率同 921 R368 一樣：最後一根已收市 H4（22:00 UTC 對齊）EMA50 減上一根（filter_921.H4Slope）。
過濾（主判）＝雙向：斜率 > 0 唔做空、< 0 唔做多；斜率 = 0／計唔到唔擋。另列「只擋逆勢做多」（921 R368 款）做描述。
932：頻道訊號（xau/sig/history 90 日回補＋xau/sig/signals 10-21 起），模擬同 932 現行：follower.entry_check 判 ok／wait／skip；
  ok＝下一分鐘開盤市價入；wait＝60 分鐘內價入入場區先成交（用入場區近邊價）；頻道 SL；CTC／0342 TP1 全平、DAN（7713）逐級鎖；24h；扣 0.5 美元。
  另列 932 真倉成交簿（xau/sig/follow book_seed＋state.book，10-23 起）。
935：組合 A（#183）六個成份滾動前向樣本外成交 2009→2026（Dukascopy H1，同 portfolio.py）。
判（預先登記，IDEAS #227）：①平均 R 唔差過唔過濾 ②PF ≥ 唔過濾 +0.10 ③累計 R 最大回撤細過唔過濾 ④按時間對半兩半過濾後平均 R 都 ≥ 唔過濾；四樣都要。
932 每個頻道分開判，過濾後 < 30 張＝未有定論；935 組合 A 合併判。
用法：python3 research/strategy_search/h4_filter_932_935.py → H4_FILTER_932_935.md"""
import datetime as dt
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "xau"))
os.environ.setdefault("XAU_SYMBOL", "XAUUSD"); os.environ.setdefault("XAU_BOOK", "signal")
try:
    import anthropic   # noqa: F401
except ImportError:
    _an = types.ModuleType("anthropic"); _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = Exception; sys.modules["anthropic"] = _an
import config as XC   # noqa: E402
import follower as FO   # noqa: E402
import filter_921 as F  # noqa: E402

COST = 0.5
WAIT = 60 * 60
CHANNELS = {"5231": "CTC", "7713": "DAN", "0342": "Gold Brother"}
LADDER = {"7713"}
MIN_N = 30


# ------------------------------------------------------------------ 共用
def mdd(rs):
    eq = np.cumsum(rs) if len(rs) else np.array([0.0])
    return float(np.min(eq - np.maximum.accumulate(np.r_[0.0, eq])[1:])) if len(rs) else 0.0


def stats(rows):
    rows = sorted(rows, key=lambda x: x["ts"])
    rs = [x["r"] for x in rows]
    s = F.summ(rs); s["mdd"] = mdd(rs)
    return s


def halves(rows, mid):
    return F.summ([x["r"] for x in rows if x["ts"] < mid]), F.summ([x["r"] for x in rows if x["ts"] >= mid])


def keep_both(x):
    return not ((x["s"] > 0 and x["h4"] < 0) or (x["s"] < 0 and x["h4"] > 0))


def keep_long(x):
    return not (x["s"] > 0 and x["h4"] < 0)


def judge(base, filt):
    """回傳 (dict 四項, 文字)。"""
    sb, sf = stats(base), stats(filt)
    mid = sorted(x["ts"] for x in base)[len(base) // 2] if base else 0
    b1, b2 = halves(base, mid); f1, f2 = halves(filt, mid)
    ok = {"①平均": sf["avg"] >= sb["avg"], "②PF+0.1": sf["pf"] >= sb["pf"] + 0.10, "③回撤": sf["mdd"] > sb["mdd"],
          "④兩半": f1["n"] > 0 and f2["n"] > 0 and f1["avg"] >= b1["avg"] and f2["avg"] >= b2["avg"]}
    return ok, (sb, sf, b1, b2, f1, f2)


def fmt(s):
    return f"{s['n']} 張 平均 {s['avg']:+.3f}R PF {s['pf']:.2f} ΣR {s['sum']:+.2f} 回撤 {s.get('mdd', 0):+.2f}R" if s["n"] else "0 張"


def table(out, label, rows):
    """唔過濾／雙向／只擋做多 × 全部／做多／做空。"""
    out += [f"### {label}", "", "| 版本 | 全部 | 做多 | 做空 |", "|---|---|---|---|"]
    for name, fn in (("唔過濾", lambda x: True), ("雙向過濾（主判）", keep_both), ("只擋逆勢做多（描述）", keep_long)):
        sel = [x for x in rows if fn(x)]
        out.append(f"| {name} | {fmt(stats(sel))} | {fmt(stats([x for x in sel if x['s'] > 0]))} | {fmt(stats([x for x in sel if x['s'] < 0]))} |")
    ok, (sb, sf, b1, b2, f1, f2) = judge(rows, [x for x in rows if keep_both(x)])
    out += ["", f"- 前後半（按入場時間對半）：唔過濾 {b1['avg']:+.3f}／{b2['avg']:+.3f}；雙向過濾 {f1['avg']:+.3f}／{f2['avg']:+.3f}",
            f"- 擋走嘅逆勢單：{fmt(stats([x for x in rows if not keep_both(x)]))}", ""]
    return ok, sf


def verdict(ok, n, need_n=True):
    if need_n and n < MIN_N:
        return f"⏳ 未有定論（過濾後 {n} 張 < {MIN_N}）；四項：" + "、".join(f"{k}{'✅' if v else '❌'}" for k, v in ok.items())
    return ("✅ 達標" if all(ok.values()) else "❌ 唔達") + "：" + "、".join(f"{k}{'✅' if v else '❌'}" for k, v in ok.items())


# ------------------------------------------------------------------ 932
def load_signals(g):
    out = {}
    for pre in ("xau/sig/history/", "xau/sig/signals/"):
        for nm in g.list(pre):
            base = nm.rsplit("/", 1)[-1]
            ch = next((c for c in CHANNELS if base.split("_")[0].endswith(c)), None)
            if ch is None:
                continue
            d = g.read_json(nm) or {}
            s = d.get("signal") or {}
            if s.get("kind") != "new_signal" or s.get("side") not in ("BUY", "SELL") or s.get("sl") is None or not s.get("tp"):
                continue
            ts = d.get("received_ts") if pre.endswith("signals/") and d.get("received_ts") else d.get("msg_ts")
            if not ts:
                continue
            out[d["sid"]] = {**s, "ch": base.split("_")[0], "c4": ch, "sid": d["sid"], "ts": float(ts),
                             "tp": [float(x) for x in s["tp"]], "sl": float(s["sl"])}
    return sorted(out.values(), key=lambda r: r["ts"])


def follow_sim(m1, r):
    t, o, h, l, c = m1["t"], m1["o"], m1["h"], m1["l"], m1["c"]
    side = 1 if r["side"] == "BUY" else -1
    a = int(np.searchsorted(t, r["ts"], side="right"))
    if a <= 0 or a >= len(t) or t[a] - r["ts"] > 600:
        return None
    price = float(c[a - 1])
    act, why = FO.entry_check(r, price, now=r["ts"])
    if act == "skip":
        return {"skip": why}
    sl, tps = r["sl"], r["tp"]
    if act == "ok":
        fi, fill = a, float(o[a])
    else:
        lo, hi = float(r["entry_low"]), float(r["entry_high"])
        lim = hi if side > 0 else lo
        fi = None
        for j in range(a, min(int(np.searchsorted(t, r["ts"] + WAIT, side="right")), len(t))):
            if (l[j] <= lim) if side > 0 else (h[j] >= lim):
                fi = j; break
        if fi is None:
            return {"skip": "等唔到入場區"}
        fill = lim
    if (fill - sl) * side <= 0 or (tps[0] - fill) * side <= 0:
        return {"skip": "成交價錯邊"}
    risk = abs(fill - sl); cur = sl; k = -1; ladder = r["c4"] in LADDER
    end = int(np.searchsorted(t, t[fi] + 86400)); ex = None
    for j in range(fi, min(end, len(t))):
        if (l[j] <= cur) if side > 0 else (h[j] >= cur):
            ex = cur; break
        if j == fi:
            continue
        fav = h[j] if side > 0 else l[j]
        if not ladder:
            if (fav - tps[0]) * side >= 0:
                ex = tps[0]; break
            continue
        while k + 1 < len(tps) and (fav - tps[k + 1]) * side >= 0:
            k += 1
        if k == len(tps) - 1:
            ex = tps[-1]; break
        if k >= 0:
            want = fill if k == 0 else tps[k - 1]
            if (want - cur) * side > 0:
                cur = want
    if ex is None:
        if end >= len(t):
            return None
        ex = float(c[end - 1])
    return {"r": (side * (ex - fill) - COST) / risk, "ts": int(t[fi]), "s": side}


def live_book(g):
    seed = [x for x in (g.read_json("xau/sig/follow/book_seed.json") or []) if isinstance(x, dict) and x.get("closed_ts")]
    st = g.read_json("xau/sig/follow/state.json") or {}
    last = max([x["closed_ts"] for x in seed] or [0])
    rows = seed + [x for x in (st.get("book") or []) if (x.get("closed_ts") or 0) > last]
    return [{"ts": float(x["opened_ts"]), "s": int(x["side"]), "r": float(x["r"]), "c4": str(x.get("ch") or "")[-4:]}
            for x in rows if x.get("r") is not None and x.get("opened_ts")]


# ------------------------------------------------------------------ main
def main():
    g = F.gb.Gcs()
    out = ["# 932／935 加 H4 趨勢過濾（IDEAS #227）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；H4 斜率＝最後一根已收市 H4（22:00 UTC 對齊）EMA50 減上一根（同 921 R368）",
           "- 雙向過濾（主判）：斜率 > 0 唔做空、< 0 唔做多；「只擋逆勢做多」＝921 R368 款（描述）；回撤＝累計 R 由高位跌幾多（按入場時間）", ""]
    # ---- 932
    sigs = load_signals(g)
    d0 = dt.datetime.fromtimestamp(sigs[0]["ts"] - 86400 * 15, dt.timezone.utc).date().isoformat()
    m1 = F.EF6.broker_bars(int(sigs[0]["ts"]) - 86400 * 15)
    m1, _ = F.merge_duka(g, m1, d0)
    hs = F.H4Slope(m1["t"], m1["c"])
    rows, skips = [], {}
    for r in sigs:
        res = follow_sim(m1, r)
        if res is None:
            continue
        if "skip" in res:
            skips.setdefault(r["c4"], 0); skips[r["c4"]] += 1
            continue
        rows.append({**res, "c4": r["c4"], "h4": hs.at(res["ts"])})
    out += ["## 932 跟單：頻道訊號模擬（同 932 現行跟法）", "",
            f"- 訊號 {len(sigs)} 個（{dt.datetime.fromtimestamp(sigs[0]['ts'], dt.timezone.utc):%Y-%m-%d} → {dt.datetime.fromtimestamp(sigs[-1]['ts'], dt.timezone.utc):%Y-%m-%d}）；"
            f"有成交 {len(rows)} 張；entry_check 略過：" + "、".join(f"{CHANNELS[k]} {v}" for k, v in sorted(skips.items())), ""]
    verdicts = {}
    for c4, name in CHANNELS.items():
        sel = [x for x in rows if x["c4"] == c4]
        if not sel:
            out += [f"### {name}（…{c4}）", "", "- 冇成交", ""]
            continue
        ok, sf = table(out, f"{name}（…{c4}）", sel)
        verdicts[name] = verdict(ok, sf["n"])
        out += [f"- 判：{verdicts[name]}", ""]
    lb = live_book(g)
    for x in lb:
        x["h4"] = hs.at(x["ts"])
    if lb:
        out += ["## 932 真倉成交簿（10-23 起，描述）", ""]
        okl, sfl = table(out, f"932 真倉全部（{len(lb)} 張）", lb)
        out += [f"- 參考：{verdict(okl, sfl['n'])}", ""]
    # ---- 935
    import portfolio as P
    import robust_long as R
    duka = R.load_duka()
    ds, _ = P.streams(duka)
    t1, c1 = duka[0], duka[4]
    h1s = F.H4Slope(np.asarray(t1, dtype=np.int64), np.asarray(c1, dtype=float))
    core = [k for k in ds if not k.startswith("7")]
    combo = []
    for k in core:
        for x in ds[k]:
            if R.yr(x[0]) >= 2009:
                combo.append({"ts": int(x[0]), "s": int(x[1]), "r": float(x[3]), "comp": k, "h4": h1s.at(int(x[0]))})
    out += ["## 935 組合 A（#183 六個成份，滾動前向樣本外 2009→2026，Dukascopy H1）", ""]
    ok5, sf5 = table(out, f"組合 A 合併（{len(combo)} 張）", combo)
    verdicts["935 組合 A"] = verdict(ok5, sf5["n"], need_n=False)
    out += [f"- 判：{verdicts['935 組合 A']}", "", "### 各成份（描述）", "", "| 成份 | 唔過濾 | 雙向過濾 | 擋走 |", "|---|---|---|---|"]
    for k in core:
        sel = [x for x in combo if x["comp"] == k]
        out.append(f"| {k} | {fmt(stats(sel))} | {fmt(stats([x for x in sel if keep_both(x)]))} | {fmt(stats([x for x in sel if not keep_both(x)]))} |")
    yy = {}
    for x in combo:
        yy.setdefault(dt.datetime.fromtimestamp(x["ts"], dt.timezone.utc).year, []).append(x)
    pos_b = sum(1 for v in yy.values() if sum(x["r"] for x in v) > 0)
    pos_f = sum(1 for v in yy.values() if sum(x["r"] for x in v if keep_both(x)) > 0)
    out += ["", f"- 正數年：唔過濾 {pos_b}/{len(yy)}；雙向過濾 {pos_f}/{len(yy)}", ""]
    out += ["## 總結（預先登記判）", ""] + [f"- {k}：{v}" for k, v in verdicts.items()] + [
        "", "- 只係研究；達標先提案改 env／程式（932 喺 follower、935 喺 combo_live），部署要總指揮 dry-run＋使用者批。",
        "- 932 頻道訊號只得約 3 個月（回補可能有事後編輯）；entry_check 用預設 config（避開時段等），同真倉 env 可能有少少出入。", ""]
    open(os.path.join(HERE, "H4_FILTER_932_935.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
