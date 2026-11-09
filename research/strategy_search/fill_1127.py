"""IDEAS #1127：933 真倉成交價偏差＋R 單位對照（只量度，唔改真倉）。

預先登記（11-09 UTC，跑之前 commit）：
- 數據：GCS xau/sig/studentlive/state.json 嘅 orders（決策價 price、sl、tp、ticket）同 book（成交 entry、r、pnl_hkd、exit_est），
  只計 SIG_STUDENT_HWM_START（2026-11-09）之後開倉、而且 ticket 對得上嘅單。
- E6S4 入場區：mid＝(sl＋tp)／2（SL＝mid 外 4、TP＝mid 內 4），區＝mid ± Z（Z＝2）；S＝4 係回測 R 單位（fit_rules.simulate：r＝(出場−成交−成本)／S）。
- 每張計：①滑價＝成交對決策價（逆方向為正，美元）②出區距離＝成交喺入場區外幾多（逆方向為正，喺區內＝0）
  ③book R（實盤成交簿：分母＝決策價到 SL）④R_S＝實盤成交、回測單位（(出場−成交)×方向−成本）／S
  ⑤R_bt＝回測假設成交（買：min(決策價, 區頂)；賣：max(決策價, 區底)）、同一出場、回測單位。
  出場：用成交簿 exit_est（實際出場）；冇先當 R>0＝TP、否則＝SL（11-09 首跑後修正，判準唔變）。成本＝fit_rules.COST。
- 判（同 #1125 30 張一齊判）：平均滑價 ≥ 0.5 美元，或者 平均(R_S − R_bt) ≤ −0.05R → 提案改執行方式（例如限價單／收窄容許偏差），
  要使用者批；冇過線 → 照舊。#1125 30 張判斷要同時列 book R 同 R_S（回測期望係 S 單位），由使用者睇。
"""
import json
import os
import subprocess
import sys
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "FILL_1127.md")
START = dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc).timestamp()
Z, S = 2.0, 4.0
sys.path.insert(0, os.path.join(ROOT, "xau"))
try:
    import config  # noqa: E402
    COST = float(config.STUDENT_COST)
except Exception:  # noqa: BLE001
    COST = 0.30


def load():
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return json.load(open(sys.argv[1]))
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "gcp_agent.py"), "cat", "--object",
                          "xau/sig/studentlive/state.json"], capture_output=True, text=True, cwd=ROOT).stdout
    return json.loads(out)


def rows(st):
    orders = {o.get("ticket"): o for o in st.get("orders") or [] if o.get("ticket") and o.get("ok")}
    res = []
    for b in st.get("book") or []:
        o = orders.get(b.get("ticket"))
        if not o or (b.get("opened_ts") or 0) < START or b.get("r") is None:
            continue
        sgn = 1 if o.get("side") == "BUY" else -1
        sl, tp, dec, fill = float(o["sl"]), float(o["tp"]), float(o["price"]), float(b["entry"])
        mid = (sl + tp) / 2
        lo, hi = mid - Z, mid + Z
        exit_ = float(b["exit_est"]) if b.get("exit_est") is not None else (tp if b["r"] > 0 else sl)   # [11-09 修正] 用成交簿實際出場價（第 1 張唔係喺 SL 平）
        slip = (fill - dec) * sgn                                        # 買：成交高過決策價＝逆；賣：成交低過＝逆
        out_zone = max(0.0, (fill - hi) if sgn == 1 else (lo - fill))    # 買：高過區頂＝逆；賣：低過區底＝逆
        bt_fill = min(dec, hi) if sgn == 1 else max(dec, lo)
        r_s = ((exit_ - fill) * sgn - COST) / S
        r_bt = ((exit_ - bt_fill) * sgn - COST) / S
        res.append({"t": dt.datetime.fromtimestamp(b["opened_ts"], dt.timezone.utc).strftime("%m-%d %H:%M"), "ch": (b.get("ch") or "").split(":")[-1],
                    "side": "多" if sgn == 1 else "空", "lo": lo, "hi": hi, "dec": dec, "fill": fill, "slip": slip, "out": out_zone,
                    "r": b["r"], "r_s": r_s, "r_bt": r_bt, "hkd": b.get("pnl_hkd")})
    return res


def main():
    rs = rows(load())
    n = len(rs)
    L = ["# IDEAS #1127：933 真倉成交價偏差＋R 單位對照", "",
         f"更新：{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC｜只量度，唔改真倉；判斷同 #1125 30 張一齊（見腳本頂預先登記）。", "",
         "| 開倉 UTC | 規則 | 方向 | 入場區 | 決策價 | 成交 | 滑價 | 出區 | book R | R_S（實盤，回測單位） | R_bt（回測成交） |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in rs:
        L.append(f"| {x['t']} | {x['ch']} | {x['side']} | {x['lo']:.2f}–{x['hi']:.2f} | {x['dec']:.2f} | {x['fill']:.2f} | {x['slip']:+.2f} | {x['out']:.2f} | "
                 f"{x['r']:+.2f} | {x['r_s']:+.3f} | {x['r_bt']:+.3f} |")
    if n:
        avg = lambda k: sum(x[k] for x in rs) / n
        gap = avg("r_s") - avg("r_bt")
        flags = []
        if avg("slip") >= 0.5:
            flags.append("平均滑價 ≥ 0.5 美元")
        if gap <= -0.05:
            flags.append("平均 R_S − R_bt ≤ −0.05R")
        L += ["", f"**n＝{n}**｜平均滑價 {avg('slip'):+.2f} 美元｜出區張數 {sum(1 for x in rs if x['out'] > 0)}（平均 {avg('out'):.2f}）｜"
                  f"平均 book R {avg('r'):+.3f}｜平均 R_S {avg('r_s'):+.3f}｜平均 R_bt {avg('r_bt'):+.3f}｜R_S − R_bt {gap:+.3f}", "",
              ("⚠ 過咗預先登記線：" + "、".join(flags) + "（" + ("夠 30 張，照判" if n >= 30 else f"未夠 30 張（{n}），只記錄") + "）") if flags
              else f"未過線（{n}／30 張）。",
              "", "註：book R 分母＝決策價到 SL（約 6 美元）；回測 R 分母＝S＝4 美元，所以同一張單兩個數唔同，#1125 回測期望要對 R_S。"]
    else:
        L += ["", "未有 11-09 之後對得上嘅成交。"]
    open(OUT, "w").write("\n".join(L) + "\n")
    print("\n".join(L[-6:]))


if __name__ == "__main__":
    main()
