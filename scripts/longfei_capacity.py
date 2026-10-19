"""[R248] 🐉 龍飛陣：模擬倉成交套落「真倉戶口」重演——購買力變化、邊啲單因為購買力唔夠做唔到、邊種注碼最好。

使用者 10-20：「模擬倉加購買力變化。再測試喺真倉（包括用盡槓桿）嗰啲單會因為購買力不足而做唔到。調節最好嘅注碼。」

做法（只讀，唔落單）：
- 讀 GCS longfei/<產品>/latest.json 嘅模擬平倉紀錄（美股 ETF／個股；HSI 係期貨戶口，唔計）。
- 每筆換算成「每 1 蚊名義金額嘅回報」r = 扣費後盈虧 ÷（開倉價 × 股數 × 7.8）。
- 按開倉／平倉時間重演一個真倉戶口：起始權益 --capital（HK$），購買力 = 槓桿倍數 × 權益（富途證券保證金戶口 10-19 實測約 2 倍）。
  開倉時已用名義 + 新單 > 購買力 → 只可以開到剩低嗰啲（同真倉程式 _cap_open_qty 一樣）；一蚊都冇就「做唔到」。
- 比較幾種注碼：
  - 模擬原本金額（每單 US$100k／50k／30k）
  - 用盡槓桿（R235）：剩餘購買力 ÷ 未有倉嘅產品隻數（--slots）
  - 固定比例：每單 = f × 權益（f 由 0.1 到 2.0）
- 揀「最好」：回報 ÷ 最大回撤（MAR）最高，而且最大回撤唔超過 --max-dd（權益 %）。
- 樣本少（< 30 筆）一律寫明只供參考。

用法：python3 scripts/longfei_capacity.py --capital 400000 [--leverage 2] [--slots 2] [--max-dd 20] [--out 報告.md]
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from longfei_review import PRODUCTS, _gcs_cat, t_stat  # noqa: E402

HKT = timezone(timedelta(hours=8))
USD_HKD = 7.8
STOCKS = [p for p in PRODUCTS if p != "HSI"]
FRACTIONS = (0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0)


def _ts(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=HKT)
    except (TypeError, ValueError):
        return None


def load_trades(docs):
    """{產品: latest.json} → [{p, t_open, t_close, r, notional}]，按開倉時間排。"""
    out = []
    for p, doc in docs.items():
        for t in (doc or {}).get("trades") or []:
            if not isinstance(t, dict) or t.get("type") != "CLOSE":
                continue
            pnl = t.get("pnl_hkd_net") if isinstance(t.get("pnl_hkd_net"), (int, float)) else t.get("pnl_hkd_gross")
            entry, qty = t.get("entry"), t.get("qty")
            t0, t1 = _ts(t.get("opened_at")), _ts(t.get("ts"))
            if not all(isinstance(x, (int, float)) for x in (pnl, entry, qty)) or not (t0 and t1) or entry <= 0 or qty <= 0:
                continue
            n = entry * qty * USD_HKD
            out.append({"p": p, "t_open": t0, "t_close": t1, "r": pnl / n, "notional": n})
    return sorted(out, key=lambda x: x["t_open"])


def simulate(trades, capital, leverage, size_fn):
    """按時間重演；回傳結果 dict。size_fn(equity, available, n_open) → 想開幾多名義（HK$）。"""
    events = [(t["t_open"], 1, i) for i, t in enumerate(trades)] + [(t["t_close"], 0, i) for i, t in enumerate(trades)]
    events.sort(key=lambda e: (e[0], e[1]))           # 同一刻先平倉（釋放購買力）再開倉
    eq, peak, max_dd = capital, capital, 0.0
    open_n, used = {}, 0.0
    taken = capped = skipped = 0
    min_free, curve = None, []
    by_day = {}
    for when, kind, i in events:
        t = trades[i]
        if kind == 1:
            power = leverage * eq
            avail = power - used
            want = size_fn(eq, avail, len(open_n))
            n = min(want, max(avail, 0.0))
            if n <= 0:
                skipped += 1
                continue
            if n < want - 1e-6:
                capped += 1
            taken += 1
            open_n[i] = n
            used += n
            free = power - used
            min_free = free if min_free is None else min(min_free, free)
        elif i in open_n:
            n = open_n.pop(i)
            used -= n
            pnl = t["r"] * n
            eq += pnl
            day = when.astimezone(HKT).date().isoformat()
            by_day[day] = by_day.get(day, 0.0) + pnl
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)
            curve.append((when, eq, leverage * eq - used))
    return {"equity": eq, "ret": eq / capital - 1, "max_dd": max_dd, "taken": taken, "capped": capped,
            "skipped": skipped, "min_free": min_free, "by_day": by_day, "curve": curve}


def run_all(trades, capital, leverage, slots):
    """逐種注碼重演。「模擬原本金額」用每筆自己嘅模擬名義（按開倉次序）。"""
    orig = iter([t["notional"] for t in trades])        # trades 已按開倉時間排，同開倉事件次序一致
    plans = [("模擬原本金額（每單 US$100k／50k／30k）", lambda eq, av, k: next(orig, 0.0)),
             (f"用盡槓桿（剩餘購買力 ÷ {slots} 隻未有倉）", lambda eq, av, k: av / max(slots - k, 1))]
    plans += [(f"固定比例：每單 {f:g} × 權益", (lambda f: lambda eq, av, k: f * eq)(f)) for f in FRACTIONS]
    return [(name, simulate(trades, capital, leverage, fn)) for name, fn in plans]


def kelly(trades):
    rs = [t["r"] for t in trades]
    if len(rs) < 2:
        return None
    m = sum(rs) / len(rs)
    var = sum((x - m) ** 2 for x in rs) / (len(rs) - 1)
    return m / var if var > 0 else None


def report(trades, capital, leverage, slots, max_dd_cap):
    n = len(trades)
    L = [f"# 🐉 龍飛陣：模擬成交套落真倉戶口重演（{datetime.now(HKT):%Y-%m-%d %H:%M} HKT）\n",
         f"起始權益 HK${capital:,.0f}；購買力 = {leverage:g} × 權益；美股 {len({t['p'] for t in trades})} 隻、模擬平倉 {n} 筆"
         f"（HSI 係期貨戶口唔計）。按開倉／平倉時間重演，同一刻先平後開。\n"]
    if n < 30:
        L.append(f"> ⚠ 樣本得 {n} 筆（< 30），以下只供參考，唔好據此改真倉注碼。\n")
    if not n:
        return "\n".join(L + ["未有模擬平倉紀錄。"])
    res = run_all(trades, capital, leverage, slots)
    L += ["| 注碼 | 期末權益 | 回報 | 最大回撤 | MAR | 開到 | 購買力唔夠減細 | 購買力唔夠做唔到 | 最少剩餘購買力（HK$） |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    best = None
    for name, r in res:
        mar = r["ret"] / r["max_dd"] if r["max_dd"] > 0 else (math.inf if r["ret"] > 0 else None)
        L.append(f"| {name} | HK${r['equity']:,.0f} | {r['ret']:+.1%} | {r['max_dd']:.1%} | "
                 f"{'—' if mar is None else ('∞' if mar == math.inf else f'{mar:.2f}')} | {r['taken']} | {r['capped']} | {r['skipped']} | "
                 f"{'—' if r['min_free'] is None else format(r['min_free'], ',.0f')} |")
        if r["max_dd"] * 100 <= max_dd_cap and r["ret"] > 0 and mar is not None:
            if best is None or mar > best[1]:
                best = (name, mar, r)
    k = kelly(trades)
    rs = [t["r"] for t in trades]
    tt = t_stat(rs)
    L.append("")
    L.append(f"每筆回報（按名義）：平均 {sum(rs) / n:+.3%}、t 值 {'—' if tt is None else f'{tt:.2f}'}；"
             f"凱利比例（平均 ÷ 方差）{'—' if k is None else f'{k:.2f} × 權益'}（樣本少時凱利會大幅高估，實際要用一半或以下）。\n")
    edge = n >= 30 and tt is not None and tt >= 1
    if not edge:
        L.append(f"**未有統計上嘅優勢（{n} 筆、t {'—' if tt is None else f'{tt:.2f}'}，要 ≥ 30 筆而且 t ≥ 1 先揀注碼）**："
                 "邊種注碼「最好」只係運氣。建議真倉暫時用細注碼（例如每單 0.1–0.2 × 權益，差唔多全部單都做得到），"
                 "等模擬有優勢先加大。下面只係按 MAR 排出嚟嘅參考。")
    if best:
        L.append(f"**{'建議注碼' if edge else '參考（唔係建議）'}（最大回撤 ≤ {max_dd_cap:g}% 入面 MAR 最高）：{best[0]}**，"
                 f"回報 {best[2]['ret']:+.1%}、"
                 f"最大回撤 {best[2]['max_dd']:.1%}。")
    else:
        L.append(f"**冇一種注碼喺最大回撤 ≤ {max_dd_cap:g}% 之下賺錢**：而家模擬成交本身未有正期望，任何注碼都只係放大蝕損；"
                 "應該先改進策略，唔係加大注碼。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, required=True, help="假設真倉戶口起始權益（HK$）")
    ap.add_argument("--leverage", type=float, default=2.0, help="購買力 ÷ 權益（富途 10-19 實測約 2）")
    ap.add_argument("--slots", type=int, default=2, help="用盡槓桿模式要分幾隻（真倉產品數）")
    ap.add_argument("--max-dd", type=float, default=20.0, help="揀注碼時容許嘅最大回撤（權益 %）")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    docs = {p: _gcs_cat(f"longfei/{p}/latest.json") for p in STOCKS}
    text = report(load_trades({p: d for p, d in docs.items() if isinstance(d, dict)}),
                  a.capital, a.leverage, a.slots, a.max_dd)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
