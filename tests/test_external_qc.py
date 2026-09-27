"""[R96] scripts/external_qc.py 的每條判定規則，用人工構造的數據逐一驗證（不連網、不讀真分支）。"""
import csv, gzip, io, json, os, sys, tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["EXTERNAL_DIR"] = str(TMP / "external")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import external_qc as qc   # noqa: E402

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name} {extra}")


def gz(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n"); w.writeheader(); w.writerows(rows)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(buf.getvalue())


def web_csv(rows):
    return "Date,Open,High,Low,Close,Volume\n" + "".join(f"{d},{o},{h},{l},{c},{v}\n" for d, o, h, l, c, v in rows)


# ---- 假的網站分支（git show / ls-tree）
WEB = {
    "data/equities/us/QQQ/prices_2026.csv": web_csv([
        ("2026-09-23", 746.97, 747.13, 738.19, 741.21, 1), ("2026-09-24", 735.29, 742.66, 734.62, 741.1, 1),
        ("2026-09-25", 742.84, 745.915, 739.64, 744.5, 30017218)]),
    "data/equities/us/AAA/prices_2026.csv": web_csv([
        ("2026-09-23", 10, 11, 9, 10.0, 1), ("2026-09-24", 10, 11, 9, 10.5, 1), ("2026-09-25", 10, 11, 9, 10.2, 1)]),
    "data/equities/hk/_HSI/prices_2026.csv": web_csv([
        ("2026-09-22", 1, 2, 0.5, 25000.0, 0), ("2026-09-23", 1, 2, 0.5, 24834.119140625, 0),
        ("2026-09-24", 1, 2, 0.5, 24761.130859375, 0), ("2026-09-25", 1, 2, 0.5, 24900.0, 0)]),
    "data/equities/hk/3328.HK/prices_2026.csv": web_csv([("2026-09-23", 8.12, 8.25, 8.12, 8.21, 1),
                                                          ("2026-09-24", 8.16, 8.3, 8.16, 8.285, 1)]),
    "data/equities/us/_second/quotes_2026-09-25.json": json.dumps(
        {"trade_date": "2026-09-25", "quotes": {"AAA": {"close": 10.5}, "QQQ": {"close": 744.5}}}),
    # 金絲雀：少了 09-23（中間缺漏）；最後只到 09-24（亞洲鳥慢一日）
    "canary/data_external/hsi_daily.csv": "Date,Open,High,Low,Close\n2026-09-22,1,2,0.5,25000.0\n"
                                          "2026-09-24,1,2,0.5,24761.13\n",
}
LS = {"data/equities/us/": ["QQQ", "AAA", "_GSPC", "_second"], "data/equities/hk/": ["_HSI", "3328.HK"],
      "data/equities/us/_second/": ["quotes_2026-09-25.json"]}
qc.git_show = lambda ref, path: WEB.get(path)
qc.git_ls = lambda ref, path: LS.get(path, [])

print("\n=== 容差 ===")
check("完全相同 → 一致", qc.tol_ok(744.5, 744.5))
check("Yahoo float32 尾數 → 一致", qc.tol_ok(24761.13, 24761.130859375))
check("低價股差一跳 0.001 → 不一致", not qc.tol_ok(0.466, 0.465))
check("差一分錢 → 不一致", not qc.tol_ok(65.26, 65.25))

print("\n=== Futu 5 分 K 合成日線 ===")
ext = Path(os.environ["EXTERNAL_DIR"])
full = [{"time_key": "2026-09-25 09:35:00", "open": 742.83, "high": 745.915, "low": 739.64, "close": 743.0, "volume": 10}]
for i in range(1, 77):
    t = 9 * 60 + 35 + 5 * i
    full.append({"time_key": f"2026-09-25 {t // 60:02d}:{t % 60:02d}:00", "open": 743, "high": 744, "low": 742, "close": 743, "volume": 10})
full.append({"time_key": "2026-09-25 16:00:00", "open": 744, "high": 744.6, "low": 744, "close": 744.5, "volume": 10})
gz(ext / "futu/US.QQQ/K_5M/2026/2026-09-25.csv.gz", full, ["time_key", "open", "high", "low", "close", "volume"])
part = [{"time_key": "2026-09-24 15:55:00", "open": 740, "high": 741, "low": 739, "close": 740.5, "volume": 1},
        {"time_key": "2026-09-24 16:00:00", "open": 740.5, "high": 741.2, "low": 740, "close": 741.1, "volume": 1}]
gz(ext / "futu/US.QQQ/K_5M/2026/2026-09-24.csv.gz", part, ["time_key", "open", "high", "low", "close", "volume"])
rep = qc.Report({}); web = qc.WebDaily("x")
qc.futu_intraday_daily(web, rep)
got = {(r["date"], r["field"]): r["verdict"] for r in rep.rows}
check("完整時段：收盤一致", got.get(("2026-09-25", "close")) == qc.OK, got)
check("完整時段：最高最低一致", got.get(("2026-09-25", "high")) == qc.OK and got.get(("2026-09-25", "low")) == qc.OK, got)
check("完整時段：開盤只記錄", got.get(("2026-09-25", "open")) == qc.INFO, got)
check("不完整時段：只比收盤", got.get(("2026-09-24", "close")) == qc.OK and ("2026-09-24", "high") not in got, got)
check("不完整時段：其他欄位標略過", got.get(("2026-09-24", "open/high/low/volume")) == qc.SKIP, got)

print("\n=== 日期錯位：值等於對方前一交易日 ===")
rep = qc.Report({})
qc.web_vs_web(qc.WebDaily("x"), rep, __import__("random").Random(1))
aaa = [r for r in rep.rows if r["instrument"] == "AAA"][0]
check("AAA 標 09-25 的 10.5 = Yahoo 09-24 → ❌", aaa["verdict"] == qc.FAIL, aaa)
check("說明寫出日期錯位與哪一天", "日期錯位" in aaa["note"] and "2026-09-24" in aaa["note"], aaa["note"])
q = [r for r in rep.rows if r["instrument"] == "QQQ"][0]
check("QQQ 同日相同 → 一致", q["verdict"] == qc.OK, q)

print("\n=== 金絲雀輸入：日期缺漏與慢一日 ===")
rep = qc.Report({})
qc.canary_vs_web(qc.WebDaily("x"), rep)
by = {(r["date"], r["field"]): r for r in rep.rows}
check("中間少了 09-23 → ❌ 日期缺漏", by[("2026-09-23", "date")]["verdict"] == qc.FAIL, by.get(("2026-09-23", "date")))
check("最後一天 09-25 還沒到 → 略過（亞洲鳥慢一日）", by[("2026-09-25", "date")]["verdict"] == qc.SKIP)
check("09-24 收盤（float32 尾數）→ 一致", by[("2026-09-24", "close")]["verdict"] == qc.OK)

print("\n=== 已知原因登記 ===")
rep = qc.Report({("AAA", "*", "close"): "Nasdaq 快照錯位（測試）"})
qc.web_vs_web(qc.WebDaily("x"), rep, __import__("random").Random(1))
aaa = [r for r in rep.rows if r["instrument"] == "AAA"][0]
check("登記後 ❌ → ⚠️", aaa["verdict"] == qc.KNOWN and "已知" in aaa["note"], aaa)

print("\n=== 第三來源投票 ===")
rows = []
rep = qc.Report({}); rep.rows = rows
rep.add("ibkr_vs_web", "股票收市", "3328.HK", "2026-09-24", "open", "ibkr", 8.21, "web_yahoo", 8.16)
rep.add("futu_vs_web", "日線抽樣", "HK.03328", "2026-09-24", "open", "futu_kday", 8.16, "web_yahoo", 8.16)
rep.add("web_vs_web", "x", "3328.HK", "2026-09-24", "open", "web_nasdaq", 8.30, "web_yahoo", 8.16,
        neighbours={"前一交易日 2026-09-23": 8.30})
qc.add_votes(rows)
check("爭議列附上 Futu 的值", "futu 8.16" in rows[0]["note"], rows[0]["note"])
check("已錯位的來源不投票", "web_nasdaq" not in rows[0]["note"], rows[0]["note"])

print("\n=== 閘門 ===")
g = qc.gates([{"family": f, "verdict": v, "check": "x"} for f, v in (
    ("futu_vs_web", qc.OK), ("ibkr_vs_web", qc.OK), ("ibkr_vs_web", qc.FAIL), ("web_vs_web", qc.SKIP),
    ("canary_inputs", qc.KNOWN), ("canary_inputs", qc.OK))])
check("只有一致 → PASS", g["futu_vs_web"]["status"] == "PASS")
check("有一筆未解釋 → FAIL", g["ibkr_vs_web"]["status"] == "FAIL")
check("全是略過 → NO_DATA", g["web_vs_web"]["status"] == "NO_DATA")
check("已知不擋 → PASS", g["canary_inputs"]["status"] == "PASS")
g2 = qc.gates([{"family": "canary_inputs", "verdict": qc.OK, "check": "hsi_daily.csv（同源 Yahoo：只驗抄錄與日期）"}])
check("只有同源一致 → SAME_SOURCE_ONLY", g2["canary_inputs"]["status"] == "SAME_SOURCE_ONLY", g2["canary_inputs"])

print("\n=== 明天的 Futu 抽樣清單 ===")
qc.QC.mkdir(parents=True, exist_ok=True)
codes = qc.write_sample(__import__("random").Random(1), "2026-09-27", rows)
check("錨點在最前面", codes[:3] == qc.FUTU_ANCHORS, codes[:5])
check("今天的爭議代號排進去", "HK.03328" in codes, codes)
check("代號格式轉換正確", qc.web_to_futu("us", "BRK-B") == "US.BRK.B" and qc.futu_to_web("HK.00700") == ("hk", "0700.HK"))

print("\n=== IBKR 每日抽樣（SOP 附錄 B）===")
WEB["canary/data_external/vix_daily.csv"] = "Date,Open,High,Low,Close\n2026-09-25,15.609999656677246,15.9399995803833,14.680000305175781,14.859999656677246\n"
WEB["canary/data_external/spx_daily.csv"] = "Date,Open,High,Low,Close\n2026-09-25,7709.86,7752.07,7693.08,7743.41\n"
qc.canary_file.__defaults__[0].clear()
rep = qc.Report({})
qc.ibkr_daily(qc.WebDaily("x"), rep)
check("還沒有檔 → 略過並指向附錄 B", rep.rows and rep.rows[0]["verdict"] == qc.SKIP and "附錄 B" in rep.rows[0]["note"])
ib = ext / "ibkr/daily_sample/ib_daily_sample.csv"; ib.parent.mkdir(parents=True, exist_ok=True)
ib.write_text("date,sec_type,symbol,exchange,currency,open,high,low,close,volume,fetched_utc\n"
              "2026-09-25,IND,VIX,CBOE,USD,15.61,15.94,14.68,14.86,,2026-09-26 01:00:00\n"
              "2026-09-25,IND,SPX,CBOE,USD,7709.86,7752.07,7693.08,7744.41,,2026-09-26 01:00:00\n"
              "2026-09-25,STK,QQQ,SMART,USD,742.84,745.915,739.64,744.5,30017218,2026-09-26 01:00:00\n"
              "2026-09-24,STK,3328,SEHK,HKD,8.21,8.3,8.16,8.285,1,2026-09-26 01:00:00\n", encoding="utf-8")
rep = qc.Report({})
qc.ibkr_daily(qc.WebDaily("x"), rep)
got = {(r["family"], r["instrument"], r["field"]): r for r in rep.rows}
check("VIX 對金絲雀（float32 尾數）→ 一致", got[("canary_inputs", "VIX", "close")]["verdict"] == qc.OK)
check("SPX 收盤差 1 點 → ❌", got[("canary_inputs", "SPX", "close")]["verdict"] == qc.FAIL, got[("canary_inputs", "SPX", "close")])
check("SPX 也對網站 _GSPC（沒有這檔 → 略過）", ("ibkr_vs_web", "_GSPC", "close") in got)
check("股票 QQQ 對網站 → 一致", got[("ibkr_vs_web", "QQQ", "close")]["verdict"] == qc.OK)
check("港股 3328 開盤 8.21 對 8.16 → ❌", got[("ibkr_vs_web", "3328.HK", "open")]["verdict"] == qc.FAIL)
rep2 = qc.Report({}); qc.canary_vs_web(qc.WebDaily("x"), rep2)
check("金絲雀對網站的比對標示為同源", any("同源" in r["check"] for r in rep2.rows if r["verdict"] == qc.OK),
      {r["check"] for r in rep2.rows})

print("\n=== 請求清單 ===")
codes = qc.write_sample(__import__("random").Random(2), "2026-09-27", [])
ibl = (qc.QC / "ibkr_sample.txt").read_text(encoding="utf-8").splitlines()
check("IBKR 清單有表頭與金絲雀指數", ibl[0].startswith("sec_type,") and any(l.startswith("IND,VIX,CBOE") for l in ibl))
check("IBKR 美股代號空格格式（BRK B）", all("-" not in l.split(",")[1] for l in ibl[1:]))
check("Futu 清單美港交錯", codes[3:6] and any(c.startswith("HK.") for c in codes[3:12]), codes[:12])

print(f"\n通過 {OK} / 失敗 {FAIL}")
sys.exit(1 if FAIL else 0)
