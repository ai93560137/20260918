"""[總指揮 11-09 批，只讀] 933 真倉 vs 影子總表 對拍：11-08 23:00 → 11-09 21:00 UTC，同一段 M1（券商 M1 存檔，同 shadow_board 一樣）。

三樣嘢逐個比：
A. 訊號：影子（batch_1120 r1121／r1122／r1123 嘅 raw＋60 分鐘冷卻）對 真倉 規則學生 log（GCS xau/sig/student/log/2026-11-09.jsonl）。
B. 成交：影子（fit_rules.simulate：入場區 ±0.3 用 K 線高低掂到就成交、TTL 30、每條規則獨立、可以同時多張）
         對 真倉實際（xau/sig/studentlive/state.json 成交簿＋orders）。
C. 重演真倉 _decide（xau/student_live.py）：每分鐘收市後用收市價判斷；一次一張；候選新→舊、TTL 30；
   版本「現行」＝遇到第一個「等入場區」就 return（現行程式）；版本「修正」＝等緊嘅跳過、繼續睇舊啲嘅候選。
   出場用之後 K 線高低：同一根 SL／TP 都掂當 SL。重演「現行」應該重現實際成交（驗證重演準唔準）。
只讀：唔改 env、唔改程式、唔寫 GCS。
用法：python3 research/strategy_search/parity_1109.py [學生log.json] [studentlive_state.json] → PARITY_1109.md"""
import datetime as dt
import json
import os
import subprocess
import sys

import numpy as np

ARGV = list(sys.argv)            # 下面匯入嘅模組會改 sys.argv，先保存
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, HERE)
import shadow_board as SB       # noqa: E402
import batch_1019 as B          # noqa: E402
import batch_1037 as B37        # noqa: E402
import batch_1083 as B83        # noqa: E402
import fit_rules as fr          # noqa: E402

T0 = fr.ts_of("2026-11-08T23:00")
T1 = fr.ts_of("2026-11-09T21:00")
RULES = ("m5spike", "spike2", "dopen15")
E, Z, S, RT = 6.0, 2.0, 4.0, 1.0
TOL = 0.30
TTL = 30 * 60
OUT = os.path.join(HERE, "PARITY_1109.md")
f = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%H:%M")


def gcs(obj):
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "gcp_agent.py"), "cat", "--object", obj],
                         capture_output=True, text=True, cwd=ROOT).stdout
    return json.loads(out)


def raw_signals(d):
    """同 batch_1120 r1121／r1122／r1123 一樣嘅 raw（未冷卻）。"""
    t, o, c = d["t"], d["o"], d["c"]
    out = {}
    b = B.resample(d, 300); km = B83.last_m1(d, b["t"], 300); raw = []
    for i in range(len(b["c"])):
        if km[i] < 30 or (b["h"][i] - b["l"][i]) < 6.0 or b["c"][i] == b["o"][i]:
            continue
        raw.append((int(km[i]), "BUY" if b["c"][i] < b["o"][i] else "SELL"))
    out["m5spike"] = raw
    raw = []
    for s, e in B37.days(t):
        if t[s] % 86400 >= 300:
            continue
        op = o[s]
        for i in range(s + 1, e):
            if abs(c[i] - op) >= 15.0:
                raw.append((i, "SELL" if c[i] > op else "BUY")); break
    out["dopen15"] = raw
    body = c - o; raw = []
    for i in range(30, len(c)):
        a, b2 = body[i - 1], body[i]
        if a > 0 and b2 > 0 and a + b2 >= 5.0:
            raw.append((i, "SELL"))
        elif a < 0 and b2 < 0 and a + b2 <= -5.0:
            raw.append((i, "BUY"))
    out["spike2"] = raw
    return out


def struct(price, side):
    sgn = 1 if side == "BUY" else -1
    mid = price - sgn * E
    return {"lo": mid - Z, "hi": mid + Z, "sl": mid - sgn * S, "tp": mid + sgn * RT * S, "sgn": sgn}


