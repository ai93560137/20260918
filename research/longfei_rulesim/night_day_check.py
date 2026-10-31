"""[IDEAS #156] 恒指期貨夜市方向預唔預測到下一個日市（MILESTONES「夜市 vs 日市」研究，限期 11-07）。

文獻：Cheng, Jiang & Ng 2004（J. Futures Markets）恒指期貨延長交易時段嘅資料有助解釋之後正常時段嘅現貨回報；
So & Tse 2004：期貨先反映資訊。即係夜市方向可能係下一個日市嘅線索。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，含夜市，約一年）。富途 time_key 係分鐘結束時間。
定義（曆日 C）：DC＝C 日 16:30 前最後一分鐘收市；NC＝C 晚夜市（17:15 → C+1 03:00）最後一分鐘收市；
  夜市回報 n＝NC − DC（點）。下一個日市（C+1，或者週末後第一個交易日）：
  入場＝09:40 嗰分鐘收市（避開 R353 開市封鎖），出場＝16:25 嗰分鐘收市；日市回報 d＝出場 − 入場。

預先登記（10-31，結果出嚟之前寫，唔再改）：
  只計 |n| ≥ 50 點嘅日子。成本每筆 2 點。
  A 順夜市：方向＝sign(n)，每筆 d×sign(n) − 2。
  B 逆夜市：方向＝−sign(n)，每筆 −d×sign(n) − 2。
  成功：A 或 B 筆數 ≥ 100、平均 ≥ +10 點、t ≥ 2、前後兩半平均都 > 0。
  另外描述性（唔判）：夜市幅度（高−低）中位數 ÷ 日市幅度中位數；夜市收市 → 翌日 09:15 開市跳空絕對值中位數。
用途（只係提案，真倉要使用者批）：A 或 B 過 → 提案將「夜市方向」加入 MHI AI context 做日市偏向；都唔過 → 唔改，
「夜市 vs 日市」研究只交描述性結果。

用法：python3 research/longfei_rulesim/night_day_check.py [--out 報告.json]（要 GCS 讀權）
"""
import argparse
import json
import math
import statistics
import sys
from datetime import time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402

COST = 2
MIN_NIGHT = 50
ENTRY_T, EXIT_T = time(9, 40), time(16, 25)


def sessions(bars):
    """曆日 → {"day": [bars 09:15<t<=16:30], "night": [bars 17:15 → 翌日 03:00]}（夜市掛返開始嗰個曆日）。"""
    out = {}
    for b in bars:
        t = b[0]
        m = t.time()
        if time(9, 15) < m <= time(16, 30):
            out.setdefault(t.date(), {"day": [], "night": []})["day"].append(b)
        elif m > time(17, 15):
            out.setdefault(t.date(), {"day": [], "night": []})["night"].append(b)
        elif m <= time(3, 0):
            out.setdefault((t - timedelta(days=1)).date(), {"day": [], "night": []})["night"].append(b)
    return out


def at(rows, tm):
    return next((b[4] for b in rows if b[0].time() == tm), None)


def build(bars):
    s = sessions(bars)
    days = sorted(d for d in s if s[d]["day"])
    rows = []
    for i, c in enumerate(days[:-1]):
        nx = days[i + 1]
        if not s[c]["night"] or (nx - c).days > 4:
            continue
        dc, nc = s[c]["day"][-1][4], s[c]["night"][-1][4]
        nd = s[nx]["day"]
        ent, ex = at(nd, ENTRY_T), at(nd, EXIT_T)
        if ent is None or ex is None:
            continue
        rows.append({"d": nx, "n": nc - dc, "d_ret": ex - ent, "gap": nd[0][1] - nc,
                     "night_rng": max(b[2] for b in s[c]["night"]) - min(b[3] for b in s[c]["night"]),
                     "day_rng": max(b[2] for b in nd) - min(b[3] for b in nd)})
    return rows


def st(xs):
    if len(xs) < 2:
        return {"n": len(xs)}
    m, sd = statistics.mean(xs), statistics.stdev(xs)
    return {"n": len(xs), "mean": round(m, 1), "t": round(m / (sd / math.sqrt(len(xs))), 2) if sd else None,
            "win": round(sum(x > 0 for x in xs) / len(xs), 3)}


def report(rows):
    sel = [r for r in rows if abs(r["n"]) >= MIN_NIGHT]
    split = sorted(r["d"] for r in sel)[len(sel) // 2]
    out = {"from": str(rows[0]["d"]), "to": str(rows[-1]["d"]), "pairs": len(rows), "selected": len(sel)}
    for name, k in (("A_follow", 1), ("B_fade", -1)):
        pnl = lambda rs: [k * r["d_ret"] * (1 if r["n"] > 0 else -1) - COST for r in rs]  # noqa: E731
        out[name] = {"all": st(pnl(sel)), "h1": st(pnl([r for r in sel if r["d"] < split])),
                     "h2": st(pnl([r for r in sel if r["d"] >= split]))}
        a = out[name]
        a["pass"] = bool(a["all"]["n"] >= 100 and a["all"]["mean"] >= 10 and (a["all"]["t"] or 0) >= 2
                         and a["h1"]["mean"] > 0 and a["h2"]["mean"] > 0)
    out["desc"] = {"night_range_med": statistics.median(r["night_rng"] for r in rows),
                   "day_range_med": statistics.median(r["day_rng"] for r in rows),
                   "gap_abs_med": statistics.median(abs(r["gap"]) for r in rows),
                   "night_abs_ret_med": statistics.median(abs(r["n"]) for r in rows)}
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
    text = json.dumps(report(build(um.load(raw))), ensure_ascii=False, indent=1, default=str)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
