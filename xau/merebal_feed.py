"""[IDEAS #1463] 月尾股債再平衡嘅公開數據來源：Yahoo Finance chart v8（唔使帳號、請求唔帶任何個人資料）。
只喺訊號日（每月一次）用：攞指數（^GSPC／^FTSE）同美債 10 年期貨（ZN=F）嘅日線，計「當月至今回報」。
攞唔到／數據唔新鮮 → 回 None＋原因，當月唔做（trend_live 會記日誌同通知）。解析同計算係純函數，方便測試。"""
import datetime as dt
import json
import urllib.parse
import urllib.request

BOND = "ZN=F"
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=3mo&interval=1d"


def parse_chart(doc):
    """Yahoo chart JSON → [(交易所當地日期, 收市／最新價)]，按日期排序；壞格式回 []。"""
    try:
        r = doc["chart"]["result"][0]; off = int(r["meta"].get("gmtoffset", 0)); cl = r["indicators"]["quote"][0]["close"]; rows = {}
        for t, c in zip(r["timestamp"], cl):
            if c is not None and c > 0:
                rows[dt.datetime.fromtimestamp(int(t) + off, dt.timezone.utc).date()] = float(c)
        return sorted(rows.items())
    except (KeyError, IndexError, TypeError, ValueError):
        return []


def mtd(rows, today):
    """→ (當月至今回報, None) 或 (None, 原因)。要有上個月最後一個收市，同埋今日（today）嘅價。"""
    prev = [c for d, c in rows if (d.year, d.month) < (today.year, today.month)]
    cur = [(d, c) for d, c in rows if d <= today and (d.year, d.month) == (today.year, today.month)]
    if not prev:
        return None, "冇上個月收市"
    if not cur or cur[-1][0] != today:
        return None, f"今日（{today}）未有價，最新 {cur[-1][0] if cur else '冇'}"
    return cur[-1][1] / prev[-1] - 1.0, None


def fetch(ticker, timeout=8, tries=2):
    for _ in range(tries):
        try:
            req = urllib.request.Request(URL.format(urllib.parse.quote(ticker)), headers={"User-Agent": "Mozilla/5.0"})
            rows = parse_chart(json.loads(urllib.request.urlopen(req, timeout=timeout).read()))
            if rows:
                return rows
        except Exception:  # noqa: BLE001  網絡／格式問題一律當攞唔到
            pass
    return []


def probe(idx_ticker, fetcher=fetch):
    """每日一次嘅連線檢查：→ {"idx_last": [日期, 價], "bond_last": [日期, 價]} 或 {"err": …}。唔影響交易。"""
    out = {}
    for key, tk in (("idx_last", idx_ticker), ("bond_last", BOND)):
        rows = fetcher(tk)
        if not rows:
            return {"err": f"攞唔到 {tk}"}
        out[key] = [rows[-1][0].isoformat(), round(rows[-1][1], 4)]
    return out


def snapshot(idx_ticker, today, fetcher=fetch):
    """→ {"idx": 指數當月至今, "bond": 美債當月至今} 或 {"err": 原因}。"""
    out = {}
    for key, tk in (("idx", idx_ticker), ("bond", BOND)):
        rows = fetcher(tk)
        if not rows:
            return {"err": f"攞唔到 {tk}"}
        v, why = mtd(rows, today)
        if v is None:
            return {"err": f"{tk}：{why}"}
        out[key] = round(v, 6)
    return out
