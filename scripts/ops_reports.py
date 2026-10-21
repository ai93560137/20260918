"""ops_reports.py — 週報（FUND_SOP 缺口 7）與月報（缺口 9）。只讀、不重算，原料都是別人每日產出的檔。

  週報  每週日 09:00 HKT（週日 03:37 評分卡／偏離監控跑完之後）
        一、本週損益（ops/books/pnl_daily.csv 本週各列：權益變化、按陣已實現合計、未實現最新、階梯非 Ⓐ 日數）
        二、研究治理（IDEAS.md 狀態變化與新增列、評分卡判決、偏離燈；都跟 7 天前的版本比）
        三、要處理（本週對帳 ⚠ 次數與合約、心跳紅燈次數與項目）
        四、建議改 IDEAS 狀態（評分卡出 🔍／☠️、偏離 🟡／🔴 的列）
        五、下週事件（calendar/WEEK.md「下週」節）
        季初那週加一行「季度棄用清單重讀」

  月報  每月 1 日 09:30 HKT，報上一個月
        一、權益與回撤（月初→月末、月報酬、月內最大回撤、最差一日）
        二、按陣貢獻（已實現合計、月末未實現）
        三、風控（各階梯日數、人手額度超標日數）
        四、研究與流水線（IDEAS 本月變動、評分卡判決、心跳紅燈日數）
        五、下月到期與事件（calendar/events.csv 的持倉到期、結算、FOMC、假期）

輸出：Telegram（含權益，私人，超過 3,900 字分段）；全文存 GCS ops/reports/weekly/<日>.md、ops/reports/monthly/<YYYY-MM>.md。
     公開版（不含權益絕對值）併入 GCS ops/reports/public.json（各留 12 份），tnt-hk.com/?view=fund_report 顯示。
不 commit 進 repo（含權益）。

用法：python3 scripts/ops_reports.py weekly|monthly [--dry-run] [--show-private] [--now "2026-10-18 09:00"]
（預設只印公開版：Actions 日誌係公開嘅；--show-private 先連完整版印。）
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
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ops_notify import HKT, gcs_cat, gcs_put, parse_hkt, print_private, send_telegram  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FOOTER = "只係資訊、唔係落單指令；富途報價只作監控，落單以券商即時價為準。"
LADDER = {"A": "Ⓐ", "B": "Ⓑ", "C": "Ⓒ", "D": "Ⓓ"}


# ---------------------------------------------------------------- 讀檔（含「某日當時的版本」）
def read_repo(rel: str) -> str | None:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


def repo_as_of(rel: str, when: datetime) -> str | None:
    """rel 在 when 之前最後一個 commit 的版本。先試本機 git，淺 clone 拿不到就用 GitHub API。"""
    r = subprocess.run(["git", "-C", str(ROOT), "log", "-1", f"--before={when.isoformat()}", "--format=%H", "--", rel],
                       capture_output=True, text=True)
    sha = r.stdout.strip()
    if sha:
        r2 = subprocess.run(["git", "-C", str(ROOT), "show", f"{sha}:{rel}"], capture_output=True, text=True)
        if r2.returncode == 0:
            return r2.stdout
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return None
    import requests
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    c = requests.get(f"https://api.github.com/repos/{repo}/commits", headers=h, timeout=30,
                     params={"path": rel, "until": when.astimezone(HKT).isoformat(), "per_page": 1,
                             **({"sha": os.environ["GITHUB_REF_NAME"]} if os.environ.get("GITHUB_REF_NAME") else {})})
    if c.status_code != 200 or not c.json():
        return None
    raw = requests.get(f"https://raw.githubusercontent.com/{repo}/{c.json()[0]['sha']}/{rel}",
                       headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return raw.text if raw.status_code == 200 else None


def gcs_text(obj: str) -> str | None:
    try:
        v = gcs_cat(obj)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(v, dict) and set(v) == {"_text"}:
        return v["_text"]
    return None if v is None else (v if isinstance(v, str) else None)


def pnl_rows() -> list[dict]:
    text = gcs_text("ops/books/pnl_daily.csv")
    return list(csv.DictReader(io.StringIO(text))) if text else []


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def hk(x) -> str:
    return "—" if x is None else f"HK${x:,.0f}"


# ---------------------------------------------------------------- 損益
def pnl_section(rows: list[dict], start: date, end: date, title: str, ladder_line: bool = True,
                public: bool = False) -> tuple[list[str], dict]:
    """public=True：給公開網頁用，不列權益絕對值（只列報酬率、回撤、最差一日百分比）；按陣盈虧照列（策略總表本已公開）。"""
    sel = [r for r in rows if start <= date.fromisoformat(r["date"]) <= end]
    out = [title]
    stats: dict = {"n": len(sel)}
    if not sel:
        return out + ["（這段期間逐日損益帳沒有資料）"], stats
    eq = [f(r.get("equity_total")) for r in sel]
    eq_valid = [x for x in eq if x is not None]
    prev = [r for r in rows if date.fromisoformat(r["date"]) < start]
    base = f(prev[-1].get("equity_total")) if prev else eq_valid[0] if eq_valid else None
    last = eq_valid[-1] if eq_valid else None
    if base and last:
        chg = last - base
        stats.update(base=base, last=last, chg=chg, ret=chg / base)
        note = "" if prev else "（期初取期間第一日，帳本由 2026-10-13 起）"
        out.append(f"合計權益報酬 {chg / base:+.2%}{note}" if public else
                   f"合計權益 {hk(base)} → {hk(last)}（{chg:+,.0f}，{chg / base:+.2%}）{note}")
    peak, mdd, worst = base or (eq_valid[0] if eq_valid else 0), 0.0, None
    series = ([base] if prev and base else []) + eq_valid
    for a, b in zip(series, series[1:]):
        if worst is None or b - a < worst[0]:
            worst = (b - a, (b - a) / a if a else 0.0)
    for x in series:
        peak = max(peak, x)
        if peak:
            mdd = max(mdd, (peak - x) / peak)
    stats["mdd"] = mdd
    if len(series) >= 2:
        w = (f"；最差一日 {worst[1]:+.2%}" if public else f"；最差一日 {worst[0]:+,.0f}") if worst else ""
        out.append(f"期間最大回撤 {mdd:.2%}{w}")
    teams = sorted({k[len("real_"):] for k in sel[0] if k.startswith("real_")})
    parts = []
    for t in teams:
        real = sum(f(r.get(f"real_{t}")) or 0 for r in sel)
        unreal = f(sel[-1].get(f"unreal_{t}")) or 0
        if real or unreal:
            parts.append(f"{t.replace('_', '・')} 已實現 {real:+,.0f}／期末未實現 {unreal:+,.0f}")
    if parts:
        out.append("按陣：" + "；".join(parts))
    mt5 = sum(f(r.get("mt5_realized_today")) or 0 for r in sel)
    if mt5:
        out.append(f"MT5 黃金已實現合計 {mt5:+,.2f}")
    levels: dict[str, int] = {}
    for r in sel:
        levels[r.get("ladder") or "?"] = levels.get(r.get("ladder") or "?", 0) + 1
    stats["levels"] = levels
    if ladder_line:
        out.append("風控階梯：" + "、".join(f"{LADDER.get(k, k)} {v} 日" for k, v in sorted(levels.items())))
    return out, stats


# ---------------------------------------------------------------- IDEAS.md 差異
def ideas_table(md: str | None) -> dict[str, dict]:
    rows = {}
    for ln in (md or "").splitlines():
        if not re.match(r"^\| \d+ \|", ln):
            continue
        c = [x.strip() for x in ln.strip("|").split("|")]
        status = next((x for x in c if re.match(r"^(💡|🔬|📊|📒|💼|📡|✅|☠️|⏸)", x)), "")
        rows[c[0]] = {"name": c[1], "status": status.split("（")[0].strip()[:30]}
    return rows


def ideas_diff(old_md: str | None, new_md: str | None) -> list[str]:
    old, new = ideas_table(old_md), ideas_table(new_md)
    if not old and new:
        return [f"IDEAS.md 期初未存在，本期新建，共 {len(new)} 列"]
    out = []
    for k, v in new.items():
        if k not in old:
            out.append(f"＋ #{k} {v['name'][:30]}（{v['status'] or '—'}）")
        elif old[k]["status"] != v["status"] and v["status"]:
            out.append(f"↻ #{k} {v['name'][:30]}：{old[k]['status'] or '—'} → {v['status']}")
    return out


def scorecard_verdicts(md: str | None) -> dict[tuple[str, str], str]:
    out, scr = {}, None
    for ln in (md or "").splitlines():
        m = re.match(r"^## (\w+)", ln)
        if m:
            scr = m.group(1)
        c = [x.strip() for x in ln.strip("|").split("|")] if ln.startswith("| ") else []
        if scr and len(c) >= 13 and c[1] == "10" and c[-1] in ("⏳", "🔍", "☠️"):
            out[(scr, c[0])] = f"{c[-1]}（已評分 {c[2]}，命中 {c[4]} 對照 {c[5]}）"
    return out


def divergence_lights(md: str | None) -> dict[str, str]:
    out = {}
    for ln in (md or "").splitlines():
        c = [x.strip() for x in ln.strip("|").split("|")] if ln.startswith("| ") else []
        if len(c) > 1 and c[1] in ("⚪", "🟢", "🟡", "🔴"):
            out[c[0]] = c[1]
    return out


def chunks(text: str, limit: int = 3900) -> list[str]:
    """Telegram 一則上限 4096 字：按段落切，單段太長再硬切。"""
    out, cur = [], ""
    for para in text.split("\n\n"):
        if len(para) > limit:
            if cur:
                out.append(cur)
                cur = ""
            while len(para) > limit:
                out.append(para[:limit])
                para = para[limit:]
        if cur and len(cur) + 2 + len(para) > limit:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    return out + ([cur] if cur else [])


# ---------------------------------------------------------------- 週報
def gcs_json(obj: str) -> dict | None:
    try:
        v = gcs_cat(obj)
    except Exception:  # noqa: BLE001
        return None
    return v if isinstance(v, dict) and "_text" not in v else None


def incident_lines(md: str | None, start: date, end: date) -> list[str]:
    """ops/INCIDENTS.md：本週新增嘅列，加埋所有未結案嘅列（缺口 D）。"""
    if not md:
        return ["事故登記：⚠ 讀不到 ops/INCIDENTS.md"]
    new, open_ = [], []
    for ln in md.splitlines():
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(c) < 8 or not re.match(r"\d{4}-\d{2}-\d{2}$", c[0]):
            continue
        d = date.fromisoformat(c[0])
        if start <= d <= end:
            new.append(f"{d:%m-%d} {c[1][:40]}（{c[7]}）")
        elif c[7] != "已結":
            open_.append(f"{d:%m-%d} {c[1][:40]}（{c[6]}）")
    out = [f"事故：本週新增 {len(new)} 宗" + ("：" + "；".join(new) if new else "")]
    if open_:
        out.append("事故未結（之前登記）：" + "；".join(open_))
    return out


USAGE_CONTEXT_ROTATE = 600_000      # 上下文超過就建議換新工作階段（FUND_SOP 二之三 缺口 A；使用者 10-15 定 60 萬）


def usage_lines(now_snap: dict | None, old_snap: dict | None) -> list[str]:
    """GCS ops/claude_usage/latest.json（SOP 顧問每週日 08:45 用 get_session 寫）：本週各工作階段 Claude 用量（API 等值美元）。"""
    if not now_snap:
        return ["Claude 用量：⚠ 讀不到 ops/claude_usage/latest.json"]
    old = {s["id"]: s for s in (old_snap or {}).get("sessions", [])}
    rows = []
    for s in now_snap.get("sessions", []):
        prev = old.get(s["id"], {}).get("cost_usd")
        week = s["cost_usd"] - prev if prev is not None and s["cost_usd"] >= prev else s["cost_usd"]
        rows.append((week, s, prev is None))
    rows.sort(key=lambda r: -r[0])
    total = sum(r[0] for r in rows)
    basis = "本週" if old_snap else "累計（未有上週快照）"
    out = [f"Claude 用量（{basis}，API 等值）：合計 ≈ US${total:,.0f}；7 日額度 {now_snap.get('rate_limit', '?')}"
           + (f"，{now_snap['resets_hkt']} 重置" if now_snap.get("resets_hkt") else "")]
    out.append("　" + "、".join(f"{s['name']} {w:,.0f}" for w, s, _ in rows[:6]))
    big = [f"{s['name']}（{s['context_tokens'] / 10000:.0f} 萬）" for _, s, _ in rows
           if s.get("context_tokens", 0) > USAGE_CONTEXT_ROTATE]
    if big:
        out.append("　上下文過長、建議換新工作階段：" + "、".join(big))
    return out


def longfei_api_line(reviews: dict[str, str | None]) -> str:
    """龍飛陣 Claude API 實際費用（另計，唔係訂閱額度）：GCS ops/longfei/reviews/<日>.md 每個「## Claude API 費用」表嘅合計列。"""
    days, total = [], 0.0
    for day, text in sorted(reviews.items()):
        if not text:
            continue
        cost, in_sec = 0.0, False
        for ln in text.splitlines():
            if ln.startswith("#"):
                in_sec = ln.startswith("## Claude API 費用")
            elif in_sec and ln.startswith("| **合計**"):
                m = re.search(r"\*\*([\d.,]+)\*\*", ln.split("|")[7] if ln.count("|") > 7 else "")
                if m:
                    cost += float(m.group(1).replace(",", ""))
        if cost:
            days.append(f"{day[5:]} {cost:.0f}")
            total += cost
    if not days:
        return "龍飛陣 Claude API（另計）：本週冇覆盤費用表"
    return f"龍飛陣 Claude API（另計，覆盤實數）：合計 ≈ US${total:,.0f}（" + "、".join(days) + "）"


