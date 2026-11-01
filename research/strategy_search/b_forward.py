"""[IDEAS #177] 日線 B 確認影子前向（唔落單）：Keltner 20／2×ATR 收出通道＋拋物線 SAR 同方向＋收市喺 SMA200 同邊，
TP 4／SL 2 × D1 ATR20、20 日時間止蝕、下一日第一根 H1 開盤入（同 #173 d1_combo.py 一模一樣）。
數據：Dukascopy H1（2022-08 之前）＋券商 MT5 M1→H1（2022-08→2026-10-30）做指標預熱；之後用經紀 EA 心跳 M1（xau/sig/bars/）。
前向只計 2026-11-02（券商日）收市之後先出嘅訊號。輸出 B_FORWARD.md（commit＋PR 由巡檢做）。
用法：python3 research/strategy_search/b_forward.py"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "student_offline"))
import d1_combo as C  # noqa: E402
import d1_indicators as Q  # noqa: E402
import g7_long as G  # noqa: E402
import robust_long as R  # noqa: E402

START_DAY = dt.date(2026, 11, 2)          # 呢個券商日（22:00 UTC 日界）收市起出嘅訊號先計
END_DAY = dt.date(2027, 11, 1)
TARGET_N = 20
BACKTEST = "黃金 2005→2026（揀指標嗰份數據）137 張 +0.358R PF 1.92；白銀（未見）107 張 +0.167R PF 1.37；MT5 2022-10→2026-10 22 張 +0.90R"


def bday(ts):
    return dt.datetime.fromtimestamp(int(ts) + 7200, dt.timezone.utc).date()


def load_h1():
    hist = R.load_mt5_spliced(R.load_duka())
    import e6s4_forward as ef   # noqa: E402
    last = int(hist[0][-1])
    try:
        m1 = ef.broker_bars(last + 3600)
    except Exception as e:                                   # noqa: BLE001
        print("經紀 K 線讀唔到：", e)
        return hist, 0
    if not len(m1["t"]):
        return hist, 0
    t, o, h, l, c = G.h1_from_m1(m1)
    m = t > last
    return [np.r_[a, b[m]] for a, b in zip(hist, (t, o, h, l, c))], int(m.sum())


def main():
    R.COST = 0.5
    arr, n_new = load_h1()
    D = Q.DI(*arr)
    b5, x5 = Q.signals(D, "J5", C.P5)
    tu, td = D.dc > D.s200, D.dc < D.s200
    b, x = b5 & D.sar_up & tu, x5 & ~D.sar_up & td
    days = [bday(D.t[f]) for f in D.dfirst]
    sig_days = [d for d in np.flatnonzero(b | x) if days[d] >= START_DAY and d >= 210]
    ent = [(int(D.dfirst[d + 1]), 1 if b[d] else -1, C.SL * D.datr[d], C.TP * D.datr[d], C.T_H) for d in sig_days if d + 1 < len(D.dc)]
    done = R.simulate(D, ent)
    done_ts = {x[0] for x in done}
    now = dt.datetime.now(dt.timezone.utc)
    last_d = len(D.dc) - 1
    out = ["# 日線 B 確認影子前向（IDEAS #177）", "",
           f"- 更新：{now:%Y-%m-%d %H:%M} UTC；最後一根 H1：{dt.datetime.fromtimestamp(int(D.t[-1]), dt.timezone.utc):%Y-%m-%d %H:%M} UTC（經紀心跳新增 {n_new} 根）",
           f"- 規則：Keltner 20／2×ATR 收出通道＋拋物線 SAR 同方向＋收市喺 SMA200 同邊；TP 4／SL 2 × D1 ATR20；20 日；下一日開盤入；唔落單",
           f"- 前向由 {START_DAY} 收市起；到期 {TARGET_N} 張或 {END_DAY}；回測對照：{BACKTEST}", "",
           "## 最新日線狀態", "",
           f"- 收市 {D.dc[last_d]:.2f}；Keltner 上 {D.ku[last_d]:.2f}／下 {D.kl[last_d]:.2f}；SMA200 {D.s200[last_d]:.2f}；"
           f"拋物線 SAR {'向上' if D.sar_up[last_d] else '向下'}（{D.sar[last_d]:.2f}）；D1 ATR20 {D.datr[last_d]:.2f}", ""]
    out += ["## 前向成交", "", "| 訊號日 | 方向 | 入場（UTC） | 入場價 | SL | TP | 出場（UTC） | R |", "|---|---|---|---|---|---|---|---|"]
    rows_open = []
    for (a, s, sl_d, tp_d, _), d in zip(ent, sig_days):
        px = D.o[a]; sl = px - s * sl_d; tp = px + s * tp_d
        tr = next((t_ for t_ in done if t_[0] == int(D.t[a])), None)
        if tr:
            out.append(f"| {days[d]} | {'多' if s > 0 else '空'} | {dt.datetime.fromtimestamp(tr[0], dt.timezone.utc):%m-%d %H:%M} | {px:.2f} | {sl:.2f} | {tp:.2f} | "
                       f"{dt.datetime.fromtimestamp(tr[4], dt.timezone.utc):%m-%d %H:%M} | {tr[3]:+.2f} |")
        else:
            rows_open.append(f"| {days[d]} | {'多' if s > 0 else '空'} | {dt.datetime.fromtimestamp(int(D.t[a]), dt.timezone.utc):%m-%d %H:%M} | {px:.2f} | {sl:.2f} | {tp:.2f} | 持倉中 | — |")
    out += rows_open
    if not ent:
        out.append("| — | — | — | — | — | — | 未有訊號 | — |")
    rs = np.array([t_[3] for t_ in done]); s_ = R.summ(rs)
    streak = mx = 0
    for r in rs:
        streak = streak + 1 if r < 0 else 0; mx = max(mx, streak)
    warn = rs.sum() <= -5 or mx >= 6
    out += ["", "## 累計", "",
            f"- 已平倉 {len(rs)} 張；ΣR {rs.sum():+.2f}；" + (f"平均 {s_['avg']:+.3f}R PF {s_['pf']:.2f}；最長連輸 {mx}" if len(rs) else "未有平倉"),
            f"- 判：{'⚠ 觸發警示（累計 ≤ −5R 或連輸 ≥ 6）→ 報總指揮重評' if warn else ('到期，照 IDEAS #177 判' if len(rs) >= TARGET_N or now.date() >= END_DAY else f'未到期（{len(rs)}／{TARGET_N} 張）')}", ""]
    open(os.path.join(HERE, "B_FORWARD.md"), "w").write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
