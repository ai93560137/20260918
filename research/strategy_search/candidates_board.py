"""🌌 天覆陣 候選總表（排行榜）：將各影子前向報告嘅最新數字放喺同一張表，方便揀「下一條上實倉」。

使用者 11-07（經總指揮）：「全力集中資源去開發天覆」；總指揮排第 1 項。只讀各 *_FORWARD.md 等報告，唔重新計、唔落單、唔寫 GCS。
轉實倉規矩（使用者 11-05）：影子滿 30 張達標先提案；固定細注；一次只上一條；總指揮 dry-run＋使用者批。
用法：python3 research/strategy_search/candidates_board.py → research/strategy_search/CANDIDATES.md（每日影子前向之後跑）
"""
import datetime as dt
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# (IDEAS, 名稱, 檔案, 揀法, 目標張數, 備註)
# 揀法："sec1"＝第一個 ## 段入面第一行「N 張 平均…」；"row:<名>"＝表格嗰行嘅最後一個 n= 欄；"line:<字>"＝含呢段字嗰行
CANDS = [
    ("#160", "rev15 學生 E6S4 1R", "research/student_offline/E6S4_FORWARD.md", "row:rev15", 30, "11-07 已達標，使用者話「等」"),
    ("#160", "rev15x 學生 E6S4 1R", "research/student_offline/E6S4_FORWARD.md", "row:rev15x", 30, ""),
    ("#160", "level 學生 E6S4 1R", "research/student_offline/E6S4_FORWARD.md", "row:level", 30, ""),
    ("#160", "swing 學生 E6S4 1R", "research/student_offline/E6S4_FORWARD.md", "row:swing", 30, "11-07 ❌（②④唔過）"),
    ("#163", "G7 H1 回調（934）", "research/strategy_search/FORWARD_out.md", "grow:G7_h1_pullback", 30, ""),
    ("#163", "G1 H4 Donchian", "research/strategy_search/FORWARD_out.md", "grow:G1_h4_donchian", 30, ""),
    ("#163", "G6 上週高低", "research/strategy_search/FORWARD_out.md", "grow:G6_prevweek", 30, ""),
    ("#220", "921＋Z1 H1 ZGL 過濾", "research/strategy_search/PINE_ZGL_B.md", "line:Z1 順勢", 30, "921 影子決策重播"),
    ("#212", "921 止蝕止賺 1.5×", "research/strategy_search/WIDEN_921.md", "line:- 1.5×：", 30, "要高過 1.0× ≥0.10R"),
    ("#238", "921 B1 規則執行", "research/strategy_search/B1_FORWARD.md", "line:| B1 |", 60, "11-05 20:00 UTC 起"),
    ("#227b", "935 A+＋H4 雙向過濾", "research/strategy_search/H4_APLUS_FORWARD.md", "sec1", 30, "對照 A+ 同期"),
    ("#214", "935 A+＋TTM", "research/strategy_search/TTM_FORWARD.md", "sec1", 30, "到期 2027-11-01"),
    ("#190", "935 改良出場", "research/strategy_search/EXITS_FORWARD.md", "sec1", 30, "到期 2027-11-01"),
    ("#194", "935＋白銀", "research/strategy_search/SILVER_FORWARD.md", "sec1", 30, "到期 2027-11-01"),
    ("#208", "935＋內包線突破", "research/strategy_search/CANDLE_FORWARD.md", "sec1", 30, "到期 2027-11-01"),
    ("#184", "組合 A（多倉）", "research/strategy_search/PORTFOLIO_FORWARD.md", "sec_acc", 30, "到期 2027-11-01"),
    ("#177", "日線 B", "research/strategy_search/B_FORWARD.md", "sec_acc", 20, "到期 20 張或 2027-11-01"),
    ("#218", "DAN 走咗訊號限價", "research/strategy_search/DAN_LATE_LIMIT.md", "line:限價成交", 15, ""),
]

PAT_N = re.compile(r"(\d+) 張 平均 ([+-]?\d+\.\d+)R PF (\S+)")
PAT_EQ = re.compile(r"n=(\d+)(?: 平均 ([+-]?\d+\.\d+)R ΣR \S+ PF (\S+) 連敗 (\d+))?")
PAT_ZERO = re.compile(r"(?:^|- )0 張")


