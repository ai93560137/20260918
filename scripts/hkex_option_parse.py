"""港交所恒指期權（hsio 月期權、hsiwo 週期權）每日報告的解析與逐日下載（給 hkex_option_iv.py fetch 用）。

報告格式（看過 2026-10-02 樣本）：每個系列一行——
  <合約> <行使價> <C/P> | 前一日夜市 開 高 低 收 量 | 日市 開 高 低 O.Q.P.收 變動 IV% 量 | 合約高 合約低 量 未平倉 OI變動
  月期權合約寫 OCT-26，週期權寫 02-OCT-26（到期日）。O.Q.P. = 官方結算價（日市 16:30）。
輸出（只進 git 的是解析後、壓縮過的檔）：
  data/hkex_options/series/<產品>_<年>.csv.gz   每日、每個到期、遠期價 ±12% 內的系列（夠算價平、偏斜、鐵鷹）
  data/hkex_options/atm_iv.csv                   每日、每個到期一行：遠期價（買賣權平價）、價平行使價、C／P 結算價、跨式、IV、量、未平倉
  data/hkex_options/index.csv                    每日每產品的下載狀態（ok／none＝假期或沒報告／error），重跑時略過已完成的
遠期價：取 |C−P| 最小的行使價 K，F = K + C − P（兩邊結算價都 > 0 才算）。
"""
import csv, gzip, io, re, sys, time
from datetime import date, timedelta
from pathlib import Path

ROW_RE = re.compile(r"^\s*(\d{2}-[A-Z]{3}-\d{2}|[A-Z]{3}-\d{2})\s+(\d+)\s+([CP])\s+(.*)$")
NUM_RE = re.compile(r"^[+-]?\d+$")
FIELDS = ("aht_open", "aht_high", "aht_low", "aht_close", "aht_vol", "open", "high", "low", "oqp", "oqp_chg", "iv",
          "vol", "c_high", "c_low", "c_vol", "oi", "oi_chg")
SERIES_COLS = ("date", "product", "expiry", "strike", "cp", "oqp", "oqp_chg", "iv", "vol", "oi", "oi_chg", "open", "high", "low",
               "aht_close", "aht_vol")
ATM_COLS = ("date", "product", "expiry", "forward", "atm_strike", "call_oqp", "put_oqp", "straddle", "iv_call", "iv_put",
            "n_series", "vol_total", "oi_total")
BAND = 0.12
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def expiry_key(label):
    """'02-OCT-26' → '2026-10-02'；'OCT-26' → '2026-10'（月期權到期日由分析端算）。"""
    parts = label.split("-")
    if len(parts) == 3:
        return f"20{parts[2]}-{MONTHS[parts[1]]:02d}-{int(parts[0]):02d}"
    return f"20{parts[1]}-{MONTHS[parts[0]]:02d}"


def parse(text, day, product):
    """回傳 (系列列清單, 價平摘要清單, 跳過的行數)。"""
    rows, skipped = [], 0
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        toks = m.group(4).replace("|", " ").split()
        if len(toks) != len(FIELDS) or not all(NUM_RE.match(t) for t in toks):
            skipped += 1
            continue
        v = dict(zip(FIELDS, (int(t) for t in toks)))
        rows.append({"date": day, "product": product, "expiry": expiry_key(m.group(1)), "strike": int(m.group(2)),
                     "cp": m.group(3), **v})
    by_exp = {}
    for r in rows:
        by_exp.setdefault(r["expiry"], {}).setdefault(r["strike"], {})[r["cp"]] = r
    keep, atm = [], []
    for exp, strikes in sorted(by_exp.items()):
        pairs = [(k, d["C"], d["P"]) for k, d in strikes.items() if "C" in d and "P" in d and d["C"]["oqp"] > 0 and d["P"]["oqp"] > 0]
        if not pairs:
            continue
        k0, c0, p0 = min(pairs, key=lambda x: abs(x[1]["oqp"] - x[2]["oqp"]))
        fwd = k0 + c0["oqp"] - p0["oqp"]
        allrows = [r for d in strikes.values() for r in d.values()]
        atm.append({"date": day, "product": product, "expiry": exp, "forward": fwd, "atm_strike": k0, "call_oqp": c0["oqp"],
                    "put_oqp": p0["oqp"], "straddle": c0["oqp"] + p0["oqp"], "iv_call": c0["iv"], "iv_put": p0["iv"],
                    "n_series": len(allrows), "vol_total": sum(r["vol"] + r["aht_vol"] for r in allrows),
                    "oi_total": sum(r["oi"] for r in allrows)})
        keep += [r for r in allrows if abs(r["strike"] - fwd) <= BAND * fwd]
    return keep, atm, skipped


