"""地載陣：加倉後買期權保護，能否令 Sharpe ≥ 1？八年主連 1 分 K；訓練 2018-10 至 2023-12、測試 2024 起。

沒有八年的恒指期權價格，所以用模型：Black-Scholes（r = 0），引伸波幅 = 上一個交易日的 VHSI 收市（VHSI 是恒指期權
30 日引伸波幅）。買入與賣回各扣買賣差價 max(2 點, 5% 權利金)。期權每點 HK$50（同恒指期貨）。
保護：持倉加到 trig 張（4 = 加滿、2 = 第一次加倉後）那一根，按當時持倉張數買同等數量的期權——沽單買 Call、好單買 Put；
行使價 = 當時價格 ± 價外距離（0 = 平價；0.5／1 × ATR20；sl = 止蝕價）；期限 tenor 日（曆日）。
平倉時（止賺／止蝕）把期權按當時模型價值減差價賣回；期權先到期就按到期價值結算（不再續買）。
每日權益 = 期貨（含浮動）＋期權市值，Sharpe = 日變化 × √252。

用法：python3 research/hsi_futures_range/dizai_options.py --json /tmp/hsimain.json
"""
import argparse, itertools, json, math, sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_filters as fl                                  # noqa: E402
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import dizai_vhsi as dv                                     # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

HKD = 50
VARIANTS = {"穩": ("confirm", 0.75, 30, 1000, None), "進": ("cross", 1.0, 150, 3000, "run5_3")}


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, vol, call):
    if T <= 1e-9 or vol <= 0:
        return max(0.0, S - K) if call else max(0.0, K - S)
    sd = vol * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    return S * ncdf(d1) - K * ncdf(d2) if call else K * ncdf(-d2) - S * ncdf(-d1)


def spread(p):
    return max(2.0, 0.05 * p)


class Vol:
    """日期 → 上一個交易日的 VHSI（小數）。"""

    def __init__(self):
        rows = dv.load_vhsi()
        self.dates = np.array([d for d, _ in rows])
        self.vals = np.array([v for _, v in rows]) / 100

        self.cache = {}

    def at(self, day):
        if day not in self.cache:
            k = np.searchsorted(self.dates, day) - 1
            self.cache[day] = float(self.vals[max(k, 0)])
        return self.cache[day]


def bar_time(tk):
    return datetime.strptime(tk, "%Y-%m-%d %H:%M:%S")


