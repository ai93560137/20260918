#!/usr/bin/env python3
# =============================================================================
# 每日美債快報 → Telegram
# -----------------------------------------------------------------------------
# 內容：
#   1. 殖利率：財政部每日殖利率曲線（3M/2Y/5Y/10Y/20Y/30Y），1 日 / 1 週 / 1 月 / 今年以來變動（bp）
#      利差：10Y−2Y、10Y−3M、30Y−10Y；實質利率（TIPS）與通膨預期（兩者相減）
#   2. 債券價格：TLT、IEF、SHY、TIP、LQD、HYG、EDV 與 10Y / 30Y 公債期貨（Yahoo 日線）
#      再用今天的殖利率算 10Y / 30Y 票面債的存續期間：殖利率每動 10bp 價格大約變多少
#   3. 公債標售：財政部 fiscaldata API，近 10 天長天期標售結果（得標殖利率、投標倍數）與未來一週排程
#   4. 新聞：Google News RSS（中英文關鍵字，過去 24 小時），去重後列標題與連結
#   5. 每日一則債券知識（依日期輪替）
# 任一來源失敗只略過該段，其餘照發。
#
# 用法：
#   python3 scripts/bond_daily.py            # 需要環境變數 TG_BOT_TOKEN、TG_CHAT_ID
#   python3 scripts/bond_daily.py --dry-run  # 只印出訊息，不發送
# 排程：.github/workflows/bond_daily.yml（美股每個交易日收盤後，台灣時間早上 07:30）
# =============================================================================
import argparse
import csv
import html
import io
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"}
URL_UST = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           "daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
URL_YAHOO = "https://{host}.finance.yahoo.com/v8/finance/chart/{t}?range=1y&interval=1d"
URL_STOOQ = "https://stooq.com/q/d/l/?s={t}&i=d&d1={d1:%Y%m%d}&d2={d2:%Y%m%d}"
URL_FISCAL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/"
URL_GNEWS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"

TENORS = [("3M", "3mo"), ("2Y", "2yr"), ("5Y", "5yr"), ("10Y", "10yr"), ("20Y", "20yr"), ("30Y", "30yr")]
TICKERS = [
    ("TLT", "20 年以上美債 ETF"),
    ("EDV", "超長天期零息美債 ETF"),
    ("IEF", "7–10 年美債 ETF"),
    ("SHY", "1–3 年美債 ETF"),
    ("TIP", "抗通膨債 ETF"),
    ("LQD", "投資級公司債 ETF"),
    ("HYG", "高收益債 ETF"),
    ("ZN=F", "10 年期公債期貨"),
    ("ZB=F", "30 年期公債期貨"),
]
NEWS_QUERIES = [
    ("美債 殖利率", "zh-TW"), ("美國公債 長債", "zh-TW"), ("債券 聯準會", "zh-TW"),
    ('"Treasury yields"', "en-US"), ('"30-year" Treasury bond', "en-US"),
    ("bond market selloff OR rally", "en-US"), ("Treasury auction", "en-US"),
]
NEWS_MAX = 12

