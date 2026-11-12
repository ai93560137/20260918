"""[IDEAS #1445] 純方向普查：「尋日收市 > SMA200 → 今日做多」喺約 30 個市場有冇資訊（使用者 11-12，路線第二步）。規格同門檻以 IDEAS 預先登記為準。
用法：python3 research/strategy_search/direction_1445.py → research/strategy_search/DIRECTION_1445.md"""
import datetime as dt
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import data_cache as DC          # noqa: E402
import fetch_yahoo_daily as FY   # noqa: E402
import multi_1422 as MU          # noqa: E402

OUT = os.path.join(HERE, "DIRECTION_1445.md")
MK = [("貴金屬", "黃金", "stooq:xauusd", 0.001), ("貴金屬", "白銀", "stooq:xagusd", 0.001), ("貴金屬", "鉑", "PL=F", 0.001), ("貴金屬", "鈀", "PA=F", 0.001),
      ("股指", "標普 500", "^GSPC", 0.0002), ("股指", "納指 100", "^NDX", 0.0002), ("股指", "恒指", "^HSI", 0.0002), ("股指", "日經", "^N225", 0.0002), ("股指", "德國 DAX", "^GDAXI", 0.0002),
      ("股指", "英國富時", "^FTSE", 0.0002), ("股指", "歐元區 50", "^STOXX50E", 0.0002), ("股指", "澳洲", "^AXJO", 0.0002), ("股指", "韓國", "^KS11", 0.0002), ("股指", "台灣", "^TWII", 0.0002),
      ("股指", "印度", "^BSESN", 0.0002), ("股指", "巴西", "^BVSP", 0.0002),
      ("債", "美債 10 年期貨", "ZN=F", 0.0002), ("債", "美債 30 年期貨", "ZB=F", 0.0002), ("債", "TLT", "TLT", 0.0002), ("債", "IEF", "IEF", 0.0002),
      ("能源", "原油", "CL=F", 0.0008), ("能源", "布蘭特", "BZ=F", 0.0008), ("能源", "天然氣", "NG=F", 0.0008),
      ("商品", "銅", "HG=F", 0.0008), ("商品", "粟米", "ZC=F", 0.0008), ("商品", "大豆", "ZS=F", 0.0008), ("商品", "小麥", "ZW=F", 0.0008), ("商品", "咖啡", "KC=F", 0.0008), ("商品", "糖", "SB=F", 0.0008),
      ("加密", "比特幣", "BTC-USD", 0.001)]


def load(tk):
    if tk.startswith("stooq:"):
        d = MU.stooq(tk[6:]); return d["t"], d["c"]
    key = "yahood/x_" + "".join(ch if ch.isalnum() else "_" for ch in tk) + "_d.npz"; d = DC.get(key)
    if d is None:
        d = FY.fetch(tk); time.sleep(1.0)
        if d is None:
            return None, None
        DC.put(key, d)
    return d["t"], d["c"]


def diff(c, n):
    """回傳 (上面日回報, 下面日回報, 狀態陣列, 日回報)。狀態用尋日收市對尋日 SMA n。"""
    r = np.diff(c) / c[:-1]; ok = np.abs(r) < 0.5; md = pd.Series(c).rolling(n).mean().to_numpy(); st = (c > md)[:-1]; valid = ~np.isnan(md[:-1]) & ok
    return r[valid & st], r[valid & ~st], st, r, valid


def welch(a, b):
    if len(a) < 30 or len(b) < 30:
        return float("nan")
    return float((a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))


def mdd(eq):
    pk = np.maximum.accumulate(eq); return float(((pk - eq) / pk).max())


def main():
    L = ["# #1445：純方向普查（尋日收市 > SMA200 → 今日做多）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；日收市對收市回報；每次轉倉扣成本；只讀研究",
         "- 合格＝①上面 − 下面日均回報 > 0 而且 t ≥ 2 ②前後半都 > 0 ③SMA150／250 都 > 0 ④擇時最大回落 < 買入持有", "",
         "| 類別 | 市場 | 由 | 日數 | 在場 | 上面日均 | 下面日均 | t | 前半差 | 後半差 | SMA150 差 | SMA250 差 | 年化：擇時／持有 | Sharpe：擇時／持有 | 最大回落：擇時／持有 | 四關 | 判 |", "|---|" + "---|" * 16]
    npass = 0; passed = []
    for cat, name, tk, cost in MK:
        t, c = load(tk)
        if t is None or len(c) < 1500:
            L.append(f"| {cat} | {name} | 冇數據 |" + " |" * 14); continue
        up, dn, st, r, valid = diff(c, 200); tt = welch(up, dn); idx = np.flatnonzero(valid); h = len(idx) // 2
        d1 = r[idx[:h]][st[idx[:h]]].mean() - r[idx[:h]][~st[idx[:h]]].mean(); d2 = r[idx[h:]][st[idx[h:]]].mean() - r[idx[h:]][~st[idx[h:]]].mean()
        n150 = (lambda a, b, *_: a.mean() - b.mean())(*diff(c, 150)); n250 = (lambda a, b, *_: a.mean() - b.mean())(*diff(c, 250))
        rv, sv = r[idx], st[idx].astype(float); sw = np.abs(np.diff(np.r_[0.0, sv])); tim = sv * rv - sw * cost
        yrs = len(rv) / 252; cg = lambda x: float(np.prod(1 + x) ** (1 / yrs) - 1); sh = lambda x: float(x.mean() / x.std() * np.sqrt(252)) if x.std() > 0 else 0.0  # noqa: E731
        dt_, db = mdd(np.cumprod(1 + tim)), mdd(np.cumprod(1 + rv))
        g = [up.mean() - dn.mean() > 0 and tt >= 2.0, d1 > 0 and d2 > 0, n150 > 0 and n250 > 0, dt_ < db]; ok = all(g); npass += ok
        if ok:
            passed.append(name)
        L.append(f"| {cat} | {name} | {dt.datetime.fromtimestamp(int(t[0]), dt.timezone.utc):%Y} | {len(rv):,} | {100 * sv.mean():.0f}% | {1e4 * up.mean():+.1f}bp | {1e4 * dn.mean():+.1f}bp | {tt:+.2f} | {1e4 * d1:+.1f} | {1e4 * d2:+.1f} | {1e4 * n150:+.1f} | {1e4 * n250:+.1f} | "
                 f"{100 * cg(tim):+.1f}%／{100 * cg(rv):+.1f}% | {sh(tim):.2f}／{sh(rv):.2f} | {100 * dt_:.0f}%／{100 * db:.0f}% | {''.join('✓' if x else '✗' for x in g)} | {'✅' if ok else '❌'} |")
        print(name, ok, flush=True)
    L += ["", f"- **四關全過 {npass}／{len(MK)}**：{'、'.join(passed) if passed else '冇'}（①單獨撞彩預期約 0.7 個）", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
