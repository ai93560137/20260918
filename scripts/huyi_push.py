#!/usr/bin/env python3
"""將虎翼最新候選（美＋港最近一次掃描）同紙上紀錄推上總指揮網頁（Cloud Run action=huyi_push → GCS huyi/latest.json，?view=huyi）。

    python3 scripts/huyi_push.py            # 要 ZHUGE_GCP_URL、ZHUGE_WEBHOOK_TOKEN（GitHub Secrets）；冇就唔推
    python3 scripts/huyi_push.py --dry-run  # 只印 JSON
"""
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "huyi"
MAX_ROWS = 200


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def row(r: dict, paper: bool) -> dict:
    d = {"date": r.get("open_date" if paper else "date"), "market": r.get("market"), "code": r.get("ticker"),
         "name": r.get("name"), "drop_pct": num(r.get("drop_pct")), "close": num(r.get("spot" if paper else "close")),
         "atm_iv": num(r.get("atm_iv")), "rv63": num(r.get("rv63pre")), "rho": num(r.get("rho")),
         "rho_star": num(r.get("rho_req")), "leg": r.get("leg"), "strike": num(r.get("strike")),
         "expiry": r.get("expiry"), "premium": num(r.get("fill")), "note": r.get("note")}
    if paper:
        st = "合資格" if r.get("qualifies") == "Y" else "唔合資格"
        d["status"] = f"{st}｜{'未到期' if r.get('status') == 'open' else '已結算' + ('（接貨／被call）' if r.get('assigned') == 'Y' else '')}"
        d["pnl_pct"] = num(r.get("pnl_pct"))
    else:
        d["status"] = "✅ 合資格（紙上）" if r.get("qualifies") == "Y" else "—"
    return {k: v for k, v in d.items() if v not in (None, "")}


def build() -> dict:
    cands, asof = [], []
    for m in ("us", "hk"):
        files = sorted((OUT / m).glob("*.csv")) if (OUT / m).exists() else []
        if files:
            asof.append(f"{m} {files[-1].stem}")
            with open(files[-1], newline="", encoding="utf-8") as f:
                cands += [row(r, False) for r in csv.DictReader(f)]
    paper = []
    if (OUT / "paper_log.csv").exists():
        with open(OUT / "paper_log.csv", newline="", encoding="utf-8") as f:
            paper = [row(r, True) for r in csv.DictReader(f)][-MAX_ROWS:]
    notes = [f"最近掃描：{'、'.join(asof) or '未有'}",
             "ρ＝平值 IV ÷ 大跌前 RV63；ρ* 欄＝該腿開倉門檻 ρ₂（put 0.95；call 美 1.20／港 1.50，call 只准紙上）",
             "權利金：美＝買價；港＝港交所結算價減 1 波動點",
             "前向證偽：合資格 put 前 30 筆平均損益 ≤ 0，或累計虧損 > 已收權利金 → 停"]
    for m in ("us", "hk"):
        p = OUT / f"tg_{m}.txt"
        if p.exists():
            notes.append(p.read_text(encoding="utf-8").splitlines()[-1])
    now = datetime.now(timezone(timedelta(hours=8)))
    return {"action": "huyi_push", "asof_hkt": now.strftime("%Y-%m-%d %H:%M"), "mode": "paper",
            "candidates": cands[:MAX_ROWS], "paper": paper, "notes": notes[:20]}


def main() -> int:
    doc = build()
    if "--dry-run" in sys.argv:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0
    url, token = os.getenv("ZHUGE_GCP_URL", "").strip(), os.getenv("ZHUGE_WEBHOOK_TOKEN", "").strip()
    if not url or not token:
        print("冇 ZHUGE_GCP_URL／ZHUGE_WEBHOOK_TOKEN，唔推")
        return 0
    doc["token"] = token
    req = urllib.request.Request(url, data=json.dumps(doc, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("huyi_push", r.status, r.read()[:200].decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print(f"::warning::huyi_push 失敗 {e!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
