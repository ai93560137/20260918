"""1 分 K「RSI 逆市＋加倉攤平」回測（恒指即月期貨 HK.HSI_FRONT）。

規則（使用者 2026-10-09 定）：
  入場：當日升跌（現價對上一交易日收市）絕對值 ≥ 1%，且 1 分 K RSI(14) 向上穿 80 → 沽 1 張；
        向下穿 20 → 買 1 張。訊號 K 線收市確認，下一根 K 線開市價成交。同一時間只持一組倉。
        --same-dir：只做「升 ≥ 1% 才沽、跌 ≥ 1% 才買」（逆當日方向）。
  止賺：入場訊號那一刻的當日極值（沽 → 當日最低位；買 → 當日最高位），全部平倉。
  止蝕：平均成本逆向 2%，全部平倉。
  加倉：價格比「最近一次加倉價」再逆向 300 點，加 1 張（第一張的入場價算第一次）。
  減倉：持 ≥ 2 張時，價格回到平均成本 → 平到剩 1 張（平均成本不變，原本是一張張掛同一個價，
        同一根 K 線全部成交）。剩下那張的成本 = 平均成本，比第一張入場價好。
        例：24000 沽 → 24300 加（S×2 @24150）→ 回 24150 平 1 → S×1 @24150。
  交易日 = 香港時間 09:00 至翌日 09:00（日市＋夜市）；「當日極值」「上日收市」都按這個交易日。
  --session-close：每個交易日最後一根 K 線收市全部平倉（不留倉過夜／過週末）。

成交模擬：1 分 K 內的路徑假設為 開→高→低→收（開市較近高位）或 開→低→高→收（較近低位），
  沿路徑逐個觸發掛單；跳空（前收到今開）觸發的單一律以開市價成交。
  成本：每張每次成交扣 --cost 點（預設 1 點，含佣金、徵費與滑點）。恒指每點 HK$50。

數據：GCS archive/futu_k_1m/HK.HSI_FRONT/<日期>.json（本地腳本 v12 --export-intraday … K_1M）；
  或 --symbol HK.HSIMAIN：主連 1 分 K 長歷史（本地腳本 v13 --export-raw HK.HSImain K_1M）。
  即月合約按最後交易日轉月拼接；轉月日價差會令留倉的單有跳動（--session-close 不受影響）。

用法：
  python3 research/hsi_futures_range/rsi_avg_down.py --json /tmp/k1m.json   # 第一次從 GCS 下載並存快取
  python3 research/hsi_futures_range/rsi_avg_down.py --json /tmp/k1m.json --same-dir --session-close
"""
import argparse, csv, json, sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
POINT_HKD = 50


# ---- 數據 --------------------------------------------------------------------
def load_gcs(ktype="K_1M", symbol="HK.HSI_FRONT"):
    sys.path.insert(0, str(REPO / "scripts"))
    import gcp_agent as g
    ctx = g.Ctx(argparse.Namespace(region=None, function=None, bucket=None, project=None))
    s, base = ctx.session, f"https://storage.googleapis.com/storage/v1/b/{ctx.bucket}/o"
    names, token = [], None
    while True:
        params = {"prefix": f"archive/futu_{ktype.lower()}/{symbol}/", "fields": "items(name),nextPageToken"}
        if token:
            params["pageToken"] = token
        r = s.get(base, params=params).json()
        names += [i["name"] for i in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    bars = []
    for n in names:
        bars += s.get(f"{base}/{n.replace('/', '%2F')}", params={"alt": "media"}).json()
    return bars


def session_of(time_key):
    d, hh = time_key[:10], int(time_key[11:13])
    return d if hh >= 9 else (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def clean(bars):
    seen = {}
    for b in bars:
        if isinstance(b, dict) and b.get("volume") and all(b.get(k) for k in ("open", "high", "low", "close")):
            seen[b["time_key"]] = {k: (b[k] if k == "time_key" else float(b[k]))
                                   for k in ("time_key", "open", "high", "low", "close")}
    return [seen[k] for k in sorted(seen)]


def rsi_series(closes, n=14):
    """Wilder RSI；前 n 根是 None。"""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, n + 1)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, n + 1)]
    ag, al = sum(gains) / n, sum(losses) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


