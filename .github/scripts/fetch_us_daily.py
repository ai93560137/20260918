"""每日刷新波指/現貨日線（HSI+US 兩市場掃描共用）+ ES/NQ 期貨最新報價。
只用 PyPI 主流套件（yfinance / pandas），輸出到 tradingview/data_external/。
恒指掃描的 HV20 與美股 VRP 檢查都依賴這裡的 CSV 保持最新。"""
import json
import os
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

OUT = 'tradingview/data_external'
os.makedirs(OUT, exist_ok=True)
log = []
KEEP_DAYS = 5          # 舊檔有、新抓冇嘅日子，喺最近 N 個曆日內就保留（Yahoo 暫缺，唔好刪）
# 亞洲市場收市時間（UTC，含 5 分鐘緩衝）：喺呢個時間之前抓到嘅「當日」一列係收市前嘅數，標 partial
ASIA_FINAL_UTC = {'vhsi_daily.csv': (8, 15), 'hsi_daily.csv': (8, 15), 'n225_daily.csv': (6, 15)}
asia_status = {}


def merge_keep(old_path, d, now_utc, fname, log):
    """新抓到嘅數據優先；舊檔有而新抓冇、且屬最近 KEEP_DAYS 個曆日內嘅日子 → 保留，並寫 log。
    傳回 (合併後 DataFrame, 保留嘅日期清單)。"""
    d = d.copy()
    d['Date'] = pd.to_datetime(d['Date']).dt.tz_localize(None).dt.normalize()
    if not os.path.exists(old_path):
        return d, []
    old = pd.read_csv(old_path)
    old['Date'] = pd.to_datetime(old['Date']).dt.tz_localize(None).dt.normalize()
    cutoff = pd.Timestamp(now_utc.date()) - pd.Timedelta(days=KEEP_DAYS)
    missing = old[(~old['Date'].isin(d['Date'])) & (old['Date'] >= cutoff)]
    kept = [x.strftime('%Y-%m-%d') for x in missing['Date']]
    if len(missing):
        d = pd.concat([d, missing[[c for c in d.columns if c in missing.columns]]], ignore_index=True)
        d = d.sort_values('Date').reset_index(drop=True)
        for k in kept:
            log.append(f"KEEP {fname} {k}（Yahoo 暫缺，保留舊檔嗰一列）")
    return d, kept

for sym, fname in [('^HSIL', 'vhsi_daily.csv'), ('^HSI', 'hsi_daily.csv'),
                   ('^VIX', 'vix_daily.csv'), ('^GSPC', 'spx_daily.csv'),
                   ('^VXN', 'vxn_daily.csv'), ('^NDX', 'ndx_daily.csv'),
                   ('^N225', 'n225_daily.csv'), ('^VIX9D', 'vix9d_daily.csv'),
                   ('^VIX3M', 'vix3m_daily.csv'), ('^VVIX', 'vvix_daily.csv'),
                   ('^MOVE', 'move_daily.csv'), ('^SKEW', 'skew_daily.csv'),
                   ('^AXVI', 'axvi_daily.csv')]:
    try:
        d = yf.download(sym, period='max', interval='1d', progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d.reset_index()
        d.columns = [str(c).strip().title() for c in d.columns]
        keep = [c for c in ['Date', 'Open', 'High', 'Low', 'Close'] if c in d.columns]
        d = d[keep].dropna(subset=['Close'])
        # 少於既有檔案九成的行數視為壞抓取，不覆蓋
        old = f'{OUT}/{fname}'
        if os.path.exists(old):
            n_old = sum(1 for _ in open(old)) - 1
            if len(d) < n_old * 0.9:
                log.append(f"SKIP {fname}: fetched {len(d)} < 90% of existing {n_old}")
                continue
        now_utc = datetime.now(timezone.utc)
        d, kept = merge_keep(old, d, now_utc, fname, log)
        d.to_csv(old, index=False)
        log.append(f"SAVED {fname}: {len(d)} rows -> {d.Date.max()}")
        if fname in ASIA_FINAL_UTC:
            hh, mm = ASIA_FINAL_UTC[fname]
            last = pd.Timestamp(d.Date.max()).strftime('%Y-%m-%d')
            # 最後一列屬今日而且抓取時間未到收市＋緩衝 → partial；屬舊日或已過收市時間 → 視為 final（保留舊列時沿用舊標記）
            fin = not (last == now_utc.strftime('%Y-%m-%d') and (now_utc.hour, now_utc.minute) < (hh, mm))
            asia_status[fname] = {'last_date': last, 'last_row': 'final' if fin else 'partial',
                                  'fetched_utc': now_utc.strftime('%Y-%m-%d %H:%M'), 'kept_dates': kept}
    except Exception as e:
        log.append(f"{sym} ERR: {e!r}")

# 日經波指（Nikkei 225 VI）：Yahoo 不載，改抓日經指數公司官方 CSV
import io
import requests
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
     'Referer': 'https://indexes.nikkei.co.jp/en/nkave/archives/download',
     'Accept': 'text/csv,text/html,application/json,*/*'}
