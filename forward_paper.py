#!/usr/bin/env python3
"""Minervini（主）＋ VCP 全市場 XV（次）紙上前向記錄（預先登記：stock_research/FORWARD_PAPER.md A2）。

    python3 forward_paper.py                    # 9 國全部：重算凍結規格，只留入場日 ≥ 2026-11-06 的交易
    python3 forward_paper.py --market hk        # 單一市場

每月底全市場數據更新（Release fullmarket-data／oos-data，用 scripts/get_market_data.py 下載）後跑；
規則全機械、只用當日及以前的數據，月底補算與每日即時記錄結果相同。輸出 research/forward/。
"""
import argparse
import csv
import io
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import vcp_backtest as vb  # noqa: E402
import vcp_minervini as vm  # noqa: E402
from matrix_fill import vcp_drop_locked  # noqa: E402
from oos_backtest import locked_matrix  # noqa: E402

START = date(2026, 11, 6)          # 登記 commit 後第一個交易日
MARKETS = ("hk", "jp", "us", "tw", "kr", "au", "ca", "in", "sg")
OUT = ROOT / "research" / "forward"
FIELDS = ["strategy", "market", "ticker", "entry", "entry_px_adj", "exit", "exit_px_adj", "status", "ret_net", "hold_days"]


def run_market(mk: str, start: date) -> list[dict]:
    v = vb.VCPData(mk, full=True)                  # scan=True：XV 需要 VCP 事件；Minervini 另掃自己的形態
    m = v.m
    last_j = len(m.cal) - 1
    lk = locked_matrix(m, mk)
    cost = m.cfg["cost"]
    rows = []
    # ---- 主：Minervini 忠實版（凍結 DEFAULT）----
    mv = vm.Minervini(mk, set(), v=v)
    mv.setups = [x for x in mv.setups if not lk[x[0], x[2]]]
    for t in mv.trades(*vm.DEFAULT):
        if m.cal[t["a"]] < start:
            continue
        rw = v.raw[t["s"]]
        still_open = t["at_close"] and t["b"] == last_j and (t["b"] - t["a"]) < vm.MAX_HOLD
        rows.append({"strategy": "Minervini", "market": mk, "ticker": m.tickers[t["s"]],
                     "entry": m.cal[t["a"]].isoformat(), "entry_px_adj": f"{t['in_adj']:.6g}",
                     "exit": "" if still_open else m.cal[t["b"]].isoformat(), "exit_px_adj": f"{t['out_adj']:.6g}",
                     "status": "open" if still_open else "closed",
                     "ret_net": f"{t['out_adj'] / t['in_adj'] * (1 - cost) ** 2 - 1:.4f}", "hold_days": t["b"] - t["a"]})
    # ---- 次：VCP 全市場 XV（凍結 DEFAULT）----
    ev = vcp_drop_locked(m, v.events(*vb.DEFAULT), lk)
    for s, a, b, op in v.trades(ev, "xv"):
        if m.cal[a] < start:
            continue
        pin = m.aopen[s, a]                                            # 訊號次日開市入場（還原價）
        pout = m.aopen[s, b] if op else m.adj[s, b]                    # op = 開市出場，否則收市
        still_open = b == last_j
        rows.append({"strategy": "VCP_XV", "market": mk, "ticker": m.tickers[s], "entry": m.cal[a].isoformat(),
                     "entry_px_adj": f"{pin:.6g}", "exit": "" if still_open else m.cal[b].isoformat(),
                     "exit_px_adj": f"{pout:.6g}", "status": "open" if still_open else "closed",
                     "ret_net": f"{pout / pin * (1 - cost) ** 2 - 1:.4f}", "hold_days": b - a})
    print(f"[{mk}] 數據到 {m.cal[-1]}；前向（入場 ≥ {start}）Minervini {sum(r['strategy'] == 'Minervini' for r in rows)} 筆、"
          f"XV {sum(r['strategy'] == 'VCP_XV' for r in rows)} 筆", file=sys.stderr)
    return rows, m.cal[-1]


def summarize() -> str:
    """由磁碟上全部帳本（research/forward/ledger_<m>.csv）重建摘要；單一市場日更也能用。"""
    L = [f"# 紙上前向記錄（前向起點 {START}；規則見 stock_research/FORWARD_PAPER.md）\n",
         "描述性：前向 6–12 個月檢定力很低，只作災難偵測與執行檢查；12 個月（2027-11）才套用原登記證偽條件。\n",
         "| 市場 | 帳本更新 | Minervini 筆數（已平倉／未平倉） | Minervini 已平倉平均淨報酬 | XV 筆數（已平倉／未平倉） | XV 已平倉平均淨報酬 |",
         "|---|---|---|---|---|---|"]
    for mk in MARKETS:
        p = OUT / f"ledger_{mk}.csv"
        if not p.exists():
            L.append(f"| {mk} | — | — | — | — | — |")
            continue
        rows = list(csv.DictReader(open(p, encoding="utf-8")))
        upd = (OUT / f"ledger_{mk}.asof").read_text().strip() if (OUT / f"ledger_{mk}.asof").exists() else "—"
        cells = []
        for st in ("Minervini", "VCP_XV"):
            rs = [r for r in rows if r["strategy"] == st]
            cl = [float(r["ret_net"]) for r in rs if r["status"] == "closed"]
            cells += [f"{len(cl)}／{len(rs) - len(cl)}", f"{sum(cl) / len(cl):+.1%}" if cl else "—"]
        L.append(f"| {mk} | 數據到 {upd} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--market", choices=MARKETS)
    a.add_argument("--start", type=date.fromisoformat, default=START, help="只供測試程式；正式記錄一律用登記起點")
    a.add_argument("--dry-run", action="store_true", help="不寫檔（測試用）")
    a.add_argument("--monthly", metavar="YYYY-MM", help="只出月度快照 research/forward/<YYYY-MM>.md（不重算）")
    a.add_argument("--summary", action="store_true", help="只由現有帳本重建 research/forward/README.md（不重算）")
    args = a.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.summary:
        (OUT / "README.md").write_text(summarize(), encoding="utf-8")
        return
    if args.monthly:
        (OUT / f"{args.monthly}.md").write_text(f"<!-- {args.monthly} 月度快照（月初由 fullmarket_daily.yml group=monthly 產生） -->\n"
                                                + summarize(), encoding="utf-8")
        return
    for mk in ([args.market] if args.market else MARKETS):
        rows, last = run_market(mk, args.start)
        if args.dry_run:
            continue
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        (OUT / f"ledger_{mk}.csv").write_text(buf.getvalue(), encoding="utf-8")
        (OUT / f"ledger_{mk}.asof").write_text(f"{last}\n", encoding="utf-8")
    if not args.dry_run and not args.market:      # 單一市場日更時由工作流程最後一步統一重建摘要（避免並行 job 互相覆寫）
        (OUT / "README.md").write_text(summarize(), encoding="utf-8")


if __name__ == "__main__":
    main()