def weekly(now: datetime, public: bool = False) -> str:
    today = now.date()
    mon = today - timedelta(days=today.weekday())        # 本週一（週日跑時 = 6 日前）
    week_ago = now - timedelta(days=7)
    parts = [f"🗓 週報 {mon:%m-%d}～{today:%m-%d}"]

    sec, _ = pnl_section(pnl_rows(), mon, today, "【一、本週損益】", public=public)
    parts.append("\n".join(sec))

    gov = ["【二、研究治理（對比 7 天前）】"]
    diff = ideas_diff(repo_as_of("IDEAS.md", week_ago), read_repo("IDEAS.md"))
    gov += diff or ["IDEAS.md 本週沒有狀態變化"]
    sc_now, sc_old = scorecard_verdicts(read_repo("research/screener_scorecard/SCORECARD.md")), \
        scorecard_verdicts(repo_as_of("research/screener_scorecard/SCORECARD.md", week_ago))
    for k, v in sc_now.items():
        changed = "（變！）" if sc_old.get(k) and sc_old[k][:2] != v[:2] else ""
        gov.append(f"評分卡 {k[0]}／{k[1]} h=10：{v}{changed}")
    dv_now, dv_old = divergence_lights(read_repo("research/divergence/DIVERGENCE.md")), \
        divergence_lights(repo_as_of("research/divergence/DIVERGENCE.md", week_ago))
    lit = [f"{v} {k[:24]}" + (f"（上週 {dv_old[k]}）" if dv_old.get(k) and dv_old[k] != v else "")
           for k, v in dv_now.items() if v != "⚪" or (dv_old.get(k) and dv_old[k] != v)]
    gov.append("偏離燈：" + ("、".join(lit) if lit else "全部 ⚪（樣本未夠）"))
    parts.append("\n".join(gov))

    todo = ["【三、要處理】"]
    warn_days, warn_codes = 0, {}
    for i in range(7):
        d = mon + timedelta(days=i)
        md = read_repo(f"research/reconcile/{d:%Y-%m-%d}.md")
        if not md:
            continue
        ws = [ln.split("|")[1].strip() for ln in md.splitlines() if ln.startswith("| ") and "| ⚠ |" in ln]
        if ws:
            warn_days += 1
            for w in ws:
                warn_codes[w] = warn_codes.get(w, 0) + 1
    todo.append(f"對帳 ⚠：{warn_days} 日" + (f"（{'、'.join(f'{k}×{v}' for k, v in warn_codes.items())}）" if warn_codes else ""))
    reds: dict[str, int] = {}
    hb_days = 0
    for i in range(7):
        d = mon + timedelta(days=i)
        txt = gcs_text(f"ops/heartbeat/{d:%Y-%m-%d}.txt")
        if not txt:
            continue
        hb_days += 1
        for ln in txt.splitlines():
            if ln.startswith("🔴 "):
                name = ln[2:].split("：")[0].strip()
                reds[name] = reds.get(name, 0) + 1
    todo.append(f"心跳紅燈（{hb_days} 日有紀錄）：" + ("、".join(f"{k}×{v}" for k, v in sorted(reds.items(), key=lambda kv: -kv[1])) or "無"))
    todo += incident_lines(read_repo("ops/INCIDENTS.md"), mon, today)
    if not public:
        todo += usage_lines(gcs_json("ops/claude_usage/latest.json"),
                            gcs_json(f"ops/claude_usage/{today - timedelta(days=7):%Y-%m-%d}.json"))
        todo.append(longfei_api_line({f"{d:%Y-%m-%d}": gcs_text(f"ops/longfei/reviews/{d:%Y-%m-%d}.md")
                                      for d in (today - timedelta(days=i) for i in range(7))}))
    parts.append("\n".join(todo))

    sug = ["【四、建議改 IDEAS 狀態】"]
    for k, v in sc_now.items():
        if v.startswith("🔍"):
            sug.append(f"評分卡 {k[0]}／{k[1]} 出 🔍 → IDEAS #14 考慮升「回測中」")
        elif v.startswith("☠️"):
            sug.append(f"評分卡 {k[0]}／{k[1]} 出 ☠️ → IDEAS #14 該市場改「棄用」並寫原因")
    for k, v in dv_now.items():
        if v in ("🟡", "🔴"):
            sug.append(f"偏離 {v} {k[:24]} → 依 RISK_LADDER（🔴 = Ⓑ 停開新倉），IDEAS 對應列註記")
    parts.append("\n".join(sug if len(sug) > 1 else sug + ["無"]))

    nxt = ["【五、下週事件】"]
    wk = read_repo("calendar/WEEK.md") or ""
    m = re.search(r"## 下週[^\n]*\n(.*?)(?:\n## |\Z)", wk, re.S)
    if m:
        head = re.search(r"## (下週[^\n]*)", wk).group(1)
        nxt.append(head)
        for ln in m.group(1).splitlines():
            c = [x.strip() for x in ln.strip("|").split("|")] if ln.startswith("| ") and "---" not in ln and "日期" not in ln else []
            if len(c) >= 5:
                nxt.append(f"{c[0]} {c[1]} {c[4]}")
    else:
        nxt.append("⚠ 讀不到 calendar/WEEK.md")
    parts.append("\n".join(nxt[:14]))

    if mon.month in (1, 4, 7, 10) and mon.day <= 7:
        parts.append("📌 季初：請重讀 IDEAS.md 第三節棄用清單，確認沒有舊想法換名字回來。")
    parts.append(FOOTER)
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 月報
def blotter_line(csv_text: str | None) -> str:
    """GCS ops/blotter/<月>.csv（scripts/ops_blotter.py）→ 按陣成交筆數同平均滑價點數（缺口 E）。"""
    if not csv_text:
        return "落單紀錄：本月冇 blotter（ops/blotter/<月>.csv）"
    from ops_blotter import summarize
    teams = summarize(list(csv.DictReader(io.StringIO(csv_text))), "")["teams"]
    parts = [f"{k} {v['fills']} 筆" + (f"（{v['with_intent']} 筆有意圖價，平均滑價 {v['avg_slip_pts']:+g} 點）"
                                       if v["with_intent"] else "（冇意圖價）")
             for k, v in sorted(teams.items(), key=lambda kv: -kv[1]["fills"])]
    return "落單紀錄：" + "；".join(parts)


