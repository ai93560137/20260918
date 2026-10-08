"""方向二在 ES：「高位／低位已出現」之後反向做，賺不賺錢？（盈虧回測，2026-10-09）

與恒指 fade_pnl.py 同一套規則（訊號那根 15 分 K 收市 → 下一根開市進場；止蝕 = 極值 + b×R̂；可選止賺；段末平倉），
市場設定沿用 hl_signal_us.py（CME 全段交易日、C 時間點 12:00／16:00）。成本：每筆來回 0.75 點（ES 一跳 0.25 點 = 12.5 美元，加佣金滑點）。
用法：python3 research/us_futures/fade_us.py [--src usa500] [--cost 0.75] [--periods day,week]
輸出：research/us_futures/fade_us/REPORT.md、summary.json、trades_<kind>.csv（線上參數每筆紀錄，核對用）
"""
import argparse, csv, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "research" / "hsi_futures_range"))
import hl_signal_us as us                                 # noqa: E402  套用美股設定（session_minutes、grid）
import high_low_in as hl                                  # noqa: E402
import fade_pnl as fp                                     # noqa: E402

OUT = HERE / "fade_us"
fp.LIVE = {"day": [("A", 0.8, 0.5), ("B", 0.05), ("C", "16:00", 0.4)],
           "week": [("A", 0.8, 0.5), ("B", 0.05), ("C", 4, 0.4)]}


def grid_us(kind):
    a = [("A", al, be) for al in (0.6, 0.8, 1.0) for be in (0.3, 0.5)]
    b = [("B", p) for p in (0.05, 0.10, 0.20)]
    c = [("C", cut, be) for cut in ({"day": ("12:00", "16:00"), "week": (2, 3, 4)}[kind]) for be in (0.2, 0.4)]
    e = [("E", k) for k in (0.8, 1.0, 1.2)]
    exits = [(sk, tk) for sk in (0.0, 0.1, 0.25) for tk in (None, 0.25, 0.5)]
    return [(s, sk, tk) for s in a + b + c + e for sk, tk in exits]


fp.grid = grid_us


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="usa500", choices=list(us.SRC))
    ap.add_argument("--cost", type=float, default=0.75)
    ap.add_argument("--periods", default="day,week")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    zh, load = us.SRC[a.src]
    bars, daily = load()
    days, _ = us.build_days(bars, daily)
    L = [f"# 方向二在 {zh}：頂底已現 → 反向做（fade_us.py，成本每筆 {a.cost:g} 點）", "",
         f"- {len(days)} 個交易日（{days[0]['date']} 至 {days[-1]['date']}），交易日 = CME 全段；規則與恒指 fade_pnl.py 相同，"
         "A、B、C 訊號同 hl_signal_us.py；E = 已走 ≥ k×R̂ 即反向（不用回落確認）。基準 = 同一段同一邊、在訊號中位時間無條件進場。", ""]
    out = {}
    for kind in a.periods.split(","):
        periods = hl.build_periods(days, kind)
        text, out[kind] = fp.report(periods, kind, a.cost)
        L.append(text)
        with open(OUT / f"trades_{kind}.csv", "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["period", "side", "strat", "net", "exit"])
            for s in fp.LIVE[kind]:
                for side in ("high", "low"):
                    for key, net, why in fp.run(periods, s, side, 0.0, None, a.cost):
                        w.writerow([key, side, fp.name(s, kind), round(net, 2), why])
    (OUT / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    json.dump(out, open(OUT / "summary.json", "w"), ensure_ascii=False, indent=1, default=str)
    print("\n".join(L))


if __name__ == "__main__":
    main()
