"""[IDEAS #153] 恒指期貨「連續同向 K 線之後追唔追」（MILESTONES 入場質素研究；IDEAS #136 R286 入場特徵延伸）。

起因：MHI 真倉 6/19 筆一開倉就錯，好多係「連跌幾支之後追沽」。文獻：Grant, Wolf & Yu 2005（J. Banking & Finance）
美國指數期貨開市大幅移動後日內明顯反轉；arXiv 2605.04004 MNQ 動能訊號多數捉到假突破之後嘅反轉。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘，約一年）→ 合成 5 分鐘 K（富途 time_key 係分鐘結束時間）。
時段分開計（唔跨時段）：早市 09:15–12:00、午市 13:00–16:30、夜市 17:15–03:00。

預先登記（10-30，結果出嚟之前寫，唔再改）：
  訊號：連續 4 支 5 分鐘 K 同方向（收 > 開＝升；收 < 開＝跌；平嘅斷連）；第 4 支收市嗰刻出訊號（第 5、6 支唔再出）。
        訊號 K 收市要喺時段結束前 ≥ 60 分鐘；09:15–09:40 開市亂段（R353）唔出訊號。
  A 追：下一支 5 分鐘開市價順連續方向入場，訊號後 60 分鐘收市平；成本每筆 2 點。
  B 等反彈：訊號後 30 分鐘內，價格逆方向回到連續段幅度（4 支最高－最低）嘅 38.2% → 喺嗰個價入場（限價），同 A 同一時間平；
        30 分鐘內冇回到就唔做（當 0 點）。成本每筆 2 點。
  對照 C：同時段所有 5 分鐘收市（唔係訊號），順「上一支 K 方向」入場，同樣 60 分鐘平。
  量度：每筆點數（順方向）、頭 30 分鐘最大逆向（MAE）。
成功標準：
  樣本 ≥ 300 個訊號。
  「唔追」成立：A 平均（扣成本）< 0，前後兩半都 < +2 點；而且 A 頭 30 分鐘 MAE 中位數 ≥ C 嘅 1.2 倍。
  「等反彈」成立：B 每個訊號平均（冇成交當 0）≥ A + 3 點，全部同前後兩半都成立；B 成交嗰啲平均 > 0；成交率 ≥ 40%。
用途（只係提案，真倉要使用者批）：兩樣都成立 → 提案 MHI AI 指引／硬規則「連續 4 支 5 分鐘同向唔追，等回 38.2% 先入」；
只有「唔追」成立 → 提案唔追；都唔成立 → 唔改，連續 K 唔係入場質素問題嘅主因。

用法：python3 research/longfei_rulesim/streak_check.py [--out 報告.json]（要 GCS 讀權）
"""
import argparse
import json
import statistics
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402

COST = 2
STREAK = 4
HOLD = 12          # 60 分鐘（5 分鐘 K）
WAIT = 6           # 30 分鐘
FIB = 0.382
SESSIONS = {"am": (time(9, 15), time(12, 0)), "pm": (time(13, 0), time(16, 30)), "night": (time(17, 15), time(3, 0))}
NO_SIGNAL = (time(9, 15), time(9, 40))


def session_of(t):
    """分鐘結束時間 → (時段名, 交易日)；夜市過咗午夜算返前一日。"""
    m = t.time()
    for name, (a, b) in SESSIONS.items():
        if a < b and a < m <= b:
            return name, t.date()
    if m > time(17, 15):
        return "night", t.date()
    if m <= time(3, 0):
        return "night", (t - timedelta(days=1)).date()
    return None, None


