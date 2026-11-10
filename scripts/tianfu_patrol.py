import json,subprocess,datetime as dt,urllib.request,os,time
S=os.path.dirname(os.path.abspath(__file__))
f=lambda t: dt.datetime.fromtimestamp(t,dt.timezone.utc).strftime("%m-%d %H:%M") if isinstance(t,(int,float)) and t else t
for u in ("zhuge-xau","zhuge-xau-sig","zhuge-eurusd"):
    d=json.loads(urllib.request.urlopen(f"https://{u}-1056099871997.europe-west1.run.app/?format=json",timeout=30).read())
    print("==",u,"recv",d.get("account_received_utc"),"acct…",str(d.get("account_id") or "")[-2:],"off",d.get("server_offset"),"dry",d.get("ea_dry_run"),"trade",all((d.get("trade_allowed") or {}).values()),"open",d.get("market_open"))
    print(" mode",(d.get("control") or {}).get("mode"),"ladder",(d.get("ladder") or {}).get("level"),"pos",d.get("live_positions"),"pending",[c.get("text","")[:70] for c in (d.get("pending_cmds") or [])][-3:])
    rl=(d.get("risk_sizing") or {}).get("last") or {}
    print(" widen",d.get("sltp_widen"),"pct",(d.get("risk_sizing") or {}).get("pct"),"risk_last",f(rl.get("ts")),rl.get("lots"),rl.get("risk_pct"),"max",(d.get("lots") or {}).get("max"),"blocked",(d.get("data_block") or {}).get("blocked"))
    if u!="zhuge-eurusd": print(" open_risk",d.get("open_risk"))
    lb=d.get("live_book") or {}; s=lb.get("summary") or {}
    print(" book n",s.get("n"),"today",s.get("today"),"today_n",s.get("today_n"),"pf",s.get("pf"),"total",s.get("total"),"open",lb.get("open"))
    errs=[x for x in (d.get("decisions") or []) if x.get("error")]
    opens=[(f(x.get("ts")),x.get("final"),x.get("stop"),x.get("target"),(x.get("rejected") or "")[:50]) for x in (d.get("decisions") or []) if str(x.get("final") or x.get("action") or "").startswith(("OPEN","UPDATE"))]
    print(" dec errors",len(errs),"opens/updates",opens[-4:])
    # [11-07] API 餘額不足即報（11-06 08:38–17:24 UTC 試過全日冇決策都冇人發現）
    cred=[x for x in errs if "credit balance" in str(x.get("error") or x.get("reason") or "")]
    if cred: print(" ⚠⚠ API 餘額不足：最近",len(cred),"個決策出 credit balance 錯，最新",f(cred[-1].get("ts")),"→ 即報總指揮、叫使用者喺 Anthropic Console 充值")
    for k in ("student_live","g7_live","combo_live","follow"):
        x=d.get(k)
        if isinstance(x,dict):
            o=(x.get("orders") or [])
            print(" ",k,"on",x.get("on"),x.get("version",""),"orders",len(o),"newest",(o[0].get("utc"),o[0].get("applied","")[:60],o[0].get("ok")) if o else None,"last",str((x.get("last") or {}).get("note"))[:90])
    ls=d.get("listener")
    if ls: print("  listener age",ls.get("age_sec"))

# 11-03：補 …69 三本成交簿最新平倉（933／934／935），避免漏報
import subprocess as _sp, datetime as _dt
for _nm in ("studentlive", "g7live", "combolive"):
    try:
        _st = json.loads(_sp.run(["python3", "scripts/gcp_agent.py", "cat", "--object", f"xau/sig/{_nm}/state.json"], capture_output=True, text=True, cwd="/home/user/20260918").stdout)
        _ac = json.loads(_sp.run(["python3", "scripts/gcp_agent.py", "cat", "--object", f"xau/sig/{_nm}/account.json"], capture_output=True, text=True, cwd="/home/user/20260918").stdout)
        _b = _st.get("book") or []
        _x = _b[-1] if _b else None
        _f = lambda t: _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime("%m-%d %H:%M")
        print(f"  [{_nm}] 持倉 {len(_ac.get('positions') or [])} 張；成交簿 {len(_b)} 張；最新平倉",
              (f"{_f(_x['closed_ts'])} {_x.get('ch')} {_x['side']:+d} {_x['lots']} R {_x['r']:+.2f} HKD {_x['pnl_hkd']:+.2f}" if _x else "—"))
    except Exception as _e:
        print(f"  [{_nm}] 讀唔到：{_e}")

