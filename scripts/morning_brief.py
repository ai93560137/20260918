"""morning_brief.py — 每日晨會簡報（FUND_SOP 缺口 2）：一則 Telegram，「只看這則也夠」。

平日 08:30 HKT，GitHub Actions `morning_brief.yml` 跑。只讀、不重算；原料都由別人產出：

  順序（先風險、再持倉、再今日事件、再今日要做）
  1. 風控：GCS futu/risk/latest.json（本機 auto_risk 每 15 分鐘，即時）＋ ops/books/ladder_state.json（總指揮 R173）
     → 階梯等級、保證金緩衝、離硬止損、止損線用量（≥ 50% 才列）、警報、數據新鮮度
  2. 金絲雀：repo canary/tg_daily.txt 的「🚦 三軸」段（06:30 已出）
  3. 昨日損益：GCS ops/books/pnl_daily.csv 最後一列（按陣已實現／未實現）
  4. 對帳：repo research/reconcile/latest.md 的 ⚠ 列與人手額度一行
  5. 偏離燈：repo research/divergence/DIVERGENCE.md 非 ⚪ 的列
  6. 今日事件：repo calendar/events.csv（事件日曆，每日 07:00）——事件週、未來 24 小時 High 數據、FOMC、
     3 日內持倉到期／恒指結算／假期；日曆讀不到才退回 GCS 財經日曆快取＋POSITIONS.md
  7. 今日要做：由日期推出（週五風揚方向一開新週、到期日、恒指結算週）

輸出：Telegram 一則；全文另存 GCS ops/brief/<日>.txt 與 ops/brief/latest.txt（含權益，私人，不進 repo）。
每個來源讀不到或過期就在該段寫 ⚠，不中斷整份簡報。

用法：python3 scripts/morning_brief.py [--dry-run] [--now "2026-10-14 08:30"]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops_notify import HKT, gcs_cat, gcs_put, parse_hkt, print_private, send_telegram  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FOOTER = "只係資訊、唔係落單指令；富途報價只作監控，落單以券商即時價為準。"
LADDER_NAME = {"A": "Ⓐ 觀察", "B": "Ⓑ 停開新倉", "C": "Ⓒ 減半", "D": "Ⓓ 全平"}


def read_repo(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


def hk(n) -> str:
    return "—" if n is None else f"HK${float(n):,.0f}"


def age_note(ts: datetime | None, now: datetime, max_min: int) -> str:
    if ts is None:
        return "（時間不明）"
    mins = (now - ts).total_seconds() / 60
    return f"⚠ 數據舊 {mins / 60:.1f} 小時" if mins > max_min else ""


# ---------------------------------------------------------------- 1. 風控
def section_risk(risk: dict | None, ladder: dict | None, now: datetime) -> list[str]:
    out = ["【一、風控】"]
    if ladder:
        why = "；".join(ladder.get("why") or []) or "冇觸發"
        out.append(f"階梯 {LADDER_NAME.get(ladder.get('level'), ladder.get('level'))}（{ladder.get('date')} 對帳表）：{why}")
    else:
        out.append("階梯 ⚠ 讀不到 ops/books/ladder_state.json")
    if not risk:
        out.append("⚠ 讀不到 futu/risk/latest.json（auto_risk 可能停咗）")
        return out
    m = risk.get("metrics") or {}
    run = risk.get("run_hkt")
    out.append(f"富途快照 {run} {age_note(parse_hkt(run), now, 60)}".rstrip())
    eq, hs = m.get("equity"), m.get("hard_stop")
    gap_pct = (m.get("gap") / eq * 100) if eq and m.get("gap") is not None else None
    out.append(f"合計權益 {hk(eq)}｜離硬止損 {hk(m.get('gap'))}"
               + (f"（{gap_pct:.0f}%）" if gap_pct is not None else "")
               + f"｜富途緩衝 {hk(m.get('cushion'))}（Ⓑ<15萬 Ⓒ<10萬 Ⓓ<6萬）")
    uses = {k: v for k, v in (m.get("stop_use") or {}).items() if v is not None}
    if uses:
        hi = sorted(uses.items(), key=lambda kv: -kv[1])
        out.append("止損線用量：" + "、".join(f"{k} {v:.0%}{' ⚠' if v >= 0.8 else ''}" for k, v in hi))
    dp = m.get("delta_parts") or {}
    if dp:
        out.append(f"Δ（MHI 手）：雲垂含對沖淨 {dp.get('net_with_hedge', 0):+.2f}（界線 ±0.5）｜恒指全部 {dp.get('hsi_all', 0):+.2f}")
    alerts = risk.get("alerts") or {}
    if alerts:
        out.append("警報：" + "；".join(f"{k} {v}" if not isinstance(v, (dict, list)) else str(k) for k, v in alerts.items()))
    return out


# ---------------------------------------------------------------- 2. 金絲雀
def section_canary(text: str | None, today: date) -> list[str]:
    out = ["【二、金絲雀】"]
    if not text:
        return out + ["⚠ 讀不到 canary/tg_daily.txt"]
    m = re.search(r"📅\s*(\d{4}-\d{2}-\d{2})", text)
    if m and m.group(1) != today.isoformat():
        out.append(f"⚠ 今日報告未出，沿用 {m.group(1)}")
    block = re.search(r"🚦[^\n]*\n(.*?)(?:\n\s*\n|\Z)", text, re.S)
    if not block:
        return out + ["（找不到三軸段）"]
    for ln in block.group(1).splitlines():
        ln = ln.strip()
        if ln:
            out.append(ln.split("|")[0].strip())   # 只留燈與狀態，數字細節留給金絲雀原文
    return out


# ---------------------------------------------------------------- 3. 昨日損益
def section_pnl(csv_text: str | None) -> list[str]:
    out = ["【三、昨日損益】"]
    if not csv_text or "_text" in str(type(csv_text)):
        return out + ["⚠ 讀不到 ops/books/pnl_daily.csv"]
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if not rows:
        return out + ["（帳本未有資料）"]
    r = rows[-1]
    out.append(f"{r.get('date')}（{r.get('run_hkt')}）未實現合計 {hk(_f(r.get('unrealized_total')))}；MT5 黃金當日已實現 {hk(_f(r.get('mt5_realized_today')))}")
    teams = sorted({k[len('unreal_'):] for k in r if k.startswith("unreal_")})
    parts = []
    for t in teams:
        u, z = _f(r.get(f"unreal_{t}")), _f(r.get(f"real_{t}"))
        if (u or 0) == 0 and (z or 0) == 0:
            continue
        parts.append(f"{t.replace('_', '・')} 已實現 {z or 0:+,.0f}／未實現 {u or 0:+,.0f}")
    if parts:
        out.append("按陣：" + "；".join(parts))
    if len(rows) >= 2:
        prev = _f(rows[-2].get("equity_total"))
        cur = _f(r.get("equity_total"))
        if prev and cur:
            out.append(f"合計權益對前一日 {cur - prev:+,.0f}")
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 4. 對帳
def section_reconcile(md: str | None) -> list[str]:
    out = ["【四、對帳】"]
    if not md:
        return out + ["⚠ 讀不到 research/reconcile/latest.md"]
    m = re.search(r"# 每日對帳表 (\S+)", md)
    rows = [ln for ln in md.splitlines() if ln.startswith("| ") and not ln.startswith("| 合約") and "---" not in ln]
    warn = [ln for ln in rows if "| ⚠ |" in ln]
    out.append(f"{m.group(1) if m else '?'}：{len(rows) - len(warn)} 合約一致 ✅、{len(warn)} 不一致 ⚠")
    for ln in warn[:5]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        out.append(f"⚠ {cells[0]}（{cells[1]}）：{cells[-1][:80]}")
    mm = re.search(r"## 人手交易額度\n(.*?)(?:\n## |\Z)", md, re.S)
    if mm:
        last = [ln for ln in mm.group(1).strip().splitlines() if ln.strip()]
        if last:
            out.append("人手：" + last[-1].strip())
    return out


# ---------------------------------------------------------------- 5. 偏離燈
def section_divergence(md: str | None) -> list[str]:
    out = ["【五、偏離監控】"]
    if not md:
        return out + ["⚠ 讀不到 research/divergence/DIVERGENCE.md"]
    lit = []
    for ln in md.splitlines():
        if not ln.startswith("| ") or "---" in ln:
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) > 1 and cells[1] in ("🟢", "🟡", "🔴"):
            lit.append(f"{cells[1]} {cells[0]}")
    m = re.search(r"更新 (\d{4}-\d{2}-\d{2})", md)
    out.append(("、".join(lit) if lit else "全部 ⚪（樣本未夠，未判燈）") + (f"（{m.group(1)} 週更）" if m else ""))
    return out


# ---------------------------------------------------------------- 6. 今日事件
def section_events_calendar(events_csv: str, now: datetime) -> list[str] | None:
    """讀 calendar/events.csv（事件日曆，每日 07:00 產生）。讀不到或格式不對回 None，改用舊路徑。"""
    rows = list(csv.DictReader(io.StringIO(events_csv)))
    if not rows or "event_week" not in rows[0]:
        return None
    out = ["【六、今日事件（HKT）】"]
    today = now.date()
    this_week = [r for r in rows if date.fromisoformat(r["date"]).isocalendar()[:2] == today.isocalendar()[:2]]
    if any(r.get("event_week") == "Y" for r in this_week):
        keys = [r["event"][:24] for r in this_week if r["category"] in ("FOMC", "HK 結算", "HK 假期")
                or (r["category"] == "數據" and r["impact"] == "High" and r["market"] in ("USD", "CNY", "HKD"))]
        out.append("⚠ 本週係事件週：" + "、".join(dict.fromkeys(keys))[:120])
    for r in rows:
        d = date.fromisoformat(r["date"])
        t = r["time_hkt"]
        if r["category"] == "數據" and r["impact"] == "High":
            try:
                dt = datetime.strptime(f"{r['date']} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=HKT)
            except ValueError:
                continue
            if now <= dt < now + timedelta(hours=24):
                out.append(f"{dt:%H:%M} {r['market']} {r['event']}" + (f"（{r['affects']}）" if r["affects"] else ""))
        elif r["category"] in ("FOMC",) and 0 <= (d - today).days <= 1:
            out.append(f"{'今日' if d == today else '明日'} {t} {r['event']}")
    for r in rows:
        d = date.fromisoformat(r["date"])
        days = (d - today).days
        if r["category"] in ("持倉到期", "HK 結算", "HK 假期", "US 假期") and 0 <= days <= 3:
            when = "今日" if days == 0 else f"{days} 日後"
            icon = {"持倉到期": "⏳", "HK 結算": "📅", "HK 假期": "🏖", "US 假期": "🏖"}[r["category"]]
            out.append(f"{icon} {when}（{d:%m-%d}）：{r['event']}")
    if len(out) == 1:
        out.append("未來 24 小時冇 High 級數據、3 日內冇到期／結算／假期")
    return out


def section_events(cal: dict | None, positions_md: str | None, now: datetime, events_csv: str | None = None) -> list[str]:
    if events_csv:
        got = section_events_calendar(events_csv, now)
        if got:
            return got
    out = ["【六、今日事件（HKT）】"]
    today = now.date()
    evs = []
    for e in (cal or {}).get("events") or []:
        if e.get("impact") != "High":
            continue
        try:
            t = datetime.fromisoformat(e["date"]).astimezone(HKT)
        except (KeyError, ValueError):
            continue
        # 今日 08:30 至明日 08:30（含美國夜盤）
        if now <= t < now + timedelta(hours=24):
            evs.append((t, f"{t:%H:%M} {e.get('country')} {e.get('title')}"))
    if cal is None:
        out.append("⚠ 讀不到財經日曆快取")
    elif evs:
        out += [s for _, s in sorted(evs)]
    else:
        out.append("未來 24 小時冇 High 級數據")
    for name, hold, end in parse_positions(positions_md):
        try:
            d = date.fromisoformat(end)
        except ValueError:
            continue
        days = (d - today).days
        if 0 <= days <= 3:
            short = hold.split("（")[0].strip()[:60]
            out.append(f"{'⏰ 今日到期' if days == 0 else f'⏳ {days} 日後到期'}：{name} {short}（{end}）")
    return out


def parse_positions(md: str | None) -> list[tuple[str, str, str]]:
    rows = []
    for ln in (md or "").splitlines():
        if not ln.startswith("| ") or ln.startswith("| 陣") or "---" in ln:
            continue
        c = [x.strip() for x in ln.strip("|").split("|")]
        if len(c) >= 7:
            m = re.search(r"\d{4}-\d{2}-\d{2}", c[5])
            if m and "持倉" in c[6]:
                rows.append((c[0], c[2], m.group(0)))
    return rows


# ---------------------------------------------------------------- 7. 今日要做
def hsi_settlement(d: date) -> date:
    """恒指期貨結算日 = 該月倒數第二個交易日（只扣週末，假期由各陣自己核對）。"""
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    days = [nxt - timedelta(days=i) for i in range(1, 8)]
    biz = [x for x in days if x.weekday() < 5]
    return biz[1]


def section_todo(today: date) -> list[str]:
    out = ["【七、今日要做】"]
    if today.weekday() == 4:
        out.append("🌬️ 風揚方向一：16:30 後開下一週 1σ 勒式（先看緩衝，< HK$26 萬唔開）")
    s = hsi_settlement(today)
    biz_left = sum(1 for i in range((s - today).days + 1) if (today + timedelta(days=i)).weekday() < 5) - 1
    if 0 <= biz_left <= 3:
        out.append(f"📅 恒指月結算 {s:%m-%d}（尚餘 {biz_left} 個交易日；轉倉週，蛇蟠／雲垂核對近月合約）")
    out.append("14:35／15:55 對沖狀態、17:10 成交通報（Actions）；16:00 雲垂對沖指令；17:20 對帳表")
    return out


# ---------------------------------------------------------------- main
def build(now: datetime, sources: dict) -> str:
    today = now.date()
    parts = [f"☀️ 晨會簡報 {today:%m-%d}（{'一二三四五六日'[today.weekday()]}）{now:%H:%M} HKT"]
    for sec in (section_risk(sources["risk"], sources["ladder"], now),
                section_canary(sources["canary"], today),
                section_pnl(sources["pnl"]),
                section_reconcile(sources["reconcile"]),
                section_divergence(sources["divergence"]),
                section_events(sources["calendar"], sources["positions"], now, sources.get("events_csv")),
                section_todo(today)):
        parts.append("\n".join(sec))
    parts.append(FOOTER)
    return "\n\n".join(parts)


def load_sources() -> dict:
    def safe(fn, *a):
        try:
            v = fn(*a)
            return None if isinstance(v, dict) and "_text" in v and len(v) == 1 and not v["_text"] else v
        except Exception as exc:  # noqa: BLE001  一個來源壞不擋整份
            print(f"⚠ {a}: {exc}", file=sys.stderr)
            return None
    pnl = safe(gcs_cat, "ops/books/pnl_daily.csv")
    return {
        "risk": safe(gcs_cat, "futu/risk/latest.json"),
        "ladder": safe(gcs_cat, "ops/books/ladder_state.json"),
        "pnl": pnl.get("_text") if isinstance(pnl, dict) else pnl,
        "calendar": safe(gcs_cat, "cache/ff_calendar_thisweek.json"),
        "canary": read_repo("canary/tg_daily.txt"),
        "reconcile": read_repo("research/reconcile/latest.md"),
        "divergence": read_repo("research/divergence/DIVERGENCE.md"),
        "positions": read_repo("POSITIONS.md"),
        "events_csv": read_repo("calendar/events.csv"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="覆寫現在時間（HKT，YYYY-MM-DD HH:MM）")
    a = ap.parse_args()
    now = parse_hkt(a.now) if a.now else datetime.now(HKT)
    text = build(now, load_sources())
    print_private(text)
    if not a.dry_run:
        send_telegram(text)
        gcs_put(f"ops/brief/{now:%Y-%m-%d}.txt", text + "\n")
        gcs_put("ops/brief/latest.txt", text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
