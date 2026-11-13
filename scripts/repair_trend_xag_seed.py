"""[IDEAS #1442] 白銀趨勢簿日線修復：將 gs://<bucket>/xag/trend/state.json 嘅 d1 換成券商 M1 砌嘅完整日線
（xau/trend_d1_seed_xagusd.py，由 research/strategy_search/build_seed_xag.py 產生）。原因：服務第一次心跳已經用舊種子（到 11-10）
寫咗 420 日 d1，程式只喺 d1 < 270 日先會再用種子，所以換種子再部署補唔到 11-10 之後嘅缺日。

安全（總指揮 11-13 要求）：預設 dry-run，只列改動日子同前後 OHLC；--yes 先寫。寫之前檢查 XAU_TREND_LIVE=0、state 冇 pos、
EA 冇持倉、冇排緊指令、心跳產品係 XAGUSD，任何一樣唔啱就拒絕；先備份舊 state 到 xag/trend/state.backup-<UTC>.json（唔刪）；
用 generation 前置條件寫，唔會蓋過服務同時嘅寫入。只改 d1（同 repaired_utc 記號），其餘欄位唔郁。
用法：python3 scripts/repair_trend_xag_seed.py [--yes]"""
import datetime as dt
import json
import sys
import time
from urllib.parse import quote

OBJ = "xag/trend/state.json"
ACCT = "xag/trend/account.json"
OFF = ("", "0", "false", "no", "off")


def refusal(env, state, account):
    """純函數：有任何唔安全就回傳原因，否則 None。"""
    if str((env or {}).get("XAU_TREND_LIVE", "")).strip().lower() not in OFF:
        return "XAU_TREND_LIVE 唔係 0（趨勢簿開緊），唔修"
    if (state or {}).get("pos"):
        return "state 有 pos（服務以為有倉），唔修"
    if (state or {}).get("pending_cmds"):
        return "有排緊嘅指令，唔修"
    if (account or {}).get("positions"):
        return "EA 回報有持倉，唔修"
    if "XAGUSD" not in str((account or {}).get("symbol") or "").upper():
        return f"心跳產品唔係 XAGUSD（{(account or {}).get('symbol')!r}），唔修"
    return None


def merge_day(a, b):
    """同一日兩個來源（種子同心跳）合併：開市用較早嗰個、收市用較遲嗰個、高低取極值。"""
    lo, hi = (a, b) if a["t0"] <= b["t0"] else (b, a)
    last = a if a["t1"] >= b["t1"] else b
    return {"o": lo["o"], "h": max(a["h"], b["h"]), "l": min(a["l"], b["l"]), "c": last["c"], "t0": lo["t0"], "t1": last["t1"]}


def new_d1(cur, seed, keep=420):
    """純函數：種子範圍內嘅日子以種子為準（最後一日同心跳合併，因為種子可能未到收市）；種子之後嘅日子保留心跳砌嘅。"""
    cur, seed = cur or {}, seed or {}
    if not seed:
        return dict(cur)
    last = max(seed, key=int)
    out = {k: dict(v) for k, v in seed.items()}
    for k, v in cur.items():
        if int(k) > int(last):
            out[k] = dict(v)
        elif k == last:
            out[k] = merge_day(seed[k], v)
    return {k: out[k] for k in sorted(out, key=int)[-keep:]}


def changes(cur, new):
    """純函數：[(日, 舊或 None, 新或 None)]，只列有變嘅日子。"""
    out = []
    for k in sorted(set(cur or {}) | set(new or {}), key=int):
        a, b = (cur or {}).get(k), (new or {}).get(k)
        if a is None or b is None or any(a.get(x) != b.get(x) for x in ("o", "h", "l", "c", "t0", "t1")):
            out.append((k, a, b))
    return out


def fmt(k, a, b):
    day = dt.datetime.fromtimestamp(int(k) * 86400, dt.timezone.utc).strftime("%Y-%m-%d %a")
    f = lambda r: "（冇）" if r is None else f"O {r['o']} H {r['h']} L {r['l']} C {r['c']}｜{(r['t1'] - r['t0']) / 3600:.1f} 小時"  # noqa: E731
    return f"{day}：{f(a)} → {f(b)}"


def gaps(d1, lookback=30):
    """最近 lookback 日入面缺咗嘅平日（星期一至五）；假期會被列出，要人手睇。"""
    ks = sorted(int(k) for k in d1)
    if not ks:
        return []
    have = set(ks)
    return [dt.datetime.fromtimestamp(k * 86400, dt.timezone.utc).strftime("%Y-%m-%d") for k in range(max(ks[0], ks[-1] - lookback), ks[-1])
            if (k + 3) % 7 < 5 and k not in have]


def main(argv):
    sys.path.insert(0, "scripts"); sys.path.insert(0, "xau")
    import gcp_agent as G
    import trend_d1_seed_xagusd as S
    write = "--yes" in argv
    ctx = G.Ctx(G.build_parser().parse_args(["--profile", "xag", "whoami"])); s, B = ctx.session, ctx.bucket
    svc = G.require_service(ctx); env = {e["name"]: e.get("value") for e in svc["template"]["containers"][0].get("env", [])}
    for _ in range(6):
        url = f"{G.GCS_API}/b/{B}/o/{quote(OBJ, safe='')}"
        gen = s.get(url, timeout=30).json()["generation"]
        cur = s.get(url, params={"alt": "media", "ifGenerationMatch": gen}, timeout=30).json()
        account = G.gcs_get(ctx, ACCT) or {}
        why = refusal(env, cur, account)
        if why:
            print("❌ 拒絕：" + why); return 2
        d1 = new_d1(cur.get("d1"), S.SEED); ch = changes(cur.get("d1"), d1)
        print(f"📝 {OBJ}：d1 {len(cur.get('d1') or {})} 日 → {len(d1)} 日；有變 {len(ch)} 日；修復後缺日位：{gaps(d1) or '冇'}")
        for k, a, b in ch[-15:]:
            print("   " + fmt(k, a, b))
        if len(ch) > 15:
            print(f"   …（另外 {len(ch) - 15} 日較舊嘅改動冇列）")
        if not ch:
            print("沒有變更。"); return 0
        if not write:
            print("（dry-run；確認無誤後加 --yes 先會寫。會先備份舊 state。）"); return 0
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"); up = f"{G.GCS_UPLOAD_API}/b/{B}/o"
        r = s.post(up, params={"uploadType": "media", "name": f"xag/trend/state.backup-{stamp}.json", "ifGenerationMatch": 0},
                   data=json.dumps(cur, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, timeout=30)
        if r.status_code != 200:
            print(f"❌ 備份失敗 HTTP {r.status_code}，冇改任何嘢"); return 1
        new = {**cur, "d1": d1, "repaired_utc": f"{stamp} 日線由券商 M1 種子修復（scripts/repair_trend_xag_seed.py）"}
        r = s.post(up, params={"uploadType": "media", "name": OBJ, "ifGenerationMatch": gen},
                   data=json.dumps(new, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, timeout=30)
        if r.status_code == 200:
            print(f"✅ 已寫入；備份 xag/trend/state.backup-{stamp}.json"); return 0
        print(f"⚠️ 寫入撞到服務同時更新（HTTP {r.status_code}），重試…"); time.sleep(3)
    print("❌ 重試 6 次都寫唔到，冇改 state（備份檔保留）"); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
