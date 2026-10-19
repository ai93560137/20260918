#!/usr/bin/env python3
"""每日對帳表＋逐日損益帳（FUND_SOP 缺口 3、5；總指揮擁有，純 Python，GitHub Actions ops_daily_books.yml 每日 17:20 HKT 跑）。

對帳表（research/reconcile/<日>.md，repo 公開；只有手數同燈號，冇任何金額／NAV 百分比——金額＋手數可反推權益；
  含金額嘅完整版寫 GCS ops/books/reconcile_private/<日>.md，私人）。Actions 日誌公開，含金額內文一律 print_private 只印字數：
  每個合約並列三方：① 富途快照 futu/risk/latest.json 嘅 positions.qty；② POSITIONS.md 登記（由持倉欄文字解析）；
  ③ 各陣 journal（蛇蟠 journal/position.json hsi.real_pos、雲垂 position.json hedges／跨式、position_mes.json、
  風揚 PAPER_TRADING.md 方向一本週兩腳）。三方一致 ✅；唔一致 ⚠ 並列「原因」欄（research/reconcile/explanations.json，
  人手填）；連續兩個交易日未解釋 → 升級 RISK_LADDER Ⓑ（停開新倉）並 Telegram。狀態 research/reconcile/state.json。

逐日損益帳（GCS ops/books/pnl_daily.csv，私人；含權益、保證金，唔推公開 repo）：
  每日一列：日期、run_hkt、合計權益、硬止損、離硬止損、富途權益、維持保證金、緩衝、未實現合計、各陣未實現、
  各陣當日已實現（futu/deals FIFO 平倉，按 FUTU_TEAM_RULES 配對）、MT5 當日已實現（logs/trade_ledger.json，有先計）、
  階梯等級。同一日重跑會覆蓋該列。

風控階梯（RISK_LADDER.md）：由緩衝、離硬止損百分比、單策略止損用量、偏離燈計出 Ⓐ／Ⓑ／Ⓒ／Ⓓ；Ⓒ／Ⓓ 直接 Telegram
  提示使用者（使用者 2026-10-13 同意）。只係資訊、唔係落單指令；落單由使用者人手。

用法：python3 scripts/daily_books.py [--date YYYY-MM-DD] [--dry-run] [--no-tg] [--local-json 目錄]
  --local-json：測試用，從目錄讀 futu_risk.json／futu_deals.json／futu_pnl.json／trade_ledger.json 代替 GCS。
陣別規則照 main.py FUTU_TEAM_RULES 抄（main.py 要裝 Cloud Run 套件先 import 到，所以呢度抄一份；改嗰邊記得改呢邊）。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HKT = timezone(timedelta(hours=8))
RECON_DIR = ROOT / "research" / "reconcile"
PNL_OBJECT = "ops/books/pnl_daily.csv"
LADDER_STATE_OBJECT = "ops/books/ladder_state.json"
USD_HKD = float(os.environ.get("FUTU_USD_HKD", "7.8") or 7.8)

TEAM_MANUAL, TEAM_GIFT, TEAM_UNMATCHED = "使用者人手", "券商贈股", "未配對"
TEAM_LONGFEI = "龍飛陣"
TEAM_RULES = (   # 照 main.py FUTU_TEAM_RULES（代碼正則, 陣, 用途, 最多手數；超出當使用者人手）
    (r"^HK\.MHI\d{6}[CP]\d+$", "雲垂陣", "MHI 月跨式", None),
    (r"^HK\.MHI2611$", TEAM_MANUAL, "MHI2611 小期（人手）", None),   # 2026-10-14 使用者確認；雲垂轉倉去 2611 前要改
    (r"^HK\.MHI\d{4}$", "雲垂陣", "MHI 期貨 Δ 對沖", 1),
    (r"^US\.EX\d{5}[CP]\d+x\d$", "雲垂陣", "MES 週權跨式", None),
    (r"^HK\.HSI\d{6}[CP]\d+$", "風揚陣・方向一", "恒指週權 1σ 勒式", None),
    (r"^HK\.HSI\d{4}$", TEAM_MANUAL, "大恒指期貨（人手）", None),   # 2026-10-14 使用者：預設歸人手；屬蛇蟠要逐張確認
    (r"^US\.EW\d{4}[CP]\d+x\d$", TEAM_MANUAL, "標普 E-mini 月底 Put", None),
    (r"^US\.(ES|MES)\d{4}$", TEAM_MANUAL, "標普期貨（人手，EW put 對沖）", None),
    (r"^US\.SPCX$", TEAM_GIFT, "SpaceX 碎股（券商送）", None),
    (r"^US\.(SPY|QQQ)$", TEAM_LONGFEI, "美股 ETF 真倉（AI 自動）", None),   # [R237] PR #212；同 main.py 一齊改
)
TEAM_ORDER = ["雲垂陣", "風揚陣・方向一", "蛇蟠陣", TEAM_LONGFEI, TEAM_MANUAL, TEAM_GIFT, TEAM_UNMATCHED]
AUTO_TEAMS = {TEAM_LONGFEI}   # [R237] 程式自動落單：持倉日內會變，唔登記 POSITIONS.md 每筆，對帳只列示、唔計 ⚠
JOURNAL_BRANCHES = {"蛇蟠陣": "claude/gifted-carson-v2tvhw", "雲垂陣": "claude/dazzling-curie-f3xzb8"}

# 風控階梯初稿（使用者 2026-10-13：Ⓒ／Ⓓ 可直接 TG 提示；門檻待使用者確認，見 RISK_LADDER.md）
LADDER = {
    "cushion_hkd": {"B": 37_500, "C": 25_000, "D": 15_000},         # 富途保證金緩衝 < 線（使用者 2026-10-14：原 15 萬／10 萬／6 萬 ×0.25）
    "gap_pct": {"C": 0.20, "D": 0.10},                               # 離硬止損 / 合計權益 < 線
    "stop_use": {"C": 0.80, "D": 1.00},                              # 單策略止損用量 ≥ 線（該策略）
}
NIGHT_FACTOR = 1.5   # 夜盤（17:15–03:00 HKT）無人：緩衝／離硬止損線 ×1.5、止損用量線 ÷1.5 更保守（使用者 2026-10-13 定）
MANUAL_LIMITS = {"notional_pct_nav": 0.50, "daily_loss_pct_nav": 0.02}   # 人手交易額度（缺口 8，使用者 2026-10-13 同意）：超額只通報
POINT_VALUE = {r"^HK\.HSI\d{4}$": 50, r"^HK\.MHI\d{4}$": 10, r"^US\.EW": 50, r"^US\.EX": 5, r"^US\.MES\d{4}$": 5, r"^US\.ES\d{4}$": 50}
# 補倉／提款（使用者 2026-10-13：本金隨時可入金、隨時可提款；本金金額只放私人，唔入公開 repo）
TOPUP = {"target_hkd": 45_000,         # 補倉補到緩衝 ≥ 此線（＝FUTU_MARGIN_CLEAR；10-14 隨緩衝線 ×0.25）；夜盤 ×NIGHT_FACTOR
         "round_hkd": 10_000,          # 建議金額向上取整
         "c_minutes": 30,              # 緩衝觸發 Ⓒ：30 分鐘內補到目標可代替減半
         "withdraw_floor_hkd": 300_000}  # 提款後緩衝要 ≥ 此數，而且當時係 Ⓐ（10-14 緩衝線降低後唔跟住降，維持原本 30 萬）
LEVEL_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}
LEVEL_NAME = {"A": "Ⓐ 觀察", "B": "Ⓑ 停開新倉", "C": "Ⓒ 減半", "D": "Ⓓ 全平"}
FOOTER = "（只係資訊、唔係落單指令；富途報價只作監控，落單以券商即時價為準）"


# ---------------------------------------------------------------- 外部來源
def gcs_cat(obj: str) -> dict | list | str | None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gcp_agent.py"), "cat", "--object", obj],
                       capture_output=True, text=True)
    if r.returncode != 0:
        if "不存在" in (r.stderr + r.stdout):
            return None
        raise RuntimeError(f"gcp_agent cat {obj} 失敗：{(r.stderr or r.stdout)[:300]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.stdout


def gcs_put(obj: str, text: str) -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gcp_agent.py"), "put", "--object", obj, "--file", "-"],
                       input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gcp_agent put {obj} 失敗：{(r.stderr or r.stdout)[:300]}")


def git_show(branch: str, path: str) -> str | None:
    """讀其他分支嘅檔（Actions 要先 fetch 該分支；本機已 fetch 就得）。"""
    for ref in (f"origin/{branch}", branch):
        r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
    return None


def print_private(text: str) -> None:
    """含金額／權益嘅內文：本機照印；GitHub Actions 日誌喺公開 repo 人人睇到，只印字數（同 ops_notify.print_private）。"""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"（內文含金額，Actions 日誌公開所以不印；{len(text)} 字，見 Telegram／GCS）")
    else:
        print(text)


def send_telegram(text: str) -> bool:
    token, chat = os.environ.get("TG_BOT_TOKEN", "").strip(), os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat:
        print("（沒有 TG_BOT_TOKEN／TG_CHAT_ID，只印不發）")
        return False
    import requests
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
    return True


# ---------------------------------------------------------------- 工具
def num(x, default=None):
    try:
        v = float(x)
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def team_of(code: str) -> tuple[str, str, float | None]:
    for rx, team, use, cap in TEAM_RULES:
        if re.match(rx, code or ""):
            return team, use, cap
    return TEAM_UNMATCHED, "—", None


def split_by_cap(code: str, qty: float) -> list[tuple[str, float]]:
    """有手數上限嘅規則（MHI 對沖 1 手）：上限內歸該陣，超出歸使用者人手。"""
    team, _, cap = team_of(code)
    if cap is None or abs(qty) <= cap:
        return [(team, qty)]
    sign = 1 if qty > 0 else -1
    return [(team, sign * cap), (TEAM_MANUAL, qty - sign * cap)]


def fmt_q(q) -> str:
    if q is None:
        return "—"
    q = float(q)
    return f"{q:+.0f}" if q == int(q) else f"{q:+.2f}"


def pts_to_strike_code(strike: float) -> str:
    return f"{int(round(strike * 1000))}"


def nth_friday_code(d: date) -> int:
    first = date(d.year, d.month, 1)
    first_fri = first + timedelta(days=(4 - first.weekday()) % 7)
    return (d - first_fri).days // 7 + 1


# ---------------------------------------------------------------- ② POSITIONS.md 解析
def parse_positions_md(text: str, year: int = 2026) -> tuple[dict[str, float], list[str]]:
    """POSITIONS.md 持倉欄文字 → {富途代碼: 手數（空為負）}。解析唔到嘅列回傳喺 unparsed。"""
    out: dict[str, float] = {}
    unparsed: list[str] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("| 陣 ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        team, pos, status = cells[0], cells[2], cells[6]
        if "已平" in status or status.startswith("空手") or "空手" in pos[:6]:
            # 空手：登記 0（只對能辨認合約嘅列）
            m = re.search(r"HSI(\d{4})", line)                 # 整列搵合約（空手列通常喺歷史或紀錄欄提到）
            if m and "蛇蟠" in team:
                out[f"HK.HSI{m.group(1)}"] = 0.0
            continue
        if "持倉中" not in status and "持有" not in status:
            continue
        hit = False
        m = re.search(r"沽 MHI (\d{1,2})/(\d{1,2}) 跨式 C/P ([\d,]+) 各 (\d+) 張", pos)
        if m:
            mo, dd, k, n = int(m.group(1)), int(m.group(2)), float(m.group(3).replace(",", "")), float(m.group(4))
            base = f"HK.MHI{year % 100:02d}{mo:02d}{dd:02d}"
            out[f"{base}C{pts_to_strike_code(k)}"] = -n
            out[f"{base}P{pts_to_strike_code(k)}"] = -n
            hit = True
        m = re.search(r"MHI(\d{4}) 期貨對沖沽 (\d+) 張", pos)
        if m:
            out[f"HK.MHI{m.group(1)}"] = out.get(f"HK.MHI{m.group(1)}", 0.0) - float(m.group(2))
            hit = True
        m = re.search(r"沽 MES (\d{1,2})/(\d{1,2}) 跨式 C/P ([\d,]+) 各 (\d+) 張", pos)
        if m:
            mo, dd, k, n = int(m.group(1)), int(m.group(2)), float(m.group(3).replace(",", "")), float(m.group(4))
            wk = nth_friday_code(date(year, mo, dd))
            base = f"US.EX{wk}{year % 100:02d}{mo:02d}"
            out[f"{base}C{int(k)}x0"] = -n
            out[f"{base}P{int(k)}x0"] = -n
            hit = True
        m = re.search(r"沽 HSI 週期權 (\d{1,2})/(\d{1,2})(?:（[^）]*）)?：Put ([\d,]+) @[\d.]+ ＋ Call ([\d,]+) @[\d.]+（各 (\d+) 張", pos)
        if m:
            mo, dd = int(m.group(1)), int(m.group(2))
            kp, kc, n = float(m.group(3).replace(",", "")), float(m.group(4).replace(",", "")), float(m.group(5))
            base = f"HK.HSI{year % 100:02d}{mo:02d}{dd:02d}"
            out[f"{base}P{pts_to_strike_code(kp)}"] = -n
            out[f"{base}C{pts_to_strike_code(kc)}"] = -n
            hit = True
        m = re.search(r"(賣|買) HSI(\d{4}) 大恒指期貨(?:淨 ([−-]?\d+) 手| ?(\d+) 手)", pos)
        if m:
            n = float((m.group(3) or m.group(4)).replace("−", "-"))
            if m.group(3) is None and m.group(1) == "賣":
                n = -n
            out[f"HK.HSI{m.group(2)}"] = n
            hit = True
        m = re.search(r"(賣|買) MHI(\d{4}) 小恒指期貨 ?(\d+) 手", pos)
        if m:
            n = float(m.group(3)) * (-1 if m.group(1) == "賣" else 1)
            out[f"HK.MHI{m.group(2)}"] = out.get(f"HK.MHI{m.group(2)}", 0.0) + n
            hit = True
        m = re.search(r"(賣|買) (ES|MES)(\d{4}) 標普期貨 ?(\d+) 手", pos)
        if m:
            n = float(m.group(4)) * (-1 if m.group(1) == "賣" else 1)
            out[f"US.{m.group(2)}{m.group(3)}"] = out.get(f"US.{m.group(2)}{m.group(3)}", 0.0) + n
            hit = True
        m = re.search(r"沽 EW(\d{4}) P([\d,]+) (\d+) 張", pos)
        if m:
            k = float(m.group(2).replace(",", ""))
            out[f"US.EW{m.group(1)}P{int(k)}x0"] = -float(m.group(3))
            hit = True
        if not hit and "即日" not in pos and "不定" not in status:
            unparsed.append(f"{team}：{pos[:60]}")
    return out, unparsed


# ---------------------------------------------------------------- ③ 各陣 journal
def journal_expectations(fetch=git_show, paper_md: str | None = None, year: int = 2026) -> tuple[dict[str, float], dict[str, str]]:
    """回傳 {代碼: 手數}（journal 口徑）同 {代碼: 來源}。"""
    exp: dict[str, float] = {}
    src: dict[str, str] = {}
    raw = fetch(JOURNAL_BRANCHES["蛇蟠陣"], "journal/position.json")
    if raw:
        try:
            j = json.loads(raw)
            hsi = j.get("hsi") or {}
            if hsi.get("real_pos") is not None and hsi.get("contract"):
                code = f"HK.{hsi['contract']}"
                exp[code] = float(hsi["real_pos"])
                src[code] = "蛇蟠 journal/position.json hsi.real_pos"
        except (ValueError, TypeError):
            pass
    raw = fetch(JOURNAL_BRANCHES["雲垂陣"], "tradingview/data_external/position.json")
    if raw:
        try:
            j = json.loads(raw)
            if j.get("expiry") and j.get("strike") and j.get("qty"):
                d = date.fromisoformat(j["expiry"])
                base = f"HK.MHI{d.year % 100:02d}{d.month:02d}{d.day:02d}"
                for cp in "CP":
                    exp[f"{base}{cp}{pts_to_strike_code(float(j['strike']))}"] = -float(j["qty"])
                    src[f"{base}{cp}{pts_to_strike_code(float(j['strike']))}"] = "雲垂 position.json 跨式"
            if j.get("hedge_expected_mhi_qty") is not None:
                hcode = None
                for h in j.get("hedges") or []:
                    m = re.search(r"MHI(\d{4})", str(h.get("contract", "")))
                    if m:
                        hcode = f"HK.MHI{m.group(1)}"
                if hcode:
                    exp[hcode] = float(j["hedge_expected_mhi_qty"])
                    src[hcode] = "雲垂 position.json hedge_expected_mhi_qty"
        except (ValueError, TypeError):
            pass
    raw = fetch(JOURNAL_BRANCHES["雲垂陣"], "tradingview/data_external/position_mes.json")
    if raw:
        try:
            j = json.loads(raw)
            if j.get("expiry") and j.get("strike") and j.get("qty"):
                d = date.fromisoformat(j["expiry"])
                base = f"US.EX{nth_friday_code(d)}{d.year % 100:02d}{d.month:02d}"
                for cp in "CP":
                    exp[f"{base}{cp}{int(j['strike'])}x0"] = -float(j["qty"])
                    src[f"{base}{cp}{int(j['strike'])}x0"] = "雲垂 position_mes.json"
        except (ValueError, TypeError):
            pass
    paper = paper_md if paper_md is not None else (ROOT / "research" / "hsi_futures_range" / "PAPER_TRADING.md").read_text(encoding="utf-8") \
        if (ROOT / "research" / "hsi_futures_range" / "PAPER_TRADING.md").exists() else ""
    for line in paper.splitlines():
        m = re.match(r"\|\s*\d+\s*\|.*?\|\s*([\d,]+) @ [\d.]+\s*\|\s*([\d,]+) @ [\d.]+\s*\|[^|]*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]*)\|", line)
        if not m:
            continue
        kp, kc, exp_d, settle = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", "")), date.fromisoformat(m.group(3)), m.group(4).strip()
        if settle and settle != "—":
            continue                                             # 已結算
        base = f"HK.HSI{exp_d.year % 100:02d}{exp_d.month:02d}{exp_d.day:02d}"
        exp[f"{base}P{pts_to_strike_code(kp)}"] = -1.0
        exp[f"{base}C{pts_to_strike_code(kc)}"] = -1.0
        src[f"{base}P{pts_to_strike_code(kp)}"] = src[f"{base}C{pts_to_strike_code(kc)}"] = "風揚 PAPER_TRADING.md 方向一"
    return exp, src


# ---------------------------------------------------------------- 對帳
def reconcile(risk: dict | None, positions_md: str, journal: tuple[dict, dict], today: date,
              state: dict, explanations: dict) -> tuple[str, dict, list[dict]]:
    futu = {}
    for p in (risk or {}).get("positions") or []:
        code, q = str(p.get("code", "")), num(p.get("qty"))
        if code and q is not None and abs(q) > 1e-9 and not re.match(r"^US\.SPCX$", code):
            futu[code] = futu.get(code, 0.0) + q
    reg, unparsed = parse_positions_md(positions_md)
    jexp, jsrc = journal
    codes = sorted(set(futu) | {c for c, q in reg.items()} | set(jexp))
    rows, mismatches = [], []
    new_state = {"date": today.isoformat(), "open": {}}
    for code in codes:
        f, r, j = futu.get(code), reg.get(code), jexp.get(code)
        team, use, _ = team_of(code)
        vals = [v for v in (f, r, j) if v is not None]
        ok = len(vals) >= 2 and all(abs(v - vals[0]) < 1e-9 for v in vals) and (f is not None or all(abs(v) < 1e-9 for v in vals))
        if f is None and r is not None and abs(r) < 1e-9 and (j is None or abs(j) < 1e-9):
            ok = True                                              # 登記空手、富途冇倉：一致
        status = "✅" if ok else "⚠"
        reason = ""
        if team in AUTO_TEAMS and not ok:                          # [R237] 龍飛陣程式自動：只列示
            status, reason = "🐉", "程式自動落單，以龍飛陣自己帳為準（唔計 ⚠）"
        elif not ok:
            ex = explanations.get(code) or {}
            prev = (state.get("open") or {}).get(code) or {}
            first = prev.get("first_seen") or today.isoformat()
            days = int(prev.get("days", 0)) + 1 if prev.get("last") != today.isoformat() else int(prev.get("days", 1))
            explained = bool(ex.get("reason")) and ex.get("date", "") >= first
            new_state["open"][code] = {"first_seen": first, "days": days, "last": today.isoformat(), "explained": explained}
            reason = ex.get("reason", "") if explained else f"（未解釋，第 {days} 日）"
            mismatches.append({"code": code, "team": team, "futu": f, "reg": r, "journal": j, "days": days, "explained": explained})
        rows.append((code, team, use, f, r, j, status, reason, jsrc.get(code, "")))
    escalate = [m for m in mismatches if m["days"] >= 2 and not m["explained"]]
    run_hkt = (risk or {}).get("run_hkt", "—")
    lines = [f"# 每日對帳表 {today.isoformat()}", "",
             f"富途快照：{run_hkt} HKT（futu/risk/latest.json）；POSITIONS.md 與各陣 journal 以產表時預設分支／各陣分支為準。",
             "手數：空為負。三方一致 ✅；不一致 ⚠（原因填 research/reconcile/explanations.json，連續兩個交易日未解釋升級 RISK_LADDER Ⓑ）。",
             "只係資訊、唔係落單指令。", "",
             "| 合約 | 陣 | 用途 | 富途快照 | POSITIONS.md | 陣 journal | 狀態 | 原因／備註 |",
             "|---|---|---:|---:|---:|---:|:-:|---|"]
    for code, team, use, f, r, j, status, reason, s in rows:
        lines.append(f"| {code} | {team} | {use} | {fmt_q(f)} | {fmt_q(r)} | {fmt_q(j)} | {status} | {reason}{('（' + s + '）') if s and not ok_src(status) else ''} |")
    if unparsed:
        lines += ["", "POSITIONS.md 未能解析嘅列（請用標準寫法或人手核對）：", *[f"- {u}" for u in unparsed]]
    if escalate:
        lines += ["", "## ⬆ 升級", *[f"- {m['code']}（{m['team']}）不一致已連續 {m['days']} 個交易日未解釋 → RISK_LADDER **Ⓑ 停開新倉**（該陣）" for m in escalate]]
    lines += ["", f"產表：{datetime.now(HKT).strftime('%Y-%m-%d %H:%M')} HKT，scripts/daily_books.py"]
    return "\n".join(lines) + "\n", new_state, escalate


def ok_src(status: str) -> bool:
    return status == "✅"


# ---------------------------------------------------------------- 損益帳
def pnl_row(risk: dict | None, deals: dict | None, ledger, today: date, ladder_level: str) -> dict:
    m = (risk or {}).get("metrics") or {}
    unreal = defaultdict(float)
    for p in (risk or {}).get("positions") or []:
        code, q, pl = str(p.get("code", "")), num(p.get("qty"), 0.0), num(p.get("futu_pl"))
        if pl is None or not q:
            continue
        fx = USD_HKD if code.startswith("US.") else 1.0
        parts = split_by_cap(code, q)
        for team, part in parts:
            unreal[team] += pl * fx * (part / q)
    real = defaultdict(float)
    for c in (deals or {}).get("closed") or []:
        v = num(c.get("realized_ccy"))
        if v is None:
            continue
        fx = USD_HKD if c.get("ccy") == "USD" else 1.0
        real[team_of(str(c.get("code", "")))[0]] += v * fx
    mt5 = 0.0
    if isinstance(ledger, list):
        for e in ledger:
            if not isinstance(e, dict):
                continue
            t = str(e.get("time_hkt") or e.get("hkt") or e.get("time") or "")[:10]
            if t == today.isoformat():
                mt5 += num(e.get("realized") or e.get("pnl") or e.get("amount"), 0.0)
    row = {"date": today.isoformat(), "run_hkt": (risk or {}).get("run_hkt", ""),
           "equity_total": num(m.get("equity")), "hard_stop": num(m.get("hard_stop")), "gap_to_hard_stop": num(m.get("gap")),
           "futu_equity": num(m.get("futu_equity")), "maintenance_margin": num(m.get("maintenance_margin")), "cushion": num(m.get("cushion")),
           "unrealized_total": num(m.get("pnl")), "mt5_realized_today": round(mt5, 2), "ladder": ladder_level,
           "deals_fetched_hkt": (deals or {}).get("fetched_hkt", "")}
    for team in TEAM_ORDER:
        key = re.sub(r"[・\s]", "_", team)
        row[f"unreal_{key}"] = round(unreal.get(team, 0.0), 2)
        row[f"real_{key}"] = round(real.get(team, 0.0), 2)
    return row


def upsert_csv(existing: str | None, row: dict) -> str:
    rows = []
    if existing:
        rows = list(csv.DictReader(io.StringIO(existing)))
    rows = [r for r in rows if r.get("date") != row["date"]]
    rows.append({k: ("" if v is None else v) for k, v in row.items()})
    fields = list(row.keys())
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in sorted(rows, key=lambda r: r.get("date", "")):
        w.writerow({k: r.get(k, "") for k in fields})
    return buf.getvalue()


# ---------------------------------------------------------------- 風控階梯
def is_night(t: datetime | None = None) -> bool:
    t = t or datetime.now(HKT)
    hm = t.hour * 60 + t.minute
    return hm >= 17 * 60 + 15 or hm < 3 * 60


def ladder_lines(night: bool) -> dict:
    if not night:
        return LADDER
    return {"cushion_hkd": {k: v * NIGHT_FACTOR for k, v in LADDER["cushion_hkd"].items()},
            "gap_pct": {k: v * NIGHT_FACTOR for k, v in LADDER["gap_pct"].items()},
            "stop_use": {k: v / NIGHT_FACTOR for k, v in LADDER["stop_use"].items()}}


def ladder_level(risk: dict | None, divergence_md: str = "", escalated_teams: tuple[str, ...] = (),
                 night: bool | None = None) -> tuple[str, list[str]]:
    """回傳 (最高等級 A–D, 觸發原因列表)。night=None 按而家 HKT 判斷。"""
    m = (risk or {}).get("metrics") or {}
    night = is_night() if night is None else night
    LADDER = ladder_lines(night)
    level, why = "A", []
    def bump(lv, msg):
        nonlocal level
        if LEVEL_ORDER[lv] > LEVEL_ORDER[level]:
            level = lv
        why.append(f"{LEVEL_NAME[lv]}：{msg}")
    cushion = num(m.get("cushion"))
    if cushion is not None:
        for lv in ("D", "C", "B"):
            if cushion < LADDER["cushion_hkd"][lv]:
                bump(lv, f"富途保證金緩衝 HK${cushion:,.0f} < {LADDER['cushion_hkd'][lv]:,}")
                break
    gap, eq = num(m.get("gap")), num(m.get("equity"))
    if gap is not None and eq:
        pct = gap / eq
        for lv in ("D", "C"):
            if pct < LADDER["gap_pct"][lv]:
                bump(lv, f"離硬止損只剩 {pct:.0%} < {LADDER['gap_pct'][lv]:.0%}")
                break
    for name, use in (m.get("stop_use") or {}).items():
        u = num(use)
        if u is None:
            continue
        for lv in ("D", "C"):
            if u >= LADDER["stop_use"][lv]:
                bump(lv, f"{name} 止損用量 {u:.0%} ≥ {LADDER['stop_use'][lv]:.0%}（該策略）")
                break
    for line in divergence_md.splitlines():
        if "🔴" in line and "|" in line:
            bump("B", f"偏離燈 🔴：{line.strip()[:60]}")
    for t in escalated_teams:
        bump("B", f"對帳不一致連續兩日未解釋（{t}）")
    return level, why


def topup_advice(risk: dict | None, level: str, why: list[str], night: bool) -> list[str]:
    """補倉／提款建議（只係資訊）。緩衝 < Ⓑ 線先建議補倉；Ⓓ 唔接受補倉代替平倉；
    硬止損／止損用量／偏離觸發嘅等級，補倉唔解決（入金唔會推遠硬止損，見 RISK_LADDER.md §5）。"""
    m = (risk or {}).get("metrics") or {}
    cushion = num(m.get("cushion"))
    if cushion is None:
        return []
    lines = ladder_lines(night)["cushion_hkd"]
    target = TOPUP["target_hkd"] * (NIGHT_FACTOR if night else 1)
    out = []
    if cushion < lines["B"]:
        amt = -(-(target - cushion) // TOPUP["round_hkd"]) * TOPUP["round_hkd"]
        if cushion < lines["D"]:
            out.append(f"💰 補倉：緩衝已穿 Ⓓ 線，唔接受補倉代替全平；平倉後再入金 HK${amt:,.0f} 補返緩衝到 HK${target:,.0f}")
        elif cushion < lines["C"]:
            out.append(f"💰 補倉：{TOPUP['c_minutes']} 分鐘內入金 HK${amt:,.0f}（緩衝補到 HK${target:,.0f}）可代替減半；做唔到就照減半")
        else:
            out.append(f"💰 補倉：建議入金 HK${amt:,.0f}（緩衝補到 HK${target:,.0f}）或減倉釋放同等保證金；"
                       f"{'下一個日盤開市前' if night else '今日夜盤 17:15 前'}完成")
    other = [w for w in why if "保證金緩衝" not in w and not w.startswith(LEVEL_NAME["B"])]
    if other and any(w.startswith((LEVEL_NAME["C"], LEVEL_NAME["D"])) for w in other):
        out.append("💰 補倉唔解決：硬止損／止損用量觸發嘅 Ⓒ／Ⓓ 照執行（入金唔可以用嚟攤平虧損倉）")
    if level == "A" and not out:
        floor = TOPUP["withdraw_floor_hkd"]
        room = cushion - floor
        if room > 0:
            out.append(f"🏧 可提款上限 HK${room // TOPUP['round_hkd'] * TOPUP['round_hkd']:,.0f}（提款後緩衝 ≥ HK${floor:,.0f}）；提款／入金後要同步改硬止損線")
    return out


def manual_limits(risk: dict | None, deals: dict | None) -> tuple[list[str], dict]:
    """人手交易額度：名義 ≤ NAV 50%、單日虧損（已實現＋未實現）≤ NAV 2%。超額只通報。
    人手 = 蛇蟠陣 HSI 期貨（使用者人手）＋ 使用者人手列（EW、MHI 超出對沖上限部分）。"""
    m = (risk or {}).get("metrics") or {}
    nav = num(m.get("equity"))
    notional, unreal, codes = 0.0, 0.0, []
    for p in (risk or {}).get("positions") or []:
        code, q = str(p.get("code", "")), num(p.get("qty"), 0.0)
        if not q:
            continue
        manual_q = sum(part for team, part in split_by_cap(code, q) if team in (TEAM_MANUAL, "蛇蟠陣"))
        if not manual_q:
            continue
        px = num(p.get("last")) or num(p.get("open_price")) or 0.0
        pv = next((v for rx, v in POINT_VALUE.items() if re.match(rx, code)), 1)
        fx = USD_HKD if code.startswith("US.") else 1.0
        notional += abs(manual_q) * px * pv * fx if not re.search(r"[CP]\d+", code) else abs(manual_q) * px * pv * fx
        pl = num(p.get("futu_pl"))
        if pl is not None:
            unreal += pl * fx * (manual_q / q)
        codes.append(f"{code} {fmt_q(manual_q)}")
    realized = 0.0
    for c in (deals or {}).get("closed") or []:
        team = team_of(str(c.get("code", "")))[0]
        if team in (TEAM_MANUAL, "蛇蟠陣"):
            realized += (num(c.get("realized_ccy"), 0.0)) * (USD_HKD if c.get("ccy") == "USD" else 1.0)
    out = {"nav": nav, "manual_notional_hkd": round(notional), "manual_unrealized_hkd": round(unreal), "manual_realized_today_hkd": round(realized), "codes": codes}
    why = []
    if nav:
        if notional > nav * MANUAL_LIMITS["notional_pct_nav"]:
            why.append(f"人手名義 HK${notional:,.0f} ＝ NAV {notional / nav:.0%} > {MANUAL_LIMITS['notional_pct_nav']:.0%}")
        loss = realized + unreal
        if loss < -nav * MANUAL_LIMITS["daily_loss_pct_nav"]:
            why.append(f"人手單日虧損 HK${loss:,.0f} ＝ NAV {-loss / nav:.1%} > {MANUAL_LIMITS['daily_loss_pct_nav']:.0%} → 建議停當日人手交易")
    return why, out


PRIVATE_DIR_OBJECT = "ops/books/reconcile_private"   # 含金額嘅完整對帳表（私人）


def strip_amounts(text: str) -> str:
    """公開版：拎走 HK$／US$ 金額同 NAV 百分比（repo 公開，金額＋手數可反推權益）。"""
    text = re.sub(r"(HK|US)\$-?[\d,]+(\.\d+)?", "（金額見私人版）", text)
    text = re.sub(r"＝?\s*NAV\s*[\d.]+%", "", text)
    text = re.sub(r"只剩\s*[\d.]+%", "低於線", text)
    return text


def tail_sections(level: str, why: list[str], mwhy: list[str], minfo: dict, night: bool,
                  topup: list[str] = ()) -> tuple[str, str]:
    """回傳 (公開版, 私人版) 嘅「風控階梯」＋「人手交易額度」兩段。公開版冇金額、冇 NAV 百分比。"""
    head = f"\n## 風控階梯\n現時 **{LEVEL_NAME[level]}**（{'夜盤線，日間線 ×' + str(NIGHT_FACTOR) if night else '日間線'}）"
    priv = head + ("：\n" + "\n".join(f"- {w}" for w in why) if why else "，冇觸發") + "\n"
    pub = head + ("：\n" + "\n".join(f"- {strip_amounts(w)}" for w in why) if why else "，冇觸發") + "\n"
    pub_topup = [t for t in topup if not t.startswith("🏧")]   # 提款上限反推得到緩衝，只放私人版
    priv += "".join(f"- {t}\n" for t in topup)
    pub += "".join(f"- {strip_amounts(t)}\n" for t in pub_topup)
    codes = "、".join(minfo.get("codes") or []) or "無"
    if minfo.get("nav"):
        priv += (f"\n## 人手交易額度\n人手持倉：{codes}；名義 HK${minfo['manual_notional_hkd']:,}"
                 f"（NAV {minfo['manual_notional_hkd'] / minfo['nav']:.0%}）；當日已實現 HK${minfo['manual_realized_today_hkd']:,}、"
                 f"未實現 HK${minfo['manual_unrealized_hkd']:,}。")
    else:
        priv += "\n## 人手交易額度\n（讀不到 NAV）"
    pub += f"\n## 人手交易額度\n人手持倉：{codes}（金額見私人版）。"
    verdict_ok = "額度內 ✅（名義 ≤ NAV 50%、單日虧損 ≤ NAV 2%）"
    priv += ("\n" + "\n".join(f"- ⚠ {w}" for w in mwhy) + "\n") if mwhy else f"\n{verdict_ok}\n"
    pub += ("\n" + "\n".join(f"- ⚠ {strip_amounts(w)}" for w in mwhy) + "\n") if mwhy else f"\n{verdict_ok}\n"
    return pub, priv


def ladder_message(level: str, why: list[str], today: date, topup: list[str] = ()) -> str:
    head = {"C": "🟠 Ⓒ 減半：請而家把觸發嘅策略倉位減半（使用者 10-13 同意直接提示）",
            "D": "⛔ Ⓓ 全平：請而家平倉（使用者 10-13 同意直接提示）"}.get(level, f"風控階梯 {LEVEL_NAME[level]}")
    return (f"【風控階梯 {today.isoformat()}】{head}\n" + "\n".join(f"- {w}" for w in [*why, *topup])
            + f"\n詳見 RISK_LADDER.md。{FOOTER}")


# ---------------------------------------------------------------- 主流程
def load_sources(args) -> tuple[dict | None, dict | None, dict | None, list | None]:
    if args.local_json:
        d = Path(args.local_json)
        rd = lambda n: json.loads((d / n).read_text(encoding="utf-8")) if (d / n).exists() else None
        return rd("futu_risk.json"), rd("futu_deals.json"), rd("futu_pnl.json"), rd("trade_ledger.json")
    risk = gcs_cat("futu/risk/latest.json")
    deals = gcs_cat(f"futu/deals/{args.day.isoformat()}.json")
    ledger = gcs_cat("logs/trade_ledger.json")
    return (risk if isinstance(risk, dict) else None, deals if isinstance(deals, dict) else None, None,
            ledger if isinstance(ledger, list) else None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD（HKT），預設今日")
    ap.add_argument("--dry-run", action="store_true", help="只印，唔寫 repo／GCS、唔發 TG")
    ap.add_argument("--no-tg", action="store_true")
    ap.add_argument("--local-json", help="測試：從目錄讀 JSON 代替 GCS")
    args = ap.parse_args()
    args.day = date.fromisoformat(args.date) if args.date else datetime.now(HKT).date()
    today = args.day

    risk, deals, _pnl, ledger = load_sources(args)
    if risk is None:
        print("⚠ 讀不到 futu/risk/latest.json，對帳表以空快照產出")
    positions_md = (ROOT / "POSITIONS.md").read_text(encoding="utf-8")
    journal = journal_expectations()
    RECON_DIR.mkdir(parents=True, exist_ok=True)
    state_f, expl_f = RECON_DIR / "state.json", RECON_DIR / "explanations.json"
    state = json.loads(state_f.read_text(encoding="utf-8")) if state_f.exists() else {}
    expl = json.loads(expl_f.read_text(encoding="utf-8")) if expl_f.exists() else {}
    md, new_state, escalate = reconcile(risk, positions_md, journal, today, state, expl)

    div_md = (ROOT / "research" / "divergence" / "DIVERGENCE.md").read_text(encoding="utf-8") \
        if (ROOT / "research" / "divergence" / "DIVERGENCE.md").exists() else ""
    level, why = ladder_level(risk, div_md, tuple(sorted({m["team"] for m in escalate})))
    mwhy, minfo = manual_limits(risk, deals)
    night = is_night()
    topup = topup_advice(risk, level, why, night)
    pub_tail, priv_tail = tail_sections(level, why, mwhy, minfo, night, topup)
    md_private = md + priv_tail
    md += pub_tail
    row = pnl_row(risk, deals, ledger, today, level)
    row.update({"manual_notional_hkd": minfo.get("manual_notional_hkd"), "manual_realized_today_hkd": minfo.get("manual_realized_today_hkd")})

    print_private(md_private)
    print_private("損益帳列：" + json.dumps(row, ensure_ascii=False))
    if args.dry_run:
        return 0
    (RECON_DIR / f"{today.isoformat()}.md").write_text(md, encoding="utf-8")
    (RECON_DIR / "latest.md").write_text(md, encoding="utf-8")
    state_f.write_text(json.dumps(new_state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    gcs_put(f"{PRIVATE_DIR_OBJECT}/{today.isoformat()}.md", md_private)
    gcs_put(f"{PRIVATE_DIR_OBJECT}/latest.md", md_private)
    existing = gcs_cat(PNL_OBJECT)
    gcs_put(PNL_OBJECT, upsert_csv(existing if isinstance(existing, str) else None, row))
    print(f"✅ 已寫 research/reconcile/{today.isoformat()}.md、latest.md、state.json（公開版，冇金額）；GCS {PNL_OBJECT}、{PRIVATE_DIR_OBJECT}/")

    # Telegram：⚠ 升級、階梯 Ⓒ／Ⓓ（同一等級每日最多一次）
    msgs = []
    if escalate:
        msgs.append(f"【每日對帳 {today.isoformat()}】⚠ 以下合約不一致連續兩個交易日未解釋，升級 Ⓑ 停開新倉：\n" +
                    "\n".join(f"- {m['code']}（{m['team']}）富途 {fmt_q(m['futu'])}／登記 {fmt_q(m['reg'])}／journal {fmt_q(m['journal'])}" for m in escalate) +
                    f"\n請喺 research/reconcile/explanations.json 填原因。{FOOTER}")
    prev = gcs_cat(LADDER_STATE_OBJECT)
    prev = prev if isinstance(prev, dict) else {}
    if level in ("C", "D") and not (prev.get("date") == today.isoformat() and prev.get("level") == level):
        msgs.append(ladder_message(level, why, today, topup))
    elif level == "B" and any(t.startswith("💰") for t in topup) and prev.get("topup_date") != today.isoformat():
        msgs.append(ladder_message(level, why, today, topup))   # Ⓑ 補倉提示：每日一次
        prev["topup_date"] = today.isoformat()
    if mwhy and prev.get("manual_date") != today.isoformat():
        msgs.append(f"【人手交易額度 {today.isoformat()}】\n" + "\n".join(f"- {w}" for w in mwhy) + f"\n超額只通報、唔干預。{FOOTER}")
        prev["manual_date"] = today.isoformat()
    gcs_put(LADDER_STATE_OBJECT, json.dumps({"date": today.isoformat(), "level": level, "why": why, "manual_date": prev.get("manual_date"),
                                                 "topup_date": prev.get("topup_date")}, ensure_ascii=False))
    for msg in msgs:
        print_private("TG → " + msg)
        if not args.no_tg:
            send_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
