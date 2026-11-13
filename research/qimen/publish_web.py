"""將記錄簿同知識庫網頁整成 tnt-hk.com 版本（?view=qimen、?view=qimen_kb；main.py R368 由 GCS qimen/web/ 原樣供應）。

tnt-hk.com 係公開網站：呢度會加頁頂連結、拎走經度。測人只可以有代號。

用法：
  python3 research/qimen/build_page.py
  python3 research/qimen/build_kb_page.py KB.md KB_OUT
  python3 research/qimen/publish_web.py research/qimen/page.html KB_OUT/index.html WEB_OUT
  python3 scripts/gcp_agent.py put --any-prefix --object qimen/web/index.html --file WEB_OUT/index.html
  python3 scripts/gcp_agent.py put --any-prefix --object qimen/web/kb.html --file WEB_OUT/kb.html
"""
import re
import sys
from pathlib import Path

NAV = ('<p style="max-width:1180px;margin:0 auto;padding:12px 16px 0;font-size:14px">'
       '<a href="?view=welcome">← 主頁</a> ｜ <a href="?view=qimen">🔮 記錄簿</a> ｜ <a href="?view=qimen_kb">📖 知識庫</a>'
       '　<span style="opacity:.7">全部紙上，占卦結果唔係落單指令或投資建議。</span></p>')


def web(src):
    s = Path(src).read_text(encoding="utf-8")
    s = re.sub(r"；經度約 [0-9.]+°[EW]", "", s)
    assert "°E" not in s and "°W" not in s
    return s.replace("<body>", "<body>" + NAV, 1)


if __name__ == "__main__":
    rec, kb, out = sys.argv[1:4]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(web(rec), encoding="utf-8")
    (out / "kb.html").write_text(web(kb), encoding="utf-8")
    print("wrote", out / "index.html", out / "kb.html")