def exit_after(d, k0, side, sl, tp):
    """由第 k0 根（含）起，用高低判 SL／TP；同一根都掂當 SL。回傳 (出場價, 出場時間, 'SL'/'TP') 或 None。"""
    t, h, l = d["t"], d["h"], d["l"]
    for k in range(k0, len(t)):
        if side == "BUY":
            s_hit, t_hit = l[k] <= sl, h[k] >= tp
        else:
            s_hit, t_hit = h[k] >= sl, l[k] <= tp
        if s_hit:
            return sl, int(t[k]) + 60, "SL"
        if t_hit:
            return tp, int(t[k]) + 60, "TP"
    return None


def replay(d, preds, fixed):
    """重演 student_live._decide：每分鐘收市後（heartbeat ≈ t+60+31 秒）用收市價。"""
    t, c = d["t"], d["c"]
    idx = np.nonzero((t >= T0) & (t < T1))[0]
    used, trades, pos_until = set(), [], 0
    for k in idx:
        now = int(t[k]) + 60 + 31
        if now < pos_until:
            continue
        price = float(c[k])
        cands = [p for p in preds if 0 <= now - p["ts"] <= TTL][::-1]
        for p in cands:
            if p["id"] in used:
                continue
            st = struct(p["price"], p["side"])
            sgn = st["sgn"]
            if (price - st["sl"]) * sgn <= 0:
                used.add(p["id"]); continue                              # 止損已經觸發／錯邊 → 略過
            if not (st["lo"] - TOL <= price <= st["hi"] + TOL):
                if fixed:
                    continue                                              # 修正：等緊嘅跳過，睇下一個
                break                                                     # 現行：return「等現價入入場區」
            used.add(p["id"])
            ex = exit_after(d, k + 1, p["side"], st["sl"], st["tp"])
            if ex is None:
                trades.append({"ts": now, "rule": p["rule"], "side": p["side"], "pred": f(p["ts"]), "fill": price, "exit": None, "how": "未完", "r": None})
                pos_until = 10**12
            else:
                r = ((ex[0] - price) * sgn) / abs(price - st["sl"])        # 成交簿口徑：分母＝決策價到 SL
                trades.append({"ts": now, "rule": p["rule"], "side": p["side"], "pred": f(p["ts"]), "fill": price, "exit": ex[0], "how": ex[2],
                               "out": f(ex[1]), "r": round(r, 2), "r_s": round(((ex[0] - price) * sgn - 0.3) / S, 3)})
                pos_until = ex[1] + 31
            break
    return trades


