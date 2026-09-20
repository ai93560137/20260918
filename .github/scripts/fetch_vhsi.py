"""抓 VHSI（恒指波指）與 ^HSI（恒指現貨）日線 + 探測 HKEX 期權日報路徑。
只用 PyPI 主流套件（yfinance / pandas / requests），不安裝任何第三方 Git 程式碼。
輸出到 tradingview/data_external/，由 workflow commit 回分支。"""
import os
import re
import pandas as pd
import requests

OUT = 'tradingview/data_external'
os.makedirs(OUT, exist_ok=True)
log = []


def save(df, fname, src):
    df = df.reset_index()
    df.columns = [str(c).strip().title() for c in df.columns]
    if 'Datetime' in df.columns:
        df = df.rename(columns={'Datetime': 'Date'})
    keep = [c for c in ['Date', 'Open', 'High', 'Low', 'Close'] if c in df.columns]
    df = df[keep].dropna(subset=['Close'])
    df.to_csv(f'{OUT}/{fname}', index=False)
    log.append(f"SAVED {fname}: {len(df)} rows from {src}: {df.Date.min()} -> {df.Date.max()}")


import yfinance as yf
for sym, fname in [('^HSIL', 'vhsi_daily.csv'), ('^HSI', 'hsi_daily.csv')]:
    try:
        d = yf.download(sym, period='max', interval='1d', progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        log.append(f"yfinance {sym}: {len(d)} rows")
        if len(d) > 500:
            save(d, fname, f'yfinance {sym}')
    except Exception as e:
        log.append(f"yfinance {sym} ERR: {e!r}")

# HKEX 期權日報：舊路徑 404，掃可能的新舊格式；並抓報表索引頁找真實連結
H = {'User-Agent': 'Mozilla/5.0'}
try:
    idx = requests.get('https://www.hkex.com.hk/Market-Data/Statistics/'
                       'Consolidated-Reports/Derivatives-Daily-Market-Report?sc_lang=en',
                       headers=H, timeout=30)
    links = re.findall(r'href="([^"]*(?:hsio|dqe|dayrpt|option)[^"]*)"', idx.text, re.I)
    log.append(f"HKEX index page: HTTP {idx.status_code}, matched links: {links[:15]}")
except Exception as e:
    log.append(f"HKEX index ERR: {e!r}")
for pat in ['https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/hsio{d}.htm',
            'https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/hsio{d}.zip',
            'https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/dqe{d}.htm',
            'https://www.hkex.com.hk/chi/stat/dmstat/dayrpt/hsio{d}c.htm']:
    try:
        u = pat.format(d='250917')
        r = requests.get(u, timeout=20, headers=H)
        log.append(f"{u} -> HTTP {r.status_code}, {len(r.content)} bytes")
        if r.status_code == 200 and len(r.content) > 20000:
            with open(f'{OUT}/hkex_sample' + os.path.splitext(u)[1], 'wb') as f:
                f.write(r.content[:50000])
    except Exception as e:
        log.append(f"{pat} ERR: {e!r}")

with open(f'{OUT}/fetch_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
