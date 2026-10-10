"""地載陣 × 金絲雀（烽燧）：燈色只決定「開不開新倉／開多大」，RSI 仍是入場方法；持倉中任何燈色都不平倉（手冊 §4：亮燈平倉已證偽）。

烽燧響應規則（依 CANARY_PLAYBOOK.md §8，先登記後測試；登記日期 2026-10-10；以下候選全數報告，不挑後隱藏）：
  K0 基準：不看燈。
  K1 雲垂同款：紅=不開新倉；深紅=不開新倉；黃=照做。（地載陣訊號只在當日有效，雲垂的「延後」= 不開）
  K2 深紅=不開新倉；紅=照做；黃=照做。
  K3 紅=半注；深紅=不開新倉；黃=照做。
  K4 黃=不開新倉；紅、深紅=照做。（對照：黃燈有沒有用）
口徑：燈色日 D = canary/canary_daily.csv 中日期早於恒指交易日 d 的最後一列（美股 D 收市在香港 d 09:00 之前，lag=1）；
空白燈色（假期／資料不足）= 綠。只用正式欄位 light／yellow，不用 trial_*。

組合：穩（1→2→3→4→5）、穩 60 分、進、進＋Nasdaq 各自套同一條規則，再找注碼組合（每組 0–4 份，1 份 = 開倉 1 張）
令 Sharpe ≥ 1 且 最大回撤 ≤ 年化；只用訓練期（2018-10 至 2023-12）挑，測試期（2024 起）只報告。
% 口徑：本金 = 滿倉張數 × 每張保證金 HK$15 萬 ＋ 訓練期最大回撤（不追加資金也不會斬倉的最低本金）。

用法：python3 research/hsi_futures_range/dizai_canary.py --json /tmp/hsimain.json
"""
import argparse, csv, functools, itertools, json, sys
from bisect import bisect_left
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dizai_cross as dc                                    # noqa: E402
import dizai_filters as fl                                  # noqa: E402
import dizai_martingale as mg                               # noqa: E402
import dizai_more as dm                                     # noqa: E402
import dizai_search as ds                                   # noqa: E402
import dizai_vhsi as dv                                     # noqa: E402
import rsi_avg_down as rad                                  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MARGIN = 150000
RULES = {"K0": {}, "K1": {"紅": 0, "深紅": 0}, "K2": {"深紅": 0}, "K3": {"紅": 0.5, "深紅": 0}, "K4": {"黃": 0}}
COMPS = {  # 名稱: (觸發, RSI 分 K, 加倉間距 ATR, 止賺, 止蝕, 5 日升跌篩選, Nasdaq 篩選, 每次加倉張數)
    "穩": ("confirm", 1, 0.75, 30, 1000, None, None, (1, 1, 1, 1)),
    "穩60": ("confirm", 60, 0.75, 30, 1000, None, None, (1, 2)),
    "進": ("cross", 1, 1.0, 150, 3000, "run5_3", None, (1, 2)),
    "進NQ": ("cross", 1, 1.0, 150, 1500, "run5_3", "oppo", (1, 2)),
}


def load_canary():
    rows = list(csv.DictReader(open(REPO / "canary" / "canary_daily.csv", encoding="utf-8")))
    return [r["date"] for r in rows], [(r["light"] or "綠", r["yellow"] == "1") for r in rows]


def light_for(cd, cl, day):
    k = bisect_left(cd, day) - 1                             # 日期嚴格早於 d 的最後一列
    return cl[k] if k >= 0 else ("綠", False)


def weight(rule, light):
    lt, yel = light
    w = 1.0
    if lt in rule:
        w = min(w, rule[lt])
    if yel and "黃" in rule:
        w = min(w, rule["黃"])
    return w


