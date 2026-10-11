#!/usr/bin/env python3
"""自動：每 N 分鐘讀富途持倉＋報價 → 重算風險報告 → 記錄 → 有警報就（可選）發 Telegram。
跑喺使用者自己部電腦（OpenD 同機）。只讀：唔落單、唔 unlock_trade、唔改單。富途報價只作監控，落單以券商即時價為準。

用法（PowerShell，喺 repo 資料夾）：
  python gcp_ib\\auto_risk.py --once                 # 跑一次
  python gcp_ib\\auto_risk.py --every 15             # 每 15 分鐘一次，視窗開住就一直跑（Ctrl+C 停）

設定（環境變數，用 setx 設一次，重開 PowerShell 生效；唔好寫入 repo）：
  setx ZHUGE_COMBINED_EQUITY 2520339     # 幾個戶口合計權益 HKD（硬止損按合計計）
  setx TG_BOT_TOKEN "…"                 # 選填：有就發 Telegram 警報（同 repo 其他通知同一個 bot）
  setx TG_CHAT_ID "…"
  setx ZHUGE_GCP_URL "https://…run.app/"   # 選填：有就每次推上 GCP（main.py R147 action=futu_risk，存私人 bucket）
  setx WEBHOOK_SECRET_TOKEN "…"            #        同 futu/push_to_gcp.py 用同一對設定
  選填門檻：ZHUGE_ALERT_CUSHION（富途保證金緩衝警報線，預設 100000）、ZHUGE_ALERT_STOP（止損用量，預設 0.8）

輸出（全部喺 tradingview/out/，已 .gitignore，唔會 commit）：
  risk_report_live.md   最新報告
  risk_history.csv      每次嘅主要指標
  alert_state.json      警報狀態（只喺警報出現／解除時先發 Telegram，唔會每次都發）
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "out"
HKT = timezone(timedelta(hours=8))
sys.path.insert(0, str(ROOT / "tradingview"))
import risk_report  # noqa: E402


def now_hkt():
    return datetime.now(HKT)


def weekend_closed(t):
    """香港時間 星期六 06:00 至 星期一 06:00 冇市（美股期權週五夜收、恒指夜市週六 03:00 收）。"""
    wd = t.weekday()
    return (wd == 5 and t.hour >= 6) or wd == 6 or (wd == 0 and t.hour < 6)


def fetch():
    """跑 futu_positions_quote.py 更新 futu_positions.json。回傳 (成功, 錯誤訊息)。"""
    r = subprocess.run([sys.executable, str(ROOT / "gcp_ib" / "futu_positions_quote.py")], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode:
        return False, (r.stderr or r.stdout).strip().splitlines()[-1:] or ["未知錯誤"]
    if "富途 API 冇讀到持倉" in r.stdout:
        return False, ["富途 API 冇讀到持倉（OpenD 登入咗另一個 ID？）"]
    return True, []


def alerts(M, cushion_line, stop_line):
    """回傳 {警報鍵: 訊息}；空＝冇警報。"""
    a = {}
    if M.get("gap", 1) < 0:
        a["hard_stop"] = f"⛔ 合計權益 {M['equity']:,.0f} 低於硬止損 {M['hard_stop']:,.0f}"
    if M.get("cushion") is not None and M["cushion"] < cushion_line:
        a["margin"] = f"⚠ 富途保證金緩衝 HK${M['cushion']:,.0f}（< {cushion_line:,.0f}）"
    for name, use in M.get("stop_use", {}).items():
        if use >= 1:
            a[f"stop:{name}"] = f"⛔ {name} 觸止損（買回 {use * 100:.0f}% 止損線）"
        elif use >= stop_line:
            a[f"stop:{name}"] = f"⚠ {name} 近止損（買回 {use * 100:.0f}% 止損線）"
    for name, (d, band) in M.get("delta", {}).items():
        if abs(d) > band:
            a[f"delta:{name}"] = f"⚠ {name} 淨 Δ {d:+.2f} 手，超出 ±{band}"
    return a


def telegram(text):
    tok, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not tok or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=10)
        return True
    except Exception as e:  # 唔好印 token；只印錯誤類型
        print(f"Telegram 發送失敗：{e.__class__.__name__}")
        return False


SCRIPT_VERSION = "R149"


def push_gcp(t, M, cur, txt):
    """推上 Cloud Run（action=futu_risk）。冇設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN 就跳過。回傳狀態文字。"""
    url, tok = os.environ.get("ZHUGE_GCP_URL"), os.environ.get("WEBHOOK_SECRET_TOKEN")
    if not url or not tok:
        return "（冇設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN，唔推 GCP）"
    try:
        fp = json.loads((ROOT / "tradingview" / "data_external" / "futu_positions.json").read_text(encoding="utf-8"))
        positions = [{k: r.get(k) for k in ("code", "name", "qty", "open_price", "bid", "ask", "last", "quote_time", "futu_pl")}
                     for r in fp.get("positions", [])]
    except Exception:
        positions = []
    body = {"action": "futu_risk", "token": tok, "run_hkt": t.strftime("%Y-%m-%d %H:%M"),
            "script_version": SCRIPT_VERSION, "metrics": M, "alerts": cur, "positions": positions, "report": txt,
            "client_telegram": bool(os.environ.get("TG_BOT_TOKEN") and os.environ.get("TG_CHAT_ID"))}  # 本機發就唔使 Cloud Run 再發
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False, default=list).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read().decode("utf-8") or "{}")
        return "GCP ✅ 已存" if res.get("status") == "stored" else f"GCP ⚠ 回應 {res.get('status')}"
    except urllib.error.HTTPError as e:
        return f"GCP ❌ HTTP {e.code}"
    except Exception as e:        # 唔好印網址同權杖
        return f"GCP ❌ {e.__class__.__name__}"


def cycle(equity, cushion_line, stop_line):
    t = now_hkt()
    OUT.mkdir(parents=True, exist_ok=True)
    ok, err = fetch()
    state_f = OUT / "alert_state.json"
    try:
        prev = json.loads(state_f.read_text(encoding="utf-8"))
    except Exception:
        prev = {}
    if not ok:
        cur = {"fetch": f"❌ 讀富途失敗：{' '.join(err)[:200]}"}
        M = {}
    else:
        txt, M = risk_report.build(str(ROOT / "tradingview" / "data_external" / "risk_book.json"),
                                   str(ROOT / "tradingview" / "data_external" / "futu_positions.json"), equity)
        (OUT / "risk_report_live.md").write_text(txt + "\n", encoding="utf-8")
        cur = alerts(M, cushion_line, stop_line)
        hist = OUT / "risk_history.csv"
        new = not hist.exists()
        with hist.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["run_hkt", "quotes_hkt", "pnl_hkd", "equity_hkd", "gap_hkd", "futu_cushion_hkd",
                            "yunchui_delta", "stop_use", "alerts"])
            d = next(iter(M["delta"].values()), (None, None))[0]
            w.writerow([t.strftime("%Y-%m-%d %H:%M"), M.get("quotes_fetched"), round(M["pnl"]), round(M["equity"]),
                        round(M["gap"]), round(M["cushion"]) if M.get("cushion") is not None else "",
                        round(d, 2) if d is not None else "",
                        ";".join(f"{k}={v:.0%}" for k, v in M["stop_use"].items()), ";".join(cur)])
    new_on = {k: v for k, v in cur.items() if prev.get(k) != v}
    cleared = [k for k in prev if k not in cur]
    state_f.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    line = (f"[{t:%m-%d %H:%M} HKT] 盈虧 {M['pnl']:+,.0f}｜合計權益 {M['equity']:,.0f}｜富途緩衝 "
            f"{M.get('cushion', 0):,.0f}｜雲垂 Δ {next(iter(M['delta'].values()), (0, 0))[0]:+.2f}" if M else f"[{t:%m-%d %H:%M} HKT]")
    print(line + ("｜警報：" + "；".join(cur.values()) if cur else "｜冇警報"))
    if M:
        print("  → " + push_gcp(t, M, cur, txt))
    if new_on or cleared:
        msg = ["【諸葛亮持倉風險（自動）】" + f"{t:%m-%d %H:%M} HKT"]
        msg += list(new_on.values())
        msg += [f"✅ 已解除：{k}" for k in cleared]
        if M:
            msg.append(line.split("] ", 1)[-1])
        msg.append("只係監控，唔係落單指令；落單以富途即時價為準。")
        sent = telegram("\n".join(msg))
        print("  → Telegram 已發（本機）" if sent else "  →（本機冇設 Telegram；推上 GCP 之後由 Cloud Run 代發）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=15, help="每幾多分鐘跑一次")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--combined-equity", type=float, default=float(os.environ.get("ZHUGE_COMBINED_EQUITY", 0)) or None)
    ap.add_argument("--weekend", action="store_true", help="週末都照跑（預設週末唔跑）")
    a = ap.parse_args()
    cushion_line = float(os.environ.get("ZHUGE_ALERT_CUSHION", 100000))
    stop_line = float(os.environ.get("ZHUGE_ALERT_STOP", 0.8))
    if not a.combined_equity:
        print("⚠ 冇設合計權益（setx ZHUGE_COMBINED_EQUITY …），硬止損會用 book 假設 NAV 計")
    while True:
        if a.once or a.weekend or not weekend_closed(now_hkt()):
            try:
                cycle(a.combined_equity, cushion_line, stop_line)
            except Exception as e:
                print(f"[{now_hkt():%m-%d %H:%M}] 出錯：{e.__class__.__name__}: {e}")
        if a.once:
            return
        time.sleep(max(1.0, a.every) * 60)


if __name__ == "__main__":
    main()
