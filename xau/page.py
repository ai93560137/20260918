"""🌌 天覆陣頁面：同龍飛陣 ?view=longfei 同一套版面（真倉／模擬倉分色區、績效卡、成交紀錄、最近決策、模式／階梯）。
取代舊服務五頁（投資人日誌、關卡開關、送單參數、錦囊執行單、錦囊九十筆）。只讀，冇任何按鈕或解鎖連結。"""
import html

import config
from market import fmt_hkt

CSS = """
:root{color-scheme:light;--primary:#0f62fe;--success:#198754;--danger:#dc3545;--warning:#d97706;--bg:#f4f7fb;--card:#fff;--text:#161616;--muted:#6c757d}
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);padding:20px 15px;margin:0}
.container{max-width:1050px;margin:0 auto}.page-title{font-size:22px;margin:0 0 6px}.muted{color:var(--muted)!important}
.grid{display:grid;gap:16px;margin-bottom:24px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.card{background:var(--card);padding:20px;border-radius:16px;box-shadow:0 4px 15px rgba(0,0,0,.04)}
.card-title{font-size:13px;color:var(--muted);margin-bottom:8px;font-weight:600}.card-value{font-size:24px;font-weight:bold}.card-desc{font-size:12px;color:#adb5bd;margin-top:8px}
.section{background:var(--card);padding:25px;border-radius:16px;box-shadow:0 4px 15px rgba(0,0,0,.04);margin-bottom:24px}
h2{font-size:17px;margin:0 0 16px}h3{font-size:15px;margin:18px 0 10px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #e9ecef;vertical-align:top}th{color:var(--muted);font-weight:600}
.pos{color:var(--success)!important}.neg{color:var(--danger)!important}.tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:12px;background:#eef}
.lf-grp{margin-bottom:28px}.lf-banner{font-size:20px;font-weight:700;padding:10px 18px;border-radius:12px;margin:8px 0 14px;color:#fff}
.lf-real .lf-banner{background:#b45309}.lf-sim .lf-banner{background:#1d4ed8}
.lf-real .section{border-left:8px solid #d97706;background:#fffbeb}.lf-sim .section{border-left:8px solid #2563eb;background:#eff6ff}
.nav{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:24px;padding:15px 20px;background:var(--card);border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,.03)}
.nav-links{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.nav-link{display:inline-block;padding:7px 12px;border-radius:20px;font-size:13px;font-weight:700;text-decoration:none;color:var(--primary);background:#eef4ff;white-space:nowrap}
.nav-link:hover{background:#dbe7ff}.nav-current{background:#0f62fe;color:#fff;cursor:default}
"""


# 使用者 10-21：同舊服務每頁頂一樣嘅導覽列（同樣次序、emoji、pill 樣式）；舊服務嘅頁用絕對網址，本頁係目前頁
PAGE_LINKS = [
    ("welcome", "🏠 首頁"), ("futu_range", "🌬️ 風揚陣恆指波幅"), ("es_range", "🇺🇸 風揚陣ES 波幅"), ("nq_range", "🇺🇸 風揚陣NQ 波幅"),
    ("bazhentu", "🐍 蛇蟠陣"), ("dizai", "⛰️ 地載陣"), ("yunchui", "☁️ 雲垂陣"), ("canary", "🐤 金絲雀"), ("htf", "📈 鳥翔 HTF 掛單"),
    ("longfei", "🐉 龍飛陣"), ("strategies", "🧭 策略總表"), ("fund_report", "📊 基金報告"),
]


RISK_HIDE = {"CLAUDE_PROVIDER", "XAU_MAGIC", "XAU_EXECUTE"}   # 使用者 10-21：硬性風控表只顯示真正風控數值（內部設定唔顯示）


def page_nav():
    items = "".join(f"<a class='nav-link' href='{esc(config.ZHUGE_URL)}?view={view}'>{label}</a>" for view, label in PAGE_LINKS)
    items += f"<span class='nav-link nav-current'>{esc(config.TEAM_EMOJI)} {esc(config.TEAM_NAME)} {esc(config.SYMBOL)}</span>"
    return f"<nav class='nav-links' aria-label='頁面導覽'>{items}</nav>"


def esc(x):
    return html.escape("" if x is None else str(x))


def card(title, value, desc=""):
    return f"<div class='card'><div class='card-title'>{title}</div><div class='card-value'>{value}</div><div class='card-desc'>{desc}</div></div>"


