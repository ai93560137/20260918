"""[IDEAS #229] 921「B1」規則執行影子前向（使用者 11-05「登記 B1 做 #229 開始計」）。
樣本外：2026-11-05 20:00 UTC 之後嘅 921 決定。計法同 #228（ai_zone_921.replay，B1／B0 一字不改）。
判（預先登記）：見 IDEAS #229。用法：python3 research/strategy_search/b1_forward.py → B1_FORWARD.md"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ai_zone_921 as Z  # noqa: E402
import filter_921 as F  # noqa: E402

START = int(dt.datetime(2026, 11, 5, 20, 0, tzinfo=dt.timezone.utc).timestamp())
NEED = 60


def max_losing(rs):
    m = c = 0
    for r in rs:
        c = c + 1 if r < 0 else 0
        m = max(m, c)
    return m


def hk(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%m-%d %H:%M")


def main():
    g = F.gb.Gcs()
    decs = [d for d in F.load_decisions(g) if d[0] >= START]
    out = ["# 921 B1 規則執行影子前向（IDEAS #229）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；樣本外由 2026-11-05 20:00 UTC 起；"
           "決策日誌每日 04:57 UTC 先寫上一日，所以遲一日", "",
           "- B1：下一分鐘市價入、止蝕＝AI 止蝕位再推遠 1 美元、止賺＝規則 2R、AI 唔准干預、24 小時到鐘；B0＝現行（AI 止蝕／止賺）", ""]
    if not decs:
        out += ["- 未有新決定。", ""]
        res = {"B1": [], "B0": []}
    else:
        m1 = F.EF6.broker_bars(int(decs[0][0]) - 3600)
        res = {v: Z.replay(m1, decs, v)[0] for v in ("B1", "B0")}
    b1 = [x[2] for x in res["B1"]]; b0 = [x[2] for x in res["B0"]]
    s1, s0 = F.summ(b1), F.summ(b0)
    n = len(b1)
    out += [f"- 決定 {len(decs)} 個；B1 已完 {n}／{NEED} 張", "",
            "| 組 | 結果 | 最大連敗 |", "|---|---|---|",
            f"| B1 | {F.fmt(s1)} | {max_losing(b1)} |", f"| B0 現行（同期對照） | {F.fmt(s0)} | {max_losing(b0)} |", ""]
    if res["B1"]:
        out += ["## 逐張（B1）", "", "| # | 入場 UTC | 方向 | R |", "|---|---|---|---|"]
        out += [f"| {i + 1} | {hk(t)} | {'多' if s > 0 else '空'} | {r:+.2f} |" for i, (t, s, r) in enumerate(res["B1"])]
        out.append("")
    if n >= NEED:
        h1, h2 = F.summ(b1[:n // 2]), F.summ(b1[n // 2:])
        ok = {"①≥60張": True, "②平均R≥+0.10": s1["avg"] >= 0.10, "③PF≥1.2": s1["pf"] >= 1.2,
              "④高過B0≥0.10R": s1["avg"] - s0["avg"] >= 0.10, "⑤最大連敗≤8": max_losing(b1) <= 8,
              "⑥前後半都>0": h1["avg"] > 0 and h2["avg"] > 0}
        out += ["## 判（預先登記 IDEAS #229）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- " + ("✅ 達標 → 只出提案（B1 執行模式 env 預設關；轉真倉固定細注、一次一條；PR＋總指揮 dry-run＋使用者批）"
                        if all(ok.values()) else "❌ 唔達：" + "、".join(k for k, v in ok.items() if not v) + "；唔用、寫原因"), ""]
    else:
        out += [f"- 未夠 {NEED} 張，未判（到期 2027-01-31）。", ""]
    open(os.path.join(HERE, "B1_FORWARD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