def parse_line(s):
    m = PAT_N.search(s)
    if m:
        return {"n": int(m.group(1)), "avg": float(m.group(2)), "pf": m.group(3)}
    m = PAT_EQ.search(s)
    if m:
        return {"n": int(m.group(1)), "avg": float(m.group(2)) if m.group(2) else None,
                "pf": m.group(3), "lose": int(m.group(4)) if m.group(4) else None}
    if PAT_ZERO.search(s) or re.search(r"\| 0 張 \|", s):
        return {"n": 0}
    return None


def extract(text, how):
    lines = text.splitlines()
    if how.startswith("row:") or how.startswith("grow:"):
        key = how.split(":", 1)[1]
        for ln in lines:
            if ln.startswith(f"| {key} |"):
                cells = [c.strip() for c in ln.strip("|").split("|")]
                col = cells[3] if how.startswith("row:") else cells[2]   # E6S4：新結構欄；G：全部欄
                return parse_line(col)
        return None
    if how.startswith("line:"):
        key = how.split(":", 1)[1]
        for ln in lines:
            if key in ln:
                seg = ln.split(key, 1)[1] if key.endswith("：") or "順勢" in key else ln
                r = parse_line(seg)
                if r:
                    return r
        return None
    if how == "sec1":
        seen = 0
        for ln in lines:
            if ln.startswith("## "):
                seen += 1
                if seen > 1:
                    break
            elif seen == 1:
                r = parse_line(ln) if ("張" in ln and ln.startswith("- ")) else None
                if r:
                    return r
        return None
    if how == "sec_acc":
        on = False
        for ln in lines:
            if ln.startswith("## 累計"):
                on = True
            elif on and ln.startswith("- "):
                r = parse_line(ln)
                if r:
                    return r
                if "已平倉 0 張" in ln:
                    return {"n": 0}
        return None
    return None


def main():
    rows = []
    for idea, name, path, how, need, note in CANDS:
        fp = os.path.join(ROOT, path)
        if not os.path.exists(fp):
            rows.append((idea, name, None, need, note + "（報告未有）"))
            continue
        text = open(fp, encoding="utf-8").read()
        m = re.search(r"更新[：: ]*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", text) or re.search(r"到 (?:2026-)?(\d{2}-\d{2} \d{2}:\d{2})", text)
        upd = m.group(1) if m else "—"
        r = extract(text, how)
        rows.append((idea, name, r, need, (note + "；" if note else "") + f"報告 {upd}"))

    def key(row):
        r = row[2] or {}
        n = r.get("n") or 0
        return (-(1 if n >= row[3] else 0), -n / row[3], -(r.get("avg") or -9) if n else 9)
    out = ["# 🌌 天覆陣 候選總表（影子前向）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；資料＝各前向報告最新一次結果（只讀，唔重計）",
           "- 轉實倉規矩（使用者 11-05）：影子滿目標張數＋照 IDEAS 預先登記標準達標先提案；固定細注（每張風險 ≤1% 或 0.01–0.05 手）；一次只上一條；"
           "總指揮 dry-run＋使用者批。下表只係排序參考，唔係判決（判決以各 IDEAS 登記為準）。", "",
           "| IDEAS | 候選 | 張數／目標 | 平均 R | PF | 連敗 | 備註 |", "|---|---|---|---|---|---|---|"]
    for idea, name, r, need, note in sorted(rows, key=key):
        if r is None:
            out.append(f"| {idea} | {name} | 讀唔到 | — | — | — | {note} |")
            continue
        n = r.get("n") or 0
        flag = "✅ 夠數" if n >= need else ""
        avg = f"{r['avg']:+.3f}" if r.get("avg") is not None else "—"
        out.append(f"| {idea} | {name} | {n}／{need} {flag} | {avg} | {r.get('pf') or '—'} | "
                   f"{r.get('lose') if r.get('lose') is not None else '—'} | {note} |")
    out += ["", "- 排序：夠數嘅排先，之後按完成比例（張數／目標）；張數少（< 10）嘅平均 R 唔可靠。", ""]
    open(os.path.join(HERE, "CANDIDATES.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
