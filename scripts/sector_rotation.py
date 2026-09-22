#!/usr/bin/env python3
"""版塊輪動檢測（多市場；描述性監測工具，不是策略、不產生交易訊號）。

在 point-in-time 指數成分股宇宙（universe.py：恒指/S&P 500/Nasdaq-100/道指/日經225）
上建三類「組」的等權指數，看資金往哪裡轉：
1. **行業**：yfinance sector（各市場同一套 11 類，跨市場可比；每日 QC 順便抓；已下市
   抓不到的用手動補缺檔，報告標明來源）。
   ⚠ 是「今天的分類」套用到歷史——公司轉型（如 0001 長實→長和）會被歸錯年代，
   這個偏差寫進報告。
2. **指數公司分類**（有才有）：恒指 Wikipedia 當年快照的四大類（金融/公用/地產/工商），
   point-in-time 正確但太粗，當交叉核對。
3. **風格籃子**（每月底在當時成分股裡重選約 1/10 檔數，全部只用當時已知數據）：
   高息（滾動 12 個月股息率）、低波（252 日波動最低）、動量（12-1 個月報酬）、
   大市值（股數×收市）。

指數構造：每月最後一個交易日按 point-in-time 名單定組員，組內**每日等權**
（當日組員 AdjClose 日報酬平均，含股息）；組員中途停牌/下市就從那天起不計。
基準：指數 ETF（2800.HK/SPY/QQQ/DIA/1321.T，市值加權）與「全體成分股等權」——
相對等權才是乾淨的版塊輪動（相對市值加權基準會混入大小盤效應）。

輸出（sector/<index>/）：
- ROTATION_REPORT.md：最新 1/3/6/12 個月超額、排名、排名變化、廣度、年度輪動表
- group_index.csv：各組日指數（給後續研究/畫圖）
- tg_rotation.txt：Telegram 摘要

**紀律**：這個工具只描述「過去誰強誰弱」，不回答「強的會不會繼續強」——
那是版塊動量策略的問題，必須先預註冊（SECTOR_ROTATION.md）再用回測引擎測，
不能拿這份報告的數字反覆看來挑參數。

    python3 scripts/sector_rotation.py                      # 預設恒指
    python3 scripts/sector_rotation.py --index sp500
    python3 scripts/sector_rotation.py --as-of 2024-12-31   # 看歷史某一天
"""
import argparse
import bisect
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from stock_momentum_backtest import (  # noqa: E402
    derive_dividends, load_series, load_shares, month_end_dates, shares_asof, trailing_vol,
)
from universe import INDICES, Universe  # noqa: E402

OUT_ROOT = ROOT / "sector"
WINDOWS = [("1M", 21), ("3M", 63), ("6M", 126), ("12M", 252)]
MIN_MEMBERS = 3          # 組員少於此數：結果標「薄」，別過度解讀

