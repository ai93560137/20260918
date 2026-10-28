"""[IDEAS #144] FOMC 事件日對恒指嘅影響（MILESTONES「事件日規則」研究，限期 10-31）。

文獻線索：
  - Lucca & Moench（NY Fed Staff Report 512；JF 2015）：議息公佈前 24 小時美股有異常正回報（pre-FOMC drift），
    文中話其他主要外國股市都有類似現象（冇點名恒指）。
  - Hu, Pan, Wang & Zhu（JFE 2022）：非農、ISM、GDP 公佈前都有類似隔夜正回報。
  - Fernandez-Perez, Frijns & Tourani-Rad（J. Empirical Finance 2017）：公佈後約 45 分鐘內波動先升後跌。

數據：yfinance ^HSI 日線；FOMC 公佈日由聯儲局網頁 fomccalendars.htm 抓（2020 起，剔走 unscheduled／notation vote）。
時間：聲明美東 14:00 ＝ 香港翌日 02:00／03:00，所以：
  前一日 D ＝ 香港同一個日期（日市 16:00 收，喺公佈之前）；後一日 D+1 ＝ D 之後第一個香港交易日（公佈之後先開市）。

預先登記（10-28，結果出嚟之前寫，唔再改）：
  A 恒指 pre-FOMC 漂移：D 日回報平均 − 其他日子平均 ≥ +0.15 個百分點，而且 Welch t ≥ 2，前後兩半（2020–2022／2023–）都 > 0。
  B 公佈後波動：D+1 嘅「跳空絕對值」或者「日內幅度」中位數 ≥ 其他日子中位數 × 1.2。
用途（只係提案，真倉改動要使用者批）：
  A 過 → 建議 FOMC 前唔好揸淡倉過夜；B 過 → 支持 R348 數據前封鎖，並考慮公佈後頭一段時間都唔開新倉。
  兩樣都唔過 → R348 照使用者定嘅 4 小時，唔再加嘢。

用法：python3 research/longfei_rulesim/fomc_hsi_check.py [--no-upload]
"""
import argparse
import html
import json
import math
import re
import statistics
import urllib.request
from datetime import date, datetime

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}
ABBR = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10,
        "Nov": 11, "Dec": 12}


def parse_fed(text):
    """聯儲局頁面純文字 → 定期會議聲明日（會議最後一日）清單。"""
    out = []
    parts = re.split(r"(\d{4}) FOMC Meetings", text)
    for i in range(1, len(parts) - 1, 2):
        year, seg = int(parts[i]), parts[i + 1]
        pat = (r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
               r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))"
               r"\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?\*?([^A-Z]{0,40})")
        for m in re.finditer(pat, seg):
            mon, d1, d2, tail = m.groups()
            if re.search(r"unscheduled|notation|cancel", tail, re.I):
                continue
            if "/" in mon:
                mo = ABBR[mon.split("/")[1]]
            else:
                mo = MONTHS[mon]
            day = int(d2 or d1)
            try:
                out.append(date(year, mo, day))
            except ValueError:
                continue
    return sorted(set(out))


def fetch_fomc():
    req = urllib.request.Request(FED_URL, headers={"User-Agent": "Mozilla/5.0 zhuge-research"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"\s+", " ", text)
    return parse_fed(text)


def stats(a, b):
    """a 對 b：平均、差、Welch t。"""
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    t = (ma - mb) / math.sqrt(va / len(a) + vb / len(b))
    return {"n": len(a), "mean_pct": round(ma * 100, 3), "others_mean_pct": round(mb * 100, 3),
            "diff_pct": round((ma - mb) * 100, 3), "t": round(t, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    import yfinance as yf

    fomc = [d for d in fetch_fomc() if d.year >= 2020 and d <= date.today()]
    print("FOMC 公佈日", len(fomc), [d.isoformat() for d in fomc[:3]], "…", [d.isoformat() for d in fomc[-3:]])
    if len(fomc) < 30:
        raise SystemExit("FOMC 日期抓唔夠（網頁格式可能變咗）")
    df = yf.download("^HSI", start="2019-12-01", interval="1d", progress=False, auto_adjust=False)
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    rows = [(t.date(), float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]))
            for t, r in df.iterrows() if r["Close"] == r["Close"]]
    days = [r[0] for r in rows]
    ret, gap, rng = {}, {}, {}
    for i in range(1, len(rows)):
        d, o, h, lo, c = rows[i]
        pc = rows[i - 1][4]
        ret[d], gap[d], rng[d] = c / pc - 1, abs(o / pc - 1), (h - lo) / pc
    pre, post = [], []
    for f in fomc:
        if f in ret:
            pre.append(f)
        nxt = next((d for d in days if d > f), None)
        if nxt in ret:
            post.append(nxt)
    others = [d for d in ret if d not in set(pre) | set(post) and d >= date(2020, 1, 1)]
    split = date(2023, 1, 1)
    res = {"generated_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z", "fomc_n": len(fomc),
           "pre_days": len(pre), "post_days": len(post),
           "A_pre_drift": stats([ret[d] for d in pre], [ret[d] for d in others]),
           "A_h1": stats([ret[d] for d in pre if d < split], [ret[d] for d in others if d < split]),
           "A_h2": stats([ret[d] for d in pre if d >= split], [ret[d] for d in others if d >= split]),
           "post_ret": stats([ret[d] for d in post], [ret[d] for d in others]),
           "B_gap_median": [round(statistics.median(gap[d] for d in post) * 100, 3),
                            round(statistics.median(gap[d] for d in others) * 100, 3)],
           "B_range_median": [round(statistics.median(rng[d] for d in post) * 100, 3),
                              round(statistics.median(rng[d] for d in others) * 100, 3)],
           "pre_range_median": round(statistics.median(rng[d] for d in pre) * 100, 3)}
    A = res["A_pre_drift"]
    res["A_pass"] = bool(A["diff_pct"] >= 0.15 and A["t"] >= 2 and res["A_h1"]["mean_pct"] > 0 and res["A_h2"]["mean_pct"] > 0)
    g, r = res["B_gap_median"], res["B_range_median"]
    res["B_pass"] = bool(g[0] >= 1.2 * g[1] or r[0] >= 1.2 * r[1])
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if not a.no_upload:
        from google.cloud import storage
        storage.Client().bucket("zhuge-risk-manager-bucket").blob("longfei/rulesim_oos/fomc_hsi_report.json").upload_from_string(
            json.dumps(res, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