def to_5m(bars):
    """1 分鐘 → 每時段一串 5 分鐘 K [(結束時間, o, h, l, c)]，用時段開始計 5 分鐘格。"""
    groups = {}
    for t, o, h, lo, c in bars:
        s, d = session_of(t)
        if s is None:
            continue
        start = datetime.combine(d, SESSIONS[s][0])
        k = int((t - start).total_seconds() // 60 - 1) // 5
        groups.setdefault((d, s), {}).setdefault(k, []).append((t, o, h, lo, c))
    out = {}
    for key, ks in groups.items():
        seq = []
        for k in sorted(ks):
            rows = ks[k]
            seq.append((rows[-1][0], rows[0][1], max(r[2] for r in rows), min(r[3] for r in rows), rows[-1][4]))
        out[key] = seq
    return out


def sign(b):
    return (b[4] > b[1]) - (b[4] < b[1])


def trades(sessions):
    A, B, C = [], [], []
    for (d, s), seq in sorted(sessions.items()):
        run, last = 0, 0
        for i, b in enumerate(seq):
            sg = sign(b)
            run = run + 1 if sg and sg == last else (1 if sg else 0)
            last = sg
            if i + HOLD >= len(seq):
                continue
            nxt = seq[i + 1:i + 1 + HOLD]
            ex = seq[i + HOLD][4]
            ok_time = not (s == "am" and NO_SIGNAL[0] < b[0].time() <= NO_SIGNAL[1])
            if not sg or not ok_time:
                continue
            ent = nxt[0][1]
            mae = max(((ent - x[3]) if sg > 0 else (x[2] - ent)) for x in nxt[:WAIT])
            row = {"d": d, "pts": (ex - ent) * sg - COST, "mae": mae, "dir": sg, "s": s}
            if run == STREAK:
                A.append(row)
                seg = seq[i - STREAK + 1:i + 1]
                hi, lo = max(x[2] for x in seg), min(x[3] for x in seg)
                lim = b[4] - sg * FIB * (hi - lo)
                fill = next((x for x in nxt[:WAIT] if (x[3] <= lim if sg > 0 else x[2] >= lim)), None)
                B.append({"d": d, "pts": ((ex - lim) * sg - COST) if fill else 0.0, "filled": bool(fill)})
            elif run < STREAK:
                C.append(row)
    return A, B, C


def stats(A, B, C):
    m = lambda xs: round(statistics.mean(xs), 2) if xs else None  # noqa: E731
    filled = [x["pts"] for x in B if x["filled"]]
    return {"n": len(A), "A_mean": m([x["pts"] for x in A]), "A_win": m([x["pts"] > 0 for x in A]),
            "A_mae_med": statistics.median(x["mae"] for x in A) if A else None,
            "C_n": len(C), "C_mean": m([x["pts"] for x in C]),
            "C_mae_med": statistics.median(x["mae"] for x in C) if C else None,
            "B_mean_per_signal": m([x["pts"] for x in B]), "B_fill": m([x["filled"] for x in B]),
            "B_mean_filled": m(filled)}


def summarize(bars):
    A, B, C = trades(to_5m(bars))
    days = sorted({x["d"] for x in A})
    split = days[len(days) // 2]
    out = {"from": str(days[0]), "to": str(days[-1]), "days": len(days), "all": stats(A, B, C)}
    for k, f in (("h1", lambda x: x["d"] < split), ("h2", lambda x: x["d"] >= split)):
        out[k] = stats([x for x in A if f(x)], [x for x in B if f(x)], [x for x in C if f(x)])
    for s in SESSIONS:
        idx = [i for i, x in enumerate(A) if x["s"] == s]
        out[f"sess_{s}"] = stats([A[i] for i in idx], [B[i] for i in idx], [x for x in C if x["s"] == s])
    for nm, dr in (("up", 1), ("down", -1)):
        idx = [i for i, x in enumerate(A) if x["dir"] == dr]
        out[f"dir_{nm}"] = stats([A[i] for i in idx], [B[i] for i in idx], [x for x in C if x["dir"] == dr])
    al = out["all"]
    out["no_chase_pass"] = bool(al["n"] >= 300 and al["A_mean"] < 0 and out["h1"]["A_mean"] < 2
                                and out["h2"]["A_mean"] < 2 and al["A_mae_med"] >= 1.2 * al["C_mae_med"])
    out["wait_pass"] = bool(al["n"] >= 300 and all(out[k]["B_mean_per_signal"] >= out[k]["A_mean"] + 3
                                                   for k in ("all", "h1", "h2"))
                            and al["B_mean_filled"] > 0 and al["B_fill"] >= 0.4)
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
    text = json.dumps(summarize(um.load(raw)), ensure_ascii=False, indent=1, default=str)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
