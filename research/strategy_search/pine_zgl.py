"""[IDEAS #219／#220／#221] 使用者自己寫嘅 Pine v6「智能諸葛亮發佈版」（ZGL）回測（使用者 11-02「A 同 B 同 C 都做」、「多空都做先睇吓回測結果」）。

指標（照原版參數，唔優化）：src＝hl2；九條 ZLEMA（長度 6、27、48 … 174，step 21）；final＝WMA5(L1−L9)；isUp＝final ≥ 0。
ZLEMA(x,n)＝2·EMA(x,n) − EMA(EMA(x,n),n)。K 線顏色：收 > 開＝陽、收 < 開＝陰。

A（#219）原版邏輯回測，多空都做：
  首單＝isUp 嘅第一根陽燭（做空：非 isUp 嘅第一根陰燭）；加單＝之後每根同色燭（加單間隔 1）；每根最多一個動作；
  出場＝只有反轉（isUp 轉向）平晒；冇止蝕；訊號喺收市判斷、下一根開盤成交；每個單位扣 0.5 美元（來回）。
  損益以每單位（0.01 手＝1 盎司）美元計。變化：加單上限 0（只首單）、5、200（原版）；時框 1m／5m／15m／1h。
  數據：券商 MT5 M1（xau/sig/mt5m1/，2022-08-03→2026-10-30）合成各時框；1h 另用 Dukascopy H1 2017→2026 核對。
  判（每個時框×加單組合各自判，多空合計）：① 每單位平均 ≥ +0.10 美元；② PF ≥ 1.15；③ 2023／2024／2025／2026 ≥ 3/4 年正；
  ④ 前後半（以 2024-09-17 分）都正；⑤（只 1h）Dukascopy H1 2017–2026 ≥ 7/10 年正兼 PF ≥ 1.1。
  另列：只做多／只做空、扣趨勢後（減去同期持倉嘅平均漂移）、最大同時單位數、最大回撤。12 個組合同時測，有多重比較風險。

B（#220）ZGL 方向做 921／933 過濾器，對照 H4 EMA50 斜率（#211／#217 嘅 F1）：
  Z1＝H1 ZGL 方向（已收市 H1）同入場一致先做；Z4＝H4 ZGL 方向（已收市 H4，22:00 UTC 對齊）一致先做；H4S＝H4 EMA50 斜率順勢（對照）。
  樣本：921 B 決策重播（#211 樣本 B）、933 rev15 離線（#217，Dukascopy M1 2026-07-24→10-31）；921 A 真倉只作描述（同 #211 一樣屬樣本內）。
  判（每個 Z 過濾×每個樣本各自）：① 前後半過濾後平均 R 都高過唔過濾 ≥ +0.10R；② 過濾後平均 R ≥ +0.05、PF ≥ 1.1；③ 保留 ≥ 40%；
  ④ 過濾後平均 R 高過 H4S 過濾。

C（#221）「超主升／超主跌」之後點走：
  同原版：每個波段記錄最大加單次數；最近 10 個波段（≥ 3 個）去頭去尾後 μ＋2σ；當前加單次數 > 門檻＝超主升（isUp）／超主跌。
  事件＝每個波段第一次變成超主升／跌嗰根（收市）。前向：順波段方向 10／30／60 根後收市變化 ÷ ATR14；同埋到反轉為止（下一根開盤進、反轉後開盤出）。
  基準＝同方向波段入面加單次數 ≥ 1、但未係超主嘅 K 線（同一個前向計法）。
  判（每個時框各自）：「延續」＝60 根前向平均 > 基準、Welch t ≥ 2、前後半都同號；「力竭」＝60 根前向平均 < 0、t ≤ −2、前後半都同號；否則冇邊。
  另列可交易版：事件下一根開盤進、反轉出、扣 0.5 美元：每單位平均 ≥ +0.10、PF ≥ 1.15、前後半都正先算有用。

任何結果都只係提案，要用落真倉要使用者經總指揮批，建議先影子。
D（#222）M1 改良（使用者 11-03「Pine script m1 有冇辦法變到賺錢策略」）：A 顯示 M1 原版每單位 −0.50＝扣 0.5 成本前約 0，即訊號本身冇方向。
  六個改法（只首單、唔加單；收市判斷下一根開盤；扣 0.5）：
  V1 只做同 H1 ZGL 方向一致嘅 M1 首單（反轉出）；V2 V1＋H4 ZGL 都一致；V3 M1 ATR14 ≥ 1.5 美元（成本 3 倍）先做；
  V4 只做 07:00–20:00 UTC（倫敦＋紐約）；V5 用 M1 做 H1 入場時機：H1 ZGL 轉向之後第一個同向 M1 首單入、H1 ZGL 再轉向先出（每個 H1 波段最多一張）；
  V6 V1＋V3＋V4。
  判（每個改法各自）：① 後半（≥ 2024-09-17，當樣本外）每單位平均 ≥ +0.10、PF ≥ 1.15；② 前半平均 > 0；③ 2023–2026 ≥ 3/4 年正；
  ④ 後半做多同做空平均都 > 0（唔係淨係跟大升市）。另列成本 0.3 美元描述。6 個同時測，有多重比較風險；達標只提案先影子。
E（#223）#220 Z1 穩健度（使用者 11-03「繼續研究」）：
  E1 參數敏感度：帶距 step ∈ {15, 21, 27} × 平滑 ∈ {3, 5, 8}（9 組，原版 21／5），921 B 決策重播 Z1 過濾後平均 R 對唔過濾嘅改善；
  E2 長歷史獨立樣本：#211 樣本 C（隨機入場 2009→，SL 1×H1 ATR、TP 1.5R、24h、扣 0.5），Z1／Z4／H4S 過濾，2017–2026 每年平均 R 有冇改善。
  判（預先登記）：穩健＝① E1 ≥ 7/9 組改善 ≥ +0.10R；② E2 Z1 全期改善 > 0、≥ 7/10 年改善；③ E2 Z1 過濾後平均 R ≥ H4S 過濾後。
  全過 → #220 影子照做、信心加；唔過 → 喺 #220 註明「參數／樣本唔穩」，影子照做但夠 30 張判時要更嚴（Z1 要贏 H4S ≥ +0.10R）。唔改真倉。
用法：python3 research/strategy_search/pine_zgl.py --part A|B|C|D|E → PINE_ZGL_A.md／PINE_ZGL_B.md／PINE_ZGL_C.md／PINE_ZGL_D.md
"""
import argparse
import datetime as dt
import os
import sys

