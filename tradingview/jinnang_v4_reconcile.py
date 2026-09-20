#!/usr/bin/env python3
"""錦囊 v4 — Python 基準產生器 ＋ TradingView 成交明細對數工具。

用法
  1) 產生（並凍結）Python 基準：
        python3 jinnang_v4_reconcile.py --freeze
     → 寫出 jinnang_v4_python_baseline.csv 與 .json（預登記用，之後不再重算）

  2) 跟 TradingView 匯出的成交明細對數：
        python3 jinnang_v4_reconcile.py --tv <TradingView匯出.csv>

對數只證明「兩個實作量到同一件事」，**不證明規則有效**。
README §21 就是把這兩件事搞混才栽的。
"""
import argparse, hashlib, json, math, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bazhentu_sim as bz

PRESET       = bz.PRESETS['M15']
HOLD_BARS    = 10
LONG_ONLY    = True
VOL_FLOOR    = 0.10          # ATR(14) ÷ 價格 %
SPREAD_USD   = 0.40          # 來回，每盎司
USD_HKD      = 7.8
OZ           = 1.0
BASE_CSV     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jinnang_v4_python_baseline.csv")
BASE_JSON    = BASE_CSV.replace(".csv", ".json")


def load_m15(path):
    df = pd.read_csv(path)
    tc = [c for c in df.columns if 'time' in c.lower() or 'date' in c.lower()][0]
    df[tc] = pd.to_datetime(df[tc], errors='coerce', utc=True).dt.tz_localize(None)
    df = df.dropna(subset=[tc]).set_index(tc).sort_index()
    ren = {c: k.capitalize() for c in df.columns for k in ('open', 'high', 'low', 'close')
           if c.lower().startswith(k)}
    return df.rename(columns=ren)[['Open', 'High', 'Low', 'Close']].astype(float)


def trades(df, long_only=LONG_ONLY, vol_floor=VOL_FLOOR):
    """錦囊 v4：突破確認根收盤進場，抱 HOLD_BARS 根，無價格停損。"""
    s = bz.states(df, PRESET)
    atr, C = s.atr.values, df.Close.values
    hi, lo, st = s.hi.values, s.lo.values, s.st.values
    atrpct = np.where(C > 0, atr / C * 100, np.nan)
    n = len(df)
    boxTop = boxBot = np.nan
    live, lastR, run_, pdir, pc = False, -1, 0, 0, 0
    out = []
    for i in range(1, n):
        run_ = run_ + 1 if st[i] == 0 else 0
        if st[i] == 0 and run_ >= PRESET['rangeMinBars']:
            boxTop, boxBot, live, lastR = hi[i - 1], lo[i - 1], True, i
        elif live and i - lastR > PRESET['boxMaxAge']:
            live = False
        if not live or np.isnan(atr[i]):
            pdir = pc = 0
            continue
        raw = 1 if C[i] > boxTop + PRESET['bufATR'] * atr[i] else \
              (-1 if C[i] < boxBot - PRESET['bufATR'] * atr[i] else 0)
        if raw != 0 and raw == pdir:
            pc += 1
        elif raw != 0:
            pdir, pc = raw, 1
        else:
            pdir = pc = 0
        if pdir != 0 and pc == PRESET['confirmBars']:
            skip_dir = long_only and pdir < 0
            skip_vol = vol_floor > 0 and (np.isnan(atrpct[i]) or atrpct[i] < vol_floor)
            if not (skip_dir or skip_vol):
                j = min(i + HOLD_BARS, n - 1)
                out.append(dict(
                    entry_time=df.index[i], exit_time=df.index[j],
                    dir="多" if pdir > 0 else "空",
                    px_in=round(C[i], 2), px_out=round(C[j], 2),
                    atr_pct=round(float(atrpct[i]), 4),
                    bars=j - i,
                    gross_usd=round((C[j] - C[i]) * pdir * OZ, 4),
                    net_hkd=round(((C[j] - C[i]) * pdir * OZ - SPREAD_USD * OZ) * USD_HKD, 2),
                ))
                # ⚠️ 只有【真的進場】才消耗掉區間。Pine 的 `boxLive := false` 在
                #    `if takeUp and strategy.position_size == 0` 區塊【裡面】，
                #    被方向或波動門檻擋掉時區間仍然活著，之後可以再觸發一次。
                #    2026-09-20 對數時發現：原本無條件消耗，導致少做 29% 的交易。
                live = False
            # pendDir / pendCnt 不重置 —— Pine 讓它自然遞增，
            # 所以價格要先跌回門檻之下、再突破一次，才會再出訊號。
    return pd.DataFrame(out)


