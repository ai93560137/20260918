"""地載陣加 VHSI：能否令 Sharpe ≥ 1？八年主連 1 分 K；訓練 2018-10 至 2023-12、測試 2024 起。

VHSI 日線：canary/data_external/vhsi_daily.csv（金絲雀每日更新）。交易日 D 只用 D 之前最後一個 VHSI 收市（入場前已知）。
Sharpe = 每個交易日收市時的累計權益（含持倉浮動）的日變化，平均 ÷ 標準差 × √252，無風險利率當 0。

篩選（沽、買都一樣）：
  vmax_X   上日 VHSI > X 不做           vmin_X  上日 VHSI < X 不做
  vchg_X   VHSI 過去 5 日升 ≥ X% 不做   vpct_X  上日 VHSI 高於過去 250 日的 X 分位不做
注碼：
  eq      每筆一樣（1→2→4 張）
  inv     每筆 × (過去 250 日 VHSI 中位 ÷ 上日 VHSI)，限 0.5–2 倍（VHSI 高時落少、低時落多）
  inv2    同上但平方（反比於變異數），限 0.25–2 倍

用法：python3 research/hsi_futures_range/dizai_vhsi.py --json /tmp/hsimain.json [--variant steady|bold]
"""
import argparse, csv, itertools, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_filters as fl                                  # noqa: E402
import dizai_martingale as mg                               # noqa: E402
import dizai_search as ds                                   # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
VARIANTS = {"steady": ("confirm", 0.75, 30, 1000, None), "bold": ("cross", 1.0, 150, 3000, "run5_3")}
HKD = 50


def load_vhsi():
    with open(REPO / "canary" / "data_external" / "vhsi_daily.csv") as f:
        rows = [(r["Date"], float(r["Close"])) for r in csv.DictReader(f) if r.get("Close")]
    return sorted(rows)


def vhsi_by_session(days, vh):
    """每個交易日：上日 VHSI、過去 250 日中位與 X 分位所需的歷史、5 日變化。"""
    dates = np.array([d for d, _ in vh])
    vals = np.array([v for _, v in vh])
    out = []
    for d in days:
        k = np.searchsorted(dates, d) - 1                   # 嚴格早於交易日
        if k < 250:
            out.append(None)
            continue
        hist = vals[k - 249:k + 1]
        out.append({"v": vals[k], "med": float(np.median(hist)), "hist": hist,
                    "chg5": vals[k] / vals[k - 5] - 1})
    return out


def keep(V, flt):
    if flt == "none":
        return True
    if V is None:
        return False
    kind, x = flt.split("_")
    x = float(x)
    if kind == "vmax":
        return V["v"] <= x
    if kind == "vmin":
        return V["v"] >= x
    if kind == "vchg":
        return V["chg5"] < x / 100
    if kind == "vpct":
        return V["v"] <= np.quantile(V["hist"], x / 100)
    raise ValueError(flt)


def weight(V, mode):
    if mode == "eq" or V is None:
        return 1.0
    r = V["med"] / V["v"]
    return float(np.clip(r, 0.5, 2.0)) if mode == "inv" else float(np.clip(r * r, 0.25, 2.0))


def daily_equity(D, trades, weights):
    """每個交易日收市時的累計權益（點 × 注碼）。"""
    c, ends, n = D["c"], D["ends"], len(D["c"])
    eq = np.zeros(n)
    realized, last = 0.0, 0
    for x, w in zip(trades, weights):
        f, side = x["fills"], x["side"]
        e, j = f[0][0], f[-1][0]
        eq[last:e] = realized
        lots, avg, paid, idx = 0, 0.0, 0.0, 0
        for b in range(e, j + 1):
            while idx < len(f) and f[idx][0] == b and f[idx][1] in ("open", "add"):
                q = f[idx][3] - lots
                avg = (avg * lots + f[idx][2] * q) / f[idx][3]
                lots, paid, idx = f[idx][3], paid + q, idx + 1
            eq[b] = realized + w * (lots * side * (c[b] - avg) - paid)
        realized += w * x["pnl"]
        last = j + 1
    eq[last:] = realized
    return eq[ends - 1]


