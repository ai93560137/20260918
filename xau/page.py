"""🌌 天覆陣單一頁面：取代舊服務嘅投資人日誌／關卡開關／送單參數／錦囊執行單／錦囊九十筆五頁。
只讀 GCS，唔接受任何寫入（風控數字由環境變數定，改要經 env set）。"""
import html

import config
from market import fmt_hkt

CSS = """
:root{--p:#0f62fe;--ok:#198754;--bad:#dc3545;--warn:#d97706;--bg:#f4f7fb;--card:#fff;--t:#161616;--m:#6c757d}
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--t);margin:0;padding:16px}
.c{max-width:1050px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--m);font-size:13px;margin-bottom:14px}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:14px}
.card{background:var(--card);border-radius:10px;padding:14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h3{margin:0 0 8px;font-size:14px;color:var(--m);font-weight:600}.big{font-size:22px;font-weight:700}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}
th{color:var(--m);font-weight:600}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:12px;background:#eef}
"""


def esc(x):
    return html.escape("" if x is None else str(x))


def _pos_text(pos):
    if not pos:
        return "空倉"
    return (f"{'多' if pos['side'] > 0 else '空'} {pos['lots']:.2f} 手 @ {pos['entry']:.2f}｜止損 {pos.get('stop')}"
            f"｜止賺 {pos.get('target') or '—'}｜{fmt_hkt(pos['opened_ts'])} 開")


def render(status):
    """status = main.build_status() 嘅 dict。"""
    s = status
    st = s.get("stats") or {}
    mode = "實倉（EA 執行指令）" if s.get("execute") else "影子模式（只記錄，唔送單）"
    gate = s.get("gate") or {}
    gate_cls = "ok" if gate.get("status") == "OPEN" else "bad"
    rows_d = "".join(
        f"<tr><td class=mono>{esc(fmt_hkt(d.get('ts', 0), '%m-%d %H:%M'))}</td><td>{esc(d.get('price'))}</td>"
        f"<td><span class=tag>{esc(d.get('final') or d.get('action'))}</span>"
        f"{(' <small class=warn>AI 提 ' + esc(d.get('action')) + '</small>') if d.get('rejected') else ''}</td>"
        f"<td>{esc(d.get('reason'))}{('<br><small class=bad>擋：' + esc(d.get('rejected')) + '</small>') if d.get('rejected') else ''}"
        f"{('<br><small class=m>' + esc(d.get('applied')) + '</small>') if d.get('applied') and d.get('applied') != 'HOLD' else ''}</td>"
        f"<td class=mono>{esc(d.get('ms'))} ms<br>${esc(d.get('cost_usd'))}</td></tr>"
        for d in list(reversed(s.get("decisions") or []))[:60])
    rows_t = "".join(
        f"<tr><td class=mono>{esc(fmt_hkt(t['opened_ts']))} → {esc(fmt_hkt(t['closed_ts']))}</td>"
        f"<td>{'多' if t['side'] > 0 else '空'} {t['lots']:.2f}</td><td>{t['entry']:.2f} → {t['exit']:.2f}</td>"
        f"<td>{esc(t.get('reason'))}</td><td class=\"{'ok' if t['pnl_usd'] > 0 else 'bad'}\">{t['pnl_usd']:+.2f}</td></tr>"
        for t in list(reversed(s.get("trades") or []))[:40])
    risk = s.get("risk") or {}
    risk_rows = "".join(f"<tr><th>{esc(k)}</th><td class=mono>{esc(v)}</td></tr>" for k, v in risk.items())
    usage = s.get("usage_today") or {}
    return f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{esc(config.TEAM_EMOJI)} {esc(config.TEAM_NAME)}</title><style>{CSS}</style></head><body><div class=c>
<h1>{esc(config.TEAM_EMOJI)} {esc(config.TEAM_NAME)}｜{esc(config.SYMBOL)} CFD（MT5）</h1>
<div class=sub>Claude 每根 M1 收盤決策 · 硬性風控由程式把關 · {esc(mode)} · 更新 {esc(s.get('updated_hkt'))} HKT</div>
<div class=g>
<div class=card><h3>模式</h3><div class="big {'bad' if s.get('execute') else 'warn'}">{esc('實倉' if s.get('execute') else '影子')}</div><small>{esc(s.get('model'))}（effort {esc(s.get('effort'))}）{('＋篩選 ' + esc(s.get('gate_model'))) if s.get('gate_model') else ''}</small></div>
<div class=card><h3>電閘（讀舊服務）</h3><div class="big {gate_cls}">{esc(gate.get('status') or '未知')}</div><small>{esc(gate.get('reason'))}</small></div>
<div class=card><h3>市場</h3><div class=big>{esc(s.get('last_price') or '—')}</div><small>{esc(s.get('session'))}<br>M1 {esc(s.get('m1_bars'))} 根・M15 {esc(s.get('m15_bars'))} 根・{'開市' if s.get('market_open') else '休市'}</small></div>
<div class=card><h3>持倉（{'紙上' if not s.get('execute') else '真倉'}）</h3><div style="font-size:14px">{esc(_pos_text(s.get('position')))}</div></div>
<div class=card><h3>紙上成績</h3><div class="big {'ok' if st.get('pnl_usd', 0) >= 0 else 'bad'}">{st.get('pnl_usd', 0):+.2f} USD</div><small>{esc(st.get('n', 0))} 筆・勝 {esc(st.get('wins', 0))}・最大回撤 {esc(st.get('max_dd', 0))}・今日開倉 {esc(s.get('trades_today'))}</small></div>
<div class=card><h3>AI 今日用量</h3><div class=big>${esc(usage.get('cost_usd', 0))}</div><small>決策 {esc(usage.get('decide', 0))} 次・篩選 {esc(usage.get('screen', 0))} 次・p95 {esc(usage.get('p95_ms'))} ms</small></div>
</div>
<div class=card style="margin-bottom:14px"><h3>最近決策（最新在上）</h3><table><tr><th>HKT</th><th>價</th><th>動作</th><th>理由</th><th>延遲／費用</th></tr>{rows_d or '<tr><td colspan=5>未有</td></tr>'}</table></div>
<div class=card style="margin-bottom:14px"><h3>紙上交易</h3><table><tr><th>開 → 平（HKT）</th><th>方向</th><th>價</th><th>原因</th><th>USD</th></tr>{rows_t or '<tr><td colspan=5>未有</td></tr>'}</table></div>
<div class=card><h3>硬性風控（環境變數，AI 無權改）</h3><table>{risk_rows}</table></div>
<div class=sub style="margin-top:12px">舊服務 zhuge-risk-manager 嘅投資人日誌／關卡開關／送單參數／錦囊兩頁，切換後由本頁取代。本頁只讀。</div>
</div></body></html>"""
