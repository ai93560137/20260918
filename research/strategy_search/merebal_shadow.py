"""[IDEAS #1481／#1466／#1469] 月尾股債再平衡影子前向（紙上，唔落單）：亞洲（日經、ASX200）係影子；美國、歐洲同真倉 945／946 並列對照。
每個月完結後入賬一行（訊號日＝該月倒數第 6 個交易日，用指數自己嘅實際交易日；美債 10 年期貨：亞洲用訊號日前一個交易日收市、歐美用同日）。
由 2026-11 起計；已入賬嘅月份存喺 merebal_shadow.json，之後唔改。數據：Yahoo 公開日線（請求唔帶個人資料）。
用法：python3 research/strategy_search/merebal_shadow.py → research/strategy_search/MEREBAL_SHADOW.md"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from xau import merebal_feed as MF  # noqa: E402

OUT = os.path.join(HERE, "MEREBAL_SHADOW.md")
LEDGER = os.path.join(HERE, "merebal_shadow.json")
START = (2026, 11)
COST = 0.0004
LEGS = [("標普 ^GSPC", "^GSPC", False, "真倉 945（SP500 0.2 手）"), ("富時 ^FTSE", "^FTSE", False, "真倉 946（UK100 0.1 手）"), ("DAX ^GDAXI", "^GDAXI", False, "影子（#1469 另一半）"),
        ("日經 ^N225", "^N225", True, "影子 #1481"), ("ASX200 ^AXJO", "^AXJO", True, "影子 #1481")]


def fetch(tk):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(tk)}?range=1y&interval=1d"
    for _ in range(3):
        try:
            rows = MF.parse_chart(json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read()))
            if rows:
                return rows
        except Exception:  # noqa: BLE001
            pass
    return []


def month_row(rows, bond, ym, lag):
    """該月已完結先計：→ dict 或 None。"""
    cur = [(d, c) for d, c in rows if (d.year, d.month) == ym]; prev = [(d, c) for d, c in rows if (d.year, d.month) < ym]; nxt = [d for d, _ in rows if (d.year, d.month) > ym]
    if not nxt or not prev or len(cur) < 12:
        return None
    sd, sp = cur[-6]; ed, ep = cur[-1]; pd_, pp = prev[-1]

    def bv(day):
        v = [c for d, c in bond if (d < day if lag else d <= day)]; return v[-1] if v else None
    b1, b0 = bv(sd), bv(pd_)
    if b1 is None or b0 is None:
        return None
    im, bm = sp / pp - 1, b1 / b0 - 1; side = 1 if im - bm < 0 else -1
    return {"sig": sd.isoformat(), "idx_mtd": round(im, 5), "bond_mtd": round(bm, 5), "side": side, "entry": round(sp, 2), "exit_day": ed.isoformat(), "exit": round(ep, 2), "net": round(side * (ep / sp - 1) - COST, 5)}


def main():
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}; bond = fetch(MF.BOND); today = dt.datetime.now(dt.timezone.utc).date(); last = {}
    for name, tk, lag, _ in LEGS:
        rows = fetch(tk); last[name] = rows[-1][0].isoformat() if rows else "攞唔到"; ym = START
        while ym <= (today.year, today.month):
            key = f"{ym[0]}-{ym[1]:02d}"
            if rows and bond and key not in led.get(name, {}):
                r = month_row(rows, bond, ym, lag)
                if r:
                    led.setdefault(name, {})[key] = r
            ym = (ym[0] + (ym[1] == 12), ym[1] % 12 + 1)
    json.dump(led, open(LEDGER, "w"), ensure_ascii=False, indent=1, sort_keys=True)
    L = ["# 影子前向：月尾股債再平衡（#1466 美國／#1469 歐洲／#1481 亞洲）", "",
         f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；由 {START[0]}-{START[1]:02d} 起計；每個月完結後入賬一行；來回成本 {100 * COST:.2f}%，未扣隔夜息；唔落單。",
         "- 亞洲兩隻（#1481）係影子；標普、富時有真倉（945／946，20:45 UTC 入場，同呢度嘅收市價口徑會有少少出入），呢度係紙上對照。", "",
         "| 腳 | 身份 | 日線到 | 已入賬月數 | 累計淨回報 | 勝月 |", "|---|---|---|---|---|---|"]
    for name, _, _, role in LEGS:
        v = list(led.get(name, {}).values()); tot = sum(x["net"] for x in v)
        L.append(f"| {name} | {role} | {last[name]} | {len(v)} | {100 * tot:+.2f}% | {sum(x['net'] > 0 for x in v)}／{len(v)} |")
    L += ["", "## 逐月記錄", "", "| 月 | 腳 | 訊號日 | 指數當月 | 美債當月 | 方向 | 入場（訊號日收市） | 出場日 | 出場 | 淨回報 |", "|---|---|---|---|---|---|---|---|---|---|"]
    rows = sorted((k, name, r) for name in led for k, r in led[name].items())
    for k, name, r in rows:
        L.append(f"| {k} | {name} | {r['sig']} | {100 * r['idx_mtd']:+.2f}% | {100 * r['bond_mtd']:+.2f}% | {'多' if r['side'] > 0 else '空'} | {r['entry']:.2f} | {r['exit_day']} | {r['exit']:.2f} | {100 * r['net']:+.2f}% |")
    if not rows:
        L.append("| — | 未有完結嘅月份（2026-11 月尾後入賬） | | | | | | | | |")
    L += ["", "- 判準（#1481 轉真倉前要睇）：亞洲兩隻前向滿 12 個月，合併每月淨平均 > 0；另外要先做真倉口徑驗證（隔夜息、規則日曆、券商合約規格）。", ""]
    open(OUT, "w").write("\n".join(L) + "\n"); print("\n".join(L))


if __name__ == "__main__":
    main()
