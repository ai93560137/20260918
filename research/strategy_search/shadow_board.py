"""[IDEAS #1028／#1049] 影子總表：5 條合格規則＋#1049 價位回測合併（只前向）（933 rev15 E6S4、#1011 整數關口、#1017 rev60、#1022 D1 20 日突破、#1026 月尾做多）
同所有組合（2 條或以上，共 26 個）嘅影子前向，每張固定 1R、規則同各自回測完全一樣。只係紙上：唔落單。
數據：MT5 M1 存檔（2026-09-01→10-30，只作預熱）接券商 M1（xau/sig/bars/）；入場時間 ≥ START 先計。
各條自己嘅前向判決照各自 IDEAS（#1011／#1017／#1022／#1026；933 係實倉）；組合只作描述，唔另設判決（#1027 三條組合會標明）。
D1／月尾嘅單如果未完，用最新收市價計（標「未完」）。
用法：python3 research/strategy_search/shadow_board.py [--start 2026-11-08T23:00] [--write]
--write：寫 GCS xau/sig/shadow_board/latest.json（zhuge-xau 網頁「🔬 前向測試」讀）。"""
import datetime as dt
import itertools
import json
import os
import sys

import numpy as np

ARGV = list(sys.argv)            # rev15_session 匯入時會改 sys.argv，先保存
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import asia_sweep as A          # noqa: E402
import round_e6s4 as RD         # noqa: E402
import batch_1015 as B15        # noqa: E402
import batch_1019 as B19        # noqa: E402
import batch_1023 as B23        # noqa: E402
import combo_1027 as C          # noqa: E402
import level_pool as LP         # noqa: E402
import batch_1067 as B67        # noqa: E402
import batch_1083 as B83        # noqa: E402
import h1_lab3 as H3            # noqa: E402
import h1_lab4 as H4            # noqa: E402
import h1_lab5 as H5            # noqa: E402
import h1_lab6 as H6            # noqa: E402
import h1_lab7 as H7            # noqa: E402
import h1_lab8 as H8            # noqa: E402

START = "2026-11-08T23:00"
OUT = "xau/sig/shadow_board/latest.json"
STRATS = [("rev15", "933 rev15 E6S4（實倉同時有影子）", "#1001／#160", C.rev15, 0),
          ("round", "50 美元整數關口 E6S4", "#1011", RD.run, 0),
          ("rev60", "rev60 E6S4", "#1017", B15.r1017, 0),
          ("d1brk", "D1 20 日突破", "#1022", B19.r1022, 7 * 86400),
          ("mend", "月尾做多", "#1026", B23.r1026, 5 * 86400),
          ("lvlpool", "價位回測合併（只前向，冇回測判）", "#1049", LP.r1049, 0),
          ("spike", "M1 單根急動反向 E6S4", "#1067", B67.r1067, 0),
          ("ema60", "偏離 EMA60 ≥ 6 美元反向 E6S4（同急動家族重疊 87–94%，唔入組合）", "#1083", B83.r1083, 0),
          ("wkbrk", "上週高／低突破（星期二至四；做多為主）", "#1096", H3.r1096, 0),
          ("d10brk", "10 日高／低突破（做多為主，同 #1096 同家族）", "#1102", H4.r1102, 0),
          ("w52brk", "52 週收市新高／低（持 20 日；做多為主）", "#1105", H5.r1105, 0),
          ("qbrk", "上季高／低突破（張數少）", "#1107", H6.r1107, 0),
          ("lvbrk", "低波幅 20 日突破（張數少）", "#1113", H7.r1113, 0),
          ("mobrk", "月初三日區間突破", "#1114", H8.r1114, 0),
          ("turtle2", "海龜系統 2（55 日突破、20 日出場；做多為主）", "#1116", H8.r1116, 0)]
COMBO_KEYS = ("rev15", "round", "rev60", "d1brk", "mend", "spike")   # 6 條回測合格規則嘅 63 個組合（使用者 11-08「63 個組合回測同影子都做」）；#1049 唔入
OVERLAP = (("rev15", "rev60"), ("rev15", "spike"), ("rev60", "spike"))   # 高度重疊：rev15＋rev60 約 80%、rev15＋急動約 54–65%
COMBO_1027 = ("rev15", "round", "d1brk")


def load_data():
    import e6s4_forward as ef
    import fit_rules as fr
    hist = A.load("mt5", "2026-09-01", "2026-10-30")
    br = ef.broker_bars(fr.ts_of("2026-10-31"))
    m = br["t"] > hist["t"][-1]
    return {k: np.r_[hist[k], br[k][m]] for k in ("t", "o", "h", "l", "c")}


