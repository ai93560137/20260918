"""[IDEAS #2001] 指數跌穿 200 日線之後，第一次反彈到 200 日線會唔會被壓返（使用者 11-07：「2018、2022 跌穿後反彈都喺 200 SMA 附近被壓回」）。

數據：yfinance ^NDX、^GSPC 日線 1990 起（GitHub Actions 跑）。
事件：收市跌穿 200 SMA，而之前已經連續 ≥ 60 日收市喺 200 SMA 上面（「第一次跌穿」）。
反彈觸碰：跌穿之後 60 日內第一日最高 ≥ 當日 200 SMA。
  壓返＝觸碰日之後第 10 個交易日收市仍然 < 200 SMA；另計觸碰後 20 日報酬。
對照：跌穿後 60 日內冇觸碰（一路跌）分開計。

預先登記（11-08，結果出嚟之前寫，唔再改）：
  「200 SMA 跌穿後係強阻力」成立 ＝ 兩隻指數各自觸碰事件 ≥ 15 次，而且壓返比例都 ≥ 60%。
  成立 → 寫入分析欄 STYLE（第 45 條已經用咗，作數據支持）；唔成立 → STYLE 第 45 條改寫「200 SMA 預設阻力」嘅講法。

用法：python3 research/longfei_analyst/ma200/ma200_reject_check.py（輸出 GCS ops/longfei/analyst/research/ma200_reject.json）
"""
import json
import statistics


def run(tk):
    import yfinance as yf
    df = yf.download(tk, start="1990-01-01", interval="1d", progress=False, auto_adjust=False)
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] for c in df.columns]
    df["sma"] = df["Close"].rolling(200).mean()
    df = df.dropna()
    c, h, s, idx = df["Close"].tolist(), df["High"].tolist(), df["sma"].tolist(), [d.strftime("%Y-%m-%d") for d in df.index]
    ev, i = [], 60
    while i < len(c) - 70:
        if c[i] < s[i] and all(c[j] > s[j] for j in range(i - 60, i)):
            touch = next((j for j in range(i + 1, min(i + 61, len(c))) if h[j] >= s[j]), None)
            rec = {"break": idx[i], "touch": idx[touch] if touch else None}
            if touch is not None and touch + 20 < len(c):
                rec["rejected"] = c[touch + 10] < s[touch + 10]
                rec["ret20"] = round(c[touch + 20] / c[touch] - 1, 4)
                rec["days_to_touch"] = touch - i
            ev.append(rec)
            i += 60
        else:
            i += 1
    t = [e for e in ev if "rejected" in e]
    return {"events": len(ev), "touch": len(t), "no_touch_60d": len(ev) - len(t),
            "rejected": sum(e["rejected"] for e in t),
            "rejected_share": round(sum(e["rejected"] for e in t) / len(t), 3) if t else None,
            "ret20_median": round(statistics.median(e["ret20"] for e in t), 4) if t else None,
            "list": ev}


def main():
    res = {k: run(k) for k in ("^NDX", "^GSPC")}
    res["pass"] = all(res[k]["touch"] >= 15 and (res[k]["rejected_share"] or 0) >= 0.6 for k in ("^NDX", "^GSPC"))
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    print(txt)
    from google.cloud import storage
    storage.Client().bucket("zhuge-risk-manager-bucket").blob("ops/longfei/analyst/research/ma200_reject.json") \
        .upload_from_string(txt, content_type="application/json")


if __name__ == "__main__":
    main()
