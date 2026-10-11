"""前向測試：恒指牛熊證折讓 ＋ 恒指窩輪 vs 期權 IV ＋ 界內證，定時掃描、本地存 CSV、推上 GCP（R150 action=scan_push）。

在裝有 Futu OpenD 的電腦上（PowerShell，在 repo 資料夾）：
  python futu\\scan_push.py --once --force          # 立刻跑一輪（週末拿到的是上個交易日收市報價）
  python futu\\scan_push.py --every 30              # 港股日市內每 30 分鐘一輪，視窗開住就一直跑（Ctrl+C 停）
  python futu\\scan_push.py --once --kinds cbbc     # 只跑某幾種：cbbc,warrant,inline

每輪三種掃描各自：印摘要 → 存 tradingview/out/scan/<kind>_<日期>_<時分>.csv → POST（kind, rows, summary）到 Cloud Run。
環境變數跟 push_to_gcp.py 同一對（ZHUGE_GCP_URL、WEBHOOK_SECRET_TOKEN；選填 OPEND_HOST／OPEND_PORT）；沒設就只存本地。
只讀行情、不落單。
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "out" / "scan"
HKT = timezone(timedelta(hours=8))
SCRIPT_VERSION = "R150"
sys.path.insert(0, str(ROOT / "research" / "warrants_cbbc"))
import cbbc_discount_scan as cds  # noqa: E402
import warrant_iv_scan as wis  # noqa: E402
import inline_vs_options as ivo  # noqa: E402

GCP_URL = os.environ.get("ZHUGE_GCP_URL", "").strip()
TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN", "").strip()
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))


def now_hkt():
    return datetime.now(HKT)


def log(msg):
    print(f"[{now_hkt():%H:%M:%S}] {msg}", flush=True)


def in_session(t):
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return (9 * 60 + 30 <= hm <= 12 * 60) or (13 * 60 <= hm <= 16 * 60)


def save_csv(kind, rows, t):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{kind}_{t:%Y-%m-%d_%H%M}.csv"
    keys = sorted({k for r in rows for k in r})
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date"] + keys)
        w.writeheader()
        for r in rows:
            w.writerow({"date": t.strftime("%Y-%m-%d"), **r})
    return p


def push(kind, rows, summary, meta, t):
    if not GCP_URL or not TOKEN:
        return "（沒設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN，不推 GCP）"
    body = {"action": "scan_push", "token": TOKEN, "kind": kind, "run_hkt": t.strftime("%Y-%m-%d %H:%M"),
            "script_version": SCRIPT_VERSION, "owner": meta.get("owner"), "forward": meta.get("forward"),
            "summary": summary, "rows": rows[:500]}
    req = urllib.request.Request(GCP_URL, data=json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8") or "{}")
        if res.get("status") == "stored":
            return f"GCP ✅ 已存（{res.get('n')} 列）" + (f" ⚠ {res['warnings']}" if res.get("warnings") else "")
        return f"GCP ⚠ 回應 {res.get('status')}：{res.get('message')}"
    except urllib.error.HTTPError as e:
        return f"GCP ❌ HTTP {e.code}"
    except Exception as e:
        return f"GCP ❌ {e.__class__.__name__}"


def run_cbbc(owner, t):
    rows, meta = cds.scan_live(OPEND_HOST, OPEND_PORT, owner, log=log)
    pos = [r for r in rows if r["discount"] > 0]
    cand = [r for r in rows if r["candidate"]]
    summary = {"n": len(rows), "n_discount": len(pos), "n_candidate": len(cand), "forward": meta["forward"],
               "best_code": cand[0]["code"] if cand else "", "best_net": cand[0]["net_if_held"] if cand else None}
    cds.print_rows(pos[:15], meta["forward"])
    log(f"牛熊證：{len(rows)} 隻，折讓>0 {len(pos)}，候選 {len(cand)}")
    return rows, summary, meta


def run_warrant(owner, t):
    rows, meta = wis.scan_live(OPEND_HOST, OPEND_PORT, owner, 120, 30.0, log=log)
    ok = [r for r in rows if "error" not in r and r.get("premium_pct") is not None]
    locks = [r for r in ok if r.get("lock_edge_pts") is not None and r["lock_edge_pts"] > 0]
    prem = sorted(r["premium_pct"] for r in ok)
    summary = {"n": len(rows), "n_ok": len(ok), "n_lock": len(locks), "n_neg_premium": sum(1 for r in ok if r["premium_pct"] < 0),
               "premium_median": prem[len(prem) // 2] if prem else None, "premium_p10": prem[len(prem) // 10] if prem else None,
               "expiries": meta.get("expiries"), "best_code": locks[0]["code"] if locks else "",
               "best_lock_pts": max((r["lock_edge_pts"] for r in locks), default=None)}
    wis.print_rows(rows, 15)
    return rows, summary, meta


def run_inline(owner, t):
    rows, meta = ivo.scan_live(OPEND_HOST, OPEND_PORT, owner, 30.0, 0.03, 3.0, log=log)
    summary = {**ivo.summarize(rows), "forward": meta.get("forward")} if rows else {"n": 0, "n_inline": meta.get("n_inline", 0)}
    if rows:
        ivo.print_results(rows)
    return rows, summary, meta


RUNNERS = {"cbbc": run_cbbc, "warrant": run_warrant, "inline": run_inline}


def cycle(kinds, owner):
    t = now_hkt()
    for kind in kinds:
        log(f"=== {kind} ===")
        try:
            rows, summary, meta = RUNNERS[kind](owner, t)
        except Exception as exc:
            log(f"🔴 {kind} 掃描失敗：{exc.__class__.__name__}: {exc}")
            continue
        if rows:
            p = save_csv(kind, rows, t)
            log(f"本地已存 {p.relative_to(ROOT)}")
        log(f"{kind} 摘要：{json.dumps(summary, ensure_ascii=False, default=str)[:300]}")
        log(push(kind, rows, summary, meta, t))
        time.sleep(3.5)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--every", type=float, metavar="分鐘")
    p.add_argument("--kinds", default="cbbc,warrant,inline", help="逗號分隔：cbbc,warrant,inline")
    p.add_argument("--owner", default="HK.800000")
    p.add_argument("--force", action="store_true", help="交易時段外也跑")
    a = p.parse_args()
    kinds = [k.strip() for k in a.kinds.split(",") if k.strip() in RUNNERS]
    if a.once:
        cycle(kinds, a.owner)
        return
    log(f"每 {a.every:g} 分鐘一輪（{','.join(kinds)}）{'含交易時段外' if a.force else '只在港股日市'}；Ctrl+C 停。")
    while True:
        if a.force or in_session(now_hkt()):
            cycle(kinds, a.owner)
        else:
            log("非交易時段，略過。")
        time.sleep(max(1.0, a.every) * 60)


if __name__ == "__main__":
    main()