def protect_series(D, trades, vol, trig_lots, offset, tenor_days):
    """回傳 (每日期權損益累計（點，按交易日收市）, 期權淨成本總點數, 買了幾次)。"""
    c, tk, ends, sid = D["c"], D["tk"], D["ends"], D["sid"]
    n = len(c)
    opt_eq = np.zeros(n)                                     # 期權已實現＋市值（累計，點）
    realized, last, bought, net = 0.0, 0, 0, 0.0
    for x in trades:
        f, side = x["fills"], x["side"]
        buy = next((fj for fj, k, px, lt in f if k in ("open", "add") and lt >= trig_lots), None)
        end = f[-1][0]
        if buy is None:
            continue
        opt_eq[last:buy] = realized
        lots = max(lt for fj, k, px, lt in f if fj <= buy and k in ("open", "add"))
        S0, call = c[buy], side < 0
        atr = D["atr"][f[0][0]]
        if offset == "sl":                                   # 行使價 = 買期權時的止蝕價（平均成本逆向止蝕點數）
            avg, tot = 0.0, 0
            for fj, k, px, lt in f:
                if fj <= buy and k in ("open", "add"):
                    avg, tot = (avg * tot + px * (lt - tot)) / lt, lt
            K = avg - side * x["sl_pts"]
        else:
            K = S0 - side * offset * atr                     # 沽單 Call：K 高於現價；好單 Put：K 低於現價
        tday = D["tday"]
        t0 = tday[buy]
        v0 = vol.at(tk[buy][:10])
        T0 = tenor_days / 365.0
        p0 = bs(S0, K, T0, v0, call)
        cost = lots * (p0 + spread(p0))
        bought += 1
        for b in range(buy, end + 1):
            el = (tday[b] - t0) / 365.0
            val = lots * bs(c[b], K, max(T0 - el, 0.0), vol.at(tk[b][:10]), call)
            opt_eq[b] = realized - cost + val
        el = (tday[end] - t0) / 365.0
        pe = bs(c[end], K, max(T0 - el, 0.0), vol.at(tk[end][:10]), call)
        proceeds = lots * max(0.0, pe - (spread(pe) if pe > 0 else 0.0))
        realized += proceeds - cost
        net += proceeds - cost
        last = end + 1
    opt_eq[last:] = realized
    return opt_eq[ends - 1], net, bought


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    epoch = datetime(2000, 1, 1)
    D["tday"] = np.array([(bar_time(t) - epoch).total_seconds() / 86400 for t in D["tk"]])
    F = fl.day_features(D)
    vol = Vol()
    base = {}
    for name, (trig, g, tp, sl, f5) in VARIANTS.items():
        sig = ds.signals(D, "fade", trig, 0.02, "all")
        if f5:
            sig = [(i, s) for i, s in sig if fl.keep(F, D, i, s, f5)]
        t = [x for x in mg.simulate_mg(D, sig, g, tp, sl_pts=sl) if x["reason"] != "open"]
        for x in t:
            x["sl_pts"] = sl
        base[name] = (t, dv.daily_equity(D, t, [1.0] * len(t)))
    print("加倉後買期權保護（BS＋VHSI，買賣各扣 max(2 點, 5%)）；Sharpe = 日 × √252；金額 HK$\n")
    print("組   觸發 價外   期限 買次 期權淨成本(點)｜ Sharpe 全 訓 測 ｜ 年化HK$萬 最大回撤HK$萬 Calmar")
    results = {}
    for name, (t, fut) in base.items():
        for trig_lots, offset, tenor in [(None, None, None)] + list(itertools.product((4, 2), (0.0, 0.5, 1.0, "sl"), (14, 30, 60))):
            if trig_lots is None:
                opt, net, nb = np.zeros(len(days)), 0.0, 0
            else:
                opt, net, nb = protect_series(D, t, vol, trig_lots, offset, tenor)
            daily = (fut + opt) * HKD
            al, tr, te = dv.metrics(daily, days), dv.metrics(daily, days, hi=ds.TRAIN_END), dv.metrics(daily, days, lo="2024-01-01")
            results[(name, trig_lots, offset, tenor)] = (fut + opt, al, tr, te)
            lab = "不買" if trig_lots is None else f"{trig_lots}張 {offset!s:4s} {tenor:3d}日"
            print(f"{name}  {lab:16s} {nb:3d} {net:+9.0f} ｜ {al['sharpe']:5.2f} {tr['sharpe']:5.2f} {te['sharpe']:5.2f} ｜ "
                  f"{al['ann'] / 1e4:7.1f} {al['mdd'] / 1e4:9.1f} {al['calmar']:6.2f}")
    print("\n穩＋進一齊做（各自用訓練期 Sharpe 最高的保護）：")
    pick = {}
    for name in VARIANTS:
        cand = [(k, v) for k, v in results.items() if k[0] == name]
        k, v = max(cand, key=lambda kv: kv[1][2]["sharpe"])
        pick[name] = (k, v)
        print(f"  {name}：{k[1:]} 訓練 {v[2]['sharpe']:.2f} → 測試 {v[3]['sharpe']:.2f}（全期 {v[1]['sharpe']:.2f}）")
    comb = (pick["穩"][1][0] + pick["進"][1][0]) * HKD
    al, tr, te = dv.metrics(comb, days), dv.metrics(comb, days, hi=ds.TRAIN_END), dv.metrics(comb, days, lo="2024-01-01")
    print(f"  合併：Sharpe 全 {al['sharpe']:.2f}／訓 {tr['sharpe']:.2f}／測 {te['sharpe']:.2f}；年化 HK${al['ann']:,.0f}；"
          f"最大回撤 HK${al['mdd']:,.0f}；Calmar {al['calmar']:.2f}")


if __name__ == "__main__":
    main()
