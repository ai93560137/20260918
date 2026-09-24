#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八陣圖指令台數據:抓恒指期貨即月 + 金期貨最近 3 個完整交易日的日高/日低。

跑在 GitHub Actions runner(外網全通),輸出 tradingview/data_external/levels.json,
session 端 git pull 後讀取並寫入 Artifact 資料庫。
HKEX widget 手法(token/JSONP/headers)同 fetch_hkex_quotes.py,詳見
tradingview/DATA_PIPELINE.md。
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests

HKT = timezone(timedelta(hours=8))
ET = timezone(timedelta(hours=-4))          # 夏令;冬令差 1 小時對「排除未完日」判斷無影響
OUT = 'tradingview/data_external'
log = []

S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                  'Referer': 'https://www.hkex.com.hk/'})

result = {'fetched_at': datetime.now(HKT).strftime('%Y-%m-%d %H:%M HKT')}


def num(x):
    try:
        return float(str(x).replace(',', ''))
    except (TypeError, ValueError):
        return None


def hsi_levels():
    page = S.get('https://www.hkex.com.hk/Market-Data/Futures-and-Options-Prices/'
                 'Equity-Index/Hang-Seng-Index-Futures-and-Options?sc_lang=en', timeout=30).text
    token = re.search(r'return\s*"(evLts[^"]+)"', page).group(1)

    def call(ep, **params):
        qid = str(int(time.time() * 1000))
        q = '&'.join(f"{k}={v}" for k, v in params.items())
        u = f'https://www1.hkex.com.hk/hkexwidget/data/{ep}?lang=eng&token={token}&{q}&qid={qid}&callback=j'
        body = S.get(u, timeout=30).text
        m = re.search(r'^j\((.*)\)\s*$', body, re.S)
        return json.loads(m.group(1)) if m else None

    # getchartdata2 的 int/span 組合未在別處驗證過:網格嘗試,取到合理日線序列為準
    rows = None
    for i, sp in [(8, 6), (8, 3), (9, 6), (6, 6), (7, 6), (8, 2)]:
        try:
            d = call('getchartdata2', hchart=1, span=sp, int=i, ric='HSIc1')
            dl = (d or {}).get('data', {}).get('datalist') or []
            # 期望格式 [ts_ms, open, high, low, close, ...];至少 5 根、價位合理
            cand = [r for r in dl if isinstance(r, list) and len(r) >= 5
                    and r[2] and r[3] and 15000 < float(r[3]) < float(r[2]) < 40000]
            if len(cand) >= 5:
                # 判斷是否日線:相鄰時間戳間隔 >= 20 小時
                gaps = [(cand[k+1][0] - cand[k][0]) / 3600000 for k in range(len(cand)-1)]
                if gaps and min(gaps[-5:]) >= 20:
                    rows = cand
                    log.append(f'getchartdata2 int={i} span={sp}: {len(cand)} daily rows')
                    break
        except Exception as e:
            log.append(f'getchartdata2 int={i} span={sp}: {e}')
    if not rows:
        raise RuntimeError('getchartdata2 no usable daily series: ' + ' | '.join(log[-6:]))

    # 港交所慣例:夜市屬下一交易日,故當日日線於 16:30 收市即完結。
    # 16:35(HKT)後把「今天」納入窗口,與 TradingView 的日界一致。
    now_hk = datetime.now(HKT)
    cutoff = now_hk.date() if (now_hk.hour, now_hk.minute) >= (16, 35) else \
        (now_hk.date() - timedelta(days=1))
    for r in rows[-4:]:                                    # 除錯:源序列尾部原樣記錄
        ts = datetime.fromtimestamp(r[0] / 1000, tz=HKT)
        log.append(f'raw {ts:%Y-%m-%d %H:%M} h={r[2]} l={r[3]}')
    days = []
    for r in rows:
        d = datetime.fromtimestamp(r[0] / 1000, tz=HKT).date()
        if d <= cutoff:                                    # 只要已完結的日
            days.append((d, float(r[2]), float(r[3])))     # (date, high, low)
    # 傍晚補位:EOD 序列常晚半天才補當天的行。若 cutoff 日已完結但序列缺行,
    # 用日內數據按 HKEX 交易日窗口(前一交易日 17:10 夜市起 → 當日 16:35)聚合。
    agg_note = ''
    if days and days[-1][0] < cutoff and cutoff.weekday() < 5:
        back = 3 if cutoff.weekday() == 0 else 1            # 週一的夜市始於上週五
        w0 = datetime.combine(cutoff - timedelta(days=back),
                              datetime.min.time(), tzinfo=HKT) + timedelta(hours=17, minutes=10)
        w1 = datetime.combine(cutoff, datetime.min.time(), tzinfo=HKT) + timedelta(hours=16, minutes=35)
        # 逐組嘗試,以「窗口內夠多根」為準——小 span 的緩衝在深夜會滑出目標窗口
        for i, sp in [(4, 1), (4, 2), (5, 2), (3, 2), (5, 3), (6, 3)]:
            try:
                d2 = call('getchartdata2', hchart=1, span=sp, int=i, ric='HSIc1')
                dl = (d2 or {}).get('data', {}).get('datalist') or []
                cand = [r for r in dl if isinstance(r, list) and len(r) >= 5
                        and r[2] and r[3] and 15000 < float(r[3]) <= float(r[2]) < 40000]
                seg = [r for r in cand
                       if w0 <= datetime.fromtimestamp(r[0] / 1000, tz=HKT) < w1]
                span_dbg = ''
                if cand:
                    t0 = datetime.fromtimestamp(cand[0][0] / 1000, tz=HKT)
                    t1 = datetime.fromtimestamp(cand[-1][0] / 1000, tz=HKT)
                    span_dbg = f' [{t0:%m-%d %H:%M}..{t1:%m-%d %H:%M}]'
                log.append(f'intraday int={i} span={sp}: {len(cand)} rows, {len(seg)} in window{span_dbg}')
                if len(seg) >= 30:
                    hi_d = max(float(r[2]) for r in seg)
                    lo_d = min(float(r[3]) for r in seg)
                    days.append((cutoff, hi_d, lo_d))
                    agg_note = '(當日由日內聚合)'
                    log.append(f'aggregated {cutoff}: h={hi_d} l={lo_d} from {len(seg)} bars')
                    break
            except Exception as e:
                log.append(f'intraday int={i} span={sp}: {e}')
    # 深夜補位第二招:期貨報價 widget 的當日高低。深夜 lastupd 停在日市收市
    # (實測 00:49 仍見 '22/09/2026 16:29'),日期等於 cutoff 時其 hi/lo 即當日高低。
    # 注意:此 hi/lo 只覆蓋日市段;昨夜市段(屬同一交易日)由前次執行存下的
    # night 記錄(見報價段)在此合併,否則上軌可能低估(09-23 實測差 170 點)。
    if days and days[-1][0] < cutoff and cutoff.weekday() < 5:
        try:
            q0 = call('getderivativesfutures', ats='HSI', type=0)
            qd0 = (q0 or {}).get('data', {})
            row0 = (qd0.get('futureslist') or [{}])[0]
            log.append('futureslist[0] raw: ' + json.dumps(
                {k: row0.get(k) for k in sorted(row0)}, ensure_ascii=False)[:700])
            hi_q, lo_q = num(row0.get('hi')), num(row0.get('lo'))
            lu = str(qd0.get('lastupd', ''))
            m = re.match(r'(\d{2})/(\d{2})/(\d{4})', lu)
            lu_d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date() if m else None
            if lu_d == cutoff and hi_q and lo_q and 15000 < lo_q <= hi_q < 40000:
                agg_note = '(當日取自收市報價)'
                try:
                    prev = json.load(open(f'{OUT}/levels.json', encoding='utf-8'))
                    n = (prev.get('hsi') or {}).get('night') or {}
                    nh, nl = num(n.get('h')), num(n.get('l'))
                    if n.get('date') == str(cutoff) and nh and nl and 15000 < nl <= nh < 40000:
                        hi_q, lo_q = max(hi_q, nh), min(lo_q, nl)
                        agg_note = '(當日=收市報價+昨夜市合併)'
                        log.append(f'night merged {n}')
                except Exception as e:
                    log.append(f'night merge skip: {e}')
                days.append((cutoff, hi_q, lo_q))
                log.append(f'quote hi/lo accepted {cutoff}: h={hi_q:.0f} l={lo_q:.0f}')
            else:
                log.append(f'quote hi/lo rejected: lastupd={lu!r} hi={hi_q} lo={lo_q}')
        except Exception as e:
            log.append(f'quote hi/lo fail: {e}')
    # 第三招:Yahoo HSI=F 日線,先用已知 HKEX 日子交叉驗證(容差 40 點)才敢收缺行。
    if days and days[-1][0] < cutoff and cutoff.weekday() < 5:
        try:
            import yfinance as yf
            df = yf.download('HSI=F', period='10d', interval='1d',
                             progress=False, auto_adjust=False)
            log.append(f'yahoo HSI=F df rows={len(df)}')
            if hasattr(df.columns, 'levels'):
                df.columns = df.columns.get_level_values(0)
            ymap = {}
            for idx, r in df.iterrows():
                h, l = float(r['High']), float(r['Low'])
                if 15000 < l <= h < 40000:
                    ymap[idx.date()] = (h, l)
                    log.append(f'yahoo HSI=F {idx.date()} h={h:.0f} l={l:.0f}')
            known = {d: (h, l) for d, h, l in days}
            overlap = [d for d in ymap if d in known]
            bad = [d for d in overlap
                   if abs(ymap[d][0] - known[d][0]) > 40 or abs(ymap[d][1] - known[d][1]) > 40]
            if cutoff in ymap and len(overlap) >= 2 and not bad:
                h, l = ymap[cutoff]
                days.append((cutoff, h, l))
                agg_note = '(當日補自 Yahoo HSI=F)'
                log.append(f'yahoo fallback accepted {cutoff}: h={h:.0f} l={l:.0f} '
                           f'(validated on {len(overlap)} overlap days)')
            else:
                log.append(f'yahoo fallback rejected: cutoff_in={cutoff in ymap} '
                           f'overlap={len(overlap)} bad={[str(d) for d in bad]}')
        except Exception as e:
            log.append(f'yahoo fallback fail: {e}')
    days = days[-3:]
    if len(days) < 3:
        raise RuntimeError(f'only {len(days)} completed days')
    days.reverse()                                          # [0]=最近一日
    out = {}
    for n, (d, h, l) in enumerate(days, 1):
        out[f'h{n}'], out[f'l{n}'] = round(h), round(l)
    out['dates'] = [str(d) for d, _, _ in days]
    out['agg'] = agg_note

    # 延遲報價:近月買賣中間價。type=0 日市 / type=1 夜市(T+1),日市報價在
    # 夜市時段會凍結在 16:29——兩邊都拿,取 lastupd 較新且有雙邊報價的一邊。
    try:
        best = None
        for typ, tag in ((0, '日市'), (1, '夜市')):
            try:
                q = call('getderivativesfutures', ats='HSI', type=typ)
                qd = (q or {}).get('data', {})
                row = (qd.get('futureslist') or [{}])[0]
                bd, as_, se = num(row.get('bd')), num(row.get('as')), num(row.get('se'))
                lu = str(qd.get('lastupd', ''))
                m = re.match(r'(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})', lu)
                ts = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)),
                              int(m.group(4)), int(m.group(5))) if m else None
                log.append(f'quote {tag}: bd={bd} as={as_} se={se} lastupd={lu!r}')
                # 記下夜市時段高低給下次執行合併(夜市屬下一交易日:
                # lastupd 17:15-23:59 → 翌日;00:00-03:00 → 當日;週末順延至週一)
                if typ == 1 and ts:
                    nh, nl = num(row.get('hi')), num(row.get('lo'))
                    if nh and nl and 15000 < nl <= nh < 40000:
                        nd = ts.date() + timedelta(days=1 if ts.hour >= 12 else 0)
                        while nd.weekday() >= 5:
                            nd += timedelta(days=1)
                        out['night'] = {'date': str(nd), 'h': nh, 'l': nl, 'asof': lu}
                        log.append(f"night session saved: {out['night']}")
                cand = None
                if bd and as_ and 15000 < bd <= as_ < 40000:
                    cand = {'px': round((bd + as_) / 2), 'kind': f'中間價({tag})', 'asof': lu}
                elif typ == 0 and se:
                    cand = {'px': round(se), 'kind': '昨結(非現價)', 'asof': lu}
                if cand and (best is None or (ts and best[0] and ts > best[0])
                             or (ts and not best[0])):
                    best = (ts, cand)
            except Exception as e:
                log.append(f'quote type={typ} fail: {e}')
        if best:
            out['quote'] = best[1]
        log.append(f"hsi quote: {out.get('quote')}")
    except Exception as e:
        log.append(f'hsi quote fail: {e}')
    if 'night' not in out:                      # 本次拿不到夜市記錄則沿用上次的
        try:
            prev = json.load(open(f'{OUT}/levels.json', encoding='utf-8'))
            n = (prev.get('hsi') or {}).get('night')
            if n:
                out['night'] = n
        except Exception:
            pass
    return out


