"""[IDEAS #2040] 月頭月尾效應喺龍飛陣自己嘅期貨數據重驗（天覆陣 #1456 轉交；使用者 11-12「1456 教龍飛」）。

天覆陣 #1456：26 個股指現貨，月尾最後 1 日＋月頭 3 日做多，窗口日每日多 +9.9bp（t 5.83）；弱點係 2010 後減半、月尾嗰日已冇優勢。
佢建議龍飛陣用自己嘅 HSI／NQ／ES 期貨數據同成交時段重驗（原版同「月頭 3 日版」各一）。
數據：
  ES、NQ：GCS longfei/daily/ES_F.json、NQ_F.json（Yahoo 連續合約日線，2000-09 起；收市對收市）。
  HSI 期貨：GCS longfei/bars/HSI/ 1 分鐘 K 砌日市收市（16:30），2018-11 起；收市對收市（包夜市）。
  參考（唔入判決）：^HSI 現貨 longfei/daily/HSI.json（1990 起）。
版本：
  V1 原版：每月最後 1 個交易日＋月頭 3 個交易日（即係揸住呢 4 日嘅日報酬）。
  V2 月頭版：只做月頭 3 個交易日（月尾最後一日收市入、月頭第 3 日收市出）。
成本：每次入場＋出場合共 2bp（ES／NQ 一格滑價有突；MHI 4 點約 1.6bp）。

預先登記（11-13，跑之前寫，唔再改）：
  ES、NQ（每個市場、每個版本分開判）：① 全樣本「窗口日平均 − 其他日平均」> 0 而 Welch t ≥ 2.0；
    ② 2015 年起差值 > 0；③ 2021 年起只喺窗口做多（扣成本）≥ 4/6 年正數；④ 另一個版本全樣本差值亦 > 0。
  HSI 期貨（樣本短，只當旁證）：2018-11 起差值 > 0、t ≥ 1.5、扣成本 ≥ 5/8 年正數。
  合格 → 只當「入場時機偏向」做影子前向（例如 12 月動量恢復時嘅入場日）；真倉改動要使用者批。冇 → 記低、#2041。
輸出：GCS longfei/strategy_search/tom_futures.json。
"""
import concurrent.futures as cf
import json
import math
import statistics

BUCKET = "zhuge-risk-manager-bucket"
COST = 0.0002


def flags(dates):
    """→ {日期: (月頭第幾日 0 起, 月尾倒數第幾日 0＝最後一日)}。未完嘅最後一個月唔俾「月尾」標記。"""
    by = {}
    for d in dates:
        by.setdefault(d[:7], []).append(d)
    months = sorted(by)
    out = {}
    for m in months:
        ds = by[m]
        for i, d in enumerate(ds):
            out[d] = (i, (len(ds) - 1 - i) if m != months[-1] else 99)
    return out


def welch(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    return (ma - mb), (ma - mb) / math.sqrt(va / len(a) + vb / len(b))


def analyse(rows, since=None):
    """rows: [(日期, 收市)]。回傳每個版本嘅統計。"""
    dates = [d for d, _ in rows]
    fl = flags(dates)
    rets = [(rows[i][0], rows[i][1] / rows[i - 1][1] - 1) for i in range(1, len(rows))]
    if since:
        rets = [x for x in rets if x[0] >= since]
    res = {}
    for name, inwin in (("V1", lambda f: f[0] < 3 or f[1] == 0), ("V2", lambda f: f[0] < 3)):
        w = [r for d, r in rets if inwin(fl[d])]
        o = [r for d, r in rets if not inwin(fl[d])]
        diff, t = welch(w, o)
        # 只喺窗口做多：每個月一次進出（V1 月尾入、V2 月尾收市入），扣 COST
        yrs = {}
        prev_in = False
        for d, r in rets:
            now_in = inwin(fl[d])
            pnl = r if now_in else 0.0
            if now_in and not prev_in:
                pnl -= COST
            yrs[d[:4]] = yrs.get(d[:4], 0.0) + pnl
            prev_in = now_in
        res[name] = {"n_win": len(w), "n_other": len(o), "win_bp": round(statistics.mean(w) * 1e4, 2),
                     "other_bp": round(statistics.mean(o) * 1e4, 2), "diff_bp": round(diff * 1e4, 2), "t": round(t, 2),
                     "by_year_pct": {y: round(v * 100, 2) for y, v in sorted(yrs.items())},
                     "share_in": round(len(w) / len(rets), 3)}
    # 逐日位置（月頭第 1–3 日、月尾最後 1–2 日）
    pos = {}
    for d, r in rets:
        f = fl[d]
        for key, ok in (("first1", f[0] == 0), ("first2", f[0] == 1), ("first3", f[0] == 2), ("last1", f[1] == 0), ("last2", f[1] == 1)):
            if ok:
                pos.setdefault(key, []).append(r)
    res["by_pos_bp"] = {k: round(statistics.mean(v) * 1e4, 1) for k, v in pos.items()}
    return res


def gcs_json(b, name):
    return json.loads(b.blob(name).download_as_text())


def hsi_futures_daily(cli, b):
    blobs = [x for x in cli.list_blobs(b, prefix="longfei/bars/HSI/") if x.name.endswith(".json")]

    def get(bl):
        d = json.loads(bl.download_as_text())
        day = [r for r in d["bars"] if "09:15" < r[0] <= "16:30"]
        return (d["date"], day[-1][4]) if len(day) >= 100 else None

    with cf.ThreadPoolExecutor(32) as ex:
        return sorted(x for x in ex.map(get, blobs) if x)


def main():
    from google.cloud import storage
    cli = storage.Client()
    b = cli.bucket(BUCKET)
    data = {n: [(r[0], r[4]) for r in gcs_json(b, f"longfei/daily/{n}.json")["rows"]] for n in ("ES_F", "NQ_F", "HSI")}
    data["HSI_FUT"] = hsi_futures_daily(cli, b)
    out = {}
    for name, rows in data.items():
        full = analyse(rows)
        s15 = analyse(rows, "2015-01-01") if name != "HSI_FUT" else None
        out[name] = {"from": rows[0][0], "to": rows[-1][0], "days": len(rows), "full": full, "since2015": s15}
        for v in ("V1", "V2"):
            f = full[v]
            yrs = {y: p for y, p in f["by_year_pct"].items() if y >= "2021"}
            pos_y = sum(1 for p in yrs.values() if p > 0)
            other = full["V2" if v == "V1" else "V1"]
            if name in ("ES_F", "NQ_F"):
                q = {"c1": bool(f["diff_bp"] > 0 and f["t"] >= 2.0), "c2": bool(s15[v]["diff_bp"] > 0),
                     "c3": bool(pos_y >= 4), "c4": bool(other["diff_bp"] > 0)}
            elif name == "HSI_FUT":
                ally = sum(1 for p in f["by_year_pct"].values() if p > 0)
                q = {"c1": bool(f["diff_bp"] > 0 and f["t"] >= 1.5), "c3": bool(ally >= 5)}
            else:
                q = {}
            f["checks"], f["qualified"] = q, bool(q) and all(q.values())
            print(name, v, "窗口", f["win_bp"], "其他", f["other_bp"], "差", f["diff_bp"], "t", f["t"],
                  "2015起差", s15[v]["diff_bp"] if s15 else None, "2021起年", yrs, q, "✅" if f["qualified"] else "")
        print(name, "逐日位置 bp", full["by_pos_bp"])
    b.blob("longfei/strategy_search/tom_futures.json").upload_from_string(json.dumps(out, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
