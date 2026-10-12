#!/usr/bin/env python3
"""HTF 每日掛單網頁 + PDF（2026-10-12）。讀 analysis/htf_daily/ 的 latest.json 與 CSV → index.html；--pdf 另出 PDF（Chromium headless）。

    python3 scripts/htf_page.py            # → analysis/htf_daily/index.html
    python3 scripts/htf_page.py --pdf      # 另出 analysis/htf_daily/htf_daily.pdf（Actions 內發 Telegram 用）
    python3 scripts/htf_page.py --names    # 先用 yfinance 補股票名稱（只在能連 Yahoo 的地方；結果存 names.json）
"""
import argparse
import csv
import html
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "htf_daily"
MKS = [("hk", "港股", "HKD"), ("tw", "台股", "TWD"), ("jp", "日股", "JPY"), ("us", "美股", "USD")]
FIT_T = {"hk": 3.58, "tw": 3.35, "jp": 2.57, "us": 1.48}   # 全期擬合 alpha t（research/htf_curvefit/<市場>.json）
TRAIL = {"ma10": "10 日線", "ma20": "20 日線", "ma50": "50 日線"}
NAMES_P = OUT / "names.json"

CSS = """
/* 版面：一張交易櫃台的「明日掛單單」——摘要在上，三個市場各一節：掛單 → 持倉 → 已平倉；規則與風險在最後 */
:root{
  --bg:#F3F5F7; --paper:#FFFFFF; --ink:#16202A; --muted:#5B6773; --rule:#D9DEE4; --row:#F7F9FA;
  --accent:#2F4B8F; --accent-soft:#E6EBF6; --buy:#1D6B47; --buy-soft:#E3F1EA; --sell:#A3271B; --sell-soft:#F8E6E3;
  --warn:#8A5A00; --warn-soft:#FBF0D9;
  --f-display:"Barlow Condensed","Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
  --f-body:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif;
  --f-data:"IBM Plex Mono","SFMono-Regular",Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#11161C; --paper:#18202A; --ink:#E6EAEE; --muted:#9AA6B2; --rule:#2A3542; --row:#1C2530;
  --accent:#8EA8E8; --accent-soft:#232F48; --buy:#6FCB9C; --buy-soft:#173326; --sell:#F08A7E; --sell-soft:#3A1E1B;
  --warn:#E8B95C; --warn-soft:#3A2D12; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#11161C; --paper:#18202A; --ink:#E6EAEE; --muted:#9AA6B2; --rule:#2A3542; --row:#1C2530;
  --accent:#8EA8E8; --accent-soft:#232F48; --buy:#6FCB9C; --buy-soft:#173326; --sell:#F08A7E; --sell-soft:#3A1E1B;
  --warn:#E8B95C; --warn-soft:#3A2D12; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:15px;line-height:1.55;padding-inline:16px;padding-block:20px 48px}
.wrap{max-width:980px;margin:0 auto;display:grid;gap:20px}
header{display:grid;gap:10px}
.eyebrow{font-family:var(--f-data);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
h1{font-family:var(--f-display);font-weight:600;font-size:clamp(28px,5vw,40px);letter-spacing:.01em;margin:0;line-height:1.1;text-wrap:balance}
h2{font-family:var(--f-display);font-weight:600;font-size:24px;margin:0;letter-spacing:.02em}
h3{font-size:14px;font-weight:600;margin:0;color:var(--muted);letter-spacing:.04em}
.lede{color:var(--muted);max-width:68ch;margin:0}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:flex;gap:10px;align-items:baseline;background:var(--paper);border:1px solid var(--rule);border-radius:8px;padding:8px 12px}
.chip b{font-family:var(--f-display);font-size:18px;font-weight:600}
.chip span{font-size:13px;color:var(--muted)}
.num{font-family:var(--f-data);font-variant-numeric:tabular-nums}
section.mk{background:var(--paper);border:1px solid var(--rule);border-radius:10px;padding:18px 18px 8px;display:grid;gap:14px;min-width:0}
.mk-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px}
.meta{font-size:13px;color:var(--muted)}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:600;white-space:nowrap}
.pill.buy{background:var(--buy-soft);color:var(--buy)}
.pill.sell{background:var(--sell-soft);color:var(--sell)}
.pill.warn{background:var(--warn-soft);color:var(--warn)}
.pill.idle{background:var(--accent-soft);color:var(--accent)}
.block{display:grid;gap:6px;min-width:0}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{font-weight:600;font-size:12px;color:var(--muted);text-align:right;padding:6px 8px;border-bottom:1.5px solid var(--ink);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
th:first-child,td:first-child,th.l,td.l{text-align:left}
tbody tr:nth-child(even){background:var(--row)}
td.tk{font-family:var(--f-data);font-weight:600}
td.tk small{display:block;font-family:var(--f-body);font-weight:400;color:var(--muted);font-size:12px;white-space:normal}
td.trig{font-weight:700;color:var(--accent)}
td.stop{color:var(--sell)}
.empty{color:var(--muted);font-size:14px;padding:6px 0 10px}
.note{font-size:13px;color:var(--muted);max-width:75ch}
.rules{background:var(--paper);border:1px solid var(--rule);border-radius:10px;padding:18px;display:grid;gap:12px}
.rules ol{margin:0;padding-left:1.3em;display:grid;gap:4px;max-width:75ch}
.foot{font-size:12px;color:var(--muted);border-top:1px solid var(--rule);padding-top:12px}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media print{
  @page{size:A4;margin:12mm 11mm 14mm}
  body{background:#fff;color:#000;font-size:11pt;padding:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .wrap{max-width:none;gap:10pt}
  section.mk,.rules{border-color:#bbb;break-inside:auto}
  .mk-head,h2,h3{break-after:avoid}
  thead{display:table-header-group}
  tr,.chip,.rules li{break-inside:avoid}
  .tbl{overflow:visible}
  td,th{white-space:normal}
}
"""


