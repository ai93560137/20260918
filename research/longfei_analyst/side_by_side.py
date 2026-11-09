"""使用者 vs AI 分析員並排計分（使用者 11-08「並排計分」）。

同一套規則（pack.score_call：support／resistance 睇收市、target 睇最高最低、bias 睇 horizon 日後收市方向）計：
  使用者：research/longfei_analyst/user_calls.json（由 notes/「可計分」抄）
  AI：GCS ops/longfei/analyst/scorecard.json 嘅 calls（只計同期：日期 ≥ 使用者第一條 call）
輸出：GCS ops/longfei/analyst/side_by_side.json，同埋印表。

用法：python3 research/longfei_analyst/side_by_side.py [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pack  # noqa: E402

OUT = "ops/longfei/analyst/side_by_side.json"


def score(c, d1, base):
    """同 pack.score_call，但未到期都可以提早定：target 已經掂到＝✅；support／resistance 已經收市穿＝❌。兩邊用同一個。"""
    r = pack.score_call(c, d1, base)
    if r is not None:
        return r
    path = [b for b in d1 if b[0] > base][:c.get("horizon", 5)]
    if not path:
        return None
    start = next(b[4] for b in reversed(d1) if b[0] <= base)
    k = c["kind"]
    if k == "target":
        down = c["level"] < start
        hit = next((b for b in path if (b[3] <= c["level"] if down else b[2] >= c["level"])), None)
        return {"ok": True, "detail": f"{hit[0]} 掂到（提早）"} if hit else None
    if k == "support":
        bad = next((b for b in path if b[4] < c["level"]), None)
        return {"ok": False, "detail": f"{bad[0]} 收市 {bad[4]:,.2f} 跌穿（提早）"} if bad else None
    if k == "resistance":
        bad = next((b for b in path if b[4] > c["level"]), None)
        return {"ok": False, "detail": f"{bad[0]} 收市 {bad[4]:,.2f} 升穿（提早）"} if bad else None
    return None


def summ(rows):
    done = [r for r in rows if r.get("result")]
    out = {"n": len(done), "hit": sum(1 for r in done if r["result"]["ok"]), "pending": len(rows) - len(done)}
    out["rate"] = round(out["hit"] / out["n"], 3) if out["n"] else None
    by = {}
    for r in done:
        k = by.setdefault(r["kind"], {"n": 0, "hit": 0})
        k["n"] += 1
        k["hit"] += r["result"]["ok"]
    out["by_kind"] = by
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data = {}
    for name in ("NQ", "ES", "SPX", "HSI", "VIX", "RSP", "VXN", "VVIX", "NVDA"):
        raw = pack.gcs_cat(pack.DATA + f"{name}.json")
        if raw:
            data[name] = json.loads(raw)["d1"]
    user = json.loads((HERE / "user_calls.json").read_text(encoding="utf-8"))["calls"]
    for c in user:
        d1 = data.get(c["market"])
        c["result"] = score(c, d1, c["base"]) if d1 else None
    start = min(c["date"] for c in user)
    sc = json.loads(pack.gcs_cat(pack.OUT + "scorecard.json") or "{}")
    ai = [c for c in sc.get("calls", []) if (c.get("date") or "") >= start]
    for c in ai:
        d1 = data.get(c.get("market"))
        c["result"] = score(c, d1, c["base_used"]) if d1 and c.get("base_used") else None
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "since": start,
           "user": summ(user), "ai": summ(ai),
           "user_calls": user, "ai_calls": ai}
    print(f"同期（{start} 起）  使用者 {res['user']['hit']}/{res['user']['n']}（{res['user']['rate']}），"
          f"未到期 {res['user']['pending']}   AI {res['ai']['hit']}/{res['ai']['n']}（{res['ai']['rate']}），未到期 {res['ai']['pending']}")
    for who, rows in (("使用者", user), ("AI", ai)):
        for r in rows:
            if r.get("result"):
                print(who, r["date"], r["market"], r["kind"], r.get("level", r.get("dir")), "✅" if r["result"]["ok"] else "❌", r["result"]["detail"])
    if not a.dry_run:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        pack.gcs_put(OUT, f.name)


if __name__ == "__main__":
    main()
