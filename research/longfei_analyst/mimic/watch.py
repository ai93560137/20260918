"""龍飛陣 4 小時 K 提示（使用者 11-11：「4 小時 K 收返 7565 之下提我；有向下 4 小時 inside bar 提我；有以上情況你都可以試寫」）。

讀 GCS ops/longfei/analyst/data/<代號>.json（要先跑 longfei_analyst_data.yml 更新），用 TradingView／CME 嘅 4 小時切法（charts.h4_cme），
只睇**已經收咗**嘅 4 小時 K：
  below  ：最新收咗嗰根收市 < 關鍵位，而前一根收市 ≥ 關鍵位（由上面收返落去；之後一直喺下面唔重複提）
  inside ：最新收咗嗰根係 inside bar（高 ≤ 前一根高、低 ≥ 前一根低）而且收黑（收市 < 開市）＝「向下 inside bar」
  inside_up：同上但收紅（收市 ≥ 開市）＝「向上 inside bar」（使用者 11-12 加）
每根 K 每個條件只提一次（狀態：GCS ops/longfei/analyst/watch_state.json）。只係提示同分析，唔落單。

用法：python3 research/longfei_analyst/mimic/watch.py [--dry-run] [--max-age-min 20]
設定：research/longfei_analyst/mimic/watch.json  {"ES": {"below": [7565]}, ...}
輸出一行 JSON：{"fresh": bool, "alerts": [...], "last_bar": [...], "prev_bar": [...], "sma": {...}}
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import pack  # noqa: E402
import charts  # noqa: E402

ET = ZoneInfo("America/New_York")
STATE = pack.OUT + "watch_state.json"


def bar_end(key):
    """4 小時 K 結束時間（美東）：14:00 嗰根 17:00 收市，其餘 +4 小時。"""
    t = datetime.strptime(key, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    return t + timedelta(hours=3 if t.hour == 14 else 4)


def closed_bars(bars, now_et):
    return [b for b in bars if bar_end(b[0]) <= now_et]


def near_key(p, keys, tol=0.001):
    """[11-12] 使用者：「Inside bar 不是每一個都有用」——佢兩次用 inside bar 都係喺關鍵位攻唔破／有支撐之後。
    所以每個提示都標明：前一根 K 嘅高／低位有冇掂到關鍵位（±0.1%）。冇掂到就寫「唔喺關鍵位」，等使用者自己判斷。"""
    hit = []
    o, h, lo, c = p[1], p[2], p[3], p[4]
    for k in keys:
        t = k * tol
        if o > k and lo <= k + t:                  # 由上面落嚟測試
            hit.append(f"前一根低位 {lo:,.2f} 測試 {k:,.2f}，{'收返上面' if c > k else '收穿'}")
        elif o < k and h >= k - t:                 # 由下面上嚟測試
            hit.append(f"前一根高位 {h:,.2f} 測試 {k:,.2f}，{'收返下面' if c < k else '收企上面'}")
    return "喺關鍵位：" + "；".join(hit) if hit else "唔喺關鍵位附近（前一根高低位冇掂到清單入面嘅位）"


def check(bars, levels):
    """bars：已收市 4 小時 K（舊到新）。回傳 [(種類, 關鍵位或 None, 訊息)]。"""
    out = []
    if len(bars) < 2:
        return out
    p, b = bars[-2], bars[-1]
    for lv in levels.get("below", []):
        if b[4] < lv <= p[4]:
            out.append(("below", lv, f"4 小時 K（{b[0]} 美東）收 {b[4]:,.2f}，收返 {lv:,.2f} 之下（前一根收 {p[4]:,.2f}）"))
    if b[2] <= p[2] and b[3] >= p[3]:             # [11-12] 使用者：「向上 inside bar 都提我」——向上（收 ≥ 開）、向下都提，分開標
        up = b[4] >= b[1]
        out.append(("inside_up" if up else "inside", None,
                    f"4 小時 K（{b[0]} 美東）係{'向上' if up else '向下'} inside bar：開 {b[1]:,.2f} 高 {b[2]:,.2f} 低 {b[3]:,.2f} 收 {b[4]:,.2f}"
                    f"（前一根高 {p[2]:,.2f} 低 {p[3]:,.2f}）；{near_key(p, levels.get('keys', []))}"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-age-min", type=int, default=20)
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(HERE, "watch.json"), encoding="utf-8"))
    state = json.loads(pack.gcs_cat(STATE) or "{}")
    now = datetime.now(timezone.utc)
    res = {"now_utc": now.isoformat(timespec="seconds"), "markets": {}}
    for name, levels in cfg.items():
        doc = json.loads(pack.gcs_cat(pack.DATA + f"{name}.json"))
        age = (now - datetime.fromisoformat(doc["fetched_utc"])).total_seconds() / 60
        bars = closed_bars(charts.h4_cme(charts.clean_h1(doc["h1"], doc["d1"])), now.astimezone(ET))
        c = [x[4] for x in bars]
        alerts = []
        for kind, lv, msg in check(bars, levels):
            key = f"{name}:{kind}:{lv}:{bars[-1][0]}"
            if key not in state.get("sent", []):
                alerts.append({"kind": kind, "level": lv, "msg": msg, "key": key})
        res["markets"][name] = {"fresh": age <= a.max_age_min, "age_min": round(age, 1), "alerts": alerts,
                                "last_bar": bars[-1], "prev_bar": bars[-2],
                                "sma": {k: round(sum(c[-k:]) / k, 2) for k in (50, 100, 200)}}
        if alerts and age <= a.max_age_min and not a.dry_run:
            state.setdefault("sent", []).extend(x["key"] for x in alerts)
            state["sent"] = state["sent"][-200:]
    if not a.dry_run:
        tmp = "/tmp/longfei_watch_state.json"
        json.dump(state, open(tmp, "w"))
        pack.gcs_put(STATE, tmp)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
