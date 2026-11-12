"""[IDEAS #1427–#1436] 黃金日線框架原封不動搬去恒指／納指／標普（使用者 11-12，經總指揮）。規格、成本、門檻、配額以 IDEAS 預先登記為準（跑之前 commit）。
數據：龍飛陣存喺 GCS longfei/daily/（Yahoo 日線）。只讀研究。
用法：python3 research/strategy_search/index_1427.py → research/strategy_search/INDEX_1427.md"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import data_cache as DC      # noqa: E402
import frame_1272 as FR      # noqa: E402
import multi_1422 as MU      # noqa: E402
import oldgold_1260 as OG    # noqa: E402

M3 = FR.M3
OUT = os.path.join(HERE, "INDEX_1427.md")
NRAND = 200
CFG = [("#1268 事件版 重拾 SMA20", lambda q, a: FR.e_base(q, a), lambda q, a, md: FR.x_base(q, a, md)),
       ("#1273 RSI14 升穿 40", lambda q, a: FR.e2(q, a, 40), lambda q, a, md: FR.x_base(q, a, md)),
       ("#1285 單日升 ≥ 1.5×ATR", lambda q, a: FR.b4(q, a, 1.5), lambda q, a, md: FR.x_base(q, a, md, 10)),
       ("#1290 升穿 SMA50", lambda q, a: FR.b9(q, a, 50), lambda q, a, md: FR.x_base(q, a, md, 10)),
       ("#1300 只用 SMA200 反轉出場", lambda q, a: FR.e_base(q, a), lambda q, a, md: FR.x9(q, a, md, 0))]
MKTS = [("恒指 ^HSI 現貨（代理）", "HSI", 0.0005, True), ("納指 NQ=F", "NQ_F", 0.0002, True), ("標普 ES=F", "ES_F", 0.0002, True),
        ("（補充）納指 100 現貨 ^NDX", "NDX", 0.0002, False), ("（補充）標普 500 現貨 ^GSPC", "GSPC", 0.0002, False)]


def load(name):
    j = json.loads(DC._bucket().blob(f"longfei/daily/{name}.json").download_as_text()); r = [x for x in j["rows"] if x[2] > x[3] and min(x[1:5]) > 0]
    return {"t": np.array([OG.ts(x[0]) for x in r], np.int64), "o": np.array([x[1] for x in r], float), "h": np.array([max(x[1:5]) for x in r], float),
            "l": np.array([min(x[1:5]) for x in r], float), "c": np.array([x[4] for x in r], float)}


def sim(d, cfg, cost, nd=200, long_only=False, rnd=None):
    """同 frame_1272.simulate 一樣嘅流程；rnd＝(rng, p) 時用隨機入場（密度 p）代替規則觸發。"""
    _, tf, xf = cfg; restore = OG.patch("gold"); OG._rate[0] = cost
    try:
        cx = M3.d1ctx(d); b = cx.b; a = FR.B.atr(b); n = len(b["c"]); out = []; busy = -1; side = {}; dens = {}
        for sg, q in ((1, b), (-1, FR.neg(b))):
            md = FR.sma(q["c"], nd); ok = ~np.isnan(md) & (q["c"] > md)
            trig = tf(q, a) if rnd is None else (rnd[0].random(n) < rnd[1])
            dens[sg] = (int((trig & ok).sum()), int(ok.sum())); side[sg] = (q, md, trig, xf(q, a, md))
        for i in range(max(nd, 60) + 1, n - 1):
            if i <= busy or np.isnan(a[i]):
                continue
            sg = 0
            for s in ((1,) if long_only else (1, -1)):
                q, md, trig, mk = side[s]
                if not np.isnan(md[i]) and q["c"][i] > md[i] and trig[i]:
                    sg = s; break
            if not sg:
                continue
            ex = side[sg][3](i)
            x = FR.M.trade_m1(cx, i, sg, 3.0 * a[i], None, 250, (lambda k, s, ex=ex: ex(k)))
            if x:
                out.append((int(x[0]), sg, float(x[2]))); busy = x[3]
        return out, dens
    finally:
        restore()


def parity():
    """我嘅流程對 frame_1272.simulate（黃金 stooq）：四條要逐張一致。"""
    d = MU.stooq("xauusd", "1973-01-01"); restore = OG.patch("gold"); OG._rate[0] = 0.0005
    try:
        ref = {i: [(int(a), int(b), round(float(r), 9)) for a, b, r in FR.simulate(M3.d1ctx(d), next(x for x in FR.RULES if x[0] == i))] for i in ("#1273", "#1285", "#1290", "#1300")}
    finally:
        restore()
    bad = 0
    for k, i in ((1, "#1273"), (2, "#1285"), (3, "#1290"), (4, "#1300")):
        mine = [(t, s, round(r, 9)) for t, s, r in sim(d, CFG[k], 0.0005)[0]]; bad += mine != ref[i]
    return bad


def main():
    bad = parity()
    L = ["# #1427–#1436：黃金日線框架搬去恒指／納指／標普", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；數據 GCS `longfei/daily/`（龍飛陣 11-12 存，Yahoo 日線）；只讀研究，唔落單",
         f"- 程式核對：同 frame_1272.simulate 喺黃金逐張比較，{'四條完全一致' if not bad else f'⚠ 有 {bad} 條唔一致'}",
         "- 規則原封不動（SMA200 定方向、SL 3×ATR14、250 日到期）；日線執行模擬；成本 NQ／ES 0.02%、恒指 0.05%",
         "- **前科**：龍飛陣已喺同一批數據跑過約 450 組（#2003–#2038）；今次配額 10 條，跑完就停", ""]
    gold = MU.stooq("xauusd", "1990-01-01"); gtr = [sim(gold, c, 0.0005)[0] for c in CFG]
    res = {}; passes = {"LS": {k: 0 for k in range(5)}, "LO": {k: 0 for k in range(5)}}
    for title, name, cost, counted in MKTS:
        d = load(name); rng = np.random.default_rng(1427 + len(name) + int(d["c"][0]))
        L += [f"## {title}（{dt.datetime.fromtimestamp(int(d['t'][0]), dt.timezone.utc):%Y-%m} → {dt.datetime.fromtimestamp(int(d['t'][-1]), dt.timezone.utc):%Y-%m}，{len(d['t']):,} 日；成本 {cost * 100:.2f}%）", "",
              "| # | 規則 | 版本 | 張 | 平均 R | PF | 前半 | 後半 | 多 | 空 | SMA150 | SMA250 | 隨機平均 | 贏隨機百分位 | 同黃金每月相關 | 每十年 ΣR | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, cfg in enumerate(CFG):
            for ver, lo_only, idea in (("雙向", False, 1427 + k), ("只做多", True, 1432 + k)):
                tr, dens = sim(d, cfg, cost, long_only=lo_only); n, m, pf = MU.st(tr); sp = MU.split_t(tr)
                h1, h2 = MU.mean([x[2] for x in tr if x[0] < sp]), MU.mean([x[2] for x in tr if x[0] >= sp])
                lo, sh = MU.mean([x[2] for x in tr if x[1] > 0]), MU.mean([x[2] for x in tr if x[1] < 0])
                n1 = MU.st(sim(d, cfg, cost, 150, lo_only)[0])[1]; n2 = MU.st(sim(d, cfg, cost, 250, lo_only)[0])[1]
                decs = {}
                for t, _, r in tr:
                    decs[OG.year(t) // 10 * 10] = decs.get(OG.year(t) // 10 * 10, 0) + r
                rm = pct = float("nan")
                if lo_only:
                    p = dens[1][0] / max(dens[1][1], 1); rs = [MU.st(sim(d, cfg, cost, long_only=True, rnd=(rng, p))[0])[1] for _ in range(NRAND)]
                    rm = float(np.mean(rs)); pct = 100.0 * float(np.mean(np.array(rs) < m))
                    ok = all(v > 0 for v in (m, h1, h2, n1, n2)) and pf >= 1.15 and pct >= 95
                else:
                    ok = all(v > 0 for v in (m, h1, h2, lo, sh, n1, n2)) and pf >= 1.15
                if counted:
                    passes["LO" if lo_only else "LS"][k] += ok
                res[(name, k, lo_only)] = tr
                L.append(f"| {idea} | {cfg[0]} | {ver} | {n} | {m:+.3f} | {pf:.2f} | {h1:+.3f} | {h2:+.3f} | {lo:+.3f} | {sh:+.3f} | {n1:+.3f} | {n2:+.3f} | "
                         + (f"{rm:+.3f} | {pct:.0f}" if lo_only else "— | —") + f" | {MU.corr(tr, gtr[k]):+.2f} | " + "、".join(f"{y}s {v:+.0f}" for y, v in sorted(decs.items())) + f" | {'✅' if ok else '❌'} |")
            print(title, cfg[0], flush=True)
        L.append("")
    L += ["## 判決（3 個市場過 ≥ 2 個先算合格；補充嘅現貨指數唔計）", "", "| # | 規則 | 版本 | 過關市場數 | 判 |", "|---|---|---|---|---|"]
    nq = 0
    for k, cfg in enumerate(CFG):
        for ver, key, idea in (("雙向", "LS", 1427 + k), ("只做多", "LO", 1432 + k)):
            ok = passes[key][k] >= 2; nq += ok
            L.append(f"| {idea} | {cfg[0]} | {ver} | {passes[key][k]}／3 | {'✅ 合格' if ok else '❌'} |")
    L += ["", f"- **合格 {nq}／10**", "", "## 三個市場之間同一條規則（只做多版）嘅每月 R 相關", "", "| 規則 | 恒指–納指 | 恒指–標普 | 納指–標普 |", "|---|---|---|---|"]
    for k, cfg in enumerate(CFG):
        L.append(f"| {cfg[0]} | {MU.corr(res[('HSI', k, True)], res[('NQ_F', k, True)]):+.2f} | {MU.corr(res[('HSI', k, True)], res[('ES_F', k, True)]):+.2f} | {MU.corr(res[('NQ_F', k, True)], res[('ES_F', k, True)]):+.2f} |")
    L.append("")
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
