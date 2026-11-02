"""[IDEAS #210] 921（Opus 自主單）兩個過濾嘅回測描述（總指揮 11-02 交，使用者揀「A＋C」嘅 C）：
  F1 H4 斜率：H4 EMA50 斜率向下（最後一根已收 H4 對上一根）唔做多；向上唔做空（對稱）
  F2a 亞洲時段（開倉 22:00–07:00 UTC）唔做多
  F2b 亞洲時段做多手數減半（R × 0.5，張數唔變）
  F1＋F2a 一齊（只作描述，唔計判斷）
三個樣本：
  A. 921 真倉成交簿（GCS xau/book_seed.json＋xau/state.json book；R＝決策價→初始止損，同 TEST_RESULTS）
  B. 921 決策日誌所有 OPEN_LONG／OPEN_SHORT（GCS xau/decisions/<日>.jsonl，連冇落到單嗰啲）用經紀 M1 重播：
     下一分鐘開盤入、AI 原始止損／目標固定唔改、同一分鐘都掂當止損、24 小時到鐘市價走、每張扣 0.5 美元；每個決定獨立計（唔理同時持倉）
  C. 通用對照（長歷史）：黃金 H1 2009→2026（Dukascopy＋券商 MT5＋經紀心跳）隨機入場（固定種子，每根 H1 有 10% 機會、方向一半一半），
     SL 1×H1 ATR(14)、TP 1.5R、24 小時、扣 0.5 美元、同時一張——睇兩個過濾本身有冇通用作用、逐年穩唔穩
判斷（預先登記，每個過濾 F1／F2a／F2b 各自）：見 IDEAS #210。只係提案；改 921 程式要使用者經總指揮批。
用法：python3 research/strategy_search/filter_921.py → FILTER_921.md"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
import b_forward as BF  # noqa: E402
import e6s4_forward as EF6  # noqa: E402
import g7_long as G7  # noqa: E402
import gb_rulesim as gb  # noqa: E402
import robust_long as R  # noqa: E402

COST = 0.5
ASIA = set(range(22, 24)) | set(range(0, 7))
Y10 = range(2017, 2027)


class H4Slope:
    def __init__(self, t, c):
        key = (t - 7200) // 14400 * 14400 + 7200          # 22:00 UTC 對齊（同 g7_long）
        ks, first = np.unique(key, return_index=True)
        last = np.r_[first[1:], len(t)] - 1
        self.k = ks; self.e = G7.ema(c[last], 50)

    def at(self, ts):
        j = np.searchsorted(self.k, ts - 14400, side="right") - 1   # 已收市（開始 + 4h ≤ ts）嘅最後一根
        if j < 51:
            return 0.0
        return float(self.e[j] - self.e[j - 1])


def asia(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).hour in ASIA


def keep(f, side, ts, sl):
    """回傳權重：1 照做、0 唔做、0.5 減半。"""
    if f in ("F1", "F1＋F2a") and ((side > 0 and sl < 0) or (side < 0 and sl > 0)):
        return 0.0
    if f in ("F2a", "F1＋F2a") and side > 0 and asia(ts):
        return 0.0
    if f == "F2b" and side > 0 and asia(ts):
        return 0.5
    return 1.0


def summ(rs):
    rs = np.asarray(rs, float)
    if not len(rs):
        return dict(n=0, avg=0.0, pf=0.0, sum=0.0)
    g, b = rs[rs > 0].sum(), -rs[rs < 0].sum()
    return dict(n=len(rs), avg=float(rs.mean()), pf=float(g / b) if b > 0 else 99.0, sum=float(rs.sum()))


def apply(trs, f, slope):
    """trs: [(ts, side, R)] → (保留張數, 加權 R list)。F2b 張數唔變、R 減半。"""
    out = []
    for ts, s, r in trs:
        w = keep(f, s, ts, slope.at(ts))
        if w > 0:
            out.append(r * w)
    return out


def fmt(s):
    return f"{s['n']} 張 平均 {s['avg']:+.3f}R PF {s['pf']:.2f} ΣR {s['sum']:+.2f}" if s["n"] else "0 張"


def load_live(g):
    seed = g.read_json("xau/book_seed.json") or []
    st = g.read_json("xau/state.json") or {}
    seed = [x for x in seed if isinstance(x, dict) and x.get("closed_ts")]
    last = max((x["closed_ts"] for x in seed), default=0)
    rows = seed + [x for x in (st.get("book") or []) if (x.get("closed_ts") or 0) > last]
    return [(int(x["opened_ts"]), int(x["side"]), float(x["r"])) for x in rows if x.get("opened_ts") and x.get("r") is not None]


def load_decisions(g):
    out = []
    for nm in sorted(g.list("xau/decisions/")):
        txt = g.read_text(nm) or ""
        try:
            arr = json.loads(txt)
            arr = arr if isinstance(arr, list) else [arr]
        except ValueError:
            arr = []
            for ln in txt.splitlines():
                try:
                    v = json.loads(ln); arr += v if isinstance(v, list) else [v]
                except ValueError:
                    continue
        for o in arr:
            if o.get("kind") == "decide" and o.get("final") in ("OPEN_LONG", "OPEN_SHORT") and o.get("stop") and o.get("target"):
                out.append((float(o["ts"]), 1 if o["final"] == "OPEN_LONG" else -1, float(o["stop"]), float(o["target"]), bool(o.get("applied"))))
    return sorted(out)


def replay(m1, decs):
    t, o, h, l, c = m1["t"], m1["o"], m1["h"], m1["l"], m1["c"]
    out = []
    for ts, s, sl, tp, applied in decs:
        a = int(np.searchsorted(t, ts, side="right"))
        if a >= len(t) or t[a] - ts > 600:
            continue
        px = o[a]; d = (px - sl) * s
        if d <= 0 or (tp - px) * s <= 0:
            continue
        ex = None
        for j in range(a, len(t)):
            if t[j] - t[a] >= 86400:
                ex = o[j]; break
            if (l[j] <= sl) if s > 0 else (h[j] >= sl):
                ex = sl; break
            if (h[j] >= tp) if s > 0 else (l[j] <= tp):
                ex = tp; break
        if ex is None:
            continue
        out.append((int(t[a]), s, float((s * (ex - px) - COST) / d)))
    return out


class _D:
    pass


def random_entries(t, o, h, l, c, seed=921):
    tr = np.r_[h[0] - l[0], np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])]
    cs = np.r_[0, np.cumsum(tr)]; atr = np.full(len(t), np.nan); atr[13:] = (cs[14:] - cs[:-14]) / 14
    rng = np.random.default_rng(seed)
    pick = rng.random(len(t)) < 0.10; side = np.where(rng.random(len(t)) < 0.5, 1, -1)
    a0 = int(dt.datetime(2009, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    ent = [(i + 1, int(side[i]), float(atr[i]), 1.5 * float(atr[i]), 24) for i in np.flatnonzero(pick)
           if i + 1 < len(t) and t[i + 1] >= a0 and atr[i] > 0]
    D = _D(); D.t, D.o, D.h, D.l, D.c = t, o, h, l, c
    R.COST = COST
    return [(x[0], x[1], x[3]) for x in R.simulate(D, ent)]


FILTERS = ["F1", "F2a", "F2b", "F1＋F2a"]


def main():
    g = gb.Gcs()
    (t, o, h, l, c), n_new = BF.load_h1()
    slope = H4Slope(t, c)
    A = load_live(g)
    decs = load_decisions(g)
    m1 = EF6.broker_bars(int(decs[0][0]) - 86400) if decs else None
    B = replay(m1, decs) if decs else []
    C = random_entries(t, o, h, l, c)
    now = dt.datetime.now(dt.timezone.utc)
    out = ["# 921 過濾回測描述：H4 斜率／亞洲時段（IDEAS #210）", "",
           f"- 更新 {now:%Y-%m-%d %H:%M} UTC；H4 EMA50 斜率用已收市 H4（22:00 UTC 對齊）；亞洲＝開倉 22:00–07:00 UTC",
           f"- A：921 真倉 {len(A)} 張；B：決策日誌 OPEN {len(decs)} 個（落到單 {sum(d[4] for d in decs)} 個），經紀 M1 重播到 {len(B)} 個；"
           f"C：隨機入場 2009→ {len(C)} 張（SL 1×H1 ATR、TP 1.5R、24h、扣 0.5 美元）", ""]
    # 組成
    for lab, S in (("A 真倉", A), ("B 決策重播", B)):
        lo = [x for x in S if x[1] > 0]; sh = [x for x in S if x[1] < 0]
        out.append(f"- {lab}：做多 {fmt(summ([x[2] for x in lo]))}；做空 {fmt(summ([x[2] for x in sh]))}；"
                   f"亞洲做多 {fmt(summ([x[2] for x in lo if asia(x[0])]))}；斜率逆向做多 {fmt(summ([x[2] for x in lo if slope.at(x[0]) < 0]))}；"
                   f"斜率逆向做空 {fmt(summ([x[2] for x in sh if slope.at(x[0]) > 0]))}")
    out += ["", "| 過濾 | 樣本 | 唔過濾 | 過濾後 | 平均 R 變化 | 保留張數 | 近 10 年平均 R 改善年數（只 C） |", "|---|---|---|---|---|---|---|"]
    res = {}
    for f in FILTERS:
        res[f] = {}
        for lab, S in (("A", A), ("B", B), ("C", C)):
            base = summ([x[2] for x in S]); fl = apply(S, f, slope); fs = summ(fl)
            kept = sum(1 for x in S if keep(f, x[1], x[0], slope.at(x[0])) == 1.0) / max(len(S), 1)
            avg_f = fs["sum"] / max(fs["n"], 1)
            yrs = ""
            if lab == "C":
                imp = 0
                for y in Y10:
                    Sy = [x for x in S if R.yr(x[0]) == y]
                    if summ(apply(Sy, f, slope))["avg"] > summ([x[2] for x in Sy])["avg"]:
                        imp += 1
                yrs = f"{imp}/10"; res[f]["C_yrs"] = imp
            res[f][lab] = dict(base=base, f=fs, d=avg_f - base["avg"], kept=kept)
            out.append(f"| {f} | {lab} | {fmt(base)} | {fmt(fs)} | {avg_f - base['avg']:+.3f} | {kept:.0%} | {yrs} |")
            print(f, lab, fmt(base), fmt(fs), flush=True)
    out += ["", "## 判（預先登記 IDEAS #210；F1＋F2a 只作描述）", ""]
    for f in ("F1", "F2a", "F2b"):
        r = res[f]
        ok = {"①A 平均R +0.10": r["A"]["d"] >= 0.10, "①B 平均R +0.10": r["B"]["d"] >= 0.10,
              "②A PF≥1.1": r["A"]["f"]["pf"] >= 1.1,
              "④C 全期改善": r["C"]["d"] > 0, "④C ≥7/10 年": r["C_yrs"] >= 7}
        if f != "F2b":
            ok["③保留≥50%"] = r["A"]["kept"] >= 0.5 and r["B"]["kept"] >= 0.5
        else:
            ok["③A ΣR 改善"] = r["A"]["f"]["sum"] > r["A"]["base"]["sum"]
        out.append(f"- {f}：{'✅ 達標 → 提案先前向影子標記 921 新單 30 張再決定' if all(ok.values()) else '❌ 唔達：' + '、'.join(k for k, v in ok.items() if not v)}")
    out += ["", "- A 係觸發呢個想法嘅樣本（L36／L37 亞洲盤逆斜率做多），屬樣本內；B 同 A 有重疊（B 包括冇落到單嘅決定）；只有 C 係獨立長歷史，但係隨機入場唔係 921 嘅揀位。",
            "- 任何結果都只係提案；改 921 程式要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "FILTER_921.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
