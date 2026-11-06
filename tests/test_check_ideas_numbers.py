"""check_ideas_numbers.py：IDEAS.md 重複編號檢查。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_ideas_numbers as ck  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class CheckIdeasNumbersTest(unittest.TestCase):
    def test_finds_duplicates_only_in_table_rows(self):
        text = "| # | 名 |\n|---|---|\n| 28 | 風揚 |\n| 29 | x |\n| 28 | 天覆 |\n\n1. 矛盾一\n1. 矛盾二\n| 1000–1999 | 🌌 天覆陣 |\n"
        self.assertEqual(ck.duplicates(text), {28: [3, 5]})

    def test_hash_prefix_counts(self):
        self.assertEqual(ck.duplicates("| #5 | a |\n| 5 | b |\n"), {5: [1, 2]})

    def test_repo_ideas_has_no_duplicates(self):
        self.assertEqual(ck.duplicates((ROOT / "IDEAS.md").read_text(encoding="utf-8")), {})


if __name__ == "__main__":
    unittest.main()
