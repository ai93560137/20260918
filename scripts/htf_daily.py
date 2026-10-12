#!/usr/bin/env python3
"""HTF 全期參數 每日訊號（港台日美；美股 2026-10-12 使用者要求加入；參數 = research/htf_curvefit/<市場>.json 的全期最佳；使用者 2026-10-12 指示）。

    python3 scripts/htf_daily.py --market hk tw jp            # 出明日買入觸發價 + 前向持倉出場指令 + Telegram 摘要
    python3 scripts/htf_daily.py --market hk --selftest 20    # 機制自檢：歷史 20 個交易日，「當日候選」必須涵蓋回測下一日的全部入場

引擎與回測同一套（htf_curvefit.CF）。所有條件用「今天收市」判斷（= 回測的 t−1），明天盤中最高 > 旗桿頂 P 才成交：
  - 掛單：觸發價 P（買入停損單）；明天開市 > P ×（1 + 追價上限）就取消；成交價 = max(開市, P)
  - 初始停損 = 成交價 ×（1 − 停損倍數 × ADR20）；入場當日收市後上移到當日最低；賣一半後移到成本（回測口徑）
  - 前向持倉（FWD_START 起入場）每天從頭重算狀態，不靠記憶狀態
輸出 analysis/htf_daily/：<市場>_orders_<日期>.csv、<市場>_positions.csv、<市場>_closed.csv、<市場>_latest.json、tg_htf.txt、log.csv

⚠️ 下游依賴（2026-10-12）：總指揮（分支 claude/beautiful-hypatia-8qrgjj，Cloud Run ?view=htf 與策略總表 htf_<市場> 四行，R165）
直接讀這些檔：檔名規則（orders 帶日期）、欄位名、「（無）」空檔格式、latest.json 的 date／n_orders／n_open／n_closed／mkt_filter／mkt_ok／params。
改任何格式前先用 send_message 通知總指揮 session_01N1jfpEJciBkfAgwtd4QxgU。
"""
import argparse
import csv
import gc
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import htf_backtest as H  # noqa: E402
import htf_curvefit as C  # noqa: E402

OUT = ROOT / "analysis" / "htf_daily"
FWD_START = date(2026, 10, 13)          # 前向紀錄由這天（含）之後入場的交易算起
BASE = 0.20                              # 每筆基本資金比例（與 HTF_INVESTOR_BRIEF 主表一致）；風險倉位 × w
NAME = {"hk": "港股", "tw": "台股", "jp": "日股", "us": "美股"}
TRAIL_TXT = {"ma10": "10 日線", "ma20": "20 日線", "ma50": "50 日線"}


def params(mk: str) -> dict:
    return json.loads((C.OUT / f"{mk}.json").read_text(encoding="utf-8"))["search"]["best"]


def weight(c: dict, adr: float) -> float:
    return float(np.clip(0.05 / adr, 0.25, 4.0)) if c["risk"] else 1.0


def candidates(x: C.CF, c: dict, asof_j: int) -> list[dict]:
    """以日曆第 asof_j 日收市為準（= 回測 t−1），找出下一交易日的掛單候選（未套「下一日盤中突破」與追價）。"""
    m = x.m
    if c["mkt"] and not x.mkt_ok[asof_j]:
        return []
    mq = x.mom_ok[c["mom_q"]]
    out = []
    for s, rw in x.raw.items():
        if not (m.member[s, asof_j] and mq[s, asof_j]):
            continue
        hit = np.nonzero(rw["jarr"] == asof_j)[0]
        if len(hit) == 0:
            continue
        i = int(hit[0])                      # 今天在該股自己的索引
        p = i + 1                            # 回測裡的入場索引（虛擬：明天）
        if p < 2 * H.POLE_LOOK + 1:
            continue
        high, low, vol, adj = rw["high"], rw["low"], rw["vol"], rw["adj"]
        win = high[p - H.POLE_LOOK:p]
        k = int(np.argmax(win))
        ptop = p - H.POLE_LOOK + k
        P = float(high[ptop])
        flag_len = (p - 1) - ptop
        if not (H.FLAG_MIN <= flag_len <= c["flag_max"]):
            continue
        pole_low = low[ptop - H.POLE_LOOK:ptop + 1].min()
        G = P / pole_low - 1 if pole_low > 0 else 0.0
        D = (P - low[ptop + 1:p].min()) / P
        if G < c["g"] or D > c["d"]:
            continue
        volp, volf = vol[ptop - 19:ptop + 1].mean(), vol[ptop + 1:p].mean()
        vr = volf / volp if volp > 0 else np.inf
        if c["vol"] is not None and not vr < c["vol"]:
            continue
        if c["ma20"] and not adj[i] > rw["ma20"][i]:
            continue
        adr = float(rw["adr"][i])
        if not (adr == adr and adr > 0) or adr < c["adr_min"]:
            continue
        out.append({"s": s, "ticker": m.tickers[s], "pivot": P, "max_open": P * (1 + c["chase"]),
                    "stop_if_fill_at_pivot": P * (1 - c["stop"] * adr), "adr": adr, "G": G, "D": D, "flag_len": int(flag_len),
                    "vol_ratio": float(vr), "close": float(rw["close"][i]), "dist_pct": P / float(rw["close"][i]) - 1,
                    "weight": weight(c, adr), "alloc_pct": BASE * weight(c, adr)})
    out.sort(key=lambda r: r["dist_pct"])
    return out


