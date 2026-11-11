"""[11-11] 對拍：真倉 xau/trend_d1rules.py 嘅 td（#1268，每日只用最近 420 日由頭計狀態機）對研究版（全歷史狀態機）。
數據：stooq 日線黃金 1995–2026。用法：python3 research/strategy_search/parity_td.py → research/strategy_search/PARITY_TD.md"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import trend_d1rules as D1R  # noqa: E402

WIN = 420


def main():
    days = []
    with open(os.path.join(HERE, "..", "macro_data", "stooq_xauusd_d.csv")) as fh:
        r = csv.reader(fh); next(r)
        for k, row in enumerate(r):
            if row[0] >= "1995-01-01":
                days.append((k, {"o": float(row[1]), "h": float(row[2]), "l": float(row[3]), "c": float(row[4])}))
    full = D1R.td_state(days)
    n_full = n_live = both = 0; exit_diff = 0; n_chk = 0
    for i in range(WIN + 250, len(days)):
        w = days[i - WIN + 1:i + 1]
        f = full[i] if (full[i] != 0 and full[i] != full[i - 1]) else 0
        sig = D1R.signal("td", w); lv = sig["side"] if sig else 0
        n_full += f != 0; n_live += lv != 0; both += (f != 0 and f == lv)
        if full[i - 1] != 0:                                   # 研究版持倉中：出場判斷一唔一致
            n_chk += 1
            ex_full = full[i] != full[i - 1]
            ex_live = D1R.exit_hit("td", full[i - 1], w) is not None
            exit_diff += ex_full != ex_live
    L = ["# 對拍：#1268 真倉規則（420 日窗）對研究版（全歷史）", "",
         f"- stooq 日線黃金 1995–2026，檢查 {len(days) - WIN - 250} 個交易日",
         f"- 入場訊號：研究版 {n_full} 個、真倉版 {n_live} 個、兩邊同一日同方向 {both} 個",
         f"- 出場判斷（研究版持倉嘅 {n_chk} 日）：唔一致 {exit_diff} 日", ""]
    open(os.path.join(HERE, "PARITY_TD.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
