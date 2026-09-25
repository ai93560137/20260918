#!/usr/bin/env python3
"""投資人說明書 PDF：stock_research/TT_ALL_INVESTOR_BRIEF.md → HTML → PDF（Chromium headless，中文用文泉驛正黑）。

    python3 scripts/tt_all_pdf.py                # → stock_research/TT_ALL_INVESTOR_BRIEF.pdf
"""
import html
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "stock_research" / "TT_ALL_INVESTOR_BRIEF.md"
HTML_OUT = ROOT / "stock_research" / "TT_ALL_INVESTOR_BRIEF.html"
PDF_OUT = ROOT / "stock_research" / "TT_ALL_INVESTOR_BRIEF.pdf"
CHROME = next((p for p in [Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome"), *Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")] if p.exists()), None)

CSS = """
@page{size:A4;margin:16mm 14mm 18mm 14mm}
body{font-family:"Noto Sans CJK TC","Noto Sans TC","WenQuanYi Zen Hei","PingFang TC",sans-serif;font-size:10.5pt;line-height:1.55;color:#1E2A32;margin:0}
h1{font-size:20pt;margin:0 0 4pt;letter-spacing:.02em}
h2{font-size:13.5pt;margin:16pt 0 6pt;padding-bottom:3pt;border-bottom:1.5px solid #0E6F68;color:#0B5B55}
p{margin:5pt 0}
.cover{border-left:5px solid #0E6F68;padding-left:10pt;margin-bottom:12pt}
.cover .sub{color:#66707A;font-size:9.5pt}
.badge{display:inline-block;background:#E3F2EE;color:#0B5B55;border-radius:4px;padding:1pt 7pt;font-size:9pt;font-weight:600;margin-right:6pt}
table{border-collapse:collapse;width:100%;font-size:8.2pt;margin:6pt 0;page-break-inside:auto}
th,td{border-bottom:1px solid #DDDBD3;padding:3pt 4pt;text-align:right;white-space:normal;font-variant-numeric:tabular-nums;vertical-align:top}
table.num th,table.num td{white-space:nowrap}
table:not(.num) th,table:not(.num) td{text-align:left}
th{background:#F1F0EA;color:#4A545C;font-weight:600;text-align:right}
td:first-child,th:first-child{text-align:left}
tr{page-break-inside:avoid}
ol,ul{padding-left:18pt;margin:4pt 0}li{margin:2pt 0}
code{font-family:"DejaVu Sans Mono",monospace;font-size:9pt;background:#F1F0EA;padding:0 3pt}
.note{color:#66707A;font-size:9pt}
.wide{font-size:7.6pt}
.foot{margin-top:14pt;padding-top:6pt;border-top:1px solid #DDDBD3;color:#66707A;font-size:8.5pt}
"""


def inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


def md_to_html(md: str) -> str:
    out, i, lines = [], 0, md.splitlines()
    list_type = None
    def close_list():
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1]):
            close_list()
            hdr = [c.strip() for c in ln.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            def emit(h, rs, cls):
                out.append(f"<table{cls}><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in h) + "</tr></thead><tbody>")
                for r in rs:
                    out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
                out.append("</tbody></table>")
            if len(hdr) > 14:                      # 太寬：拆成兩張，第一欄（市場）兩張都保留
                k = (len(hdr) + 1) // 2
                emit(hdr[:k], [r[:k] for r in rows], ' class="num wide"')
                emit([hdr[0]] + hdr[k:], [[r[0]] + r[k:] for r in rows], ' class="num wide"')
            elif len(hdr) > 4:
                emit(hdr, rows, ' class="num"')
            else:
                emit(hdr, rows, "")
            continue
        if ln.startswith("# "):
            close_list(); i += 1; continue                      # 標題另做封面
        if ln.startswith("## "):
            close_list(); out.append(f"<h2>{inline(ln[3:])}</h2>"); i += 1; continue
        m = re.match(r"^(\d+)\. (.*)$", ln)
        if m:
            if list_type != "ol":
                close_list(); out.append("<ol>"); list_type = "ol"
            out.append(f"<li>{inline(m.group(2))}</li>"); i += 1; continue
        if ln.startswith("- "):
            if list_type != "ul":
                close_list(); out.append("<ul>"); list_type = "ul"
            out.append(f"<li>{inline(ln[2:])}</li>"); i += 1; continue
        if not ln.strip():
            close_list(); i += 1; continue
        close_list()
        para = [ln]
        while i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith(("#", "|", "- ")) and not re.match(r"^\d+\. ", lines[i + 1]):
            i += 1; para.append(lines[i])
        out.append(f"<p>{inline(' '.join(para))}</p>"); i += 1
    close_list()
    return "\n".join(out)


def main() -> None:
    md = SRC.read_text(encoding="utf-8")
    body = md_to_html(md)
    cover = f"""<div class="cover"><h1>鳥翔 · 趨勢模板全部等權策略</h1>
<div class="sub">投資人說明書 · {date.today().isoformat()} · 陣名「鳥翔」已對號、正式發名待前向驗證</div>
<p><span class="badge">回測 🔍 有希望未證實</span><span class="badge">9 市場 · 2005–2026</span><span class="badge">衛星倉 ≤ 10%</span></p></div>"""
    foot = '<div class="foot">本文件為研究記錄與回測結果的整理，不構成投資建議。回測數據來自 Yahoo Finance 日線（候選池只含現存股票，存在倖存者偏差），全部扣除交易成本；未來表現不保證與回測一致。研究方法與全部判決見倉庫 stock_research/ 資料夾。</div>'
    doc = f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><title>鳥翔 投資人說明書</title><style>{CSS}</style></head><body>{cover}{body}{foot}</body></html>'
    HTML_OUT.write_text(doc, encoding="utf-8")
    if not CHROME:
        print("找不到 Chromium，只輸出 HTML", file=sys.stderr)
        return
    cmd = [str(CHROME), "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={PDF_OUT}", HTML_OUT.as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": "/tmp"})
    if not PDF_OUT.exists():
        print(r.stderr[-800:], file=sys.stderr)
        sys.exit(1)
    print(PDF_OUT, PDF_OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
