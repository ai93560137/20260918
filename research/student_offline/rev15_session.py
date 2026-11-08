"""[IDEAS #1012] rev15 E6S4 係咪集中喺紐約開市前後：時段過濾（先過濾後冷卻，即係實盤加時段開關嘅效果）。
主判窗口＝12:00–15:59 UTC（涵蓋 12:30／13:30 美國數據、COMEX 開市、美股 13:30／14:30 開市，夏冬令都包）；對照＝其餘時間。
規則同 #1001／#1002 原版：前 15 根走幅 ≥ 3 美元反向；E6 Z2 S4 1R、30 分鐘有效、60 分鐘冷卻、每張扣 0.5 美元。冇網格。
規格、成功標準以 IDEAS #1012 預先登記為準（跑之前 commit）。每個鐘嘅表只作描述，唔准用嚟揀新窗口再試同一批數據。
用法：python3 research/student_offline/rev15_session.py → research/student_offline/REV15_SESSION.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = [sys.argv[0], "--src", "mt5"]
import rev15_history as rh   # noqa: E402
fr = rh.fr

LB, TH = 15, 3.0
E, Z, S, RT = 6.0, 2.0, 4.0, 1.0
WIN = (12, 16)               # 12:00–15:59 UTC


def load(src, a, b):
    rh.SRC = src
    rh.A, rh.B, rh.CACHE = a, b, f"/tmp/rev15_history_{src}_{a}_{b}.npz"
    return rh.load()


def run(d, keep):
    """keep(hour 陣列) → bool；回傳 (r, ts)。訊號時間＝觸發分鐘收市（t+60）。"""
    t, o, c = d["t"], d["o"], d["c"]
    n = len(t)
    mv = np.full(n, np.nan); mv[LB:] = c[LB:] - o[:-LB]
    hr = ((t + 60) // 3600) % 24
    ok = (np.abs(mv) >= TH) & (np.arange(n) >= 29) & keep(hr)
    raw = [(int(i), "BUY" if mv[i] < 0 else "SELL") for i in np.nonzero(ok)[0]]
    sigs = fr.cooldown(raw, t, 60, int(t[0]), int(t[-1]) + 60)
    r = fr.simulate(fr.future_mats(d, sigs), E, Z, S, RT)
    ts = np.array([int(t[i]) + 60 for i, _ in sigs], dtype=np.int64)
    return r, ts


def yearly(r, ts):
    out = {}
    for x, s in zip(r, ts):
        if not np.isnan(x):
            out.setdefault(dt.datetime.fromtimestamp(int(s), dt.timezone.utc).year, []).append(x)
    return {y: fr.stats(np.array(v)) for y, v in sorted(out.items())}


def main():
    inw = lambda h: (h >= WIN[0]) & (h < WIN[1])
    outw = lambda h: ~inw(h)
    sets = [("Dukascopy 2015–2022", load("duka", "2015-01-01", "2022-12-31")),
            ("MT5 2023-01→2026-10", load("mt5", "2023-01-01", "2026-10-30"))]
    out = ["# rev15 E6S4 時段集中（IDEAS #1012）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；主判窗口 {WIN[0]:02d}:00–{WIN[1] - 1:02d}:59 UTC；"
           "規則同原版 rev15 E6S4（走幅≥3 反向、E6 Z2 S4 1R、30 分鐘、冷卻 60 分鐘、扣 0.5 美元）；先按時段過濾再冷卻", "",
           "| 數據 | 窗口內（主判） | 窗口外 | 全日（原版） |", "|---|---|---|---|"]
    res = {}
    for name, d in sets:
        a, b, c = run(d, inw), run(d, outw), run(d, lambda h: np.ones_like(h, bool))
        res[name] = (a, b, c)
        out.append(f"| {name} | {fr.fmt(fr.stats(a[0]))} | {fr.fmt(fr.stats(b[0]))} | {fr.fmt(fr.stats(c[0]))} |")
    out += ["", "## 每個鐘（全日原版冷卻後按訊號鐘分；只作描述）", "", "| UTC 鐘 | Dukascopy | MT5 |", "|---|---|---|"]
    for hh in range(24):
        row = []
        for name, _ in sets:
            r, ts = res[name][2]
            m = ((ts // 3600) % 24) == hh
            row.append(fr.fmt(fr.stats(r[m])))
        out.append(f"| {hh:02d} | " + " | ".join(row) + " |")
    dn = sets[0][0]; mn = sets[1][0]
    ywin, yout = yearly(*res[dn][0]), yearly(*res[dn][1])
    out += ["", "## Dukascopy 每年（窗口內 對 窗口外）", "", "| 年 | 窗口內 | 窗口外 |", "|---|---|---|"]
    out += [f"| {y} | {fr.fmt(ywin[y])} | {fr.fmt(yout.get(y, {'n': 0}))} |" for y in sorted(ywin)]
    sw, so = fr.stats(res[dn][0][0]), fr.stats(res[dn][1][0])
    mw, mo = fr.stats(res[mn][0][0]), fr.stats(res[mn][1][0])
    beat = sum(1 for y in ywin if ywin[y]["n"] and yout.get(y, {"n": 0})["n"] and ywin[y]["avg"] > yout[y]["avg"])
    g = lambda s: s["avg"] if s["n"] else -9
    ok = {"①Duka 窗口內 n≥200、平均≥+0.15R、PF≥1.3": sw["n"] >= 200 and g(sw) >= 0.15 and sw["pf"] >= 1.3,
          "②Duka 窗口內減窗口外 ≥ +0.10R": g(sw) - g(so) >= 0.10,
          "③MT5 窗口內平均≥+0.10R 且 減窗口外 ≥ +0.05R": g(mw) >= 0.10 and g(mw) - g(mo) >= 0.05,
          "④Duka 8年≥6年窗口內高過窗口外": beat >= 6}
    out += ["", "## 判（預先登記 IDEAS #1012）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            f"- Duka 窗口內高過窗口外嘅年份 {beat}／{len(ywin)}",
            "- " + ("✅ 達標 → 只提案：933／rev15 影子加時段版並排前向（唔落單）" if all(ok.values())
                    else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔准按每鐘表另揀窗口再試同一批數據"), ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "REV15_SESSION.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
