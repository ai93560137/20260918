"""[R364] 核對 xau/combo_live.py（純 Python，真倉用）同 research numpy 版（d1_indicators／h4_indicators／robust2）訊號一致：
用 Dukascopy H1 2015→2026，逐根 D1／H4 比較六個成份嘅訊號方向同止蝕距離。用法：python3 research/strategy_search/combo_live_parity.py"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
os.environ.setdefault("XAU_BOOK", "signal")
import combo_live as CL  # noqa: E402
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import robust_long as R  # noqa: E402

t, o, h, l, c = R.load_duka()
m = t >= 1420070400                      # 2015-01-01
t, o, h, l, c = t[m], o[m], h[m], l[m], c[m]
h1 = list(zip(t.tolist(), o.tolist(), h.tolist(), l.tolist(), c.tolist()))
res = {}
for tf, per, D in (("D1", 86400, Q.DI(t, o, h, l, c)), ("H4", 14400, H.H4I(t, o, h, l, c))):
    bars = CL.group(h1, per); ind = CL.indicators(bars)
    assert len(bars) == len(D.dc), (tf, len(bars), len(D.dc))
    atr_diff = np.nanmax(np.abs(np.array([np.nan if a is None else a for a in ind["atr"]]) - D.datr))
    for name, fam, ctf, *_ in CL.COMPONENTS:
        if ctf != tf or fam == "S2":
            continue
        p = {"J5": dict(ex=2), "J7": dict(filt=True, ex=2), "J8": dict(th=20, filt=True, ex=2), "J2": dict(filt=True, ex=1)}[fam]
        b, x = Q.signals(D, fam, p)
        ref = np.where(b, 1, np.where(x, -1, 0))
        live = np.array([CL.family_side(ind, fam, i) for i in range(len(bars))])
        k = np.arange(len(bars)) >= 210
        res[name] = (int((ref[k] != 0).sum()), int((live[k] != 0).sum()), int((ref[k] != live[k]).sum()), float(atr_diff))
for k, v in res.items():
    print(f"{k}：research 訊號 {v[0]}、live 訊號 {v[1]}、唔一致 {v[2]} 根、ATR 最大差 {v[3]:.6f}")
