"""[IDEAS #2004 影子前向] NQ／ES 合格策略日線影子：每日用 yfinance 重新計訊號，記錄 2026-11-09 起嘅訊號同持倉（唔落單）。

NQ：Donchian 20 日只做好、止蝕 2×ATR、20 日低位出（F2 N20 k2 M20）
ES：Donchian 20 日只做好、止蝕 3×ATR、10 日低位出（F2 N20 k3 M10）
NQ_T2：Keltner 突破 k1.5 只做好（#2015，收市 > EMA20 + 1.5×ATR 買、收市 < EMA20 出、止蝕 2×ATR）
目標：每隻 10 張或 2027-05-09（6 個月），之後按 #2004 判（平均 R > 0、PF ≥ 1.2、冇連敗 > 4）先提案真倉（MNQ／MES 1 張，使用者批）。
輸出：GCS longfei/strategy_search/shadow/latest.json（已平倉張、而家持倉、今日訊號）。
"""
import json
from datetime import datetime, timezone
import daily_search as ds
import batch7 as b7
import batch4 as b4
import batch13 as b13

START = "2026-11-09"
CFG = {"NQ": ("NQ=F", {"N": 20, "k": 2, "M": 20, "both": False}), "ES": ("ES=F", {"N": 20, "k": 3, "M": 10, "both": False})}


def main():
    out = {"updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "start": START, "ideas": [2004, 2009, 2015]}
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
    # [#2015 T2] NQ Keltner 突破 k1.5 只做好
    b = ds.load("NQ=F")
    ind = ds.indicators(b)
    ex = b13.extra(b, ind)
    p = {"k": 1.5, "both": False}
    done = [x for x in b13.run13(b, ind, ex, "T2", p) if x["d"] >= START]
    i = len(b) - 1
    up = ex["ema"][i] + 1.5 * ind["atr"][i]
    out["NQ_T2"] = {"params": p, "last_bar": b[-1][0], "close": round(ind["c"][i], 2), "closed_trades": done,
                    "stats": ds.stats(done) if len(done) >= 2 else {"n": len(done)},
                    "signal_today": bool(ind["c"][i] > up), "entry_level": round(up, 2), "exit_level_ema20": round(ex["ema"][i], 2),
                    "judge": "10 張或 2027-05-09：平均 R > 0、PF ≥ 1.2、冇連敗 > 4 → 先提案真倉（使用者批）"}
    print("NQ_T2", b[-1][0], "收", round(ind["c"][i], 2), "入場線", round(up, 2), "EMA20", round(ex["ema"][i], 2), "已平", len(done))
    # [#2009 C2] MHI 組合影子（使用者 11-09「C2 開始做影子前向測試」）：K3 月度動量 L6 雙向＋H1 市況切換＋K2 週度動量 L4 雙向
    b = ds.load("^HSI")
    ind = ds.indicators(b)
    mem = {m: [x for x in b7.member(b, ind, m) if x["d"] >= START] for m in ("K3", "H1", "K2")}
    allc = sorted([dict(x, m=m) for m, v in mem.items() for x in v], key=lambda x: x["d"])
    c = ind["c"]
    def past(n_months=None, n_weeks=None):
        from datetime import date
        d = [x[0] for x in b]
        if n_months:
            ends = [i for i in range(len(b) - 1) if d[i + 1][:7] != d[i][:7]] + [len(b) - 1]
            return c[ends[-1]] / c[ends[-1 - n_months]] - 1
        wk = lambda i: date.fromisoformat(d[i]).isocalendar()[:2]  # noqa: E731
        ends = [i for i in range(len(b) - 1) if wk(i + 1) != wk(i)] + [len(b) - 1]
        return c[ends[-1]] / c[ends[-1 - n_weeks]] - 1
    rg = b4.regime(b, ind)[-1]
    out["MHI_C2"] = {"members": {"K3": "月度動量 6 個月雙向（+200 日線過濾）", "H1": "市況切換：升勢 Donchian55 只做好、其他布林帶回歸雙向",
                                 "K2": "週度動量 4 週雙向"},
                     "last_bar": b[-1][0], "close": round(c[-1], 2), "closed_trades": allc,
                     "stats": ds.stats(allc) if len(allc) >= 2 else {"n": len(allc)},
                     "by_member": {m: (ds.stats(v) if len(v) >= 2 else {"n": len(v)}) for m, v in mem.items()},
                     "now": {"K3_6m_ret": round(past(n_months=6), 4), "K3_above_sma200": bool(ind["sma"][200][-1] and c[-1] > ind["sma"][200][-1]),
                             "K2_4w_ret": round(past(n_weeks=4), 4), "H1_regime": rg},
                     "judge": "30 張或 2027-05-09：平均 R > 0、PF ≥ 1.2、累計 R > 0 → 先提案真倉（使用者批）"}
    print("MHI C2", b[-1][0], "已平", len(allc), out["MHI_C2"]["now"])
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/strategy_search/shadow/latest.json") \
        .upload_from_string(json.dumps(out, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
