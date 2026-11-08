"""[IDEAS #1045–#1048] 第八批：價位回測 → E6S4 返原方向（同 #1039／#1042 同一邏輯，換四個未測過嘅價位；離開門檻固定 5 美元）。
#1045 前日中位（前日高低平均）；#1046 倫敦開市價（07:00 UTC，07:00–19:59 有效）；#1047 紐約開市價（13:30 UTC，13:30–19:59 有效）；#1048 亞洲區間中位（00–06:59，07:00–19:59 有效）。
收市離開價位 ≥ 5 美元之後第一次返到 → 由上面返落嚟就喺價位下 6 美元做多（由下面就做空）；E6S4（ai_entry_forward.sim）；每日每價位一次。成本每張 0.5 美元。
門檻 5 美元係因為 #1039／#1042（10 美元）Duka 張數唔夠而揀，唔係睇成績揀；預先寫明。
用法：python3 research/strategy_search/batch_1045.py → research/strategy_search/BATCH_1045.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import batch_1033 as B33        # noqa: E402
import batch_1037 as B37        # noqa: E402
import batch_1041 as B41        # noqa: E402

A = B33.A
AWAY = 5.0


def r1045(d):
    out = []; ds = B37.days(d["t"])
    for (ps, pe), (s, e) in zip(ds[:-1], ds[1:]):
        lvl = (d["h"][ps:pe].max() + d["l"][ps:pe].min()) / 2
        x = B41.revisit(d, s, e, lvl, AWAY, s)
        if x:
            out.append(x)
    return out


def at_time(d, sec_from, sec_to, lvl_fn):
    t = d["t"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        idx = np.nonzero((sod[s:e] >= sec_from) & (sod[s:e] < sec_to))[0] + s
        if not len(idx):
            continue
        lvl, i0 = lvl_fn(d, s, e, idx)
        if lvl is None:
            continue
        x = B41.revisit(d, s, idx[-1] + 1, lvl, AWAY, i0)
        if x:
            out.append(x)
    return out


def r1046(d):
    def f(d, s, e, idx):
        return (d["o"][idx[0]], idx[0] + 1) if d["t"][idx[0]] % 86400 < 7 * 3600 + 300 else (None, None)
    return at_time(d, 7 * 3600, 20 * 3600, f)


def r1047(d):
    def f(d, s, e, idx):
        return (d["o"][idx[0]], idx[0] + 1) if d["t"][idx[0]] % 86400 < 13 * 3600 + 1800 + 300 else (None, None)
    return at_time(d, 13 * 3600 + 1800, 20 * 3600, f)


def r1048(d):
    t = d["t"]; sod = t % 86400; out = []
    for s, e in B37.days(t):
        ai = np.nonzero(sod[s:e] < 7 * 3600)[0] + s
        li = np.nonzero((sod[s:e] >= 7 * 3600) & (sod[s:e] < 20 * 3600))[0] + s
        if len(ai) < 300 or not len(li):
            continue
        lvl = (d["h"][ai].max() + d["l"][ai].min()) / 2
        x = B41.revisit(d, s, li[-1] + 1, lvl, AWAY, li[0])
        if x:
            out.append(x)
    return out


def main():
    duka = A.load("duka", "2015-01-01", "2022-12-31")
    mt5 = A.load("mt5", "2023-01-01", "2026-10-30")
    out = ["# 第八批：價位回測 → E6S4（IDEAS #1045–#1048）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；離開門檻 5 美元；每張扣 0.5 美元", ""]
    for name, fn in (("#1045 前日中位回測", r1045), ("#1046 倫敦開市價回測", r1046), ("#1047 紐約開市價回測", r1047), ("#1048 亞洲區間中位回測", r1048)):
        td, tm = fn(duka), fn(mt5)
        ok, lines, _, _ = B33.judge(td, tm, 300, 150)
        out += [f"## {name}", "", *lines, *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
                "- **判：" + ("✅ 達標 → 只提案影子前向（唔落單）" if all(ok.values()) else "❌ 唔達") + "**", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "BATCH_1045.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