def state(x: C.CF, t: dict, c: dict) -> dict:
    """前向持倉：照 CF.sim 的規則逐日走到最後一根，回傳現況與明天要做的事（不靠記憶狀態）。"""
    s, p, fill = t["s"], t["p"], t["fill"]
    rw = x.raw[s]
    high, low, close, opn, adj, ma = (rw[k] for k in ("high", "low", "close", "open", "adj", c["trail"]))
    n = len(close)
    adr = t["info"]["adr"]
    stop = fill * (1 - c["stop"] * adr)
    o0 = opn[p] if opn[p] == opn[p] and opn[p] > 0 else fill
    legs = []
    if low[p] <= stop and not (o0 < fill and low[p] == o0):
        return {"open": False, "legs": [(p, stop, "入場當日停損", 1.0)]}
    stop = max(stop, low[p])
    units, exit_next, pd_ = 1.0, False, c["partial"]
    start_trail = p + (pd_ if pd_ else 1)
    last = min(n, p + c["hold"] + 1)
    for k in range(p + 1, last):
        o = opn[k] if opn[k] == opn[k] and opn[k] > 0 else close[k]
        if exit_next:
            legs.append((k, o, f"收市破{TRAIL_TXT[c['trail']]}→開市賣", units))
            return {"open": False, "legs": legs}
        if low[k] <= stop:
            legs.append((k, min(o, stop), "觸及停損", units))
            return {"open": False, "legs": legs}
        if pd_ and k == p + pd_:
            legs.append((k, close[k], f"第 {pd_} 日收市賣一半", 0.5))
            units = 0.5
            stop = max(stop, fill)
        if k >= start_trail and ma[k] == ma[k] and adj[k] < ma[k]:
            exit_next = True
    if last < n or (last == n and p + c["hold"] + 1 <= n):
        legs.append((last - 1, close[last - 1], "最長持有到期收市賣", units))
        return {"open": False, "legs": legs}
    held = (n - 1) - p
    tomorrow = n                               # 明天的索引
    if exit_next:
        act = f"明天開市全數賣出（今天收市破{TRAIL_TXT[c['trail']]}）"
    elif pd_ and tomorrow == p + pd_:
        act = f"明天收市賣一半（第 {pd_} 日），之後停損移到成本 {fill:.4g}"
    elif tomorrow == p + c["hold"]:
        act = "明天收市全數賣出（最長持有到期）"
    else:
        act = "持有"
    return {"open": True, "legs": legs, "units": units, "stop": float(stop), "held": held, "action": act,
            "close": float(close[n - 1]), "ma": float(ma[n - 1]) if ma[n - 1] == ma[n - 1] else None}


