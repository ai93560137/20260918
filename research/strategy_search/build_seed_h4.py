"""[IDEAS #1421] 黃金趨勢簿 H4 冷啟動種子：券商 MT5 XAUUSD_M1_MAX.csv → UTC H4 → xau/trend_h4_seed.py（最近 400 根）。
同真倉一樣唔收休市時段 K 線（星期六、星期日 21:00 UTC 前）。上線前用最新匯出重跑；種子尾同上線之間嘅缺口由服務 M1 存檔（最近 10 日）補。
用法：python3 research/strategy_search/build_seed_h4.py --csv <XAUUSD_M1_MAX.csv>"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "xau"))
import import_mt5_max as IM      # noqa: E402
import trend_h4rules as H4R      # noqa: E402


def closed(ts):                                          # 同 xau/trend_live.closed_window（黃金）
    wd = (int(ts) // 86400 + 3) % 7
    return wd == 5 or (wd == 6 and int(ts) % 86400 < 21 * 3600)


def main():
    d, _ = IM.load(sys.argv[sys.argv.index("--csv") + 1]); t0 = int(d["t"][-1]) - 120 * 86400
    rows = [{"t": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c)}
            for t, o, h, l, c in zip(d["t"], d["o"], d["h"], d["l"], d["c"]) if t >= t0 and not closed(t)]
    seed = H4R.h4_merge({}, rows, keep=H4R.KEEP); ks = sorted(seed, key=int)
    f = lambda k: dt.datetime.fromtimestamp(int(k) * H4R.H4, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    with open(os.path.join(HERE, "..", "..", "xau", "trend_h4_seed.py"), "w") as fh:
        fh.write(f'"""[IDEAS #1421] 黃金趨勢簿 H4 種子（UTC；券商 MT5 M1 砌，{f(ks[0])}→{f(ks[-1])}；只係冷啟動用）。自動產生（research/strategy_search/build_seed_h4.py），唔好手改。"""\n')
        fh.write("SEED = " + json.dumps(seed, separators=(",", ":")) + "\n")
    print(len(seed), f(ks[0]), f(ks[-1]), seed[ks[-1]])


if __name__ == "__main__":
    main()
