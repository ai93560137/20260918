"""[IDEAS #218] DAN（頻道 …7713）「走咗」訊號改掛限價（使用者 11-02「回測 DAN 限價改法」）。
現行：收到時 signals.is_late（現價過咗 TP1，或者已向有利方向離入場 ≥ 1×止損距離）→ 唔跟（0）。
改法：走咗嘅訊號喺有效期（收到後 30 分鐘）掛限價：SELL＝價回升到入場區下沿（entry_low）成交、BUY＝回落到上沿（entry_high）成交；
冇入場區就用 signals.ref_entry 嘅價；30 分鐘內冇返到就取消。成交之後同 932 一樣逐級鎖：到 TP1 止損移保本、到 TP(k+1) 鎖 TP(k)，
最後一級 TP 全平；24 小時到鐘市價走；同一分鐘止蝕同 TP 都掂當止蝕；成交嗰分鐘只計止蝕、唔計有利方向（11-02 第一次跑發現會偷睇未來，修正後重跑，標準唔變）。每張扣 0.5 美元；R＝（出場−成交）÷|成交−SL|。
數據：訊號＝GCS xau/sig/history/3860767713_*.json（90 日回補）＋ xau/sig/signals/3860767713_*.json（10-21 起實時），只取 kind=new_signal 有 SL／TP；
價格＝Dukascopy M1（xau/sig/duka/）＋經紀 M1（xau/sig/bars/），收到時間＝msg_ts（回補）／received_ts（實時）。
判（預先登記）：走咗訊號限價成交 ≥ 15 張；成交後平均 R ≥ +0.2、PF ≥ 1.3；前後半（按時間對半）平均 R 都 > 0。
另列：唔走咗訊號（現行會跟嗰啲，同一引擎掛入場區限價）做對照。達標 → 只係提案，改 932 程式要使用者經總指揮批，建議先影子。
用法：python3 research/strategy_search/dan_late_limit.py → DAN_LATE_LIMIT.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "xau"))
os.environ.setdefault("XAU_SYMBOL", "XAUUSD"); os.environ.setdefault("XAU_BOOK", "signal")
import types   # noqa: E402
try:
    import anthropic   # noqa: F401
except ImportError:
    _an = types.ModuleType("anthropic"); _an.Anthropic = lambda *a, **k: None; _an.BadRequestError = Exception; sys.modules["anthropic"] = _an
import signals as SG   # noqa: E402
import filter_921 as F  # noqa: E402

CH = "3860767713"
COST = 0.5
VALID = 30 * 60
FWD_TS = int(dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc).timestamp())   # [影子] 使用者 11-02「DAN 先做影子」：呢個時間之後收到嘅訊號＝前向
FWD_TARGET = 15


def load_signals(g):
    out = {}
    for pre in ("xau/sig/history/", "xau/sig/signals/"):
        for nm in g.list(pre):
            if CH not in nm:
                continue
            d = g.read_json(nm) or {}
            s = d.get("signal") or {}
            if s.get("kind") != "new_signal" or s.get("side") not in ("BUY", "SELL") or s.get("sl") is None or not s.get("tp"):
                continue
            ts = d.get("received_ts") if pre.endswith("signals/") and d.get("received_ts") else d.get("msg_ts")
            if pre.endswith("history/"):
                ts = d.get("msg_ts")
            out[d["sid"]] = {**s, "sid": d["sid"], "ts": float(ts), "tp": [float(x) for x in s["tp"]], "sl": float(s["sl"])}
    return sorted(out.values(), key=lambda r: r["ts"])


def simulate(m1, r, late):
    t, o, h, l, c = m1["t"], m1["o"], m1["h"], m1["l"], m1["c"]
    side = 1 if r["side"] == "BUY" else -1
    a = int(np.searchsorted(t, r["ts"], side="right"))
    if a >= len(t) or t[a] - r["ts"] > 600:
        return None
    if r.get("entry_low") is not None and r.get("entry_high") is not None:
        lim = float(r["entry_high"]) if side > 0 else float(r["entry_low"])
    else:
        lim, _ = SG.ref_entry({**r, "price": float(c[a - 1]) if a > 0 else float(o[a])})
        if lim is None:
            return None
    sl, tps = r["sl"], r["tp"]
    if (lim - sl) * side <= 0:
        return None
    end_fill = int(np.searchsorted(t, r["ts"] + VALID, side="right"))
    fi = None
    for j in range(a, min(end_fill, len(t))):
        if (l[j] <= lim) if side > 0 else (h[j] >= lim):
            fi = j; break
    if fi is None:
        return {"filled": False}
    fill = lim; risk = abs(fill - sl); cur = sl; k = -1
    end = int(np.searchsorted(t, t[fi] + 86400))
    ex = None
    for j in range(fi, min(end, len(t))):
        if (l[j] <= cur) if side > 0 else (h[j] >= cur):
            ex = cur; break
        if j == fi:
            continue                     # 成交嗰分鐘唔計有利方向（嗰分鐘嘅高／低可能喺成交之前出現，計咗係偷睇未來）
        fav = h[j] if side > 0 else l[j]
        while k + 1 < len(tps) and (fav - tps[k + 1]) * side >= 0:
            k += 1
        if k == len(tps) - 1:
            ex = tps[-1]; break
        if k >= 0:
            want = fill if k == 0 else tps[k - 1]
            if (want - cur) * side > 0:
                cur = want
    if ex is None:
        ex = float(c[min(end, len(c)) - 1])
    return {"filled": True, "r": (side * (ex - fill) - COST) / risk, "ts": int(t[fi])}


def main():
    g = F.gb.Gcs()
    sigs = load_signals(g)
    d0 = dt.datetime.fromtimestamp(sigs[0]["ts"] - 86400, dt.timezone.utc).date().isoformat()
    m1 = F.EF6.broker_bars(int(sigs[0]["ts"]) - 86400)
    m1, _ = F.merge_duka(g, m1, d0)
    rows = []
    for r in sigs:
        a = int(np.searchsorted(m1["t"], r["ts"], side="right")) - 1
        if a < 0:
            continue
        price = float(m1["c"][a])
        late = SG.is_late({**r, "price": price}, price)
        res = simulate(m1, r, late)
        if res is None:
            continue
        rows.append({**r, "late": late, **res})
    out = ["# DAN 走咗訊號改掛限價（IDEAS #218）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；DAN 新開倉訊號 {len(rows)} 個（{dt.datetime.fromtimestamp(rows[0]['ts'], dt.timezone.utc):%Y-%m-%d} → {dt.datetime.fromtimestamp(rows[-1]['ts'], dt.timezone.utc):%Y-%m-%d}）；限價有效 30 分鐘、逐級鎖、24h、扣 0.5 美元", "",
           "| 組 | 訊號 | 限價成交 | 成交率 | 成交後 | 前半 | 後半 |", "|---|---|---|---|---|---|---|"]
    res = {}
    for lab, sel in (("走咗（改法新增）", [x for x in rows if x["late"]]), ("唔走咗（現行會跟，對照）", [x for x in rows if not x["late"]])):
        fl = [x for x in sel if x.get("filled")]
        mid = fl[len(fl) // 2]["ts"] if fl else 0
        s = F.summ([x["r"] for x in fl]); h1 = F.summ([x["r"] for x in fl if x["ts"] < mid]); h2 = F.summ([x["r"] for x in fl if x["ts"] >= mid])
        res[lab] = (s, h1, h2, len(fl))
        out.append(f"| {lab} | {len(sel)} | {len(fl)} | {len(fl) / max(len(sel), 1):.0%} | {F.fmt(s)} | {F.fmt(h1)} | {F.fmt(h2)} |")
    s, h1, h2, n = res["走咗（改法新增）"]
    ok = dict(n=n >= 15, avg=s["avg"] >= 0.2, pf=s["pf"] >= 1.3, halves=h1["avg"] > 0 and h2["avg"] > 0)
    out += ["", "## 判（預先登記）", "", f"- {'✅ 達標 → 提案（先影子）' if all(ok.values()) else '❌ 唔達：' + '、'.join(k for k, v in ok.items() if not v)}",
            "- 只係提案；改 932 程式要使用者經總指揮批。回補訊號可能有事後編輯；限價用入場區近邊成交屬保守（實際可能更好價）。", "",
            "## 走咗訊號逐個", "", "| 收到（UTC） | 方向 | 入場區 | SL | 成交 | R |", "|---|---|---|---|---|---|"]
    for x in [x for x in rows if x["late"]]:
        out.append(f"| {dt.datetime.fromtimestamp(x['ts'], dt.timezone.utc):%m-%d %H:%M} | {x['side']} | {x.get('entry_low')}–{x.get('entry_high')} | {x['sl']} | "
                   f"{'✓' if x.get('filled') else '✗'} | {x['r']:+.2f} |" if x.get("filled") else
                   f"| {dt.datetime.fromtimestamp(x['ts'], dt.timezone.utc):%m-%d %H:%M} | {x['side']} | {x.get('entry_low')}–{x.get('entry_high')} | {x['sl']} | ✗ | — |")
    fw = [x for x in rows if x["late"] and x["ts"] >= FWD_TS]; ff = [x for x in fw if x.get("filled")]
    sf = F.summ([x["r"] for x in ff])
    ok_f = len(ff) >= FWD_TARGET and sf["avg"] >= 0.2 and sf["pf"] >= 1.3
    out[3:3] = ["## 影子前向（11-03 00:00 UTC 起；使用者 11-02「DAN 先做影子」）", "",
                f"- 走咗訊號 {len(fw)} 個、限價成交 {len(ff)}／{FWD_TARGET}：{F.fmt(sf)}",
                f"- 判（同回測標準）：成交 ≥ {FWD_TARGET} 張、平均 ≥ +0.2R、PF ≥ 1.3 → "
                + ("✅ 夠數達標 → 報總指揮提案改 932（寫程式＋dry-run＋使用者批）" if ok_f else ("❌ 夠數但唔達 → 唔改" if len(ff) >= FWD_TARGET else "未夠數，繼續影子")),
                "- 「走咗」用收到嗰分鐘 M1 收市價判（實時用即時價，可能有少少出入）", ""]
    open(os.path.join(HERE, "DAN_LATE_LIMIT.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out[:20]))


if __name__ == "__main__":
    main()
