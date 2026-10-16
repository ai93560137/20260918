"""成績報告：python report.py            （由 logs 計）
              python report.py --futu     （另外由富途成交紀錄計，核對用）"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

from config import CFG


def load(name):
    p = CFG.log_dir / f"{name}.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def max_drawdown(values):
    peak, mdd = None, 0.0
    for v in values:
        peak = v if peak is None else max(peak, v)
        mdd = min(mdd, v - peak)
    return mdd


def summarize(closes, eq):
    pv = CFG.point_value
    trades = [t for t in closes if t.get("points") is not None]
    n = len(trades)
    print(f"=== 龍飛陣 AI 交易成績（{CFG.trd_env}）===")
    if eq:
        first, last = eq[0]["equity"], eq[-1]["equity"]
        print(f"期間        : {eq[0]['ts'][:10]} → {eq[-1]['ts'][:10]}")
        print(f"戶口淨值    : HK${first:,.0f} → HK${last:,.0f}（變動 HK${last - first:+,.0f}，已含費用）")
        print(f"最大回撤    : HK${max_drawdown([e['equity'] for e in eq if e['equity']]):,.0f}")
    if not n:
        print("暫時未有已平倉交易")
        return
    pts = [t["points"] for t in trades]
    wins = [p for p in pts if p > 0]
    losses = [p for p in pts if p <= 0]
    gross = sum(pts) * pv
    print(f"已平倉交易  : {n} 次（勝 {len(wins)}／負 {len(losses)}，勝率 {len(wins) / n:.0%}）")
    print(f"總點數      : {sum(pts):+.0f} 點 = HK${gross:+,.0f}（未扣佣金）")
    if wins:
        print(f"平均賺      : {sum(wins) / len(wins):+.1f} 點")
    if losses:
        print(f"平均蝕      : {sum(losses) / len(losses):+.1f} 點")
    if wins and losses and sum(losses) != 0:
        print(f"盈虧比      : {abs(sum(wins) / sum(losses)):.2f}")
    print(f"交易點數回撤: {max_drawdown([sum(pts[:i + 1]) for i in range(n)]):.0f} 點")
    by_day = defaultdict(float)
    for t in trades:
        by_day[t["ts"][:10]] += t["points"] * pv
    print("\n每日（毛利）:")
    for d, v in sorted(by_day.items()):
        print(f"  {d}  HK${v:+,.0f}")
    print("\n平倉原因統計:")
    reasons = defaultdict(lambda: [0, 0.0])
    for t in trades:
        key = t["reason"].split("：")[0].split(" ")[0]
        reasons[key][0] += 1
        reasons[key][1] += t["points"]
    for k, (c, p) in sorted(reasons.items(), key=lambda x: -x[1][0]):
        print(f"  {k:<12} {c:>3} 次  {p:+.0f} 點")


def ai_stats():
    dec = load("decisions")
    if not dec:
        return
    acts = defaultdict(int)
    rej = sum(1 for d in dec if d.get("rejected"))
    tin = sum((d.get("usage") or {}).get("in", 0) for d in dec)
    tout = sum((d.get("usage") or {}).get("out", 0) for d in dec)
    for d in dec:
        acts[d.get("ai_action")] += 1
    print(f"\nAI 決策 {len(dec)} 次：" + "，".join(f"{k} {v}" for k, v in acts.items()))
    print(f"被風控否決 {rej} 次；Token 用量 輸入 {tin:,}／輸出 {tout:,}")


def futu_report(days):
    from datetime import datetime, timedelta
    from broker import FutuBroker
    from rules import HKT
    b = FutuBroker(CFG)
    try:
        end = datetime.now(HKT)
        start = end - timedelta(days=days)
        ret, df = b.trade.history_deal_list_query(start=start.strftime("%Y-%m-%d %H:%M:%S"),
                                                  end=end.strftime("%Y-%m-%d %H:%M:%S"),
                                                  trd_env=b.env, acc_id=b.acc_id)
        if ret != 0:
            print("富途查詢失敗:", df)
            return
        df = df[df["code"].str.match(rf"^HK\.{CFG.product}\d{{4}}$")].sort_values("create_time")
        pos, avg, realized, n = 0, 0.0, 0.0, 0
        per_code = {}
        for _, r in df.iterrows():
            code = r["code"]
            pos, avg = per_code.get(code, (0, 0.0))
            q = int(r["qty"]) * (1 if str(r["trd_side"]).startswith("BUY") else -1)
            px = float(r["price"])
            if pos == 0 or (pos > 0) == (q > 0):
                avg = (avg * abs(pos) + px * abs(q)) / (abs(pos) + abs(q))
                pos += q
            else:
                close_q = min(abs(q), abs(pos))
                realized += (px - avg) * close_q * (1 if pos > 0 else -1)
                n += 1
                pos += q
                if pos == 0:
                    avg = 0.0
                elif (pos > 0) != (pos - q > 0):
                    avg = px
            per_code[code] = (pos, avg)
        print(f"\n=== 富途成交紀錄（近 {days} 日）===")
        print(f"成交 {len(df)} 筆，平倉 {n} 次，已實現 {realized:+.0f} 點 = HK${realized * CFG.point_value:+,.0f}（未扣佣金）")
    finally:
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--futu", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    summarize([t for t in load("trades") if t["type"] == "CLOSE"], load("equity"))
    ai_stats()
    if a.futu:
        futu_report(a.days)
