"""使用者 11-02：分析原文 PDF 清單頁同開檔（?view=user_notes／user_note&f=）。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import main
from unittest import mock


class Req:
    def __init__(self, **args):
        self.args = args


class Blob:
    size = 10

    def download_as_bytes(self):
        return b"%PDF-1.4 x"


class Bucket:
    def __init__(self, blob):
        self.blob, self.asked = blob, []

    def get_blob(self, name):
        self.asked.append(name)
        return self.blob


app = main.app if hasattr(main, "app") else None
idx = [{"file": "2026-11-02_1958.pdf", "posted_hkt": "2026-11-02 19:58", "title": "NQ 日K <b>", "images": 1},
       {"file": "../x.pdf", "posted_hkt": "x", "title": "壞", "images": 0}]
import flask
ctx = flask.Flask("t").test_request_context()
ctx.push()
main._analyst_new_results = lambda *a, **k: None   # 導覽列提示唔關事
with mock.patch.object(main, "gcs_read_json", return_value=idx):
    h = main.handle_user_notes_get(Req())
assert "?view=user_note&f=2026-11-02_1958.pdf" in h and "NQ 日K &lt;b&gt;" in h and "壞" not in h, h[-600:]
with mock.patch.object(main, "gcs_read_json", return_value=None):
    assert "暫時未有" in main.handle_user_notes_get(Req())
b = Bucket(Blob())
with mock.patch.object(main, "_bucket", return_value=b):
    r = main.handle_user_notes_get(Req(f="2026-11-02_1958.pdf"))
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.get_data().startswith(b"%PDF")
    assert b.asked == ["ops/longfei/analyst/user_notes/2026-11-02_1958.pdf"]
    assert main.handle_user_notes_get(Req(f="../secret.json")).status_code == 400
with mock.patch.object(main, "_bucket", return_value=Bucket(None)):
    assert main.handle_user_notes_get(Req(f="2026-11-02_1958.pdf")).status_code == 404
# 分析頁頂有連結
assert "?view=user_notes" in main.build_analyst_page({"docs": []}, None, "x")
ctx.pop()
print("user notes ok")
