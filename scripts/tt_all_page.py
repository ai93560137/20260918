#!/usr/bin/env python3
"""趨勢模板全部等權——月底名單網頁（自包含 HTML，讀 analysis/tt_all/<市場>_latest.json 與同日 CSV）。

    python3 scripts/tt_all_page.py                 # → analysis/tt_all/index.html
    python3 scripts/tt_all_page.py --market hk sg  # 只放這些市場

規格與判決見 stock_research/TT_MOMENTUM_BACKTEST.md；網頭與 Telegram 摘要由 scripts/tt_all_signal.py 產生。
"""
import argparse
import csv
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "tt_all"
ORDER = ["hk", "sg", "ca", "in", "au", "us", "jp", "tw", "kr"]

CSS = """
:root{color-scheme:light;--bg:#F6F5F0;--surface:#FFFFFF;--ink:#1E2A32;--muted:#6A7580;--rule:#E1DFD6;--accent:#0E6F68;--accent-ink:#0B5B55;
--ok-bg:#E3F2EE;--ok-ink:#0B5B55;--warn-bg:#FBEBD5;--warn-ink:#8A4B08;--star:#B7791F;--row:#F9F8F4}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#141A1E;--surface:#1B2328;--ink:#E7E5DF;--muted:#98A2AB;--rule:#2B353C;
--accent:#3FB8AE;--accent-ink:#7ADBD2;--ok-bg:#153A36;--ok-ink:#8FE0D6;--warn-bg:#4A2E0F;--warn-ink:#F3C77E;--star:#E2B45A;--row:#1F292F}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#141A1E;--surface:#1B2328;--ink:#E7E5DF;--muted:#98A2AB;--rule:#2B353C;
--accent:#3FB8AE;--accent-ink:#7ADBD2;--ok-bg:#153A36;--ok-ink:#8FE0D6;--warn-bg:#4A2E0F;--warn-ink:#F3C77E;--star:#E2B45A;--row:#1F292F}
body{background:var(--bg);color:var(--ink);font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif;line-height:1.5;padding-inline:16px;padding-block:20px 40px}
.wrap{max-width:960px;margin:0 auto;display:grid;gap:22px}
h1{font-size:1.5rem;margin:0;text-wrap:balance;letter-spacing:.01em}
h2{font-size:1.15rem;margin:0}
.sub{color:var(--muted);font-size:.92rem}
.nav{display:flex;flex-wrap:wrap;gap:8px}
.nav a{border:1px solid var(--rule);border-radius:999px;padding:4px 12px;text-decoration:none;color:var(--ink);font-size:.9rem;background:var(--surface)}
.nav a:focus-visible,.nav a:hover{outline:2px solid var(--accent);outline-offset:1px}
.market{display:grid;gap:12px;padding-block:8px;border-top:1px solid var(--rule)}
.head{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
.pill{display:inline-block;border-radius:6px;padding:2px 10px;font-weight:600;font-size:.9rem}
.ok{background:var(--ok-bg);color:var(--ok-ink)}.warn{background:var(--warn-bg);color:var(--warn-ink)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 16px;font-size:.92rem}
.stats div span{display:block;color:var(--muted);font-size:.8rem;letter-spacing:.04em}
.stats b{font-variant-numeric:tabular-nums;font-weight:600}
.tbl{overflow-x:auto;border:1px solid var(--rule);border-radius:8px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--rule)}
th{color:var(--muted);font-weight:500;font-size:.8rem;letter-spacing:.04em;position:sticky;top:0;background:var(--surface)}
td:nth-child(2),td:nth-child(3),th:nth-child(2),th:nth-child(3){text-align:left}
tbody tr:nth-child(even){background:var(--row)}
tr:last-child td{border-bottom:0}
.star{color:var(--star)}
.note{color:var(--muted);font-size:.86rem;max-width:68ch}
.rules{font-size:.9rem;display:grid;gap:6px;max-width:72ch}
.rules li{margin:0}
code{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.86em}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""


def load(mk: str):
    p = OUT / f"{mk}_latest.json"
    if not p.exists():
        return None, []
    meta = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    csvp = OUT / f"{mk}_{meta['date']}.csv"
    if csvp.exists():
        with open(csvp, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return meta, rows


def pct(x: str | float, digits: int = 0) -> str:
    try:
        return f"{float(x) * 100:+.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def section(meta: dict, rows: list[dict]) -> str:
    ok = meta["market_ok"]
    pill = '<span class="pill ok">✅ 本月持股</span>' if ok else '<span class="pill warn">⛔ 本月持現金</span>'
    chg = "" if meta.get("n_enter") is None else f'<div><span>較上月（{meta["prev_date"]}）</span><b>+{meta["n_enter"]} / −{meta["n_leave"]}</b></div>'
    cap_note = (f"★ = 40 檔版抽中（種子 {meta['seed']}）" if meta["n"] > meta["cap"] else "不足 40 檔，40 檔版 = 全部")
    trs = []
    for r in rows:
        star = '<span class="star">★</span>' if r.get("in40") == "1" and meta["n"] > meta["cap"] else ""
        trs.append(f"<tr><td>{star}</td><td>{html.escape(r['ticker'])}</td><td>{html.escape(r.get('name', ''))}</td>"
                   f"<td>{html.escape(r['close'])}</td><td>{pct(r['ret252'])}</td><td>{float(r['rs']):.0f}</td><td>{pct(r['above_200ma_pct'], 1)}</td></tr>")
    body = ("<tbody>" + "".join(trs) + "</tbody>") if trs else '<tbody><tr><td colspan="7" style="text-align:left">沒有股票通過趨勢模板</td></tr></tbody>'
    banner = "" if ok else '<p class="note">大市過濾未通過：本月不買入，名單只作記錄。持股中的舊倉按規則在月初開市全部賣出。</p>'
    test = '<span class="sub">（測試輸出，非月底）</span>' if meta.get("test") else ""
    return f"""
