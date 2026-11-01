"""[R363] 按風險計手數（使用者 11-01：921、932、931 S1、933、934 全部改用；每張風險＝該戶口權益 XAU_RISK_PCT%）。預設關（XAU_RISK_SIZING=0）。
手數＝floor(權益 × pct% ÷（|入場 − 初始止損| × 合約 × HKD／報價貨幣）, 0.01)，夾喺 [0.01, 該書硬上限]；
計出嚟細過 0.01 → 唔開（寫原因）；權益讀唔到 → 退返固定 XAU_RISK_FALLBACK_LOTS（0.05）並寫 WARNING。
所有書（921 main／931 S1／932 follower／933 student_live／934 g7_live／tgsignal）用同一個函數。純函數，方便測試。"""
import math

import config
import storage
from storage import StorageError

STEP = 0.01


def per_lot_loss_hkd(entry, stop):
    """1 手由入場去到止損蝕幾多 HKD（同 live_book.make 反推出場價嘅換算一致）。"""
    return abs(float(entry) - float(stop)) * config.CONTRACT_SIZE * config.HKD_PER_USD / (config.QUOTE_PER_USD or 1.0)


def size(equity, entry, stop, max_lots, pct=None, fallback=None):
    """回傳 (手數, info)。手數 None＝按風險關（用返原本手數）；0.0＝唔開（info["why"]）。
    info：mode（off／risk／fallback／skip）、risk_hkd、risk_pct、per_lot_hkd、why。"""
    if not config.RISK_SIZING:
        return None, {"mode": "off"}
    pct = config.RISK_PCT if pct is None else pct
    fallback = config.RISK_FALLBACK_LOTS if fallback is None else fallback
    try:
        eq = float(equity)
    except (TypeError, ValueError):
        eq = 0.0
    if not eq or eq <= 0 or math.isnan(eq):
        lots = round(min(fallback, max_lots), 2)
        return lots, {"mode": "fallback", "why": "權益讀唔到，用固定手數", "lots": lots}
    if entry is None or stop is None:
        return 0.0, {"mode": "skip", "why": "冇入場價或者止損，唔計得風險"}
    per = per_lot_loss_hkd(entry, stop)
    if per <= 0:
        return 0.0, {"mode": "skip", "why": "止損距離 0"}
    budget = eq * pct / 100.0
    raw = budget / per
    lots = math.floor(raw / STEP + 1e-9) * STEP
    lots = round(min(lots, max_lots), 2)
    if lots < STEP:
        return 0.0, {"mode": "skip", "why": f"權益 {pct:g}%＝{budget:,.0f} HKD 唔夠 0.01 手（止損 {abs(entry - stop):.2f}、0.01 手風險 {per * STEP:,.0f} HKD）",
                     "per_lot_hkd": round(per, 2), "budget_hkd": round(budget, 2)}
    risk = lots * per
    return lots, {"mode": "risk", "lots": lots, "risk_hkd": round(risk, 2), "risk_pct": round(risk / eq * 100, 3),
                  "per_lot_hkd": round(per, 2), "budget_hkd": round(budget, 2), "capped": lots >= max_lots and raw > max_lots}


def open_risk(equity_file, position_files):
    """戶口合計開倉風險：Σ |入場 − 止損| × 手數 × 合約 × HKD ÷ 權益。止損冇設嘅倉另計（none_sl）。讀唔到回 None。"""
    try:
        eq = float((storage.read_json(equity_file, {}) or {}).get("equity") or 0)
    except (StorageError, TypeError, ValueError):
        return None
    total, n, none_sl = 0.0, 0, 0
    for f in position_files:
        try:
            pos = (storage.read_json(f, {}) or {}).get("positions") or []
        except StorageError:
            continue
        for p in pos:
            n += 1
            if p.get("stop") is None or p.get("entry") is None or p.get("lots") is None:
                none_sl += 1
                continue
            total += per_lot_loss_hkd(p["entry"], p["stop"]) * float(p["lots"])
    if eq <= 0:
        return {"positions": n, "risk_hkd": round(total, 2), "pct": None, "none_sl": none_sl}
    return {"positions": n, "risk_hkd": round(total, 2), "pct": round(total / eq * 100, 2), "none_sl": none_sl}


def accounts_open_risk():
    """兩個真戶口：…63（921＋932）、…69（931＋933＋934）。路徑用 MAIN_PREFIX（xau/）＋ sig/。"""
    base = config.MAIN_PREFIX
    sig = base + "sig/"
    return {"…63（921＋932）": open_risk(base + "account.json", [base + "account.json", sig + "follow/account.json"]),
            "…69（931＋933＋934）": open_risk(sig + "account.json", [sig + "account.json", sig + "studentlive/account.json", sig + "g7live/account.json"])}
