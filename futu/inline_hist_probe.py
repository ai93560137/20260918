"""Futu 探測：還有沒有界內證（含已退市）的基本資料與歷史日線？給 research/warrants_cbbc 的歷史驗證用。

在裝有 Futu OpenD 的電腦上執行（PowerShell，在 repo 資料夾）：
  python futu\\inline_hist_probe.py                 # 列全港窩輪基本資料，篩 stock_child_type=INLINE（含 delisting），試拉前 10 隻日線
  python futu\\inline_hist_probe.py --kline 50      # 試拉 50 隻（注意歷史 K 線額度：每 30 天有限制，先用小數目）
  python futu\\inline_hist_probe.py --kline 0       # 只列清單，不拉 K 線

輸出（tradingview/out/inline_scan/，已 .gitignore）：
  futu_warrant_basicinfo.csv   全港窩輪基本資料（code, name, stock_child_type, stock_owner, listing_date, delisting …）
  futu_inline_list.csv         其中界內證
  futu_inline_kline_<code>.csv 拉到的日線
把終端最後的統計貼回來即可。只讀行情、不落單。
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "out" / "inline_scan"
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kline", type=int, default=10, help="試拉幾隻界內證的日線（預設 10）")
    a = ap.parse_args()
    try:
        import futu as ft  # type: ignore
        ft.OpenQuoteContext
    except (ImportError, AttributeError):
        sys.exit("需要 pip install futu-api；用完整路徑執行，不要在 repo 根目錄互動模式 import futu")
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = ft.OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        ret, df = ctx.get_stock_basicinfo(ft.Market.HK, ft.SecurityType.WARRANT)
        if ret != ft.RET_OK:
            sys.exit(f"get_stock_basicinfo 失敗：{df}")
        df.to_csv(OUT / "futu_warrant_basicinfo.csv", index=False, encoding="utf-8")
        print(f"全港窩輪基本資料 {len(df)} 筆；欄位：{list(df.columns)}")
        if "stock_child_type" in df.columns:
            print("子類型分佈：", df["stock_child_type"].astype(str).value_counts().to_dict())
        if "delisting" in df.columns:
            print("已退市：", int(df["delisting"].astype(bool).sum()), "筆")
        inline = df[df.get("stock_child_type", "").astype(str).str.upper() == "INLINE"] if "stock_child_type" in df.columns else df.iloc[0:0]
        # 名稱裡的 @L 也算（保險）
        by_name = df[df["name"].astype(str).str.contains("@L", regex=False)] if "name" in df.columns else df.iloc[0:0]
        import pandas as pd
        inline = pd.concat([inline, by_name]).drop_duplicates(subset=["code"]) if len(by_name) else inline
        inline.to_csv(OUT / "futu_inline_list.csv", index=False, encoding="utf-8")
        print(f"界內證（含退市）{len(inline)} 筆")
        if len(inline):
            cols = [c for c in ("code", "name", "stock_owner", "listing_date", "delisting") if c in inline.columns]
            print(inline[cols].head(20).to_string())
            if "stock_owner" in inline.columns:
                print("相關資產分佈：", inline["stock_owner"].astype(str).value_counts().head(10).to_dict())
            if "listing_date" in inline.columns:
                ld = inline["listing_date"].astype(str)
                print("上市日範圍：", ld.min(), "→", ld.max())
        # 試拉日線
        ok = fail = 0
        for code in list(inline["code"].astype(str))[: max(0, a.kline)]:
            ret, data = ctx.request_history_kline(code, ktype=ft.KLType.K_DAY, max_count=1000)
            if ret == ft.RET_OK:
                kl = data[0] if isinstance(data, tuple) else data
                if len(kl):
                    kl.to_csv(OUT / f"futu_inline_kline_{code.replace('.', '_')}.csv", index=False, encoding="utf-8")
                    print(f"  {code}: 日線 {len(kl)} 根 {kl['time_key'].iloc[0][:10]} → {kl['time_key'].iloc[-1][:10]}")
                    ok += 1
                else:
                    print(f"  {code}: 日線 0 根")
                    fail += 1
            else:
                print(f"  {code}: 失敗 {data}")
                fail += 1
            time.sleep(0.6)
        print(f"日線：成功 {ok}、失敗 {fail}（額度：request_history_kline 每 30 天可拉的股票數有限，詳見 get_history_kl_quota）")
        ret, q = ctx.get_history_kl_quota()
        if ret == ft.RET_OK:
            print(f"歷史 K 線額度：已用 {q[0]}、剩 {q[1]}")
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