# 每日一則債券知識，依「年內第幾天」輪替
KNOWLEDGE = [
    ("殖利率與價格反向", "債券的票息是固定的，市場利率上升時，舊債的固定票息變得不吸引人，價格就得下跌，直到它的殖利率和新債一樣。所以「殖利率創新高」就等於「債券價格創新低」。"),
    ("存續期間（Duration）", "衡量債券價格對利率有多敏感。修正存續期間 15 的債券，殖利率上升 1 個百分點，價格大約跌 15%。期限越長、票息越低，存續期間越長，價格波動越大。"),
    ("凸性（Convexity）", "價格和殖利率的關係是一條往下彎的曲線，不是直線。凸性讓長債在利率下跌時漲得比利率上升時跌得多；利率波動大時，凸性越高越有利。"),
    ("殖利率曲線", "把不同期限的公債殖利率連成一條線。正常時長天期較高（補償時間風險）；短天期高於長天期叫「倒掛」，通常代表市場預期未來會降息、經濟轉弱。"),
    ("熊市變陡 vs 牛市變陡", "曲線變陡有兩種：長債殖利率往上衝（熊市變陡，常見於擔心通膨或財政赤字），或短債殖利率往下掉（牛市變陡，常見於 Fed 開始降息）。對股市的含義完全不同。"),
    ("期限溢價（Term Premium）", "持有長債而不是一路滾動短債，投資人要求的額外補償。赤字擴大、通膨不確定、Fed 縮表時期限溢價會上升，長債殖利率就算沒有升息也會走高。"),
    ("實質利率與 TIPS", "TIPS（抗通膨公債）的本金會隨 CPI 調整，它的殖利率就是「實質利率」。實質利率越高，持有現金和債券越划算，對成長股與黃金壓力越大。"),
    ("通膨預期（Breakeven）", "名目公債殖利率 − 同期限 TIPS 殖利率 = 市場預期的平均通膨率。10 年期通膨預期長期在 2%–2.5% 附近，明顯突破代表市場對 Fed 控制通膨的信心下降。"),
    ("公債標售怎麼看", "財政部定期標售公債。重點看三個：投標倍數（越高需求越好）、得標殖利率和發行前市場殖利率的差（尾差，正值代表需求弱）、間接投標比例（外國央行與基金的需求）。"),
    ("30 年期公債", "美國最長的公債，存續期間約 15–17。退休基金、保險公司是主要買家，因為它們的負債也很長。30 年期殖利率反映的是市場對美國長期通膨與財政的看法。"),
    ("TLT 與長債 ETF", "TLT 持有 20 年以上美債，存續期間約 16–17；EDV 持有零息長債，存續期間約 24，波動更大。買長債 ETF 等於押注長期利率下跌。"),
    ("零息債券", "不付票息、以折價發行，到期領回面額。所有報酬都集中在到期那一刻，所以存續期間等於到期年數，是對利率最敏感的債券。"),
    ("票息再投資風險", "持有付息債券時，收到的票息要以當時的利率再投資。利率下跌時，再投資報酬變低，實際報酬會低於買進時的殖利率。"),
    ("信用利差", "公司債殖利率 − 同期限公債殖利率。利差擴大代表市場擔心違約，常常早於股市下跌。高收益債（垃圾債）利差是觀察信用風險最直接的指標。"),
    ("Fed 與短天期利率", "Fed 直接控制隔夜利率，所以 3 個月到 2 年期公債主要反映「未來幾次會議會升息還是降息」。2 年期殖利率是觀察市場預期 Fed 路徑的最佳指標。"),
    ("量化緊縮（QT）", "Fed 讓持有的公債到期不再投資，等於從市場收回買盤。市場上要吸收的公債變多，通常推升長天期殖利率與期限溢價。"),
    ("財政赤字與長債", "赤字越大，財政部要發的公債越多，市場需要更高的殖利率才吸收得了。近年長債殖利率走高，財政供給是被討論最多的原因之一。"),
    ("債券的總報酬", "債券總報酬 = 票息收入 + 價格變動。殖利率 5% 的長債，只要一年內殖利率上升不超過約 0.3 個百分點（5% ÷ 存續期間 16），票息就能抵銷價格損失。"),
    ("股債相關性", "過去 20 年股債多半反向（股跌時債漲，可以避險）；但在通膨主導的時期（1970–90 年代、2022 年起）股債會同跌，60/40 組合的避險效果變差。"),
    ("MOVE 指數", "債市的「恐慌指數」，衡量美債選擇權隱含的波動率，概念類似股市的 VIX。MOVE 飆高時，債市流動性通常變差，也常外溢到股市與匯市。"),
    ("殖利率計算單位 bp", "1 個基點（bp）= 0.01 個百分點。殖利率從 5.00% 升到 5.10% 叫上升 10bp。債市行情多用 bp 表達，因為變動通常很小但金額很大。"),
    ("到期殖利率（YTM）", "假設持有到期、票息都以同一利率再投資，買進價格所隱含的年化報酬率。新聞上講的「10 年期殖利率」就是剛發行那檔 10 年期公債的到期殖利率。"),
    ("指標券（On-the-run）", "最新發行的那一檔公債，成交最活絡，新聞引用的殖利率大多是它。舊券（off-the-run）流動性較差，殖利率通常略高一點。"),
    ("債券期貨", "ZN 是 10 年期公債期貨、ZB 是 30 年期。一口 ZB 面額 10 萬美元，價格以 1/32 為跳動單位。機構常用期貨快速調整存續期間或避險。"),
    ("日本與全球長債", "日本央行放寬殖利率控制後，日本長債殖利率上升，日本資金有更多理由留在國內，減少買美債。全球長債殖利率常常同步移動。"),
    ("債券與美元、黃金", "美債殖利率上升通常推升美元、壓抑黃金（持有黃金的機會成本上升）；但如果殖利率上升是因為市場擔心美國財政信用，美元和黃金可能同時上漲。"),
    ("降息不一定壓低長債", "Fed 降息直接壓低短天期利率，但如果市場認為降息會讓通膨回來，長債殖利率反而可能上升，2024 年 9 月降息後 10 年期殖利率上升就是例子。"),
    ("債券的「階梯」配置", "把資金分散到不同到期年份（例如 1、2、3、5、10 年），每年都有債券到期可以再投資，降低一次押在某個利率水位的風險。"),
    ("公債與存款的差別", "公債由美國政府擔保、可以隨時在市場賣出，但賣出價格會隨利率波動；持有到期則領回面額。短天期國庫券（T-bill）幾乎沒有價格風險，常被當作現金替代品。"),
    ("盈餘殖利率 vs 公債", "股票的盈餘殖利率（本益比的倒數）減掉 10 年期公債殖利率，可以粗略比較股票和公債哪個比較划算。差距越低，股票相對公債越貴。"),
]