def stats(tr):
    r = np.array([x[2] for x in sorted(tr)], float)
    if not len(r):
        return {"n": 0, "sum": 0.0, "avg": None, "pf": None, "mdd": 0.0, "streak": 0}
    w, ls = r[r > 0].sum(), -r[r < 0].sum()
    eq = np.cumsum(r)
    s = mx = 0
    for x in r:
        s = s + 1 if x < 0 else 0; mx = max(mx, s)
    return {"n": int(len(r)), "sum": round(float(r.sum()), 2), "avg": round(float(r.mean()), 3),
            "pf": (round(float(w / ls), 2) if ls > 0 else None), "mdd": round(float((np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max()), 2),
            "streak": mx}


def main():
    import fit_rules as fr
    start = ARGV[ARGV.index("--start") + 1] if "--start" in ARGV else START
    t0 = fr.ts_of(start)
    d = load_data()
    last = int(d["t"][-1])
    trades, singles = {}, []
    for key, name, idea, fn, hold in STRATS:
        tr = [(int(ts), int(sg), float(r)) for ts, sg, r in fn(d) if ts >= t0]
        trades[key] = tr
        st = stats(tr)
        recent = [{"utc": dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%m-%d %H:%M"), "side": "BUY" if sg > 0 else "SELL",
                   "r": round(r, 2), "open": bool(hold and ts + hold > last)} for ts, sg, r in tr[-5:][::-1]]
        singles.append({"key": key, "name": name, "idea": idea, **st, "recent": recent})
    combos = []
    keys = list(COMBO_KEYS)
    for k in range(1, len(keys) + 1):
        for sub in itertools.combinations(keys, k):
            st = stats([x for s in sub for x in trades[s]])
            combos.append({"keys": list(sub), "name": "＋".join(sub), "is_1027": sub == COMBO_1027,
                           "overlap": any(a in sub and b in sub for a, b in OVERLAP), **st})
    meta = {"run_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), "start": start,
            "bars_to": dt.datetime.fromtimestamp(last, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")}
    res = {"meta": meta, "singles": singles, "combos": combos,
           "criteria": "⚠＝組合含 rev15／rev60／M1 急動任何兩條（高度重疊，等於同一訊號落多倍注）；各條 30 張判（#1011／#1017：平均 ≥ +0.10R、PF ≥ 1.3、連敗 ≤ 6；#1022：PF ≥ 1.2、連敗 ≤ 8；#1026：PF ≥ 1.2、連敗 ≤ 6；#1067：同 #1011）；組合只作描述；一次只上一條實倉"}
    f = lambda x, p="{:+.2f}": "—" if x is None else p.format(x)  # noqa: E731
    out = ["# 影子總表：5 條規則同所有組合（IDEAS #1028）", "", f"- 更新 {meta['run_utc']} UTC；由 {start} UTC 起；K 線到 {meta['bars_to']} UTC；每張 1R；唔落單", "",
           "## 單條", "", "| 規則 | IDEAS | 張 | ΣR | 平均 | PF | 最大回撤 | 連敗 |", "|---|---|---|---|---|---|---|---|"]
    out += [f"| {s['name']} | {s['idea']} | {s['n']} | {f(s['sum'])} | {f(s['avg'], '{:+.3f}')} | {f(s['pf'], '{:.2f}')} | {s['mdd']:.2f} | {s['streak']} |" for s in singles]
    out += ["", "## 63 個組合（含單條；每張 1R 相加；⭐＝#1027 預先登記組合；⚠＝含高度重疊規則：rev15／rev60／M1 急動任何兩條）", "", "| 組合 | 張 | ΣR | 平均 | PF | 最大回撤 |", "|---|---|---|---|---|---|"]
    out += [f"| {'⭐ ' if c['is_1027'] else ''}{'⚠ ' if c['overlap'] else ''}{c['name']} | {c['n']} | {f(c['sum'])} | {f(c['avg'], '{:+.3f}')} | {f(c['pf'], '{:.2f}')} | {c['mdd']:.2f} |" for c in combos]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "SHADOW_BOARD.md"), "w", encoding="utf-8").write(md)
    if "--write" in ARGV:
        sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
        import gb_rulesim as gb
        gb.Gcs().write(OUT, json.dumps(res, ensure_ascii=False), "application/json")
        print(f"已寫 GCS {OUT}")


if __name__ == "__main__":
    main()
