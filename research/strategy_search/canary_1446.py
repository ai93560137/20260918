"""[IDEAS #1446] 金絲雀燈色（波動率期限結構）用喺天覆陣：過濾新倉／亮燈減注／同黃金方向規則嘅關係（使用者 11-12，經總指揮）。
規格同門檻以 IDEAS 預先登記為準（跑之前 commit；唔改燈嘅定義同閾值）。燈色表讀預設分支 canary/canary_daily.csv（冇先退去金絲雀分支）。只讀研究。
用法：python3 research/strategy_search/canary_1446.py → research/strategy_search/CANARY_1446.md"""
import csv
import datetime as dt
import io
import os
import subprocess
import sys

import numpy as np

ARGV = list(sys.argv); sys.argv = [sys.argv[0]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intraday_1323 as I      # noqa: E402
import portfolio_1444 as PF    # noqa: E402
import shadow_board as SB      # noqa: E402

MU = PF.MU
OUT = os.path.join(HERE, "CANARY_1446.md")
BRANCH = "origin/claude/canary-playbook-final-3um9lp"
LIVE = [("926 #1300", "fr1300"), ("933 #1114", "mobrk"), ("937 #1165", "mom1165"), ("939 #1178", "mom1178"), ("940 #1285", "fr1285"), ("942 #1268", "td1268")]
NR = 1000


def lights():
    local = os.path.join(HERE, "..", "..", "canary", "canary_daily.csv")      # 預設分支已有（金絲雀每日更新）；冇先退去金絲雀分支
    if os.path.exists(local):
        txt = open(local, encoding="utf-8").read()
    else:
        txt = subprocess.run(["git", "show", f"{BRANCH}:canary/canary_daily.csv"], capture_output=True, text=True, check=True, cwd=os.path.join(HERE, "..", "..")).stdout
    days, rows = [], []
    for r in csv.DictReader(io.StringIO(txt)):
        f = lambda k: r.get(k) == "1"  # noqa: E731
        days.append(MU.OG.ts(r["date"]) // 86400); rows.append((f("red"), f("deep_red"), f("trial_yellow2")))
    return np.array(days), np.array(rows, bool)


def tag(tr, days, rows):
    """每張單 → (ts, side, R, 紅, 深紅, 黃×2)；用入場日之前最後一個燈色日。冇燈色日（太早／太遲）嘅單剔走。"""
    out = []
    for t, s, r in tr:
        j = int(np.searchsorted(days, int(t) // 86400)) - 1
        if j < 0 or int(t) // 86400 - days[j] > 7:
            continue
        out.append((int(t), int(s), float(r), bool(rows[j][0]), bool(rows[j][1]), bool(rows[j][2])))
    return out


def mk(t):
    x = dt.datetime.fromtimestamp(int(t), dt.timezone.utc); return x.year * 12 + x.month - 1


def monthly(pairs):
    if not pairs:
        return np.zeros(1)
    m0, m1 = min(mk(t) for t, _ in pairs), max(mk(t) for t, _ in pairs); v = np.zeros(m1 - m0 + 1)
    for t, r in pairs:
        v[mk(t) - m0] += r
    return v


def dd(v):
    c = np.cumsum(v); return float((np.maximum.accumulate(np.r_[0, c]) - np.r_[0, c]).max())


def w12(v):
    return float(min(v[i:i + 12].sum() for i in range(max(len(v) - 11, 1))))


def pf(r):
    g = sum(x for x in r if x > 0); l = -sum(x for x in r if x < 0); return g / l if l else float("inf")


def block(L, title, T, rng):
    lit = np.array([x[3] or x[4] or x[5] for x in T]); r = np.array([x[2] for x in T]); ts_ = np.array([x[0] for x in T]); n = len(T)
    keep, cut = r[~lit], r[lit]; mid = np.median(ts_)
    rnd = np.array([np.delete(r, rng.choice(n, size=int(lit.sum()), replace=False)).mean() for _ in range(NR)]); pct = 100.0 * float((rnd < keep.mean()).mean())
    allm = monthly(list(zip(ts_, r))); km = monthly(list(zip(ts_[~lit], keep))); hm = monthly(list(zip(ts_, np.where(lit, 0.5 * r, r))))
    ra, rk, rh = allm.sum() / dd(allm), km.sum() / dd(km), hm.sum() / dd(hm)
    h1 = cut[ts_[lit] < mid].mean() < keep[ts_[~lit] < mid].mean() if (ts_[lit] < mid).any() else False
    h2 = cut[ts_[lit] >= mid].mean() < keep[ts_[~lit] >= mid].mean() if (ts_[lit] >= mid).any() else False
    g1 = [pct >= 95, cut.mean() < keep.mean() and h1 and h2, rk > ra]; g2 = [dd(hm) < dd(allm), w12(hm) > w12(allm), rh > ra]
    L += [f"### {title}", "", f"- 共 {n} 張，亮燈時入場 {int(lit.sum())} 張（{100 * lit.mean():.0f}%）", "",
          "| 版本 | 張 | 平均 R | PF | ΣR | 每月最大回落 | 最差連續 12 月 | ΣR÷回落 |", "|---|---|---|---|---|---|---|---|",
          f"| 全部（原本） | {n} | {r.mean():+.3f} | {pf(r):.2f} | {r.sum():+.1f} | {dd(allm):.1f} | {w12(allm):+.1f} | {ra:.2f} |",
          f"| 亮燈時入場嘅單 | {len(cut)} | {cut.mean():+.3f} | {pf(cut):.2f} | {cut.sum():+.1f} | — | — | — |",
          f"| 測試 1：亮燈唔開新倉 | {len(keep)} | {keep.mean():+.3f} | {pf(keep):.2f} | {keep.sum():+.1f} | {dd(km):.1f} | {w12(km):+.1f} | {rk:.2f} |",
          f"| 測試 2：亮燈新倉減半 | {n} | — | — | {hm.sum():+.1f} | {dd(hm):.1f} | {w12(hm):+.1f} | {rh:.2f} |", "",
          f"- 測試 1：留低嘅單平均 R 喺隨機剔走入面排第 {pct:.0f} 百分位（隨機平均 {rnd.mean():+.3f}）；被剔走 < 留低 前半 {'✓' if h1 else '✗'}、後半 {'✓' if h2 else '✗'}；三關 {''.join('✓' if x else '✗' for x in g1)} → **{'✅' if all(g1) else '❌'}**",
          f"- 測試 2：回落 {dd(allm):.1f}→{dd(hm):.1f}、最差 12 月 {w12(allm):+.1f}→{w12(hm):+.1f}、代價 {r.sum() - hm.sum():+.1f}R；三關 {''.join('✓' if x else '✗' for x in g2)} → **{'✅' if all(g2) else '❌'}**", ""]
    return all(g1), all(g2)


def main():
    days, rows = lights(); rng = np.random.default_rng(1446); d = I.load(); S = {s[0]: s for s in SB.STRATS}
    L = ["# #1446：金絲雀燈色用喺天覆陣", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；燈色表＝`canary/canary_daily.csv`（{len(days):,} 日；紅 {100 * rows[:, 0].mean():.0f}%、深紅 {100 * rows[:, 1].mean():.0f}%、黃×2 {100 * rows[:, 2].mean():.0f}%、任何一隻 {100 * rows.any(axis=1).mean():.0f}% 嘅日子亮）",
         "- 「亮燈」＝紅或深紅或黃×2；D 日收市嘅燈只用喺之後入場嘅單；燈嘅定義同閾值冇改；只讀研究", "", "## (A) 真倉 6 本（2010–2026 M1 嚴格版回測）", ""]
    A = {name: tag(S[key][3](d), days, rows) for name, key in LIVE}
    ra = block(L, "6 本合併", [x for v in A.values() for x in v], rng)
    L += ["| 簿 | 張 | 亮燈張數 | 冇燈平均 R | 亮燈平均 R |", "|---|---|---|---|---|"]
    for name, T in A.items():
        a = [x[2] for x in T if not (x[3] or x[4] or x[5])]; b = [x[2] for x in T if (x[3] or x[4] or x[5])]
        L.append(f"| {name} | {len(T)} | {len(b)} | {np.mean(a):+.3f} | {np.mean(b) if b else float('nan'):+.3f} |")
    L += ["", "## (B) #1444 組合四部件（日線回測，2006-08 起）", ""]
    P = {k: tag(v, days, rows) for k, v in PF.parts().items()}
    rb = block(L, "四部件合併", [x for v in P.values() for x in v], rng)
    L += ["| 部件 | 張 | 亮燈張數 | 冇燈平均 R | 亮燈平均 R |", "|---|---|---|---|---|"]
    for name, T in P.items():
        a = [x[2] for x in T if not (x[3] or x[4] or x[5])]; b = [x[2] for x in T if (x[3] or x[4] or x[5])]
        L.append(f"| {name} | {len(T)} | {len(b)} | {np.mean(a):+.3f} | {np.mean(b) if b else float('nan'):+.3f} |")
    G = P[next(k for k in P if k.startswith("G"))]
    L += ["", "## 測試 3：黃金 #1268（日線，2006 後）按入場時燈色同方向（描述性）", "", "| 分組 | 做多 張／平均 R | 做空 張／平均 R |", "|---|---|---|"]
    for nm, fn in (("冇燈", lambda x: not (x[3] or x[4] or x[5])), ("亮燈（任何）", lambda x: x[3] or x[4] or x[5]), ("紅", lambda x: x[3]), ("深紅", lambda x: x[4]), ("黃×2", lambda x: x[5])):
        lo = [x[2] for x in G if fn(x) and x[1] > 0]; sh = [x[2] for x in G if fn(x) and x[1] < 0]
        L.append(f"| {nm} | {len(lo)}／{np.mean(lo) if lo else float('nan'):+.3f} | {len(sh)}／{np.mean(sh) if sh else float('nan'):+.3f} |")
    for nm, sgn in (("做多", 1), ("做空", -1)):
        a = np.array([x[2] for x in G if x[1] == sgn and not (x[3] or x[4] or x[5])]); b = np.array([x[2] for x in G if x[1] == sgn and (x[3] or x[4] or x[5])])
        t = (b.mean() - a.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)) if len(a) > 5 and len(b) > 5 else float("nan")
        L.append(f"- {nm}：亮燈 − 冇燈 平均 R 差 {b.mean() - a.mean() if len(b) else float('nan'):+.3f}（t {t:+.2f}）")
    L += ["", "## 判決", "", f"- (A) 真倉 6 本：測試 1 {'✅' if ra[0] else '❌'}、測試 2 {'✅' if ra[1] else '❌'}", f"- (B) #1444 組合：測試 1 {'✅' if rb[0] else '❌'}、測試 2 {'✅' if rb[1] else '❌'}", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
