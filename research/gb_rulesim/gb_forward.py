"""[IDEAS #149／#150] Gold Brother（0342）同黃金戰鬥機（5117）影子前向：經紀 M1，唔落單。

使用者 10-29「停跟 Gold Brother，但學佢入場，再改善佢」＋「黃金戰鬥機做回測同 gold brother 一樣」；#150 判 5m 期貨代理對 5117（SL 7.5）唔可信，
所以兩個頻道都改用經紀 M1 前向計 20 張先判。

每次跑：
1. 歸檔：讀 GCS xau/sig/signals/recent.json（只留最近 100 條，會滾走），把 0342／5117 嘅 new_signal 解析欄位（方向、入場區、SL、TP、時間）
   寫入 xau/sig/fwd_archive/<sid>.json——**唔存訊號原文**。補返「評分紀錄只留 100 條、history 匯入止於 10-21」嘅缺口。
2. 計：歸檔入面 START 之後嘅訊號，用 GCS xau/sig/bars/<日>.jsonl（經紀 M1，無基差）行 gb_rulesim.simulate；訊號後要有 ≥ 6 小時 K 線先計（未夠嘅標「未完」）。
3. 寫 xau/sig/gb_forward/latest.json／latest.md；Actions 日誌只印數字。
判法（預先登記，IDEAS #149）：每頻道候選（0342＝V13；5117＝V11）20 張後 ΣR ≥ +2.0R、PF ≥ 1.2、最大回撤 ≤ 3R，且好過同批 V0 → 先提真倉 0.05 手（使用者批）。"""
import argparse
import datetime as dt
import json
import time

import gb_rulesim as gb

START = "2026-10-29 00:00:00"          # 停跟 0342 嗰日起計（#149 預先登記）
ARCHIVE = "xau/sig/fwd_archive/"
OUT = "xau/sig/gb_forward/"
CHANNELS = {"0342": {"name": "Gold Brother", "id": "2249680342", "candidate": "V13"},
            "5117": {"name": "黃金戰鬥機", "id": "1473735117", "candidate": "V11"}}
ARCHIVE_ONLY = ("5231",)              # [IDEAS #152] CTC 只歸檔（學生＋CTC 同向確認前向用），唔計變體
VARS = ("V0", "V6", "V11", "V13")
MIN_AFTER_SEC = 6 * 3600
TARGET_N = 20


def archive_doc(rec):
    """recent.json 一條 → 歸檔 dict（只保留解析欄位）；唔係 0342／5117（或只歸檔嘅 5231）入場訊號就 None。"""
    ch = str(rec.get("ch") or "")[-4:]
    if ch not in CHANNELS and ch not in ARCHIVE_ONLY:
        return None
    s = gb.parse_recent(rec, ch)
    if not s:
        return None
    return {**s, "ch": ch, "parse_confidence": rec.get("parse_confidence"), "archived_utc": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}


def judge(summary, v0_summary, n_target=TARGET_N):
    """預先登記判法。回傳（狀態字串, 細項 dict）。"""
    if summary["n"] < n_target:
        return f"未夠 {summary['n']}／{n_target} 張", {}
    c = {"ΣR≥+2.0": summary["sum_r"] >= 2.0, "PF≥1.2": (summary["pf"] or 0) >= 1.2,
         "回撤≤3R": summary["max_dd_r"] >= -3.0, "好過V0": summary["sum_r"] > v0_summary["sum_r"]}
    return ("達標" if all(c.values()) else "唔達標"), c


def evaluate(signals, bars, now_ts):
    """signals：歸檔 dict 列表；bars：經紀 M1。回傳 {ch: {"done": n, "pending": n, "result": {var: {...}}}}。"""
    last = bars[-1]["utc"] if bars else 0
    out = {}
    for ch, meta in CHANNELS.items():
        sigs = sorted([s for s in signals if s["ch"] == ch and s["utc"] >= START], key=lambda s: s["ts"])
        done = [s for s in sigs if last - s["ts"] >= MIN_AFTER_SEC]
        res = {}
        for k in VARS:
            per = []
            for s in done:
                win = [b for b in bars if s["ts"] - 3600 <= b["utc"] <= s["ts"] + 24 * 3600]
                r = gb.simulate(win, s, **gb.VARIANTS[k]["kw"])
                r.update({"sid": s["sid"], "utc": s["utc"], "side": s["side"]})
                per.append(r)
            res[k] = {"name": gb.VARIANTS[k]["name"], "summary": gb.summarize(per), "per_signal": per}
        cand = meta["candidate"]
        verdict, detail = judge(res[cand]["summary"], res["V0"]["summary"])
        out[ch] = {"name": meta["name"], "candidate": cand, "done": len(done), "pending": len(sigs) - len(done),
                   "verdict": verdict, "detail": detail, "result": res}
    return out


def to_md(ev, meta):
    lines = ["# 0342／5117 影子前向（IDEAS #149／#150，經紀 M1，唔落單）", "",
             f"- 跑：{meta['run_utc']} UTC；起計 {START}；K 線到 {meta['bars_to']}；歸檔共 {meta['archived']} 張（今次新增 {meta['new']}）", ""]
    for ch, e in ev.items():
        lines += [f"## {e['name']}（{ch}）候選 {e['candidate']}：{e['verdict']}（已完 {e['done']}、未完 {e['pending']}）", "",
                  "| 變體 | 張 | 勝 | 平 | 負 | ΣR | PF | 最大回撤R |", "|---|---|---|---|---|---|---|---|"]
        for k, v in e["result"].items():
            s = v["summary"]
            lines.append(f"| {k} {v['name']} | {s['n']} | {s['win']} | {s['flat']} | {s['loss']} | {s['sum_r']} | {s['pf']} | {s['max_dd_r']} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10, help="讀最近幾日經紀 K 線")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    g = gb.Gcs()
    have = {n.split("/")[-1][:-5] for n in g.list(ARCHIVE)}
    new = 0
    for rec in g.read_json(gb.RECENT) or []:
        d = archive_doc(rec)
        if d and d["sid"] not in have:
            new += 1
            have.add(d["sid"])
            if not a.dry_run:
                g.write(ARCHIVE + d["sid"] + ".json", json.dumps(d, ensure_ascii=False), "application/json")
    signals = [g.read_json(n) for n in g.list(ARCHIVE)]
    signals = [s for s in signals if isinstance(s, dict) and s.get("ch") in CHANNELS]
    bars = gb.fetch_broker_bars(g, a.days)
    ev = evaluate(signals, bars, time.time())
    meta = {"run_utc": dt.datetime.utcnow().strftime("%Y-%m-%dT%H%MZ"), "archived": len(signals), "new": new,
            "bars_to": dt.datetime.utcfromtimestamp(bars[-1]["utc"]).strftime("%Y-%m-%d %H:%M") if bars else "冇"}
    md = to_md(ev, meta)
    print(md)
    if not a.dry_run:
        g.write(OUT + "latest.json", json.dumps({"meta": meta, "eval": ev}, ensure_ascii=False), "application/json")
        g.write(OUT + "latest.md", md, "text/markdown; charset=utf-8")
        print("已寫 GCS", OUT + "latest.json／latest.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
