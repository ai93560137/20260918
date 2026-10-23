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