def summarise(tr, years):
    net = tr.net_hkd
    n = len(net)
    t = net.mean() / (net.std(ddof=1) / math.sqrt(n)) if n > 1 else float('nan')
    wins, losses = net[net > 0], net[net <= 0]
    eq = net.cumsum()
    dd = float((eq - eq.cummax()).min())
    sv = np.sort(net.values)[::-1]
    k = int(n * 0.05)
    return {
        "trades": int(n),
        "per_year": round(n / years, 1),
        "win_rate_pct": round(float((net > 0).mean() * 100), 2),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if len(losses) else None,
        "total_hkd": round(float(net.sum()), 2),
        "mean_hkd": round(float(net.mean()), 2),
        "t_stat": round(float(t), 3),
        "annual_pct": round(float(net.sum() / 20000 / years * 100), 3),
        "max_dd_hkd": round(dd, 2),
        "max_dd_pct": round(dd / 20000 * 100, 2),
        "best_hkd": round(float(net.max()), 2),
        "worst_hkd": round(float(net.min()), 2),
        "ex_top5pct_hkd": round(float(sv[k:].sum()), 2),
    }


def freeze(m15_path):
    df = load_m15(m15_path)
    years = (df.index[-1] - df.index[0]).days / 365.25
    tr = trades(df)
    tr.to_csv(BASE_CSV, index=False)
    meta = {
        "produced_from": os.path.basename(m15_path),
        "data_span": [str(df.index[0]), str(df.index[-1])],
        "bars": int(len(df)),
        "years": round(years, 3),
        "params": {"preset": "M15", "hold_bars": HOLD_BARS, "long_only": LONG_ONLY,
                   "vol_floor_atr_pct": VOL_FLOOR, "spread_usd_round_trip": SPREAD_USD,
                   "usd_hkd": USD_HKD, "oz": OZ,
                   "entry": "確認根收盤 (C[i])", "exit": "第 i+10 根收盤"},
        "summary": summarise(tr, years),
        "sha256": hashlib.sha256(open(BASE_CSV, 'rb').read()).hexdigest()[:16],
    }
    json.dump(meta, open(BASE_JSON, 'w'), ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"\n已凍結 → {BASE_CSV}\n         {BASE_JSON}")


def load_tv(path):
    d = pd.read_csv(path)
    d.columns = [c.strip('﻿') for c in d.columns]
    col_type = next(c for c in d.columns if '類型' in c or 'Type' in c)
    col_time = next(c for c in d.columns if '日期' in c or 'Date' in c)
    col_px = next(c for c in d.columns if '價格' in c or 'Price' in c)
    col_pnl = next((c for c in d.columns if '淨損益' in c or 'Net P&L' in c), None)
    ent = d[d[col_type].astype(str).str.contains('進場|Entry', regex=True)].copy()
    ext = d[d[col_type].astype(str).str.contains('出場|Exit', regex=True)].copy()
    for f in (ent, ext):
        f['t'] = pd.to_datetime(f[col_time])
        f['px'] = pd.to_numeric(f[col_px], errors='coerce')
    ent['dir'] = np.where(ent[col_type].astype(str).str.contains('多|Long'), '多', '空')
    ent['pnl'] = pd.to_numeric(ent[col_pnl], errors='coerce') if col_pnl else np.nan
    key = next((c for c in d.columns if '交易編號' in c or 'Trade #' in c), None)
    if key:
        ext = ext.set_index(key)['t']
        ent['exit_time'] = ent[key].map(ext)
    return ent[['t', 'dir', 'px', 'pnl'] + (['exit_time'] if key else [])] \
        .rename(columns={'t': 'entry_time', 'px': 'px_in'}).sort_values('entry_time').reset_index(drop=True)