def _read_csv(path, gz=False):
    if not path.exists():
        return []
    opener = (lambda p: io.TextIOWrapper(gzip.open(p, "rb"), encoding="utf-8")) if gz else (lambda p: open(p, encoding="utf-8"))
    with opener(path) as fh:
        return list(csv.DictReader(fh))


def _write_csv(path, rows, cols, gz=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    if gz:
        with gzip.open(path, "wb", compresslevel=9) as fh:
            fh.write(data)
    else:
        path.write_bytes(data)


def fetch(start, end, products, out, get, to_text, base="https://www.hkex.com.hk/eng/stat/dmstat/dayrpt/", pause=0.4):
    out = Path(out)
    idx_path = out / "index.csv"
    index = {(r["date"], r["product"]): r for r in _read_csv(idx_path)}
    atm_path = out / "atm_iv.csv"
    atm_all = {(r["date"], r["product"], r["expiry"]): r for r in _read_csv(atm_path)}
    series_cache = {}

    def series_file(product, year):
        return out / "series" / f"{product}_{year}.csv.gz"

    def series_rows(product, year):
        key = (product, year)
        if key not in series_cache:
            series_cache[key] = {(r["date"], r["expiry"], r["strike"], r["cp"]): r for r in _read_csv(series_file(product, year), gz=True)}
        return series_cache[key]

    d, last = date.fromisoformat(start), date.fromisoformat(end)
    n_ok = n_none = n_err = n_skip = 0
    while d <= last:
        if d.weekday() < 5:
            day = d.isoformat()
            for p in products:
                st = index.get((day, p), {}).get("status")
                if st in ("ok", "none"):
                    n_skip += 1
                    continue
                code, raw = get(f"{base}{p}{d.strftime('%y%m%d')}.htm")
                if code == 404 or (code == 200 and len(raw) < 500):
                    index[(day, p)] = {"date": day, "product": p, "status": "none", "rows": 0, "skipped": 0}
                    n_none += 1
                elif code != 200:
                    index[(day, p)] = {"date": day, "product": p, "status": f"error:{code}", "rows": 0, "skipped": 0}
                    n_err += 1
                    print(f"⚠️ {day} {p}: HTTP {code}", flush=True)
                else:
                    keep, atm, skipped = parse(to_text(raw), day, p)
                    if not atm:
                        index[(day, p)] = {"date": day, "product": p, "status": "error:parse", "rows": 0, "skipped": skipped}
                        n_err += 1
                        print(f"⚠️ {day} {p}: 解析不到任何系列（{len(raw)} bytes）", flush=True)
                    else:
                        rows = series_rows(p, day[:4])
                        for r in keep:
                            rows[(r["date"], r["expiry"], str(r["strike"]), r["cp"])] = r
                        for a in atm:
                            atm_all[(a["date"], a["product"], a["expiry"])] = a
                        index[(day, p)] = {"date": day, "product": p, "status": "ok", "rows": len(keep), "skipped": skipped}
                        n_ok += 1
                time.sleep(pause)
        d += timedelta(days=1)
        if d.day == 1 or d > last:                                  # 每月寫一次，中途失敗也保得住
            _flush(out, idx_path, index, atm_path, atm_all, series_cache, series_file)
    print(f"完成：下載 {n_ok} 份、沒有報告 {n_none}、錯誤 {n_err}、已存在略過 {n_skip}")


def _flush(out, idx_path, index, atm_path, atm_all, series_cache, series_file):
    _write_csv(idx_path, [index[k] for k in sorted(index)], ("date", "product", "status", "rows", "skipped"))
    _write_csv(atm_path, [atm_all[k] for k in sorted(atm_all)], ATM_COLS)
    for (p, y), rows in series_cache.items():
        _write_csv(series_file(p, y), [rows[k] for k in sorted(rows, key=lambda k: (k[0], k[1], int(k[2]), k[3]))], SERIES_COLS, gz=True)


if __name__ == "__main__":                                          # 本機測試：python3 hkex_option_parse.py 樣本.txt 2026-10-02 hsio
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    keep, atm, skipped = parse(text, sys.argv[2], sys.argv[3])
    print(f"系列 {len(keep)} 列（遠期 ±{BAND:.0%}）、到期 {len(atm)} 個、跳過 {skipped} 行")
    for a in atm:
        print(a)
