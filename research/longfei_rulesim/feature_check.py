"""[IDEAS #154] 使用者 R286 入場特徵做「入場質素過濾」：日線跌勢日沽空，有特徵（已經低過開市＋貼近昨日低位）嘅入場
係咪少啲「一開倉就錯」（MILESTONES 入場質素研究最後一部分）。

同 #125 唔同：#125 係全套方法（入場＋出場）前向測試；呢度只問「特徵係咪一個好嘅入場過濾」，用同一套出場比較有／冇特徵。
文獻方向相反要留意：Grant, Wolf & Yu 2005 話開市大幅移動之後日內傾向反轉（即係順住沽會蝕）；使用者 34 單係順住沽。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT（1 分鐘含夜市，約一年）；日線、ATR、昨日低位用 user_method.daily（日市 09:15–16:30）。

預先登記（10-30，結果出嚟之前寫，唔再改）：
  日子：日線跌勢（昨收 < 20 日均）。時段：日市 13:00–16:00、夜市 17:15–23:30，用 5 分鐘收市（同 user_method 方法 A 一樣）。
  F 有特徵：價 ≤ 今日開市 − 0.30 ATR，而且 ≤ 昨日低位 + 0.25 ATR（R286 方法 A 門檻，唔改）。每日取第一個 F。
  N 冇特徵：同一日時段內唔符合 F 嘅 5 分鐘收市，隨機抽 1 個（seed 0）。
  沽空、收市價入場，成本 2 點。
  「一開倉就錯」＝之後 3 個鐘內先掂入場 +120 點（MHI 真倉止蝕）先過掂 −120 點；兩樣都冇掂唔計錯。
  另量：頭 30 分鐘最大逆向（MAE）、60 分鐘後點數。
成功標準（全部要達）：F ≥ 60 日；F「一開倉就錯」比率 ≤ N − 10 個百分點；F MAE 中位數 ≤ N × 0.8；前後兩半 F 錯率都低過 N。
用途（只係提案，真倉要使用者批）：成立 → 提案 MHI AI 指引「日線跌勢沽空要等價低過開市 0.3 ATR 同貼近昨日低位先入」；
唔成立 → 唔改，R286 特徵唔係入場質素嘅答案。另外報日線升勢做好嘅鏡像（只作參考，唔判）。

用法：python3 research/longfei_rulesim/feature_check.py [--out 報告.json]（要 GCS 讀權）
"""
import argparse
import json
import random
import statistics
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "longfei_lessons"))
import user_method as um  # noqa: E402

COST = 2
STOP = 120
LOOK = timedelta(hours=3)
MAE_WIN = timedelta(minutes=30)
FWD = timedelta(minutes=60)


def outcome(bars, i, side):
    t0, c0 = bars[i][0], bars[i][4]
    wrong = fwd = None
    mae = 0.0
    for t, o, h, lo, c in bars[i + 1:]:
        if t - t0 > LOOK:
            break
        adv = (h - c0) if side < 0 else (c0 - lo)
        fav = (c0 - lo) if side < 0 else (h - c0)
        if t - t0 <= MAE_WIN:
            mae = max(mae, adv)
        if fwd is None and t - t0 >= FWD:
            fwd = (c - c0) * side - COST
        if wrong is None:
            if adv >= STOP:
                wrong = True
            elif fav >= STOP:
                wrong = False
    return {"wrong": wrong, "mae": mae, "fwd": fwd}


def samples(bars, ctx, side):
    rng = random.Random(0)
    by_day = {}
    for i, (t, o, h, lo, c) in enumerate(bars):
        if t.minute % 5 != 4 or not any(a <= t.time() < b for a, b in um.WINDOWS):
            continue
        sd = um.session_date(t)
        x = ctx.get(sd)
        if not x or ((x["pdc"] < x["sma"]) != (side < 0)):
            continue
        if side < 0:
            f = c <= x["open"] - 0.30 * x["atr"] and c <= x["pdl"] + 0.25 * x["atr"]
        else:
            pdh = x.get("pdh")
            f = c >= x["open"] + 0.30 * x["atr"] and pdh is not None and c >= pdh - 0.25 * x["atr"]
        g = by_day.setdefault(sd, {"F": None, "N": []})
        if f and g["F"] is None:
            g["F"] = i
        elif not f:
            g["N"].append(i)
    F, N = [], []
    for sd, g in sorted(by_day.items()):
        if g["F"] is not None:
            F.append((sd, outcome(bars, g["F"], side)))
        if g["N"]:
            N.append((sd, outcome(bars, rng.choice(g["N"]), side)))
    return F, N


def stat(rows):
    dec = [r["wrong"] for _, r in rows if r["wrong"] is not None]
    fw = [r["fwd"] for _, r in rows if r["fwd"] is not None]
    return {"n": len(rows), "decided": len(dec), "wrong_rate": round(sum(dec) / len(dec), 3) if dec else None,
            "mae_med": statistics.median(r["mae"] for _, r in rows) if rows else None,
            "fwd60_mean": round(statistics.mean(fw), 1) if fw else None}


def report(F, N):
    days = sorted({d for d, _ in F + N})
    split = days[len(days) // 2]
    out = {"from": str(days[0]), "to": str(days[-1]), "F": stat(F), "N": stat(N)}
    for k, f in (("h1", lambda d: d < split), ("h2", lambda d: d >= split)):
        out[k] = {"F": stat([x for x in F if f(x[0])]), "N": stat([x for x in N if f(x[0])])}
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
    bars = um.load(raw)
    keys, ctx = um.daily(bars)
    d = {}
    for t, o, h, lo, c in bars:                       # 鏡像要昨日高位
        if um.time(9, 15) <= t.time() < um.time(16, 30):
            d[t.date()] = max(d.get(t.date(), h), h)
    for i, k in enumerate(keys):
        if k in ctx and i:
            ctx[k]["pdh"] = d[keys[i - 1]]
    res = {"short_downtrend": report(*samples(bars, ctx, -1)), "long_uptrend_ref": report(*samples(bars, ctx, 1))}
    s = res["short_downtrend"]
    s["pass"] = bool(s["F"]["n"] >= 60 and s["F"]["wrong_rate"] <= s["N"]["wrong_rate"] - 0.10
                     and s["F"]["mae_med"] <= 0.8 * s["N"]["mae_med"]
                     and all(s[h]["F"]["wrong_rate"] < s[h]["N"]["wrong_rate"] for h in ("h1", "h2")))
    text = json.dumps(res, ensure_ascii=False, indent=1, default=str)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