# ---- 持倉 --------------------------------------------------------------------
class Position:
    """side = +1 買、−1 沽。用平均成本法記帳：平倉時已實現 = 張數 × side × (成交價 − 平均成本)。"""

    def __init__(self, side, price, tp, p):
        self.side, self.lots, self.avg, self.tp, self.p = side, 1, price, tp, p
        self.last_add = price
        self.realized = -p.cost
        self.max_lots, self.adds, self.reduces = 1, 0, 0
        self.worst = 0.0                                   # 最大浮虧（點，全部張數）

    def sl(self):
        return self.avg * (1 - self.side * self.p.sl_pct)

    def add_level(self):
        return self.last_add - self.side * self.p.step

    def orders(self):
        """[(價位, 種類)]：價格到這裡就觸發。"""
        out = [(self.tp, "tp"), (self.sl(), "sl"), (self.add_level(), "add")]
        if self.lots > 1:
            out.append((self.avg, "reduce"))
        return out

    def fill(self, kind, px):
        s = self.side
        if kind == "add":
            self.avg = (self.avg * self.lots + px) / (self.lots + 1)
            self.lots += 1
            self.last_add = px
            self.adds += 1
            self.realized -= self.p.cost
            self.max_lots = max(self.max_lots, self.lots)
            return False
        k = self.lots - 1 if kind == "reduce" else self.lots
        self.realized += k * (s * (px - self.avg) - self.p.cost)
        self.lots -= k
        if kind == "reduce":
            self.reduces += 1
        return self.lots == 0

    def mark(self, px):
        self.worst = min(self.worst, self.lots * self.side * (px - self.avg))


def triggered(level, kind, side, a, b):
    """價格由 a 走到 b（直線）有沒有觸及這張單。止賺／減倉在順向、止蝕／加倉在逆向。"""
    favorable = kind in ("tp", "reduce")
    up_order = (side > 0) == favorable                      # 價格向上才會觸發
    return (a < level <= b) if up_order else (b <= level < a)


def walk(pos, a, b, gap):
    """沿 a→b 依次觸發；回傳 (平倉原因, 成交價) 或 None。"""
    cur = a                                                  # 跳空時 a 不動：成交後重算掛單，仍以整段跳空判斷
    while True:
        hits = [(abs(lv - cur), lv, k) for lv, k in pos.orders() if triggered(lv, k, pos.side, cur, b)]
        if not hits:
            pos.mark(b)
            return None
        _, lv, kind = min(hits)
        px = b if gap else lv
        pos.mark(px)
        if pos.fill(kind, px):
            return kind, px
        if not gap:
            cur = lv


def bar_path(bar):
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    return [o, h, l, c] if h - o <= o - l else [o, l, h, c]


# ---- 回測 --------------------------------------------------------------------
def run(bars, p):
    closes = [b["close"] for b in bars]
    rsi = rsi_series(closes, p.rsi_n)
    sess = [session_of(b["time_key"]) for b in bars]
    trades, pos, entry, pending = [], None, None, None
    prev_close, day_hi, day_lo = None, None, None
    for i, bar in enumerate(bars):
        new_day = i == 0 or sess[i] != sess[i - 1]
        if new_day:
            pending = None                                   # 上一交易日最後一根的訊號不帶過夜
            prev_close = closes[i - 1] if i else None
            day_hi, day_lo = bar["high"], bar["low"]
        # 1) 上一根的訊號 → 這根開市價入場
        if pending and pos is None:
            side, tp = pending
            px = bar["open"]
            if side * (tp - px) > 0:                        # 止賺價要在有利方向
                pos = Position(side, px, tp, p)
                entry = {"entry_time": bar["time_key"], "side": "買" if side > 0 else "沽",
                         "entry": px, "tp": tp, "session": sess[i]}
        pending = None
        # 2) 持倉：沿 K 線路徑觸發
        if pos is not None:
            path = bar_path(bar)
            prev_px = closes[i - 1] if i else bar["open"]
            res = walk(pos, prev_px, path[0], gap=True) if prev_px != path[0] else None
            for a, b in zip(path, path[1:]):
                if res:
                    break
                res = walk(pos, a, b, gap=False)
            last_of_day = i + 1 == len(bars) or sess[i + 1] != sess[i]
            if not res and p.session_close and last_of_day:
                pos.fill("close", bar["close"])
                res = ("close", bar["close"])
            if res:
                trades.append({**entry, "exit_time": bar["time_key"], "reason": res[0], "exit": res[1],
                               "max_lots": pos.max_lots, "adds": pos.adds, "reduces": pos.reduces,
                               "worst_pts": round(pos.worst, 1), "pnl_pts": round(pos.realized, 1)})
                pos = None
        day_hi, day_lo = max(day_hi, bar["high"]), min(day_lo, bar["low"])
        # 3) 這根收市：訊號
        if pos is None and prev_close and rsi[i] is not None and rsi[i - 1] is not None:
            chg = closes[i] / prev_close - 1
            if abs(chg) >= p.move_pct:
                if rsi[i - 1] <= p.rsi_hi < rsi[i] and (not p.same_dir or chg > 0):
                    pending = (-1, day_lo)
                elif rsi[i - 1] >= p.rsi_lo > rsi[i] and (not p.same_dir or chg < 0):
                    pending = (1, day_hi)
    open_pos = None
    if pos is not None:
        open_pos = {**entry, "lots": pos.lots, "avg": round(pos.avg, 1),
                    "float_pts": round(pos.realized + pos.lots * pos.side * (closes[-1] - pos.avg), 1)}
    return trades, open_pos


