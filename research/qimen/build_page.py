"""奇門遁甲陣記錄頁：由 predictions.csv（測市）同 readings.csv（測人、測事）產生 page.html。

用法：python3 research/qimen/build_page.py
頁面只顯示 repo 入面已 commit 嘅記錄；測人只顯示代號。
"""
import csv
import html
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HKT = timezone(timedelta(hours=8))


def load(name):
    with open(HERE / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def e(x):
    return html.escape(x or "")


def binom_p_one_sided(k, n):
    """P(X >= k), X ~ Bin(n, 0.5)."""
    if n == 0:
        return None
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def pill(status):
    cls = {"open": "open", "scored": "ok", "void": "void"}.get(status, "open")
    label = {"open": "未揭曉", "scored": "已對答案", "void": "作廢"}.get(status, status or "未揭曉")
    return f'<span class="pill {cls}">{e(label)}</span>'


def hitcell(h):
    if h == "1":
        return '<span class="hit">中</span>'
    if h == "0":
        return '<span class="miss">唔中</span>'
    return '<span class="na">—</span>'


def market_summary(rows):
    out = []
    for m in sorted({r["market"] for r in rows if r.get("market")}):
        rs = [r for r in rows if r["market"] == m and r.get("status") == "scored" and r.get("hit") in ("0", "1")]
        n = len(rs)
        k = sum(r["hit"] == "1" for r in rs)

        def rate(col):
            v = [r[col] for r in rs if r.get(col) in ("0", "1")]
            return f"{sum(x == '1' for x in v) / len(v):.0%}" if v else "—"

        p = binom_p_one_sided(k, n)
        out.append(
            f"<tr><td>{e(m)}</td><td class=num>{n}</td><td class=num>{(k / n if n else 0):.0%}</td>"
            f"<td class=num>{'—' if p is None else f'{p:.3f}'}</td><td class=num>{rate('hit_coin')}</td>"
            f"<td class=num>{rate('hit_up')}</td><td class=num>{rate('hit_prev')}</td>"
            f"<td class=num>{n}/100</td></tr>"
        )
    return "".join(out) or '<tr><td colspan="8" class="empty">未有已對答案嘅測市卦</td></tr>'


def build():
    preds = load("predictions.csv")
    reads = load("readings.csv")
    now = datetime.now(HKT).strftime("%Y-%m-%d %H:%M")

    def count(rows, **kw):
        return sum(all(r.get(k) == v for k, v in kw.items()) for r in rows)

    n_ren = count(reads, kind="測人")
    n_shi = count(reads, kind="測事")
    def read_rate(kind):
        v = [r for r in reads if r.get("kind") == kind and r.get("status") == "scored" and r.get("hit") in ("0", "1")]
        return f"{sum(r['hit'] == '1' for r in v)}/{len(v)}" if v else "—"

    scored_preds = [r for r in preds if r.get("status") == "scored" and r.get("hit") in ("0", "1")]
    pred_rate = f"{sum(r['hit'] == '1' for r in scored_preds)}/{len(scored_preds)}" if scored_preds else "—"

    pred_rows = "".join(
        f"<tr><td class=mono>{e(r['id'])}</td><td class=num>{e(r['true_solar'])}</td><td>{e(r['dun_ju'])}</td>"
        f"<td>{e(r['zhifu'])}／{e(r['zhishi'])}</td><td>{e(r['market'])}</td><td class=num>{e(r['window_start_hkt'])}</td>"
        f"<td><b>{e(r['call'])}</b> {e(r['strength'])}</td><td>{e(r['outcome_dir'])}</td><td>{hitcell(r.get('hit'))}</td>"
        f"<td>{pill(r.get('status'))}</td></tr>"
        for r in reversed(preds)
    ) or '<tr><td colspan="10" class="empty">未有記錄。使用者起局後，本陣喺驗證時段開始之前寫入。</td></tr>'

    read_rows = "".join(
        f"<tr><td class=mono>{e(r['id'])}</td><td>{e(r['kind'])}</td><td class=mono>{e(r['subject'])}</td>"
        f"<td>{e(r['question'])}</td><td class=num>{e(r['true_solar'])}</td><td>{e(r['dun_ju'])}</td>"
        f"<td>{e(r['judgement'])}</td><td class=num>{e(r['deadline_hkt'])}</td><td>{e(r['outcome'])}</td>"
        f"<td>{hitcell(r.get('hit'))}</td><td>{pill(r.get('status'))}</td></tr>"
        for r in reversed(reads)
    ) or '<tr><td colspan="11" class="empty">未有記錄。</td></tr>'

    page = TEMPLATE
    for k, v in {
        "{{NOW}}": now,
        "{{N_PRED}}": str(len(preds)),
        "{{N_REN}}": str(n_ren),
        "{{N_SHI}}": str(n_shi),
        "{{RATE_SHI_MKT}}": pred_rate,
        "{{RATE_REN}}": read_rate("測人"),
        "{{RATE_SHI}}": read_rate("測事"),
        "{{MKT}}": market_summary(preds),
        "{{PRED_ROWS}}": pred_rows,
        "{{READ_ROWS}}": read_rows,
    }.items():
        page = page.replace(k, v)
    (HERE / "page.html").write_text(page, encoding="utf-8")
    print("wrote", HERE / "page.html")


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-Hant-HK">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>奇門遁甲陣記錄簿</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root {
  /* 佈局：一欄帳簿，摘要格 → 方法 → 測市表 → 測人測事表 → 規矩 */
  --ink: #1b2330; --paper: #f4f5f2; --card: #ffffff; --line: #d9ddd6;
  --accent: #8a1c1c; --muted: #5f6873;
  --ok: #1f7a4d; --warn: #9a6a00; --bad: #a12b2b;
  --display: "Noto Serif TC", "Songti TC", serif;
  --body: "Noto Sans TC", "PingFang HK", "Microsoft JhengHei", sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ink: #e6e8ea; --paper: #14181d; --card: #1c2229; --line: #2f3740;
    --accent: #e0736a; --muted: #9aa3ad; --ok: #5cc28e; --warn: #e0b04a; --bad: #ef7d7d;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --ink: #e6e8ea; --paper: #14181d; --card: #1c2229; --line: #2f3740;
  --accent: #e0736a; --muted: #9aa3ad; --ok: #5cc28e; --warn: #e0b04a; --bad: #ef7d7d;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.6 var(--body); }
main { max-width: 1100px; margin: 0 auto; padding: 28px 16px 48px; display: grid; gap: 28px; }
h1, h2 { font-family: var(--display); text-wrap: balance; margin: 0; }
h1 { font-size: 30px; color: var(--accent); }
h2 { font-size: 20px; border-bottom: 2px solid var(--accent); padding-bottom: 4px; }
p { margin: 0; max-width: 68ch; }
.sub { color: var(--muted); font-size: 14px; }
.banner { border-left: 4px solid var(--warn); background: var(--card); padding: 10px 14px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.tile { background: var(--card); border: 1px solid var(--line); padding: 12px 14px; }
.tile b { display: block; font: 700 26px var(--display); font-variant-numeric: tabular-nums; }
.tile span { color: var(--muted); font-size: 13px; }
section { display: grid; gap: 12px; }
.wrap { overflow-x: auto; background: var(--card); border: 1px solid var(--line); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; white-space: nowrap; }
th { color: var(--muted); font-weight: 500; background: var(--paper); }
td.num { font-variant-numeric: tabular-nums; }
td.mono { font-family: ui-monospace, Menlo, monospace; font-size: 13px; }
td.empty { color: var(--muted); text-align: center; padding: 18px; white-space: normal; }
.pill { font-size: 12px; padding: 1px 8px; border: 1px solid currentColor; }
.pill.open { color: var(--warn); } .pill.ok { color: var(--ok); } .pill.void { color: var(--muted); }
.hit { color: var(--ok); font-weight: 700; } .miss { color: var(--bad); font-weight: 700; } .na { color: var(--muted); }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0; background: var(--card); border: 1px solid var(--line); padding: 14px; }
dt { color: var(--muted); } dd { margin: 0; }
ol { margin: 0; padding-left: 22px; display: grid; gap: 4px; max-width: 72ch; }
@media (max-width: 480px) { dl { grid-template-columns: 1fr; } dd { margin-bottom: 6px; } }
</style>
</head>
<body>
<main>
<header style="display:grid;gap:6px">
  <h1>奇門遁甲陣記錄簿</h1>
  <p class="sub">占卦、測市、佈陣、測人、測事。使用者起局，本陣記錄同分析。更新：{{NOW}}（香港時間）</p>
</header>

<p class="banner">全部紙上。占卦結果唔係落單指令。測人、測事由 2026-11-13 起計分；測市評分表已批，等定咗市場同起局時間先開始計分。</p>

<div class="tiles">
  <div class="tile"><b>{{N_PRED}}</b><span>測市卦｜命中 {{RATE_SHI_MKT}}</span></div>
  <div class="tile"><b>{{N_REN}}</b><span>測人卦｜命中 {{RATE_REN}}</span></div>
  <div class="tile"><b>{{N_SHI}}</b><span>測事卦｜命中 {{RATE_SHI}}</span></div>
</div>

<section>
  <h2>起局方法 v1</h2>
  <dl>
    <dt>盤種</dt><dd>時家奇門，每個時辰一局</dd>
    <dt>定局</dt><dd>拆補法</dd>
    <dt>盤式</dt><dd>轉盤，中五寄坤二</dd>
    <dt>時間</dt><dd>英國真太陽時（UTC＋經度修正＋均時差）；經度約 0.25°E</dd>
    <dt>換日</dt><dd>真太陽時 23:00 起當翌日子時</dd>
    <dt>節氣</dt><dd>天文交節時刻，換算英國時間</dd>
    <dt>起局</dt><dd>使用者起局，本陣記錄、分析、對答案</dd>
    <dt>分析依據</dt><dd>使用者提供嘅知識庫（私人存放）；唔上網搵</dd>
    <dt>用神</dt><dd>測人測事按知識庫「用神嘅種類」；測市按評分表 v1（時干宮 ×2＋生門宮＋戊宮）</dd>
  </dl>
</section>

<section>
  <h2>測市計分</h2>
  <p class="sub">每個市場要 100 個非棄權卦先判；三關：單尾二項 p &lt; 0.05（即 ≥ 59/100）、高過永遠估升同前一日方向、高過擲毫。</p>
  <div class="wrap"><table>
    <thead><tr><th>市場</th><th>已計分</th><th>命中率</th><th>二項 p</th><th>擲毫</th><th>永遠估升</th><th>前一日方向</th><th>進度</th></tr></thead>
    <tbody>{{MKT}}</tbody>
  </table></div>
</section>

<section>
  <h2>測市記錄</h2>
  <div class="wrap"><table>
    <thead><tr><th>編號</th><th>真太陽時</th><th>局</th><th>值符／值使</th><th>市場</th><th>驗證開始</th><th>判斷</th><th>實際</th><th>中否</th><th>狀態</th></tr></thead>
    <tbody>{{PRED_ROWS}}</tbody>
  </table></div>
</section>

<section>
  <h2>測人、測事記錄</h2>
  <p class="sub">測人只用代號，唔顯示真名或私人資料。測人、測事、測市三類命中率分開計，唔混埋。</p>
  <div class="wrap"><table>
    <thead><tr><th>編號</th><th>類別</th><th>代號</th><th>所問</th><th>真太陽時</th><th>局</th><th>判斷</th><th>揭曉期限</th><th>結果</th><th>中否</th><th>狀態</th></tr></thead>
    <tbody>{{READ_ROWS}}</tbody>
  </table></div>
</section>

<section>
  <h2>規矩</h2>
  <ol>
    <li>每卦喺驗證時段或揭曉之前 commit 入 repo；commit 時間遲過開始時間就作廢。</li>
    <li>寫低之後判斷唔改，只加結果欄；打錯都只喺備註補。</li>
    <li>起局方法寫死；改方法就升版本、重新登記、重新計數。</li>
    <li>唔落單、唔改任何服務；真倉要使用者經總指揮親口批。</li>
  </ol>
</section>
</main>
</body>
</html>
"""

if __name__ == "__main__":
    build()