# ---------------------------------------------------------------- 工具
def get(url, retries=3, timeout=(10, 30)):
    for i in range(retries):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def section(name, fn, *a):
    """單一段落失敗只印警告並回空字串，不影響其他段落。"""
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001 — 任何來源錯誤都只略過該段
        print(f"::warning::{name} 失敗：{e}")
        return ""


def esc(s):
    return html.escape(str(s), quote=False)


def bp(x):
    """百分點差 → bp 字串（0.10 → +10）。"""
    return "—" if x is None else f"{x * 100:+.0f}"


def pctf(x):
    return "—" if x is None else f"{x * 100:+.1f}%"


# ---------------------------------------------------------------- 1. 殖利率
def treasury(kind, years):
    """財政部殖利率 CSV → [(date, {欄位小寫無空白: 值})]，由舊到新。"""
    rows = []
    for yr in years:
        text = get(URL_UST.format(year=yr, kind=kind)).text
        for r in csv.DictReader(io.StringIO(text)):
            d = datetime.strptime(r.pop("Date"), "%m/%d/%Y").date()
            vals = {k.lower().replace(" ", ""): float(v) for k, v in r.items() if k and v not in (None, "")}
            rows.append((d, vals))
    rows.sort(key=lambda x: x[0])
    return rows


def at_or_before(rows, d):
    """rows 中日期 ≤ d 的最後一筆。"""
    best = None
    for day, v in rows:
        if day <= d:
            best = (day, v)
        else:
            break
    return best


