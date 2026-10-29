"""[IDEAS #147] 恒指期貨開市時段波動：09:30 A 股開市嗰幾分鐘係咪特別亂（入場質素研究 IDEAS #136 嘅一部分）。

起因：10-28 MHI 真倉 09:30:07 落市價單，決策價 23,054、成交 23,087（差 33 點）；嗰一分鐘 MHI 由 23,047 扯到 23,147，
成交 2,270 張（平時 100–500）。文獻：Tang & Lui（2002）恒指開市後頭 15–30 分鐘波動明顯高過期貨，主要係雜訊交易。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，約一年）；用每分鐘幅度（高 − 低，點）同成交量，按「分鐘」平均。
富途 1 分鐘 K 嘅 time_key 係嗰分鐘「結束」時間（09:31 ＝ 09:30–09:31）。

預先登記（10-29，結果出嚟之前寫，唔再改）：
  A 09:31–09:35 五分鐘平均每分鐘幅度 ≥ 10:00–11:30 中位數 × 1.5，而且前後兩半樣本都成立 → A 成立
  B 09:16–09:20（港股期貨開市頭 5 分鐘）同樣標準
用途（只係提案，真倉要使用者批）：A 成立 → 提案 MHI 真倉 09:28–09:36 唔開新倉（同 R348 一樣只停開新倉，有倉照管）；
B 成立 → 提案開市頭 5 分鐘唔開新倉。都唔成立 → 唔改，10-28 嗰次當個別事件。

用法：python3 research/longfei_rulesim/open_vol_check.py [--out 報告.json]（要 GCS 讀權）
"""
import argparse
import json
import statistics
import sys
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402

WIN = {"A_0931_0935": (time(9, 31), time(9, 35)), "B_0916_0920": (time(9, 16), time(9, 20)),
       "base_1000_1130": (time(10, 0), time(11, 30))}


def summarize(bars):
    by_min, days = {}, set()
    for t, o, h, lo, c in bars:
        if time(9, 15) < t.time() <= time(16, 30):
            by_min.setdefault(t.time(), []).append((t.date(), h - lo))
            days.add(t.date())
    days = sorted(days)
    split = days[len(days) // 2] if days else None

    def win_avg(name, part=None):
        a, b = WIN[name]
        xs = [r for m, rows in by_min.items() if a <= m <= b for d, r in rows
              if part is None or (d < split) == (part == 1)]
        return xs

    out = {"days": len(days), "from": str(days[0]) if days else None, "to": str(days[-1]) if days else None}
    for part in (None, 1, 2):
        base = statistics.median(win_avg("base_1000_1130", part))
        key = "all" if part is None else f"h{part}"
        out[key] = {"base_median_range": round(base, 1)}
        for w in ("A_0931_0935", "B_0916_0920"):
            m = statistics.mean(win_avg(w, part))
            out[key][w] = {"mean_range": round(m, 1), "ratio": round(m / base, 2)}
    out["A_pass"] = all(out[k]["A_0931_0935"]["ratio"] >= 1.5 for k in ("all", "h1", "h2"))
    out["B_pass"] = all(out[k]["B_0916_0920"]["ratio"] >= 1.5 for k in ("all", "h1", "h2"))
    prof = {m.strftime("%H:%M"): round(statistics.mean(r for _, r in rows), 1)
            for m, rows in sorted(by_min.items()) if time(9, 15) < m <= time(10, 0)}
    out["profile_0916_1000"] = prof
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    from google.cloud import storage
    b = storage.Client().bucket(um.GCS_BUCKET)
    raw = {}
    for x in b.list_blobs(prefix=um.GCS_BARS):
        try:
            raw[x.name.rsplit("/", 1)[1][:10]] = json.loads(x.download_as_bytes())
        except Exception:  # noqa: BLE001  今日檔案寫緊
            continue
    res = summarize(um.load(raw))
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