def hk(v):
    return "—" if v is None else f"HK${v * config.HKD_PER_USD:+,.0f}"


def usd(v):
    return "—" if v is None else f"{v:+,.2f}"


def metric_cards(m):
    f2 = lambda v: "—" if v is None else f"{v:.2f}"
    sharpe = "—" if m["trades"] == 0 else ("樣本不足" if m["sharpe"] is None else f"{m['sharpe']:.2f}")
    return ("<div class='grid'>"
            + card("勝率", "—" if m["win_rate"] is None else f"{m['win_rate']:.0%}", "贏嘅筆數 ÷ 總筆數")
            + card("盈虧比 RRR", f2(m["rrr"]), "平均贏 ÷ 平均蝕")
            + card("Sharpe ratio（年化）", sharpe, f"按紐約交易日，要 ≥ 5 日（而家 {m['days']} 日）")
            + card("獲利因子", f2(m["profit_factor"]), "總贏 ÷ 總蝕")
            + card("每筆平均", hk(m["expectancy"]), f"{usd(m['expectancy'])} USD／筆")
            + card("最大回撤", "—" if m["max_dd"] is None else hk(-m["max_dd"]), "累計由高位最大跌幅")
            + card("平均贏", hk(m["avg_win"]), f"{usd(m['avg_win'])} USD／筆")
            + card("平均蝕", "—" if m["avg_loss"] is None else hk(-m["avg_loss"]), f"{usd(-m['avg_loss']) if m['avg_loss'] else '—'} USD／筆")
            + "</div>")


def _pos_text(pos):
    if not pos:
        return "冇"
    return (f"{'好倉' if pos['side'] > 0 else '淡倉'} {pos['lots']:.2f} 手 @ {pos['entry']:.{config.PRICE_DIGITS}f}｜止蝕 {pos.get('stop') or '—'}"
            f"｜止賺 {pos.get('target') or '—'}｜票 {pos.get('ticket') or '—'}")


def _ta_text(ta):
    """EA v0.32 心跳 trade_allowed：終端掣／EA 屬性／戶口三個自動交易開關。"""
    if not isinstance(ta, dict):
        return ""
    names = {"terminal": "終端 Algo Trading 掣", "ea": "EA 屬性「允許算法交易」", "account": "戶口准自動交易"}
    off = [names[k] for k in names if not ta.get(k)]
    return "；✅ MT5 自動交易三個開關全開" if not off else "；<b class='neg'>⛔ MT5 自動交易被擋：" + "、".join(off) + "（關住）</b>"


def run_text(s):
    ctl, lad = s.get("control") or {}, s.get("ladder") or {}
    mode = ctl.get("mode") or "RUN"
    who = "使用者" if ctl.get("set_by") == "user" else "風控"
    reset = f"，{ctl['auto_reset_day']} 紐約換日自動重開" if ctl.get("auto_reset_day") else ""
    if mode == "STOP":
        return f"⛔ 停機（{who}）：{ctl.get('reason') or ''}{reset}"
    if mode == "PAUSE":
        return f"⏸ 停開新倉（{who}）：{ctl.get('reason') or ''}{reset or '，回升自動解'}"
    if not s.get("market_open"):
        return "🌙 休市"
    return "✅ 運行中"


