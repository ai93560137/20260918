"""HSI vs ES 月度跨式淨收益相關性（同月災難疊加檢查）"""
import pandas as pd, numpy as np

D = '/home/user/20260918/tradingview/data_external'

def monthly_net(vol_csv, px_csv, vol_col, cost_pts):
    v = pd.read_csv(f'{D}/{vol_csv}', parse_dates=['Date']).set_index('Date')
    p = pd.read_csv(f'{D}/{px_csv}', parse_dates=['Date']).set_index('Date')
    iv = v['Close'].rename('iv')
    r = np.log(p['Close']).diff()
    rv = (r[::-1].rolling(21).std()[::-1]).shift(-1) * np.sqrt(252) * 100
    al = pd.concat([iv, rv.rename('rv')], axis=1).dropna()
    mo = al.groupby(al.index.to_period('M')).first()
    VEGA = 0.8 * np.sqrt(21/252)
    mo['net'] = (mo.iv - mo.rv - cost_pts) * VEGA
    return mo['net']

hsi = monthly_net('vhsi_daily.csv', 'hsi_daily.csv', 'Close', 0.12)
es  = monthly_net('vix_daily.csv',  'spx_daily.csv', 'Close', 0.12)

j = pd.concat([hsi.rename('hsi'), es.rename('es')], axis=1).dropna()
print(f'重疊月數: {len(j)}  ({j.index[0]} → {j.index[-1]})')
print(f'月度淨收益相關: {j.hsi.corr(j.es):+.2f}')

# 災難月定義：各自最差 10%
qh, qe = j.hsi.quantile(0.10), j.es.quantile(0.10)
bh, be = j.hsi < qh, j.es < qe
both = (bh & be).sum()
exp_indep = bh.mean() * be.mean() * len(j)
print(f'各自最差10%門檻: HSI {qh:+.2f}%  ES {qe:+.2f}%')
print(f'同月雙災難: {both} 個月（獨立假設下預期 {exp_indep:.1f}）→ 疊加倍數 {both/exp_indep:.1f}x')
print('雙災難月:', list(j[bh & be].index.astype(str)))

# 尾部條件：ES 災難月時 HSI 平均表現
print(f'ES 災難月時 HSI 平均: {j.hsi[be].mean():+.2f}%（全期均值 {j.hsi.mean():+.2f}%）')
print(f'HSI 災難月時 ES 平均: {j.es[bh].mean():+.2f}%（全期均值 {j.es.mean():+.2f}%）')

# 兩市場各半倉 vs 單市場滿倉：組合最差月
half = 0.5*j.hsi + 0.5*j.es
for name, s in [('HSI 滿倉', j.hsi), ('ES 滿倉', j.es), ('各半倉', half)]:
    print(f'{name}: 均 {s.mean():+.2f}%  最壞月 {s.min():+.2f}%  月標差 {s.std():.2f}  t {s.mean()/s.std()*np.sqrt(len(s)):+.1f}')
