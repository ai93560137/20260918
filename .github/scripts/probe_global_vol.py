"""全球波指金絲雀探測（2026-09-25）：Yahoo 上還有哪些國家的波指可養？
試 14 個候選代碼，凡拉到 >500 行日線即存 data_external/global_vol/<代碼>.csv。
只偵察數據管道，不下單。"""
import os

import pandas as pd
import yfinance as yf

OUT = 'tradingview/data_external/global_vol'
os.makedirs(OUT, exist_ok=True)
log = []
CANDS = [
    ('^VDAXI', 'germany_vdax'), ('^VDAX', 'germany_vdax2'),
    ('^V2TX', 'europe_vstoxx'), ('^VFTSE', 'uk_vftse'),
    ('^VCAC', 'france_vcac'), ('^VAEX', 'nl_vaex'), ('^VSMI', 'swiss_vsmi'),
    ('^INDIAVIX', 'india_vix'), ('^KSVKOSPI', 'korea_vkospi'),
    ('^VXJ', 'japan_vxj'), ('^AXVI', 'australia_axvi'),
    ('^VXFXI', 'china_vxfxi'), ('^VXEEM', 'em_vxeem'), ('^VXEWZ', 'brazil_vxewz'),
]
for sym, name in CANDS:
    try:
        d = yf.download(sym, period='max', interval='1d', progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d.reset_index()
        d.columns = [str(c).strip().title() for c in d.columns]
        d = d[[c for c in ['Date', 'Close'] if c in d.columns]].dropna()
        if len(d) > 500:
            d.to_csv(f'{OUT}/{name}.csv', index=False)
            log.append(f"HIT  {sym:<10} {name:<15} {len(d)} rows  "
                       f"{d.Date.iloc[0].date()} -> {d.Date.iloc[-1].date()}  last {d.Close.iloc[-1]:.1f}")
        else:
            log.append(f"miss {sym:<10} {len(d)} rows")
    except Exception as e:
        log.append(f"miss {sym:<10} ERR {str(e)[:60]}")
with open(f'{OUT}/probe_log.txt', 'w') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
