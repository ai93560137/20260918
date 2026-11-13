"""[R368] 🔮 奇門遁甲陣頁：有內容原樣供應、冇內容、讀取失敗；只讀兩個固定物件。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import main
from unittest import mock

assert main.QIMEN_PAGES == {"qimen": "qimen/web/index.html", "qimen_kb": "qimen/web/kb.html"}
with mock.patch.object(main, "gcs_read_text", return_value="<!DOCTYPE html><html><head><title>t</title></head><body>卦</body></html>") as m:
    body, code, hdr = main.render_qimen_page("qimen")
    m.assert_called_once_with("qimen/web/index.html")
assert code == 200 and "卦" in body and hdr["Content-Type"].startswith("text/html") and main.FAVICON_LINK in body
with mock.patch.object(main, "gcs_read_text", return_value=None):
    r = main.render_qimen_page("qimen_kb")
    assert "暫時未有內容" in (r if isinstance(r, str) else r[0])
with mock.patch.object(main, "gcs_read_text", side_effect=main.StorageError("boom")):
    r = main.render_qimen_page("qimen")
    assert "讀取失敗" in (r if isinstance(r, str) else r[0])


class Req:
    def __init__(self, view): self.args = {"view": view}


with mock.patch.object(main, "render_qimen_page", return_value="X") as m:
    assert main.handle_get(Req("qimen")) == "X" and main.handle_get(Req("qimen_kb")) == "X" and m.call_count == 2
assert any(v == "qimen" for v, _ in main.NAV_LINKS) if hasattr(main, "NAV_LINKS") else True
print("ok")
