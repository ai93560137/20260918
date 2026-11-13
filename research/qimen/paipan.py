"""時家奇門轉盤排盤（核對用）：由「陰／陽遁、局數、時干支」排出九宮。

只做排盤，唔做曆法（四柱、節氣、定局由使用者起局時提供）。規則：轉盤、中五寄坤二、天禽隨天芮。
每宮輸出跟記錄格式：八神/門+天盤干/星+地盤干。

用法：python3 research/qimen/paipan.py 陽 4 乙酉
"""
import sys

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
YIQI = "戊己庚辛壬癸丁丙乙"                      # 地盤排干次序
XUN = {0: ("甲子", "戊", "戌亥"), 10: ("甲戌", "己", "申酉"), 8: ("甲申", "庚", "午未"),
       6: ("甲午", "辛", "辰巳"), 4: ("甲辰", "壬", "寅卯"), 2: ("甲寅", "癸", "子丑")}
RING = [1, 8, 3, 4, 9, 2, 7, 6]                    # 順時針宮序
STAR = {1: "天蓬", 8: "天任", 3: "天衝", 4: "天輔", 9: "天英", 2: "天芮", 7: "天柱", 6: "天心"}
DOOR = {1: "休門", 8: "生門", 3: "傷門", 4: "杜門", 9: "景門", 2: "死門", 7: "驚門", 6: "開門"}
GODS = ["值符", "螣蛇", "太陰", "六合", "白虎", "玄武", "九地", "九天"]
MA = {"申": 8, "子": 8, "辰": 8, "寅": 2, "午": 2, "戌": 2, "巳": 6, "酉": 6, "丑": 6, "亥": 4, "卯": 4, "未": 4}
NAME = {1: "坎1", 2: "坤2", 3: "震3", 4: "巽4", 5: "中5", 6: "乾6", 7: "兌7", 8: "艮8", 9: "離9"}


def paipan(yang, ju, shi):
    g, z = GAN.index(shi[0]), ZHI.index(shi[1])
    if g % 2 != z % 2:
        raise ValueError(f"干支唔成立：{shi}")
    step = g                                        # 由旬首到用時行咗幾個時辰
    xun_name, yi, kong = XUN[(z - g) % 12]
    # 地盤
    di = {}
    for i, q in enumerate(YIQI):
        p = (ju - 1 + (i if yang else -i)) % 9 + 1
        di[p] = q
    pos = {q: p for p, q in di.items()}
    home = lambda p: 2 if p == 5 else p             # 中五寄坤二
    fu_from = home(pos[yi])                         # 旬首（值符）原宮
    shi_gan = yi if shi[0] == "甲" else shi[0]       # 甲時用旬首儀
    fu_to = home(pos[shi_gan])
    # 天盤：星連同原宮地盤干順時針轉
    shift = RING.index(fu_to) - RING.index(fu_from)
    tian, star = {}, {}
    for i, p in enumerate(RING):
        t = RING[(i + shift) % 8]
        star[t] = STAR[p] + ("(禽)" if p == 2 else "")
        tian[t] = di[p] + (f"({di[5]})" if p == 2 else "")
    # 八門：值使由旬首原宮按時辰數行宮（陽順陰逆，過中五寄坤二）
    shi_from = pos[yi]
    shi_to = home((shi_from - 1 + (step if yang else -step)) % 9 + 1)
    dshift = RING.index(shi_to) - RING.index(home(shi_from))
    door = {RING[(i + dshift) % 8]: DOOR[p] for i, p in enumerate(RING)}
    # 八神：值符神跟值符星，陽順時針、陰逆時針
    god = {RING[(RING.index(fu_to) + (i if yang else -i)) % 8]: s for i, s in enumerate(GODS)}
    pan = {p: f"{god[p]}/{door[p]}{tian[p]}/{star[p]}{di[p]}" for p in RING}
    pan[5] = di[5]
    return {"旬首": xun_name + yi, "空亡": kong, "馬星": NAME[MA[shi[1]]],
            "值符": f"{STAR[fu_from]}落{fu_to}宮", "值使": f"{DOOR[home(shi_from)]}落{shi_to}宮", "盤": pan}


def show(r):
    print(f"旬首 {r['旬首']}｜空亡 {r['空亡']}｜馬星 {r['馬星']}｜值符 {r['值符']}｜值使 {r['值使']}")
    for row in ((4, 9, 2), (3, 5, 7), (8, 1, 6)):
        print("　".join(f"{NAME[p]}:{r['盤'][p]}" for p in row))


if __name__ == "__main__":
    show(paipan(sys.argv[1].startswith("陽"), int(sys.argv[2]), sys.argv[3]))