def run(D, F, nq, canary, name, rule):
    trig, tf, g, tp, sl, f5, nqf, al = COMPS[name]
    sig = dm.tf_signals(D, trig, tf)
    if f5:
        sig = [(i, s) for i, s in sig if fl.keep(F, D, i, s, f5)]
    if nqf:
        ft = dc.features(D, sig, nq)
        sig = [(i, s) for i, s in sig if dc.keep(ft, i, s, nqf)]
    w_of = {i: weight(rule, light_for(*canary, D["days"][D["sid"][i]])) for i, s in sig}
    sig = [(i, s) for i, s in sig if w_of[i] > 0]
    orig = mg.simulate_mg
    mg.simulate_mg = functools.partial(orig, add_lots=al)
    try:
        t = dm.run_seq(D, sig, g, tp, sl)
    finally:
        mg.simulate_mg = orig
    ws = [w_of[x["fills"][0][0] - 1] for x in t]
    return dv.daily_equity(D, t, ws) * 50, len(t), 1 + sum(al)


def pct(m, cap):
    return f"年化 {m['ann'] / cap:6.1%} 回撤 {m['mdd'] / cap:7.1%}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    a = ap.parse_args()
    D = ds.prepare(rad.clean(json.loads(Path(a.json).read_text())))
    days, F, nq, canary = D["days"], fl.day_features(D), dc.load_us("usatechidxusd"), load_canary()
    lights = [light_for(*canary, d) for d in days]
    print(f"恒指 {len(days)} 個交易日的燈色（lag=1）：" + "、".join(f"{k} {sum(1 for l in lights if l[0] == k)}" for k in ("綠", "走平", "紅", "深紅"))
          + f"；黃 {sum(1 for l in lights if l[1])}")
    eqs = {}
    print("\n各版本 × 響應規則（Sharpe 全期／訓練／測試；HK$ 以 1 份計）")
    for name in COMPS:
        for rk, rule in RULES.items():
            eq, n, ml = run(D, F, nq, canary, name, rule)
            eqs[name, rk] = (eq, ml)
            al, tr, te = dv.metrics(eq, days), dv.metrics(eq, days, hi=ds.TRAIN_END), dv.metrics(eq, days, lo="2024-01-01")
            print(f"  {name:4s} {rk} 筆{n:4d}｜Sharpe {al['sharpe']:5.2f}／{tr['sharpe']:5.2f}／{te['sharpe']:5.2f}"
                  f"｜年化 HK${al['ann'] / 1e4:5.1f}萬 回撤 HK${al['mdd'] / 1e4:6.1f}萬 年化÷回撤 {al['calmar']:.2f}")
    print("\n注碼組合（訓練期挑：Sharpe ≥ 1 且 回撤 ≤ 年化，取訓練期 Sharpe 最高；測試期只報告）")
    names = list(COMPS)
    for rk in RULES:
        best = None
        for w in itertools.product(range(5), repeat=len(names)):
            if not any(w):
                continue
            eq = sum(wi * eqs[n, rk][0] for wi, n in zip(w, names))
            tr = dv.metrics(eq, days, hi=ds.TRAIN_END)
            if tr["sharpe"] >= 1 and tr["calmar"] >= 1 and (best is None or tr["sharpe"] > best[0]):
                best = (tr["sharpe"], w, eq)
        if best is None:
            print(f"  {rk}：訓練期沒有組合達標")
            continue
        _, w, eq = best
        lots = sum(wi * eqs[n, rk][1] for wi, n in zip(w, names))
        tr, te, al = dv.metrics(eq, days, hi=ds.TRAIN_END), dv.metrics(eq, days, lo="2024-01-01"), dv.metrics(eq, days)
        cap = lots * MARGIN - tr["mdd"]
        mix = "＋".join(f"{n}×{wi}" for wi, n in zip(w, names) if wi)
        print(f"  {rk}：{mix}（滿倉最多 {lots} 張，本金 HK${cap / 1e4:.0f} 萬）")
        for lab, m in (("訓練", tr), ("測試", te), ("全期", al)):
            ok = "✅" if m["sharpe"] >= 1 and m["calmar"] >= 1 else "❌"
            print(f"      {lab} {ok} Sharpe {m['sharpe']:5.2f}｜{pct(m, cap)}｜年化÷回撤 {m['calmar']:.2f}")


if __name__ == "__main__":
    main()
