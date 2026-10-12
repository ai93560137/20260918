#!/usr/bin/env python3
"""論文登記用摘錄：從 PDF 抽出含關鍵詞的段落（逐字、標頁碼），全文不進 git。登記：forex_research/FOMC_DATA_REQUEST.md 第 1 節。

    python3 scripts/paper_excerpt.py <pdf> <out.md> [--max-lines 900]

用 pdftotext -layout（poppler）；沒有就退到 pypdf。第 1、2 頁（摘要／引言）全文收錄；其餘頁只收含關鍵詞的段落與表格頁。
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

KEYS = [r"federal funds futures", r"fed funds futures", r"futures[- ]implied", r"implied (?:target|rate|change)", r"two[- ]days?", r"day[s]? (?:before|prior|ahead)",
        r"\bt\s*[-−–]\s*[123]\b", r"three days", r"spread", r"expected (?:hike|cut|change|target)", r"surprise", r"\btable\b", r"sharpe", r"transaction cost",
        r"bid[- ]ask", r"sample", r"scheduled", r"unscheduled", r"basis points?", r"\bbps?\b", r"t-stat", r"t\s*=\s*\d", r"R\^?2|R-squared", r"2:15|2:00|12:30|14:15|14:00",
        r"announcement", r"dollar index", r"equally[- ]weighted", r"trade[- ]weighted", r"subsample|sub-sample", r"robust", r"zero lower bound|ZLB", r"datastream|bloomberg|reuters|wm/r",
        r"close|closing", r"london|new york", r"strategy", r"return[s]? (?:of|is|are|average)", r"average", r"significan", r"mechanism|information|slow", r"FOMC meetings?", r"199\d|20[012]\d"]
RX = re.compile("|".join(KEYS), re.I)


def pages_from_pdf(pdf: Path) -> list[str]:
    if shutil.which("pdftotext"):
        txt = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
        return txt.split("\f")
    try:
        from pypdf import PdfReader
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--user", "pypdf"], check=False)
        from pypdf import PdfReader
    return [p.extract_text() or "" for p in PdfReader(str(pdf)).pages]


def info(pdf: Path) -> str:
    if shutil.which("pdfinfo"):
        return subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    return f"(pdfinfo 不可用) size={pdf.stat().st_size}"


def paragraphs(page: str) -> list[str]:
    out, cur = [], []
    for line in page.splitlines():
        if line.strip():
            cur.append(line.rstrip())
        elif cur:
            out.append("\n".join(cur)); cur = []
    if cur:
        out.append("\n".join(cur))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--max-lines", type=int, default=900)
    a = ap.parse_args()
    if not a.pdf.exists() or a.pdf.stat().st_size < 10_000 or a.pdf.read_bytes()[:4] != b"%PDF":
        sys.exit(f"找不到有效的 PDF：{a.pdf}（不存在、太小或不是 PDF）。請先用瀏覽器下載後放到該路徑再跑。")
    pages = pages_from_pdf(a.pdf)
    L = [f"# 摘錄：{a.pdf.name}（逐字，標頁碼；全文留在 VM 不進 git）", "", "```", info(a.pdf).strip(), "```", "",
         f"共 {len(pages)} 頁；關鍵詞選段，第 1–2 頁全文。登記用，見 forex_research/FOMC_DATA_REQUEST.md 第 1 節。", ""]
    n = 0
    for i, pg in enumerate(pages, 1):
        paras = paragraphs(pg)
        if not paras:
            continue
        is_table = bool(re.search(r"^\s*Table\s+\d", pg, re.M))
        keep = paras if (i <= 2 or is_table) else [p for p in paras if RX.search(p) and len(p) > 40]
        if not keep:
            continue
        L.append(f"## p.{i}" + ("（表格頁，全頁收錄）" if is_table and i > 2 else ""))
        for p in keep:
            L.append("```"); L.append(p); L.append("```")
            n += p.count("\n") + 3
        L.append("")
        if n > a.max_lines:
            L.append(f"（已達 {a.max_lines} 行上限，其餘頁略；需要時指定頁碼再抽）")
            break
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"寫入 {a.out}（約 {n} 行，{len(pages)} 頁）")


if __name__ == "__main__":
    main()