def summarize(trades, label):
    n = len(trades)
    if not n:
        return {"label": label, "trades": 0}
    pnl = [t["pnl_pts"] for t in trades]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for x in pnl:
        eq += x
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["reason"]] += 1
    return {"label": label, "trades": n, "win_rate": len(wins) / n, "total_pts": sum(pnl),
            "total_hkd": sum(pnl) * POINT_HKD, "avg_win": sum(wins) / len(wins) if wins else 0,
            "avg_loss": sum(losses) / len(losses) if losses else 0, "max_dd_pts": mdd,
            "worst_trade": min(pnl), "worst_float": min(t["worst_pts"] for t in trades),
            "max_lots": max(t["max_lots"] for t in trades),
            "pf": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else float("inf"),
            "reasons": dict(reasons)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="本地快取（不存在就從 GCS 下載後寫入）")
    ap.add_argument("--symbol", default="HK.HSI_FRONT", help="GCS 封存代號；主連長歷史用 HK.HSIMAIN（本地腳本 v13 --export-raw）")
    ap.add_argument("--from-date", help="只用這天（交易日）之後的數據，例 2019-01-01")
    ap.add_argument("--move-pct", type=float, default=1.0)
    ap.add_argument("--rsi-n", type=int, default=14)
    ap.add_argument("--rsi-hi", type=float, default=80)
    ap.add_argument("--rsi-lo", type=float, default=20)
    ap.add_argument("--sl-pct", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=300)
    ap.add_argument("--cost", type=float, default=1.0)
    ap.add_argument("--same-dir", action="store_true")
    ap.add_argument("--session-close", action="store_true")
    ap.add_argument("--all", action="store_true", help="四個組合（雙向／逆當日方向 × 留倉／收市平倉）一起跑")
    ap.add_argument("--trades-csv")
    p = ap.parse_args()
    p.move_pct /= 100
    p.sl_pct /= 100

    if p.json and Path(p.json).exists():
        raw = json.loads(Path(p.json).read_text())
    else:
        raw = load_gcs(symbol=p.symbol.upper())
        if p.json:
            Path(p.json).write_text(json.dumps(raw))
    bars = clean(raw)
    if p.from_date:
        bars = [b for b in bars if session_of(b["time_key"]) >= p.from_date]
    days = sorted(set(session_of(b["time_key"]) for b in bars))
    print(f"1 分 K {len(bars)} 根，{len(days)} 個交易日（{days[0]} 至 {days[-1]}）")

    combos = ([(sd, sc) for sd in (False, True) for sc in (False, True)] if p.all
              else [(p.same_dir, p.session_close)])
    for sd, sc in combos:
        q = argparse.Namespace(**{**vars(p), "same_dir": sd, "session_close": sc})
        label = ("逆當日方向" if sd else "雙向") + "／" + ("收市平倉" if sc else "留倉")
        trades, open_pos = run(bars, q)
        s = summarize(trades, label)
        print(json.dumps(s, ensure_ascii=False, default=lambda x: round(x, 3)))
        if open_pos:
            print(f"  未平倉：{json.dumps(open_pos, ensure_ascii=False)}")
        if p.trades_csv:
            path = Path(p.trades_csv.replace(".csv", f"_{'same' if sd else 'both'}_{'sc' if sc else 'hold'}.csv"))
            with path.open("w", newline="", encoding="utf-8") as f:
                if trades:
                    w = csv.DictWriter(f, fieldnames=list(trades[0]))
                    w.writeheader()
                    w.writerows(trades)


if __name__ == "__main__":
    main()
