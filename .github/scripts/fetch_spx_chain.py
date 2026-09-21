"""抓 SPX 期權鏈（Yahoo）做 MES 的第二報價源。
取 25–40 天窗口內最近到期（無則取 20 天以上最近的），ATM ±3% 檔位的
bid/ask/IV/OI，存 data_external/quotes_us/。SPX 指數期權 vs MES 期貨期權
有基差（股息/carry）與 15 分鐘延遲，ATM IV 對比容差建議 1.0 波動點。"""
import json
import os
from datetime import date, datetime, timezone

import yfinance as yf

OUT = 'tradingview/data_external/quotes_us'
os.makedirs(OUT, exist_ok=True)

t = yf.Ticker('^SPX')
spot = float(t.history(period='1d').Close.iloc[-1])
today = date.today()
exps = [(e, (date.fromisoformat(e) - today).days) for e in t.options]
window = [x for x in exps if 25 <= x[1] <= 40]
pick = min(window, key=lambda x: x[1]) if window else \
    min([x for x in exps if x[1] >= 20], key=lambda x: x[1])
exp, dte = pick

ch = t.option_chain(exp)
lo, hi = spot * 0.97, spot * 1.03
rows = {}
for side, df in [('c', ch.calls), ('p', ch.puts)]:
    for _, r in df.iterrows():
        k = float(r['strike'])
        if not lo <= k <= hi:
            continue
        rows.setdefault(k, {})[side] = {
            'bid': float(r.get('bid') or 0), 'ask': float(r.get('ask') or 0),
            'last': float(r.get('lastPrice') or 0),
            'iv': round(float(r.get('impliedVolatility') or 0) * 100, 2),
            'oi': int(r.get('openInterest') or 0)}

out = {'fetched_utc': datetime.now(timezone.utc).isoformat(timespec='minutes'),
       'spot': round(spot, 2), 'expiry': exp, 'dte': dte,
       'strikes': {str(k): v for k, v in sorted(rows.items())}}
stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
with open(f'{OUT}/spx_chain_{stamp}.json', 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
atm = min(rows, key=lambda k: abs(k - spot))
print(f"SPX {spot:.0f}  expiry {exp} ({dte}d)  strikes {len(rows)}  "
      f"ATM {atm:.0f} c_iv {rows[atm].get('c', {}).get('iv')} "
      f"p_iv {rows[atm].get('p', {}).get('iv')}")