def metrics(daily, days, lo=None, hi=None):
    idx = [k for k, d in enumerate(days) if (lo is None or d >= lo) and (hi is None or d <= hi)]
    if len(idx) < 30:
        return None
    eq = daily[idx[0]:idx[-1] + 1]
    base = daily[idx[0] - 1] if idx[0] > 0 else 0.0
    dp = np.diff(np.r_[base, eq])
    yrs = len(idx) / 245.0
    pk = np.maximum.accumulate(np.r_[base, eq])[1:]
    mdd = float((eq - pk).min())
    sharpe = float(dp.mean() / dp.std() * np.sqrt(252)) if dp.std() > 0 else 0.0
    ann = float(dp.sum() / yrs)
    return {"sharpe": sharpe, "ann": ann, "mdd": mdd, "calmar": ann / -mdd if mdd < 0 else float("inf"), "total": float(dp.sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--variant", default="steady", choices=list(VARIANTS))
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days = D["days"]
    F = fl.day_features(D)
    VS = vhsi_by_session(days, load_vhsi())
    trig, g, tp, sl, f5 = VARIANTS[a.variant]
    base_sig = ds.signals(D, "fade", trig, 0.02, "all")
    if f5:
        base_sig = [(i, s) for i, s in base_sig if fl.keep(F, D, i, s, f5)]
    filters = (["none"] + [f"vmax_{x}" for x in (20, 22, 25, 28, 30, 35)] + [f"vmin_{x}" for x in (15, 18, 20)]
               + [f"vchg_{x}" for x in (10, 20, 30)] + [f"vpct_{x}" for x in (70, 80, 90)])
    print(f"地載・{'穩' if a.variant == 'steady' else '進'}＋VHSI（Sharpe：日、√252；金額 HK$，每點 50、注碼 1 = 1→2→4 張大期）\n")
    print("篩選       注碼  筆數 止蝕 ｜ Sharpe 全期 訓練 測試 ｜ 年化HK$萬 最大回撤HK$萬 Calmar ｜ 測試年化 測試回撤")
    rows = []
    for flt, mode in itertools.product(filters, ("eq", "inv", "inv2")):
        sig = [(i, s) for i, s in base_sig if keep(VS[D["sid"][i]], flt)]
        t = [x for x in mg.simulate_mg(D, sig, g, tp, sl_pts=sl) if x["reason"] != "open"]
        w = [weight(VS[x["sid"]], mode) for x in t]
        daily = daily_equity(D, t, w) * HKD
        al, tr, te = metrics(daily, days), metrics(daily, days, hi=ds.TRAIN_END), metrics(daily, days, lo="2024-01-01")
        nsl = sum(1 for x in t if x["reason"] == "sl")
        rows.append((flt, mode, len(t), nsl, al, tr, te))
        print(f"{flt:10s} {mode:4s} {len(t):4d} {nsl:3d}  ｜ {al['sharpe']:5.2f} {tr['sharpe']:5.2f} {te['sharpe']:5.2f} ｜ "
              f"{al['ann'] / 1e4:7.1f} {al['mdd'] / 1e4:9.1f} {al['calmar']:6.2f} ｜ {te['ann'] / 1e4:6.1f} {te['mdd'] / 1e4:7.1f}")
    best = sorted(rows, key=lambda r: r[5]["sharpe"], reverse=True)[:5]
    print("\n訓練期 Sharpe 最高 5 組 → 測試期：")
    for flt, mode, n, nsl, al, tr, te in best:
        print(f"  {flt} {mode}：訓練 {tr['sharpe']:.2f} → 測試 {te['sharpe']:.2f}（全期 {al['sharpe']:.2f}、年化 HK${al['ann']:,.0f}、回撤 HK${al['mdd']:,.0f}）")


if __name__ == "__main__":
    main()
