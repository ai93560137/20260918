import json, sys, subprocess, collections, statistics
day = sys.argv[1]
def cat(o):
    r = subprocess.run(["python3", "scripts/gcp_agent.py", "cat", "--object", o], capture_output=True, text=True)
    t = r.stdout; i = min([x for x in (t.find("{"), t.find("[")) if x >= 0] or [-1])
    return t[i:] if i >= 0 else ""
for pre in ("xau/", "fx/eurusd/"):
    rows = []
    for ln in cat(f"{pre}decisions/{day}.jsonl").splitlines():
        try: o = json.loads(ln)
        except ValueError: continue
        rows += o if isinstance(o, list) else [o]
    kinds = collections.Counter(r.get("kind") for r in rows)
    dec = [r for r in rows if r.get("kind") == "decide"]
    act = collections.Counter(r.get("final") or r.get("action") for r in dec)
    err = sum(1 for r in rows if r.get("error"))
    cost = [float(r.get("cost_usd") or 0) for r in rows if r.get("cost_usd") is not None]
    lat = sorted(float(r.get("latency_s") or r.get("latency") or 0) for r in dec if (r.get("latency_s") or r.get("latency")))
    u = [r.get("usage") or {} for r in dec]
    cw1 = [x.get("cache_write_1h") for x in u if x.get("cache_write_1h") is not None]
    cw5 = [x.get("cache_write_5m") for x in u if x.get("cache_write_5m") is not None]
    reuse = [r for r in rows if r.get("kind") == "reuse" or r.get("reuse") or r.get("reuse_shadow")]
    print(f"== {pre} rows {len(rows)} kinds {dict(kinds)}")
    print(f" actions {dict(act)} errors {err} cost Σ{sum(cost):.2f} avg/dec {sum(cost)/max(1,len(dec)):.3f}")
    if lat: print(f" p95 lat {lat[int(0.95*(len(lat)-1))]:.1f}s n={len(lat)}")
    if cw1: print(f" cw1h avg {statistics.mean(cw1):.0f} cw5m avg {statistics.mean(cw5) if cw5 else 0:.0f}")
    print(f" reuse {len(reuse)}; reuse_shadow opens {sum(1 for r in reuse if str(r.get('reuse_shadow') or r.get('action') or '').startswith('OPEN'))}")
    if dec: print(" keys sample", sorted(dec[-1].keys())[:40])
    st = json.loads(cat(f"{pre}state.json") or "{}")
    print(" hold_rules", (st.get("hold_rules") or {}).get("stats"))
    print(" paper/live trades today", [ (t.get("side"), t.get("entry"), t.get("exit_est") or t.get("exit"), t.get("r") or t.get("R"), t.get("reason")) for t in (st.get("book") or st.get("trades") or []) if day.replace("-","") in str(t.get("closed_utc") or "").replace("-","")][:10])
    print(" ladder", (st.get("ladder") or {}).get("level") if isinstance(st.get("ladder"), dict) else st.get("ladder"), "position", st.get("position"))
