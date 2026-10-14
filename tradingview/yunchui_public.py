#!/usr/bin/env python3
"""產生雲垂陣公開頁用 JSON：tradingview/data_external/yunchui_public.json
來源：position.json、position_mes.json、digest.txt（最新掃描）、yunchui_history.json。
只放策略規則、持倉規格、Δ／止損狀態、事件紀錄；不放權益、保證金、帳戶資料。
Cloud Run 頁面（?view=yunchui）可由本分支 raw URL 讀取（同 bazhentu 讀 levels.json 同一做法）。
用法：python3 tradingview/yunchui_public.py
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
D = HERE / "data_external"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def main():
    pos = load(D / "position.json")
    mes = load(D / "position_mes.json") if (D / "position_mes.json").exists() else {}
    hist = load(HERE / "yunchui_history.json")
    dg = (D / "digest.txt").read_text(encoding="utf-8") if (D / "digest.txt").exists() else ""
    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")

    m = re.search(r"HSI 期貨\([^)]*\)\s*([\d,\.]+)", dg)
    front = num(m.group(1)) if m else None
    m = re.search(r"HSI 跨式Δ\s*([+\-][\d\.]+)(?:\s*對沖\s*([+\-]\d+)\s*→\s*淨Δ\s*([+\-][\d\.]+))?", dg)
    h_str = num(m.group(1)) if m else None
    h_hedge = num(m.group(2)) if m and m.group(2) else None
    h_net = num(m.group(3)) if m and m.group(3) else h_str
    m = re.search(r"MES 跨式Δ\s*([+\-][\d\.]+)", dg)
    m_delta = num(m.group(1)) if m else None
    m = re.search(r"ES 期貨\s*([\d,\.]+)", dg)
    es = num(m.group(1)) if m else None
    hedges = pos.get("hedges", [])
    hedge_lots = sum((-1 if h["side"] == "sell" else 1) * h.get("qty", 1) for h in hedges)

    out = {
        "updated_hkt": now,
        "strategy": {
            "name": "雲垂陣", "icon": "☁️",
            "summary": "賣出期權跨式（Straddle）收取時間價值與波幅溢價，用期貨做 Δ 對沖，將方向性風險壓到界線內。",
            "rules": [
                "進場：賣出近月 ATM 跨式（恒指用小型恒指期權 MHI 月權；標普用 MES 期權）；隱含波幅高於實際波幅（溢價為正）先進場。",
                "Δ 對沖：整手期貨對沖，淨 Δ 界線 ±0.5 手；超界即用 1 手期貨拉返。",
                "止損：跨式買回總價 ≥ 權利金 2 倍即平倉；帳戶另有合計權益硬止損。",
                "溢價轉負（IV−HV < 0）暫停新增賣出；臨近到期按日程平倉／滾倉。",
                "監控：烽燧指標燈（只作提示，不具警報權）；對沖狀態由富途 API 核實。"],
            "disclaimer": "只作資訊展示，唔係投資建議。報價延遲，落單以券商即時價為準。",
        },
        "positions": [
            {"id": "HSI 月跨式", "instrument": pos.get("instrument"), "expiry": pos.get("expiry"), "strike": pos.get("strike"),
             "qty": pos.get("qty"), "entry_date": pos.get("entry_date"), "credit_pts": pos.get("credit_pts"),
             "credit_hkd": pos.get("credit_hkd"), "stop_buyback_pts": pos.get("stop_buyback_pts"), "entry_atm_iv": pos.get("entry_atm_iv")},
            {"id": "MHI 期貨對沖", "instrument": "小型恒指期貨 MHI2610", "net_lots": hedge_lots,
             "open_price": hedges[0]["price"] if hedges else None, "opened_hkt": hedges[0].get("time_hkt") if hedges else None},
        ] + ([
            {"id": "MES 跨式", "instrument": mes.get("instrument"), "expiry": mes.get("expiry"), "strike": mes.get("strike"),
             "qty": mes.get("qty"), "entry_date": mes.get("entry_date"), "credit_pts": mes.get("credit_pts"),
             "credit_usd": mes.get("credit_usd"), "stop_buyback_pts": mes.get("stop_buyback_pts"), "entry_iv": mes.get("entry_iv")}] if mes else []),
        "status": {
            "hsi": {"front": front, "straddle_delta": h_str, "hedge_lots": h_hedge if h_hedge is not None else hedge_lots,
                    "net_delta": h_net, "band": 0.5,
                    "hedge_verified_hkt": pos.get("hedge_verified_hkt"), "hedge_source": "富途 API（總指揮通報）"},
            "mes": {"es": es, "straddle_delta": m_delta if mes else None, "band": 0.5},
        },
        "events": hist["events"],
        "corrections": hist["corrections"],
    }
    p = D / "yunchui_public.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已寫入 {p}")


if __name__ == "__main__":
    main()
