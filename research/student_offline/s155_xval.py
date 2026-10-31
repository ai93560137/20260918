"""[#155] 921 L29–L35 嘅「學生同向」分組：實時學生 log vs 離線 Dukascopy 學生（rev15／level／swing，60 分鐘冷卻）。
用法：python3 research/student_offline/s155_xval.py"""
import os
import sys, datetime as dt
sys.argv=[sys.argv[0],"rev15"]; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rev15_gap as g
duka=g.load(g.config.PREFIX+"duka/", g.days_between("2026-10-27","2026-10-30"),"json")
ts=lambda s: int(dt.datetime.fromisoformat("2026-10-30 "+s).replace(tzinfo=dt.timezone.utc).timestamp())
trades=[("L29","10:22"),("L30","11:36"),("L31","12:50"),("L32","13:27"),("L33","13:47"),("L34","14:47"),("L35","17:27")]
preds=[]
for r in ("rev15","level","swing"):
    g.RULE="rule:"+r
    preds+= [dict(p,rule=r) for p in g.run(duka, ts("06:00"), ts("18:00"))]
for name,t in trades:
    T=ts(t); near=[p for p in preds if T-1800<=p["ts"]<=T]
    hit=[p for p in near if p["side"].upper().startswith("S")]
    print(name, t, "離線同向:", [(p["rule"],dt.datetime.fromtimestamp(p["ts"],dt.timezone.utc).strftime("%H:%M")) for p in hit], "反向:", [(p["rule"],dt.datetime.fromtimestamp(p["ts"],dt.timezone.utc).strftime("%H:%M")) for p in near if p not in hit])
