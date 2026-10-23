#!/usr/bin/env python3
"""自動：每 N 分鐘讀富途持倉＋報價 → 重算風險報告 → 記錄 → 有警報就（可選）發 Telegram。
跑喺使用者自己部電腦（OpenD 同機）。只讀：唔落單、唔 unlock_trade、唔改單。富途報價只作監控，落單以券商即時價為準。

用法（PowerShell，喺 repo 資料夾）：
  python gcp_ib\\auto_risk.py --once                 # 跑一次
  python gcp_ib\\auto_risk.py --every 15             # 每 15 分鐘一次，視窗開住就一直跑（Ctrl+C 停）
  每日香港時間 03:05／05:30／16:35 之後第一次循環會喺背景跑一次 futu_pnl_export.py（推 action=futu_pnl：
  05:30 畀基金報告 R152；03:05 夜盤、16:35 日盤成交畀每日成交紀錄 R172，Cloud Run 存 futu/deals/<日期>.json）；
  每個時段成功先記低，失敗最多試 3 次。唔想要就加 --no-pnl。

設定（環境變數，用 setx 設一次，重開 PowerShell 生效；唔好寫入 repo）：
  setx ZHUGE_COMBINED_EQUITY 7800000     # 幾個戶口合計權益 HKD（硬止損按合計計）；示例：1,000,000 USD × 7.8，換成你自己嘅數
  setx TG_BOT_TOKEN "…"                 # 選填：有就發 Telegram 警報（同 repo 其他通知同一個 bot）
  setx TG_CHAT_ID "…"
  setx ZHUGE_GCP_URL "https://…run.app/"   # 選填：有就每次推上 GCP（main.py R147 action=futu_risk，存私人 bucket）
  setx WEBHOOK_SECRET_TOKEN "…"            #        同 futu/push_to_gcp.py 用同一對設定
  選填門檻：ZHUGE_ALERT_CUSHION（富途保證金緩衝警報線，預設 60000；Cloud Run 另有逐級 Telegram）、ZHUGE_ALERT_STOP（止損用量，預設 0.8）、
  ZHUGE_ALERT_MM_JUMP（維持保證金單日升幅警報，預設 0.30＝30%，R193）

輸出（全部喺 tradingview/out/，已 .gitignore，唔會 commit）：
  risk_report_live.md   最新報告
  risk_history.csv      每次嘅主要指標
  alert_state.json      警報狀態（只喺警報出現／解除時先發 Telegram，唔會每次都發）
  margin_base.json      當日（06:00 HKT 起）維持保證金基準（R193 急升預警用）
  manual_rules_state.json 上次期貨手數同「蝕緊加注」旗（R284 人手守則①）
"""
import argparse
import csv
import json
import os
import re
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
    sec = M.get("sec") or {}
    if sec.get("exposed") and sec.get("ladder", "A") != "A":   # [R205] 證券戶口（龍飛陣 ETF）；冇倉嘅現金戶口唔警報
        a["sec_margin"] = (f"⚠ 富途證券戶口緩衝 HK${sec['cushion']:,.0f} → {sec['ladder']}"
                           f"（線 Ⓑ {risk_report.SEC_LADDER_CUSHION['B']:,.0f}／Ⓒ {risk_report.SEC_LADDER_CUSHION['C']:,.0f}"
                           f"／Ⓓ {risk_report.SEC_LADDER_CUSHION['D']:,.0f}）")
    for name, use in M.get("stop_use", {}).items():
        det = (M.get("stop_detail") or {}).get(name)          # [R260] 附腿同價，唔使估係邊個倉
        tail = f"\n   ↳ {det}" if det else ""
        if use >= 1:
            a[f"stop:{name}"] = f"⛔ {name} 觸止損（買回 {use * 100:.0f}% 止損線）{tail}"
        elif use >= stop_line:
            a[f"stop:{name}"] = f"⚠ {name} 近止損（買回 {use * 100:.0f}% 止損線）{tail}"
    for name, (d, band) in M.get("delta", {}).items():
        if abs(d) > band:
            a[f"delta:{name}"] = f"⚠ {name} 淨 Δ {d:+.2f} 手，超出 ±{band}"
    return a


