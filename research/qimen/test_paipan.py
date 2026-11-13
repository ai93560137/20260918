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

# qiju.py：知識庫例局（2004-12-22 酉時，中環；18:00 HKT＝10:00 UTC，經度 114.16°E）
from datetime import datetime, timezone
from qiju import qiju
q = qiju(datetime(2004, 12, 22, 10, 0, tzinfo=timezone.utc), 114.16)
assert q["四柱"] == "甲申年 丙子月 乙亥日 乙酉時" and q["節氣"] == "冬至" and q["元"] == "下元" and q["局"] == "陽遁4局", q
assert q["盤"]["盤"] == want
print("qiju ok")

# 2026-11-13 12:47 UTC（英國）：真太陽時 13:04＝乙未時；App 用時鐘 12:47＝甲午時（已同使用者 App 逐宮核對）
q = qiju(datetime(2026, 11, 13, 12, 47, tzinfo=timezone.utc), 0.25)
assert q["四柱"].endswith("辛卯日 乙未時") and q["局"] == "陰遁3局" and q["App盤"]["日時"] == "辛卯日 甲午時", q
assert q["App盤"]["盤"]["盤"][9] == "值符/景門辛/天英辛" and q["App盤"]["盤"]["馬星"] == "坤2"
assert qiju(datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc), 0.25)["App盤"] is None
print("app-diff ok")

# 2026-11-13 App 15:05 丙申時（時干落中五寄坤二），已同使用者 App 逐宮核對
z = paipan(False, 3, "丙申")
assert z["盤"] == {4: "太陰/生門戊/天衝乙", 9: "螣蛇/傷門乙/天輔辛", 2: "值符/杜門辛/天英己", 3: "六合/休門壬/天任戊", 5: "丙",
                   7: "九天/景門己(丙)/天芮(禽)癸", 8: "白虎/開門庚/天蓬壬", 1: "玄武/驚門丁/天心庚", 6: "九地/死門癸/天柱丁"}, z
assert z["值使"] == "景門落7宮" and z["馬星"] == "艮8"
print("app 丙申 ok")

# score.py：第一卦正式計分 QR-20261113-1（陰遁 3 局 庚子時 亥月）人手計係 −5／+2／+3，總分 −5 → 跌
# 要知識庫 kb.json（私人 GCS）；冇就跳過。
import os as _os
_kb = _os.environ.get("QIMEN_KB")
if _kb and _os.path.exists(_kb):
    from score import load_kb, score
    r = score(paipan(False, 3, "庚子"), "庚子", "亥", load_kb(_kb))
    assert (r["時干宮"][0], r["時干宮"][1]) == (9, -5) and (r["生門宮"][0], r["生門宮"][1]) == (6, 2) and (r["戊宮"][0], r["戊宮"][1]) == (7, 3), r
    assert r["總分"] == -5 and r["call"] == "跌"
    assert score(paipan(False, 3, "甲午"), "甲午", "亥", load_kb(_kb))["call"] == "棄權"
    print("score ok")
else:
    print("score 測試跳過（未設 QIMEN_KB）")
