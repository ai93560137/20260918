"""大股災探索：由節氣局抽特徵（只作探索，唔係驗證；見 PREREG「大股災：探索同樣本外驗證」）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import DOOR_WX, GONG_WX, KE, SHENG, ZHI_GONG, gong_of

MU = {"乙": 6, "丙": 6, "戊": 6, "丁": 8, "己": 8, "庚": 8, "辛": 4, "壬": 4, "癸": 2}
XING = {"戊": 3, "己": 2, "庚": 8, "辛": 9, "壬": 4, "癸": 4}
JI_MEN, XIONG_MEN = {"開門", "休門", "生門"}, {"死門", "驚門", "傷門"}
JI_XING, XIONG_XING = {"天輔", "天心", "天任"}, {"天蓬", "天芮", "天柱"}
XIONG_SHEN = {"白虎", "玄武", "螣蛇"}
OPP = {1: 9, 9: 1, 2: 8, 8: 2, 3: 7, 7: 3, 4: 6, 6: 4}


def features(q):
    """q＝qiju() 回傳；回傳 {特徵名: bool}。"""
    pan = q["盤"]
    G = pan["宮"]
    kong = {ZHI_GONG[z] for z in pan["空亡支"]}
    nian, yue, ri, shi = (x[0] for x in q["四柱"].replace("年", "").replace("月", "").replace("日", "").replace("時", "").split())
    f = {"伏吟（甲時）": shi == "甲"}
    fu = next(p for p, g in G.items() if g["神"] == "值符")
    f["星返吟"] = any(g["星"] == s and OPP[p] == h for p, g in G.items()
                    for s, h in (("天蓬", 1), ("天任", 8), ("天衝", 3), ("天輔", 4), ("天英", 9), ("天芮", 2), ("天柱", 7), ("天心", 6)))
    xing_t = [p for p, g in G.items() for x in (g["天"], g["寄天"]) if x and XING.get(x) == p]
    xing_d = [p for p, g in G.items() if XING.get(g["地"]) == p]
    mu_t = [p for p, g in G.items() for x in (g["天"], g["寄天"]) if x and MU.get(x) == p]
    f["盤有擊刑（天盤）"] = bool(xing_t)
    f["盤有擊刑（地盤）"] = bool(xing_d)
    f["盤有入墓（天盤）"] = bool(mu_t)

    def gong_feats(tag, p, gan=None):
        g = G[p]
        dw, gw = DOOR_WX[g["門"]], GONG_WX[p]
        f[f"{tag}：落空亡"] = p in kong
        f[f"{tag}：凶門"] = g["門"] in XIONG_MEN
        f[f"{tag}：吉門"] = g["門"] in JI_MEN
        f[f"{tag}：死門"] = g["門"] == "死門"
        f[f"{tag}：凶星"] = g["星"] in XIONG_XING
        f[f"{tag}：吉星"] = g["星"] in JI_XING
        f[f"{tag}：天芮"] = g["星"] == "天芮"
        f[f"{tag}：凶神"] = g["神"] in XIONG_SHEN
        f[f"{tag}：白虎"] = g["神"] == "白虎"
        f[f"{tag}：門迫"] = KE[dw] == gw
        f[f"{tag}：宮有擊刑"] = p in xing_t or p in xing_d
        f[f"{tag}：宮有入墓"] = p in mu_t
        f[f"{tag}：凶門＋落空"] = g["門"] in XIONG_MEN and p in kong
        f[f"{tag}：凶門或凶星＋落空"] = (g["門"] in XIONG_MEN or g["星"] in XIONG_XING) and p in kong
        f[f"{tag}：凶門＋凶星"] = g["門"] in XIONG_MEN and g["星"] in XIONG_XING
        if gan:
            f[f"{tag}：干入墓"] = MU.get(gan) == p
            f[f"{tag}：干擊刑"] = XING.get(gan) == p
        for n in (1, 2, 3, 4, 6, 7, 8, 9):
            f[f"{tag}：落{n}宮"] = p == n

    gong_feats("戊宮", gong_of(pan, "戊"), "戊")
    gong_feats("值符宮", fu)
    gong_feats("生門宮", next(p for p, g in G.items() if g["門"] == "生門"))
    gong_feats("開門宮", next(p for p, g in G.items() if g["門"] == "開門"))
    for tag, gan in (("年干宮", nian), ("日干宮", ri), ("時干宮", shi)):
        gan = pan["旬首儀"] if gan == "甲" else gan
        gong_feats(tag, gong_of(pan, gan), gan)
    pw, pm = gong_of(pan, "戊"), next(p for p, g in G.items() if g["門"] == "生門")
    f["戊宮剋生門宮"] = KE[GONG_WX[pw]] == GONG_WX[pm]
    f["生門宮剋戊宮"] = KE[GONG_WX[pm]] == GONG_WX[pw]
    f["戊同生門同宮"] = pw == pm
    for j in ("陽遁2局", "陽遁5局", "陽遁8局"):
        f[f"局：{j}"] = q["局"] == j
    return f