<section class="market" id="{meta['market']}">
  <div class="head"><h2>{meta['name']} <span class="sub">{meta['date']} · {meta.get('tier', '')}</span> {test}</h2>{pill}</div>
  <div class="stats">
    <div><span>基準 ETF 對 50 / 200 日線</span><b>{meta['etf']}　{pct(meta['etf_vs_ma50'], 1)} / {pct(meta['etf_vs_ma200'], 1)}</b></div>
    <div><span>通過趨勢模板</span><b>{meta['n']} 檔</b>（宇宙前 {meta['top_n']}）</div>
    {chg}
    <div><span>40 檔版</span><b>{cap_note}</b></div>
  </div>
  {banner}
  <div class="tbl"><table>
    <thead><tr><th></th><th>代號</th><th>名稱</th><th>收市</th><th>252 日報酬</th><th>RS 百分位</th><th>對 200 日線</th></tr></thead>
    {body}
  </table></div>
</section>"""


def build(markets: list[str]) -> str:
    metas = []
    secs = []
    for mk in markets:
        meta, rows = load(mk)
        if meta:
            metas.append(meta)
            secs.append(section(meta, rows))
    date = max(m["date"] for m in metas) if metas else "—"
    nav = "".join(f'<a href="#{m["market"]}">{m["name"]} {"✅" if m["market_ok"] else "⛔"} {m["n"]}</a>' for m in metas)
    return f"""<title>趨勢模板月底名單</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;600&family=IBM+Plex+Mono:wght@400&display=swap">
<style>{CSS}</style>
<div class="wrap">
  <header>
    <h1>趨勢模板全部等權 · 月底名單</h1>
    <p class="sub">數據日 {date}。等級：試行 = 回測相對等權顯著（港、新、加、印、澳）；觀察 = 日、美；不建議 = 台、韓（回測 alpha 不顯著，只作記錄）。月底收市選股，下一交易日開市等權買入，持有一個月不動。大市過濾未通過的市場整月持現金。規格凍結於 stock_research/TT_MOMENTUM_BACKTEST.md 第三部分；回測判定「有希望、未經前向驗證」，只作衛星倉。</p>
  </header>
  <nav class="nav">{nav}</nav>
  {''.join(secs)}
  <section class="market">
    <h2>規則</h2>
    <ol class="rules">
      <li>宇宙：該市場 60 日成交額中位數前 N 檔；剔除數據斷點股（一日 ±100%／−60% 的縫接、垃圾列）與指數／ETF 代號。</li>
      <li>趨勢模板（月底收市）：收市 &gt; 50 日 &gt; 150 日 &gt; 200 日均線；200 日均線高於 21 個交易日前；收市 ≥ 252 日低點 × 1.3；收市 ≥ 252 日高點 × 0.75；252 日報酬在宇宙內百分位 ≥ 70。</li>
      <li>大市過濾：基準 ETF 收市高於 50 日與 200 日均線才持股，否則整月現金。</li>
      <li>買入：下一交易日開市價，全部等權（40 檔版：超過 40 檔時隨機抽，種子 = 年月）。持有到下月底，中途不動。</li>
      <li>證偽：前向 12 個月相對當地 ETF 跑輸 15 個百分點，或相對全市場等權為負 → 停。</li>
    </ol>
    <p class="note">「對 200 日線」= 收市高於 200 日均線的幅度。RS 百分位 = 252 日報酬在宇宙內的排名。表內為原始收市價（按拆股還原、不按股息）。本頁不是投資建議；回測數字見 TT_ALL_INVESTOR_BRIEF.md。</p>
  </section>
</div>
"""


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", nargs="*", default=ORDER)
    args = a.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(build([m for m in ORDER if m in args.market]), encoding="utf-8")
    print(OUT / "index.html")


if __name__ == "__main__":
    main()