def run_market(mk: str, selftest: int) -> dict | None:
    c = params(mk)
    x = C.CF(mk)
    m = x.m
    jT = len(m.cal) - 1
    # 日曆最後一日要有足夠股票（同鳥翔：宇宙前 N 至少一半有價）
    cover = (m.has & m.member).sum(0) / max(int(getattr(m, "top_n", 0)), 1)
    jT = int(np.nonzero(cover >= 0.5)[0][-1])
    d = m.cal[jT]
    if selftest:
        return selftest_market(x, c, jT, selftest)
    tr = x.ctrades(c)
    fwd = [t for t in tr if x.raw[t["s"]]["dlist"][t["p"]] >= FWD_START]
    held_s = set()
    pos_rows, closed_rows = [], []
    for t in fwd:
        st = state(x, t, c)
        rw = x.raw[t["s"]]
        base = {"ticker": m.tickers[t["s"]], "entry_date": rw["dlist"][t["p"]].isoformat(), "fill": round(t["fill"], 4),
                "adr": round(t["info"]["adr"], 4), "weight": round(weight(c, t["info"]["adr"]), 2)}
        if st["open"]:
            held_s.add(t["s"])
            pos_rows.append({**base, "units": st["units"], "held_days": st["held"], "close": st["close"],
                             "stop_tomorrow": round(st["stop"], 4), "pnl_pct": round(st["close"] / t["fill"] - 1, 4),
                             "action": st["action"]})
        else:
            ret = sum(u * px for _, px, _, u in st["legs"]) / t["fill"] - 1
            closed_rows.append({**base, "exit_date": rw["dlist"][st["legs"][-1][0]].isoformat(),
                                "exits": "；".join(f"{rw['dlist'][k].isoformat()} {why} {u:g} 份 @ {px:.4g}" for k, px, why, u in st["legs"]),
                                "ret_gross": round(ret, 4)})
    cands = [r for r in candidates(x, c, jT) if r["s"] not in held_s]
    OUT.mkdir(parents=True, exist_ok=True)
    tag = d.isoformat()
    cols = ["ticker", "close", "pivot", "dist_pct", "max_open", "stop_if_fill_at_pivot", "adr", "weight", "alloc_pct", "G", "D", "flag_len", "vol_ratio"]
    with open(OUT / f"{mk}_orders_{tag}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in cands:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    for name, rows in (("positions", pos_rows), ("closed", closed_rows)):
        p_ = OUT / f"{mk}_{name}.csv"
        with open(p_, "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
                w.writeheader()
                w.writerows(rows)
            else:
                f.write("（無）\n")
    meta = {"market": mk, "date": tag, "params": c, "n_orders": len(cands), "n_open": len(pos_rows), "n_closed": len(closed_rows),
            "mkt_ok": bool(x.mkt_ok[jT]), "mkt_filter": c["mkt"], "fwd_start": FWD_START.isoformat(),
            "closed_avg": float(np.mean([r["ret_gross"] for r in closed_rows])) if closed_rows else None,
            "closed_win": float(np.mean([r["ret_gross"] > 0 for r in closed_rows])) if closed_rows else None,
            "orders_top": [f"{r['ticker']} 觸發 {r['pivot']:.4g}（距收市 {r['dist_pct']:+.1%}）" for r in cands[:8]],
            "positions": [f"{r['ticker']} {r['action']}；停損 {r['stop_tomorrow']:.4g}；浮動 {r['pnl_pct']:+.1%}" for r in pos_rows]}
    (OUT / f"{mk}_latest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    with open(OUT / "log.csv", "a", newline="", encoding="utf-8") as f:
        f.write(f"{tag},{mk},{len(cands)},{len(pos_rows)},{len(closed_rows)}\n")
    print(f"[{mk}] {tag}：明日掛單 {len(cands)}、前向持倉 {len(pos_rows)}、已平倉 {len(closed_rows)}", file=sys.stderr)
    return meta


def selftest_market(x: C.CF, c: dict, jT: int, ndays: int) -> None:
    """歷史上每一日：候選（不看明天）必須涵蓋回測「下一交易日」的全部入場，觸發價一致。"""
    m = x.m
    tr = x.ctrades(c)
    by_day = {}
    for t in tr:
        by_day.setdefault(t["info"]["j"] if "j" in t["info"] else x.raw[t["s"]]["jarr"][t["p"]], []).append(t)
    days = sorted(by_day)[-ndays:]
    bad = 0
    for jn in days:
        for t in by_day[jn]:
            rw = x.raw[t["s"]]
            j_prev = int(rw["jarr"][t["p"] - 1])
            cs = {r["s"]: r for r in candidates(x, c, j_prev)}
            r = cs.get(t["s"])
            if r is None or abs(r["pivot"] - t["info"]["pivot"]) > 1e-9:
                bad += 1
                print(f"  ✗ {m.tickers[t['s']]} 入場 {rw['dlist'][t['p']]}：候選{'沒有' if r is None else '觸發價不同'}", file=sys.stderr)
    n = sum(len(by_day[j]) for j in days)
    print(f"[{x.market}] 自檢：最近 {len(days)} 個有入場的交易日共 {n} 筆，候選漏掉／不一致 {bad} 筆", file=sys.stderr)


def tg(metas: list[dict]) -> str:
    L = [f"🕊 鳥翔｜HTF 每日掛單 {max(m_['date'] for m_ in metas)}", "（高漲旗型，全期擬合參數；鳥翔每日一腿，月底名單另發）", ""]
    for m_ in metas:
        mk = m_["market"]
        filt = "" if not m_["mkt_filter"] else ("｜大市過濾 ✅" if m_["mkt_ok"] else "｜大市過濾 ⛔ 明天不開新倉")
        L.append(f"{NAME[mk]} {m_['date']}{filt}：明天掛單 {m_['n_orders']} 隻、持倉 {m_['n_open']}、前向已平倉 {m_['n_closed']}")
        if m_["orders_top"]:
            L.append("　掛單（最近觸發價先）：" + "；".join(m_["orders_top"]))
        for pz in m_["positions"]:
            L.append("　持倉：" + pz)
    L += ["", "掛單 = 明天盤中升穿觸發價才買（買入停損單）；開市已高於觸發價 × (1+追價上限) 就取消。",
          "每筆資金 = 20% × 權重（按波幅，見 CSV alloc_pct）；總曝險不超過 100%。",
          "網頁（可列印成 PDF）：https://zhuge-risk-manager-1056099871997.europe-west1.run.app/?view=htf",
          "明細：analysis/htf_daily/<市場>_orders_<日期>.csv、<市場>_positions.csv"]
    return "\n".join(L)[:3900] + "\n"


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", nargs="+", default=["hk", "tw", "jp", "us"], choices=list(NAME))
    a.add_argument("--selftest", type=int, default=0)
    args = a.parse_args()
    metas = []
    for mk in args.market:
        r = run_market(mk, args.selftest)
        if r:
            metas.append(r)
        gc.collect()
    if metas:
        (OUT / "tg_htf.txt").write_text(tg(metas), encoding="utf-8")


if __name__ == "__main__":
    main()
