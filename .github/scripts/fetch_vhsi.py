"""抓 VHSI（恒指波指）日線 + 探測 HKEX 期權日報可用性。
只用 PyPI 主流套件（yfinance / pandas / requests），不安裝任何第三方 Git 程式碼。
輸出到 tradingview/data_external/，由 workflow commit 回分支。"""
import os
import pandas as pd
import requests

OUT = 'tradingview/data_external'
os.makedirs(OUT, exist_ok=True)
log = []


def save(df, src):
    df = df.reset_index()
    df.columns = [str(c).strip().title() for c in df.columns]
    if 'Datetime' in df.columns:
        df = df.rename(columns={'Datetime': 'Date'})
    keep = [c for c in ['Date', 'Open', 'High', 'Low', 'Close'] if c in df.columns]
    df = df[keep].dropna(subset=['Close'])
    df.to_csv(f'{OUT}/vhsi_daily.csv', index=False)
    log.append(f"SAVED {len(df)} rows from {src}: {df.Date.min()} -> {df.Date.max()}")


got = False

# 1) Yahoo Finance 的候選代碼
try:
    import yfinance as yf
    for sym in ['^HSIL', '^VHSI.HK', 'VHSI.HK']:
        try:
            d = yf.download(sym, period='max', interval='1d', progress=False, auto_adjust=False)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            log.append(f"yfinance {sym}: {len(d)} rows")
            if len(d) > 500:
                save(d, f'yfinance {sym}')
                got = True
                break
        except Exception as e:
            log.append(f"yfinance {sym} ERR: {e!r}")
except Exception as e:
    log.append(f"yfinance import ERR: {e!r}")

# 2) investing.com 公開 API（純 requests，先搜 id 再拉歷史）
if not got:
    try:
        h = {'User-Agent': 'Mozilla/5.0', 'domain-id': 'www'}
        s = requests.get('https://api.investing.com/api/search/v2/search?q=VHSI',
                         headers=h, timeout=30).json()
        cands = [q for q in s.get('quotes', []) if 'VHSI' in str(q.get('symbol', '')).upper()]
        log.append(f"investing search: {[(q.get('id'), q.get('symbol'), q.get('description')) for q in cands][:5]}")
        if cands:
            iid = cands[0]['id']
            u = (f'https://api.investing.com/api/financialdata/historical/{iid}'
                 f'?start-date=2010-01-01&end-date=2026-09-20&time-frame=Daily&add-missing-rows=false')
            r = requests.get(u, headers=h, timeout=60).json()
            rows = r.get('data', [])
            log.append(f"investing historical: {len(rows)} rows")
            if len(rows) > 500:
                df = pd.DataFrame(rows)
                df = df.rename(columns={'rowDate': 'Date', 'last_open': 'Open', 'last_max': 'High',
                                        'last_min': 'Low', 'last_close': 'Close'})
                df['Date'] = pd.to_datetime(df['Date'])
                save(df.set_index('Date').sort_index(), 'investing.com')
                got = True
    except Exception as e:
        log.append(f"investing ERR: {e!r}")

# 3) 探測 HKEX 期權日報（第二階段的資料源；含 IV 欄位）
try:
    for d8 in ['250918', '250102', '240103', '220805']:
        u = f'https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/hsio{d8}.htm'
        r = requests.get(u, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        log.append(f"HKEX hsio{d8}: HTTP {r.status_code}, {len(r.content)} bytes")
        if r.status_code == 200 and d8 == '250918':
            with open(f'{OUT}/hkex_hsio_sample.txt', 'wb') as f:
                f.write(r.content[:30000])
except Exception as e:
    log.append(f"HKEX probe ERR: {e!r}")

with open(f'{OUT}/fetch_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
