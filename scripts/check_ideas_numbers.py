"""check_ideas_numbers.py — IDEAS.md 編號唔准重複（2026-11-06，PR #649 之後；號段見 IDEAS.md 規則 7）。

只睇表格列（行首「| 數字 |」）；第四節矛盾清單用「1.」唔受影響。有重複 → 列出每個號嘅行號，exit 1。
用法：python3 scripts/check_ideas_numbers.py [IDEAS.md 路徑]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROW = re.compile(r"^\|\s*#?(\d+)\s*\|")


def duplicates(text: str) -> dict[int, list[int]]:
    seen: dict[int, list[int]] = {}
    for i, line in enumerate(text.splitlines(), 1):
        m = ROW.match(line)
        if m:
            seen.setdefault(int(m.group(1)), []).append(i)
    return {n: lines for n, lines in seen.items() if len(lines) > 1}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "IDEAS.md")
    dup = duplicates(path.read_text(encoding="utf-8"))
    if not dup:
        print(f"{path.name}：冇重複編號")
        return 0
    for n, lines in sorted(dup.items()):
        print(f"::error file={path.name},line={lines[-1]}::IDEAS #{n} 重複（第 {'、'.join(map(str, lines))} 行）；遲登記嗰行改用自己陣號段內嘅新號（IDEAS.md 規則 7）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
