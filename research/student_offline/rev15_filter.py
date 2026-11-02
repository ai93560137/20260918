"""[IDEAS #217] 933 rev15 規則學生（真倉）加過濾：用離線 Dukascopy M1（2026-07-24→10-31，同 REV15_GAP 一樣嘅引擎：60 分鐘冷卻、signals.evaluate、2R 全平、扣 0.5 美元）。
  F1 H4 順勢：H4 EMA50 斜率（已收市 H4，22:00 UTC 對齊）同入場方向一致先做
  F2 H4 逆勢：斜率同入場方向相反先做（rev15 係反轉規則，可能逆勢先有效）
  F3 唔做亞洲：出區時間 22:00–07:00 UTC 唔做
  F4 波幅高：出區前 M15 ATR14 ÷ 過去 5 日 M15 ATR14 中位數 ≥ 1 先做
判（預先登記，每個過濾各自）：① 前半（< 2026-09-12）同後半（≥ 2026-09-12）過濾後平均 R 都高過唔過濾 ≥ +0.10R；② 全期過濾後平均 R ≥ +0.05、PF ≥ 1.1；③ 保留 ≥ 40% 張數。
另列實時 933 真倉／影子（xau/sig/student/log）同一過濾嘅描述。達標 → 只係提案（改 933 程式要使用者經總指揮批），建議先影子。
用法：python3 research/student_offline/rev15_filter.py → REV15_FILTER.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = sys.argv[:1]
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "strategy_search"))
import rev15_gap as RG  # noqa: E402
import b_forward as BF  # noqa: E402
import filter_921 as F9  # noqa: E402

SPLIT = int(dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc).timestamp())
NAMES = ["F0 唔過濾", "F1 H4 順勢", "F2 H4 逆勢", "F3 唔做亞洲", "F4 波幅高"]


def m15_atr(m1):
    out = {}
    for b in m1:
        k = b["time"] // 900 * 900
        o = out.setdefault(k, [b["high"], b["low"], b["close"], b["open"]])
        o[0] = max(o[0], b["high"]); o[1] = min(o[1], b["low"]); o[2] = b["close"]
    ks = np.array(sorted(out)); h = np.array([out[k][0] for k in ks]); l = np.array([out[k][1] for k in ks]); c = np.array([out[k][2] for k in ks])
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = np.full(len(tr), np.nan)
    for i in range(14, len(tr)):
        atr[i] = tr[i - 13:i + 1].mean()
    return ks, atr


def main():
    duka = RG.load(RG.config.PREFIX + "duka/", RG.days_between("2026-07-24", "2026-10-31"), "json")
    preds = RG.score(RG.run(duka, duka[0]["time"] + 2 * 86400, duka[-1]["time"] + 60), duka)
    preds = [p for p in preds if p.get("r") is not None]
    (t, o, h, l, c), _ = BF.load_h1()
    slope = F9.H4Slope(t, c)
    ks, atr = m15_atr(duka)

    def ratio(ts):
        j = np.searchsorted(ks, ts - 900, side="right") - 1
        if j < 480:
            return np.nan
        w = atr[j - 480:j]
        return atr[j] / np.nanmedian(w)

    def keep(f, p):
        side = 1 if p["side"] == "BUY" else -1; s = slope.at(p["ts"])
        if f == 1:
            return s * side > 0
        if f == 2:
            return s * side < 0
        if f == 3:
            return not F9.asia(p["ts"])
        if f == 4:
            r = ratio(p["ts"]); return bool(r >= 1) if not np.isnan(r) else True
        return True

    out = ["# 933 rev15 加過濾（IDEAS #217）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；離線 Dukascopy M1 2026-07-24→10-31，{len(preds)} 張有結果；前後半以 09-12 分", "",
           "| 過濾 | 全期 | 前半 | 後半 | 保留 | 判 |", "|---|---|---|---|---|---|"]
    base = None
    for f, nm in enumerate(NAMES):
        sel = [p for p in preds if keep(f, p)]
        a = F9.summ([p["r"] for p in sel]); h1 = F9.summ([p["r"] for p in sel if p["ts"] < SPLIT]); h2 = F9.summ([p["r"] for p in sel if p["ts"] >= SPLIT])
        if f == 0:
            base = (a, h1, h2); verdict = "—"
        else:
            ok = dict(halves=h1["avg"] - base[1]["avg"] >= 0.10 and h2["avg"] - base[2]["avg"] >= 0.10, avg=a["avg"] >= 0.05, pf=a["pf"] >= 1.1, keep=len(sel) >= 0.4 * len(preds))
            verdict = "✅" if all(ok.values()) else "❌ " + "、".join(k for k, v in ok.items() if not v)
        out.append(f"| {nm} | {F9.fmt(a)} | {F9.fmt(h1)} | {F9.fmt(h2)} | {len(sel) / len(preds):.0%} | {verdict} |")
        print(nm, F9.fmt(a), flush=True)
    live = [p for p in RG.live_preds(RG.days_between("2026-10-20", "2026-11-02")) if p.get("r") is not None] if hasattr(RG, "live_preds") else []
    if live:
        out += ["", "## 實時影子（xau/sig/student/log，描述）", "", "| 過濾 | 結果 |", "|---|---|"]
        for f, nm in enumerate(NAMES):
            out.append(f"| {nm} | {F9.fmt(F9.summ([p['r'] for p in live if keep(f, p)]))} |")
    out += ["", "- 只係提案；改 933 程式要使用者經總指揮批，建議先影子。樣本只得 3 個月同一段市況。", ""]
    open(os.path.join(HERE, "REV15_FILTER.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
