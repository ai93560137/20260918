"""ops_blotter.py — 落單紀錄（blotter）：每筆富途成交一行，對「意圖價」計滑價（FUND_SOP 二之三 缺口 E，2026-10-15）。

每次 ops_notify.yml 成交通報（17:10／03:40 HKT）之後跑：
  1. 讀 GCS futu/deals/<今日>.json 同前一日（富途 VM auto_risk 匯出）。
  2. 每筆成交用 main.py 嘅 FUTU_TEAM_RULES（總指揮擁有，ast 讀，唔 import main.py）歸陣。
  3. 對 repo ops/intents.csv（各陣落單前登記「意圖價」）：同日或翌日、代號前綴、方向相同、手數未用完 → 配對，
     滑價點數 = 買：成交 − 意圖；賣：意圖 − 成交（正數＝差過意圖）。
  4. 追加到 GCS ops/blotter/<YYYY-MM>.csv（私人；按 order_id＋時間＋價＋手數去重），
     再寫 ops/blotter/summary.json（本月按陣：成交筆數、有意圖價筆數、平均滑價點數）畀月報讀。
只有點數、手數、價格，冇金額；repo 公開，Actions 日誌只印筆數。

用法：python3 scripts/ops_blotter.py [--dry-run] [--now "2026-10-15 17:10"]
"""
from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops_notify import HKT, gcs_cat, gcs_put, parse_hkt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COLS = ["time_hkt", "code", "product", "side", "qty", "price", "team", "intent_price", "slip_pts", "intent_note", "order_id"]
UNMATCHED = "未配對"


def team_rules(main_py: str) -> list[tuple[re.Pattern, str]]:
    """由 main.py 原始碼讀 FUTU_TEAM_RULES（(正則, 陣, 用途, 上限)），陣名常數同時解析。"""
    tree = ast.parse(main_py)
    consts, rules = {}, None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith("FUTU_TEAM_") and isinstance(node.value, ast.Constant):
                consts[name] = node.value.value
            elif name == "FUTU_TEAM_RULES":
                rules = node.value
    out = []
    for elt in (rules.elts if rules is not None else []):
        rx, team = elt.elts[0], elt.elts[1]
        team_s = team.value if isinstance(team, ast.Constant) else consts.get(getattr(team, "id", ""), UNMATCHED)
        out.append((re.compile(rx.value), team_s))
    return out


def team_of(code: str, rules) -> str:
    for rx, team in rules:
        if rx.search(code):
            return team
    return UNMATCHED


def load_intents(text: str | None) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text or "")):
        try:
            rows.append({"date": date.fromisoformat(r["date"].strip()), "team": r.get("team", "").strip(),
                         "code": r["code"].strip(), "side": r["side"].strip(), "qty": float(r["qty"]),
                         "price": float(r["intent_price"]), "note": (r.get("note") or "").strip(), "left": float(r["qty"])})
        except (KeyError, ValueError):
            continue
    return rows


def match_intent(deal: dict, intents: list[dict]) -> dict | None:
    d = parse_hkt(deal["time_hkt"][:16]).date()
    for it in intents:
        if it["left"] > 0 and it["side"] == deal["side"] and deal["code"].startswith(it["code"]) \
                and it["date"] <= d <= it["date"] + timedelta(days=1):
            it["left"] -= float(deal["qty"])
            return it
    return None


def slip(side: str, fill: float, intent: float) -> float:
    return round(fill - intent if side == "買" else intent - fill, 2)


def deal_key(r: dict) -> str:
    return f"{r.get('order_id')}|{r['time_hkt']}|{float(r['price']):g}|{float(r['qty']):g}"


