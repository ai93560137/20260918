"""ops_notify.py — 純轉發型通報搬到 GitHub Actions（取代總指揮兩個 Claude Routine，FUND_SOP 缺口 2／6）。

兩個任務，都是「讀 GCS → 比對上次狀態 → 發 Telegram → 存狀態」，不需要模型判斷：

  hedge  雲垂對沖狀態通報（平日 14:35、15:55 HKT）
         讀 futu/risk/latest.json：MHI2610 實際淨手數、雲垂申報對沖手數（ops/notify_config.json）、
         其他策略手數 = 實際 − 申報、三個 Δ（straddle／含對沖淨 Δ／恒指全部）。
         淨手數與上次不同 → 加「淨手數有變動」；run_hkt 比現在舊 > 20 分鐘 → 標「數據過期」仍發。
         同一行另外寫到 GCS ops/hedge_status.txt，給雲垂工作階段 16:00 讀。

  deals  富途成交紀錄通報（平日 17:10 日盤、翌日 03:40 夜盤 HKT）
         讀 futu/deals/<日>.json（03:40 那次讀今日＋前一日）。fetched_hkt 未到門檻 → 一句提醒使用者、不通報。
         雲垂合約（HK.MHI／US.MES／US.EX／US.EW）逐筆列出、平倉列開倉價→平倉價、點數、已實現；
         其他合約只簡短列出。order_id 已通報過的不重複；沒有新成交就靜默。

狀態存 GCS ops/notify_state.json（用 gcp_agent.py put，只准寫 ops/）。只用標準庫 + requests（Telegram）。
每則訊息註明：只係資訊、唔係落單指令；已實現未計佣金，以富途 App 為準。不含帳號、權杖。

用法：
    python3 scripts/ops_notify.py --task auto|hedge|deals [--dry-run] [--now "2026-10-13 17:10"]
    --dry-run：讀真數據、印訊息，不發 Telegram、不寫狀態。
環境變數：TG_BOT_TOKEN、TG_CHAT_ID（發 Telegram 用；沒有就只印）。GCS 認證交給 gcp_agent.py（WIF 或 GCP_SA_KEY）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HKT = timezone(timedelta(hours=8))
CONFIG_PATH = ROOT / "ops" / "notify_config.json"


# ---------------------------------------------------------------- GCS（透過 gcp_agent.py）
def gcs_cat(obj: str) -> dict | None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gcp_agent.py"), "cat", "--object", obj],
                       capture_output=True, text=True)
    if r.returncode != 0:
        if "不存在" in (r.stderr + r.stdout):
            return None
        raise RuntimeError(f"gcp_agent cat {obj} 失敗：{(r.stderr or r.stdout)[:300]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"_text": r.stdout}


def gcs_put(obj: str, text: str) -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gcp_agent.py"), "put", "--object", obj, "--file", "-"],
                       input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gcp_agent put {obj} 失敗：{(r.stderr or r.stdout)[:300]}")


# ---------------------------------------------------------------- Telegram
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
def parse_hkt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=HKT)
        except ValueError:
            continue
    return None


def fmt_lots(x) -> str:
    if x is None:
        return "—"
    x = float(x)
    return f"{x:+.0f}" if x == int(x) else f"{x:+.2f}"


def fmt_delta(x) -> str:
    return "—" if x is None else f"{float(x):+.2f}"


FOOTER = "（只係資訊、唔係落單指令；富途報價只作監控，落單以券商即時價為準）"


# ---------------------------------------------------------------- hedge
def compose_hedge(risk: dict | None, state: dict, cfg: dict, now: datetime) -> tuple[str, dict]:
    """回傳 (訊息, 新狀態)。risk 為 None 代表讀不到快照。"""
    hc = cfg["hedge"]
    declared = hc["declared_hedge_lots"]
    limit = hc["delta_limit_lots"]
    if not risk:
        return (f"⚠️ 對沖狀態 {now.strftime('%H:%M')} HKT：讀不到 futu/risk/latest.json（auto_risk 可能未推送）。{FOOTER}", state)
    m = risk.get("metrics") or {}
    run_hkt = risk.get("run_hkt") or "—"
    run_dt = parse_hkt(run_hkt)
    stale = run_dt is not None and (now - run_dt) > timedelta(minutes=hc["stale_minutes"])
    lines = []
    changed = []
    for code, decl in declared.items():
        actual = (m.get("mhi_lots") or {}).get(code)
        if actual is None:
            for p in risk.get("positions") or []:
                if p.get("code") == code:
                    actual = p.get("qty")
        actual = 0.0 if actual is None else float(actual)
        other = actual - float(decl)
        short = code.split(".")[-1]
        lines.append(f"{short} 實際淨手數 {fmt_lots(actual)}｜雲垂對沖申報 {fmt_lots(decl)}／其他 {fmt_lots(other)}")
        prev = (state.get("hedge") or {}).get(code)
        if prev is not None and float(prev) != actual:
            changed.append(f"⚠ {short} 淨手數有變動：上次 {fmt_lots(prev)}，今次 {fmt_lots(actual)}，請雲垂同使用者確認係咪對沖變動")
        state.setdefault("hedge", {})[code] = actual
    dp = m.get("delta_parts") or {}
    if dp:
        delta_txt = (f"Δ 月跨式 {fmt_delta(dp.get('straddle'))}、含對沖淨 {fmt_delta(dp.get('net_with_hedge'))}、"
                     f"恒指全部 {fmt_delta(dp.get('hsi_all'))}（MHI 手，界線 ±{limit:g}）")
    else:
        d = m.get("delta") or {}
        first = next(iter(d.values()), None)
        net = first[0] if isinstance(first, list) and first else None
        delta_txt = f"Δ 月跨式 —、含對沖淨 {fmt_delta(net)}、恒指全部 —（MHI 手，界線 ±{limit:g}；auto_risk 未升級 R154）"
    head = f"🛡️ 對沖狀態 {now.strftime('%H:%M')} HKT｜數據 {run_hkt}" + ("｜⚠ 數據過期（auto_risk 可能停咗）" if stale else "")
    msg = "\n".join([head, *lines, delta_txt, *changed, FOOTER])
    state["hedge_last_run_hkt"] = run_hkt
    return msg, state


# ---------------------------------------------------------------- deals
def is_yunchui(code: str, cfg: dict) -> bool:
    return any(code.startswith(p) for p in cfg["deals"]["yunchui_prefixes"])


def compose_deals(files: dict[str, dict | None], state: dict, cfg: dict, now: datetime, run_kind: str) -> tuple[str | None, dict, str | None]:
    """files: {date: deals_json}. 回傳 (雲垂訊息或 None, 新狀態, 給使用者的提醒或 None)。"""
    dc = cfg["deals"]
    seen = set((state.get("deals") or {}).get("order_ids") or [])
    threshold = dc["day_run_min_fetched_hkt" if run_kind == "day" else "night_run_min_fetched_hkt"]
    today = now.strftime("%Y-%m-%d")
    newest = files.get(today)
    reminder = None
    if not newest:
        reminder = f"⚠️ 成交通報 {now.strftime('%H:%M')} HKT：futu/deals/{today}.json 不存在（auto_risk 可能未攞新版、停咗或 OpenD 斷線）。"
    else:
        f_dt = parse_hkt(newest.get("fetched_hkt"))
        need = datetime.strptime(f"{today} {threshold}", "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
        if f_dt is None or f_dt < need:
            reminder = (f"⚠️ 成交通報 {now.strftime('%H:%M')} HKT：futu/deals/{today}.json 的 fetched_hkt={newest.get('fetched_hkt')} "
                        f"未到 {threshold}（auto_risk 可能未攞新版、停咗或 OpenD 斷線），今次不通報。")
            return None, state, reminder
    yun, other, closed_lines, new_ids = [], [], [], []
    for day in sorted(files):
        doc = files[day]
        if not doc:
            continue
        for d in doc.get("deals") or []:
            oid = d.get("order_id") or f"{d.get('time_hkt')}|{d.get('code')}|{d.get('price')}"
            if oid in seen:
                continue
            new_ids.append(oid)
            line = f"{d.get('time_hkt', '')[5:16]} {d.get('code')} {d.get('side')} {fmt_lots(d.get('qty')).lstrip('+')} @ {d.get('price')}"
            (yun if is_yunchui(str(d.get("code")), cfg) else other).append(line)
        for c in doc.get("closed") or []:
            if not is_yunchui(str(c.get("code")), cfg):
                continue
            key = f"closed|{c.get('close_time_hkt')}|{c.get('code')}|{c.get('close_price')}"
            if key in seen:
                continue
            new_ids.append(key)
            closed_lines.append(f"{c.get('close_time_hkt', '')[5:16]} {c.get('code')} {c.get('side')} {fmt_lots(c.get('qty')).lstrip('+')}："
                                f"{c.get('open_price')} → {c.get('close_price')}，{c.get('realized_pts'):+g} 點，"
                                f"已實現 {c.get('realized_ccy'):+,.0f} {c.get('ccy')}")
    if not new_ids:
        return None, state, reminder
    state.setdefault("deals", {})["order_ids"] = (list(seen) + new_ids)[-2000:]
    state["deals"]["last_run"] = now.strftime("%Y-%m-%d %H:%M")
    if not yun and not closed_lines:
        # 只有非雲垂合約：給使用者簡短列出
        msg = "\n".join([f"🧾 富途成交 {now.strftime('%m-%d %H:%M')} HKT（非雲垂合約，只列給使用者）", *other[:20],
                         "（只係資訊；已實現未計佣金／費用，以富途 App 為準）"])
        return msg, state, reminder
    parts = [f"🧾 富途成交紀錄通報 {now.strftime('%m-%d %H:%M')} HKT（{'日盤' if run_kind == 'day' else '夜盤'}）→ 雲垂陣"]
    if yun:
        parts += ["逐筆：", *yun]
    if closed_lines:
        parts += ["平倉：", *closed_lines]
    if other:
        parts += [f"其他合約（非雲垂）{len(other)} 筆：", *other[:10]]
    parts.append("（平倉按 FIFO 配對、未計佣金／費用，以富途 App 為準。只係資訊、唔係落單指令；富途報價只作監控，落單以券商即時價為準。）")
    state["deals"]["status"] = {"date": today, "run_hkt": now.strftime("%Y-%m-%d %H:%M"), "run_kind": run_kind,
                                "closed": [c for day in sorted(files) for c in ((files[day] or {}).get("closed") or [])
                                           if is_yunchui(str(c.get("code")), cfg)],
                                "n_yunchui_deals": len(yun), "n_other_deals": len(other),
                                "summary_text": "；".join(closed_lines) if closed_lines else "雲垂合約今日無平倉"}
    return "\n".join(parts), state, reminder


# ---------------------------------------------------------------- main
def pick_task(now: datetime) -> str:
    hm = now.hour * 60 + now.minute
    # 14:35／15:55 → hedge；17:10 → deals 日盤；03:40 → deals 夜盤。前後 40 分鐘容忍排程延遲。
    for center, task in ((14 * 60 + 35, "hedge"), (15 * 60 + 55, "hedge"), (17 * 60 + 10, "deals"), (3 * 60 + 40, "deals")):
        if abs(hm - center) <= 40:
            return task
    return "hedge"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", choices=["auto", "hedge", "deals"], default="auto")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="覆寫現在時間（HKT，YYYY-MM-DD HH:MM），測試用")
    a = ap.parse_args()
    now = parse_hkt(a.now) if a.now else datetime.now(HKT)
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    task = pick_task(now) if a.task == "auto" else a.task
    state = gcs_cat(cfg["state_object"]) or {}
    if "_text" in state:
        state = {}
    print(f"[ops_notify] task={task} now={now.strftime('%Y-%m-%d %H:%M')} HKT dry_run={a.dry_run}")

    if task == "hedge":
        risk = gcs_cat("futu/risk/latest.json")
        msg, state = compose_hedge(risk, state, cfg, now)
        print(msg)
        if not a.dry_run:
            send_telegram(msg)
            gcs_put(cfg["hedge"]["status_object"], msg + "\n")
            gcs_put(cfg["state_object"], json.dumps(state, ensure_ascii=False, indent=1))
        return 0

    run_kind = "day" if now.hour >= 12 else "night"
    days = [now.strftime("%Y-%m-%d")] + ([(now - timedelta(days=1)).strftime("%Y-%m-%d")] if run_kind == "night" else [])
    files = {d: gcs_cat(f"futu/deals/{d}.json") for d in days}
    msg, state, reminder = compose_deals(files, state, cfg, now, run_kind)
    if reminder:
        print(reminder)
        if not a.dry_run:
            send_telegram(reminder)
    if msg:
        print(msg)
        if not a.dry_run:
            send_telegram(msg)
            gcs_put(cfg["state_object"], json.dumps(state, ensure_ascii=False, indent=1))
            status = (state.get("deals") or {}).get("status")
            if status:
                gcs_put(cfg["deals"].get("status_object", "ops/deals_status.json"), json.dumps(status, ensure_ascii=False, indent=1))
    elif not reminder:
        print("沒有新成交，靜默。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