# 先爬下載頁找真實 CSV 連結
try:
    import re as _re
    pg = requests.get('https://indexes.nikkei.co.jp/en/nkave/archives/download', headers=H, timeout=30)
    links = _re.findall(r'href="([^"]*(?:vi|volatility)[^"]*\.csv[^"]*)"', pg.text, _re.I)
    log.append(f"NKVI download page: HTTP {pg.status_code}, vi-csv links: {links[:5]}")
except Exception as e:
    links = []
    log.append(f"NKVI page ERR: {e!r}")
cands = [l if l.startswith('http') else 'https://indexes.nikkei.co.jp' + l for l in links]
cands += ['https://indexes.nikkei.co.jp/en/nkave/archives/file/nikkei_stock_average_vi_daily_en.csv',
          'https://indexes.nikkei.co.jp/nkave/archives/file/nikkei_stock_average_vi_daily_jp.csv',
          'https://indexes.nikkei.co.jp/en/nkave/statistics/dataload?list=vi&csv=1']
for url in cands:
    try:
        r = requests.get(url, headers=H, timeout=30)
        log.append(f"NKVI url {url.split('/')[-1][:60]}: HTTP {r.status_code}, {len(r.content)} bytes")
        if r.status_code == 200 and len(r.content) < 5000:
            with open(f'{OUT}/nkvi_probe_body.txt', 'w') as pf:
                pf.write(r.text[:3000])
        if r.status_code == 200 and len(r.content) > 5000:
            raw = r.content.decode('utf-8-sig', errors='replace')
            d = pd.read_csv(io.StringIO(raw))
            log.append(f"NKVI columns: {list(d.columns)[:6]}, rows {len(d)}")
            # 第一欄日期、找收盤欄（close/終値/VI）
            d.columns = [str(c).strip() for c in d.columns]
            datec = d.columns[0]
            closec = next((c for c in d.columns if 'close' in c.lower() or '終値' in c or c == 'VI'),
                          d.columns[-1])
            out = d[[datec, closec]].dropna()
            out.columns = ['Date', 'Close']
            out['Close'] = pd.to_numeric(out['Close'], errors='coerce')
            out = out.dropna()
            if len(out) > 500:
                out.to_csv(f'{OUT}/jniv_daily.csv', index=False)
                log.append(f"SAVED jniv_daily.csv: {len(out)} rows {out.Date.iloc[0]} -> {out.Date.iloc[-1]}")
                break
    except Exception as e:
        log.append(f"NKVI url ERR: {e!r}")

# 期貨最新價（延遲報價即可，供 delta 對沖指令與監測用）
fut = {}
for sym in ['ES=F', 'NQ=F']:
    try:
        h = yf.download(sym, period='5d', interval='1h', progress=False, auto_adjust=False)
        if isinstance(h.columns, pd.MultiIndex):
            h.columns = h.columns.get_level_values(0)
        h = h.dropna(subset=['Close'])
        fut[sym] = {'price': round(float(h.Close.iloc[-1]), 2),
                    'asof': str(h.index[-1])}
        log.append(f"{sym}: {fut[sym]['price']} @ {fut[sym]['asof']}")
    except Exception as e:
        log.append(f"{sym} ERR: {e!r}")
if fut:
    fut['fetched_utc'] = datetime.now(timezone.utc).isoformat(timespec='minutes')
    with open(f'{OUT}/us_futures_quote.json', 'w') as f:
        json.dump(fut, f, ensure_ascii=False, indent=1)

if asia_status:
    with open(f'{OUT}/asia_daily_status.json', 'w', encoding='utf-8') as f:
        json.dump(asia_status, f, ensure_ascii=False, indent=1)

with open(f'{OUT}/fetch_us_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