def build_rows(deals: list[dict], existing: list[dict], rules, intents: list[dict]) -> list[dict]:
    """回傳新增嘅行（已存在嘅唔重複；已用過嘅意圖手數先扣返）。"""
    seen = {deal_key(r) for r in existing}
    for r in existing:     # 已配對過嘅意圖唔好再用
        if r.get("intent_price"):
            for it in intents:
                if it["left"] > 0 and it["side"] == r["side"] and r["code"].startswith(it["code"]) \
                        and abs(it["price"] - float(r["intent_price"])) < 1e-9:
                    it["left"] -= float(r["qty"])
                    break
    new = []
    for dl in sorted(deals, key=lambda x: x["time_hkt"]):
        if deal_key(dl) in seen:
            continue
        seen.add(deal_key(dl))
        it = match_intent(dl, intents)
        new.append({"time_hkt": dl["time_hkt"], "code": dl["code"], "product": dl.get("product", ""),
                    "side": dl["side"], "qty": f"{float(dl['qty']):g}", "price": f"{float(dl['price']):g}",
                    "team": team_of(dl["code"], rules),
                    "intent_price": f"{it['price']:g}" if it else "",
                    "slip_pts": f"{slip(dl['side'], float(dl['price']), it['price']):g}" if it else "",
                    "intent_note": it["note"] if it else "", "order_id": str(dl.get("order_id", ""))})
    return new


def summarize(rows: list[dict], month: str) -> dict:
    teams: dict[str, dict] = {}
    for r in rows:
        t = teams.setdefault(r["team"], {"fills": 0, "with_intent": 0, "slip_sum": 0.0})
        t["fills"] += 1
        if r.get("slip_pts"):
            t["with_intent"] += 1
            t["slip_sum"] += float(r["slip_pts"])
    for t in teams.values():
        t["avg_slip_pts"] = round(t["slip_sum"] / t["with_intent"], 2) if t["with_intent"] else None
        del t["slip_sum"]
    return {"month": month, "teams": teams}


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def all_intents_text() -> str:
    """預設分支 ops/intents.csv＋notify_config.json intent_branches 各陣分支嗰份（git show origin/<分支>，冇就略過）。"""
    import subprocess
    texts = []
    p = ROOT / "ops" / "intents.csv"
    if p.exists():
        texts.append(p.read_text(encoding="utf-8"))
    try:
        cfg = json.loads((ROOT / "ops" / "notify_config.json").read_text(encoding="utf-8"))
        branches = cfg.get("intent_branches", {}).get("branches", [])
    except (OSError, json.JSONDecodeError):
        branches = []
    for br in branches:
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"origin/{br}:ops/intents.csv"], capture_output=True, text=True)
        if r.returncode == 0:
            texts.append(r.stdout)
    lines, header = [], "date,team,code,side,qty,intent_price,note"
    for t in texts:
        lines += [ln for ln in t.splitlines()[1:] if ln.strip()]
    return "\n".join([header] + list(dict.fromkeys(lines))) + "\n"     # 同一行喺幾個分支都有就當一行


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="覆寫現在時間（HKT，YYYY-MM-DD HH:MM）")
    a = ap.parse_args()
    now = parse_hkt(a.now) if a.now else datetime.now(HKT)
    rules = team_rules((ROOT / "main.py").read_text(encoding="utf-8"))
    intents = load_intents(all_intents_text())

    deals = []
    for d in (now.date() - timedelta(days=1), now.date()):
        try:
            doc = gcs_cat(f"futu/deals/{d:%Y-%m-%d}.json")
        except Exception as exc:  # noqa: BLE001
            print(f"讀 futu/deals/{d} 失敗：{str(exc)[:120]}")
            doc = None
        if isinstance(doc, dict):
            deals += doc.get("deals") or []

    by_month: dict[str, list[dict]] = {}
    for dl in deals:
        by_month.setdefault(dl["time_hkt"][:7], []).append(dl)
    month_now = f"{now:%Y-%m}"
    by_month.setdefault(month_now, [])
    for month, ds in sorted(by_month.items()):
        obj = f"ops/blotter/{month}.csv"
        try:
            old = gcs_cat(obj)
        except Exception:  # noqa: BLE001
            old = None
        existing = list(csv.DictReader(io.StringIO(old["_text"]))) if isinstance(old, dict) and "_text" in old else []
        new = build_rows(ds, existing, rules, intents)
        rows = existing + new
        n_unmatched = sum(1 for r in new if r["team"] == UNMATCHED)
        print(f"{month}：新增 {len(new)} 筆（有意圖價 {sum(1 for r in new if r['intent_price'])}、未配對陣 {n_unmatched}），共 {len(rows)} 筆")
        if a.dry_run:
            continue
        if new:
            gcs_put(obj, to_csv(rows))
        if month == month_now:
            gcs_put("ops/blotter/summary.json", json.dumps(summarize(rows, month), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
