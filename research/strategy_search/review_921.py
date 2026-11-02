"""921（Opus 自主單）真倉檢討（使用者 11-02「921 決策全做錯 檢討」）——純描述，唔係假說測試。
每張真倉（成交簿 xau/book_seed.json＋state.json book）用 M1（經紀＋Dukascopy 補）計：
  MFE／MAE（R，入場→平倉）、方向對唔對（入場後 1h／4h 價格向單方向行咗幾多 R，唔理止蝕）、
  24h 內有冇去到 +1R／+2R（唔理止蝕）、反向做（同樣止蝕距離、1.5R 止賺、24h）R、
  H4 EMA50 斜率同唔同向、時段、入場前 15 分鐘走勢（追價）。
用法：python3 research/strategy_search/review_921.py → REVIEW_921_1102.md"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import b_forward as BF  # noqa: E402
import filter_921 as F  # noqa: E402


def sess(ts):
    h = dt.datetime.fromtimestamp(ts, dt.timezone.utc).hour
    return "亞洲" if (h >= 22 or h < 7) else ("倫敦" if h < 13 else "紐約")


def main():
    g = F.gb.Gcs()
    rows = (g.read_json("xau/book_seed.json") or []) + ((g.read_json("xau/state.json") or {}).get("book") or [])
    seen, trs = set(), []
    for r in sorted(rows, key=lambda r: r.get("opened_ts") or 0):
        k = (r.get("opened_ts"), r.get("side"))
        if k in seen or not r.get("closed_ts") or r.get("stop0") is None:
            continue
        seen.add(k); trs.append(r)
    m1 = F.EF6.broker_bars(int(trs[0]["opened_ts"]) - 86400)
    m1, _ = F.merge_duka(g, m1, "2026-10-20")
    t, o, h, l, c = m1["t"], m1["o"], m1["h"], m1["l"], m1["c"]
    (ht, ho, hh, hl, hc), _ = BF.load_h1(); slope = F.H4Slope(ht, hc)
    res = []
    for n, r in enumerate(trs, 1):
        side, e, s0 = int(r["side"]), float(r["entry"]), float(r["stop0"]); risk = abs(e - s0)
        if risk <= 0:
            continue
        a = int(np.searchsorted(t, r["opened_ts"], side="left")); b = int(np.searchsorted(t, r["closed_ts"], side="right"))
        a24 = int(np.searchsorted(t, r["opened_ts"] + 86400))
        fav = (h if side > 0 else l)[a:b]; adv = (l if side > 0 else h)[a:b]
        mfe = float(((fav - e) * side).max() / risk) if b > a else 0.0
        mae = float(((adv - e) * side).min() / risk) if b > a else 0.0

        def move(sec):
            j = int(np.searchsorted(t, r["opened_ts"] + sec)) - 1
            return float((c[j] - e) * side / risk) if a <= j < len(c) else np.nan
        f24 = (h if side > 0 else l)[a:a24]
        hit1 = bool(((f24 - e) * side >= risk).any()); hit2 = bool(((f24 - e) * side >= 2 * risk).any())
        # 反向：入場價反方向，同樣止蝕距離，1.5R 止賺，24h
        rs, rsl, rtp = -side, e + side * risk, e - side * 1.5 * risk
        rr = None
        for j in range(a, min(a24, len(t))):
            if (h[j] >= rsl) if rs < 0 else (l[j] <= rsl):
                rr = -1.0; break
            if (l[j] <= rtp) if rs < 0 else (h[j] >= rtp):
                rr = 1.5; break
        if rr is None:
            rr = float((c[min(a24, len(c)) - 1] - e) * rs / risk)
        p15 = int(np.searchsorted(t, r["opened_ts"] - 900))
        pre = float((c[a - 1] - c[p15]) * side) if a > p15 else 0.0
        sl = slope.at(r["opened_ts"])
        res.append(dict(id=r.get("id") or f"L{n}", ts=r["opened_ts"], side=side, r=float(r["r"]), mfe=mfe, mae=mae, m1h=move(3600), m4h=move(4 * 3600),
                        hit1=hit1, hit2=hit2, rev=rr, risk=risk, trend=(sl * side > 0), sess=sess(r["opened_ts"]), pre=pre, hold=(r["closed_ts"] - r["opened_ts"]) / 60))
    R = np.array([x["r"] for x in res])

    def grp(lbl, sel):
        if not sel:
            return f"| {lbl} | 0 | | | | | | |"
        rr = np.array([x["r"] for x in sel]); rv = np.array([x["rev"] for x in sel])
        return (f"| {lbl} | {len(sel)} | {rr.mean():+.2f} | {(rr > 0).mean():.0%} | {np.mean([x['mfe'] for x in sel]):.2f} | "
                f"{np.mean([x['hit1'] for x in sel]):.0%} | {np.nanmean([x['m4h'] for x in sel]):+.2f} | {rv.mean():+.2f} |")
    out = ["# 921 真倉檢討（11-02）", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；{len(res)} 張已平倉；R＝入場→初始止蝕；M1＝經紀（缺口 Dukascopy）；純描述", "",
           "## 分組", "", "| 組 | 張數 | 平均 R | 勝率 | 平均 MFE R | 24h 內去到 +1R（唔理止蝕） | 4h 後方向 R | 反向做平均 R |", "|---|---|---|---|---|---|---|---|",
           grp("全部", res), grp("最近 10 張", res[-10:]), grp("做多", [x for x in res if x["side"] > 0]), grp("做空", [x for x in res if x["side"] < 0]),
           grp("H4 順勢", [x for x in res if x["trend"]]), grp("H4 逆勢", [x for x in res if not x["trend"]]),
           grp("亞洲", [x for x in res if x["sess"] == "亞洲"]), grp("倫敦", [x for x in res if x["sess"] == "倫敦"]), grp("紐約", [x for x in res if x["sess"] == "紐約"]),
           grp("止蝕 < 6 美元", [x for x in res if x["risk"] < 6]), grp("止蝕 ≥ 6 美元", [x for x in res if x["risk"] >= 6]),
           grp("追價（入場前 15 分鐘已向單方向走 ≥ 3）", [x for x in res if x["pre"] >= 3]), grp("唔追價", [x for x in res if x["pre"] < 3]),
           "", "## 蝕單係「方向錯」定「止蝕太近」", ""]
    loss = [x for x in res if x["r"] < 0]
    dir_ok = [x for x in loss if x["hit1"]]
    out += [f"- 蝕單 {len(loss)} 張：其中 {len(dir_ok)} 張（{len(dir_ok) / max(len(loss), 1):.0%}）24 小時內價格其實有去到 +1R（即方向啱，但先掃止蝕）；"
            f"{len(loss) - len(dir_ok)} 張連 +1R 都冇去到（方向錯）",
            f"- 蝕單平均 MFE {np.mean([x['mfe'] for x in loss]):.2f}R（入場後最多浮盈）；贏單平均 MAE {np.mean([x['mae'] for x in res if x['r'] > 0]):.2f}R",
            f"- 全部單 4h 後平均方向 {np.nanmean([x['m4h'] for x in res]):+.2f}R、1h 後 {np.nanmean([x['m1h'] for x in res]):+.2f}R（正＝方向啱）", "",
            "## 逐張", "", "| 單 | 開倉（UTC） | 方向 | 時段 | H4 | 止蝕距 | 入場前 15 分 | 實際 R | MFE | MAE | 1h | 4h | 24h +1R | 反向 R |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in res:
        out.append(f"| {x['id']} | {dt.datetime.fromtimestamp(x['ts'], dt.timezone.utc):%m-%d %H:%M} | {'多' if x['side'] > 0 else '空'} | {x['sess']} | {'順' if x['trend'] else '逆'} | {x['risk']:.1f} | {x['pre']:+.1f} | "
                   f"{x['r']:+.2f} | {x['mfe']:.2f} | {x['mae']:.2f} | {x['m1h']:+.2f} | {x['m4h']:+.2f} | {'✓' if x['hit1'] else '✗'} | {x['rev']:+.2f} |")
    out += ["", f"- 全部 {len(res)} 張實際 ΣR {R.sum():+.2f}；反向做 ΣR {sum(x['rev'] for x in res):+.2f}（反向用 1.5R 止賺、24h，同原單止蝕距離）", ""]
    open(os.path.join(HERE, "REVIEW_921_1102.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
