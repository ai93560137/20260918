#!/usr/bin/env python3
"""
批次校準 — 一次把多個 M1/日線檔案丟進八陣圖，跑同一條規則，並排比較。

這支的存在理由：單一檔案的漂亮結果沒有意義。第十六節的 M15 規則
（t=+2.23）是在 2026 年黃金年化波動 30.4% 的異常期測出來的。
要知道它是「規則的函數」還是「波動的函數」，就得在多個標的、多個
時期上跑同一條規則，看它在哪些條件下活著、哪些條件下死掉。

規則（README 十六.5，不可在此調整 —— 調了就不是同一條規則）：
    八陣圖原廠 M15 門檻 / 高週期過濾關閉 / 突破確認進場 /
    10 根後無條件出場 / 不設價格停損

用法：
    python3 batch_calib.py data/*.csv
    python3 batch_calib.py data/*.csv --tf M15 --hold 10 --spread 0.35
    python3 batch_calib.py data/*.csv --split          # 每個檔再切前後半
"""
import argparse, glob, os, sys
import numpy as np
import pandas as pd

from bazhentu_sim import PRESETS, RESAMPLE, states, trades, atr, resample


def load_any(path):
    raw = pd.read_csv(path)
    tcol = next((c for c in ('Time', 'Date', 'Datetime', 'timestamp') if c in raw.columns), None)
    if tcol is None:
        raise ValueError(f"{path}: 找不到時間欄（Time / Date / Datetime）")
    raw[tcol] = pd.to_datetime(raw[tcol], format='mixed')
    df = raw.set_index(tcol).sort_index()
    df.index.name = 'Date'
    keep = [c for c in ('Open', 'High', 'Low', 'Close', 'Volume') if c in df.columns]
    miss = {'Open', 'High', 'Low', 'Close'} - set(keep)
    if miss:
        raise ValueError(f"{path}: 缺欄位 {miss}")
    return df[keep].dropna(subset=['Close']).astype(float)


def one(path, tf, hold, spread, verbose=True):
    df = resample(load_any(path), tf)
    p = PRESETS[tf]
    if len(df) < p['lenTrend'] * 5:
        return dict(file=os.path.basename(path), tf=tf, bars=len(df), note="根數不足")
    s = states(df, p)
    tr = trades(df, s, p, None, None, hold)
    px = df.Close.mean()
    cost = spread / px * 100 if spread else 0.0
    row = dict(file=os.path.basename(path), tf=tf, bars=len(df),
               start=str(df.index[0].date()), end=str(df.index[-1].date()))
    # 這份資料是什麼樣的市場 —— 沒有這幾欄就無法解釋結果
    r = np.log(df.Close / df.Close.shift(1)).dropna()
    bars_per_year = {'M5': 252*288, 'M15': 252*96, 'H1': 252*24, 'H4': 252*6, 'D': 252}[tf]
    row['年化波動%'] = r.std() * np.sqrt(bars_per_year) * 100
    row['ATR/價格%'] = atr(df, 14).median() / px * 100
    row['成本/ATR%'] = (spread / atr(df, 14).median() * 100) if spread else 0.0
    if len(tr) < 20:
        row['note'] = f"交易數 {len(tr)}，不足"
        return row
    net = tr.ret - cost
    row.update({
        '交易數': len(tr),
        '毛利%': tr.ret.mean(),
        '淨利%': net.mean(),
        '勝率%': (tr.ret > 0).mean() * 100,
        't': net.mean() / (net.std() / np.sqrt(len(net))),
        '單筆最壞%': tr.ret.min(),
    })
    eq = (1 + net / 100).cumprod()
    row['序列回撤%'] = (eq / eq.cummax() - 1).min() * 100
    mo = tr.assign(m=pd.to_datetime(tr.t).dt.to_period('M')).groupby('m').ret.sum() - \
         tr.assign(m=pd.to_datetime(tr.t).dt.to_period('M')).groupby('m').size() * cost
    row['月數'] = len(mo)
    row['正月%'] = (mo > 0).mean() * 100
    row['月均%'] = mo.mean()
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs='+')
    ap.add_argument("--tf", default="M15", choices=list(RESAMPLE))
    ap.add_argument("--hold", type=int, default=10)
    ap.add_argument("--spread", type=float, default=0.35,
                    help="來回點差，以報價單位計（黃金 $0.35；指數期貨填 1 tick）")
    ap.add_argument("--split", action="store_true", help="每個檔再切前後半各跑一次")
    a = ap.parse_args()

    paths = [p for pat in a.files for p in sorted(glob.glob(pat))]
    if not paths:
        sys.exit("找不到檔案。")

    rows = []
    for p in paths:
        try:
            rows.append(one(p, a.tf, a.hold, a.spread))
        except Exception as e:
            rows.append(dict(file=os.path.basename(p), note=f"讀取失敗: {e}"))
        print(f"  跑完 {os.path.basename(p)}", file=sys.stderr)

    out = pd.DataFrame(rows)
    cols = ['file', 'start', 'end', 'bars', '年化波動%', 'ATR/價格%', '成本/ATR%',
            '交易數', '毛利%', '淨利%', '勝率%', 't', '單筆最壞%', '序列回撤%',
            '月數', '正月%', '月均%']
    cols = [c for c in cols if c in out.columns]
    print(f"\n{'='*120}")
    print(f"批次校準  週期={a.tf}  持有={a.hold} 根  點差={a.spread}  "
          f"規則=八陣圖原廠門檻/高週期關閉/時間出場/無價格停損")
    print('='*120)
    with pd.option_context('display.width', 200, 'display.max_columns', 30,
                           'display.float_format', lambda v: f"{v:,.3f}"):
        print(out[cols].to_string(index=False))
    if 'note' in out.columns and out.note.notna().any():
        print("\n備註：")
        for _, r in out[out.note.notna()].iterrows():
            print(f"  {r['file']}: {r['note']}")

    ok = out[out.get('t', pd.Series(dtype=float)).notna()] if 't' in out.columns else out.iloc[0:0]
    if len(ok) >= 2:
        print(f"\n{'='*120}")
        print("關鍵問題：優勢是規則的函數，還是波動的函數？")
        print('='*120)
        c = ok[['年化波動%', '淨利%']].corr().iloc[0, 1]
        print(f"  年化波動 vs 每筆淨利 的相關係數 = {c:+.3f}   （n={len(ok)} 個檔案）")
        print(f"  {len(ok[ok.t > 2])} 個檔案 t>2、{len(ok[ok.t.between(0,2)])} 個 0<t<2、"
              f"{len(ok[ok.t < 0])} 個 t<0")
        if c > 0.5:
            print("  → 高度正相關：這條規則吃的是波動，不是結構。平靜期不要用。")
        elif c < -0.5:
            print("  → 負相關：低波動期反而較好，與第十六節的假設相反，要重新解釋。")
        else:
            print("  → 相關不明顯：優勢可能真的來自結構。但 n 太小時這句話不算數。")


if __name__ == "__main__":
    main()
