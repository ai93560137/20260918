"""[IDEAS #2004 影子前向] NQ／ES 合格策略日線影子：每日用 yfinance 重新計訊號，記錄 2026-11-09 起嘅訊號同持倉（唔落單）。

NQ：Donchian 20 日只做好、止蝕 2×ATR、20 日低位出（F2 N20 k2 M20）
ES：Donchian 20 日只做好、止蝕 3×ATR、10 日低位出（F2 N20 k3 M10）
目標：每隻 10 張或 2027-05-09（6 個月），之後按 #2004 判（平均 R > 0、PF ≥ 1.2、冇連敗 > 4）先提案真倉（MNQ／MES 1 張，使用者批）。
輸出：GCS longfei/strategy_search/shadow/latest.json（已平倉張、而家持倉、今日訊號）。
"""
import json
from datetime import datetime, timezone
import daily_search as ds

START = "2026-11-09"
CFG = {"NQ": ("NQ=F", {"N": 20, "k": 2, "M": 20, "both": False}), "ES": ("ES=F", {"N": 20, "k": 3, "M": 10, "both": False})}


def main():
    out = {"updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "start": START, "ideas": 2004}
    for mk, (tk, p) in CFG.items():
        b = ds.load(tk)
        ind = ds.indicators(b)
        tr = ds.run(b, ind, "F2", p)
        done = [x for x in tr if x["d"] >= START]
        c, i = ind["c"], len(b) - 1
        hi = max(x[2] for x in b[i - p["N"]:i])
        lo_exit = min(x[3] for x in b[i - p["M"] + 1:i + 1])
        out[mk] = {"params": p, "last_bar": b[-1][0], "close": round(c[-1], 2), "closed_trades": done,
                   "stats": ds.stats(done) if len(done) >= 2 else {"n": len(done)},
                   "signal_today": bool(c[i] > hi), "breakout_level": round(hi, 2), "exit_level": round(lo_exit, 2),
                   "atr14": round(ind["atr"][i], 2)}
        print(mk, b[-1][0], "收", round(c[-1], 2), "20 日高", round(hi, 2), "今日訊號", c[i] > hi, "已平", len(done))
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/shadow/latest.json") \
        .upload_from_string(json.dumps(out, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