# 11-03 R369：926 921 反向（zhuge-xau reverse_live；部署前冇呢欄）
try:
    _u = _sp.run(["python3", "scripts/gcp_agent.py", "--profile", "xau", "status"], capture_output=True, text=True, cwd="/home/user/20260918").stdout
    import re as _re
    _url = _re.search(r"https://\S+run\.app", _u).group(0)
    _rv = json.loads(urllib.request.urlopen(_url + "/?format=json", timeout=30).read()).get("reverse_live")
    if _rv is None:
        print("  [reverse 926] 未部署（status 冇 reverse_live）")
    else:
        _a = _rv.get("account") or {}
        print(f"  [reverse 926] on {_rv.get('on')} 心跳 {_a.get('received_utc')} 持倉 {len(_a.get('positions') or [])} 今日 {_a.get('daily_pnl')} "
              f"pending {len(_rv.get('pending') or [])} 最新事件 {(_rv.get('events') or [{}])[0].get('kind')} {(_rv.get('events') or [{}])[0].get('note')} "
              f"成交簿 {len(_rv.get('book') or [])}")
        _bk = [x for x in (_rv.get("book") or []) if x.get("r") is not None][::-1]     # status 係新→舊
        if _bk:
            _rs = [x["r"] for x in _bk]; _w = sum(r for r in _rs if r > 0); _l = -sum(r for r in _rs if r < 0)
            _st = 0
            for r in _rs: _st = _st + 1 if r < 0 else 0
            _pf = _w / _l if _l else None
            _al = []
            if sum(_rs) <= -5: _al.append("累計 ≤ −5R")
            if _st >= 6: _al.append("連蝕 ≥ 6")
            if len(_rs) >= 15 and (_pf or 0) < 0.8: _al.append("滿 15 張 PF < 0.8")
            print(f"  [reverse 926] 累計 {len(_rs)} 張 ΣR {sum(_rs):+.2f} PF {(_pf if _pf is not None else float('nan')):.2f} 連蝕 {_st}；" + ("⚠ 觸發停條件：" + "、".join(_al) if _al else "未觸發停條件"))
        for _o in (_rv.get("orders") or [])[:3]:
            print(f"  [reverse 926] 單 {_o.get('utc')} {_o.get('kind')} side {_o.get('side')} lots {_o.get('lots')} sl {_o.get('sl')} tp {_o.get('tp')} risk {(_o.get('risk') or {}).get('risk_pct')}% ok {_o.get('ok')} {_o.get('message')}")
except Exception as _e:
    print(f"  [reverse 926] 讀唔到：{_e}")

# 11-09 新三：趨勢簿（…63，926 圖，zhuge-xau trend_live）；11-10 加 …69 933 圖 #1114 月初突破（zhuge-xau-sig trend_live）
# 停條件（IDEAS #1114 預先登記）：累計 ≤ −5R，或 ≥ 12 張後 PF < 0.8，或連蝕 6 張 → 即報總指揮（返影子要使用者批）
for _tag, _url in (("trend 926", "https://zhuge-xau-1056099871997.europe-west1.run.app/?format=json"),
                   ("trend 933 #1114", "https://zhuge-xau-sig-1056099871997.europe-west1.run.app/?format=json")):
    try:
        _tl = json.loads(urllib.request.urlopen(_url, timeout=30).read()).get("trend_live")
        if _tl is None:
            print(f"  [{_tag}] 未部署（status 冇 trend_live）")
            continue
        _a = _tl.get("account") or {}
        _ps = _a.get("positions") or []
        print(f"  [{_tag}] on {_tl.get('on')} magic {_tl.get('magic')} rules {','.join(_tl.get('rules') or [])} used {_tl.get('used')} 心跳 {_a.get('received_utc')} "
              f"持倉 {len(_ps)} 張 pending {len(_tl.get('pending') or [])} 成交簿 {len(_tl.get('book') or [])} 張 last {str((_tl.get('last') or {}).get('note'))[:60]}")
        _lv = (_tl.get("levels") or {}).get("mobrk")
        if _lv:
            print(f"  [{_tag}] {_lv.get('month')} 頭 3 日區間 {_lv.get('lo')}–{_lv.get('hi')} {'（本月已用）' if _lv.get('used') else ''}")
        for _p in _ps:
            _sd = _p.get("side")
            _px = (_tl.get("last") or {}).get("price")
            _rk = abs((_p.get("stop") or 0) - (_p.get("entry") or 0))
            _fr = ((_px - _p["entry"]) * _sd / _rk) if (_px and _rk and _p.get("entry")) else None
            print(f"  [{_tag}] 倉 {'SELL' if _sd == -1 else 'BUY'} {_p.get('lots')} @{_p.get('entry')} SL {_p.get('stop')} TP {_p.get('target')} "
                  f"浮動 {(f'{_fr:+.2f}R' if _fr is not None else '—')}")
            if _p.get("lots") != 0.01 or not _p.get("stop"):
                print(f"  ⚠ [{_tag}] 手數唔係 0.01 或者冇 SL → 即報總指揮")
        if len(_ps) > 1:
            print(f"  ⚠ [{_tag}] 多過 1 張 → 即報總指揮")
        _p0 = _tl.get("pos") or {}
        if _ps and not _p0:
            print(f"  ⚠ [{_tag}] EA 有倉但服務 state 冇 pos（state 可能被清／到期唔會自動平）→ 即報總指揮")
        if _p0 and _ps and abs((_ps[0].get("stop") or 0) - (_p0.get("sl") or 0)) > 0.01:
            print(f"  ⚠ [{_tag}] EA SL {_ps[0].get('stop')} 同服務記錄 {_p0.get('sl')} 唔一致")
        if "mobrk" in (_tl.get("rules") or []):
            _rs = [x["r"] for x in reversed(_tl.get("book") or []) if x.get("r") is not None]
            _w = sum(r for r in _rs if r > 0); _l = -sum(r for r in _rs if r < 0)
            _pf = (_w / _l) if _l else None
            _st = 0
            for r in reversed(_rs):
                if r >= 0:
                    break
                _st += 1
            print(f"  [{_tag}] 停條件：{len(_rs)} 張 ΣR {sum(_rs):+.2f} PF {('—' if _pf is None else f'{_pf:.2f}')} 連蝕 {_st}")
            if sum(_rs) <= -5 or (len(_rs) >= 12 and (_pf or 0) < 0.8) or _st >= 6:
                print(f"  ⛔ [{_tag}] 觸發 #1114 停條件（≤−5R／12 張 PF<0.8／連蝕 6）→ 即報總指揮，建議 XAU_TREND_LIVE=0 返影子（要使用者批）")
    except Exception as _e:
        print(f"  [{_tag}] 讀唔到：{_e}")
