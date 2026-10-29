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


def live_book_section(title, v, note=""):
    """[R352] 真倉績效：逐筆（時間、方向、手數、入／出價、R、HKD）＋今日／本週／累計、勝率、獲利因子、最大回撤。v＝live_book.view()；冇就唔出。"""
    if not isinstance(v, dict):
        return ""
    sm, d = v.get("summary") or {}, config.PRICE_DIGITS
    num = lambda x: "—" if x is None else f"{x:.{d}f}"  # noqa: E731
    money = lambda x: "—" if x is None else f"HK${x:+,.2f}"  # noqa: E731
    cls = lambda x: "" if not x else ("pos" if x > 0 else "neg")  # noqa: E731
    first = fmt_hkt(sm["first_ts"])[:5] if sm.get("first_ts") else "—"
    cards = ("<div class='grid'>"
             + card("今日（EA，自己 magic）", f"<span class='{cls(v.get('ea_daily_hkd'))}'>{money(v.get('ea_daily_hkd'))}</span>", "MT5 伺服器日，含浮動")
             + card("本週（已平倉）", f"<span class='{cls(sm.get('week'))}'>{money(sm.get('week'))}</span>", "香港時間週一起")
             + card("累計（EA，自己 magic）", f"<span class='{cls(v.get('ea_realized_hkd'))}'>{money(v.get('ea_realized_hkd'))}</span>", "EA 自 InpLedgerStart 起已實現")
             + card("已平倉筆數", f"{sm.get('n', 0)}", f"{sm.get('wins', 0)} 勝／{sm.get('flat', 0)} 平／{sm.get('losses', 0)} 負；{first} 起")
             + card("勝率", "—" if sm.get("win_rate") is None else f"{sm['win_rate']:.0%}", "賺錢筆數 ÷ 總筆數")
             + card("獲利因子 PF", "—" if sm.get("pf") is None else f"{sm['pf']:.2f}", "總贏 ÷ 總蝕")
             + card("最大回撤", "—" if sm.get("max_dd") is None else f"HK${-sm['max_dd']:,.2f}", "逐筆累計由高位最大跌幅")
             + card("平均 R", "—" if sm.get("avg_r") is None else f"{sm['avg_r']:+.2f}R", "R＝按初始止損距離")
             + card("成交簿合計", f"<span class='{cls(sm.get('total'))}'>{money(sm.get('total'))}</span>", "下面逐筆加埋")
             + "</div>")
    rows = "".join(
        f"<tr><td>{esc(fmt_hkt(t['opened_ts'])) if t.get('opened_ts') else '—'}</td><td>{esc(fmt_hkt(t['closed_ts']))}</td>"
        f"<td>{esc(t.get('ch') or '')}</td><td>{'好' if (t.get('side') or 0) > 0 else '淡'}</td><td>{'—' if t.get('lots') is None else format(t['lots'], '.2f')}</td>"
        f"<td>{num(t.get('entry'))}{('<br><small class=muted>決策 ' + num(t.get('decision_price')) + '</small>') if t.get('decision_price') is not None else ''}</td>"
        f"<td>{num(t.get('exit') if t.get('exit') is not None else t.get('exit_est'))}{'' if t.get('exit') is not None else '<small class=muted> 估</small>'}</td>"
        f"<td>{'—' if t.get('r') is None else format(t['r'] or 0.0, '+.2f') + 'R'}</td>"
        f"<td class='{cls(t.get('pnl_hkd'))}'>{float(t.get('pnl_hkd') or 0):+,.2f}</td></tr>"
        for t in v.get("rows") or [])
    has_ch = any(t.get("ch") for t in v.get("rows") or [])
    head = "<tr><th>開倉 HKT</th><th>平倉 HKT</th><th>頻道</th><th>方向</th><th>手數</th><th>入場</th><th>出場</th><th>R</th><th>HKD</th></tr>"
    if not has_ch:
        head = head.replace("<th>頻道</th>", "")
        rows = rows.replace("<td></td><td>好", "<td>好").replace("<td></td><td>淡", "<td>淡")
    tbl = (("<div class='dec-scroll' style='overflow:auto;max-height:420px;border:1px solid #e5e7eb;border-radius:8px'>"   # 使用者 10-30：太長，用捲軸
            "<style>.dec-scroll th{position:sticky;top:0;background:#fff;z-index:1}</style><table>") + head + rows + "</table></div>") if rows else "<p class='muted'>未有已平倉真倉單。</p>"
    grp = ""
    for gname, items in v.get("groups") or []:                  # [R352c] 使用者 10-30「921／932 再細分」
        grows = "".join(
            f"<tr><td>{esc(k)}</td><td>{g['n']}</td><td>{g['wins']}／{g['flat']}／{g['losses']}</td>"
            f"<td>{'—' if g['win_rate'] is None else format(g['win_rate'], '.0%')}</td>"
            f"<td class='{cls(g['total'])}'>{g['total']:+,.2f}</td><td>{'—' if g['pf'] is None else format(g['pf'], '.2f')}</td>"
            f"<td>{'—' if g['avg_r'] is None else format(g['avg_r'], '+.2f') + 'R'}</td><td>{'—' if g['max_dd'] is None else format(-g['max_dd'] or 0.0, ',.2f')}</td></tr>"
            for k, g in items)
        grp += (f"<h3>🔎 按{esc(gname)}細分</h3><div style='overflow-x:auto'><table><tr><th>{esc(gname)}</th><th>筆數</th><th>勝／平／負</th><th>勝率</th>"
                "<th>合計 HKD</th><th>PF</th><th>平均 R</th><th>最大回撤 HKD</th></tr>" + grows + "</table></div>")
    return (f"<div class='section'><h2>{title}</h2>" + cards + grp + f"<h3>📒 已平倉逐筆（最新在上，共 {len(v.get('rows') or [])} 筆，捲動睇舊嘅）</h3>" + tbl
            + "<p class='muted' style='font-size:13px'>HKD 用 EA realized_total 差額（含佣金／隔夜息）；出場價由 HKD 反推（1 美元＝"
            + f"{config.HKD_PER_USD:g} 港元），標「估」；R＝(出場−入場)÷初始止損距離。"
            + (f"部署前 {v.get('seeded')} 筆由補登紀錄載入。" if v.get("seeded") else "")
            + esc(note) + "</p></div>")


