"""[IDEAS #1450–#1452] 回看第二批：三個有理論支持嘅假說，用未用過嘅市場做樣本外重現（使用者 11-12）。規格同門檻以 IDEAS 預先登記為準。
用法：python3 research/strategy_search/replicate_1450.py → research/strategy_search/REPLICATE_1450.md"""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import direction_1445 as DR   # noqa: E402
import multi_1422 as MU       # noqa: E402

OUT = os.path.join(HERE, "REPLICATE_1450.md")
COINS = [("ETH", "ETH-USD"), ("LTC", "LTC-USD"), ("XRP", "XRP-USD"), ("BCH", "BCH-USD"), ("ADA", "ADA-USD"), ("DOGE", "DOGE-USD"), ("BNB", "BNB-USD"), ("SOL", "SOL-USD")]
IDX = [("加拿大", "^GSPTSE"), ("法國", "^FCHI"), ("西班牙", "^IBEX"), ("瑞士", "^SSMI"), ("荷蘭", "^AEX"), ("瑞典", "^OMX"), ("意大利", "FTSEMIB.MI"), ("印尼", "^JKSE"), ("新加坡", "^STI"),
       ("馬來西亞", "^KLSE"), ("墨西哥", "^MXX"), ("新西蘭", "^NZ50"), ("上證", "000001.SS"), ("以色列", "^TA125.TA"), ("泰國", "^SET.BK")]
CCY = [("EUR", "EURUSD=X", True), ("JPY", "JPY=X", False), ("GBP", "GBPUSD=X", True), ("AUD", "AUDUSD=X", True), ("CHF", "CHF=X", False), ("CAD", "CAD=X", False)]


def timing(c, n, cost, days_per_year):
    """回傳 dict：上面／下面日回報、擇時同長揸嘅 Sharpe、最大回落、有效索引。"""
    up, dn, st, r, valid = DR.diff(c, n); idx = np.flatnonzero(valid); rv, sv = r[idx], st[idx].astype(float)
    tim = sv * rv - np.abs(np.diff(np.r_[0.0, sv])) * cost; sh = lambda x: float(x.mean() / x.std() * np.sqrt(days_per_year)) if x.std() > 0 else 0.0  # noqa: E731
    return {"up": up, "dn": dn, "rv": rv, "sv": sv, "tim": tim, "sh_t": sh(tim), "sh_b": sh(rv), "dd_t": DR.mdd(np.cumprod(1 + tim)), "dd_b": DR.mdd(np.cumprod(1 + rv))}


def t1450(L):
    rows = []; ups, dns, h1u, h1d, h2u, h2d = [], [], [], [], [], []; n150 = [[], []]; n250 = [[], []]
    L += ["## #1450 加密貨幣時間序列動量（8 隻，唔包比特幣；尋日收市 > SMA200 → 今日做多）", "", "| 幣 | 由 | 日數 | 線上面日均 | 線下面日均 | 差值 | 年化：擇時／長揸 | 最大回落：擇時／長揸 |", "|---|---|---|---|---|---|---|---|"]
    pos = ddok = 0
    for nm, tk in COINS:
        t, c = DR.load(tk)
        if t is None or len(c) < 700:
            L.append(f"| {nm} | 冇數據 | | | | | | |"); continue
        x = timing(c, 200, 0.001, 365); h = len(x["rv"]) // 2; s = x["sv"].astype(bool)
        ups.append(x["up"]); dns.append(x["dn"]); h1u.append(x["rv"][:h][s[:h]]); h1d.append(x["rv"][:h][~s[:h]]); h2u.append(x["rv"][h:][s[h:]]); h2d.append(x["rv"][h:][~s[h:]])
        for nn, store in ((150, n150), (250, n250)):
            a, b, *_ = DR.diff(c, nn); store[0].append(a); store[1].append(b)
        yrs = len(x["rv"]) / 365; cg = lambda v: float(np.prod(1 + v) ** (1 / yrs) - 1)  # noqa: E731
        d = x["up"].mean() - x["dn"].mean(); pos += d > 0; ddok += x["dd_t"] < x["dd_b"]
        L.append(f"| {nm} | {dt.datetime.fromtimestamp(int(t[0]), dt.timezone.utc):%Y-%m} | {len(x['rv']):,} | {1e4 * x['up'].mean():+.1f}bp | {1e4 * x['dn'].mean():+.1f}bp | {1e4 * d:+.1f}bp | {100 * cg(x['tim']):+.0f}%／{100 * cg(x['rv']):+.0f}% | {100 * x['dd_t']:.0f}%／{100 * x['dd_b']:.0f}% |")
    cat = np.concatenate; U, D = cat(ups), cat(dns); tt = DR.welch(U, D)
    d1 = cat(h1u).mean() - cat(h1d).mean(); d2 = cat(h2u).mean() - cat(h2d).mean(); e150 = cat(n150[0]).mean() - cat(n150[1]).mean(); e250 = cat(n250[0]).mean() - cat(n250[1]).mean()
    g = [U.mean() - D.mean() > 0 and tt >= 2.0, d1 > 0 and d2 > 0, e150 > 0 and e250 > 0, pos >= 6, ddok >= 6]
    L += ["", f"- 合併：線上面 {1e4 * U.mean():+.1f}bp、線下面 {1e4 * D.mean():+.1f}bp、Welch t {tt:+.2f}；前半差 {1e4 * d1:+.1f}bp、後半差 {1e4 * d2:+.1f}bp；SMA150 差 {1e4 * e150:+.1f}bp、SMA250 差 {1e4 * e250:+.1f}bp；差值為正 {pos}／8；回落較細 {ddok}／8",
          f"- 五關：{''.join('✓' if x else '✗' for x in g)} → **{'✅ 合格' if all(g) else '❌ 唔合格'}**（限制：只揀今日仲存在嘅大幣，倖存者偏差）", ""]
    return all(g)


