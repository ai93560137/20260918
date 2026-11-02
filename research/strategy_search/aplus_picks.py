"""[R365 A+ 維護] 每年重揀 A+（935）七個成份參數：同 #184／#208 滾動前向規則一樣（前 4 年、≥ 20 張、PF ≥ 1.1、揀平均 R 最高）。
用法：python3 research/strategy_search/aplus_picks.py [年份]（預設下一年）→ 印出每個成份揀法，同 xau/combo_live.py 現行寫死參數比較。
2027-01 要做：跑呢個腳本（數據要包到 2026-12）→ 如果揀法變咗就改 combo_live.py（COMPONENTS／family_side）＋ config COMBO_PARAM_YEAR，
經總指揮 dry-run＋使用者批先部署；揀法冇變都要改 COMBO_PARAM_YEAR（唔改 935 唔開新倉）。"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import candle_ind as CI  # noqa: E402
import d1_indicators as Q  # noqa: E402
import h4_indicators as H  # noqa: E402
import portfolio as P  # noqa: E402
import robust2 as S2  # noqa: E402
import robust_long as R  # noqa: E402

LIVE_2026 = {"1 D1 Keltner 突破": {"ex": 2}, "2 D1 拋物線 SAR": {"filt": True, "ex": 2}, "3 D1 威廉 %R": {"th": 20, "filt": True, "ex": 2},
             "4 H4 MACD": {"filt": True, "ex": 1}, "5 H4 拋物線 SAR": {"filt": True, "ex": 1}, "6 星期效應": {"w": 4, "dir": 1},
             "7 D1 內包線突破": {"filt": True, "ex": 2}}


def main():
    R.COST = 0.5
    year = int(sys.argv[1]) if len(sys.argv) > 1 else dt.date.today().year + 1
    import b_forward as BF
    arr, n_new = BF.load_h1()
    D1, D4, DW = Q.DI(*arr), H.H4I(*arr), S2.D2(*arr)
    last = dt.datetime.fromtimestamp(int(arr[0][-1]), dt.timezone.utc)
    print(f"# A+ {year} 年參數（訓練 {year - 4}–{year - 1}；數據到 {last:%Y-%m-%d %H:%M} UTC）")
    if last.year < year - 1 or (last.year == year - 1 and last.month < 12):
        print(f"⚠ 數據未包齊 {year - 1} 年（到 {last:%Y-%m}），結果只供預覽")
    defs = [("1 D1 Keltner 突破", "J5 Keltner 突破", D1, 480), ("2 D1 拋物線 SAR", "J7 拋物線 SAR 轉向", D1, 480),
            ("3 D1 威廉 %R", "J8 威廉 %R 極端回歸", D1, 480), ("4 H4 MACD", "J2 MACD 交叉", D4, 80), ("5 H4 拋物線 SAR", "J7 拋物線 SAR 轉向", D4, 80)]
    changed = False
    for name, fam, D, th in defs:
        grid = Q.FAMILIES[fam]
        def fn(p, D=D, fam=fam, th=th):
            Q.T_H = th
            return Q.run(D, fam, p)
        _, pk = P.wf_stream(fn, grid, years=[year]); g = pk[year]
        pick = None if g is None else grid[g]; changed |= pick != LIVE_2026[name]
        print(f"- {name}：{pick if pick is not None else '唔做（訓練過唔到）'}｜2026 真倉 {LIVE_2026[name]}{'' if pick == LIVE_2026[name] else ' ⚠ 唔同'}")
    g6 = S2.FAMILIES["S2 星期效應"]
    _, pk = P.wf_stream(lambda p: S2.s2(DW, p), g6, years=[year]); pick = None if pk[year] is None else g6[pk[year]]
    changed |= pick != LIVE_2026["6 星期效應"]
    print(f"- 6 星期效應：{pick}｜2026 真倉 {LIVE_2026['6 星期效應']}{'' if pick == LIVE_2026['6 星期效應'] else ' ⚠ 唔同'}")
    cg = CI.FAMILIES["C3 內包線突破"]; Q.T_H = 480
    T = [CI.run(D1, "C3 內包線突破", p, 480) for p in cg]
    _, pk = P.wf_stream(lambda p: T[cg.index(p)], cg, years=[year]); pick = None if pk[year] is None else cg[pk[year]]
    changed |= pick != LIVE_2026["7 D1 內包線突破"]
    print(f"- 7 D1 內包線突破：{pick}｜2026 真倉 {LIVE_2026['7 D1 內包線突破']}{'' if pick == LIVE_2026['7 D1 內包線突破'] else ' ⚠ 唔同'}")
    print("→ " + ("有成份揀法變咗：要改 combo_live.py＋COMBO_PARAM_YEAR（總指揮 dry-run＋使用者批）" if changed else f"揀法同 2026 一樣：只要改 SIG_COMBO_PARAM_YEAR={year}（總指揮 env set＋使用者批）"))


if __name__ == "__main__":
    main()
