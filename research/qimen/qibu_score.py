"""七步法（知識庫第十六節）嘅機械化評分：正數偏好、負數偏淡。IDEAS #10007，2026-11-14 預先登記。

七步法原文係定性描述；以下係本陣逐句寫成加減分，**只用原文有寫嘅條件**，冇加探索時見過嘅特徵。
 步一 年干宮：年干五行喺月令旺相 +1、囚死 −1；年干加地盤干嘅十干剋應（大吉 +2、吉 +1、凶 −1、大凶 −2）；落空亡 −1；
            臨開、休、生門 +1，臨死、驚、傷門 −1。
 步二 戊宮：土喺月令旺相 +1、囚死 −1；戊入墓（乾6）−1；落空亡 −1（使用者口述）；吉門 +1／凶門 −1；吉星（輔心任禽）+1／
            凶星（蓬芮柱）−1；臨白虎或玄武 −1；地盤係庚 −1；地盤係乙丙丁（得三奇）+1。
 步三 擊刑：天盤每有一個干擊刑 −0.5；擊刑宮同時臨白虎、螣蛇或玄武，再 −1；戊宮有擊刑再 −1。
 步四 值符、值使：值符宮天盤干入墓 −1；值使門係開門或生門 +1，係死、驚、杜門 −1。
 步五 三門：開門（金）喺月令旺相 +1、囚死 −1；生門宮十干剋應（同步一計法）。景門只講熱度同真假，唔計方向。
 步六 星神：值符星係天心或天輔 +1，係天蓬或天芮 −1。九天、九地、六合原文冇講方向，唔計。
 步七 係對照流程，唔計分。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import MONTH_WX, WX, ZHI_GONG, gong_of

JI_MEN, XIONG_MEN = {"開門", "休門", "生門"}, {"死門", "驚門", "傷門"}
JI_XING, XIONG_XING = {"天輔", "天心", "天任", "天禽"}, {"天蓬", "天芮", "天柱"}


def ling_pt(wx, month_zhi, kb):
    state = next(s for s, w in kb["ling"][MONTH_WX[month_zhi]].items() if w == wx)
    return {"旺": 1, "相": 1, "休": 0, "囚": -1, "死": -1}[state]


def qibu(q, kb):
    """q＝qiju() 回傳。回傳（總分, 各步分數 dict）。"""
    pan, mz = q["盤"], q["月支"]
    G = pan["宮"]
    kong = {ZHI_GONG[z] for z in pan["空亡支"]}
    d = {}
    # 步一
    nian = q["四柱"][0]
    nian = pan["旬首儀"] if nian == "甲" else nian
    p = gong_of(pan, nian)
    g = G[p]
    d["一年干"] = (ling_pt(WX[nian], mz, kb) + kb["ke"][nian + g["地"]] - (p in kong)
                 + (g["門"] in JI_MEN) - (g["門"] in XIONG_MEN))
    # 步二
    p = gong_of(pan, "戊")
    g = G[p]
    stars = {g["星"]} | ({"天禽"} if g["禽"] else set())
    d["二戊"] = (ling_pt("土", mz, kb) - (kb["mu"]["戊"] == p) - (p in kong) + (g["門"] in JI_MEN) - (g["門"] in XIONG_MEN)
               + bool(stars & JI_XING) - bool(stars & XIONG_XING) - (g["神"] in ("白虎", "玄武"))
               - (g["地"] == "庚") + (g["地"] in "乙丙丁"))
    wu_gong = p
    # 步三
    s3 = 0.0
    for p, g in G.items():
        for x in (g["天"], g["寄天"]):
            if x and kb["xing"].get(x) == p:
                s3 -= 0.5
                if g["神"] in ("白虎", "螣蛇", "玄武"):
                    s3 -= 1
                if p == wu_gong:
                    s3 -= 1
    d["三擊刑"] = s3
    # 步四
    fu = next(p for p, g in G.items() if g["神"] == "值符")
    shi_men = pan["值使"][:2]
    d["四值符值使"] = (-(kb["mu"].get(G[fu]["天"]) == fu) + (shi_men in ("開門", "生門")) - (shi_men in ("死門", "驚門", "杜門")))
    # 步五
    sm = next(p for p, g in G.items() if g["門"] == "生門")
    d["五三門"] = ling_pt("金", mz, kb) + kb["ke"][G[sm]["天"] + G[sm]["地"]]
    # 步六
    fx = pan["值符"][:2]
    d["六星神"] = (fx in ("天心", "天輔")) - (fx in ("天蓬", "天芮"))
    return float(sum(d.values())), d
