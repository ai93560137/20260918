#!/usr/bin/env python3
"""HTF 投資人說明書（stock_research/HTF_INVESTOR_BRIEF.md）由研究結果重新產生；再用 tt_all_pdf.py 出 PDF。2026-10-12

    python3 scripts/htf_investor_mix.py && python3 scripts/htf_brief.py && \\
    python3 scripts/tt_all_pdf.py --src stock_research/HTF_INVESTOR_BRIEF.md --title "HTF 高漲旗型 · 港台日美" \\
        --sub "投資人說明書 · 全期參數（曲線擬合版）" --badges "樣本內擬合" "港台日美" "每日訊號"
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
O = ROOT / "research" / "htf_curvefit"
MKS = ["hk", "tw", "jp", "us"]
NM = {"hk": "港股", "tw": "台股", "jp": "日股", "us": "美股"}
ETFN = {"hk": "盈富 2800", "tw": "0050", "jp": "1321", "us": "SPY"}
UNIV = {"hk": "港前 500", "tw": "台前 500", "jp": "日前 1000", "us": "美前 1500"}


def pct(v, d=1):
    return f"{v * 100:+.{d}f}%"


def pc(v, d=0):
    return f"{v * 100:.{d}f}%"


def main() -> None:
    R = {mk: json.load(open(O / f"{mk}.json")) for mk in MKS}
    I = {mk: json.load(open(O / f"investor_{mk}.json")) for mk in MKS}
    X = json.load(open(O / "investor_mix.json"))
    c = X["20%"]["combined"]
    L = ["## 一句話", "",
         "在港台日美四個市場，找近幾個月急升（漲幅在全市場前 1–3%）、之後橫行收窄、成交萎縮的股票（高漲旗型，High Tight Flag）；"
         "股價升穿旗桿頂就用買入停損單入場，按波幅設停損，跌穿均線就走。參數由 2000–2026 全期數據擬合選出。", "",
         "## 投資人先看這張表", "",
         "可執行口徑：每筆用 20% 資金 × 波幅權重，四個市場共用一筆資金，總曝險不超過 100%，扣交易成本。", "",
         "| | 年化回報 | 最大回撤 | RRR | 勝率 | 每筆期望值 | 獲利因子 | 平均持有 | 交易筆數 | 全期擬合 alpha t |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for mk in MKS:
        i, b = I[mk], X["20%"][mk]
        L.append(f"| {NM[mk]}（單獨） | {pct(b['cagr'])} | {pc(b['mdd'])} | {i['rrr']:.2f} | {pc(i['win'])} | {pct(i['expectancy'], 2)} | "
                 f"{i['profit_factor']:.2f} | {i['avg_hold']:.1f} 日 | {i['trades']} | {R[mk]['best_eval']['alpha_t']:.2f} |")
    L.append(f"| **港台日美合併** | **{pct(c['cagr'])}** | **{pc(c['mdd'])}** | — | — | — | — | — | {sum(I[mk]['trades'] for mk in MKS)} | — |")
    L += ["", "同期指數 ETF（買入持有）：" + "；".join(f"{NM[mk]} {ETFN[mk]} 年化 {pct(X['etf'][mk]['cagr'])}、最大回撤 {pc(X['etf'][mk]['mdd'])}" for mk in MKS) + "。", "",
          "- **RRR（盈虧比）** = 平均贏的一筆 ÷ 平均輸的一筆。台股 6.5 倍：勝率只有 24%，但贏一筆抵六筆半的虧損。",
          "- **每筆期望值** = 平均每筆淨回報（已扣成本）。",
          f"- **美股擬合 alpha t 只有 {R['us']['best_eval']['alpha_t']:.2f}**（港台日都 ≥ 2.5），而且最佳參數旁邊的參數全部不到 1.5，屬「孤峰」；使用者要求照樣加入，請把美股當作最弱的一腿。",
          f"- 合併組合按月計 {pc(c['months_pos'])} 的月份賺錢，夏普比率 {c['sharpe']:.2f}；平均只有 {pc(c['avg_exposure'])} 資金在市場，其餘是現金（{c['start'][:4]} 年起，四地都有數據）。", "",
          "## 資金配置與兩個口徑", "",
          "訊號稀疏，所以「每筆放多少」決定了回報和回撤。下表全部是四個市場共用一筆資金：", "",
          "| 每筆資金 | 年化回報 | 最大回撤 | 平均曝險 | 夏普 |", "|---|---:|---:|---:|---:|"]
    for k in ("10%", "20%", "33%"):
        v = X[k]["combined"]
        L.append(f"| {k} × 波幅權重 | {pct(v['cagr'])} | {pc(v['mdd'])} | {pc(v['avg_exposure'])} | {v['sharpe']:.2f} |")
    A = X["backtest_A"]
    L += ["", "研究報告裡的「回測口徑」年化（" + "、".join(f"{NM[mk][0]} {pct(A[mk]['cagr'])}" for mk in MKS) +
          "，最大回撤 " + "／".join(pc(A[mk]['mdd']) for mk in MKS) + "）假設同一時間只有一筆訊號時把全部資金壓在那一隻股票上，"
          "實盤不可能也不應這樣做，只用來比較策略好壞，**不是投資人可得的回報**。", "",
          "## 按年回報（港台日美合併，每筆 20%）", ""]
    ys = list(c["by_year"])
    for k in range(0, len(ys), 9):
        chunk = ys[k:k + 9]
        L += ["| 年份 | " + " | ".join(str(y) for y in chunk) + " |", "|---|" + "---:|" * len(chunk),
              "| 回報 | " + " | ".join(pct(c["by_year"][y], 0) for y in chunk) + " |", ""]
    L += [f"（{c['start'][:4]} 年由 {c['start'][5:]} 起；最後一年至 9 月底。）", "",
          "## 規則（全期參數）", "", "| | " + " | ".join(NM[mk] for mk in MKS) + " |", "|---|" + "---|" * len(MKS)]
    spec = [("旗桿：之前 60 日內最低到旗桿頂的漲幅", "g", lambda v: f"≥ {v:.0%}"), ("旗面：由旗桿頂回落深度", "d", lambda v: f"≤ {v:.0%}"),
            ("旗面成交量 ÷ 旗桿段成交量", "vol", lambda v: "不限" if v is None else f"< {v}"), ("旗面長度", "flag_max", lambda v: f"3–{v} 日"),
            ("動能（21／63／126 日報酬任一）", "mom_q", lambda v: f"全市場前 {100 - v}%"),
            ("大市過濾（指數 ETF 10 日線 > 20 日線且雙升）", "mkt", lambda v: "要" if v else "不用"),
            ("開市追價上限", "chase", lambda v: f"{v:.0%}"), ("最低日均波幅 ADR", "adr_min", lambda v: "不限" if not v else f"{v:.0%}"),
            ("初始停損（成交價下方）", "stop", lambda v: f"{v} × ADR"), ("賣一半", "partial", lambda v: "不賣" if not v else f"第 {v} 日收市"),
            ("出場", "trail", lambda v: f"收市破 {v[2:]} 日線翌日開市賣"), ("最長持有", "hold", lambda v: f"{v} 日"),
            ("倉位", "risk", lambda v: "按波幅" if v else "等權")]
    for name, k, f in spec:
        L.append(f"| {name} | " + " | ".join(f(R[mk]["search"]["best"][k]) for mk in MKS) + " |")
    L += ["", "共通：股票要在 60 日成交額宇宙內（" + "／".join(UNIV[mk] for mk in MKS) + "）、收市在 20 日線上；入場用買入停損單掛在旗桿頂，盤中升穿即成交。", "",
          "## 每日怎樣執行", "",
          "1. 每個交易日香港時間傍晚，系統自動更新四個市場數據，計出下一個交易日的掛單名單與持倉指令，更新網頁並發 Telegram（文字＋PDF）。美股名單當晚開市執行。",
          "2. 掛單：每隻股票一個「觸發價」（旗桿頂）。盤中升穿就買；開市已高過觸發價 × (1 + 追價上限) 就取消。",
          "3. 下單後即設停損（成交價 − 停損倍數 × ADR）。持倉指令每天更新：持有／收市賣一半／翌日開市全賣。",
          "4. 每筆資金 = 20% × 權重（名單的「資金」欄），總曝險不超過 100%。", "",
          "## 風險與限制（請細讀）", "",
          "- **曲線擬合**：參數是用整段歷史數據挑出最好的一組。同一組參數放回同一段歷史，成績一定偏好；未來的實際回報大概率低於上表。",
          "- **獲利集中**：" + "、".join(f"{NM[mk]}前 10 筆佔全部獲利 {pc(I[mk]['top10_share'])}" for mk in MKS) + "。跳過任何一筆訊號都可能錯過大贏家，必須每筆照做。",
          "- **勝率低**：連續虧損十幾筆是正常現象。",
          "- **港股、日股沒有大市過濾**：熊市照樣入場，靠停損控制。",
          "- **成交假設**：回測假設在觸發價成交（或開市價）。實盤滑價、台股漲停鎖死、小型股流動性不足都會令實際成績變差。",
          "- **倖存者偏差**：股票池只含現存股票，已下市的不在內，回測回報偏高。", "",
          "## 證偽條件（出現就停）", "",
          "- 前向 100 筆交易（或 12 個月，先到者為準）每筆平均淨回報 ≤ 0；或",
          f"- 前向最大回撤超過上表合併 20% 配置回撤的 1.5 倍（即 {pc(1.5 * c['mdd'])}）。", ""]
    (ROOT / "stock_research" / "HTF_INVESTOR_BRIEF.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
