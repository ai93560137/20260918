"""Futu：把恒指窩輪、牛熊證（現時掛牌中的）的歷史日線拉下來，給 research/warrants_cbbc 回測用。

在裝有 Futu OpenD 的電腦上（PowerShell，在 repo 資料夾）：
  python futu\\warrant_hist_pull.py --list                 # 只列清單與額度，不拉 K 線
  python futu\\warrant_hist_pull.py --limit 300            # 拉 300 隻（按成交額排序優先），每次最多 400 根日線
  python futu\\warrant_hist_pull.py --limit 300 --types BULL,BEAR   # 只拉牛熊證
  python futu\\warrant_hist_pull.py --limit 300 --resume   # 跳過已拉過的代號，續拉

Futu 歷史 K 線額度：每 30 天可拉的「股票數」有上限（您目前剩 1000），同一代號 30 天內重拉不另計。
所以：先 --list 看總數，再分批拉，優先成交額高的；額度用完就等下個月。

輸出（tradingview/out/warrant_hist/，已 .gitignore）：
  universe.csv              掃到的全部恒指窩輪牛熊證：代號、名稱、類型、發行商、行使價、收回價、換股比率、到期日、成交額、街貨比、上市日
  kline_<code>.csv          每隻的日線（time_key, open, high, low, close, volume, turnover）
  pulled.txt                已拉過的代號（--resume 用）
拉完把 universe.csv 的行數、成功隻數、額度剩餘貼回來。只讀行情、不落單。
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tradingview" / "out" / "warrant_hist"
OPEND_HOST = os.environ.get("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("OPEND_PORT", "11111"))
FIELDS = ("stock", "name", "type", "issuer", "strike_price", "recovery_price", "conversion_ratio", "maturity_time", "list_time",
          "cur_price", "bid_price", "ask_price", "turnover", "volume", "street_rate", "implied_volatility", "delta", "premium", "lot_size")


def _warrant_request_cls(ft):
    cls = getattr(ft, "WarrantRequest", None) or getattr(ft, "WarrantDataFilter", None)
    if cls is None:
        from futu.quote.quote_get_warrant import Request as cls  # type: ignore
    return cls


def universe(ctx, ft, owner, types):
    rows = []
    for tname in types:
        wtype = getattr(ft.WrtType, tname)
        begin = 0
        while True:
            req = _warrant_request_cls(ft)()
            req.type_list = [wtype]
            req.begin, req.num = begin, 200
            req.sort_field = ft.SortField.TURNOVER
            req.ascend = False
            ret, data = ctx.get_warrant(owner, req)
            if ret != ft.RET_OK:
                raise RuntimeError(f"get_warrant 失敗：{data}")
            df, last_page, all_count = data
            for r in df.to_dict("records"):
                rows.append({k: r.get(k) for k in FIELDS})
            begin += len(df)
            if last_page or len(df) == 0 or begin >= all_count:
                break
            time.sleep(3.1)
        time.sleep(3.1)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="只列清單與額度")
    ap.add_argument("--limit", type=int, default=0, help="拉幾隻日線（按成交額排序）")
    ap.add_argument("--types", default="CALL,PUT,BULL,BEAR", help="CALL,PUT,BULL,BEAR 任選")
    ap.add_argument("--owner", default="HK.800000")
    ap.add_argument("--bars", type=int, default=400, help="每隻最多幾根日線（預設 400）")
    ap.add_argument("--resume", action="store_true", help="跳過 pulled.txt 裡已拉過的")
    a = ap.parse_args()
    try:
        import futu as ft  # type: ignore
        ft.OpenQuoteContext
    except (ImportError, AttributeError):
        sys.exit("需要 pip install futu-api；用完整路徑執行，不要在 repo 根目錄互動模式 import futu")
    OUT.mkdir(parents=True, exist_ok=True)
    types = [t.strip().upper() for t in a.types.split(",") if t.strip()]
    ctx = ft.OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        rows = universe(ctx, ft, a.owner, types)
        with open(OUT / "universe.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(FIELDS))
            w.writeheader()
            w.writerows(rows)
        by_type = {}
        for r in rows:
            by_type[str(r["type"])] = by_type.get(str(r["type"]), 0) + 1
        print(f"{a.owner} 窩輪牛熊證共 {len(rows)} 隻：{by_type}；已存 universe.csv")
        ret, q = ctx.get_history_kl_quota()
        if ret == ft.RET_OK:
            print(f"歷史 K 線額度：已用 {q[0]}、剩 {q[1]}")
        if a.list or a.limit <= 0:
            return
        pulled_f = OUT / "pulled.txt"
        pulled = set(pulled_f.read_text(encoding="utf-8").split()) if (a.resume and pulled_f.exists()) else set()
        rows.sort(key=lambda r: -(float(r.get("turnover") or 0)))
        todo = [r for r in rows if str(r["stock"]) not in pulled][: a.limit]
        ok = fail = 0
        for i, r in enumerate(todo, 1):
            code = str(r["stock"])
            ret, data = ctx.request_history_kline(code, ktype=ft.KLType.K_DAY, autype=ft.AuType.NONE, max_count=a.bars)
            if ret == ft.RET_OK:
                kl = data[0] if isinstance(data, tuple) else data
                if len(kl):
                    kl.to_csv(OUT / f"kline_{code.replace('.', '_')}.csv", index=False, encoding="utf-8")
                    ok += 1
                    with open(pulled_f, "a", encoding="utf-8") as f:
                        f.write(code + "\n")
                    if i % 20 == 0 or i == len(todo):
                        print(f"  {i}/{len(todo)} {code} {len(kl)} 根 {str(kl['time_key'].iloc[0])[:10]}→{str(kl['time_key'].iloc[-1])[:10]}")
                else:
                    fail += 1
            else:
                fail += 1
                msg = str(data)
                print(f"  {code}: 失敗 {msg[:120]}")
                if "quota" in msg.lower() or "額度" in msg or "配额" in msg:
                    print("額度用完，停止。")
                    break
            time.sleep(0.6)
        print(f"日線：成功 {ok}、失敗 {fail}")
        ret, q = ctx.get_history_kl_quota()
        if ret == ft.RET_OK:
            print(f"歷史 K 線額度：已用 {q[0]}、剩 {q[1]}")
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
