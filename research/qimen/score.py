"""測市判升跌評分表 v1（知識庫第十三節，使用者 2026-11-13 批准）嘅程式版。

評分表內容（十干剋應吉凶、入墓、擊刑、門迫、月令旺衰）由知識庫 kb.json 讀入，唔寫死喺 repo：
  python3 scripts/gcp_agent.py cat --object qimen/kb/kb.json > kb.json

總分＝時干宮 ×2＋生門宮＋戊宮；≥ +2 升、≤ −2 跌、其餘棄權；時干係甲（伏吟局）一律棄權。
程式化時寫死嘅細節（評分表原文冇講，2026-11-13 預先登記 #10003 時定）：
  1. 「吉門」＝開、休、生、景。吉門得宮生或門宮比和 +0.5；門剋宮（門迫，任何門）−1；吉門被宮剋 −0.5。
  2. 十干剋應、入墓、擊刑：用神係干（時干、戊）就用嗰個干；用神係生門就用該宮主天盤干。地盤干用該宮地盤干。
  3. 天芮、天禽同宮：兩粒星都計（−1＋1＝0）。
  4. 月令旺衰：時干宮用時干五行（甲算木），生門、戊都算土；旺、相 +0.5，囚、死 −0.5，休 0。
  5. 空亡只用時空；用神落空亡宮，該宮分數 ×0.5。
  6. 乙入墓只計乾6。
"""
import json

WX = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土", "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
GONG_WX = {1: "水", 2: "土", 3: "木", 4: "木", 6: "金", 7: "金", 8: "土", 9: "火"}
DOOR_WX = {"開門": "金", "驚門": "金", "休門": "水", "生門": "土", "死門": "土", "傷門": "木", "杜門": "木", "景門": "火"}
DOOR_PT = {"開門": 2, "休門": 2, "生門": 2, "景門": 1, "死門": -2, "傷門": -2, "驚門": -2, "杜門": -1}
STAR_PT = {"天輔": 1, "天心": 1, "天禽": 1, "天任": 1, "天衝": 0.5, "天蓬": -1, "天芮": -1, "天柱": -1, "天英": -0.5}
GOD_PT = {"值符": 1, "九天": 1, "六合": 0.5, "太陰": 0.5, "九地": 0.5, "白虎": -1, "玄武": -1, "螣蛇": -0.5}
JI_MEN = {"開門", "休門", "生門", "景門"}
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
ZHI_GONG = {"子": 1, "丑": 8, "寅": 8, "卯": 3, "辰": 4, "巳": 4, "午": 9, "未": 2, "申": 2, "酉": 7, "戌": 6, "亥": 6}
MONTH_WX = {"寅": "木", "卯": "木", "巳": "火", "午": "火", "辰": "土", "未": "土", "戌": "土", "丑": "土",
            "申": "金", "酉": "金", "亥": "水", "子": "水"}
JX = {"大吉": 2, "吉": 1, "平": 0, "凶": -1, "大凶": -2}


def jx_point(text):
    for key in ("大吉", "大凶"):
        if text.startswith(key):
            return JX[key]
    if text[0] in "吉凶平":
        return JX[text[0]]
    tail = text.split("，")[-1]                    # 例如「戰格，凶」「移蕩，凶」
    return JX[tail[0]]


def load_kb(path):
    k = json.load(open(path, encoding="utf-8"))
    return {"ke": {a: jx_point(v["吉凶"]) for a, v in k["十干剋應（天+地）"].items()},
            "mu": {g: int(str(v)[0]) for g, v in k["入墓宮"].items()},      # 乙「6（一說2）」→ 6
            "xing": k["六儀擊刑宮"], "ling": k["月令旺衰"]}


def gong_of(pan, gan):
    """天盤干落宮（包括跟天芮嘅中五寄干）。"""
    for p, g in pan["宮"].items():
        if g["天"] == gan or g["寄天"] == gan:
            return p
    raise ValueError(gan)


def gong_score(pan, p, gan, wx, kb, month_zhi):
    """p 宮分數；gan＝用嚟計十干剋應、入墓、擊刑嘅天盤干；wx＝用神五行（計月令）。回傳（分數, 明細）。"""
    g = pan["宮"][p]
    d = {"門": DOOR_PT[g["門"]], "星": STAR_PT[g["星"]] + (STAR_PT["天禽"] if g["禽"] else 0), "神": GOD_PT[g["神"]]}
    dw, gw = DOOR_WX[g["門"]], GONG_WX[p]
    if KE[dw] == gw:
        d["門宮"] = -1                              # 門迫
    elif g["門"] in JI_MEN and KE[gw] == dw:
        d["門宮"] = -0.5                            # 吉門受制
    elif g["門"] in JI_MEN and (SHENG[gw] == dw or gw == dw):
        d["門宮"] = 0.5
    else:
        d["門宮"] = 0
    d["十干"] = kb["ke"][gan + g["地"]]
    d["入墓"] = -1 if kb["mu"].get(gan) == p else 0
    d["擊刑"] = -1 if kb["xing"].get(gan) == p else 0
    ling = kb["ling"][MONTH_WX[month_zhi]]
    state = next(s for s, w in ling.items() if w == wx)
    d["月令"] = {"旺": 0.5, "相": 0.5, "休": 0, "囚": -0.5, "死": -0.5}[state]
    total = sum(d.values())
    if p in {ZHI_GONG[z] for z in pan["空亡支"]}:
        d["空亡"] = "×0.5"
        total *= 0.5
    return total, d


def score(pan, shi, month_zhi, kb):
    """回傳 dict：call（升／跌／棄權）、總分、三宮明細。"""
    if shi[0] == "甲":
        return {"call": "棄權", "總分": None, "原因": "伏吟局"}
    out, total = {}, 0.0
    p = gong_of(pan, shi[0])
    s, d = gong_score(pan, p, shi[0], WX[shi[0]], kb, month_zhi)
    out["時干宮"] = (p, s, d)
    total += 2 * s
    p = next(q for q, g in pan["宮"].items() if g["門"] == "生門")
    s, d = gong_score(pan, p, pan["宮"][p]["天"], "土", kb, month_zhi)
    out["生門宮"] = (p, s, d)
    total += s
    p = gong_of(pan, "戊")
    s, d = gong_score(pan, p, "戊", "土", kb, month_zhi)
    out["戊宮"] = (p, s, d)
    total += s
    out["總分"] = total
    out["call"] = "升" if total >= 2 else "跌" if total <= -2 else "棄權"
    return out
