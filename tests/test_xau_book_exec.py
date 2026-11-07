"""[11-07] 訊號書每書獨立開關（使用者 11-07「931、932、933、934、935 全部用獨立開關」）。
真倉＝XAU_EXECUTE=1 而且該書 SIG_*_EXECUTE=1；非訊號書照舊只睇 XAU_EXECUTE。每組 env 用獨立子程序 import config／executor。"""
import json, os, subprocess, sys

XAU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xau")
PROBE = r"""
import json, config, executor
st = {"pending_cmds": [{"id": "abcd1234", "text": "open|BUY|0.01|sl=1|tp=2|magic=933|id=abcd1234", "ts": 100, "acked": False}]}
mg = {"931": config.MAGIC, "932": config.FOLLOW_MAGIC, "933": config.STUDENT_MAGIC, "934": config.G7_MAGIC, "935": config.COMBO_MAGIC}
print(json.dumps({"live": {k: config.book_live(v) for k, v in mg.items()}, "default": config.book_live(),
                  "cmd": {k: bool(executor.cmd_text(st, 110, v)) for k, v in mg.items()}, "magic": config.MAGIC}))
"""
BASE = dict(WEBHOOK_SECRET_TOKEN="tok", ANTHROPIC_API_KEY="x", GATE_MODEL="claude-haiku-5-5")
FLAGS = ("SIG_S1_EXECUTE", "SIG_FOLLOW_EXECUTE", "SIG_STUDENT_EXECUTE", "SIG_G7_EXECUTE", "SIG_COMBO_EXECUTE", "XAU_EXECUTE", "XAU_BOOK")
fails = 0


def probe(**env):
    e = {k: v for k, v in os.environ.items() if k not in FLAGS}
    e.update(BASE, **env)
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=XAU, env=e, capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def check(name, cond, extra=""):
    global fails
    print(("  ✅ " if cond else "  ❌ ") + name, "" if cond else extra)
    fails += 0 if cond else 1


ALL_OFF = {"931": False, "932": False, "933": False, "934": False, "935": False}
r = probe(XAU_BOOK="signal", XAU_EXECUTE="1")
check("訊號書 XAU_EXECUTE=1、冇書開關 → 全部書唔係真倉、cmd_text 全空", r["live"] == ALL_OFF and not any(r["cmd"].values()), r)
r = probe(XAU_BOOK="signal", XAU_EXECUTE="1", SIG_STUDENT_EXECUTE="1")
check("只開 933 → 淨係 933 真倉（931／932／934／935 照影子）", r["live"] == dict(ALL_OFF, **{"933": True}), r)
check("只開 933 → 淨係 933 嘅 cmd_text 有嘢", r["cmd"] == dict(ALL_OFF, **{"933": True}), r)
check("只開 933 → 預設（931 S1 引擎）唔係真倉", r["default"] is False, r)
r = probe(XAU_BOOK="signal", XAU_EXECUTE="0", SIG_S1_EXECUTE="1", SIG_FOLLOW_EXECUTE="1", SIG_STUDENT_EXECUTE="1", SIG_G7_EXECUTE="1", SIG_COMBO_EXECUTE="1")
check("XAU_EXECUTE=0 → 書開關全開都唔落實倉（總掣優先）", r["live"] == ALL_OFF and not any(r["cmd"].values()), r)
for flag, k in (("SIG_S1_EXECUTE", "931"), ("SIG_FOLLOW_EXECUTE", "932"), ("SIG_G7_EXECUTE", "934"), ("SIG_COMBO_EXECUTE", "935")):
    r = probe(XAU_BOOK="signal", XAU_EXECUTE="1", **{flag: "1"})
    check(f"只開 {flag} → 淨係 {k} 真倉", r["live"] == dict(ALL_OFF, **{k: True}), r)
r = probe(XAU_EXECUTE="1")
check("非訊號書（921）XAU_EXECUTE=1 → 照舊真倉（唔受書開關影響）", r["magic"] == 921 and r["default"] is True, r)
r = probe(XAU_EXECUTE="0")
check("非訊號書 XAU_EXECUTE=0 → 影子", r["default"] is False, r)

print(f"\n結果：{'全部過' if not fails else f'{fails} 失敗'}")
sys.exit(1 if fails else 0)