def yields_block(today):
    nom = treasury("daily_treasury_yield_curve", [today.year - 1, today.year])
    if len(nom) < 2:
        raise ValueError("殖利率資料不足")
    d0, cur = nom[-1]
    prev = nom[-2][1]
    wk = at_or_before(nom, d0 - timedelta(days=7))
    mo = at_or_before(nom, d0 - timedelta(days=30))
    ytd = at_or_before(nom, date(d0.year - 1, 12, 31))
    ref = {"1日": prev, "1週": wk and wk[1], "1月": mo and mo[1], "今年": ytd and ytd[1]}

    L = [f"<b>① 美債殖利率</b>（財政部，{d0:%m/%d}，變動單位 bp）",
         "<pre>Tenor  Yield    1d   1w   1m  YTD"]
    for label, key in TENORS:
        if key not in cur:
            continue
        ch = [bp(cur[key] - r[key]) if r and key in r else "—" for r in ref.values()]
        L.append(f"{label:<5} {cur[key]:>5.2f}% {ch[0]:>4} {ch[1]:>4} {ch[2]:>4} {ch[3]:>4}")
    L.append("</pre>")

    def spread(a, b, r):
        return r[a] - r[b] if r and a in r and b in r else None
    sp = []
    for label, a, b in (("10Y−2Y", "10yr", "2yr"), ("10Y−3M", "10yr", "3mo"), ("30Y−10Y", "30yr", "10yr")):
        s, s1 = spread(a, b, cur), spread(a, b, mo and mo[1])
        if s is not None:
            sp.append(f"{label} {s:+.2f}" + (f"（1 月前 {s1:+.2f}）" if s1 is not None else ""))
    L.append("利差：" + "；".join(sp))

    # 實質利率與通膨預期
    try:
        real = treasury("daily_treasury_real_yield_curve", [d0.year])
        rd, rv = real[-1]
        parts = []
        for label, key in (("10Y", "10yr"), ("30Y", "30yr")):
            if key in rv and key in cur:
                parts.append(f"{label} 實質 {rv[key]:.2f}%、通膨預期 {cur[key] - rv[key]:.2f}%")
        if parts:
            L.append("TIPS：" + "；".join(parts))
    except Exception as e:  # noqa: BLE001
        print(f"::warning::實質利率失敗：{e}")

    # 趨勢註記：10Y / 30Y 是否創 52 週新高 / 新低
    year_ago = d0 - timedelta(days=365)
    for label, key in (("10Y", "10yr"), ("30Y", "30yr")):
        hist = [v[key] for d, v in nom if d >= year_ago and key in v]
        if hist and cur.get(key) is not None:
            if cur[key] >= max(hist):
                L.append(f"⚠️ {label} 殖利率創 52 週新高（= 長債價格 52 週新低）")
            elif cur[key] <= min(hist):
                L.append(f"✅ {label} 殖利率創 52 週新低（= 長債價格 52 週新高）")
    return "\n".join(L), cur


# ---------------------------------------------------------------- 2. 債券價格
def yahoo(t):
    """Yahoo 日線收盤 [(date, close)]。GitHub runner 常被 429 限流，所以兩個主機輪流、慢慢重試。"""
    err = None
    for i, host in enumerate(("query1", "query2", "query1", "query2")):
        try:
            r = requests.get(URL_YAHOO.format(host=host, t=quote(t)), headers=UA, timeout=(10, 30))
            if r.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests")
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            return [(datetime.fromtimestamp(ts, timezone.utc).date(), c)
                    for ts, c in zip(res.get("timestamp") or [], q["close"]) if c]
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
            err = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(err)


def stooq(t):
    """Stooq 日線（Yahoo 抓不到時的備援，只有美股 ETF）。"""
    if t.endswith("=F"):
        raise ValueError("Stooq 不提供這檔")
    today = date.today()
    text = get(URL_STOOQ.format(t=f"{t.lower()}.us", d1=today - timedelta(days=400), d2=today)).text
    out = [(date.fromisoformat(r["Date"]), float(r["Close"])) for r in csv.DictReader(io.StringIO(text))
           if r.get("Close") not in (None, "", "N/D")]
    if not out:
        raise ValueError("Stooq 無資料")
    return out


def chg(series, days=None, ytd=False):
    if len(series) < 2:
        return None
    d0, last = series[-1]
    if ytd:
        base = [c for d, c in series if d.year < d0.year]
    elif days == 1:
        base = [series[-2][1]]
    else:
        base = [c for d, c in series if d <= d0 - timedelta(days=days)]
    return last / base[-1] - 1 if base else None


def fmt_price(t, p):
    if t.endswith("=F"):  # 公債期貨以 1/32 報價
        whole = int(p)
        return f"{whole}'{round((p - whole) * 32):02d}"
    return f"{p:.2f}"