def render_signal_book(s):
    """訊號書 S0 頁：監聽心跳＋最近訊號（只顯示結構化欄位，冇原文、冇頻道名）。"""
    sg = s.get("signals") or {}
    lis = sg.get("listener") or {}
    age = lis.get("age_sec")
    lis_txt = "未收到" if age is None else (f"{age / 60:.0f} 分鐘前" if age >= 60 else f"{age:.0f} 秒前")
    lis_desc = (f"版本 {esc(lis.get('version') or '—')}・頻道 {esc(lis.get('channels'))}・已轉發 {esc(lis.get('forwarded'))}・略過 {esc(lis.get('dropped'))}"
                if lis else "VM 監聽程式未開始")
    label = {"valid": "✅ 有效", "unverified": "⏳ 未核實", "invalid": "🚫 無效", "expired": "⌛ 過期", "info": "ℹ️ 參考", "error": "⚠️ 解析失敗"}
    d = config.PRICE_DIGITS
    num = lambda v: "—" if v is None else f"{v:.{d}f}"  # noqa: E731
    rows = "".join(
        f"<tr><td>{esc(r.get('msg_utc') or r.get('received_utc'))}</td><td>{esc(label.get(r.get('status'), r.get('status')))}{' 🏃 走咗' if r.get('late') else ''}{(' ↪ 轉發+' + str(r.get('fwd_lag_min')) + '分') if r.get('fwd') else ''}</td>"
        f"<td>{esc(r.get('kind'))}</td><td>{esc(r.get('side') or '—')}</td>"
        f"<td>{'—' if r.get('entry_low') is None else (num(r['entry_low']) if r['entry_low'] == r.get('entry_high') else num(r['entry_low']) + '–' + num(r.get('entry_high')))}</td>"
        f"<td>{num(r.get('sl'))}</td><td>{esc(', '.join(num(t) for t in r.get('tp') or []) or '—')}</td>"
        f"<td>{esc(r.get('reason') or '')}</td></tr>"
        for r in sg.get("rows") or [])
    body = ("<div class='section'><p>📨 訊號書（magic " + esc(config.MAGIC) + "）S0：只收 Telegram 訊號、解析、存檔，<b>唔問 Opus、唔落單</b>。"
            "訊號只係參考資料；原本 🌌 天覆陣（Claude 自主）服務完全睇唔到訊號，做對照組。</p>"
            f"<p class='muted' style='font-size:13px'>更新 {esc(s.get('updated_hkt'))} HKT・有效期 {config.SIG_TTL_MIN} 分鐘・時間 UTC</p></div>"
            "<div class='section'><div class='grid'>" + card("監聽心跳", esc(lis_txt), lis_desc)
            + card("最近訊號", esc(len(sg.get("rows") or [])), "最多顯示 30 條") + "</div></div>"
            "<div class='section'><h2>最近訊號</h2><div style='overflow-x:auto'><table><tr><th>訊息時間</th><th>狀態</th><th>種類</th>"
            "<th>方向</th><th>入場</th><th>止損</th><th>止賺</th><th>原因</th></tr>"
            + (rows or "<tr><td colspan='8' class='muted'>未有訊號</td></tr>") + "</table></div></div>")
    sc = sg.get("scores") or {}
    pct = lambda a, b: "—" if not b else f"{a / b:.0%}"  # noqa: E731
    score_rows = ""
    for ch, c in sorted(sc.items()):
        avg_tp = "—" if not c.get("filled") else f"{c['max_tp_sum'] / c['filled']:.1f}"
        avg_r = "—" if not c.get("r_n") else f"{c['r_sum'] / c['r_n']:+.2f}"
        score_rows += (f"<tr><td>…{esc(ch)}</td><td>{c['n']}</td><td>{pct(c['filled'], c['n'])}</td><td>{pct(c['tp1'], c['filled'])}</td>"
                       f"<td>{pct(c['sl'], c['filled'])}</td><td>{avg_tp}</td><td>{avg_r}</td></tr>")
    body += ("<div class='section'><h2>頻道準確度（用實際金價計，唔信頻道自稱成績）</h2><div style='overflow-x:auto'><table>"
             "<tr><th>頻道</th><th>已完結訊號</th><th>成交率</th><th>TP1 先到</th><th>SL 先到</th><th>平均去到第幾個 TP</th><th>TP1 走平均 R</th></tr>"
             + (score_rows or "<tr><td colspan='7' class='muted'>未有完結嘅訊號</td></tr>") + "</table></div>"
             "<p class='muted' style='font-size:13px'>成交＝30 分鐘內 K 線碰到入場區；同一根 K 線碰到 SL 同 TP 當 SL（保守）；24 小時未完當平手。R＝去到 TP1 即走嘅回報÷風險。</p></div>")
    if config.SIG_DECIDE:                              # S1：訊號書自己落單（demo 先），顯示持倉同最近決策
        pos = s.get("live_positions") if s.get("execute") else ([s["position"]] if s.get("position") else [])
        pos_txt = "冇" if not pos else "；".join(f"{'好' if (p.get('side') or 0) > 0 else '淡'}倉 {p.get('lots')} 手 @ {p.get('entry')}・SL {p.get('stop')}・TP {p.get('target') or '—'}" for p in pos)
        dec = [x for x in (s.get("decisions") or []) if x.get("kind") == "decide"][-10:][::-1]
        drows = "".join(f"<tr><td>{esc(fmt_hkt(x['ts']))}</td><td>{esc(x.get('final'))}</td><td>{esc(x.get('reason'))}</td></tr>" for x in dec)
        body += (f"<div class='section'><h2>S1 落單（magic {esc(config.MAGIC)}，{'demo／真倉指令' if s.get('execute') else '紙上'}）</h2>"
                 + "<div class='grid'>" + card("模式", esc((s.get("control") or {}).get("mode") or "RUN"), esc(run_text(s)))
                 + card("持倉", esc(pos_txt)) + "</div><div style='overflow-x:auto'><table><tr><th>時間 HKT</th><th>決定</th><th>理由</th></tr>"
                 + (drows or "<tr><td colspan='3' class='muted'>未有決策（冇有效訊號就唔問 Claude）</td></tr>") + "</table></div></div>")
    fo = s.get("follow")
    if fo:
        fa = fo.get("account") or {}
        fpos = fa.get("positions") or []
        fpos_txt = "冇" if not fpos else "；".join(f"{'好' if (p.get('side') or 0) > 0 else '淡'}倉 {p.get('lots')} 手 @ {p.get('entry')}・SL {p.get('stop')}・TP {p.get('target') or '—'}" for p in fpos)
        orows = "".join(f"<tr><td>{esc(fmt_hkt(o['ts']))}</td><td>{esc(o.get('ch'))}</td><td>{esc(o.get('side'))} {esc(o.get('lots'))}</td><td>{num(o.get('price'))}</td>"
                        f"<td>{num(o.get('sl'))}／{num(o.get('tp'))}</td><td>{esc(o.get('entry'))}</td>"
                        f"<td>{'紙上' if o.get('applied') == 'paper' else ('✅ ' + str(o.get('ticket') or '') if o.get('ok') else ('❌ ' + str(o.get('message') or '') if o.get('acked') else '⏳ 等回報'))}</td></tr>"
                        for o in fo.get("orders") or [])
        body += (f"<div class='section'><h2>跟單（magic {esc(fo.get('magic'))}，頻道尾號 {esc('、'.join(fo.get('channels') or []))}，{esc(fo.get('lots'))} 手，TP1 全平、原 SL；{'demo／真倉指令' if fo.get('execute') else '紙上'}）</h2>"
                 "<div class='grid'>" + card("跟單心跳", esc(fa.get("received_utc") or "未收到"), "magic " + esc(fo.get("magic")) + " 圖表")
                 + card("持倉", esc(fpos_txt)) + card("今日／累計（HKD，自己 magic）", esc(fa.get("daily_pnl")) + "／" + esc(fa.get("realized_total")))
                 + card("最近判斷", esc((fo.get("last") or {}).get("note") or "—"), esc((fo.get("last") or {}).get("utc") or "")) + "</div>"
                 "<div style='overflow-x:auto'><table><tr><th>時間 HKT</th><th>頻道</th><th>方向／手</th><th>入場價</th><th>SL／TP1</th><th>入場依據</th><th>EA 回報</th></tr>"
                 + (orows or "<tr><td colspan='7' class='muted'>未有跟單</td></tr>") + "</table></div></div>")
    head = (f"<div class='nav'><div class='brand'><h1 class='page-title'>📨 {esc(config.TEAM_NAME)}・{esc(config.SYMBOL)}</h1></div>{page_nav()}</div>")
    return (f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='light only'>"
            f"<meta http-equiv='refresh' content='300'><title>📨 {esc(config.TEAM_NAME)}・{esc(config.SYMBOL)}</title><style>{CSS}</style></head>"
            f"<body><div class='container'>{head}{body}</div></body></html>")


