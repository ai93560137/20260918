"""[IDEAS #1028] 影子總表網頁區塊：有資料就顯示、冇資料唔顯示、⭐ 組合排第一。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau"))
import page  # noqa: E402

F2 = lambda x, f="{:+.2f}": "—" if x is None else f.format(x)  # noqa: E731
SB = {"meta": {"run_utc": "2026-11-09 22:40", "start": "2026-11-08T23:00", "bars_to": "2026-11-09 21:55"}, "criteria": "各條 30 張判",
      "singles": [{"name": "933 rev15", "idea": "#1001", "n": 2, "sum": -1.3, "avg": -0.65, "pf": 0.2, "mdd": 1.6, "streak": 1,
                   "recent": [{"utc": "11-09 01:00", "side": "SELL", "r": -1.63, "open": False}, {"utc": "11-09 00:10", "side": "BUY", "r": 0.37, "open": True}]}],
      "combos": [{"keys": ["rev15", "rev60"], "name": "rev15＋rev60", "is_1027": False, "overlap": True, "n": 1, "sum": 0.1, "avg": 0.1, "pf": None, "mdd": 0.0},
                 {"keys": ["rev15", "round", "d1brk"], "name": "rev15＋round＋d1brk", "is_1027": True, "overlap": False, "n": 2, "sum": -1.3, "avg": -0.65, "pf": 0.2, "mdd": 1.6}]}


def run():
    ok = 0
    h = page.shadow_block(SB, F2)
    assert "影子總表" in h and "2／30" in h; ok += 1
    assert "11-09 00:10 BUY +0.37（未完）" in h; ok += 1
    assert h.index("⭐ rev15＋round＋d1brk") < h.index("⚠ rev15＋rev60"); ok += 1
    assert page.shadow_block(None, F2) == "" and page.shadow_block({"singles": []}, F2) == ""; ok += 1
    assert "影子總表" in page._forward_section({"shadow": SB}); ok += 1
    assert page._forward_section({"shadow": None}) == ""; ok += 1
    print(f"通過 {ok} / 失敗 0")


if __name__ == "__main__":
    run()
