"""[IDEAS #1437–#1442] 黃金日線框架搬去其他產品（第二輪：Yahoo 長歷史可買賣日線）＋白銀只做多。規格、成本、門檻以 IDEAS 預先登記為準（跑之前 commit）。
用法：python3 research/strategy_search/multi2_1437.py → research/strategy_search/MULTI2_1437.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import data_cache as DC      # noqa: E402
import index_1427 as IX      # noqa: E402
import multi_1422 as MU      # noqa: E402

OG = MU.OG
OUT = os.path.join(HERE, "MULTI2_1437.md")
IDS = ["#1437", "#1438", "#1439", "#1440", "#1441"]
CATS = [("① 外匯（9 對）", [(s, 0.0002 if s in ("EURJPY", "GBPJPY") else 0.00015) for s in MU.FX]),
        ("② 貴金屬（白銀現貨、鉑、鈀）", [("stooq:xagusd", 0.0012), ("PL_F", 0.0015), ("PA_F", 0.0015)]),
        ("③ 利率（ZN、ZB、TLT、IEF；高度相關）", [("ZN_F", 0.0002), ("ZB_F", 0.0002), ("TLT", 0.0002), ("IEF", 0.0002)]),
        ("④ 能源（原油 CL、布蘭特 BZ、天然氣 NG）", [("CL_F", 0.0005), ("BZ_F", 0.0005), ("NG_F", 0.0010)])]


def load(name):
    if name.startswith("stooq:"):
        return MU.stooq(name[6:])
    d = DC.get(f"yahood/{name}_d.npz"); return {k: d[k] for k in ("t", "o", "h", "l", "c")}


def mid_t(tr):
    ts_ = sorted(x[0] for x in tr); return ts_[len(ts_) // 2] if ts_ else 0


def main():
    L = ["# #1437–#1442：黃金日線框架搬去其他產品（第二輪：長歷史可買賣日線）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；數據 Yahoo 日線（`YAHOO_DAILY.md`）＋白銀 stooq；只讀研究，唔落單",
         "- 規則原封不動（SMA200 定方向、SL 3×ATR14、250 日到期、做空鏡像）；日線執行模擬；成本按品種寫死",
         "- **數據限制**：期貨係連續合約冇價差調整（原油、天然氣轉月跳空會造成假訊號同假損益）；ETF 未除息；鉑、鈀早年大量日子只有結算價", ""]
    gold = MU.run(MU.stooq("xauusd", "1973-01-01"), 0.0005); verdict = {}
    for cat, syms in CATS:
        base = {}; nb = {150: {}, 250: {}}
        for s, cost in syms:
            d = load(s); base[s] = MU.run(d, cost); nb[150][s] = MU.run(d, cost, 150); nb[250][s] = MU.run(d, cost, 250); print(cat, s, flush=True)
        L += [f"## {cat}", "", "| # | 規則 | 張 | 平均 R | PF | 前半 | 後半 | 多 | 空 | SMA150 | SMA250 | 為正品種 | 同黃金每月相關 | 每十年 ΣR | 各品種平均 R（張） | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for (rid0, nm, _), rid in zip(MU.RULES, IDS):
            tr = [x for s, _ in syms for x in base[s][rid0]]; n, m, pf = MU.st(tr); sp = mid_t(tr)
            h1, h2 = MU.mean([x[2] for x in tr if x[0] < sp]), MU.mean([x[2] for x in tr if x[0] >= sp])
            lo, sh = MU.mean([x[2] for x in tr if x[1] > 0]), MU.mean([x[2] for x in tr if x[1] < 0])
            n1 = MU.mean([x[2] for s, _ in syms for x in nb[150][s][rid0]]); n2 = MU.mean([x[2] for s, _ in syms for x in nb[250][s][rid0]])
            pos = sum(1 for s, _ in syms if MU.st(base[s][rid0])[1] > 0); decs = {}
            for t, _, r in tr:
                decs[OG.year(t) // 10 * 10] = decs.get(OG.year(t) // 10 * 10, 0) + r
            ok = all(v > 0 for v in (m, h1, h2, lo, sh, n1, n2)) and pf >= 1.15 and pos * 3 >= 2 * len(syms); verdict[(cat, rid)] = ok
            L.append(f"| {rid} | {nm} | {n} | {m:+.3f} | {pf:.2f} | {h1:+.3f} | {h2:+.3f} | {lo:+.3f} | {sh:+.3f} | {n1:+.3f} | {n2:+.3f} | {pos}／{len(syms)} | {MU.corr(tr, gold[rid0]):+.2f} | "
                     + "、".join(f"{y}s {v:+.0f}" for y, v in sorted(decs.items())) + " | " + "、".join(f"{s.split(':')[-1]} {MU.st(base[s][rid0])[1]:+.2f}（{MU.st(base[s][rid0])[0]}）" for s, _ in syms) + f" | {'✅' if ok else '❌'} |")
        L.append("")
    L += ["## 總表（每條規則 × 每個類別）", "", "| 類別 | " + " | ".join(IDS) + " | 過幾多條 |", "|---|" + "---|" * 6]
    for cat, _ in CATS:
        L.append(f"| {cat} | " + " | ".join("✅" if verdict[(cat, r)] else "❌" for r in IDS) + f" | {sum(verdict[(cat, r)] for r in IDS)}／5 |")
    L += ["", f"- 20 格入面過 {sum(verdict.values())} 格", "", "## #1442 白銀只做多（唔係盲測：#1422 已見過白銀做多腳為正；新嘢係「贏隨機」）", "",
          "| 數據 | 規則 | 張 | 平均 R | PF | 前半 | 後半 | SMA150 | SMA250 | 隨機平均 | 贏隨機百分位 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ag = {}
    for title, name in (("白銀 stooq 1968–2026", "stooq:xagusd"), ("白銀期貨 SI=F 2000–2026", "SI_F")):
        d = load(name); rng = np.random.default_rng(1442 + len(name))
        for k, cfg in enumerate(IX.CFG):
            tr, dens = IX.sim(d, cfg, 0.0012, long_only=True); n, m, pf = MU.st(tr); sp = mid_t(tr)
            h1, h2 = MU.mean([x[2] for x in tr if x[0] < sp]), MU.mean([x[2] for x in tr if x[0] >= sp])
            n1 = MU.st(IX.sim(d, cfg, 0.0012, 150, True)[0])[1]; n2 = MU.st(IX.sim(d, cfg, 0.0012, 250, True)[0])[1]
            p = dens[1][0] / max(dens[1][1], 1); rs = [MU.st(IX.sim(d, cfg, 0.0012, long_only=True, rnd=(rng, p))[0])[1] for _ in range(IX.NRAND)]
            pct = 100.0 * float(np.mean(np.array(rs) < m)); ok = all(v > 0 for v in (m, h1, h2, n1, n2)) and pf >= 1.15 and pct >= 95; ag.setdefault(k, []).append(ok)
            L.append(f"| {title} | {cfg[0]} | {n} | {m:+.3f} | {pf:.2f} | {h1:+.3f} | {h2:+.3f} | {n1:+.3f} | {n2:+.3f} | {np.mean(rs):+.3f} | {pct:.0f} | {'✅' if ok else '❌'} |")
        print(title, flush=True)
    L += ["", "- 兩個數據都過先算合格：" + "、".join(f"{IX.CFG[k][0]} {'✅' if all(v) else '❌'}" for k, v in ag.items()), ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