import numpy as np
from scipy.signal import lfilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import robust_long as R  # noqa: E402
import search as S  # noqa: E402
import search2 as W  # noqa: E402

COST = 0.5
STEP, SMOOTH = 21, 5
WARM = 2000
SPLIT = int(dt.datetime(2024, 9, 17, tzinfo=dt.timezone.utc).timestamp())
YEARS = (2023, 2024, 2025, 2026)
TFS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
ADDS = (0, 5, 200)
FWD_TS = int(dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc).timestamp())   # #220 Z1 921 影子前向起點
FWD_N = 30


# ------------------------------------------------------------------ 指標
def ema(x, n):
    a = 2 / (n + 1)
    y, _ = lfilter([a], [1, a - 1], x[1:], zi=[(1 - a) * x[0]])
    return np.r_[x[0], y]


def zlema(x, n):
    e1 = ema(x, n)
    return 2 * e1 - ema(e1, n)


def wma(x, n):
    w = np.arange(1, n + 1, dtype=float)
    out = np.full(len(x), np.nan)
    out[n - 1:] = np.convolve(x, w[::-1], "valid") / w.sum()
    return out


def zgl_up(h, l, step=STEP, smooth=SMOOTH):
    src = (h + l) / 2
    d = zlema(src, 6) - zlema(src, 6 + step * 8)
    f = wma(d, smooth)
    return np.nan_to_num(f, nan=0.0) >= 0


