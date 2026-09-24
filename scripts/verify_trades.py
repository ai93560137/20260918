#!/usr/bin/env python3
"""全市場 VCP 預設格逐筆交易核對（stock_research/VCP_FULLMARKET_BACKTEST.md 第一部分之二第 4 條，規則寫死）。

    python3 scripts/verify_trades.py --market us      # 讀 research/vcp_full/us_v2.json 的 trades_detail

- 美股：Nasdaq 歷史 API（近 10 年）；日股：Yahoo!ファイナンス日線頁；比訊號日收市、入場開市、出場價，
  以「第二來源 ÷ 我們」的比例看：三個比例之間差 > 2%（不是同一個拆股係數能解釋的）→ 可疑；
  成交量：量比 × 價比 偏離 1 超過 30% → 可疑
- 港股：沒有免費歷史第二來源 → 內部一致性：訊號日量 > 50 日均量 20 倍、訊號日價格一來一回
  （漲 >40% 隔日跌 >20%）、入場開市相對訊號日收市跳 >30% → 可疑
- 輸出 research/vcp_full/<m>_suspect.json（[[ticker, 訊號日], ...]）並把摘要附在 <m>_qc.md
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import newhigh_backtest as nb  # noqa: E402

TOL_PX, TOL_VOL = 0.02, 0.30


def num(s) -> float | None:
    try:
        return float(str(s).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def us_history(s: requests.Session, t: str) -> dict[date, dict]:
    import fetch_second_source as fs
    r = s.get(f"https://api.nasdaq.com/api/quote/{t.replace('-', '.')}/historical", headers=fs.UA, timeout=60,
              params={"assetclass": "stocks", "fromdate": "2000-01-01", "todate": date.today().isoformat(),
                      "limit": "20000"})
    r.raise_for_status()
    rows = (((r.json().get("data") or {}).get("tradesTable") or {}).get("rows")) or []
    out = {}
    for x in rows:
        mo, dd, y = x["date"].split("/")
        out[date(int(y), int(mo), int(dd))] = {"open": num(x.get("open")), "close": num(x.get("close")),
                                               "volume": num(x.get("volume"))}
    return out


def jp_window(s: requests.Session, t: str, a: date, b: date) -> dict[date, dict]:
    import xcheck_history as xh
    rows = xh.yj_pages(s, t, {"from": a.strftime("%Y%m%d"), "to": b.strftime("%Y%m%d"), "timeFrame": "d"}, 2)
    out = {}
    for h in rows:
        v = h["values"]
        out[date.fromisoformat(h["date"])] = {"open": num(v[0]["value"]), "close": num(v[3]["value"]),
                                              "volume": num(v[4]["value"])}
    return out


def check(tr: dict, src: dict[date, dict], split_ok: bool = False) -> tuple[str, str]:
    """回傳 (狀態 ok/suspect/unverifiable, 說明)。
    split_ok（stock_research/AIBA_PPP_BACKTEST.md 登記）：三個比例相差剛好一個整數倍（≥2，誤差 2% 內）= 第二來源沒按拆股還原，不算可疑。"""
    sig, ent, ex = (date.fromisoformat(tr[k]) for k in ("signal", "entry", "exit"))
    pts = [(sig, "close", tr["signal_close"]), (ent, "open", tr["entry_open"]),
           (ex, "open" if tr["exit_at_open"] else "close", tr["exit_px"])]
    ratios = []
    for d, k, ours in pts:
        th = (src.get(d) or {}).get(k)
        if th and ours:
            ratios.append(th / ours)
    if len(ratios) < 2:
        return "unverifiable", "第二來源沒有這些日子"
    if max(ratios) / min(ratios) - 1 > TOL_PX:
        k = max(ratios) / min(ratios)
        if split_ok and round(k) >= 2 and abs(k / round(k) - 1) <= TOL_PX:
            return "ok", f"第二來源未按拆股還原（比例 {[round(x, 4) for x in ratios]}）"
        return "suspect", f"價格比例不一致 {[round(x, 4) for x in ratios]}"
    v = (src.get(sig) or {}).get("volume")
    if v and tr["signal_volume"]:
        adj = v / tr["signal_volume"] * ratios[0]
        if abs(adj - 1) > TOL_VOL:
            return "suspect", f"訊號日成交量不符（{v:.0f} vs {tr['signal_volume']:.0f}）"
    return "ok", ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", required=True, choices=["hk", "jp", "us", "tw", "kr", "au", "ca", "in", "sg"])
    ap.add_argument("--src", help="逐筆明細 JSON（預設 research/vcp_full/<m>_v2.json）")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "research" / "vcp_full")
    ap.add_argument("--sample", type=int, default=0, help="隨機抽 N 筆核對（種子 0；0 = 全部）")
    ap.add_argument("--split-ok", action="store_true", help="整數倍比例 = 第二來源未還原拆股，不算可疑")
    args = ap.parse_args()
    m = args.market
    src_p = Path(args.src) if args.src else ROOT / "research" / "vcp_full" / f"{m}_v2.json"
    res = json.loads(src_p.read_text(encoding="utf-8"))
    trades = res.get("trades_detail", [])
    if args.sample and len(trades) > args.sample:
        import random
        trades = random.Random(0).sample(trades, args.sample)
    status, notes = {}, {}
    s = requests.Session()
    if m == "us":
        cache = {}
        for tr in trades:
            t = tr["ticker"]
            if t not in cache:
                try:
                    cache[t] = us_history(s, t)
                except Exception as exc:
                    print(f"WARN {t}: {exc}", file=sys.stderr)
                    cache[t] = {}
                time.sleep(0.5)
            status[(t, tr["signal"])], notes[(t, tr["signal"])] = check(tr, cache[t], args.split_ok)
    elif m == "jp":
        s.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "ja"})
        time.sleep(90)
        for tr in trades:
            t = tr["ticker"]
            sig, ex = date.fromisoformat(tr["signal"]), date.fromisoformat(tr["exit"])
            try:
                src = jp_window(s, t, sig - timedelta(days=3), date.fromisoformat(tr["entry"]) + timedelta(days=3))
                src |= jp_window(s, t, ex - timedelta(days=3), ex + timedelta(days=3))
            except Exception as exc:
                print(f"WARN {t}: {exc}", file=sys.stderr)
                src = {}
            status[(t, tr["signal"])], notes[(t, tr["signal"])] = check(tr, src, args.split_ok)
    else:
        load = nb.load_full(m)          # 港股與樣本外新市場：內部一致性
        for tr in trades:
            t = tr["ticker"]
            rows = load(t)
            ds = [r["Date"] for r in rows]
            i = ds.index(date.fromisoformat(tr["signal"]))
            vol = np.array([r["Volume"] for r in rows[max(0, i - 50):i]], dtype=float)
            c0, c1 = rows[i - 1]["Close"], rows[i]["Close"]
            c2 = rows[i + 1]["Close"] if i + 1 < len(rows) else c1
            why = []
            if vol.size and vol.mean() > 0 and rows[i]["Volume"] > 20 * vol.mean():
                why.append("訊號日成交量 > 50 日均量 20 倍")
            if c1 / c0 > 1.4 and c2 / c1 < 0.8:
                why.append("訊號日價格一來一回")
            if tr["entry_open"] and abs(tr["entry_open"] / c1 - 1) > 0.3:
                why.append("入場開市跳 >30%")
            status[(t, tr["signal"])] = "suspect" if why else "ok"
            notes[(t, tr["signal"])] = "、".join(why)
    sus = sorted(k for k, v in status.items() if v == "suspect")
    unv = sum(v == "unverifiable" for v in status.values())
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{m}_suspect.json").write_text(json.dumps([list(k) for k in sus], ensure_ascii=False) + "\n", encoding="utf-8")
    how = {"us": "Nasdaq 歷史 API", "jp": "Yahoo!ファイナンス日線"}.get(m, "內部一致性（無免費歷史第二來源）")
    L = [f"\n## 4. 逐筆交易核對（{how}）\n",
         f"預設格{'隨機抽' if args.sample else ''} {len(trades)} 筆：通過 {sum(v == 'ok' for v in status.values())}、**可疑 {len(sus)}**、"
         f"無法核對 {unv}（第二來源沒有那些日子，例如美股 10 年前）。可疑的剔除後重算判決。\n"]
    L += [f"- {t} {d}：{notes[(t, d)]}" for t, d in sus[:30]]
    qc = out / f"{m}_qc.md"
    qc.write_text((qc.read_text(encoding="utf-8") if qc.exists() else "") + "\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
