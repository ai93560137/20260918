"""奇門遁甲知識庫頁：將知識庫 Markdown（私人 GCS qimen/kb/KB.md）轉成網頁。

講義有版權：呢個腳本本身唔含講義內容，輸出亦唔好 commit 入 repo。

用法：
  python3 scripts/gcp_agent.py cat --object qimen/kb/KB.md > /tmp/KB.md   （或直接用本機檔）
  python3 research/qimen/build_kb_page.py KB.md OUT_DIR [pages_dir]
輸出 OUT_DIR/index.html；有 pages_dir 就喺頁尾列出原相（相片以 pages/<名>.jpg 相對路徑載入）。
"""
import html
import re
import sys
from pathlib import Path


def inline(t):
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = t.replace("【手寫】", '<span class="hw">手寫</span>').replace("【？】", '<span class="q">未確定</span>')
    return t


def slug(i):
    return f"s{i}"


def convert(md):
    out, toc = [], []
    lines = md.split("\n")
    i, n, sec = 0, len(lines), 0
    while i < n:
        l = lines[i]
        if not l.strip() or l.strip() == "---":
            i += 1
        elif l.startswith("#"):
            lvl = len(l) - len(l.lstrip("#"))
            txt = l[lvl:].strip()
            if lvl == 2:
                sec += 1
                toc.append((slug(sec), txt))
                out.append(f'<h2 id="{slug(sec)}">{inline(txt)}</h2>')
            else:
                out.append(f"<h{lvl}>{inline(txt)}</h{lvl}>")
            i += 1
        elif l.startswith("|"):
            rows = []
            while i < n and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[2:]]
            h = "".join(f"<th>{inline(c)}</th>" for c in head)
            b = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
            out.append(f'<div class="wrap"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>')
        elif l.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(inline(lines[i][1:].strip()))
                i += 1
            out.append('<blockquote>' + "<br>".join(buf) + "</blockquote>")
        elif re.match(r"^(\d+\.|-)\s", l):
            ordered = l[0].isdigit()
            buf = []
            while i < n and re.match(r"^(\d+\.|-)\s", lines[i]):
                buf.append("<li>" + inline(re.sub(r"^(\d+\.|-)\s+", "", lines[i])) + "</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(buf)}</{tag}>")
        else:
            out.append(f"<p>{inline(l)}</p>")
            i += 1
    return "\n".join(out), toc


CSS = """
:root {
  /* 佈局：左邊目錄、右邊正文；細螢幕目錄橫排喺頂 */
  --ink:#1b2330; --paper:#f4f5f2; --card:#fff; --line:#d9ddd6; --accent:#8a1c1c; --muted:#5f6873; --hw:#1d4f91; --q:#9a6a00;
  --display:"Noto Serif TC","Songti TC",serif; --body:"Noto Sans TC","PingFang HK","Microsoft JhengHei",sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --ink:#e6e8ea; --paper:#14181d; --card:#1c2229; --line:#2f3740; --accent:#e0736a; --muted:#9aa3ad; --hw:#7fb0ee; --q:#e0b04a; color-scheme:dark; } }
:root[data-theme="dark"] {
  --ink:#e6e8ea; --paper:#14181d; --card:#1c2229; --line:#2f3740; --accent:#e0736a; --muted:#9aa3ad; --hw:#7fb0ee; --q:#e0b04a; color-scheme:dark; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:15px/1.7 var(--body); }
.layout { max-width:1180px; margin:0 auto; padding:24px 16px 56px; display:grid; grid-template-columns:210px minmax(0,1fr); gap:28px; }
nav { position:sticky; top:16px; align-self:start; display:grid; gap:6px; font-size:14px; }
nav a { color:var(--ink); text-decoration:none; border-left:3px solid var(--line); padding:2px 10px; }
nav a:hover, nav a:focus-visible { border-color:var(--accent); color:var(--accent); outline:none; }
main { display:grid; gap:14px; min-width:0; }
h1,h2,h3 { font-family:var(--display); text-wrap:balance; margin:0; }
h1 { font-size:28px; color:var(--accent); }
h2 { font-size:21px; border-bottom:2px solid var(--accent); padding-bottom:4px; margin-top:22px; scroll-margin-top:12px; }
h3 { font-size:16px; margin-top:8px; }
p, ul, ol { margin:0; max-width:74ch; } ul,ol { padding-left:22px; }
blockquote { margin:0; border-left:4px solid var(--q); background:var(--card); padding:10px 14px; font-size:14px; }
code { font-family:ui-monospace,Menlo,monospace; font-size:13px; background:var(--card); border:1px solid var(--line); padding:0 4px; }
.wrap { overflow-x:auto; background:var(--card); border:1px solid var(--line); }
table { border-collapse:collapse; width:100%; font-size:14px; }
th,td { padding:7px 10px; border:1px solid var(--line); text-align:left; vertical-align:top; }
th { background:var(--paper); color:var(--muted); font-weight:500; white-space:nowrap; }
.hw { font-size:12px; color:var(--hw); border:1px solid currentColor; padding:0 5px; margin-right:4px; white-space:nowrap; }
.q { font-size:12px; color:var(--q); border:1px solid currentColor; padding:0 5px; margin-left:2px; white-space:nowrap; }
.pages { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
figure { margin:0; background:var(--card); border:1px solid var(--line); padding:8px; display:grid; gap:6px; }
figure img { max-width:100%; height:auto; display:block; }
figcaption { font-size:13px; color:var(--muted); }
@media (max-width:820px) { .layout { grid-template-columns:1fr; } nav { position:static; grid-auto-flow:column; overflow-x:auto; white-space:nowrap; } }
"""


def main():
    md_path, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    pages_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    md = md_path.read_text(encoding="utf-8")
    title_line = md.split("\n", 1)[0].lstrip("# ").strip()
    body, toc = convert(md.split("\n", 1)[1])
    figs = ""
    if pages_dir:
        imgs = sorted(p.name for p in pages_dir.glob("*.jpg"))
        figs = '<h2 id="pages">講義原相</h2><div class="pages">' + "".join(
            f'<figure><a href="pages/{html.escape(x)}"><img loading="lazy" src="pages/{html.escape(x)}" alt="{html.escape(x)}"></a>'
            f"<figcaption>{html.escape(x)}</figcaption></figure>" for x in imgs) + "</div>"
        toc.append(("pages", "講義原相"))
    nav = "".join(f'<a href="#{s}">{html.escape(t)}</a>' for s, t in toc)
    page = f"""<!DOCTYPE html>
<html lang="zh-Hant-HK"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>奇門遁甲知識庫</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="layout"><nav aria-label="目錄">{nav}</nav>
<main><h1>{html.escape(title_line)}</h1>
{body}
{figs}</main></div></body></html>"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    print("wrote", out_dir / "index.html", len(page))


if __name__ == "__main__":
    main()