def atr14(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out = np.full(len(tr), np.nan)
    cs = np.cumsum(tr)
    out[13:] = (cs[13:] - np.r_[0, cs[:-14]]) / 14
    return out


def resample(m1, sec):
    if sec == 60:
        return {k: m1[k] for k in ("t", "o", "h", "l", "c")}
    key = m1["t"] // sec * sec
    keys, first = np.unique(key, return_index=True)
    last = np.r_[first[1:], len(key)] - 1
    return {"t": keys, "o": m1["o"][first], "h": np.maximum.reduceat(m1["h"], first),
            "l": np.minimum.reduceat(m1["l"], first), "c": m1["c"][last]}


# ------------------------------------------------------------------ 原版狀態機
def run_zgl(d, max_adds):
    """回傳 entries [(i_bar_signal, side, add_no, wave_id)]、每根 current_adds、up、波段 [(start, end_flip_bar, side)]。"""
    o, c = d["o"], d["c"]
    up = zgl_up(d["h"], d["l"])
    n = len(c)
    green, red = c > o, c < o
    ents = []
    cur = np.zeros(n, dtype=np.int32)
    lt = st = False; lc = sc = 0
    wave = 0
    flips = [0]
    for i in range(1, n):
        if up[i] != up[i - 1]:
            wave += 1; flips.append(i)
        if up[i]:
            st = False; sc = 0
            if green[i]:
                if not lt:
                    lt = True; ents.append((i, 1, 0, wave))
                elif lc < 200:
                    lc += 1
                    if lc <= max_adds:
                        ents.append((i, 1, lc, wave))
        else:
            lt = False; lc = 0
            if red[i]:
                if not st:
                    st = True; ents.append((i, -1, 0, wave))
                elif sc < 200:
                    sc += 1
                    if sc <= max_adds:
                        ents.append((i, -1, sc, wave))
        cur[i] = max(lc, sc)
    flips.append(n)        # 最後一個波段未完
    return ents, cur, up, flips


def trades(d, max_adds):
    """原版：下一根開盤入、反轉 K 線之後嗰根開盤出。"""
    ents, cur, up, flips = run_zgl(d, max_adds)
    o, t = d["o"], d["t"]
    n = len(o)
    fl = np.array(flips)
    rows = []
    for i, side, k, w in ents:
        if i < WARM or i + 1 >= n:
            continue
        j = fl[w + 1]                 # 下一個反轉 K 線
        if j + 1 >= n:
            continue                  # 未平倉，唔計
        ei, xi = i + 1, j + 1
        rows.append((int(t[ei]), side, side * (o[xi] - o[ei]) - COST, int(t[xi]) - int(t[ei]), ei, xi, k))
    return rows


def stats(rows, drift=None):
    if not rows:
        return dict(n=0, avg=0.0, pf=0.0, sum=0.0, dd=0.0, yrs={}, adj=0.0, h1=0.0, h2=0.0, conc=0)
    p = np.array([r[2] for r in rows])
    g, b = p[p > 0].sum(), -p[p < 0].sum()
    xs = sorted(rows, key=lambda r: r[5])
    eq = np.cumsum([r[2] for r in xs]); dd = float((eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()) if len(eq) else 0.0
    yrs = {}
    for r in rows:
        yrs[R.yr(r[0])] = yrs.get(R.yr(r[0]), 0.0) + r[2]
    adj = float(np.mean([r[2] - (r[1] * drift * r[3] if drift is not None else 0) for r in rows]))
    ev = np.zeros(max(r[5] for r in rows) + 2, dtype=np.int64)
    for r in rows:
        ev[r[4]] += 1; ev[r[5]] -= 1
    return dict(n=len(p), avg=float(p.mean()), pf=float(g / b) if b else 99.0, sum=float(p.sum()), dd=dd, yrs=yrs, adj=adj,
                h1=float(sum(r[2] for r in rows if r[0] < SPLIT)), h2=float(sum(r[2] for r in rows if r[0] >= SPLIT)),
                conc=int(np.cumsum(ev).max()))


def f_usd(s):
    return f"{s['n']:,} 單位 平均 {s['avg']:+.2f} PF {s['pf']:.2f} Σ {s['sum']:+,.0f}" if s["n"] else "0"


def load_m1():
    return S.load("mt5", "2022-08-03", "2026-10-30")


# ------------------------------------------------------------------ A
def part_a():
    m1 = load_m1()
    drift = (m1["c"][-1] - m1["c"][0]) / (m1["t"][-1] - m1["t"][0])
    tD, oD, hD, lD, cD = R.load_duka()
    duka = {"t": tD, "o": oD, "h": hD, "l": lD, "c": cD}
    m17 = duka["t"] >= int(dt.datetime(2016, 6, 1, tzinfo=dt.timezone.utc).timestamp())    # 2016 下半年做熱身
    duka = {k: v[m17] for k, v in duka.items()}
    driftD = (duka["c"][-1] - duka["c"][0]) / (duka["t"][-1] - duka["t"][0])
    out = ["# 智能諸葛亮 Pine（ZGL）原版邏輯回測（IDEAS #219）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；券商 MT5 M1 {len(m1['t']):,} 根（2022-08-03→2026-10-30）合成各時框；"
           f"參數照原版（hl2、ZLEMA 6＋21×k、WMA5）；冇止蝕、反轉平晒；收市判斷、下一根開盤成交；每單位扣 {COST} 美元；損益＝美元／0.01 手",
           f"- 同期金價 {m1['c'][0]:.0f} → {m1['c'][-1]:.0f}（強烈上升趨勢），所以只做多一定好睇；「扣趨勢後」＝每單位損益減去持倉期間平均漂移", "",
           "| 時框 | 加單上限 | 多空合計 | 只做多 | 只做空 | 扣趨勢後平均 | 最大同時單位 | 最大回撤 | 2023／24／25／26 | 前半／後半 | 判 |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    verdict = {}
    for tf, sec in TFS.items():
        d = resample(m1, sec)
        for ma in ADDS:
            rows = trades(d, ma)
            s = stats(rows, drift)
            sl = stats([r for r in rows if r[1] > 0]); ss = stats([r for r in rows if r[1] < 0])
            ys = [s["yrs"].get(y, 0.0) for y in YEARS]
            ok = {"①平均≥0.10": s["avg"] >= 0.10, "②PF≥1.15": s["pf"] >= 1.15, "③≥3/4年": sum(v > 0 for v in ys) >= 3,
                  "④兩半正": s["h1"] > 0 and s["h2"] > 0}
            if tf == "1h":
                rd = trades(duka, ma); sd = stats(rd)
                yd = [sd["yrs"].get(y, 0.0) for y in range(2017, 2027)]
                ok["⑤Duka≥7/10年＋PF≥1.1"] = sum(v > 0 for v in yd) >= 7 and sd["pf"] >= 1.1
                verdict[(tf, ma, "duka")] = (sd, yd, stats(rd, driftD))
            v = "✅" if all(ok.values()) else "❌ " + "、".join(k for k, x in ok.items() if not x)
            verdict[(tf, ma)] = all(ok.values())
            out.append(f"| {tf} | {ma} | {f_usd(s)} | {f_usd(sl)} | {f_usd(ss)} | {s['adj']:+.2f} | {s['conc']} | {s['dd']:+,.0f} | "
                       f"{'／'.join(f'{v:+,.0f}' for v in ys)} | {s['h1']:+,.0f}／{s['h2']:+,.0f} | {v} |")
            print(tf, ma, f_usd(s), v, flush=True)
    out += ["", "## 1h Dukascopy 2017→2026（第⑤項）", "", "| 加單上限 | 多空合計 | 扣趨勢後平均 | 正數年 | 每年 |", "|---|---|---|---|---|"]
    for ma in ADDS:
        sd, yd, sda = verdict[("1h", ma, "duka")]
        out.append(f"| {ma} | {f_usd(sd)} | {sda['adj']:+.2f} | {sum(v > 0 for v in yd)}/10 | {' '.join(f'{v:+,.0f}' for v in yd)} |")
    passed = [f"{k[0]} 加單 {k[1]}" for k, v in verdict.items() if len(k) == 2 and v]
    out += ["", "## 結論", "", f"- 達標組合：{'、'.join(passed) if passed else '冇'}",
            "- 冇止蝕＋最多 200 張加單：最大同時單位數就係最壞情況要扛嘅倉；真倉按風險計手數要除返呢個數。",
            "- 12 個組合同時測，就算有一兩個達標都可能係運氣；達標只係提案先影子。", ""]
    open(os.path.join(HERE, "PINE_ZGL_A.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


# ------------------------------------------------------------------ B
class ZDir:
    """已收市 K 線嘅 ZGL 方向。sec＝時框秒數，shift＝對齊（H4 用 7200 → 22:00 UTC）。"""

    def __init__(self, t, h, l, c, sec, shift=0, step=STEP, smooth=SMOOTH):
        key = (t - shift) // sec * sec + shift
        ks, first = np.unique(key, return_index=True)
        self.k, self.sec = ks, sec
        self.up = zgl_up(np.maximum.reduceat(h, first), np.minimum.reduceat(l, first), step, smooth)

    def at(self, ts):
        j = np.searchsorted(self.k, ts - self.sec, side="right") - 1
        if j < 400:
            return 0
        return 1 if self.up[j] else -1


def part_b():
    import b_forward as BF
    import filter_921 as F9
    sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
    argv = sys.argv; sys.argv = sys.argv[:1]
    import rev15_gap as RG
    sys.argv = argv
    g = F9.gb.Gcs()
    (t, o, h, l, c), _ = BF.load_h1()
    slope = F9.H4Slope(t, c)
    z1 = ZDir(t, h, l, c, 3600); z4 = ZDir(t, h, l, c, 14400, 7200)
    # 921
    A = F9.load_live(g)
    decs = F9.load_decisions(g)
    m1 = F9.EF6.broker_bars(int(decs[0][0]) - 86400)
    m1, _ = F9.merge_duka(g, m1, dt.datetime.fromtimestamp(decs[0][0] - 86400, dt.timezone.utc).date().isoformat())
    B921 = F9.replay(m1, decs)
    # 933
    duka = RG.load(RG.config.PREFIX + "duka/", RG.days_between("2026-07-24", "2026-10-31"), "json")
    preds = [p for p in RG.score(RG.run(duka, duka[0]["time"] + 2 * 86400, duka[-1]["time"] + 60), duka) if p.get("r") is not None]
    B933 = [(p["ts"], 1 if p["side"] == "BUY" else -1, p["r"]) for p in preds]
    split933 = int(dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc).timestamp())
    FIL = {"唔過濾": lambda ts, s: True, "H4S 斜率順勢（對照）": lambda ts, s: slope.at(ts) * s > 0,
           "Z1 H1 ZGL 順勢": lambda ts, s: z1.at(ts) == s, "Z4 H4 ZGL 順勢": lambda ts, s: z4.at(ts) == s}
    out = ["# ZGL 方向做 921／933 過濾（IDEAS #220）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；H1 用 Dukascopy＋MT5＋經紀拼接；ZGL 用已收市 K 線；H4 22:00 UTC 對齊",
           f"- 921 B 決策重播 {len(B921)} 張（前後半以中位時間分）；933 rev15 離線 {len(B933)} 張（以 09-12 分）；921 A 真倉 {len(A)} 張只作描述", "",
           "| 樣本 | 過濾 | 全期 | 前半 | 後半 | 保留 | 判 |", "|---|---|---|---|---|---|---|"]
    res = {}
    for lab, S_, split in (("921 B", B921, None), ("933 離線", B933, split933), ("921 A（描述）", A, None)):
        if split is None:
            split = sorted(x[0] for x in S_)[len(S_) // 2] if S_ else 0
        base = None
        for nm, f in FIL.items():
            sel = [x for x in S_ if f(x[0], x[1])]
            a = F9.summ([x[2] for x in sel]); h1 = F9.summ([x[2] for x in sel if x[0] < split]); h2 = F9.summ([x[2] for x in sel if x[0] >= split])
            res[(lab, nm)] = a
            if base is None:
                base = (a, h1, h2); v = "—"
            elif nm.startswith("Z") and not lab.endswith("（描述）"):
                ok = {"①兩半+0.10": h1["avg"] - base[1]["avg"] >= 0.10 and h2["avg"] - base[2]["avg"] >= 0.10,
                      "②平均≥0.05 PF≥1.1": a["avg"] >= 0.05 and a["pf"] >= 1.1, "③保留≥40%": len(sel) >= 0.4 * len(S_),
                      "④贏H4S": a["avg"] > res[(lab, "H4S 斜率順勢（對照）")]["avg"]}
                v = "✅" if all(ok.values()) else "❌ " + "、".join(k for k, x in ok.items() if not x)
            else:
                v = "—"
            out.append(f"| {lab} | {nm} | {F9.fmt(a)} | {F9.fmt(h1)} | {F9.fmt(h2)} | {len(sel) / max(len(S_), 1):.0%} | {v} |")
            print(lab, nm, F9.fmt(a), v, flush=True)
    fw = [x for x in B921 if x[0] >= FWD_TS]
    fz = [x for x in fw if z1.at(x[0]) == x[1]]
    sa, sz = F9.summ([x[2] for x in fw]), F9.summ([x[2] for x in fz])
    out += ["", f"## 921 Z1 影子前向（{dt.datetime.fromtimestamp(FWD_TS, dt.timezone.utc):%m-%d %H:%M} UTC 起；回測達標後照登記先影子）", "",
            f"- 921 新決策重播 {len(fw)}／{FWD_N} 張：唔過濾 {F9.fmt(sa)}；Z1 順勢 {F9.fmt(sz)}；Z1 擋咗 {F9.fmt(F9.summ([x[2] for x in fw if z1.at(x[0]) != x[1]]))}",
            f"- 判：夠 {FWD_N} 張、Z1 平均 R 高過唔過濾 ≥ +0.10 兼 Z1 平均 ≥ +0.05 → 報總指揮提案（寫程式＋dry-run＋使用者批）；"
            + ("✅ 達標" if len(fw) >= FWD_N and sz["avg"] - sa["avg"] >= 0.10 and sz["avg"] >= 0.05 else "❌ 夠數唔達" if len(fw) >= FWD_N else "未夠數")]
    agree = np.mean([z4.at(ts) == (1 if slope.at(ts) > 0 else -1) for ts in t[-24 * 365 * 3::6]])
    out += ["", f"- 近 3 年 Z4 方向同 H4 EMA50 斜率方向一致嘅時間：{agree:.0%}（越高即係兩者差唔多）",
            "- 只係提案；改 921／933 要使用者經總指揮批，建議先影子。921 樣本細（約 70 張）、933 只得 3 個月。", ""]
    open(os.path.join(HERE, "PINE_ZGL_B.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


# ------------------------------------------------------------------ C
def super_events(d):
    """原版統計：回傳 (事件 bar 列表 [(i, side, flip_bar)], 基準 bar 列表)。"""
    ents, cur, up, flips = run_zgl(d, 200)
    n = len(cur)
    waves = []                       # 已完成波段嘅最大加單次數（最新喺前）
    ev, base = [], []
    fl = flips
    for w in range(len(fl) - 1):
        a, b = fl[w], fl[w + 1]      # 波段 [a, b)
        side = 1 if up[a] else -1
        hist = waves[:10]
        thr = None
        if len(hist) >= 3:
            s = sorted(hist)[1:-1]
            mu = float(np.mean(s)); sd = float(np.std(s))
            thr = mu + 2 * sd
        mx = 0; fired = False
        for i in range(max(a, 1), b):
            ci = int(cur[i])
            if i >= WARM and thr is not None and b < n:
                if ci > thr and not fired:
                    ev.append((i, side, b)); fired = True
                elif ci >= 1 and not fired:
                    base.append((i, side, b))
            mx = max(mx, ci)
        waves.insert(0, mx)
    return ev, base


def fwd(d, pts, k, atr):
    c = d["c"]; n = len(c)
    out = []
    for i, s, b in pts:
        if i + k < n and atr[i] > 0:
            out.append((int(d["t"][i]), s * (c[i + k] - c[i]) / atr[i]))
    return out


def welch(a, b):
    a, b = np.asarray(a), np.asarray(b)
    if len(a) < 3 or len(b) < 3:
        return 0.0
    return float((a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))


def tstat(a):
    a = np.asarray(a)
    return float(a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))) if len(a) > 2 and a.std() > 0 else 0.0


def part_c():
    m1 = load_m1()
    out = ["# 「超主升／超主跌」之後點走（IDEAS #221）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；券商 MT5 M1 2022-08→2026-10 合成各時框；門檻同原版（最近 10 個波段最大加單次數去頭去尾 μ＋2σ）",
           "- 前向＝順波段方向收市變化 ÷ ATR14（事件 K 線收市起計）；基準＝同波段方向、已加單 ≥ 1 但未超主嘅 K 線；前後半以 2024-09-17 分", "",
           "| 時框 | 事件 | 10 根 | 30 根 | 60 根（事件／基準，Welch t） | 前半／後半 60 根 | 到反轉（可交易，扣 0.5） | 判 |", "|---|---|---|---|---|---|---|---|"]
    for tf, sec in TFS.items():
        d = resample(m1, sec)
        atr = atr14(d["h"], d["l"], d["c"])
        ev, base = super_events(d)
        cols = []
        for k in (10, 30):
            e = [x[1] for x in fwd(d, ev, k, atr)]
            cols.append(f"{np.mean(e):+.2f}（t {tstat(e):.1f}）" if e else "—")
        e60 = fwd(d, ev, 60, atr); b60 = [x[1] for x in fwd(d, base, 60, atr)]
        ev60 = [x[1] for x in e60]
        h1 = [x[1] for x in e60 if x[0] < SPLIT]; h2 = [x[1] for x in e60 if x[0] >= SPLIT]
        tw = welch(ev60, b60)
        m1h, m2h = (np.mean(h1) if h1 else 0.0), (np.mean(h2) if h2 else 0.0)
        o = d["o"]; n = len(o)
        tr = [(int(d["t"][i + 1]), s, s * (o[b + 1] - o[i + 1]) - COST) for i, s, b in ev if b + 1 < n]
        p = np.array([x[2] for x in tr]) if tr else np.zeros(0)
        pf = p[p > 0].sum() / -p[p < 0].sum() if len(p) and (p < 0).any() else 99.0
        th1 = sum(x[2] for x in tr if x[0] < SPLIT); th2 = sum(x[2] for x in tr if x[0] >= SPLIT)
        cont = np.mean(ev60) > np.mean(b60) and tw >= 2 and m1h > 0 and m2h > 0 if ev60 else False
        exh = np.mean(ev60) < 0 and tstat(ev60) <= -2 and m1h < 0 and m2h < 0 if ev60 else False
        trade_ok = len(p) > 0 and p.mean() >= 0.10 and pf >= 1.15 and th1 > 0 and th2 > 0
        v = ("延續" if cont else "力竭" if exh else "冇邊") + (" ＋可交易✅" if trade_ok else "")
        out.append(f"| {tf} | {len(ev)} | {cols[0]} | {cols[1]} | {np.mean(ev60):+.2f}／{np.mean(b60):+.2f}（t {tw:.1f}） | {m1h:+.2f}／{m2h:+.2f} | "
                   f"{len(p)} 張 平均 {p.mean() if len(p) else 0:+.2f} PF {pf:.2f} 前／後 {th1:+,.0f}／{th2:+,.0f} | {v} |")
        print(out[-1], flush=True)
    out += ["", "- 只係描述＋提案；要用落 921／933／新單要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "PINE_ZGL_C.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


# ------------------------------------------------------------------ D
def htf_dir(d, sec, shift=0):
    """每根 M1（收市時）對應已收市高時框 ZGL 方向（+1／−1，熱身未夠＝0）。"""
    t = d["t"]
    key = (t - shift) // sec * sec + shift
    ks, first = np.unique(key, return_index=True)
    up = zgl_up(np.maximum.reduceat(d["h"], first), np.minimum.reduceat(d["l"], first))
    j = np.searchsorted(ks, t + 60 - sec, side="right") - 1
    out = np.where(up[np.clip(j, 0, None)], 1, -1)
    out[j < 400] = 0
    return out


def part_d():
    m1 = load_m1()
    d = resample(m1, 60)
    t, o = d["t"], d["o"]; n = len(t)
    drift = (m1["c"][-1] - m1["c"][0]) / (t[-1] - t[0])
    atr = atr14(d["h"], d["l"], d["c"])
    h1 = htf_dir(d, 3600); h4 = htf_dir(d, 14400, 7200)
    hr = (t // 3600) % 24
    ents, cur, up, flips = run_zgl(d, 0)
    fl = np.array(flips)
    base = []
    for i, side, k, w in ents:
        if i < WARM or fl[w + 1] + 1 >= n:
            continue
        base.append((i, side, fl[w + 1]))
    def mk(sel, cost=COST):
        return [(int(t[i + 1]), s, s * (o[j + 1] - o[i + 1]) - cost, int(t[j + 1]) - int(t[i + 1]), i + 1, j + 1, 0) for i, s, j in sel]
    V = {"V0 原版首單（對照）": base,
         "V1 H1 順勢": [x for x in base if h1[x[0]] == x[1]],
         "V2 H1＋H4 順勢": [x for x in base if h1[x[0]] == x[1] and h4[x[0]] == x[1]],
         "V3 ATR ≥ 1.5": [x for x in base if atr[x[0]] >= 1.5],
         "V4 倫敦＋紐約": [x for x in base if 7 <= hr[x[0]] < 20],
         "V6 V1＋V3＋V4": [x for x in base if h1[x[0]] == x[1] and atr[x[0]] >= 1.5 and 7 <= hr[x[0]] < 20]}
    # V5：H1 波段入面第一個同向 M1 首單入，H1 轉向出
    chg = np.flatnonzero(np.diff(h1) != 0) + 1
    v5 = []; bi = sorted(base)
    first_idx = np.array([x[0] for x in bi])
    for a, b in zip(chg[:-1], chg[1:]):
        if h1[a] == 0:
            continue
        p = np.searchsorted(first_idx, a)
        while p < len(bi) and bi[p][0] < b and bi[p][1] != h1[a]:
            p += 1
        if p < len(bi) and bi[p][0] < b and b + 1 < n:
            v5.append((bi[p][0], int(h1[a]), b))     # b＝H1 方向改變嗰根 M1；喺 b 收市判、b＋1 開盤出（mk 用 j+1）
    V["V5 M1 入、H1 出"] = v5
    out = ["# 智能諸葛亮 M1 改良（IDEAS #222）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；券商 MT5 M1 2022-08→2026-10；只首單、唔加單；收市判斷下一根開盤成交；每張扣 {COST} 美元（另列 0.3）；損益＝美元／0.01 手",
           "- 後半（≥ 2024-09-17）當樣本外；扣成本前＝平均＋成本", "",
           "| 改法 | 全期 | 扣成本前平均 | 前半平均 | 後半 | 後半做多／做空平均 | 2023／24／25／26 | 成本 0.3 全期 | 判 |", "|---|---|---|---|---|---|---|---|---|"]
    for nm, sel in V.items():
        rows = mk(sel); s = stats(rows, drift)
        r1 = [r for r in rows if r[0] < SPLIT]; r2 = [r for r in rows if r[0] >= SPLIT]
        s1, s2 = stats(r1), stats(r2)
        l2 = stats([r for r in r2 if r[1] > 0]); sh2 = stats([r for r in r2 if r[1] < 0])
        ys = [s["yrs"].get(y, 0.0) for y in YEARS]
        s3 = stats(mk(sel, 0.3))
        ok = {"①後半≥0.10 PF≥1.15": s2["avg"] >= 0.10 and s2["pf"] >= 1.15, "②前半>0": s1["avg"] > 0,
              "③≥3/4年": sum(v > 0 for v in ys) >= 3, "④後半多空都>0": l2["avg"] > 0 and sh2["avg"] > 0}
        v = "—" if nm.startswith("V0") else ("✅" if all(ok.values()) else "❌ " + "、".join(k for k, x in ok.items() if not x))
        out.append(f"| {nm} | {f_usd(s)} | {s['avg'] + COST:+.2f} | {s1['avg']:+.2f} | {f_usd(s2)} | {l2['avg']:+.2f}／{sh2['avg']:+.2f} | "
                   f"{'／'.join(f'{x:+,.0f}' for x in ys)} | {s3['avg']:+.2f} PF {s3['pf']:.2f} | {v} |")
        print(out[-1], flush=True)
    out += ["", "- 6 個改法同時測，有多重比較風險；達標只係提案先影子，落真倉要使用者經總指揮批。", ""]
    open(os.path.join(HERE, "PINE_ZGL_D.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


# ------------------------------------------------------------------ E
def part_e():
    import b_forward as BF
    import filter_921 as F9
    g = F9.gb.Gcs()
    (t, o, h, l, c), _ = BF.load_h1()
    slope = F9.H4Slope(t, c)
    decs = F9.load_decisions(g)
    m1 = F9.EF6.broker_bars(int(decs[0][0]) - 86400)
    m1, _ = F9.merge_duka(g, m1, dt.datetime.fromtimestamp(decs[0][0] - 86400, dt.timezone.utc).date().isoformat())
    B = F9.replay(m1, decs)
    base = F9.summ([x[2] for x in B])
    out = ["# #220 Z1（H1 ZGL 順勢）穩健度（IDEAS #223）", "",
           f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；921 B 決策重播 {len(B)} 張（唔過濾 {F9.fmt(base)}）", "",
           "## E1 參數敏感度（921 B，Z1 過濾）", "", "| 帶距＼平滑 | 3 | 5 | 8 |", "|---|---|---|---|"]
    good = 0
    for st in (15, 21, 27):
        cells = []
        for sm in (3, 5, 8):
            z = ZDir(t, h, l, c, 3600, 0, st, sm)
            sel = [x for x in B if z.at(x[0]) == x[1]]
            s_ = F9.summ([x[2] for x in sel]); dlt = s_["avg"] - base["avg"]
            good += dlt >= 0.10
            cells.append(f"{len(sel)} 張 {s_['avg']:+.3f}（{dlt:+.3f}）")
        out.append(f"| {st} | " + " | ".join(cells) + " |")
    out += ["", f"- 改善 ≥ +0.10R：{good}/9 組", ""]
    C = F9.random_entries(t, o, h, l, c)
    z1 = ZDir(t, h, l, c, 3600); z4 = ZDir(t, h, l, c, 14400, 7200)
    FIL = {"H4S 斜率順勢": lambda ts, s: slope.at(ts) * s > 0, "Z1 H1 ZGL 順勢": lambda ts, s: z1.at(ts) == s,
           "Z4 H4 ZGL 順勢": lambda ts, s: z4.at(ts) == s}
    bc = F9.summ([x[2] for x in C])
    out += ["## E2 長歷史隨機入場（#211 樣本 C）", "", f"- 唔過濾：{F9.fmt(bc)}", "",
            "| 過濾 | 全期 | 改善 | 2017–2026 改善年數 | 每年改善 |", "|---|---|---|---|---|"]
    res = {}
    for nm, f in FIL.items():
        sel = [x for x in C if f(x[0], x[1])]
        s_ = F9.summ([x[2] for x in sel]); yrs = []
        for y in F9.Y10:
            Cy = [x for x in C if R.yr(x[0]) == y]; Sy = [x for x in Cy if f(x[0], x[1])]
            yrs.append(F9.summ([x[2] for x in Sy])["avg"] - F9.summ([x[2] for x in Cy])["avg"])
        res[nm] = (s_, sum(v > 0 for v in yrs), s_["avg"] - bc["avg"])
        out.append(f"| {nm} | {F9.fmt(s_)} | {s_['avg'] - bc['avg']:+.3f} | {sum(v > 0 for v in yrs)}/10 | {' '.join(f'{v:+.2f}' for v in yrs)} |")
        print(out[-1], flush=True)
    z = res["Z1 H1 ZGL 順勢"]
    ok = {"①E1≥7/9": good >= 7, "②E2 Z1 改善>0 且 ≥7/10 年": z[2] > 0 and z[1] >= 7, "③E2 Z1 ≥ H4S": z[0]["avg"] >= res["H4S 斜率順勢"][0]["avg"]}
    out += ["", "## 判（預先登記）", "", f"- {'✅ 穩健 → #220 影子照做' if all(ok.values()) else '❌ 唔穩：' + '、'.join(k for k, v in ok.items() if not v) + ' → #220 影子照做，但夠 30 張要 Z1 贏 H4S ≥ +0.10R 先提案'}", ""]
    open(os.path.join(HERE, "PINE_ZGL_E.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["A", "B", "C", "D", "E"], required=True)
    {"A": part_a, "B": part_b, "C": part_c, "D": part_d, "E": part_e}[ap.parse_args().part]()
