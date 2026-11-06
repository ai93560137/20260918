#!/usr/bin/env python3
"""由 tradingview/data_external/levels.json 生成指令台網頁內嵌數據行（公開 artifact 寫唔到雲端庫時用）。

用法：python3 .github/scripts/artifact_embed.py hsi|mgc
輸出一行 `/*EMBED*/var EMBED = {...};/*EMBED_END*/`，用 edit_version 替換網頁中同一標記行。
網頁 script 會比較內嵌 asof 與雲端 asof，揀較新嗰份顯示。
"""
import json, sys, pathlib
key = sys.argv[1]
lv = json.loads((pathlib.Path(__file__).resolve().parents[2] / "tradingview/data_external/levels.json").read_text())
src = lv[key]
doc = {k: src[k] for k in ("h1", "l1", "h2", "l2", "h3", "l3", "dates", "quote", "source")}
doc["asof"] = lv["fetched_at"]
if key == "mgc" and "fut" in src:
    doc["fut"] = src["fut"]
print("/*EMBED*/var EMBED = " + json.dumps({key: doc}, ensure_ascii=False, separators=(",", ":")) + ";/*EMBED_END*/")