def monthly(now: datetime, public: bool = False) -> tuple[str, str]:
    first_this = now.date().replace(day=1)
    end = first_this - timedelta(days=1)
    start = end.replace(day=1)
    tag = f"{start:%Y-%m}"
    parts = [f"📘 月報 {tag}"]
    sec, st = pnl_section(pnl_rows(), start, end, "【一、權益、回撤與按陣貢獻】", ladder_line=False,
                          public=public)
    parts.append("\n".join(sec))

    risk = ["【二、風控】"]
    lv = st.get("levels") or {}
    risk.append("階梯：" + ("、".join(f"{LADDER.get(k, k)} {v} 日" for k, v in sorted(lv.items())) if lv else "無資料"))
    over = 0
    for i in range((end - start).days + 1):
        md = read_repo(f"research/reconcile/{start + timedelta(days=i):%Y-%m-%d}.md") or ""
        if re.search(r"## 人手交易額度.*?(超額|超標|⚠)", md, re.S):
            over += 1
    risk.append(f"人手額度超標日數：{over}")
    if not public:
        risk.append(blotter_line(gcs_text(f"ops/blotter/{tag}.csv")))
    parts.append("\n".join(risk))

    gov = ["【三、研究與流水線】"]
    month_end = datetime.combine(end, datetime.max.time()).replace(tzinfo=HKT)
    month_start = datetime.combine(start, datetime.min.time()).replace(tzinfo=HKT)
    diff = ideas_diff(repo_as_of("IDEAS.md", month_start), repo_as_of("IDEAS.md", month_end) or read_repo("IDEAS.md"))
    gov += diff[:15] or ["IDEAS.md 本月沒有狀態變化"]
    for k, v in scorecard_verdicts(repo_as_of("research/screener_scorecard/SCORECARD.md", month_end)
                                   or read_repo("research/screener_scorecard/SCORECARD.md")).items():
        gov.append(f"評分卡 {k[0]}／{k[1]}：{v}")
    red_days = 0
    for i in range((end - start).days + 1):
        txt = gcs_text(f"ops/heartbeat/{start + timedelta(days=i):%Y-%m-%d}.txt") or ""
        if "\n🔴 " in txt:
            red_days += 1
    gov.append(f"心跳有紅燈的日數：{red_days}")
    parts.append("\n".join(gov))

    ahead = ["【四、下月到期與事件】"]
    ev = read_repo("calendar/events.csv") or ""
    next_month = (first_this + timedelta(days=32)).replace(day=1)
    for r in csv.DictReader(io.StringIO(ev)):
        d = date.fromisoformat(r["date"])
        if first_this <= d < next_month and r["category"] in ("持倉到期", "HK 結算", "FOMC", "HK 假期", "US 假期"):
            ahead.append(f"{d:%m-%d} {r['event'][:50]}")
    if len(ahead) == 1:
        ahead.append("（日曆只涵蓋未來 35 天，未有資料）")
    parts.append("\n".join(ahead[:15]))
    parts.append(FOOTER)
    return "\n\n".join(parts), tag