def mm_jump(t, M, state_f, thr):
    """[R193] 維持保證金單日急升預警（FUND_SOP 二之三 B；10-14 一日約翻倍事後先知）。
    交易日以 06:00 HKT 為界；當日第一個讀數做基準，之後升 ≥ thr 就回傳警報字串（新一日自動解除）。"""
    mm = M.get("maintenance_margin")
    if not mm:
        return None
    day = f"{t - timedelta(hours=6):%Y-%m-%d}"
    try:
        st = json.loads(state_f.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    if st.get("day") != day or not st.get("base"):
        st = {"day": day, "base": mm}
        state_f.write_text(json.dumps(st), encoding="utf-8")
    up = mm / st["base"] - 1
    if up >= thr:
        return f"⚠ 富途維持保證金今日升 {up * 100:.0f}%（HK${st['base']:,.0f} → {mm:,.0f}）；緩衝 HK${M.get('cushion') or 0:,.0f}"
    return None


# [R284] 人手守則①「蝕緊嘅方向唔好加注」（使用者 10-22：「人手做錯即刻出警報提我」）。只睇期貨（人手落嘅主要係期貨；期權有其他陣）。
MANUAL_FUT_RX = re.compile(r"^(HK\.(HSI|MHI)\d{4}|US\.(ES|MES|NQ|MNQ)\d{4})$")


def add_to_loser(rows, state_f):
    """同上次持倉比：同方向手數多咗、而而家成個倉浮蝕 → 警報（記低加注前手數）；
    之後一直保持，直到減返去加注前或以下、或者轉賺先解除。回傳 {警報鍵: 訊息}。"""
    qty, pl = {}, {}
    for r in rows or []:
        code = str(r.get("code") or "")
        if r.get("source") == "positions" and MANUAL_FUT_RX.match(code) and r.get("qty"):
            qty[code] = qty.get(code, 0) + r["qty"]
            if r.get("futu_pl") is not None:
                pl[code] = pl.get(code, 0) + r["futu_pl"]
    try:
        st = json.loads(state_f.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    prev, flag = st.get("qty") or {}, st.get("flag") or {}
    for code, q in qty.items():
        p = prev.get(code, 0)
        if p and q * p > 0 and abs(q) > abs(p) and pl.get(code, 0) < 0 and code not in flag:
            flag[code] = p
    for code in list(flag):
        q, base = qty.get(code, 0), flag[code]
        if not (q * base > 0 and abs(q) > abs(base) and pl.get(code, 0) < 0):
            del flag[code]
    state_f.write_text(json.dumps({"qty": qty, "flag": flag}), encoding="utf-8")
    return {f"rule1:{code}": (f"⏰ 人手守則①：{code} 蝕緊（浮蝕 {pl[code]:,.0f} {'USD' if code.startswith('US.') else 'HKD'}）"
                              f"仲加注 {base:+g} → {qty[code]:+g} 手。守則：蝕緊嘅方向唔好加注（見網頁 📏 人手交易守則）")
            for code, base in flag.items()}


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


SCRIPT_VERSION = "R213"
# 香港時間匯出時段：03:05 夜盤成交（恒指夜市 03:00 收）、05:30 基金報告（美期權 04:00–05:00 收之後）、16:35 日盤成交（16:30 收）
PNL_SLOTS = ((3, 5), (5, 30), (16, 35))
PNL_MAX_TRIES = 3
_pnl_proc = None


def pnl_slot(t):
    """今日已到時間嘅最後一個匯出時段，寫成 'YYYY-MM-DD|HH:MM'；未到任何時段回傳 None。"""
    due = [h for h in PNL_SLOTS if (t.hour, t.minute) >= h]
    return f"{t:%Y-%m-%d}|{due[-1][0]:02d}:{due[-1][1]:02d}" if due else None


def pnl_daily(t):
    """每日三個時段（PNL_SLOTS）各喺背景跑一次 futu_pnl_export.py（推 action=futu_pnl）。唔阻住風險循環；結果記喺 pnl_export_state.json。"""
    global _pnl_proc
    state_f = OUT / "pnl_export_state.json"
    try:
        st = json.loads(state_f.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    if _pnl_proc is not None:
        if _pnl_proc.poll() is None:
            return
        out = (OUT / "pnl_export_last.log").read_text(encoding="utf-8", errors="replace")
        ok = _pnl_proc.returncode == 0 and "GCP ✅" in out
        key = st.get("running_slot") or st.get("running_day")
        if ok:
            st["done_slots"] = (st.get("done_slots") or [])[-9:] + [key]
            if key and key.endswith("|05:30"):
                st["done"] = key[:10]                          # 舊欄位：基金報告嗰次，RUNBOOK 查結果用
        st["last"] = {"slot": key, "ok": ok, "end_hkt": t.strftime("%Y-%m-%d %H:%M")}
        print(f"  → 成交／基金報告匯出{'✅ 完成' if ok else '❌ 失敗（睇 tradingview/out/pnl_export_last.log）'}")
        _pnl_proc = None
        state_f.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    key = pnl_slot(t)
    if key is None or key in (st.get("done_slots") or []):
        return
    if key.endswith("|05:30") and st.get("done") == key[:10]:  # 舊版狀態檔（只記日期）
        return
    tries = st.get("tries", {}) if st.get("tries_slot") == key else {}
    if tries.get("n", 0) >= PNL_MAX_TRIES:
        return
    tries["n"] = tries.get("n", 0) + 1
    st.update({"tries_slot": key, "tries": tries, "running_slot": key})
    state_f.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log = (OUT / "pnl_export_last.log").open("w", encoding="utf-8")
    _pnl_proc = subprocess.Popen([sys.executable, str(ROOT / "gcp_ib" / "futu_pnl_export.py")], cwd=ROOT,
                                 stdout=log, stderr=subprocess.STDOUT,
                                 env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log.close()                   # 子程序有自己一份
    print(f"  → 成交／基金報告匯出已喺背景開始（{key} 第 {tries['n']} 次）")


def write_ladder(t, M):
    """[R199] 風控級別寫入 ZHUGE_LADDER_FILE（冇設就唔寫，例如部機）：一行「級別 day|night YYYY-MM-DD HH:MM」，
    級別同 risk_report.ladder_level 一致（A／B／C／D，夜盤 ×1.5）。[R205] 有設 ZHUGE_SEC_LADDER_FILE 就另寫證券戶口級別。龍飛陣 VM 嘅 longfei_guard.py 讀：
    Ⓑ → PAUSE；Ⓒ／Ⓓ／硬止損／檔案變舊（讀唔到富途或冇緩衝就唔寫）→ 只發 Telegram（使用者 10-16 定）。"""
    p = os.environ.get("ZHUGE_LADDER_FILE", "").strip()
    hard = bool(M) and M.get("gap", 1) < 0                     # RISK_LADDER §6b：硬止損都當 Ⓓ（STOP）
    if not p or not M or (M.get("cushion") is None and not hard):
        return
    night = risk_report.ladder_night(t)
    lv = "D" if hard else risk_report.ladder_level(M["cushion"], night)
    _atomic_write(p, f"{lv} {'night' if night else 'day'} {t:%Y-%m-%d %H:%M}{' hard_stop' if hard else ''}\n")
    sp = os.environ.get("ZHUGE_SEC_LADDER_FILE", "").strip()   # [R205] 證券戶口級別（唔分日夜，同一格式俾 guard 讀）
    if sp and M.get("sec"):
        slv = "D" if hard else M["sec"]["ladder"]
        _atomic_write(sp, f"{slv} sec {t:%Y-%m-%d %H:%M}{' hard_stop' if hard else ''}\n")


def _atomic_write(p, text):
    path = Path(p).expanduser()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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


def fetch_cme():
    """[R184] 由 Cloud Run 攞 ib-data VM 推上去嘅 CME 延遲報價，寫 data_external/cme_quotes.json 俾 risk_report 用。
    冇設 ZHUGE_GCP_URL／WEBHOOK_SECRET_TOKEN 或者失敗就跳過（報告退返 Yahoo／富途估值）。"""
    url, tok = os.environ.get("ZHUGE_GCP_URL"), os.environ.get("WEBHOOK_SECRET_TOKEN")
    if not url or not tok:
        return
    req = urllib.request.Request(url, data=json.dumps({"action": "cme_quotes_get", "token": tok}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            doc = json.loads(r.read().decode("utf-8") or "{}")
        if doc.get("quotes"):
            (ROOT / "tradingview" / "data_external" / "cme_quotes.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    except Exception:             # 唔好印網址同權杖
        pass


def cycle(equity, cushion_line, stop_line, mm_thr=0.30):
    t = now_hkt()
    OUT.mkdir(parents=True, exist_ok=True)
    ok, err = fetch()
    fetch_cme()
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
        try:
            write_ladder(t, M)
        except OSError as e:
            print(f"  ⚠ 寫風控級別檔失敗：{e.__class__.__name__}（龍飛陣 guard 會發 Telegram）")
        try:                                                      # [R284] 人手守則①
            rows = json.loads((ROOT / "tradingview" / "data_external" / "futu_positions.json").read_text(encoding="utf-8")).get("positions")
            cur.update(add_to_loser(rows, OUT / "manual_rules_state.json"))
        except Exception as e:
            print(f"  ⚠ 人手守則檢查失敗：{e.__class__.__name__}")
        jump = mm_jump(t, M, OUT / "margin_base.json", mm_thr)
        if jump:
            cur["mm_jump"] = jump
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
    ap.add_argument("--no-pnl", action="store_true", help="唔做每日基金報告匯出")
    a = ap.parse_args()
    cushion_line = float(os.environ.get("ZHUGE_ALERT_CUSHION", 60000))
    stop_line = float(os.environ.get("ZHUGE_ALERT_STOP", 0.8))
    mm_thr = float(os.environ.get("ZHUGE_ALERT_MM_JUMP", 0.30))
    if not a.combined_equity:
        print("⚠ 冇設合計權益（setx ZHUGE_COMBINED_EQUITY …），硬止損會用 book 假設 NAV 計")
    while True:
        if a.once or a.weekend or not weekend_closed(now_hkt()):
            try:
                cycle(a.combined_equity, cushion_line, stop_line, mm_thr)
            except Exception as e:
                print(f"[{now_hkt():%m-%d %H:%M}] 出錯：{e.__class__.__name__}: {e}")
        if not (a.once or a.no_pnl) and (a.weekend or not weekend_closed(now_hkt()) or _pnl_proc is not None):
            try:
                pnl_daily(now_hkt())
            except Exception as e:
                print(f"[{now_hkt():%m-%d %H:%M}] 基金報告匯出出錯：{e.__class__.__name__}")
        if a.once:
            return
        time.sleep(max(1.0, a.every) * 60)


if __name__ == "__main__":
    main()