def main():
    d = SB.load_data()
    t = d["t"]
    log = json.load(open(ARGV[1])) if len(ARGV) > 1 else gcs("xau/sig/student/log/2026-11-09.jsonl")
    st = json.load(open(ARGV[2])) if len(ARGV) > 2 else gcs("xau/sig/studentlive/state.json")
    preds = sorted([{"id": p["id"], "rule": p["student"].split(":")[-1], "side": p["side"], "price": float(p["price"]), "ts": float(p["ts"])}
                    for p in log if p.get("student", "").split(":")[-1] in RULES and T0 <= p["ts"] < T1], key=lambda x: x["ts"])

    # A. 訊號對拍
    raw = raw_signals(d)
    sh = {}
    for rule in RULES:
        sigs = fr.cooldown(sorted(raw[rule]), t, 60, T0, T1)
        res = fr.simulate(fr.future_mats(d, sigs), E, Z, S, RT)
        sh[rule] = [{"ts": int(t[i]) + 60, "side": s, "price": float(d["c"][i]), "r": (None if np.isnan(x) else round(float(x), 3))} for (i, s), x in zip(sigs, res)]
    L = ["# 933 真倉 vs 影子總表 對拍（11-08 23:00 → 11-09 21:00 UTC）", "",
         f"- 跑：{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC；只讀，唔改 env／程式／GCS；總指揮 11-09 批。",
         "- 數據：券商 M1 存檔（同 shadow_board）；真倉訊號＝GCS 規則學生 log；真倉成交＝studentlive 成交簿。", "",
         "## A. 訊號：影子（60 分鐘冷卻）對 真倉規則學生", "", "| 規則 | 影子 時間／方向／價 | 真倉 時間／方向／價 | 對得上？ |", "|---|---|---|---|"]
    n_match = n_sh = n_live = 0
    for rule in RULES:
        lv = [p for p in preds if p["rule"] == rule]
        n_sh += len(sh[rule]); n_live += len(lv)
        seen = set()
        for s in sh[rule]:
            m = next((p for i, p in enumerate(lv) if i not in seen and abs(p["ts"] - s["ts"]) <= 90 and p["side"] == s["side"]), None)
            if m:
                seen.add(lv.index(m)); n_match += 1
            L.append(f"| {rule} | {f(s['ts'])} {s['side']} {s['price']:.2f} | " + (f"{f(m['ts'])} {m['side']} {m['price']:.2f} | ✅" if m else "— | ❌ 真倉冇") + " |")
        for i, p in enumerate(lv):
            if i not in seen:
                L.append(f"| {rule} | — | {f(p['ts'])} {p['side']} {p['price']:.2f} | ❌ 影子冇 |")
    L += ["", f"影子 {n_sh} 個、真倉 {n_live} 個，對得上 {n_match} 個。", ""]

    # B. 影子成交 vs 真倉實際
    od = {o.get("ticket"): o for o in st.get("orders") or [] if o.get("ticket")}
    actual = [{"ts": b["opened_ts"], "rule": (b.get("ch") or "").split(":")[-1], "side": "BUY" if b["side"] == 1 else "SELL",
               "fill": b["entry"], "dec": (od.get(b["ticket"]) or {}).get("price"), "r": b["r"]} for b in st.get("book") or [] if T0 <= b["opened_ts"] < T1]
    L += ["## B. 影子成交（每條規則獨立）", "", "| 規則 | 訊號 | 方向 | 影子結果 R（回測單位 ÷4） |", "|---|---|---|---|"]
    for rule in RULES:
        for s in sh[rule]:
            L.append(f"| {rule} | {f(s['ts'])} | {s['side']} | " + ("未成交（TTL 內冇入區）" if s["r"] is None else f"{s['r']:+.3f}") + " |")
    allr = [s["r"] for rule in RULES for s in sh[rule] if s["r"] is not None]
    L += ["", f"影子成交 {len(allr)} 張，ΣR（回測單位）{sum(allr):+.2f}；冇一次一張限制，可以同時揸幾張。", ""]

    # C. 重演
    cur, fix = replay(d, preds, False), replay(d, preds, True)
    L += ["## C. 真倉實際 vs 重演（現行邏輯／修正邏輯）", "", "| 真倉實際 開倉 規則 方向 決策價→成交 R | 重演「現行」 | 重演「修正」（等緊嘅跳過） |", "|---|---|---|"]
    rows = max(len(actual), len(cur), len(fix))
    fmt = lambda x: (f"{f(x['ts'])} {x['rule']} {x['side']}（訊號 {x['pred']}）@{x['fill']:.2f} → {x['how']} {x['r']:+.2f}" if x.get("r") is not None
                     else f"{f(x['ts'])} {x['rule']} {x['side']} @{x['fill']:.2f} 未完") if x else "—"
    for i in range(rows):
        a = actual[i] if i < len(actual) else None
        L.append("| " + (f"{f(a['ts'])} {a['rule']} {a['side']} {a['dec']}→{a['fill']} {a['r']:+.2f}" if a else "—") + " | "
                 + fmt(cur[i] if i < len(cur) else None) + " | " + fmt(fix[i] if i < len(fix) else None) + " |")
    sr = lambda xs, k: sum(x[k] for x in xs if x.get(k) is not None)
    L += ["", f"- 真倉實際：{len(actual)} 張，成交簿 ΣR {sum(a['r'] for a in actual):+.2f}",
          f"- 重演現行：{len(cur)} 張，ΣR {sr(cur, 'r'):+.2f}（回測單位 {sr(cur, 'r_s'):+.2f}）",
          f"- 重演修正：{len(fix)} 張，ΣR {sr(fix, 'r'):+.2f}（回測單位 {sr(fix, 'r_s'):+.2f}）", ""]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
