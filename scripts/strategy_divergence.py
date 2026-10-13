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
  * ⛰️ 地載陣（紙上）：GCS dizai/<衡|缺|突破V>/HK.HSI_FRONT.json 與 dizai/forward/HK.HSI_FRONT.json 的 variants.<穩60|進NQ>，
    trades[].pnl（點，已扣成本）、exit_tk（香港時間）。workflow 抓成 --dizai-raw 目錄，本腳本累積歸檔到
    research/divergence/dizai_trades.json（GCS 只留最近 DIZAI_TRADES_KEEP 筆）。回測期望是「點／月」，所以
    按 exit_tk 月份加總，只計「start 之後第一個完整月到上個月」（start 唔係 1 號，嗰個月唔計入 z，但計入累計與回撤），冇成交的月份當 0；合＝各成份按 weights 加權。
    z、⚪ 門檻同上，但 n 是完整月數；回撤用逐筆累計點數對回測最大回撤（取絕對值）。
  * 🐤 金絲雀（風險預報，不是交易）：canary/posthoc_log.csv（每個燈色日一列 📐 後驗倍率），
    按燈分組對比 canary/POSTHOC_EXPECT.md 的歷史期望。燈號另有一套（2026-10-13 預先登記）：
      相鄰燈色日的 5 日窗口重疊，有效樣本 n_eff = n ÷ 5；n_eff < 5 → ⚪ 不判
      燈亮的組（黃／紅／深紅）：z < −1 🟡「訊號比歷史弱」；z < −2 🔴「建議重審燈號」
      綠燈組：z > +1 🟡「綠燈期波動比歷史高（漏報）」；z > +2 🔴「建議重審燈號」

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


# ---------------------------------------------------------------- 來源：地載陣紙上狀態
def dizai_specs(live: dict) -> dict[str, tuple[str, str | None]]:
    """live 規格 → {成份名: (gcs 物件, variant)}。dizai_paper_state 一個成份；combo 多個（"路徑#variant"）。"""
    if live.get("type") == "dizai_paper_state":
        name = live.get("variant") or live["gcs"].split("/")[1]
        return {name: (live["gcs"], live.get("variant"))}
    out = {}
    for name, ref in (live.get("components") or {}).items():
        path, _, var = ref.partition("#")
        out[name] = (path, var or None)
    return out


def raw_name(gcs: str) -> str:
    return gcs.replace("/", "__")


def merge_dizai(archive: dict, raw_dir: Path | None, specs: dict[str, tuple[str, str | None]]) -> dict:
    """把 GCS 狀態檔（raw_dir/<路徑以 __ 連接>）嘅 trades 併入 archive，按整筆內容去重。"""
    if not raw_dir or not raw_dir.exists():
        return archive
    for name, (gcs, var) in specs.items():
        p = raw_dir / raw_name(gcs)
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        src = ((doc.get("variants") or {}).get(var) or {}) if var else doc
        slot = archive.setdefault(name, {"start": None, "trades": []})
        slot["start"] = doc.get("start") or slot.get("start")
        seen = {json.dumps(t, sort_keys=True, ensure_ascii=False) for t in slot["trades"]}
        for t in src.get("trades") or []:
            k = json.dumps(t, sort_keys=True, ensure_ascii=False)
            if isinstance(t, dict) and k not in seen:
                seen.add(k)
                slot["trades"].append(t)
        slot["trades"].sort(key=lambda t: str(t.get("exit_tk") or ""))
    return archive


