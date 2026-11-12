"""[IDEAS #1382–#1401] 日線方向＋細止賺大止蝕：用日線條件揀入場日子（使用者 11-12，第二批）。規格以 IDEAS 預先登記為準。
用法：python3 research/strategy_search/dayfilter_1382.py → research/strategy_search/DAYFILTER_1382.md"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import entry_1362 as E1  # noqa: E402

I, B = E1.I, E1.B


def cands_day(self, sec, fn):
    b = B.resample(self.d, 86400); n = len(b["c"]); s = np.r_[self.sd[1:], 0]           # s[k]＝第 k 日收市後嘅狀態
    age = np.zeros(n, int)
    for k in range(n):
        age[k] = 0 if s[k] == 0 else (age[k - 1] + 1 if k and s[k - 1] == s[k] else 1)
    flag = np.zeros(n, bool)
    for sg, q in ((1, b), (-1, I.neg(b))):
        f = np.nan_to_num(fn(q, age).astype(float)) > 0
        flag[1:] |= f[:-1] & (self.sd[1:] == sg)
    t = self.d["t"]
    return np.flatnonzero(self.elig & (t % 3600 == 0) & flag[self.di])


E1.Eng.cands = cands_day
E1.POOL_SEC = 3600


def A14(q):
    return I.atr(q)


def prev(x, n=1):
    return pd.Series(x).shift(n).to_numpy()


def rmax(x, n):
    return pd.Series(x).rolling(n).max().to_numpy()


def volreg(q):
    v = pd.Series(A14(q) / np.abs(q["c"])); return v.to_numpy(), v.rolling(250).median().to_numpy()


def rng_(q):
    return q["h"] - q["l"]


c = lambda q: q["c"]  # noqa: E731
RULES = [
    (1382, "新鮮度", "狀態開始 ≤ 3 日", "D", lambda q, age: age <= 3), (1383, "新鮮度", "狀態開始 ≤ 10 日", "D", lambda q, age: age <= 10),
    (1384, "新鮮度", "狀態開始 > 10 日", "D", lambda q, age: age > 10), (1385, "新鮮度", "狀態開始 > 30 日", "D", lambda q, age: age > 30),
    (1386, "尋日", "尋日收市順方向", "D", lambda q, age: c(q) > prev(c(q))), (1387, "尋日", "尋日收市逆方向", "D", lambda q, age: c(q) < prev(c(q))),
    (1388, "尋日", "尋日波幅 > 1.5×ATR", "D", lambda q, age: rng_(q) > 1.5 * prev(A14(q))), (1389, "尋日", "尋日波幅 < 0.7×ATR", "D", lambda q, age: rng_(q) < 0.7 * prev(A14(q))),
    (1390, "尋日", "尋日收市創 20 日新高", "D", lambda q, age: c(q) > prev(rmax(c(q), 20))),
    (1391, "波幅", "ATR÷價 高過 250 日中位", "D", lambda q, age: volreg(q)[0] > volreg(q)[1]), (1392, "波幅", "ATR÷價 低過 250 日中位", "D", lambda q, age: volreg(q)[0] < volreg(q)[1]),
    (1393, "位置", "高過 SMA20 ≥ 2×ATR", "D", lambda q, age: c(q) - I.sma(c(q), 20) >= 2 * A14(q)),
    (1394, "位置", "同 SMA20 相差 < 1×ATR", "D", lambda q, age: np.abs(c(q) - I.sma(c(q), 20)) < A14(q)),
    (1395, "位置", "高過 SMA200 > 5×ATR", "D", lambda q, age: c(q) - I.sma(c(q), 200) > 5 * A14(q)),
    (1396, "位置", "高過 SMA200 ≤ 5×ATR", "D", lambda q, age: c(q) - I.sma(c(q), 200) <= 5 * A14(q)),
    (1397, "一致", "SMA200 高過 20 日前", "D", lambda q, age: I.sma(c(q), 200) > prev(I.sma(c(q), 200), 20)),
    (1398, "一致", "收市 > SMA50", "D", lambda q, age: c(q) > I.sma(c(q), 50)),
    (1399, "一致", "近 20 日創過 250 日新高", "D", lambda q, age: rmax((c(q) > prev(rmax(c(q), 250))).astype(float), 20) > 0),
    (1400, "一致", "收市 > 5 日前", "D", lambda q, age: c(q) > prev(c(q), 5)), (1401, "一致", "收市 > 60 日前", "D", lambda q, age: c(q) > prev(c(q), 60)),
]

if __name__ == "__main__":
    E1.main(RULES, os.path.join(HERE, "DAYFILTER_1382.md"), "# #1382–#1401：日線方向＋細止賺大止蝕——用日線條件揀入場日子")
