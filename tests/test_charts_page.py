"""[R258] 📐 分析圖頁：有圖、冇圖、讀取失敗三種情況。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import main
from unittest import mock
items=[{"id":"hsi_fib_4h","title":"T","team":"🐉 龍飛陣","desc":"d","png":"charts/x.png","json":"charts/x.json","updated_hkt":"2026-10-23 21:00",
        "data":{"last":23103.0,"asof":"2026-10-23 20:00:00","levels":{"0":26205,"0.5":24363},"sma50":23924,"sma100":24107,"sma200":24600}}]
with mock.patch.object(main,"_chart_png_b64",return_value="AAAA"):
    h=main.build_charts_page(items)
assert "data:image/png;base64,AAAA" in h and "24,363" in h and "23,103" in h and "SMA 200" in h, h[:500]
assert "暫時未有" in main.build_charts_page([])
assert "讀取失敗" in main.build_charts_page([], "讀取失敗")
print("ok", len(h))

# [R259] 龍飛陣分析欄
h = main.md_to_html("## 標題\n\n**結構**\n・一行<script>\n・二行\n\n- 點一\n- 點二")
assert "<h3>標題</h3>" in h and "<b>結構</b>" in h and "&lt;script&gt;" in h and "<li>點一</li>" in h, h
doc = {"date": "2026-10-23", "title": "T", "markdown": "## A\n文字\n\n（技術分析僅供參考，非投資建議；龍飛陣 AI 交易不讀此欄。）", "charts": {"HSI": ["ops/longfei/analyst/charts/2026-10-23/HSI_4h.png", "bad/path.png"]}}
sc = {"summary": {"bias": {"hit": 3, "n": 4, "rate": 0.75}}, "pending": 2,
      "calls": [{"date": "2026-10-23", "market": "HSI", "kind": "resistance", "level": 23309, "horizon": 5, "why": "0.786", "result": None},
                {"date": "2026-10-22", "market": "NQ", "kind": "bias", "dir": -1, "horizon": 5, "why": "x", "result": {"ok": True, "detail": "10-30 收市 28,700 跌穿"}}, {"date": "2026-10-21", "market": "ES", "kind": "target", "level": 7600, "horizon": 5, "why": "y", "result": {"ok": False, "detail": "未到"}}]}
with mock.patch.object(main, "_chart_png_b64", return_value="BBBB") as m:
    a = main.build_analyst_section({"doc": doc, "scorecard": sc, "days": ["2026-10-23", "2026-10-22"]})
    assert m.call_count == 1                      # 只讀 ops/longfei/analyst/ 底下嘅圖
assert "BBBB" in a and "壓力 23,309" in a and "偏淡 ↓" in a and "3／4" in a and "75%" in a and "❌" in a and "28,700 跌穿" in a and "⏳" in a and "✅" in a and "?view=charts&day=2026-10-22" in a, a
assert "文字" in a and "技術分析僅供參考" not in a   # [R268] 免責句濾走
assert "暫時未有分析" in main.build_analyst_section({"doc": None})
assert main._DAY_RE.match("2026-10-23") and not main._DAY_RE.match("../x")
print("analyst ok")