PUBLIC_OBJ = "ops/reports/public.json"
KEEP = 12


def merge_public(index: dict | None, kind: str, key: str, text: str, now: datetime) -> dict:
    """公開版索引：{"weekly": [{"key","text","generated_hkt"}...], "monthly": [...]}，新的在前，各留 KEEP 份。"""
    index = index if isinstance(index, dict) else {}
    rows = [r for r in index.get(kind) or [] if isinstance(r, dict) and r.get("key") != key]
    rows.insert(0, {"key": key, "text": text, "generated_hkt": f"{now:%Y-%m-%d %H:%M}"})
    index[kind] = sorted(rows, key=lambda r: r["key"], reverse=True)[:KEEP]
    index["note"] = "公開版：不含權益絕對值；完整版只發 Telegram、存私人 ops/reports/<kind>/。由 scripts/ops_reports.py 產生。"
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["weekly", "monthly"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now")
    ap.add_argument("--show-private", action="store_true", help="連完整版（含權益）一併印出；只喺本機用")
    a = ap.parse_args()
    now = parse_hkt(a.now) if a.now else datetime.now(HKT)
    if a.kind == "weekly":
        key = f"{now:%Y-%m-%d}"
        text, web = weekly(now), weekly(now, public=True)
    else:
        (text, key), (web, _) = monthly(now), monthly(now, public=True)
    obj = f"ops/reports/{a.kind}/{key}.md"
    if a.show_private:                       # 本機用；Actions 日誌公開，預設只印公開版
        print_private(text + "\n")
    print("—— 公開版（tnt-hk.com/?view=fund_report）——\n" + web)
    if not a.dry_run:
        for part in chunks(text):
            send_telegram(part)
        gcs_put(obj, text + "\n")
        idx = gcs_cat(PUBLIC_OBJ)
        gcs_put(PUBLIC_OBJ, json.dumps(merge_public(idx, a.kind, key, web, now), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
