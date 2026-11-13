"""[IDEAS #2041] 恒指月頭 3 日優勢喺邊段時間：隔夜（夜市＋朝早跳空）定日市？（#2040 跟進；數據：恒指期貨主連 1 分鐘，2018-11 起）

#2040：恒指期貨月頭 3 個交易日收市對收市每日多 +26bp（t 2.65），第 1 日最強；但 #2035 M2（只計日市開至收）冇優勢。
猜想：優勢大部分喺隔夜。文獻：美股股票溢價幾乎全部喺隔夜賺（Bondarenko & Muravyev／Boyarchenko 等，CEPR DP14462）；
Cliff, Cooper & Gulen 2008 有按月內日子拆隔夜／日間，但搵唔到專講月頭效應拆段嘅結果。
每個交易日 D 拆做（全部用期貨價）：
  night ：D−1 日市收市（16:30）之後嗰個夜市（17:15→03:00）開至收
  gap   ：夜市收市（03:00）→ D 日市開市（09:15）嘅跳空（冇夜市就由 D−1 日市收市計）
  day   ：D 日市開市 → 收市（09:15→16:30）
  total ：D−1 日市收市 → D 日市收市
窗口＝每月頭 3 個交易日；比較窗口日同其他日每段嘅平均報酬（Welch t）。

預先登記（11-13，跑之前寫，唔再改）——呢個係拆解，唔係策略判決：
  某一段算「解釋到月頭優勢」＝ 窗口日平均 − 其他日平均 > 0、t ≥ 2.0，而且 2019–2026 八年入面 ≥ 5 年窗口日合計為正。
  冇任何一段過 → 記「分散喺各段，冇得用時段做文章」。有 → 只更新前向觀察嘅記錄方法（例如只記隔夜段），真倉唔改；要落單規則另開 IDEAS 再登記。
輸出：GCS longfei/strategy_search/tom_hsi_split.json。
"""
import concurrent.futures as cf
import json
import statistics

import mhi_intraday as mi
import tom_futures as tf


def load():
    from google.cloud import storage
    cli = storage.Client()
    b = cli.bucket(tf.BUCKET)
    blobs = [x for x in cli.list_blobs(b, prefix="longfei/bars/HSI/") if x.name.endswith(".json")]

    def get(bl):
        d = json.loads(bl.download_as_text())
        return d["date"], [(r[0], r[1], r[2], r[3], r[4], r[5] if len(r) > 5 else 0.0) for r in d["bars"]]

    with cf.ThreadPoolExecutor(32) as ex:
        return dict(ex.map(get, blobs)), b


def main():
    days, b = load()
    S = mi.sessions(days)
    ds = [d for d in sorted(S) if len(S[d]["day"]) >= 100]
    fl = tf.flags(ds)
    rows = []
    for i in range(1, len(ds)):
        d, p = ds[i], ds[i - 1]
        pc = S[p]["day"][-1][4]
        o, c = S[d]["day"][0][1], S[d]["day"][-1][4]
        ng = S[p]["night"]
        if len(ng) >= 60:
            night = ng[-1][4] / ng[0][1] - 1
            gap = o / ng[-1][4] - 1
        else:
            night, gap = 0.0, o / pc - 1
        rows.append({"d": d, "win": fl[d][0] < 3, "first": fl[d][0], "night": night, "gap": gap, "day": c / o - 1, "total": c / pc - 1})
    out = {"from": ds[0], "to": ds[-1], "days": len(rows), "segments": {}}
    for seg in ("night", "gap", "day", "total"):
        w = [r[seg] for r in rows if r["win"]]
        o = [r[seg] for r in rows if not r["win"]]
        diff, t = tf.welch(w, o)
        yrs = {}
        for r in rows:
            if r["win"] and "2019" <= r["d"][:4] <= "2026":
                yrs[r["d"][:4]] = yrs.get(r["d"][:4], 0.0) + r[seg]
        pos = sum(1 for v in yrs.values() if v > 0)
        byfirst = {k: round(statistics.mean([r[seg] for r in rows if r["first"] == k]) * 1e4, 1) for k in (0, 1, 2)}
        q = bool(diff > 0 and t >= 2.0 and pos >= 5)
        out["segments"][seg] = {"win_bp": round(statistics.mean(w) * 1e4, 1), "other_bp": round(statistics.mean(o) * 1e4, 1),
                                "diff_bp": round(diff * 1e4, 1), "t": round(t, 2), "years_pos": pos,
                                "by_year_pct": {y: round(v * 100, 2) for y, v in sorted(yrs.items())},
                                "by_first_day_bp": byfirst, "explains": q}
        print(seg, out["segments"][seg])
    b.blob("longfei/strategy_search/tom_hsi_split.json").upload_from_string(json.dumps(out, ensure_ascii=False), content_type="application/json")


if __name__ == "__main__":
    main()
