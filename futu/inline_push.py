"""界內證 vs 恒指期權掃描 → GCP（R148，對應 main.py 的 action=inline_scan）

在裝有 Futu OpenD 的電腦上執行（跟 push_to_gcp.py 同一台）。每輪：
  1. research/warrants_cbbc/inline_vs_options.py 的 scan_live()：抓全部恒指界內證（上限價、下限價、到期日、買賣價）
     與同日到期恒指期權的即時買賣價，逐隻算公平價區間、相對中值溢價、鎖定套利淨額、自做 condor 成本。
  2. 本地存一份 CSV（tradingview/out/inline_scan/<日期>_<時分>.csv，已 .gitignore）。
  3. POST 到 Cloud Run（action=inline_scan）→ 存 futu/inline/latest.json、runs/、history/；?view=inline&format=json 讀回。

用法（PowerShell 或 cmd，在 repo 資料夾）：
  python futu\\inline_push.py --once                 # 跑一次（收市後會退回結算價模式，仍會推）
  python futu\\inline_push.py --every 30             # 港股交易時段內每 30 分鐘一次，視窗開住就一直跑（Ctrl+C 停）
  python futu\\inline_push.py --every 30 --force     # 不管時段都跑（測試用）
  python futu\\inline_push.py --once --owner HK.800100   # 國指；科指 HK.800700

設定（環境變數，setx 設一次，重開命令列生效；跟 push_to_gcp.py 同一對）：
  setx ZHUGE_GCP_URL "https://你的服務.run.app/"
  setx WEBHOOK_SECRET_TOKEN "跟 Cloud Run 環境變數相同的權杖"
  選填：OPEND_HOST（127.0.0.1）、OPEND_PORT（11111）
沒設網址／權杖就只掃描＋存本地 CSV，不推。只讀行情、不落單。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "out" / "inline_scan"
HKT = timezone(timedelta(hours=8))
SCRIPT_VERSION = "R148"
sys.path.insert(0, str(ROOT / "research" / "warrants_cbbc"))
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
    """港股日市 09:30–12:00、13:00–16:00（週一至五）；期權買賣價只在這段有意義。"""
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return (9 * 60 + 30 <= hm <= 12 * 60) or (13 * 60 <= hm <= 16 * 60)


def push(results, meta, t):
    """POST 到 Cloud Run。回傳狀態文字；不印網址或權杖。"""
    if not GCP_URL or not TOKEN:
        return "（沒設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN，不推 GCP）"
    body = {"action": "inline_scan", "token": TOKEN, "run_hkt": t.strftime("%Y-%m-%d %H:%M"),
            "script_version": SCRIPT_VERSION, "owner": meta.get("owner"), "forward": meta.get("forward"),
            "source": "；".join(dict.fromkeys(meta.get("sources") or []))[:120], "rows": results[:400]}
    req = urllib.request.Request(GCP_URL, data=json.dumps(body, ensure_ascii=False, default=str).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode("utf-8") or "{}")
        if res.get("status") == "stored":
            return f"GCP ✅ 已存（{res.get('n')} 隻，鎖定 ✔ {res.get('n_lock')}）" + (f" ⚠ {res['warnings']}" if res.get("warnings") else "")
        return f"GCP ⚠ 回應 {res.get('status')}：{res.get('message')}"
    except urllib.error.HTTPError as e:
        return f"GCP ❌ HTTP {e.code}"
    except Exception as e:
        return f"GCP ❌ {e.__class__.__name__}"


def cycle(owner, fee_lot, rate, half_spread):
    t = now_hkt()
    try:
        results, meta = ivo.scan_live(OPEND_HOST, OPEND_PORT, owner, fee_lot, rate, half_spread, log=log)
    except Exception as exc:
        log(f"🔴 掃描失敗：{exc.__class__.__name__}: {exc}")
        return
    if not results:
        log("沒有可算的界內證，這輪不推。")
        return
    ivo.print_results(results)
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / f"{t:%Y-%m-%d_%H%M}.csv"
    ivo.write_csv(results, str(csv_path), t.strftime("%Y-%m-%d"))
    log(f"本地已存 {csv_path.relative_to(ROOT)}")
    log(push(results, meta, t))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--every", type=float, metavar="分鐘")
    p.add_argument("--owner", default="HK.800000", help="HK.800000 恒指（預設）、HK.800100 國指、HK.800700 科指")
    p.add_argument("--force", action="store_true", help="交易時段外也跑")
    p.add_argument("--fee-lot", type=float, default=30.0)
    p.add_argument("--rate", type=float, default=0.03)
    p.add_argument("--half-spread", type=float, default=3.0, help="退回結算價模式時的期權半差價假設（點）")
    a = p.parse_args()
    if a.once:
        cycle(a.owner, a.fee_lot, a.rate, a.half_spread)
        return
    log(f"每 {a.every:g} 分鐘掃一次{'（含交易時段外）' if a.force else '（只在港股日市）'}；Ctrl+C 停。")
    while True:
        if a.force or in_session(now_hkt()):
            cycle(a.owner, a.fee_lot, a.rate, a.half_spread)
        else:
            log("非交易時段，略過。")
        time.sleep(max(1.0, a.every) * 60)


if __name__ == "__main__":
    main()
