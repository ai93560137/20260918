"""日經 VI 第六輪：investing.com 搜尋+歷史 API、stooq 快試。"""
import json
import os

import requests

OUT = 'tradingview/data_external/nkvi_probe'
os.makedirs(OUT, exist_ok=True)
log = []
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
     'Accept': 'application/json, text/plain, */*', 'domain-id': 'www'}
# 1) investing.com 搜 id
try:
    r = requests.get('https://api.investing.com/api/search/v2/search?q=nikkei%20volatility',
                     headers=H, timeout=30)
    log.append(f"inv search: {r.status_code}, {len(r.content)}b")
    with open(f'{OUT}/inv_search.json', 'w') as f:
        f.write(r.text[:8000])
    hits = []
    if r.status_code == 200:
        js = r.json()
        for q in js.get('quotes', [])[:8]:
            hits.append((q.get('id'), q.get('description'), q.get('symbol')))
        log.append(f"inv hits: {hits}")
    # 2) 用第一個命中的 id 拉歷史
    if hits:
        pid = hits[0][0]
        u = (f'https://api.investing.com/api/financialdata/historical/{pid}'
             f'?start-date=2001-01-01&end-date=2026-09-23&time-frame=Daily&add-missing-rows=false')
        r2 = requests.get(u, headers=H, timeout=60)
        log.append(f"inv hist id={pid}: {r2.status_code}, {len(r2.content)}b")
        if r2.status_code == 200:
            js2 = r2.json()
            rows = js2.get('data', [])
            log.append(f"inv rows: {len(rows)}, sample: {rows[:1]}")
            with open(f'{OUT}/inv_hist.json', 'w') as f:
                json.dump(rows[:20], f)
            if len(rows) > 500:
                import pandas as pd
                d = pd.DataFrame(rows)
                with open(f'{OUT}/inv_cols.txt', 'w') as f:
                    f.write(','.join(map(str, d.columns)))
                # 常見欄位 rowDate/last_close
                datec = 'rowDate' if 'rowDate' in d.columns else d.columns[0]
                closec = next((c for c in ['last_close', 'last_closeRaw', 'close'] if c in d.columns), None)
                if closec:
                    out = d[[datec, closec]].copy()
                    out.columns = ['Date', 'Close']
                    out['Close'] = pd.to_numeric(out['Close'].astype(str).str.replace(',', ''), errors='coerce')
                    out = out.dropna().iloc[::-1]
                    out.to_csv('tradingview/data_external/jniv_daily.csv', index=False)
                    log.append(f"SAVED jniv_daily.csv: {len(out)} rows")
except Exception as e:
    log.append(f"investing ERR: {e!r}")
# 3) stooq 快試
for s in ['jniv', '^jniv', 'nkvi.jp', 'jniv.jp']:
    try:
        r = requests.get(f'https://stooq.com/q/d/l/?s={s}&i=d', headers=H, timeout=20)
        ok = r.status_code == 200 and len(r.content) > 2000 and b'Date' in r.content[:100]
        log.append(f"stooq {s}: {r.status_code}, {len(r.content)}b, csv={ok}")
        if ok and not os.path.exists('tradingview/data_external/jniv_daily.csv'):
            with open('tradingview/data_external/jniv_stooq.csv', 'wb') as f:
                f.write(r.content)
            log.append(f"SAVED jniv_stooq.csv from {s}")
    except Exception as e:
        log.append(f"stooq {s} ERR: {e!r}")
with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