def gold_levels():
    """XAUUSD 現貨為主源(與 TV/券商報價一致),GC=F 期貨後備(差 carry 幾十美元)。
    日界:紐約 17:00(ET)收市——未收市前當日 bar 進行中,不入通道。"""
    import yfinance as yf
    now_et = datetime.now(ET)
    cutoff = now_et.date() if now_et.hour >= 17 else now_et.date() - timedelta(days=1)

    def daily(sym):
        df = yf.download(sym, period='10d', interval='1d', progress=False, auto_adjust=False)
        if hasattr(df.columns, 'levels'):
            df.columns = df.columns.get_level_values(0)
        rows = []
        for idx, r in df.iterrows():
            d = idx.date()
            try:
                h, l = float(r['High']), float(r['Low'])
            except (TypeError, ValueError):
                continue
            if d <= cutoff and 1500 < l < h < 6000:        # 嚴格 l<h 也擋掉壞行
                rows.append((d, h, l))
        raw = ''
        if len(df):
            r0 = df.iloc[-1]
            raw = f" raw_last={df.index[-1].date()} H={r0.get('High')} L={r0.get('Low')}"
        log.append(f'{sym} daily: df={len(df)} rows, {len(rows)} valid{raw}')
        return rows[-3:]

    rows, src = [], ''
    for sym, label in (('XAUUSD=X', 'Yahoo XAUUSD 現貨'), ('XAU=X', 'Yahoo XAU 現貨'),
                       ('GC=F', 'Yahoo GC=F(期貨,現貨源缺數據)')):
        try:
            rows, src = daily(sym), label
        except Exception as e:
            log.append(f'{sym} daily fail: {e}')
        if len(rows) >= 3:
            break
    if len(rows) < 3:
        raise RuntimeError(f'only {len(rows)} completed days')
    rows.reverse()
    out = {'src': src}
    for n, (d, h, l) in enumerate(rows, 1):
        out[f'h{n}'], out[f'l{n}'] = round(h, 1), round(l, 1)
    out['dates'] = [str(d) for d, _, _ in rows]
    for sym, kind in (('XAUUSD=X', '現貨延遲'), ('XAU=X', '現貨延遲'),
                      ('GC=F', '期貨延遲(非現貨)')):
        try:
            hh = yf.download(sym, period='1d', interval='1m', progress=False, auto_adjust=False)
            if hasattr(hh.columns, 'levels'):
                hh.columns = hh.columns.get_level_values(0)
            if not len(hh):
                continue
            px = float(hh['Close'].iloc[-1])
            if not 1500 < px < 6000:
                continue
            ts = hh.index[-1].tz_convert(HKT) if hh.index[-1].tzinfo else \
                hh.index[-1].tz_localize('UTC').tz_convert(HKT)
            out['quote'] = {'px': round(px, 1), 'kind': kind,
                            'asof': ts.strftime('%m-%d %H:%M HKT')}
            break
        except Exception as e:
            log.append(f'gold quote {sym} fail: {e}')
    log.append(f"gold quote: {out.get('quote')}")
    return out


for key, fn, src in (('hsi', hsi_levels, 'HKEX 即月期貨 HSIc1(15分鐘延遲)'),
                     ('mgc', gold_levels, 'Yahoo GC=F')):
    try:
        v = fn()
        v['source'] = v.pop('src', src) + v.pop('agg', '')
        result[key] = v
        log.append(f'{key}: OK {v["dates"]}')
    except Exception as e:
        result[key] = {'error': str(e)[:300]}
        log.append(f'{key}: FAIL {e}')

result['log'] = log
import os
os.makedirs(OUT, exist_ok=True)
with open(f'{OUT}/levels.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
print('\n'.join(log))