def prices_block():
    L = ["<b>② 債券價格</b>", "<pre>Ticker  Price     1d     1w     1m    YTD"]
    notes = []
    for t, name in TICKERS:
        s = None
        for src in (yahoo, stooq):
            try:
                s = src(t)
                break
            except Exception as e:  # noqa: BLE001
                print(f"::warning::{t} {src.__name__} 失敗：{e}")
        if not s:
            continue
        L.append(f"{t:<6} {fmt_price(t, s[-1][1]):>7} {pctf(chg(s, 1)):>6} {pctf(chg(s, 7)):>6} "
                 f"{pctf(chg(s, 30)):>6} {pctf(chg(s, ytd=True)):>6}")
        notes.append(f"{t} {name}")
        time.sleep(1)
    if len(L) == 2:
        raise ValueError("所有報價都抓不到")
    L.append("</pre>")
    L.append("<i>" + "、".join(notes) + "</i>")
    return "\n".join(L)


def bond_math(y, years, coupon=None):
    """半年付息債券：回傳 (價格/100 面額, 修正存續期間, 凸性)。coupon 省略 = 票面債（票息等於殖利率）。"""
    y, c = y / 100, (coupon if coupon is not None else y) / 100
    n, i = int(years * 2), y / 2
    cfs = [(k, c / 2 * 100 + (100 if k == n else 0)) for k in range(1, n + 1)]
    pv = [(k, cf / (1 + i) ** k) for k, cf in cfs]
    price = sum(v for _, v in pv)
    mac = sum(k / 2 * v for k, v in pv) / price
    mod = mac / (1 + i)
    conv = sum(k * (k + 1) * v for k, v in pv) / (price * (1 + i) ** 2) / 4
    return price, mod, conv


def sensitivity_block(cur):
    if not cur:
        return ""
    L = ["<b>③ 長債價格敏感度</b>（以今天殖利率發行的票面債）"]
    for label, key, yrs in (("10Y", "10yr", 10), ("30Y", "30yr", 30)):
        if key not in cur:
            continue
        y = cur[key]
        _, mod, conv = bond_math(y, yrs)
        up = bond_math(y + 0.5, yrs, coupon=y)[0] / 100 - 1
        dn = bond_math(y - 0.5, yrs, coupon=y)[0] / 100 - 1
        L.append(f"{label}（{y:.2f}%）：存續期間 {mod:.1f}，殖利率每 ±10bp 價格約 ∓{mod * 0.1:.1f}%；"
                 f"升 50bp {pctf(up)}、降 50bp {pctf(dn)}；"
                 f"票息可抵銷的殖利率上升空間約 {y / mod * 100:.0f}bp / 年")
    return "\n".join(L)


# ---------------------------------------------------------------- 3. 公債標售
def fiscal(endpoint, params):
    return get(f"{URL_FISCAL}{endpoint}?{urlencode(params, safe=':,()[]-')}").json().get("data") or []


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def auctions_block(today):
    L = ["<b>④ 公債標售</b>"]
    since = (today - timedelta(days=10)).isoformat()
    done = fiscal("auctions_query", {
        "filter": f"auction_date:gte:{since},security_type:in:(Note,Bond)",
        "sort": "-auction_date", "page[size]": 20})
    seen = set()
    for r in done:
        term = r.get("security_term") or ""
        hy, btc = num(r.get("high_yield")), num(r.get("bid_to_cover_ratio"))
        if hy is None or btc is None or (term, r.get("auction_date")) in seen:
            continue  # 還沒公布結果
        seen.add((term, r.get("auction_date")))
        ind = num(r.get("indirect_bidder_accepted"))
        tot = num(r.get("total_accepted") or r.get("offering_amt"))
        share = f"、海外等間接投標 {ind / tot * 100:.0f}%" if ind and tot else ""
        tips = (r.get("inflation_index_security") or "").lower() == "yes"
        L.append(f"已標：{r.get('auction_date')} {esc(term)} {'TIPS ' if tips else ''}{esc(r.get('security_type'))}"
                 f" 得標{'實質' if tips else ''}殖利率 {hy:.3f}%、投標倍數 {btc:.2f}{share}")
    up = fiscal("upcoming_auctions", {"sort": "auction_date", "page[size]": 30})
    horizon = today + timedelta(days=7)
    for r in up:
        try:
            ad = date.fromisoformat(r.get("auction_date", ""))
        except ValueError:
            continue
        if today <= ad <= horizon and (r.get("security_type") or "") != "Bill":
            amt = num(r.get("offering_amt"))
            L.append(f"將標：{ad:%m/%d} {esc(r.get('security_term'))} {esc(r.get('security_type'))}"
                     + (f"，{amt / 1e8:,.0f} 億美元" if amt else ""))
    return "\n".join(L) if len(L) > 1 else ""


