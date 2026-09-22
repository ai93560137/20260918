#!/usr/bin/env python3
"""把 research_output/hsi_wikipedia_snapshot_<year>.txt 的原始 wikitext
解析成逐年 point-in-time 成分股代碼清單，存進 scripts/pointintime/。

純文字解析，不需要網路，本機可直接跑：
    python3 scripts/parse_hsi_snapshots.py

**這不是官方權威來源**——是 Wikipedia 條目在某個過去時間點的內容，
編輯者記錄的「當時成分股」，可能有滯後或錯漏，但比「用現在的成分股表
測過去」誠實得多，且免費（見 MOMENTUM_HK_BACKTEST.md）。

兩種年代的表格格式：
- 2010-2022：按 sub-index 分段的條列格式 `*0005 [[HSBC Holdings plc]]`
- 2023 起：`{{SEHK|N}}` 模板的 sortable wikitable
"""
import re
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "research_output"
OUT_DIR = Path(__file__).resolve().parent / "pointintime"

BULLET_RE = re.compile(r"^\*(\d{1,5})\s+(.+?)\s*$", re.MULTILINE)
SEHK_RE = re.compile(r"\{\{SEHK\|(\d{1,5})\}\}")


def parse_bullet_format(text: str) -> list[str]:
    return [m.group(1).zfill(4) for m in BULLET_RE.finditer(text)]


def parse_sehk_format(text: str) -> list[str]:
    return [m.group(1).zfill(4) for m in SEHK_RE.finditer(text)]


def parse_snapshot(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    codes = parse_sehk_format(text)
    if not codes:
        codes = parse_bullet_format(text)
    # 保留原順序但去重（sortable table 有時同一代碼因排序輔助行重複出現）
    seen = set()
    out = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    snapshots = sorted(SRC_DIR.glob("hsi_wikipedia_snapshot_*.txt"))
    if not snapshots:
        raise SystemExit(f"找不到快照檔案，先跑 research_hsi_history.py（在 {SRC_DIR}）")

    summary = []
    for path in snapshots:
        year = path.stem.rsplit("_", 1)[-1]
        codes = parse_snapshot(path)
        out_path = OUT_DIR / f"hsi_{year}.txt"
        out_path.write_text(
            f"# 恒生指數 {year} 年中前後的成分股快照（近似 point-in-time，\n"
            f"# 來源：Wikipedia「Hang Seng Index」條目該時間點的修訂版本，\n"
            f"# 非官方權威來源，見 scripts/parse_hsi_snapshots.py 說明）\n"
            + "\n".join(f"{c}.HK" for c in codes) + "\n",
            encoding="utf-8",
        )
        summary.append((year, len(codes)))
        print(f"{year}: {len(codes)} 檔 -> {out_path}")

    print("\n年度成分股數量:", summary)


if __name__ == "__main__":
    main()