def reconcile(tv_path):
    if not os.path.exists(BASE_CSV):
        sys.exit("先跑 --freeze 產生 Python 基準。")
    py = pd.read_csv(BASE_CSV, parse_dates=['entry_time', 'exit_time'])
    meta = json.load(open(BASE_JSON))
    tv = load_tv(tv_path)

    lo, hi = py.entry_time.min(), py.entry_time.max()
    tv_all = len(tv)
    tv = tv[(tv.entry_time >= lo) & (tv.entry_time <= hi)].reset_index(drop=True)
    print("=" * 66)
    print(f"Python 基準  {len(py):>5} 筆   {lo} → {hi}   sha {meta['sha256']}")
    print(f"TradingView  {tv_all:>5} 筆（全期）→ 可比區間內 {len(tv)} 筆")
    print("=" * 66)
    if tv_all > len(tv):
        print(f"⚠️ TradingView 多出 {tv_all - len(tv)} 筆落在 Python 的 M15 資料範圍之外，"
              f"不參與對數。")

    a = py.set_index('entry_time')
    b = tv.set_index('entry_time')
    both = a.index.intersection(b.index)
    only_py, only_tv = a.index.difference(b.index), b.index.difference(a.index)
    print(f"\n進場時間對得上：{len(both)} 筆"
          f"　只有 Python 有：{len(only_py)}　只有 TV 有：{len(only_tv)}")
    if len(both):
        m = a.loc[both].join(b.loc[both], rsuffix='_tv')
        dpx = (m.px_in - m.px_in_tv).abs()
        ddir = (m['dir'] != m.dir_tv).sum()
        print(f"  進場價最大差異 {dpx.max():.4f}（中位 {dpx.median():.4f}）")
        print(f"  方向不一致 {ddir} 筆")
        if m.pnl.notna().any():
            dp = (m.net_hkd - m.pnl)
            print(f"  每筆損益差 中位 {dp.median():+.2f}　平均 {dp.mean():+.2f}　"
                  f"最大絕對 {dp.abs().max():.2f} HK$")
            print(f"  總損益  Python {m.net_hkd.sum():+,.0f} vs TV {m.pnl.sum():+,.0f}"
                  f"  差 {m.net_hkd.sum() - m.pnl.sum():+,.0f} HK$"
                  f"（{abs(m.net_hkd.sum() - m.pnl.sum()) / max(1, abs(m.pnl.sum())) * 100:.2f}%）")
    for name, idx, src in (("只有 Python 有", only_py, a), ("只有 TV 有", only_tv, b)):
        if len(idx):
            print(f"\n{name}（最多列 10 筆）:")
            print(src.loc[idx].head(10).to_string())
    print("\n" + "-" * 66)
    print("⚠️ 對得上只證明兩個實作量到同一件事，**不證明規則有效**。")
    print("   README §21 就是把這兩件事搞混才栽的。")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--freeze', metavar='M15_CSV', nargs='?', const='AUTO')
    ap.add_argument('--tv', metavar='TV_EXPORT_CSV')
    args = ap.parse_args()
    if args.freeze:
        path = args.freeze
        if path == 'AUTO':
            path = os.environ.get('XAU_M15_CSV', '')
            if not path or not os.path.exists(path):
                sys.exit("請給 M15 CSV 路徑：--freeze <檔案> 或設環境變數 XAU_M15_CSV")
        freeze(path)
    elif args.tv:
        reconcile(args.tv)
    else:
        ap.print_help()
