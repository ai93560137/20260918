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
assert "BBBB" in a and "壓力 23,309" in a and "偏淡 ↓" in a and "3／4" in a and "75%" in a and "❌" in a and "28,700 跌穿" in a and "⏳" in a and "✅" in a and "?view=analyst&day=2026-10-22" in a, a
assert "文字" in a and "技術分析僅供參考" not in a   # [R268] 免責句濾走
assert "暫時未有分析" in main.build_analyst_section({"doc": None})
assert main._DAY_RE.match("2026-10-23") and not main._DAY_RE.match("../x")
print("analyst ok")

# [R329] 📝 龍飛陣分析頁：全部日子累積，最新展開連圖，舊嘅摺埋
d2 = {"date": "2026-10-24", "title": "新篇", "generated_hkt": "2026-10-24 08:51", "markdown": "## 上次對照\n今日",
      "charts": {"NQ": ["ops/longfei/analyst/charts/2026-10-24/NQ_4h.png"]}, "calls": []}
d1 = {"date": "2026-10-23", "title": "舊篇", "markdown": "## 舊\n昨日\n\n（技術分析僅供參考，非投資建議；龍飛陣 AI 交易不讀此欄。）", "charts": {"NQ": ["ops/longfei/analyst/charts/2026-10-23/NQ_4h.png"]}}
sc2 = {"summary": {"bias": {"hit": 1, "n": 2, "rate": 0.5}},
       "calls": [{"date": "2026-10-23", "market": "NQ", "kind": "bias", "dir": -1, "horizon": 5, "why": "a", "result": {"ok": True, "detail": "d"}},
                 {"date": "2026-10-23", "market": "ES", "kind": "bias", "dir": 0, "horizon": 5, "why": "b", "result": {"ok": False}},
                 {"date": "2026-10-24", "market": "HSI", "kind": "resistance", "level": 23309, "horizon": 5, "why": "c", "result": None}]}
with mock.patch.object(main, "_chart_png_b64", return_value="CCCC") as m:
    p = main.build_analyst_page({"docs": [d2, d1], "scorecard": sc2})
    assert m.call_count == 1                      # 只有展開嗰篇載圖
assert "新篇" in p and "舊篇" in p and "今日" in p and "昨日" in p and "<details>" in p and "CCCC" in p, p[:300]
assert "1／2" in p and "50%" in p and "壓力 23,309" in p and "⏳" in p and "nav-current'>📝 龍飛陣分析" in p
with mock.patch.object(main, "_chart_png_b64", return_value="CCCC"):
    p = main.build_analyst_page({"docs": [d2, d1], "scorecard": sc2}, "2026-10-23")
assert p.index("id='d-2026-10-23'><h2>") > 0 and "id='d-2026-10-24'><details>" in p
assert "暫時未有分析" in main.build_analyst_page({"docs": [], "scorecard": None})
assert "讀取失敗" in main.build_analyst_page({}, None, "讀取失敗")
assert any(v == "analyst" for v, _ in main.PAGE_LINKS)
assert "技術分析僅供參考" not in p   # [R268]
print("analyst page ok")
# [R358] 分析圖頁唔再嵌入龍飛陣分析文章，只留連結
h = main.build_charts_page([])
assert "?view=analyst" in h and "龍飛陣分析" in h
# [R359] 改名斐波那契回撤分析圖；加番 NQ／ES／SPX／VIX（龍飛陣每日分析圖，唔放 HSI 重覆、唔放文章）
assert "斐波那契回撤分析圖" in main.build_charts_page([])
_orig = main._chart_png_b64
main._chart_png_b64 = lambda path: "QUJD"
try:
    doc = {"date": "2026-10-29", "markdown": "文章內容唔應該出現",
           "charts": {m: [f"ops/longfei/analyst/charts/2026-10-29/{m}_4h.png", f"ops/longfei/analyst/charts/2026-10-29/{m}_1d.png"]
                      for m in ("NQ", "ES", "SPX", "VIX", "HSI")}}
    sec = main._charts_markets_section(doc)
    for m in ("NQ", "ES", "SPX", "VIX"):
        assert f"<h3>{m}</h3>" in sec, m
    assert "<h3>HSI</h3>" not in sec and "文章內容" not in sec and "240 分鐘圖" in sec
    h = main.build_charts_page([], None, markets=sec)
    assert "<h3>NQ</h3>" in h and "暫時未有" not in h
    assert main._charts_markets_section(None) == "" and main._charts_markets_section({"charts": {}}) == ""
finally:
    main._chart_png_b64 = _orig
print("fib charts ok")