# ---------------------------------------------------------------- 4. 新聞
def news_block(now):
    items, seen = [], set()
    ceid = {"zh-TW": "TW:zh-Hant", "en-US": "US:en"}
    for q, lang in NEWS_QUERIES:
        url = URL_GNEWS.format(q=quote(q + " when:1d"), hl=lang, gl=lang[-2:], ceid=ceid[lang])
        try:
            root = ET.fromstring(get(url).content)
        except Exception as e:  # noqa: BLE001
            print(f"::warning::新聞 {q} 失敗：{e}")
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            src = (it.findtext("source") or "").strip()
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            title = re.sub(r"\s*[|｜]\s*[^|｜]{1,20}$", "", title)  # 去掉「 | 媒體名」尾巴
            key = re.sub(r"^[A-Z ]+-", "", title)  # 去掉「GLOBAL MARKETS-」這類前綴
            key = re.sub(r"\W+", "", key.lower())
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate"))
            except (TypeError, ValueError):
                continue
            if not title or now - pub > timedelta(hours=26):
                continue
            if any(SequenceMatcher(None, key, k).ratio() > 0.75 for k in seen):
                continue
            seen.add(key)
            items.append((pub, title, src, it.findtext("link") or ""))
    if not items:
        return ""
    items.sort(reverse=True)
    L = ["<b>⑤ 債市新聞</b>（過去 24 小時）"]
    for pub, title, src, link in items[:NEWS_MAX]:
        L.append(f"• <a href=\"{html.escape(link)}\">{esc(title)}</a>" + (f"（{esc(src)}）" if src else ""))
    return "\n".join(L)


# ---------------------------------------------------------------- 5. 知識
def knowledge_block(today):
    title, body = KNOWLEDGE[today.timetuple().tm_yday % len(KNOWLEDGE)]
    return f"<b>⑥ 今日債券知識：{esc(title)}</b>\n{esc(body)}"


# ---------------------------------------------------------------- 發送
def split_msg(text, limit=3900):
    """依段落切成 Telegram 單則上限內的多則；<pre> 區塊不會被切開（段落以空行分隔）。"""
    out, buf = [], ""
    for part in text.split("\n\n"):
        if buf and len(buf) + len(part) + 2 > limit:
            out.append(buf)
            buf = ""
        buf = f"{buf}\n\n{part}" if buf else part
    if buf:
        out.append(buf)
    return out


def send(text, token, chat):
    for chunk in split_msg(text):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, data={
            "chat_id": chat, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": "true"})
        if not r.ok:
            raise RuntimeError(f"Telegram {r.status_code}: {r.text[:200]}")
        time.sleep(1)


def build(now):
    today = now.date()
    head = f"📊 <b>每日美債快報</b> {today:%Y-%m-%d}"
    y_text, cur = "", None
    try:
        y_text, cur = yields_block(today)
    except Exception as e:  # noqa: BLE001
        print(f"::warning::殖利率失敗：{e}")
    parts = [head, y_text,
             section("債券價格", prices_block),
             section("敏感度", sensitivity_block, cur),
             section("公債標售", auctions_block, today),
             section("新聞", news_block, now),
             knowledge_block(today)]
    return "\n\n".join(p for p in parts if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印出訊息，不發送")
    args = ap.parse_args()
    msg = build(datetime.now(timezone.utc))
    print(msg)
    if args.dry_run:
        return
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        print("::warning::TG_BOT_TOKEN / TG_CHAT_ID 沒設，未發送")
        return
    if msg.count("<b>") < 3:  # 只有標題與知識 → 資料來源全掛，不發半空的快報
        sys.exit("資料來源全部失敗，未發送")
    send(msg, token, chat)
    print("telegram sent")


if __name__ == "__main__":
    main()