def dizai_monthly(archive: dict, weights: dict[str, float], as_of: date,
                  pnl_key: str = "pnl", time_key: str = "exit_tk") -> dict:
    """完整月份嘅加權點數（start 月到上個月，冇成交當 0）、逐筆累計回撤、虧損筆數。"""
    starts = [archive[c]["start"] for c in weights if c in archive and archive[c].get("start")]
    if not starts:
        return {"error": "未有紙上狀態（GCS 讀唔到或未歸檔）"}
    y, m = map(int, min(starts)[:7].split("-"))
    if min(starts)[8:10] not in ("", "01"):              # 開始月份唔完整，唔同整月回測比；由下個月起計
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    months = []
    while (y, m) < (as_of.year, as_of.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    by_month = {k: 0.0 for k in months}
    path, losses, n_trades = [], 0, 0
    for c, w in weights.items():
        for t in (archive.get(c) or {}).get("trades") or []:
            v, ts = t.get(pnl_key), str(t.get(time_key) or "")
            if v is None or not ts:
                continue
            n_trades += 1
            losses += float(v) < 0
            path.append((ts, float(v) * w))
            if ts[:7] in by_month:
                by_month[ts[:7]] += float(v) * w
    cum, eq = 0.0, [0.0]
    for _, v in sorted(path):
        cum += v
        eq.append(cum)
    dd = max(max(eq[:i + 1]) - eq[i] for i in range(len(eq)))
    return {"months": months, "monthly": [by_month[k] for k in months], "n_trades": n_trades,
            "losses": losses, "dd": dd, "cum": cum, "start": min(starts)}


# ---------------------------------------------------------------- 來源：富途快照
def read_futu(path: Path | None) -> dict | None:
    if not path or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    m = data.get("metrics", {})
    return {"run_hkt": data.get("run_hkt"), "stop_use": m.get("stop_use", {}), "cushion": m.get("cushion"),
            "equity": m.get("futu_equity"), "maintenance": m.get("maintenance_margin")}


# ---------------------------------------------------------------- 報告
CANARY_MIN_NEFF = 5


def read_canary(path: Path, state_col: str, value_col: str) -> dict:
    if not path.exists():
        return {"error": f"{path} 不存在"}
    by: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            st, v = r.get(state_col, ""), r.get(value_col, "")
            if not st or not v:
                continue
            by.setdefault(st, []).append(float(v))
    return {"by_state": by}


def canary_light(state: str, z: float | None, n_eff: float) -> tuple[str, str]:
    if n_eff < CANARY_MIN_NEFF or z is None:
        return "⚪", f"有效樣本 {n_eff:.1f} < {CANARY_MIN_NEFF} 不判"
    if state == "綠":
        if z > 2:
            return "🔴", f"z = {z:.2f} > 2：綠燈期波動遠高於歷史（漏報）→ 建議重審燈號"
        if z > 1:
            return "🟡", f"z = {z:.2f} > 1：綠燈期波動比歷史高，留意"
    else:
        if z < -2:
            return "🔴", f"z = {z:.2f} < −2：亮燈後波動遠低於歷史（訊號變弱）→ 建議重審燈號"
        if z < -1:
            return "🟡", f"z = {z:.2f} < −1：亮燈後波動比歷史低，留意"
    return "🟢", "在歷史分佈內"


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
    ap.add_argument("--dizai-raw", type=Path, help="地載陣 GCS 狀態檔目錄（檔名＝物件路徑以 __ 連接）")
    ap.add_argument("--dizai-archive", type=Path, default=Path("research/divergence/dizai_trades.json"))
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

    # 地載陣：紙上成交按月加總 vs 回測「點／月」
    dz_keys = [k for k, v in exp.items() if isinstance(v, dict) and str((v.get("live") or {}).get("type", "")).startswith("dizai_paper")]
    if dz_keys:
        archive = json.loads(a.dizai_archive.read_text(encoding="utf-8")) if a.dizai_archive.exists() else {}
        all_specs: dict = {}
        for k in dz_keys:
            all_specs.update(dizai_specs(exp[k]["live"]))
        archive = merge_dizai(archive, a.dizai_raw, all_specs)
        if a.dizai_raw:
            a.dizai_archive.write_text(json.dumps(archive, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        for k in dz_keys:
            e = exp[k]
            live = e["live"]
            weights = e.get("weights") or {n: 1.0 for n in dizai_specs(live)}
            unit = "點／月"
            bt_txt = f"{fmt(e['bt_mean'], 1)} ± {fmt(e['bt_std'], 1)} {unit}"
            dd_bt = abs(e["bt_max_dd"]) if e.get("bt_max_dd") is not None else None
            dm = dizai_monthly(archive, weights, a.as_of, live.get("pnl_key", "pnl"), live.get("time_key", "exit_tk"))
            if "error" in dm:
                L.append(f"| {e['name']} | ⚪ | — | — | {bt_txt} | — | — | {fmt(dd_bt)} 點 | {dm['error']} |")
                continue
            n = len(dm["monthly"])
            z = zscore(dm["monthly"], e["bt_mean"], e["bt_std"])
            lt, why = light(z, dm["dd"] / dd_bt if dd_bt else None, n, True)
            if n < THRESH["min_n"]:
                why = f"完整月 {n} 個，< {THRESH['min_n']} 個不判（紙上由 {dm['start']} 起，已平倉 {dm['n_trades']} 筆）"
            mean = statistics.fmean(dm["monthly"]) if dm["monthly"] else None
            L.append(f"| {e['name']} | {lt} | {n} 個月（{dm['n_trades']} 筆） | {fmt(mean, 1)} {unit} | {bt_txt} | {fmt(z, 2)} | "
                     f"{fmt(dm['dd'])} 點 | {fmt(dd_bt)} 點 | {why} |")
            details += [f"### {e['name']}", "",
                        f"- 紙上由 {dm['start']} 起；完整月份：{', '.join(f'{mm} {fmt(v)}' for mm, v in zip(dm['months'], dm['monthly'])) or '尚無'}；"
                        f"累計 {fmt(dm['cum'])} 點，已平倉 {dm['n_trades']} 筆（虧損 {dm['losses']} 筆）。"
                        + (f" 權重：{'、'.join(f'{c}×{w:g}' for c, w in weights.items())}。" if len(weights) > 1 else ""),
                        f"- 回測來源：{e['bt_source']}（n = {e['bt_n']} 個月，月勝率 {e.get('bt_win_rate', 0):.0%}，最差月 {fmt(e.get('bt_worst_month'))} 點）。",
                        f"- 備註：{e.get('note', '—')}", ""]

    # 金絲雀：風險預報，按燈分組（與交易策略分開一張表）
    if "canary_posthoc" in exp:
        e = exp["canary_posthoc"]
        cz = read_canary(Path(e["live"]["path"]), e["live"]["state_col"], e["live"]["value_col"])
        C = ["", f"## {e['name']}", "",
             f"> 風險預報不是交易，燈號另一套（`scripts/strategy_divergence.py` 檔頭）。歷史期望：{e['bt_source']}，樣本 {e['bt_sample']}；"
             f"相鄰燈色日窗口重疊，z 用有效樣本 n ÷ {e['overlap_days']}。", "",
             "| 燈 | 燈號 | 前向日數 | 有效樣本 | 前向倍率平均 | 歷史平均 ± 標準差 | z | 說明 |",
             "|---|---|---:|---:|---:|---:|---:|---|"]
        if "error" in cz:
            C.append(f"| — | ⚪ | — | — | — | — | — | {cz['error']} |")
        else:
            for stt, g in e["groups"].items():
                live = cz["by_state"].get(stt, [])
                n_eff = len(live) / e["overlap_days"]
                z = None
                if live and g.get("std"):
                    z = (statistics.fmean(live) - g["mean"]) / (g["std"] / math.sqrt(max(n_eff, 1e-9)))
                lt, why = canary_light(stt, z, n_eff)
                C.append(f"| {stt} | {lt} | {len(live)} | {n_eff:.1f} | {fmt(statistics.fmean(live), 2) if live else '—'} | "
                         f"{g.get('mean', 0):.2f} ± {g.get('std', 0):.2f} | {fmt(z, 2)} | {why} |")
            skipped = sum(len(v) for k, v in cz["by_state"].items() if k not in e["groups"])
            if skipped:
                C.append(f"\n（另有 {skipped} 列燈色不屬四組，不計。）")
        L += C

    L += ["", *details,
          "## 這張表的用途", "",
          "- 它不證明策略有效或無效；它只在實際結果開始偏離回測分佈時，按事先寫好的門檻提醒減倉或停止。",
          "- 樣本少時 z 值不可靠，所以 < 5 筆一律 ⚪。這段期間監控的價值在機制本身，不在數字。",
          "- 「未登記回測期望」的實倉策略，應補一份回測（哪怕粗糙）登記到 `expectations.json`，否則永遠不會亮燈。", ""]
    (a.out / "DIVERGENCE.md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {a.out / 'DIVERGENCE.md'}")


if __name__ == "__main__":
    main()
