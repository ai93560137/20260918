"""實倉／紙上 vs 回測 偏離監控（strategy divergence）。

每個有回測期望的策略，算「上線後的實際表現落在回測分佈的哪裡」，用預先登記的門檻給燈號：

  ⚪ 樣本不足（已完結交易 < 5 筆）或沒有登記回測期望 → 只列數字，不判
  🟢 每筆平均的 z ≥ −1 且 實際最大回撤 < 0.75 × 回測最大回撤
  🟡 z < −1 或 回撤 ≥ 0.75 × 回測回撤 → 建議倉位減半
  🔴 z < −2 或 回撤 ≥ 1.0 × 回測回撤 → 建議停止、重審

  z = (實際每筆平均 − 回測每筆平均) ÷ (回測每筆標準差 ÷ √n)

門檻在這裡寫死，不按結果調。只用標準庫。期望值登記在 research/divergence/expectations.json；
沒有登記的實倉策略會被列成「未登記回測期望」——那本身就是一個發現。

資料來源：
  * 🐍 蛇蟠陣：VCP 分支 journal/forward_test.csv（紙上權益逐日）、journal/log.csv（成交）
  * 🌬️ 風揚陣方向一：research/hsi_futures_range/PAPER_TRADING.md「方向一真實交易紀錄」表
  * ☁️ 雲垂陣：research/divergence/ledger_yunchui.csv（每個結算週期一列，由該陣或總指揮填）
  * ✋ 人手：富途風險快照（gcp_agent.py cat --object futu/risk/latest.json）的 stop_use，選用
  * 智能諸葛亮 XAUUSD：GCS logs/trade_ledger.json（main.py R171 在 MT5 balance 變動時寫），
    workflow 用 gcp_agent.py cat 抓成 research/divergence/xau_trade_ledger.json；只拿 kind == "trade" 的列

用法：
    python3 scripts/strategy_divergence.py --journal <目錄含 forward_test.csv> [--futu latest.json] --out research/divergence
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from datetime import date
from pathlib import Path

THRESH = {"amber_z": -1.0, "red_z": -2.0, "amber_dd": 0.75, "red_dd": 1.0, "min_n": 5}


def light(z: float | None, dd_ratio: float | None, n: int, has_bt: bool) -> tuple[str, str]:
    if not has_bt:
        return "⚪", "未登記回測期望，無法比較"
    if n < THRESH["min_n"]:
        return "⚪", f"已完結 {n} 筆，< {THRESH['min_n']} 筆不判"
    reasons = []
    level = 0
    if z is not None:
        if z < THRESH["red_z"]:
            level, reasons = 2, reasons + [f"z = {z:.2f} < {THRESH['red_z']}"]
        elif z < THRESH["amber_z"]:
            level, reasons = max(level, 1), reasons + [f"z = {z:.2f} < {THRESH['amber_z']}"]
    if dd_ratio is not None:
        if dd_ratio >= THRESH["red_dd"]:
            level, reasons = 2, reasons + [f"回撤已達回測最大回撤的 {dd_ratio:.0%}"]
        elif dd_ratio >= THRESH["amber_dd"]:
            level, reasons = max(level, 1), reasons + [f"回撤已達回測最大回撤的 {dd_ratio:.0%}"]
    if level == 2:
        return "🔴", "；".join(reasons) + " → 建議停止並重審"
    if level == 1:
        return "🟡", "；".join(reasons) + " → 建議倉位減半"
    return "🟢", "在回測分佈內"


def zscore(live: list[float], bt_mean: float | None, bt_std: float | None) -> float | None:
    n = len(live)
    if n == 0 or bt_mean is None or not bt_std:
        return None
    return (statistics.fmean(live) - bt_mean) / (bt_std / math.sqrt(n))


def max_drawdown(equity: list[float]) -> tuple[float, float]:
    """回傳 (最大回撤金額, 最大回撤比例)。"""
    peak, dd_amt, dd_pct = -math.inf, 0.0, 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd_amt = max(dd_amt, peak - e)
            dd_pct = max(dd_pct, (peak - e) / peak)
    return dd_amt, dd_pct


# ---------------------------------------------------------------- 來源：蛇蟠陣 journal
def read_snake(journal: Path) -> dict:
    rows = []
    p = journal / "forward_test.csv"
    if not p.exists():
        return {"error": f"{p} 不存在"}
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if not rows:
        return {"error": "forward_test.csv 沒有資料"}
    equity = [float(r["equity"]) for r in rows]
    realized = [float(r["realized_cum"]) for r in rows]
    # 每筆已完結交易 = realized_cum 的變動（含手續費差）
    trades = []
    for i in range(1, len(realized)):
        d = realized[i] - realized[i - 1]
        if abs(d) > 1e-9:
            trades.append(d)
    dd_amt, dd_pct = max_drawdown(equity)
    return {
        "first": rows[0]["date"], "last": rows[-1]["date"], "days": len(rows),
        "equity_start": equity[0], "equity_last": equity[-1],
        "open_pnl": float(rows[-1]["open_pnl"]), "realized_cum": realized[-1], "fees_cum": float(rows[-1]["fees_cum"]),
        "trades": trades, "dd_amt": dd_amt, "dd_pct": dd_pct,
        "pos": rows[-1]["pos"], "instrument": rows[-1]["instrument"],
    }


# ---------------------------------------------------------------- 來源：風揚陣方向一表
def read_strangle(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    m = re.search(r"## 方向一真實交易紀錄.*?(?=\n## |\Z)", text, re.S)
    if not m:
        return {"error": "找不到「方向一真實交易紀錄」段"}
    weeks, settled = [], []
    for ln in m.group(0).splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 12 or not cells[0].isdigit():
            continue
        net = cells[11].replace(",", "").replace("*", "").replace("+", "")
        weeks.append(cells[0])
        try:
            settled.append(float(net))
        except ValueError:
            pass
    cum, eq = 0.0, [0.0]
    for x in settled:
        cum += x
        eq.append(cum)
    dd_amt = max(max(eq[:i + 1]) - eq[i] for i in range(len(eq))) if eq else 0.0
    return {"weeks_opened": len(weeks), "settled": settled, "dd_pts": dd_amt}


# ---------------------------------------------------------------- 來源：雲垂陣結算帳本
def read_ledger_csv(path: Path, instrument: str, unit: str, nominal: float | None) -> dict:
    """每個已結算週期一列：net_pnl_hkd 有值才算完結。unit 含「%」時換成 % 名義。"""
    if not path.exists():
        return {"error": f"{path} 不存在"}
    opened, settled = 0, []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("instrument") or "").strip().upper() != instrument.upper():
                continue
            opened += 1
            raw = (r.get("net_pnl_hkd") or "").replace(",", "").strip()
            if not raw:
                continue
            v = float(raw)
            if "%" in unit:
                nom = float((r.get("nominal_hkd") or "").replace(",", "") or nominal or 0)
                if nom <= 0:
                    continue
                v = v / nom * 100.0
            settled.append(v)
    cum, eq = 0.0, [0.0]
    for x in settled:
        cum += x
        eq.append(cum)
    dd = max(max(eq[:i + 1]) - eq[i] for i in range(len(eq)))
    return {"opened": opened, "settled": settled, "dd": dd}


# ---------------------------------------------------------------- 來源：XAUUSD 已實現帳本
def read_xau_ledger(path: Path | None) -> dict:
    if not path or not path.exists():
        return {"error": "沒有 xau_trade_ledger.json（main.py R171 未部署、workflow 沒有 GCP_SA_KEY、或尚無平倉）"}
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        return {"error": "帳本格式不是 list"}
    trades = [r for r in rows if r.get("kind") == "trade" and r.get("delta") is not None]
    trades.sort(key=lambda r: r.get("t") or "")
    deltas = [float(r["delta"]) for r in trades]
    equities = [float(r["equity"]) for r in trades if r.get("equity") is not None]
    # 回撤用 balance 路徑（已實現），相對高水位
    bal = [float(r["balance"]) for r in trades if r.get("balance") is not None]
    dd_amt, dd_pct = max_drawdown(bal) if bal else (0.0, 0.0)
    return {"n_rows": len(rows), "trades": deltas, "wins": sum(1 for d in deltas if d > 0),
            "first": trades[0]["t"] if trades else None, "last": trades[-1]["t"] if trades else None,
            "dd_amt": dd_amt, "dd_pct": dd_pct, "last_equity": equities[-1] if equities else None,
            "other_kinds": {k: sum(1 for r in rows if r.get("kind") == k) for k in ("transfer", "credit")}}


def win_rate_z(wins: int, n: int, p0: float | None) -> float | None:
    if n == 0 or p0 is None or not 0 < p0 < 1:
        return None
    return (wins / n - p0) / math.sqrt(p0 * (1 - p0) / n)


# ---------------------------------------------------------------- 來源：富途快照
def read_futu(path: Path | None) -> dict | None:
    if not path or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    m = data.get("metrics", {})
    return {"run_hkt": data.get("run_hkt"), "stop_use": m.get("stop_use", {}), "cushion": m.get("cushion"),
            "equity": m.get("futu_equity"), "maintenance": m.get("maintenance_margin")}


# ---------------------------------------------------------------- 報告
def fmt(x, d=0, unit=""):
    if x is None:
        return "—"
    return f"{x:,.{d}f}{unit}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--journal", type=Path, help="蛇蟠陣 journal/ 目錄（VCP 分支抽出）")
    ap.add_argument("--paper", type=Path, default=Path("research/hsi_futures_range/PAPER_TRADING.md"))
    ap.add_argument("--futu", type=Path, help="futu/risk/latest.json（選用）")
    ap.add_argument("--xau-ledger", type=Path, default=Path("research/divergence/xau_trade_ledger.json"),
                    help="XAUUSD 已實現帳本（GCS logs/trade_ledger.json 抓下來的檔）")
    ap.add_argument("--expectations", type=Path, default=Path("research/divergence/expectations.json"))
    ap.add_argument("--out", type=Path, default=Path("research/divergence"))
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    exp = json.loads(a.expectations.read_text(encoding="utf-8"))
    futu = read_futu(a.futu)

    L = [f"# 實倉／紙上 vs 回測 偏離監控（更新 {a.as_of}）", "",
         "> 每個策略：實際每筆平均相對回測分佈的 z 值、實際最大回撤相對回測最大回撤的比例。",
         f"> 燈號門檻預先登記在 `scripts/strategy_divergence.py`：🟡 z < {THRESH['amber_z']} 或回撤 ≥ {THRESH['amber_dd']:.0%} 回測回撤 → 減半；"
         f"🔴 z < {THRESH['red_z']} 或回撤 ≥ {THRESH['red_dd']:.0%} → 停止重審；已完結 < {THRESH['min_n']} 筆 ⚪ 不判。",
         "> 期望值登記在 `research/divergence/expectations.json`；燈號是建議，落單仍由各陣與總指揮決定。", "",
         "| 策略 | 燈 | 已完結 | 實際每筆平均 | 回測每筆平均 ± 標準差 | z | 實際最大回撤 | 回測最大回撤 | 說明 |",
         "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    details: list[str] = []

    # 蛇蟠陣
    e = exp["snake_hsi"]
    s = read_snake(a.journal) if a.journal else {"error": "未提供 --journal"}
    if "error" in s:
        L.append(f"| {e['name']} | ⚪ | — | — | {fmt(e['bt_mean'])} ± {fmt(e['bt_std'])} {e['unit']} | — | — | {e['bt_max_dd_pct']}% | {s['error']} |")
    else:
        z = zscore(s["trades"], e["bt_mean"], e["bt_std"])
        dd_ratio = (s["dd_pct"] * 100) / e["bt_max_dd_pct"] if e.get("bt_max_dd_pct") else None
        lt, why = light(z, dd_ratio, len(s["trades"]), True)
        mean = statistics.fmean(s["trades"]) if s["trades"] else None
        L.append(f"| {e['name']} | {lt} | {len(s['trades'])} | {fmt(mean)} {e['unit']} | {fmt(e['bt_mean'])} ± {fmt(e['bt_std'])} {e['unit']} | "
                 f"{fmt(z, 2)} | {s['dd_pct']:.1%}（{fmt(s['dd_amt'])}） | {e['bt_max_dd_pct']}% | {why} |")
        details += [f"### {e['name']}", "",
                    f"- 紙上權益 {s['first']} → {s['last']}（{s['days']} 個交易日）：{fmt(s['equity_start'])} → {fmt(s['equity_last'])} {e['unit']}；"
                    f"已實現 {fmt(s['realized_cum'])}，未實現 {fmt(s['open_pnl'])}，手續費 {fmt(s['fees_cum'])}；現倉 {s['instrument']} {s['pos']}。",
                    f"- 已完結交易（由 realized_cum 變動推得）：{', '.join(fmt(t) for t in s['trades']) or '尚無'}。",
                    f"- 回測來源：{e['bt_source']}（n = {e['bt_n']}，t = {e.get('bt_t', '—')}）。",
                    f"- 另一條預先登記的重審條件：{e['extra_rule']}。", ""]

    # 風揚陣方向一
    e = exp["strangle_1sigma"]
    st = read_strangle(a.paper) if a.paper.exists() else {"error": f"{a.paper} 不存在"}
    bt_std = e.get("bt_std") or (e["bt_mean"] / e["bt_t"] * math.sqrt(e["bt_n"]) if e.get("bt_t") else None)
    if "error" in st:
        L.append(f"| {e['name']} | ⚪ | — | — | {fmt(e['bt_mean'])} ± {fmt(bt_std)} {e['unit']} | — | — | {fmt(e['bt_max_dd'])} {e['unit']} | {st['error']} |")
    else:
        z = zscore(st["settled"], e["bt_mean"], bt_std)
        dd_ratio = st["dd_pts"] / e["bt_max_dd"] if e.get("bt_max_dd") else None
        lt, why = light(z, dd_ratio, len(st["settled"]), True)
        mean = statistics.fmean(st["settled"]) if st["settled"] else None
        L.append(f"| {e['name']} | {lt} | {len(st['settled'])}（開倉 {st['weeks_opened']} 週） | {fmt(mean)} {e['unit']} | "
                 f"{fmt(e['bt_mean'])} ± {fmt(bt_std)} {e['unit']} | {fmt(z, 2)} | {fmt(st['dd_pts'])} {e['unit']} | {fmt(e['bt_max_dd'])} {e['unit']} | {why} |")
        details += [f"### {e['name']}", "",
                    f"- 已開倉 {st['weeks_opened']} 週，已結算 {len(st['settled'])} 週：{', '.join(fmt(x) for x in st['settled']) or '尚無'}。",
                    f"- 回測來源：{e['bt_source']}（n = {e['bt_n']} 週，中位 {e.get('bt_median', '—')} 點，t = {e.get('bt_t')}；標準差由 t 值反推）。", ""]

    # 雲垂陣：兩個跨式，各自對結算帳本
    for key in ("yunchui_hsi_straddle", "yunchui_mes_straddle"):
        e = exp[key]
        bt_std = e.get("bt_std") or (e["bt_mean"] / e["bt_t"] * math.sqrt(e["bt_n"]) if e.get("bt_t") else None)
        lg = read_ledger_csv(Path(e["live"]["path"]), e["live"]["filter_instrument"], e["unit"], e.get("nominal_hkd"))
        unit = e["unit"].split("／")[0]
        bt_txt = f"{fmt(e['bt_mean'], 2 if '%' in unit else 0)} ± {fmt(bt_std, 2 if '%' in unit else 0)} {unit}"
        dd_bt = e.get("bt_max_dd")
        if "error" in lg:
            L.append(f"| {e['name']} | ⚪ | — | — | {bt_txt} | — | — | {fmt(dd_bt)} | {lg['error']} |")
            continue
        z = zscore(lg["settled"], e["bt_mean"], bt_std)
        dd_ratio = lg["dd"] / dd_bt if dd_bt else None
        lt, why = light(z, dd_ratio, len(lg["settled"]), True)
        mean = statistics.fmean(lg["settled"]) if lg["settled"] else None
        d = 2 if "%" in unit else 0
        L.append(f"| {e['name']} | {lt} | {len(lg['settled'])}（開倉 {lg['opened']} 期） | {fmt(mean, d)} {unit} | {bt_txt} | "
                 f"{fmt(z, 2)} | {fmt(lg['dd'], d)} {unit} | {fmt(dd_bt)} | {why} |")
        details += [f"### {e['name']}", "",
                    f"- 結算帳本 `{e['live']['path']}`：開倉 {lg['opened']} 期、已結算 {len(lg['settled'])} 期"
                    f"：{', '.join(fmt(x, d) for x in lg['settled']) or '尚無'}。",
                    f"- 回測來源：{e['bt_source']}（n = {e['bt_n']}，勝率 {e.get('bt_win_rate', 0):.0%}，最壞月 {fmt(e.get('bt_worst_month'), d)}）。",
                    f"- 現行規則：{e.get('live_rules', '—')}。", ""]

    # 人手：沒有登記回測期望
    e = exp["manual_es_put"]
    extra = ""
    if futu:
        uses = {k: v for k, v in futu["stop_use"].items() if k in e.get("stop_use_keys", [])}
        if uses:
            extra = "；止損線已用 " + "、".join(f"{k} {v:.0%}" for k, v in uses.items()) + f"（富途快照 {futu['run_hkt']}）"
    L.append(f"| {e['name']} | ⚪ | — | — | 未登記 | — | — | — | {e['note']}{extra} |")

    # XAUUSD：已實現帳本 vs 回測勝率／回撤
    e = exp["xauusd_v12"]
    xl = read_xau_ledger(a.xau_ledger)
    bt_txt = f"勝率 {e['bt_win_rate']:.0%}、獲利因子 {e['bt_pf']}、{e['bt_n']} 筆"
    if "error" in xl:
        L.append(f"| {e['name']} | ⚪ | — | — | {bt_txt} | — | — | {e['bt_max_dd_pct']}% | {xl['error']} |")
    else:
        n = len(xl["trades"])
        z = win_rate_z(xl["wins"], n, e["bt_win_rate"])
        dd_ratio = (xl["dd_pct"] * 100) / e["bt_max_dd_pct"] if e.get("bt_max_dd_pct") else None
        lt, why = light(z, dd_ratio, n, True)
        mean = statistics.fmean(xl["trades"]) if xl["trades"] else None
        wr = f"（勝率 {xl['wins']}/{n}）" if n else ""
        L.append(f"| {e['name']} | {lt} | {n} | {fmt(mean, 2)} {wr} | {bt_txt} | {fmt(z, 2)}（勝率 z） | "
                 f"{xl['dd_pct']:.1%}（{fmt(xl['dd_amt'], 2)}） | {e['bt_max_dd_pct']}% | {why} |")
        details += [f"### {e['name']}", "",
                    f"- 帳本 {xl['n_rows']} 列，其中已實現交易 {n} 筆（{xl['first']} → {xl['last']}）；出入金 {xl['other_kinds']['transfer']} 列、"
                    f"credit 變動 {xl['other_kinds']['credit']} 列不計。",
                    f"- 回測來源：{e['bt_source']}；{e.get('note', '')}。", ""]

    L += ["", *details,
          "## 這張表的用途", "",
          "- 它不證明策略有效或無效；它只在實際結果開始偏離回測分佈時，按事先寫好的門檻提醒減倉或停止。",
          "- 樣本少時 z 值不可靠，所以 < 5 筆一律 ⚪。這段期間監控的價值在機制本身，不在數字。",
          "- 「未登記回測期望」的實倉策略，應補一份回測（哪怕粗糙）登記到 `expectations.json`，否則永遠不會亮燈。", ""]
    (a.out / "DIVERGENCE.md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {a.out / 'DIVERGENCE.md'}")


if __name__ == "__main__":
    main()
