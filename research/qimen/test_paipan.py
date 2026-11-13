"""paipan.py 回歸測試：用知識庫例局（陽遁 4 局 乙酉時）逐宮核對。python3 research/qimen/test_paipan.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paipan import paipan

r = paipan(True, 4, "乙酉")
want = {4: "螣蛇/景門丁/天蓬戊", 9: "太陰/死門壬/天任癸", 2: "六合/驚門乙/天衝丙", 3: "值符/杜門庚/天心乙", 5: "己",
        7: "白虎/開門戊/天輔辛", 8: "九天/傷門辛/天柱壬", 1: "九地/生門丙(己)/天芮(禽)丁", 6: "玄武/休門癸/天英庚"}
assert r["盤"] == want, r["盤"]
assert r["空亡"] == "午未" and r["值符"] == "天心落3宮" and r["值使"] == "開門落7宮", r
# 伏吟：甲子時，星門歸本位
f = paipan(True, 1, "甲子")
assert f["盤"][1].endswith("/休門戊/天蓬戊") and f["值符"] == "天蓬落1宮", f
# 陰遁地盤逆排：陰 9 局 戊9 己8 庚7 辛6 壬5 癸4 丁3 丙2 乙1
y = paipan(False, 9, "甲子")
assert y["盤"][5] == "壬" and y["盤"][9].endswith("天英戊") and y["盤"][1].endswith("天蓬乙"), y
print("ok")
