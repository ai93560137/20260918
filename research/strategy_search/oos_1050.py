"""[IDEAS #1050] 未見數據驗證：Dukascopy M1 2010–2014（之前全部研究都冇用過），規則同各自回測完全一樣（固定美元，冇縮放、冇改參數）。
規格、成功標準以 IDEAS #1050 預先登記為準（數據到之前已 commit）。
組 A（已合格，確認）：rev15（933）、#1011、#1017、#1022、#1026。
組 B（差少少／平均正但未過，第二次機會）：#1016、#1033、#1038、#1039、#1042、#1045、#1046、#1047、#1048、#1049（合併）。
成功（每條獨立）：2010–2014 平均 R ≥ +0.05、PF ≥ 1.10、張數 ≥ N（日線／月尾 30，其他 100）、5 年 ≥ 3 年正數。
組 A 唔過 → 標「⚠ 未見數據唔確認」，前向照做但提案時要講；組 B 過 → 只可以加入影子總表做前向（唔會因此直接上實倉）。
用法：python3 research/strategy_search/oos_1050.py → research/strategy_search/OOS_1050.md"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import round_e6s4 as RD         # noqa: E402
import combo_1027 as C          # noqa: E402
import batch_1015 as B15        # noqa: E402
import batch_1019 as B19        # noqa: E402
import batch_1023 as B23        # noqa: E402
import batch_1033 as B33        # noqa: E402
import batch_1037 as B37        # noqa: E402
import batch_1041 as B41        # noqa: E402
import batch_1045 as B45        # noqa: E402
import level_pool as LP         # noqa: E402
import batch_1067 as B67        # noqa: E402

GROUP_A = [("rev15（933）", C.rev15, 100), ("#1011 整數關口", RD.run, 100), ("#1017 rev60", B15.r1017, 100),
           ("#1022 D1 20 日突破", B19.r1022, 30), ("#1026 月尾做多", B23.r1026, 30),
           ("#1067 M1 單根急動（11-08 18:5x 加入，數據未到）", B67.r1067, 100)]
GROUP_B = [("#1016 25 美元關口", B15.r1016, 100), ("#1033 rev15 順 D1", lambda d: B33.r1033(d)[0], 100),
           ("#1038 亞洲高低 E6S4", B37.r1038, 100), ("#1039 開市價回測", B37.r1039, 100), ("#1042 前日收市回測", B41.r1042, 100),
           ("#1045 前日中位回測", B45.r1045, 100), ("#1046 倫敦開市價回測", B45.r1046, 100), ("#1047 紐約開市價回測", B45.r1047, 100),
           ("#1048 亞洲中位回測", B45.r1048, 100), ("#1049 價位回測合併", LP.r1049, 100)]


def main():
    d = A.load("duka", "2010-01-01", "2014-12-31")
    out = ["# 未見數據驗證：Dukascopy 2010–2014（IDEAS #1050）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；規則同各自回測一樣（固定美元）；每張扣 0.5 美元", ""]
    for gname, grp in (("組 A：已合格（確認）", GROUP_A), ("組 B：差少少（第二次機會）", GROUP_B)):
        out += [f"## {gname}", "", "| 規則 | 成績 | 每年平均 R | 判 |", "|---|---|---|---|"]
        for name, fn, nmin in grp:
            tr = fn(d)
            st = A.stats([x[2] for x in tr]); yd = A.by_year(tr)
            pos = sum(1 for v in yd.values() if v["n"] and v["avg"] > 0)
            ok = st["n"] >= nmin and st["avg"] >= 0.05 and st["pf"] >= 1.10 and pos >= 3
            yrs = "；".join(f"{y} {v['avg']:+.2f}（{v['n']}）" for y, v in yd.items() if v["n"])
            out.append(f"| {name} | {A.fmt(st)} | {yrs} | {'✅' if ok else '❌'} |")
        out.append("")
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "OOS_1050.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