FWD_145_FROM = 1793232000          # 2026-10-29 00:00 UTC：R349 部署後第一張 921（L16）起計 IDEAS #145 20 張


def forward_section(fw, book=None):
    """[R352c] 包 try：前向數據格式有變都唔拖垮頁面。"""
    try:
        return _forward_section(fw, book)
    except Exception:  # noqa: BLE001
        return "<div class='section'><h2>🔬 前向測試</h2><p class='muted'>前向數據讀唔到（格式有變），睇 GCS xau/sig/gb_forward/latest.md。</p></div>"


def _forward_section(fw, book=None):
    """[R352c] 🔬 前向測試（影子，唔落單；使用者 10-30「將 V13 及其他前向測試結果放上去」）。
    fw＝{"gb": gb_forward latest.json, "student": student scores.json}；book＝921 live_book view（#145 滑價）。"""
    if not isinstance(fw, dict):
        return ""
    out = ""
    f2 = lambda x, f="{:+.2f}": "—" if x is None else f.format(x)  # noqa: E731
    gb = fw.get("gb") or {}
    ev = gb.get("eval") or {}
    crit = {"0342": "#149：候選 V13（GB 入場、SL 10、TP 10 全平）；20 張判：ΣR ≥ +2R、PF ≥ 1.2、最大回撤 ≤ 3R、好過同期 V0 → 先提真倉 0.05 手（要批）",
            "5117": "#150：歷史回測全部變體蝕，已棄用；只觀察候選 V11"}
    for ch in ("0342", "5117"):
        e = ev.get(ch)
        if not e:
            continue
        rows = "".join(
            f"<tr{' style=font-weight:600' if k == e.get('candidate') else ''}><td>{esc(k)}{' ⭐候選' if k == e.get('candidate') else ''}</td><td>{esc(r.get('name'))}</td>"
            f"<td>{r['summary']['n']}</td><td>{r['summary']['win']}／{r['summary']['flat']}／{r['summary']['loss']}</td>"
            f"<td class=\"{'pos' if (r['summary'].get('sum_r') or 0) > 0 else ('neg' if (r['summary'].get('sum_r') or 0) < 0 else '')}\">{f2(r['summary'].get('sum_r'))}</td>"
            f"<td>{f2(r['summary'].get('pf'), '{:.2f}')}</td><td>{f2(r['summary'].get('max_dd_r'))}</td></tr>"
            for k, r in (e.get("result") or {}).items())
        out += (f"<h3>{esc(e.get('name'))}（…{ch}）：{esc(e.get('verdict'))}（已完 {e.get('done')}、未完 {e.get('pending')}）</h3>"
                f"<p class='muted' style='font-size:13px'>{esc(crit.get(ch, ''))}</p>"
                "<div style='overflow-x:auto'><table><tr><th>變體</th><th>規則</th><th>張</th><th>勝／平／負</th><th>ΣR</th><th>PF</th><th>最大回撤 R</th></tr>"
                + rows + "</table></div>")
    meta = gb.get("meta") or {}
    if out:
        out += f"<p class='muted' style='font-size:13px'>經紀 M1 計、唔落單；更新 {esc(meta.get('run_utc'))} UTC（K 線到 {esc(meta.get('bars_to'))}），Actions 每 6 小時跑。</p>"
    own = ((fw.get("student") or {}).get("own")) or {}
    if own:
        names = {"rule:rev15": ("rev15（M15 反轉）", "11-11 判"), "rule:level": ("level（亞洲區間高低位）", "11-25 判"),
                 "rule:swing": ("swing", "觀察"), "rule:rev15x": ("rev15x", "已棄")}
        srows = ""
        for k in ("rule:rev15", "rule:level", "rule:swing", "rule:rev15x"):
            o = own.get(k)
            if not o:
                continue
            fl = o.get("filled") or 0
            per = (o.get("r_sum") or 0) / fl if fl else None
            srows += (f"<tr><td>{esc(names[k][0])}</td><td>{fl}／100</td><td>{o.get('win', 0)}／{o.get('sl', 0)}</td>"
                      f"<td class=\"{'pos' if (o.get('r_sum') or 0) > 0 else 'neg'}\">{f2(o.get('r_sum'))}</td><td>{f2(per)}</td><td>{esc(names[k][1])}</td></tr>")
        out += ("<h3>規則學生（#146，影子，2R 全平、扣點差＋滑價 0.2）</h3>"
                "<p class='muted' style='font-size:13px'>升 931 真倉 0.01 門檻：成交 ≥ 100、每張 R ≥ +0.2、PF ≥ 1.3、TP 命中贏隨機基準 ≥ 10 點、最大連敗 ≤ 6（要批）。</p>"
                "<div style='overflow-x:auto'><table><tr><th>學生</th><th>成交／門檻</th><th>勝／止損</th><th>合計 R</th><th>每張 R</th><th>判斷</th></tr>"
                + srows + "</table></div>")
    if isinstance(book, dict):
        rows = [x for x in (book.get("rows") or []) if (x.get("opened_ts") or 0) >= FWD_145_FROM]
        slips = [round((x.get("side") or 0) * ((x.get("entry") or 0) - x["decision_price"]), 2) for x in rows if x.get("decision_price") is not None and x.get("entry") is not None]
        if rows:
            med = sorted(slips)[len(slips) // 2] if slips else None
            if slips and len(slips) % 2 == 0:
                med = round((sorted(slips)[len(slips) // 2 - 1] + sorted(slips)[len(slips) // 2]) / 2, 2)
            p3 = any(sv > 1.5 for sv in slips) or (med is not None and med > 0.5)
            out += ("<h3>921 三項改善影子統計（#145，R349 起 20 張判）</h3>"
                    f"<p>進度 <b>{len(rows)}／20</b> 張。P3 滑價（決策價→成交，不利為正）：{esc('、'.join(f'{sv:+.2f}' for sv in reversed(slips)) or '—')}；"
                    f"中位數 {f2(med)}；{'⚠ 已觸發 P3 條件（任何一張 >1.5 或中位數 >0.5），20 張期滿先判' if p3 else '未觸發'}。"
                    "P1（0.8R 保本）／P2（止損後 15 分鐘同向重入）逐張記喺 TEST_RESULTS。</p>")
    if not out:
        return ""
    return "<div class='section' id='forward'><h2>🔬 前向測試（影子，唔落單）</h2>" + out + "</div>"


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
        f"<tr><td>{esc(r.get('msg_utc') or r.get('received_utc'))}</td><td>{esc(label.get(r.get('status'), r.get('status')))}{' 🏃 走咗' if r.get('late') else ''}{(' ↪ 轉發+' + str(r.get('fwd_lag_min')) + '分') if r.get('fwd') else ''}{(' ⏱' + str(r.get('lag_min')) + '分/走' + str(r.get('moved_usd'))) if r.get('lag_min') is not None else ''}</td>"
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
        body += (f"<p class='muted'>📅 數據封鎖：{esc(((fo.get('data_block') or {}).get('title') + '（' + str((fo.get('data_block') or {}).get('t', ''))[11:16] + ' UTC）') if fo.get('data_block') else '冇')}；最近因數據略過 {len(fo.get('skipped_data') or [])} 條</p>" if fo else "")   # [R348]
    if s.get("execute") or s.get("live_book_follow"):            # [R352] 真倉績效（932 跟單；S1 開就加 931）／模擬倉
        body += ("<div class='lf-grp lf-real'><div class='lf-banner'>💰 真倉績效</div>"
                 + live_book_section("💰 真倉績效・932（跟單）", s.get("live_book_follow"))
                 + (live_book_section(f"💰 真倉績效・{esc(config.MAGIC)}（訊號書 S1）", s.get("live_book")) if config.SIG_DECIDE else "")
                 + "</div><div class='lf-grp lf-sim'><div class='lf-banner'>🧪 模擬倉績效</div><div class='section'><p><b>已轉真倉，模擬停。</b>"
                 "頻道準確度同學徒係影子評分（唔落單），唔計入真倉績效。</p></div></div>")
    body += forward_section(s.get("forward"))                    # [R352c] 前向測試（0342 V13／5117／學生）
    stu = s.get("student")
    if stu:
        g = (stu.get("scores") or {}).get("grade") or {}; own = (stu.get("scores") or {}).get("own") or {}
        def gp(a, b): return "—" if not b else f"{a / b:.0%}"
        srows = "".join(f"<tr><td>{esc(k)}</td><td>{esc((stu.get('counts') or {}).get(k, 0))}</td>"
                        f"<td>{esc(g.get(k, {}).get('n', 0))}</td><td>{gp(g.get(k, {}).get('dir', 0), g.get(k, {}).get('n', 0))}</td>"
                        f"<td>{gp(g.get(k, {}).get('zone', 0), g.get(k, {}).get('n', 0))}</td><td>{gp(g.get(k, {}).get('time', 0), g.get(k, {}).get('n', 0))}</td>"
                        f"<td>{esc(own.get(k, {}).get('filled', 0))}／{esc(own.get(k, {}).get('n', 0))}</td><td>{gp(own.get(k, {}).get('win', 0), own.get(k, {}).get('filled', 0))}</td>"
                        f"<td>{esc(own.get(k, {}).get('r_sum', 0))}</td></tr>" for k in ("rule:swing", "rule:level", "rule:rev15", "claude"))
        prow = "".join(f"<tr><td>{esc(fmt_hkt(p['ts']))}</td><td>{esc(p.get('student'))}</td><td>{esc(p.get('side') or 'HOLD')}</td>"
                       f"<td>{'—' if p.get('entry_low') is None else num(p['entry_low']) + '–' + num(p['entry_high'])}</td><td>{num(p.get('price'))}</td>"
                       f"<td>{esc(p.get('ref') if p.get('ref') is not None else (p.get('reason') or ''))}</td><td>{esc(p.get('graded') or '')}</td></tr>" for p in stu.get("recent") or [])
        body += ("<div class='section'><h2>🎓 學徒（階段 1 影子學生，唔落單；階段 0 快照每條訊號自動存）</h2>"
                 f"<p class='muted' style='font-size:13px'>Claude 學生 {'開（' + esc(stu.get('shadow_hours')) + ' UTC 每 ' + esc(stu.get('interval_min')) + ' 分鐘）' if stu.get('shadow') else '未開（XAU_SHADOW=1）'}・"
                 f"對答案：參考頻道訊號到之前 30 分鐘內有判斷＝交卷，方向一樣＝方向命中，入場區中位差 ≤3 美元＝位置命中・自己成績：DAN 結構 2R 全平・Claude 學生用量 {esc((stu.get('usage') or {}).get('n'))} 次／${esc((stu.get('usage') or {}).get('cost_usd'))}</p>"
                 "<div style='overflow-x:auto'><table><tr><th>學生</th><th>判斷數</th><th>對過答案</th><th>方向命中</th><th>位置命中</th><th>交卷率</th><th>自己成交／完結</th><th>自己勝率</th><th>自己 R 合計</th></tr>"
                 + srows + "</table></div><h3 style='margin-top:12px'>最近判斷</h3><div style='overflow-x:auto'><table><tr><th>時間 HKT</th><th>學生</th><th>方向</th><th>入場區</th><th>現價</th><th>依據</th><th>對答案</th></tr>"
                 + (prow or "<tr><td colspan='7' class='muted'>未有判斷</td></tr>") + "</table></div></div>")
    head = (f"<div class='nav'><div class='brand'><h1 class='page-title'>📨 {esc(config.TEAM_NAME)}・{esc(config.SYMBOL)}</h1></div>{page_nav()}</div>")
    return (f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='light only'>"
            f"<meta http-equiv='refresh' content='300'><title>📨 {esc(config.TEAM_NAME)}・{esc(config.SYMBOL)}</title><style>{CSS}</style></head>"
            f"<body><div class='container'>{head}{body}</div></body></html>")


def rulesim_section(sm):
    """[R345] 即日回測（規則版，唔用 AI）：research/eurusd_rulesim/rulesim.py 每日寫 summary.json。sm 冇就唔出。"""
    if not isinstance(sm, dict):
        return ""
    title = "<h2>🧪 即日回測（規則版，唔用 AI）</h2>"
    note = ("<p class='muted'>10-27 起 EURUSD 空倉唔問 Claude（使用者「暫停 API CALL，暫時只做即日回測模擬」）；每日 17:00 UTC 收市後用當日 1 分鐘 K 線，"
            "按「倫敦開市區間突破」機械規則回測：07:00–07:30 UTC 區間、M5 收市突破、順日線 20 日均線、止蝕區間另一邊（最少 7 pip、區間闊過 25 pip 唔做）、"
            "1R 後保本再跟 3 支 M5 收緊、17:00 平倉、每張扣 1 pip。0.01 手計 HK$。量度嘅係規則，唔係 AI。</p>")
    allst = sm.get("all") or {}
    if not allst.get("n"):
        return f"<div class='section' id='rulesim'>{title}{note}<p class='muted'>未有回測成交（已評 {esc(sm.get('days_scored') or 0)} 日）。</p></div>"

    def fmt(v, f="{:+.3f}"):
        return "—" if v is None else f.format(v)

    def row(name, st):
        return (f"<tr><td>{esc(name)}</td><td>{st.get('n', 0)}</td><td>{st.get('days', 0)}</td><td>{fmt(st.get('win'), '{:.0%}')}</td>"
                f"<td>{fmt(st.get('avg_r'))}R</td><td>{fmt(st.get('pf'), '{:.2f}')}</td><td>{fmt(st.get('t'), '{:.2f}')}</td>"
                f"<td>{fmt(st.get('pips'), '{:+.1f}')}</td><td>{fmt(st.get('hkd'), '{:+,.2f}')}</td><td>{fmt(st.get('max_dd_hkd'), '{:,.2f}')}</td></tr>")
    names = {"B_or60": "B：區間 60 分鐘", "C_width": "C：區間闊度 ≥ 前 20 日中位", "D_no_trend": "D：冇日線過濾"}
    rows = row("主規則", allst) + "".join(row(names.get(k, k), st) for k, st in (sm.get("variants") or {}).items() if st.get("n"))
    tbl = ("<div style='overflow-x:auto'><table><tr><th>規則</th><th>筆數</th><th>日數</th><th>勝率</th><th>每筆平均</th><th>獲利因子</th>"
           "<th>t 值</th><th>合計 pip</th><th>合計 HK$</th><th>最大回撤 HK$</th></tr>" + rows + "</table></div>")
    rec = "".join(f"<tr><td>{esc(x.get('date'))}</td><td>{'好' if x.get('side', 0) > 0 else '淡'}</td><td>{esc(x.get('entry_t'))}</td>"
                  f"<td>{x.get('entry')}</td><td>{x.get('exit')}</td><td>{esc(x.get('exit_reason'))}</td><td>{x.get('pips'):+.1f}</td>"
                  f"<td>{x.get('r'):+.2f}R</td><td>{x.get('hkd'):+,.2f}</td><td>{esc(x.get('source') or '')}</td></tr>"
                  for x in list(reversed(sm.get("recent") or []))[:15])
    recent = ("<h3>最近成交（主規則）</h3><div style='overflow-x:auto'><table><tr><th>日期</th><th>方向</th><th>入場</th><th>入場價</th>"
              "<th>出場價</th><th>出場</th><th>pip</th><th>R</th><th>HK$</th><th>數據</th></tr>" + rec + "</table></div>")
    foot = f"<p class='muted' style='font-size:13px'>規則版本 {esc(sm.get('rules') or '')}；更新 {esc(sm.get('updated_utc') or '')}（UTC）。「yfinance（估算）」＝冇經紀 K 線嗰日用公開 1 分鐘數據補，非經紀價。</p>"
    return f"<div class='section' id='rulesim'>{title}{note}{tbl}{recent}{foot}</div>"


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
             f"{s['risk'].get('XAU_LOTS', 0.01):.2f} 手；可沽空）；程式負責落單同硬性風控（日蝕 −{config.DAILY_LOSS_PAUSE_PCT:g}% 停開新倉{'、−' + format(config.DAILY_LOSS_STOP_PCT, 'g') + '% 平倉停機' if config.DAILY_LOSS_STOP_PCT < 100 else '、冇全平線（使用者 10-22）'}，夜盤 ×{config.NIGHT_MULT:g}，換日自動重開；累計虧損 25% 停開新倉、換日自動恢復；保證金水平低停開新倉；"
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
               f"<p>EA 持倉：{esc(_pos_text(s.get('position')))}</p><p>待執行指令：{len(s.get('pending_cmds') or [])} 條</p></div>"
               + live_book_section(f"💰 真倉績效・{esc(config.MAGIC)}（AI 自主）", s.get("live_book"))
               + live_book_section("💰 真倉績效・932（跟單）", s.get("live_book_follow")))
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
                + ("<div class='dec-scroll' style='overflow:auto;max-height:420px;border:1px solid #e5e7eb;border-radius:8px'>"   # 使用者 10-30：太長，用捲軸
                   "<style>.dec-scroll th{position:sticky;top:0;background:#fff;z-index:1}</style>"
                   "<table><tr><th>HKT</th><th>價</th><th>動作</th><th>理由</th><th>延遲</th></tr>" + drows + "</table></div>"
                   if drows else "<p class='muted'>未有決策。</p>"))
    if s.get("execute"):                                         # [R352] 已轉真倉：決策搬去真倉段，模擬倉只寫停咗（有舊紙上單就照列）
        real = real[:-len("</div>")] + "<div class='section'>" + dec_html + "</div></div>"
        sim = ("<div class='lf-grp lf-sim' id='lf-sim-top'><div class='lf-banner'>🧪 模擬倉績效</div>"
               + "<div class='section'><p><b>已轉真倉，模擬停。</b>決策直接落真倉（見上面 💰 真倉績效）；以下係轉真倉前嘅紙上成績。</p>"
               + (metric_cards(m) + trades_html if m["trades"] else "<p class='muted'>冇紙上成交紀錄。</p>") + "</div></div>")
    else:
        sim = ("<div class='lf-grp lf-sim' id='lf-sim-top'><div class='lf-banner'>🧪 模擬倉（前向測試）</div>"
               + f"<div class='section'><h2>{esc(config.SYMBOL)}</h2>" + top + trades_html + dec_html + "</div>"
               + "<div class='section'><h2>📊 模擬倉績效（按 HK$，1 美元 = 7.8 港元）</h2>" + metric_cards(m)
               + "<p class='muted' style='font-size:13px'>紙上成交用該根 M1 收市價，每張扣點差；同一根碰到止損同止賺當止損。樣本少時只供參考。</p></div></div>")
    sim += rulesim_section(s.get("rulesim"))                     # [R345] 即日回測（規則版）
    sim += forward_section(s.get("forward"), s.get("live_book"))   # [R352c] 前向測試
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
            + card("📅 數據封鎖（事件前 " + esc(f"{config.DATA_BLOCK_HOURS:g}") + " 小時唔開新倉）",
                   esc(("封鎖中：" + ((s.get("data_block") or {}).get("blocked") or {}).get("title", "")) if (s.get("data_block") or {}).get("blocked") else ("關" if not (s.get("data_block") or {}).get("on") else "冇")),
                   esc(("日曆 " + str((s.get("data_block") or {}).get("calendar_updated_utc") or "讀唔到") + "；下一件：" + "、".join(f"{u.get('t', '')[5:16]} {u.get('title', '')}" for u in ((s.get("data_block") or {}).get("upcoming") or [])[:2])) if (s.get("data_block") or {}).get("calendar_ok") else "⚠ 日曆讀唔到或舊過 48 小時：照常交易（R348）"))
            + "</div><div style='overflow-x:auto'><table><tr><th>硬性風控（環境變數，AI 無權改）</th><th>值</th></tr>" + risk_rows + "</table></div></div>")
    foot = "<p class='muted' style='font-size:13px'>模擬倉成績唔係真金白銀交易；過往成績亦唔代表將來回報。舊服務嘅投資人日誌／關卡開關／送單參數／錦囊兩頁，切換後由本頁取代。</p>"
    return (f"<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta name='color-scheme' content='light only'>"
            f"<meta http-equiv='refresh' content='300'><title>{esc(config.TEAM_EMOJI)} {esc(config.TEAM_NAME)}・{esc(config.SYMBOL)} 自動交易</title><style>{CSS}</style></head>"
            f"<body><div class='container'>{head}{intro}{real}{sim}{ctrl}{foot}</div></body></html>")
