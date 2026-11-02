"""[R367／IDEAS #212 跟進] 921「浮盈未到 1R 唔准 AI 收緊止蝕」逐張記錄（總指揮 11-02 轉使用者：先等 5–10 張再決定維持 1R／改 0.5R／取消擋）。
由 L38（R367 後第一張，2026-11-02 11:40 UTC）起，每張 921 真倉單：
  ① 有冇被擋（決策 rejected「止蝕已放闊」）；② 被擋時浮盈幾多 R（R＝入場→放闊後初始止蝕）；
  ③ 反事實：A＝照 AI 每次要求收緊（只收緊、唔放鬆）；B＝浮盈 ≥ 0.5R 先准收緊；用經紀 M1（缺口用 Dukascopy 補）由被擋嗰分鐘起重播到實際平倉時間，
     撞新止蝕＝喺新止蝕出（同一分鐘都掂當止蝕），否則照實際出場；④ 實際 R（成交簿）。
數據：921 成交簿（xau/book_seed.json＋xau/state.json book）、決策（xau/decisions/<日>.jsonl＋xau/state.json decisions）。唔寫 GCS。
用法：python3 research/strategy_search/r367_block.py → R367_BLOCK.md"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import filter_921 as F  # noqa: E402

START = int(dt.datetime(2026, 11, 2, 11, 30, tzinfo=dt.timezone.utc).timestamp())


def decisions(g):
    seen, out = set(), []
    for nm in sorted(g.list("xau/decisions/")):
        if nm.rsplit("/", 1)[-1][:10] < "2026-11-02":
            continue
        txt = g.read_text(nm) or ""
        try:
            arr = json.loads(txt); arr = arr if isinstance(arr, list) else [arr]
        except ValueError:
            arr = []
            for ln in txt.splitlines():
                try:
                    v = json.loads(ln); arr += v if isinstance(v, list) else [v]
                except ValueError:
                    pass
        for o in arr:
            if o.get("id") not in seen:
                seen.add(o.get("id")); out.append(o)
    for o in (g.read_json("xau/state.json") or {}).get("decisions") or []:
        if o.get("id") not in seen:
            seen.add(o.get("id")); out.append(o)
    return sorted([o for o in out if (o.get("ts") or 0) >= START], key=lambda o: o["ts"])


def replay(m1, side, entry, stop0, exit_px, t_from, t_to, new_stops):
    """new_stops：[(ts, stop)]（已按時間排）。回傳 (出場價, 原因)。"""
    t, h, l = m1["t"], m1["h"], m1["l"]
    cur = stop0; k = 0
    a = int(np.searchsorted(t, t_from, side="left")); b = int(np.searchsorted(t, t_to, side="left"))
    for j in range(a, b):
        while k < len(new_stops) and new_stops[k][0] <= t[j]:
            s = new_stops[k][1]
            if (s - cur) * side > 0:
                cur = s
            k += 1
        if cur != stop0 and ((l[j] <= cur) if side > 0 else (h[j] >= cur)):
            return cur, "收緊後止蝕"
    return exit_px, "照實際"


def main():
    g = F.gb.Gcs()
    rows = (g.read_json("xau/book_seed.json") or []) + ((g.read_json("xau/state.json") or {}).get("book") or [])
    trades = sorted([r for r in rows if (r.get("opened_ts") or 0) >= START and r.get("closed_ts")], key=lambda r: r["opened_ts"])
    decs = decisions(g)
    m1 = F.EF6.broker_bars(START - 86400)
    m1, _ = F.merge_duka(g, m1, "2026-11-01")
    out = ["# R367「未到 1R 唔准 AI 收緊」逐張記錄", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；由 L38（11-02 11:40 UTC）起；R＝入場→放闊後初始止蝕；反事實用經紀 M1 重播（未計點差／滑價差異）", "",
           "| # | 開倉（UTC） | 方向 | 實際 R | 被擋次數 | 被擋時浮盈 R | AI 要求止蝕 | A 照 AI 收緊 R | B ≥0.5R 先准 R |", "|---|---|---|---|---|---|---|---|---|"]
    tot = {"act": 0.0, "A": 0.0, "B": 0.0}
    for n, r in enumerate(trades, 38):
        side, entry, stop0 = int(r["side"]), float(r["entry"]), float(r["stop0"])
        risk = abs(entry - stop0); o, c = r["opened_ts"], r["closed_ts"]
        exit_px = float(r.get("exit_est") or (entry + side * float(r["r"]) * risk))
        blk = [d for d in decs if o <= d["ts"] <= c and "放闊" in str(d.get("rejected") or "") and d.get("ai_stop") is not None]
        info = [((float(d["price"]) - entry) * side / risk, float(d["ai_stop"]), d["ts"]) for d in blk]
        sa = [(int(ts) + 60, s) for _, s, ts in info]
        sb = [(int(ts) + 60, s) for gr, s, ts in info if gr >= 0.5]
        xa, _ = replay(m1, side, entry, stop0, exit_px, o, c + 60, sa) if sa else (exit_px, "")
        xb, _ = replay(m1, side, entry, stop0, exit_px, o, c + 60, sb) if sb else (exit_px, "")
        ra = (xa - entry) * side / risk if sa else float(r["r"]); rb = (xb - entry) * side / risk if sb else float(r["r"])
        tot["act"] += float(r["r"]); tot["A"] += ra; tot["B"] += rb
        out.append(f"| L{n} | {dt.datetime.fromtimestamp(o, dt.timezone.utc):%m-%d %H:%M} | {'多' if side > 0 else '空'} | {float(r['r']):+.2f} | {len(blk)} | "
                   f"{'、'.join(f'{x[0]:+.2f}' for x in info) or '—'} | {'、'.join(f'{x[1]:.2f}' for x in info) or '—'} | {ra:+.2f} | {rb:+.2f} |")
    k = len(trades)
    out += ["", f"- {k} 張已平倉；合計 R：實際（擋到 1R）{tot['act']:+.2f}｜A 唔擋 {tot['A']:+.2f}｜B 0.5R 先准 {tot['B']:+.2f}",
            f"- 報告節點：5 張、10 張（而家 {k}）；{'**已到 5 張 → 報總指揮**' if k >= 5 and k < 10 else ('**已到 10 張 → 報總指揮＋建議**' if k >= 10 else '未到 5 張')}",
            "- 反事實只模擬被擋嗰幾次收緊（AI 之後可能再改），出場用實際平倉價或者新止蝕；樣本細，只作參考。", ""]
    open(os.path.join(HERE, "R367_BLOCK.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