def t1451(L):
    L += ["## #1451 股指 200 日線做「避大跌」工具（15 個未用過嘅非美國股指）", "", "| 股指 | 由 | 在場 | Sharpe：擇時／長揸 | 最大回落：擇時／長揸 | 前半 Sharpe 差 | 後半 Sharpe 差 |", "|---|---|---|---|---|---|---|"]
    ddok = shok = 0; d1s, d2s, red = [], [], []; n = 0
    for nm, tk in IDX:
        t, c = DR.load(tk)
        if t is None or len(c) < 1500:
            L.append(f"| {nm} | 冇數據 | | | | | |"); continue
        n += 1; x = timing(c, 200, 0.0005, 252); h = len(x["rv"]) // 2; sh = lambda v: float(v.mean() / v.std() * np.sqrt(252)) if v.std() > 0 else 0.0  # noqa: E731
        a1, a2 = sh(x["tim"][:h]) - sh(x["rv"][:h]), sh(x["tim"][h:]) - sh(x["rv"][h:]); d1s.append(a1); d2s.append(a2); red.append(1 - x["dd_t"] / x["dd_b"])
        ddok += x["dd_t"] < x["dd_b"]; shok += x["sh_t"] >= x["sh_b"]
        L.append(f"| {nm} | {dt.datetime.fromtimestamp(int(t[0]), dt.timezone.utc):%Y} | {100 * x['sv'].mean():.0f}% | {x['sh_t']:.2f}／{x['sh_b']:.2f} | {100 * x['dd_t']:.0f}%／{100 * x['dd_b']:.0f}% | {a1:+.2f} | {a2:+.2f} |")
    need_dd, need_sh = int(np.ceil(n * 12 / 15)), int(np.ceil(n * 10 / 15))
    g = [ddok >= need_dd, shok >= need_sh, np.mean(d1s) > 0 and np.mean(d2s) > 0, np.mean(red) >= 0.25]
    L += ["", f"- 有數據 {n} 個：回落較細 {ddok}／{n}（要 ≥ {need_dd}）；Sharpe 不低於長揸 {shok}／{n}（要 ≥ {need_sh}）；平均 Sharpe 差 前半 {np.mean(d1s):+.2f}、後半 {np.mean(d2s):+.2f}；平均最大回落相對減少 {100 * np.mean(red):.0f}%",
          f"- 四關：{''.join('✓' if x else '✗' for x in g)} → **{'✅ 合格' if all(g) else '❌ 唔合格'}**", ""]
    return all(g)


def t1452(L):
    g = MU.stooq("xauusd", "2003-12-01"); gs = pd.Series(g["c"], index=g["t"] // 86400)
    L += ["## #1452 黃金趨勢係金本身定係美元（6 種貨幣計價嘅黃金，#1268 狀態機雙向，只用收市）", "", "| 計價 | 張 | 平均 R | PF | 前半 | 後半 | 多 | 空 | SMA150 | SMA250 | 判 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    def row(nm, c, t):
        d = {"t": np.asarray(t, np.int64) * 86400, "o": c, "h": c, "l": c, "c": c}
        tr = MU.run(d, 0.0005)["#1422"]; n, m, pf = MU.st(tr); sp = MU.split_t(tr)
        h1, h2 = MU.mean([x[2] for x in tr if x[0] < sp]), MU.mean([x[2] for x in tr if x[0] >= sp]); lo, sh = MU.mean([x[2] for x in tr if x[1] > 0]), MU.mean([x[2] for x in tr if x[1] < 0])
        n1 = MU.st(MU.run(d, 0.0005, 150)["#1422"])[1]; n2 = MU.st(MU.run(d, 0.0005, 250)["#1422"])[1]
        ok = all(v > 0 for v in (m, h1, h2, lo, sh, n1, n2)) and pf >= 1.15
        L.append(f"| {nm} | {n} | {m:+.3f} | {pf:.2f} | {h1:+.3f} | {h2:+.3f} | {lo:+.3f} | {sh:+.3f} | {n1:+.3f} | {n2:+.3f} | {'✅' if ok else '❌'} |"); return ok
    row("（對照）USD", gs.to_numpy(), gs.index.to_numpy()); npass = 0
    for nm, tk, usd_quote in CCY:
        t, c = DR.load(tk); fx = pd.Series(c, index=np.asarray(t) // 86400); fx = fx[~fx.index.duplicated()]
        j = pd.concat([gs, fx], axis=1, join="inner").dropna(); x = (j.iloc[:, 0] / j.iloc[:, 1] if usd_quote else j.iloc[:, 0] * j.iloc[:, 1])
        x = x[(x.pct_change().abs() < 0.2) | x.pct_change().isna()]
        npass += row(nm, x.to_numpy(float), x.index.to_numpy())
    ok = npass >= 4
    L += ["", f"- 過關 {npass}／6（要 ≥ 4）→ **{'✅ 合格' if ok else '❌ 唔合格'}**", ""]
    return ok


def main():
    L = ["# #1450–#1452：回看第二批——三個有理論支持嘅假說做樣本外重現", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；Yahoo／stooq 日線；只讀研究，唔落單", ""]
    r = [t1450(L), t1451(L), t1452(L)]
    L += ["## 總結", "", f"- #1450 {'✅' if r[0] else '❌'}、#1451 {'✅' if r[1] else '❌'}、#1452 {'✅' if r[2] else '❌'} → 合格 {sum(r)}／3", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
