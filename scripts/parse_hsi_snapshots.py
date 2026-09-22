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
import json
import re
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "research_output"
OUT_DIR = Path(__file__).resolve().parent / "pointintime"

BULLET_RE = re.compile(r"^\*(\d{1,5})\s+(.+?)\s*$", re.MULTILINE)
SEHK_RE = re.compile(r"\{\{SEHK\|(\d{1,5})\}\}")
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
REF_RE = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.DOTALL)


def clean_wiki_name(raw: str) -> str:
    """`[[Bank of China (Hong Kong)|BOC Hong Kong (Holdings) Ltd]]` -> 顯示文字；
    去掉 <ref>、表格前綴 `|`、多餘空白。"""
    s = REF_RE.sub("", raw).strip().lstrip("|").strip()
    s = LINK_RE.sub(lambda m: m.group(2) or m.group(1), s)
    return re.sub(r"\s+", " ", s.replace("'''", "").replace("''", "")).strip()


def parse_bullet_format(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).zfill(4), clean_wiki_name(m.group(2))) for m in BULLET_RE.finditer(text)]


def parse_sehk_format(text: str) -> list[tuple[str, str]]:
    """表格列：`|{{SEHK|5}}` 下一個 `|` 開頭的儲存格是公司名；
    也容忍同一行 `||` 分隔的寫法。"""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = SEHK_RE.search(line)
        if not m:
            continue
        code = m.group(1).zfill(4)
        name = ""
        if "||" in line:
            cells = line.split("||")
            if len(cells) > 1:
                name = clean_wiki_name(cells[1])
        else:
            for nxt in lines[i + 1:i + 4]:
                if nxt.startswith("|-") or nxt.startswith("|}"):
                    break
                if nxt.startswith("|"):
                    name = clean_wiki_name(nxt)
                    break
        out.append((code, name))
    return out


def parse_snapshot(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    rows = parse_sehk_format(text)
    if not rows:
        rows = parse_bullet_format(text)
    # 保留原順序但去重（sortable table 有時同一代碼因排序輔助行重複出現）
    seen = set()
    out = []
    for code, name in rows:
        if code not in seen:
            seen.add(code)
            out.append((code, name))
    return out


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    snapshots = sorted(SRC_DIR.glob("hsi_wikipedia_snapshot_*.txt"))
    if not snapshots:
        raise SystemExit(f"找不到快照檔案，先跑 research_hsi_history.py（在 {SRC_DIR}）")

    corrections_path = OUT_DIR / "corrections.json"
    corrections = json.loads(corrections_path.read_text(encoding="utf-8")) if corrections_path.exists() else {}

    summary = []
    names: dict[str, dict[str, str]] = {}  # {"0005.HK": {"2010": "HSBC Holdings plc", ...}}
    for path in snapshots:
        year = path.stem.rsplit("_", 1)[-1]
        rows = parse_snapshot(path)
        # 套用人工更正（Wikipedia 當年版本本身寫錯的代碼，見 corrections.json）
        fixed = []
        for code, name in rows:
            fix = corrections.get(year, {}).get(f"{code}.HK")
            if fix is None:
                fixed.append((code, name))
            elif fix["to"]:
                fixed.append((fix["to"][:-3], name))
                print(f"{year}: 更正 {code}.HK -> {fix['to']}（{name}）")
            else:
                print(f"{year}: 刪除 {code}.HK（{name}）")
        rows = fixed
        out_path = OUT_DIR / f"hsi_{year}.txt"
        out_path.write_text(
            f"# 恒生指數 {year} 年中前後的成分股快照（近似 point-in-time，\n"
            f"# 來源：Wikipedia「Hang Seng Index」條目該時間點的修訂版本，\n"
            f"# 非官方權威來源，見 scripts/parse_hsi_snapshots.py 說明）\n"
            + "\n".join(f"{c}.HK" for c, _ in rows) + "\n",
            encoding="utf-8",
        )
        for code, name in rows:
            names.setdefault(f"{code}.HK", {})[year] = name
        summary.append((year, len(rows)))
        print(f"{year}: {len(rows)} 檔 -> {out_path}")

    # 名字對照表給每日資料品質檢查用（scripts/check_data_quality.py）：
    # 港交所代碼會在下市後被重新分配給別家公司，同一代碼在不同年代可能是
    # 完全不同的公司——價格歷史會被靜默拼接，必須靠名字比對抓出來。
    names_path = OUT_DIR / "hsi_names.json"
    names_path.write_text(json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
    print(f"\n名字對照表: {len(names)} 檔 -> {names_path}")
    print("年度成分股數量:", summary)


if __name__ == "__main__":
    main()