def render(status):
    s = status
    if config.SIGNAL_BOOK:
        return render_signal_book(s)
    m = s.get("metrics") or {"trades": 0, "wins": 0, "win_rate": None, "points": 0.0, "expectancy": None, "rrr": None,
                             "profit_factor": None, "max_dd": None, "avg_win": None, "avg_loss": None, "sharpe": None, "days": 0}
    pos = s.get("position")
    if pos:
        pos_txt = f"{'好倉' if pos['side'] > 0 else '淡倉'} {pos['lots']:.2f} 手 @ {pos['entry']:.{config.PRICE_DIGITS}f}"
        pos_desc = f"止蝕 {pos.get('stop')}・止賺 {pos.get('target') or '—'}・{fmt_hkt(pos['opened_ts'])} 開"
    else:
        pos_txt, pos_desc = "冇", "空手"
    lad, ctl = s.get("ladder") or {}, s.get("control") or {}
    u = s.get("usage_today") or {}
    head = (f"<div class='nav'><div class='brand'><h1 class='page-title'>{esc(config.TEAM_EMOJI)} {esc(config.TEAM_NAME)}・{esc(config.SYMBOL)} 自動交易</h1></div>"
            f"{page_nav()}</div>")
    intro = (f"<div class='section'><p>由 天覆陣每根 1 分鐘 K 線收盤自己決定買賣 {esc(config.SYMBOL)} 差價合約（最多 1 張，固定 "
             f"{s['risk'].get('XAU_LOTS', 0.01):.2f} 手；可沽空）；程式負責落單同硬性風控（日蝕 −3% 停開新倉、−6% 平倉停機，換日自動重開；累計虧損 25% 停開新倉、換日自動恢復；保證金水平低停開新倉；"
             "止損距離、最長持倉），AI 無權改。舊系統嘅六關電閘、錦囊 v4 規則只作參考。"
             "先做模擬倉前向測試，達到預先登記標準、使用者講先轉真倉；真倉落單經 MT5 EA 執行指令。</p>"
             f"<p class='muted' style='font-size:13px'>更新 {esc(s.get('updated_hkt'))} HKT・{esc(s.get('session'))}</p></div>")   # 使用者 10-21：唔顯示模型／費用
    key = s.get("api_key") or {}
    key_warn = ""
    if key.get("warn"):
        days = key.get("days_left") or 0
        key_state = "已到期" if days <= 0 else f"仲有 {days:.0f} 日到期"
        key_warn = ("<div class='section' style='border-left:8px solid #dc2626;background:#fef2f2'><b>🔑 ANTHROPIC_API_KEY "
                    + key_state + "</b>（" + esc(key.get("expires_utc")) + " UTC）：請喺 Cloud Run 控制台換新 key，否則決策會失敗。</div>")
    real = (key_warn + "<div class='lf-grp lf-real'><div class='lf-banner'>💰 真倉（真金白銀）</div>"
            + ("<div class='section'><p class='muted'>未開始真倉。模擬倉達標、使用者批准後先開始（XAU_EXECUTE=1，新 EA 執行指令）。</p></div>"
               if not s.get("execute") else
               f"<div class='section'><h2>真倉狀態</h2><p>{esc(run_text(s))}</p>"
               f"<p>EA 戶口 {esc(s.get('account_id') or '—')}（{esc(s.get('server') or '—')}）{'，EA dry-run' if s.get('ea_dry_run') else ''}；只收 XAU_ACCOUNT={esc(s.get('xau_account') or '（全收）')}"
               f"{'；⚠ XAU_TEST_CMDS=1（真倉前要關）' if s.get('test_cmds') else ''}{_ta_text(s.get('trade_allowed'))}</p>"
               f"<p>EA 持倉：{esc(_pos_text(s.get('position')))}</p><p>待執行指令：{len(s.get('pending_cmds') or [])} 條</p></div>")
            + "</div>")
    top = ("<div class='grid'>"
           + card("階段", "模擬盤" if not s.get("execute") else "真倉", esc(run_text(s)))
           + card("模擬盤筆數", str(m["trades"]), "前向測試，已平倉")
           + card("而家持倉", esc(pos_txt), pos_desc)
           + card("已平倉累計", "—" if not m["trades"] else hk(m["points"]), f"{usd(m['points'])} USD；已扣點差 {config.SPREAD_USD:g}")
           + card("今日開倉", str(s.get("trades_today", 0)), f"上限 {s['risk'].get('XAU_MAX_TRADES_PER_DAY') or '不限'}")
           + "</div>")
    rows = "".join(
        f"<tr><td>{esc(fmt_hkt(t['opened_ts']))}</td><td>{esc(fmt_hkt(t['closed_ts']))}</td><td>{'好' if t['side'] > 0 else '淡'}</td>"
        f"<td>{t['entry']:.{config.PRICE_DIGITS}f}</td><td>{t['exit']:.{config.PRICE_DIGITS}f}</td><td class=\"{'pos' if t['pnl_usd'] >= 0 else 'neg'}\">{t['pnl_usd']:+.2f}</td>"
        f"<td>{t['hold_min']}</td><td>{esc(t.get('reason'))}</td></tr>"
        for t in list(reversed(s.get("trades") or []))[:40])
    trades_html = ("<h3>📒 成交紀錄（美元）</h3>"
                   + ("<div style='overflow-x:auto'><table><tr><th>開倉</th><th>平倉</th><th>方向</th><th>開倉價</th><th>平倉價</th><th>盈虧</th><th>分鐘</th><th>出場原因</th></tr>"
                      + rows + "</table></div>" if rows else "<p class='muted'>未有平倉成交。</p>"))
    drows = "".join(
        f"<tr><td>{esc(fmt_hkt(d.get('ts', 0)))}</td><td>{esc(d.get('price'))}</td>"
        f"<td><span class='tag'>{esc(d.get('final') or d.get('action'))}</span>{(' <small class=neg>AI 提 ' + esc(d.get('action')) + '</small>') if d.get('rejected') else ''}</td>"
        f"<td>{esc(d.get('reason'))}{('<br><small class=neg>擋：' + esc(d.get('rejected')) + '</small>') if d.get('rejected') else ''}"
        f"{('<br><small class=muted>' + esc(d.get('applied')) + '</small>') if d.get('applied') and d.get('applied') != 'HOLD' else ''}</td>"
        f"<td>{esc(d.get('ms') or '—')} ms</td></tr>"
        for d in list(reversed(s.get("decisions") or []))[:60])
    dec_html = ("<h3>🧠 最近決策（最新在上）</h3>"
                + ("<div style='overflow-x:auto'><table><tr><th>HKT</th><th>價</th><th>動作</th><th>理由</th><th>延遲</th></tr>" + drows + "</table></div>"
                   if drows else "<p class='muted'>未有決策。</p>"))
    sim = ("<div class='lf-grp lf-sim' id='lf-sim-top'><div class='lf-banner'>🧪 模擬倉（前向測試）</div>"
           + f"<div class='section'><h2>{esc(config.SYMBOL)}</h2>" + top + trades_html + dec_html + "</div>"
           + "<div class='section'><h2>📊 模擬倉績效（按 HK$，1 美元 = 7.8 港元）</h2>" + metric_cards(m)
           + "<p class='muted' style='font-size:13px'>紙上成交用該根 M1 收市價，每張扣點差；同一根碰到止損同止賺當止損。樣本少時只供參考。</p></div></div>")
    lad_cls = {"A": "pos", "B": "", "D": "neg"}.get(lad.get("level"), "")
    risk_rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in (s.get("risk") or {}).items() if k not in RISK_HIDE)
    alerts = "；".join((lad.get("alerts") or {}).values()) or "冇"
    ctrl = ("<div class='section'><h2>🛡️ 模式同風控（只讀；開關只喺 GCS xau/control.json，冇網頁按鈕、冇硬鎖）</h2><div class='grid'>"
            + card("模式", esc(ctl.get("mode") or "RUN"), esc(run_text(s)))
            + card("風控階梯", f"<span class='{lad_cls}'>{esc(lad.get('level') or 'A')}</span>", esc("；".join(lad.get("reasons") or []) or "正常"))
            + card("今日盈虧（階梯用）" + ("・戶口合計" if lad.get("scope") == "account" else ""), "—" if lad.get("daily_pnl_hkd") is None else f"HK${lad['daily_pnl_hkd']:+,.0f}",
                   ("天覆陣全部產品合計（EA InpBotMagics），含浮動" + (f"；本產品 HK${lad['own_daily_pnl_hkd']:+,.0f}" if lad.get("own_daily_pnl_hkd") is not None else "")
                    if lad.get("scope") == "account" else "只計天覆陣嘅單，含浮動") + ("" if ctl.get("principal_set") else "；⚠ 未設本金，日蝕未啟用"))
            + card("只提示嘅警報", esc(alerts), "回撤／保證金：只發 Telegram，唔停唔鎖")
            + "</div><div style='overflow-x:auto'><table><tr><th>硬性風控（環境變數，AI 無權改）</th><th>值</th></tr>" + risk_rows + "</table></div></div>")
    foot = "<p class='muted' style='font-size:13px'>模擬倉成績唔係真金白銀交易；過往成績亦唔代表將來回報。舊服務嘅投資人日誌／關卡開關／送單參數／錦囊兩頁，切換後由本頁取代。</p>"
    return (f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='light only'>"
            f"<meta http-equiv='refresh' content='300'><title>{esc(config.TEAM_EMOJI)} {esc(config.TEAM_NAME)}・{esc(config.SYMBOL)} 自動交易</title><style>{CSS}</style></head>"
            f"<body><div class='container'>{head}{intro}{real}{sim}{ctrl}{foot}</div></body></html>")