SECTOR_ZH = {
    "Financial Services": "金融", "Real Estate": "地產", "Utilities": "公用",
    "Technology": "科技", "Communication Services": "通訊/互聯網",
    "Consumer Cyclical": "非必需消費", "Consumer Defensive": "必需消費",
    "Energy": "能源", "Basic Materials": "原材料", "Industrials": "工業",
    "Healthcare": "醫療",
}
OFFICIAL_ZH = {"Finance": "金融", "Utilities": "公用", "Properties": "地產", "Commerce & Industry": "工商"}
STYLE_ZH = {"divyield": "高息", "lowvol": "低波", "momentum": "動量", "largecap": "大市值"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", default="hsi", choices=list(INDICES))
    ap.add_argument("--as-of", type=date.fromisoformat, default=None, help="報告日（預設最新交易日）")
    ap.add_argument("--start", type=date.fromisoformat, default=date(2010, 6, 30))
    args = ap.parse_args()

    uni = Universe(args.index)
    BENCH = uni.benchmark
    STYLE_K = uni.cfg["style_k"]
    OUT_DIR = OUT_ROOT / args.index
    official = uni.official_sectors()
    sec_map, sec_src = uni.sectors()

    series, shares, divs = {}, {}, {}
    for t in uni.all_tickers(since=args.start - timedelta(days=400)) + [BENCH]:
        try:
            series[t] = load_series(t)
        except FileNotFoundError:
            continue
        if t != BENCH:
            shares[t] = load_shares(t)
            divs[t] = derive_dividends(series[t])
    if BENCH not in series:
        raise SystemExit(f"沒有基準 {BENCH} 的數據")
    first_date = {t: min(s) for t, s in series.items() if s}
    daily = {t: sorted((d, v[1]) for d, v in s.items()) for t, s in series.items()}
    daily_dates = {t: [d for d, _ in rows] for t, rows in daily.items()}

    cal = sorted(series[BENCH])
    as_of = args.as_of or cal[-1]
    cal = [d for d in cal if max(args.start, uni.first_date()) <= d <= as_of]
    m_ends = month_end_dates(cal)
    cal_idx = {d: i for i, d in enumerate(cal)}

    def adj_close(t: str, d: date) -> float | None:
        v = series[t].get(d)
        return v[1] if v and v[1] > 0 else None

    # --- 每月底決定各組組員 ---
    groups_by_month: dict[date, dict[str, list[str]]] = {}
    member_slots = hole_slots = 0
    for me in m_ends:
        # point-in-time 名單 + 防代碼重用（價格須早於入選日存在）+ 當天有價
        listed = uni.members_at(me)
        mem = {t for t in uni.eligible_at(me, first_date) if adj_close(t, me)}
        if not mem:
            continue
        member_slots += len(listed)
        hole_slots += len(listed) - len(mem)
        g: dict[str, list[str]] = defaultdict(list)
        g["全體等權"] = sorted(mem)
        for t in mem:
            g["行業:" + SECTOR_ZH.get(sec_map.get(t, ""), sec_map.get(t) or "未分類")].append(t)
            # 指數公司分類（恒指）：用 <= 當年最近一年的分類（現行名單期間沒有當年快照）
            snap_year = me.year if me >= date(me.year, 6, 30) else me.year - 1
            yrs = [y for y in official.get(t, {}) if int(y) <= snap_year]
            hs = official[t][max(yrs)] if yrs else None
            if hs:
                g["官方分類:" + OFFICIAL_ZH.get(hs, hs)].append(t)
        # 風格籃子
        dy, lv, mo, cap = [], [], [], []
        me_skip = m_ends[m_ends.index(me) - 1] if m_ends.index(me) >= 1 else None
        me_lb = m_ends[m_ends.index(me) - 13] if m_ends.index(me) >= 13 else None
        for t in mem:
            raw = series[t][me][2]
            if first_date[t] <= me - timedelta(days=365):
                ttm = sum(x for d, x in divs[t] if me - timedelta(days=365) < d <= me)
                if ttm > 0 and raw > 0:
                    dy.append((ttm / raw, t))
            v = trailing_vol(daily[t], daily_dates[t], me, 252)
            if v is not None:
                lv.append((-v, t))
            if me_skip and me_lb and adj_close(t, me_skip) and adj_close(t, me_lb):
                mo.append((adj_close(t, me_skip) / adj_close(t, me_lb) - 1, t))
            sh = shares.get(t)
            n = shares_asof(sh, me) if sh else None
            if n:
                cap.append((raw * n, t))
        for key, sc in (("divyield", dy), ("lowvol", lv), ("momentum", mo), ("largecap", cap)):
            if len(sc) >= STYLE_K:
                sc.sort(reverse=True)
                g["風格:" + STYLE_ZH[key]] = sorted(t for _, t in sc[:STYLE_K])
        groups_by_month[me] = dict(g)

    # --- 每日等權指數（月底換組員；當天組員中有前後兩天價格者的日報酬平均）---
    names = sorted({k for g in groups_by_month.values() for k in g})
    level = {k: 1.0 for k in names}
    index_rows: list[tuple[date, dict[str, float | None]]] = []
    started: set[str] = set()
    me_list = sorted(groups_by_month)
    for mi, me in enumerate(me_list):
        end = me_list[mi + 1] if mi + 1 < len(me_list) else cal[-1]
        days = cal[cal_idx[me]:cal_idx[end] + 1]
        groups = groups_by_month[me]
        for d0, d1 in zip(days, days[1:]):
            row = {}
            for k in names:
                mem = groups.get(k)
                if not mem:
                    row[k] = level[k] if k in started else None
                    continue
                rets = [adj_close(t, d1) / adj_close(t, d0) - 1 for t in mem
                        if adj_close(t, d0) and adj_close(t, d1)]
                if rets:
                    started.add(k)
                    level[k] *= 1 + sum(rets) / len(rets)
                row[k] = level[k] if k in started else None
            b0, b1 = adj_close(BENCH, d0), adj_close(BENCH, d1)
            level.setdefault(BENCH, 1.0)
            if b0 and b1:
                level[BENCH] *= b1 / b0
            row[BENCH] = level[BENCH]
            index_rows.append((d1, row))

    dates = [d for d, _ in index_rows]
    lvl = {k: [r.get(k) for _, r in index_rows] for k in names + [BENCH]}

    def ret_over(k: str, n: int, end_i: int | None = None) -> float | None:
        e = len(dates) - 1 if end_i is None else end_i
        s = e - n
        if s < 0 or lvl[k][e] is None or lvl[k][s] is None:
            return None
        return lvl[k][e] / lvl[k][s] - 1

    last_me = me_list[-1]
    cur_groups = groups_by_month[last_me]
    e_now = len(dates) - 1
    e_prev = bisect.bisect_right(dates, dates[-1] - timedelta(days=30)) - 1  # 約一個月前

    def breadth(mem: list[str]) -> float | None:
        ok = above = 0
        for t in mem:
            i = bisect.bisect_right(daily_dates[t], as_of)
            closes = [c for _, c in daily[t][max(0, i - 200):i]]
            if len(closes) < 200:
                continue
            ok += 1
            above += closes[-1] > sum(closes) / len(closes)
        return above / ok if ok else None

    def ranking(end_i: int, n: int, prefix: str) -> dict[str, int]:
        vals = [(ret_over(k, n, end_i), k) for k in names if k.startswith(prefix)
                and len(cur_groups.get(k, [])) >= MIN_MEMBERS]
        vals = sorted([(v, k) for v, k in vals if v is not None], reverse=True)
        return {k: i + 1 for i, (_, k) in enumerate(vals)}

    # --- 報告 ---
    L = []
    L.append(f"# {uni.cfg['name']} 版塊輪動報告（{as_of}）\n")
    L.append(f"宇宙：point-in-time {uni.cfg['name']} 成分股（組員定於 {last_me}，共 {len(cur_groups['全體等權'])} 檔；"
             f"歷史上成分股中 {hole_slots / max(member_slots, 1):.1%} 的月份檔次沒有可用價格——倖存者偏差洞）。"
             "各組每日等權、含股息。超額 = 組報酬 − 基準報酬。**描述性，不是交易訊號**"
             "（見 scripts/sector_rotation.py 開頭的紀律說明）。\n")

    def table(prefix: str, title: str) -> None:
        rk_now = ranking(e_now, 63, prefix)
        rk_prev = ranking(e_prev, 63, prefix)
        rows = [k for k in names if k.startswith(prefix) and k in cur_groups]
        rows.sort(key=lambda k: rk_now.get(k, 99))
        L.append(f"\n## {title}\n")
        L.append("| 組 | 檔數 | " + " | ".join(f"{w} 超額vs等權" for w, _ in WINDOWS)
                 + f" | 3M 超額vs{BENCH} | 3M排名(一個月前) | 廣度(>200日線) |")
        L.append("|---|---|" + "---|" * (len(WINDOWS) + 3))
        for k in rows:
            mem = cur_groups[k]
            cells = []
            for _, n in WINDOWS:
                r, b = ret_over(k, n), ret_over("全體等權", n)
                cells.append(f"{(r - b) * 100:+.1f}%" if r is not None and b is not None else "—")
            r3, b3 = ret_over(k, 63), ret_over(BENCH, 63)
            vs_b = f"{(r3 - b3) * 100:+.1f}%" if r3 is not None and b3 is not None else "—"
            now, prev = rk_now.get(k), rk_prev.get(k)
            if now and prev:
                arrow = "↑" if now < prev else ("↓" if now > prev else "→")
                rk = f"{now}({prev}){arrow}"
            else:
                rk = "薄" if len(mem) < MIN_MEMBERS else "—"
            br = breadth(mem)
            label = k.split(":", 1)[-1]
            L.append(f"| {label} | {len(mem)} | " + " | ".join(cells)
                     + f" | {vs_b} | {rk} | {f'{br:.0%}' if br is not None else '—'} |")

    table("行業:", "行業（yfinance sector）")
    table("風格:", "風格籃子（每月底在當時成分股裡選 10 檔）")
    if official:
        table("官方分類:", "指數公司分類（當年快照，交叉核對用）")

    # 全體/基準參考
    L.append("\n## 基準參考\n")
    L.append("| | " + " | ".join(w for w, _ in WINDOWS) + " |")
    L.append("|---|" + "---|" * len(WINDOWS))
    for k, lab in (("全體等權", "全體成分股等權"), (BENCH, f"{BENCH}（市值加權指數 ETF）")):
        L.append(f"| {lab} | " + " | ".join(
            f"{ret_over(k, n) * 100:+.1f}%" if ret_over(k, n) is not None else "—" for _, n in WINDOWS) + " |")

    # 輪動訊號（描述性）：短期排名跟長期排名背離
    L.append("\n## 輪動跡象（1M 超額排名 vs 12M 超額排名，僅行業與風格）\n")
    sigs = []
    for prefix in ("行業:", "風格:"):
        r1, r12 = ranking(e_now, 21, prefix), ranking(e_now, 252, prefix)
        n = len(r1)
        for k in r1:
            if k in r12 and n >= 4:
                if r1[k] <= n // 3 and r12[k] > n - n // 3:
                    sigs.append(f"- ⤴ **{k.split(':')[1]}**：近 1 月第 {r1[k]}/{n}，但 12 月第 {r12[k]}/{n}——落後者轉強")
                elif r12[k] <= n // 3 and r1[k] > n - n // 3:
                    sigs.append(f"- ⤵ **{k.split(':')[1]}**：12 月第 {r12[k]}/{n}，但近 1 月第 {r1[k]}/{n}——領先者轉弱")
    L.extend(sigs or ["- 無明顯背離（短期與長期排名一致）"])
    # 分散度：行業 3M 超額的標準差（高 = 版塊分化大、輪動活躍）
    def dispersion(end_i: int) -> float | None:
        v = [ret_over(k, 63, end_i) for k in names if k.startswith("行業:")
             and len(cur_groups.get(k, [])) >= MIN_MEMBERS]
        v = [x for x in v if x is not None]
        if len(v) < 3:
            return None
        m = sum(v) / len(v)
        return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    disp_hist = [dispersion(i) for i in range(252, len(dates), 21)]
    disp_hist = sorted(x for x in disp_hist if x is not None)
    dn = dispersion(e_now)
    if dn is not None and disp_hist:
        pct = bisect.bisect_left(disp_hist, dn) / len(disp_hist)
        L.append(f"\n行業 3M 報酬分散度 {dn * 100:.1f}%（歷史第 {pct:.0%} 百分位；高 = 版塊分化大、輪動活躍）。")

    # 年度輪動表
    L.append("\n## 年度輪動表（各組當年報酬 − 全體等權，行業與風格）\n")
    years = sorted({d.year for d in dates})
    cols = [k for k in names if k.startswith(("行業:", "風格:"))]
    L.append("| 年 | " + " | ".join(k.split(":")[1] for k in cols) + " | 全體等權 | 第一名 |")
    L.append("|---|" + "---|" * (len(cols) + 2))
    for y in years:
        idx = [i for i, d in enumerate(dates) if d.year == y]
        s_i = idx[0] - 1 if idx[0] > 0 else idx[0]
        e_i = idx[-1]
        def yr(k):
            a, b = lvl[k][s_i], lvl[k][e_i]
            return b / a - 1 if a and b else None
        base = yr("全體等權")
        cells, best = [], None
        for k in cols:
            r = yr(k)
            if r is None or base is None:
                cells.append("—")
                continue
            ex = r - base
            cells.append(f"{ex * 100:+.0f}")
            if best is None or ex > best[0]:
                best = (ex, k.split(":")[1])
        partial = "（年初至今）" if y == as_of.year else ("（下半年）" if y == dates[0].year else "")
        L.append(f"| {y}{partial} | " + " | ".join(cells)
                 + f" | {base * 100:+.0f}% | {best[1] if best else '—'} |" if base is not None else "")
    L.append("\n（單位：百分點。行業組員用今天的 yfinance 分類回溯，早年組員數可能很少。）")

    # 分類來源/偏差
    cur_all = cur_groups["全體等權"]
    all_ever = sorted({t for g in groups_by_month.values() for t in g["全體等權"]})
    n_man = sum(sec_src.get(t) == "manual" for t in all_ever)
    n_none = [t for t in all_ever if t not in sec_map]
    L.append("\n## 分類來源與已知偏差\n")
    L.append(f"- 歷史上曾入宇宙 {len(all_ever)} 檔：yfinance 分類 {sum(sec_src.get(t) == 'yf' for t in all_ever)}、"
             f"手動補 {n_man}（scripts/pointintime/sectors_manual.json）、未分類 {len(n_none)}"
             + (f"（{', '.join(n_none)}）" if n_none else ""))
    L.append("- yfinance 分類是**今天的**，套用到歷史：業務轉型的公司在早年會被歸錯組（前視偏差，"
             "影響描述不影響價格）。" + ("指數公司分類是當年快照，可以對照。" if official else ""))
    L.append(f"- 現行組員不足 {MIN_MEMBERS} 檔的組標「薄」、不參與排名。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "ROTATION_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    with open(OUT_DIR / "group_index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date"] + names + [BENCH])
        for d, r in index_rows:
            w.writerow([d.isoformat()] + [f"{r[k]:.6f}" if r.get(k) is not None else "" for k in names + [BENCH]])

    # Telegram 摘要：行業 3M 超額前三/後三 + 風格 + 輪動跡象
    rk = ranking(e_now, 63, "行業:")
    order = sorted(rk, key=rk.get)
    def ex3(k):
        r, b = ret_over(k, 63), ret_over("全體等權", 63)
        return f"{k.split(':')[1]} {(r - b) * 100:+.1f}%"
    tg = [f"{uni.cfg['name']} 版塊輪動 {as_of}（3個月超額 vs 成分股等權）",
          "強：" + "、".join(ex3(k) for k in order[:min(3, len(order) // 2)]),
          "弱：" + "、".join(ex3(k) for k in order[-min(3, len(order) // 2):]),
          "風格：" + "、".join(ex3(k) for k in sorted(ranking(e_now, 63, "風格:"),
                                                     key=ranking(e_now, 63, "風格:").get))]
    tg += [s.replace("**", "").replace("- ", "", 1) for s in sigs[:4]]
    (OUT_DIR / "tg_rotation.txt").write_text("\n".join(tg) + "\n", encoding="utf-8")
    print("\n".join(tg))
    print(f"-> {OUT_DIR / 'ROTATION_REPORT.md'}")


if __name__ == "__main__":
    main()
