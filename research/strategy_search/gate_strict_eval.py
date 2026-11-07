"""[11-07] 921 嚴格篩選（XAU_GATE_STRICT=shadow）效果：讀 GCS xau/decisions/<日>.jsonl，計嚴格版會擋走幾多次 Opus、慳幾多、擋走幾多開倉。
判斷（xau/GATE_STRICT_921.md 預先寫低）：shadow ≥ 3 個交易日，而且 ① 擋走 ≥ 30% 空倉 Opus 調用；② 擋走開倉 ≤ 10%；③ 被擋開倉嘅紙上成績唔好過其他開倉。
用法：python3 research/strategy_search/gate_strict_eval.py [--start 2026-11-09] → research/strategy_search/GATE_STRICT_EVAL.md"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gb_rulesim"))
import gb_rulesim as gb   # noqa: E402


def main():
    start = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else "2026-11-07"
    g = gb.Gcs()
    rows = []
    for nm in sorted(g.list("xau/decisions/")):
        if nm.rsplit("/", 1)[-1][:10] < start:
            continue
        txt = g.read_text(nm) or ""
        for ln in txt.splitlines():
            ln = ln.strip()
            if ln.startswith("["):
                try:
                    rows += json.loads(ln)
                except ValueError:
                    pass
    dec = [r for r in rows if r.get("kind") == "decide" and isinstance(r.get("gate_strict"), dict) and r["gate_strict"].get("mode") == "shadow"]
    days = sorted({dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc).date().isoformat() for r in dec})
    blocked = [r for r in dec if not r["gate_strict"].get("look")]
    opens = [r for r in dec if str(r.get("final") or "").startswith("OPEN")]
    ob = [r for r in opens if not r["gate_strict"].get("look")]
    cost = sum(r.get("cost_usd") or 0 for r in dec); save = sum(r.get("cost_usd") or 0 for r in blocked)
    extra = sum((r["gate_strict"].get("cost_usd") or 0) for r in dec)
    pct = len(blocked) / len(dec) if dec else 0.0
    opct = len(ob) / len(opens) if opens else 0.0
    out = ["# 921 嚴格篩選 shadow 效果", "", f"- 更新 {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；由 {start} 起；有 shadow 記錄嘅交易日 {len(days)} 日（{', '.join(days) or '—'}）",
           f"- 空倉 Opus 調用 {len(dec)} 次（${cost:.2f}）；嚴格版會擋 {len(blocked)} 次（{pct:.0%}，慳 ${save:.2f}）；嚴格版本身成本 ${extra:.2f}",
           f"- 開倉決定 {len(opens)} 次；嚴格版會擋 {len(ob)} 次（{opct:.0%}）"]
    out += ["", "## 被擋嘅開倉", ""] + [f"- {r.get('ts') and dt.datetime.fromtimestamp(r['ts'], dt.timezone.utc):%m-%d %H:%M} {r.get('final')} @ {r.get('price')}｜嚴格版：{r['gate_strict'].get('reason')}" for r in ob]
    ok = {"①≥3個交易日": len(days) >= 3, "②擋走≥30%": pct >= 0.30, "③擋走開倉≤10%": opct <= 0.10}
    out += ["", "## 判（xau/GATE_STRICT_921.md）", "", *[f"- {k}：{'✅' if v else '❌'}" for k, v in ok.items()],
            "- ③ 被擋開倉嘅紙上成績要人手對 xau/state.json trades（張數少）", ""]
    md = "\n".join(out) + "\n"
    print(md)
    open(os.path.join(HERE, "GATE_STRICT_EVAL.md"), "w", encoding="utf-8").write(md)


if __name__ == "__main__":
    main()