def load_names() -> dict:
    try:
        return json.loads(NAMES_P.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def fetch_names(tickers: list[str]) -> None:
    names = load_names()
    todo = [t for t in tickers if t not in names]
    if not todo:
        return
    try:
        import yfinance as yf
    except ImportError:
        return
    for t in todo:
        try:
            info = yf.Ticker(t).info
            names[t] = info.get("shortName") or info.get("longName") or ""
        except Exception:  # noqa: BLE001
            names[t] = ""
    NAMES_P.write_text(json.dumps(names, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8")
    if txt.startswith("（無）"):
        return []
    return list(csv.DictReader(txt.splitlines()))


def f(x, nd=2):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{v:,.{nd}f}" if abs(v) < 1e5 else f"{v:,.0f}"


def pct(x, nd=1, sign=True):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"


def price_nd(v: float) -> int:
    return 0 if v >= 1000 else (1 if v >= 100 else (2 if v >= 10 else 3))


def tk(t: str, names: dict) -> str:
    n = names.get(t, "")
    return f'<td class="tk">{html.escape(t)}' + (f"<small>{html.escape(n)}</small>" if n else "") + "</td>"


def action_pill(a: str) -> str:
    if a.startswith("明天開市全數賣出") or a.startswith("明天收市全數賣出"):
        cls = "sell"
    elif a.startswith("明天收市賣一半"):
        cls = "warn"
    else:
        cls = "idle"
    return f'<span class="pill {cls}">{html.escape(a)}</span>'


def section(mk: str, name: str, cur: str, names: dict) -> str:
    p = OUT / f"{mk}_latest.json"
    if not p.exists():
        return ""
    m = json.loads(p.read_text(encoding="utf-8"))
    c = m["params"]
    orders = read_csv(OUT / f"{mk}_orders_{m['date']}.csv")
    pos = read_csv(OUT / f"{mk}_positions.csv")
    closed = read_csv(OUT / f"{mk}_closed.csv")
    if c["mkt"]:
        mk_pill = '<span class="pill buy">大市過濾 ✓ 可開新倉</span>' if m["mkt_ok"] else '<span class="pill sell">大市過濾 ✗ 明天不開新倉</span>'
    else:
        mk_pill = '<span class="pill idle">不用大市過濾</span>'
    rows = []
    for r in orders:
        nd = price_nd(float(r["pivot"]))
        rows.append("<tr>" + tk(r["ticker"], names) +
                    f'<td class="num">{float(r["close"]):,.{nd}f}</td><td class="num trig">{float(r["pivot"]):,.{nd}f}</td>'
                    f'<td class="num">{pct(r["dist_pct"])}</td><td class="num">{float(r["max_open"]):,.{nd}f}</td>'
                    f'<td class="num stop">{float(r["stop_if_fill_at_pivot"]):,.{nd}f}</td><td class="num">{pct(r["adr"], 1, False)}</td>'
                    f'<td class="num">{pct(r["alloc_pct"], 0, False)}</td></tr>')
    t_orders = ('<div class="tbl"><table><thead><tr><th>代號</th><th>今天收市</th><th>觸發價（買入停損單）</th><th>距收市</th>'
                '<th>開市高於此就取消</th><th>停損（若在觸發價成交）</th><th>ADR</th><th>資金</th></tr></thead><tbody>'
                + "".join(rows) + "</tbody></table></div>") if rows else '<p class="empty">明天沒有掛單。</p>'
    prow = []
    for r in pos:
        nd = price_nd(float(r["fill"]))
        prow.append("<tr>" + tk(r["ticker"], names) +
                    f'<td class="num l">{r["entry_date"]}</td><td class="num">{float(r["fill"]):,.{nd}f}</td><td class="num">{r["held_days"]}</td>'
                    f'<td class="num">{float(r["units"]):g}</td><td class="num">{float(r["close"]):,.{nd}f}</td>'
                    f'<td class="num stop">{float(r["stop_tomorrow"]):,.{nd}f}</td><td class="num">{pct(r["pnl_pct"])}</td>'
                    f'<td class="l">{action_pill(r["action"])}</td></tr>')
    t_pos = ('<div class="tbl"><table><thead><tr><th>代號</th><th class="l">入場日</th><th>成交價</th><th>已持有（日）</th><th>剩餘份數</th>'
             '<th>今天收市</th><th>明天停損</th><th>浮動</th><th class="l">明天要做</th></tr></thead><tbody>' + "".join(prow) +
             "</tbody></table></div>") if prow else '<p class="empty">沒有持倉。</p>'
    if closed:
        rets = [float(r["ret_gross"]) for r in closed]
        crow = "".join("<tr>" + tk(r["ticker"], names) + f'<td class="num l">{r["entry_date"]}</td><td class="num l">{r["exit_date"]}</td>'
                       f'<td class="num">{pct(r["ret_gross"])}</td><td class="l" style="white-space:normal">{html.escape(r["exits"])}</td></tr>'
                       for r in closed[-15:])
        t_closed = (f'<p class="meta">前向已平倉 {len(closed)} 筆，平均 {pct(sum(rets) / len(rets))}（未扣成本），'
                    f'賺錢 {sum(x > 0 for x in rets)} 筆。最近 15 筆：</p>'
                    '<div class="tbl"><table><thead><tr><th>代號</th><th class="l">入場</th><th class="l">出場</th><th>回報</th><th class="l">明細</th></tr></thead><tbody>'
                    + crow + "</tbody></table></div>")
    else:
        t_closed = f'<p class="empty">前向紀錄由 {m["fwd_start"]} 起入場的交易算起，暫時未有平倉。</p>'
    spec = (f'旗桿 ≥ {c["g"]:.0%}、旗面回落 ≤ {c["d"]:.0%}、動能全市場前 {100 - c["mom_q"]}%、追價上限 {c["chase"]:.0%}、'
            f'停損 {c["stop"]} × ADR、' + ("不賣一半" if not c["partial"] else f'第 {c["partial"]} 日收市賣一半') +
            f'、收市破 {TRAIL[c["trail"]]}翌日開市賣、最長 {c["hold"]} 日')
    return f"""
<section class="mk" id="{mk}">
  <div class="mk-head"><h2>{name}</h2><div class="meta">數據至 {m['date']}（{cur}）　{mk_pill}</div></div>
  <div class="block"><h3>明日掛單（{len(orders)} 隻，按距離觸發價由近到遠）</h3>{t_orders}</div>
  <div class="block"><h3>持倉與明天動作（{len(pos)} 筆）</h3>{t_pos}</div>
  <div class="block"><h3>前向已平倉</h3>{t_closed}</div>
  <p class="note">本市場參數：{spec}。全期擬合 alpha t {FIT_T[mk]:.2f}{'（低於 1.5，相鄰參數全部不到 1.5，屬孤峰；使用者 2026-10-12 要求照樣加入）' if FIT_T[mk] < 1.5 else ''}。</p>
</section>"""


def build() -> str:
    names = load_names()
    secs, chips, dates = [], [], []
    for mk, name, cur in MKS:
        p = OUT / f"{mk}_latest.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        dates.append(m["date"])
        chips.append(f'<div class="chip"><b>{name}</b><span>掛單 <span class="num">{m["n_orders"]}</span>　持倉 <span class="num">{m["n_open"]}</span>'
                     f'　已平倉 <span class="num">{m["n_closed"]}</span></span></div>')
        secs.append(section(mk, name, cur, names))
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    try:
        mix = json.loads((ROOT / "research" / "htf_curvefit" / "investor_mix.json").read_text(encoding="utf-8"))
        stop_dd = f"{1.5 * mix['20%']['combined']['mdd'] * 100:.0f}%"
    except Exception:  # noqa: BLE001
        stop_dd = "說明書所列水平"
    d = max(dates) if dates else "—"
    return f"""<title>HTF 每日掛單</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600&family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+TC:wght@400;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
  <header>
    <div class="eyebrow">High Tight Flag · 港台日美 · 全期參數</div>
    <h1>HTF 每日掛單　{d}</h1>
    <p class="lede">每個交易日收市後更新。掛單用買入停損單：明天盤中升穿觸發價才成交，開市已高於上限就取消。下單後即設停損；持倉每天看「明天要做」。產生時間 {now}（香港時間）。</p>
    <div class="chips">{''.join(chips)}</div>
  </header>
  {''.join(secs)}
  <section class="rules">
    <h2>怎樣照做</h2>
    <ol>
      <li>掛單：在觸發價掛買入停損單（stop order）。開市價已高於「開市高於此就取消」，當天不買。美股名單在香港時間傍晚出，當晚美股開市執行。</li>
      <li>成交後即設停損：成交價 −（停損倍數 × ADR）；表內停損按「剛好在觸發價成交」計，實際以成交價重算。</li>
      <li>資金：每筆 = 20% × 波幅權重（表內「資金」欄），四個市場合計曝險不超過 100%。</li>
      <li>持倉照「明天要做」：持有、收市賣一半（之後停損移到成本）、或翌日開市全數賣出。</li>
      <li>在富途開實倉前，先在預設分支 POSITIONS.md 登記並通知總指揮。</li>
    </ol>
    <p class="note">每日 PDF 版隨 Telegram 一併發送（同一份內容，自動分頁，表格不會從中間斷開）。</p>
  </section>
  <p class="foot">參數由全期數據擬合選出（曲線擬合），未來表現大概率低於回測。回測與風險說明見投資人說明書 HTF_INVESTOR_BRIEF.pdf；證偽：前向 100 筆平均虧損，或回撤超過 {stop_dd}，即停。不構成投資建議。</p>
</div>"""


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--pdf", action="store_true")
    a.add_argument("--names", action="store_true")
    args = a.parse_args()
    if args.names:
        tks = []
        for mk, _, _ in MKS:
            p = OUT / f"{mk}_latest.json"
            if p.exists():
                m = json.loads(p.read_text(encoding="utf-8"))
                tks += [r["ticker"] for r in read_csv(OUT / f"{mk}_orders_{m['date']}.csv")]
                tks += [r["ticker"] for r in read_csv(OUT / f"{mk}_positions.csv")]
        fetch_names(tks)
    page = build()
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(OUT / "index.html", file=sys.stderr)
    if args.pdf:
        doc = OUT / "_print.html"
        doc.write_text('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"></head><body>' + page + "</body></html>", encoding="utf-8")
        chrome = os.environ.get("CHROME") or next((str(p) for p in [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium"),
                                                                     *Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")] if p.exists()), None)
        if not chrome:
            print("找不到 Chrome，只出 HTML", file=sys.stderr)
            return
        pdf = OUT / "htf_daily.pdf"
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                        f"--print-to-pdf={pdf}", doc.as_uri()], capture_output=True, timeout=120, env={**os.environ, "HOME": "/tmp"})
        doc.unlink(missing_ok=True)
        print(pdf, pdf.stat().st_size if pdf.exists() else "失敗", file=sys.stderr)


if __name__ == "__main__":
    main()
