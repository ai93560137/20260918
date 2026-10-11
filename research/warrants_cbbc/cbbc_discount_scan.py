"""恒指牛熊證「折讓 ＋ 期指對沖」掃描器原型（見 MISPRICING_RESEARCH.md 第三節 E 類）。

    python3 research/warrants_cbbc/cbbc_discount_scan.py --demo          # 離線：自我檢查 ＋ 假想掃描
    python3 research/warrants_cbbc/cbbc_discount_scan.py --live          # 在裝有 Futu OpenD 的電腦上跑（127.0.0.1:11111）
    python3 research/warrants_cbbc/cbbc_discount_scan.py --live --owner HK.00700   # 股票牛熊證：內在值用正股價，對沖＝借股沽空

恒指產品 F＝期指價（含持有成本）；股票產品 F＝正股價，另加 --borrow（年化借貨費率）把沽空成本算進淨利。

定義（以指數點計，R＝換股比率）：
    牛證內在值 = F − K，熊證內在值 = K − F
    折讓 D     = 內在值 − 市價 × R          （D > 0 ＝ 市價低於內在值）
對沖：買牛證 ＋ 沽期指（熊證反向）。沒被收回 → 賺 D；被收回 → D − (期指平倉價與觀察期極值之差)。
最大虧損 = 緩衝區 |收回價 − 行使價| − D。這不是無風險套利，是賣「敲出後區間」保險。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

TICK = [(0.25, 0.001), (0.50, 0.005), (10.0, 0.010), (20.0, 0.020), (100.0, 0.050)]


def tick_size(price: float) -> float:
    for upper, tick in TICK:
        if price < upper:
            return tick
    return 0.10


@dataclass
class Cbbc:
    code: str
    issuer: str
    bull: bool
    strike: float        # K
    call_level: float    # 收回價 C
    ratio: float         # R
    ask: float           # 我們買入用賣方價
    street_ratio: float  # 街貨比例 0–1
    days_left: int
    fin_rate: float = 0.04  # 年化財務費用率（估）
    maturity: str = ""      # YYYY-MM-DD（給同到期期指比價用）


def implied_forward(c: Cbbc) -> float:
    """牛證 F_bull = K + 賣價×R；熊證 F_bear = K − 賣價×R（市價隱含的遠期指數）。"""
    return c.strike + c.ask * c.ratio if c.bull else c.strike - c.ask * c.ratio


def futures_at(curve: dict, maturity: str) -> float | None:
    """curve = {"YYYY-MM-DD"(合約到期日): 價}；在牛熊證到期日線性內插，超出最遠合約 → None。"""
    import datetime as dt
    if not curve or not maturity:
        return None
    pts = sorted((dt.date.fromisoformat(k).toordinal(), v) for k, v in curve.items())
    t = dt.date.fromisoformat(maturity[:10]).toordinal()
    if t <= pts[0][0]:
        return pts[0][1] if t >= pts[0][0] - 40 else None
    if t > pts[-1][0]:
        return None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= t <= x1:
            return y0 + (y1 - y0) * (t - x0) / (x1 - x0)
    return None


def intrinsic_pts(c: Cbbc, fut: float) -> float:
    return (fut - c.strike) if c.bull else (c.strike - fut)


def discount_pts(c: Cbbc, fut: float) -> float:
    """折讓 D（點）。負數＝溢價。"""
    return intrinsic_pts(c, fut) - c.ask * c.ratio


def issuer_normal_premium_pts(c: Cbbc) -> float:
    """發行商正常會收的財務費用（點）＝ K × 年率 × 剩餘日／365。只作參考：以期指計的內在值已含持有成本，
    對沖到期鎖定的是折讓 D 本身，不用再扣這個數。"""
    return c.strike * c.fin_rate * c.days_left / 365.0


def distance_to_call_pct(c: Cbbc, fut: float) -> float:
    return abs(fut - c.call_level) / fut * 100.0


def hedged_pnl_pts(c: Cbbc, fut: float, knocked_out: bool, fut_exit: float | None = None,
                   obs_extreme: float | None = None) -> float:
    """對沖組合每份損益（點）。knocked_out=False → 持有到期。
    knocked_out=True：fut_exit＝收回後期指平倉價，obs_extreme＝觀察期內最低位（牛）／最高位（熊）。"""
    d = discount_pts(c, fut)
    if not knocked_out:
        return d  # 兩邊都以 EAS 結算、到期日相同時，期指與牛熊證內在值互相抵銷，剩折讓
    assert fut_exit is not None and obs_extreme is not None
    if c.bull:
        residual = max(obs_extreme - c.strike, 0.0)
        return (fut - fut_exit) + residual - (fut - c.strike - d)
    residual = max(c.strike - obs_extreme, 0.0)
    return (fut_exit - fut) + residual - (c.strike - fut - d)


def round_trip_cost_pts(c: Cbbc, fut_spread_pts: float = 1.0, fut: float | None = None, borrow_rate: float = 0.0) -> float:
    """來回成本（點）：牛熊證一格差價 ＋ 對沖腿差價 ＋ 法定費用與佣金（約 0.1% 成交額）
    ＋（股票產品）借股沽空到期的借貨費 ＝ 正股價 × 年率 × 剩餘日／365。"""
    one_tick = tick_size(c.ask) * c.ratio
    fees = 0.001 * c.ask * c.ratio
    borrow = (fut or 0.0) * borrow_rate * c.days_left / 365.0
    return one_tick + fut_spread_pts + fees + borrow


def scan(cbbcs: list[Cbbc], fut: float, min_dist_pct: float = 3.0, min_street: float = 0.5,
         hedge_spread_pts: float = 1.0, borrow_rate: float = 0.0, curve: dict | None = None) -> list[dict]:
    rows = []
    for c in cbbcs:
        d = discount_pts(c, fut)
        net = d - round_trip_cost_pts(c, hedge_spread_pts, fut, borrow_rate)
        fm = futures_at(curve, c.maturity) if curve else None
        fwd_c = implied_forward(c)
        edge_match = None if fm is None else ((fm - fwd_c) if c.bull else (fwd_c - fm))
        rows.append({
            "maturity": c.maturity, "fwd_cbbc": fwd_c, "fut_match": fm, "edge_match": edge_match,
            "code": c.code, "issuer": c.issuer, "type": "牛" if c.bull else "熊",
            "ask": c.ask, "intrinsic": intrinsic_pts(c, fut), "discount": d,
            "net_if_held": net, "normal_prem": issuer_normal_premium_pts(c), "dist_call%": distance_to_call_pct(c, fut),
            "street%": c.street_ratio * 100, "max_loss": abs(c.call_level - c.strike) - d,
            "candidate": net > 0 and distance_to_call_pct(c, fut) >= min_dist_pct and c.street_ratio >= min_street,
        })
    rows.sort(key=lambda r: -r["net_if_held"])
    return rows


def print_rows(rows: list[dict], fut: float) -> None:
    print(f"期指 F = {fut:,.0f}")
    print(f"{'代號':<9}{'發行':<5}{'類':<3}{'賣價':>7}{'內在':>7}{'折讓':>7}{'淨利*':>7}{'正常溢價':>9}{'距收回%':>8}{'街貨%':>7}{'最大虧':>8}{'對同月期指':>10}  候選")
    for r in rows:
        em = r.get("edge_match")
        print(f"{r['code']:<9}{r['issuer']:<5}{r['type']:<3}{r['ask']:>7.3f}{r['intrinsic']:>7.0f}{r['discount']:>7.0f}"
              f"{r['net_if_held']:>7.0f}{r['normal_prem']:>9.0f}{r['dist_call%']:>8.2f}{r['street%']:>7.0f}{r['max_loss']:>8.0f}"
              f"{(f'{em:+.0f}' if em is not None else '—'):>10}  {'✔' if r['candidate'] else ''}")
    print("* 淨利＝折讓 − 來回成本（一格差價＋期指 1 點＋費用），單位：指數點／每份；持有到期且沒被收回、牛熊證到期日＝期指結算日的情況。")
    print("  到期日不同時要另扣期指轉倉／基差；以期指計的內在值已含持有成本，所以不扣財務費用（發行商正常溢價見 normal_prem 欄，只作對照）。")


def demo() -> None:
    fut = 26_000.0
    # 自我檢查：報告第三節 E 類那張表
    c = Cbbc("DEMO", "X", True, strike=25_000, call_level=25_200, ratio=10_000, ask=0.095, street_ratio=0.6, days_left=30)
    d = discount_pts(c, fut)                       # 內在 1,000 點、市價 950 點 → 折讓 50 點
    assert abs(d - 50) < 1e-9, d
    assert abs(hedged_pnl_pts(c, fut, False) - 50) < 1e-9
    assert abs(issuer_normal_premium_pts(c) - 25_000 * 0.04 * 30 / 365) < 1e-9
    # 收回：期指在 25,180 平倉，觀察期最低 25,150 ≥ K → D − (C′ − L) = 50 − 30 = 20
    assert abs(hedged_pnl_pts(c, fut, True, 25_180, 25_150) - 20) < 1e-9
    # 收回：最低跌穿行使價 → D − (C′ − K) = 50 − 180 = −130；最大虧損 = 緩衝 200 − 50 = 150
    assert abs(hedged_pnl_pts(c, fut, True, 25_180, 24_900) - (-130)) < 1e-9
    assert abs(hedged_pnl_pts(c, fut, True, 25_200, 24_000) - (-150)) < 1e-9
    bear = Cbbc("DEMOB", "X", False, strike=27_000, call_level=26_800, ratio=10_000, ask=0.098, street_ratio=0.6, days_left=30)
    assert abs(discount_pts(bear, fut) - 20) < 1e-9
    assert abs(hedged_pnl_pts(bear, fut, True, 26_820, 26_850) - (20 - 30)) < 1e-9
    print("自我檢查通過。\n")

    sample = [
        Cbbc("6xxx1", "法巴", True, 24_000, 24_200, 10_000, 0.199, 0.82, 40),   # 遠離收回、街貨重、折讓 10 點
        Cbbc("6xxx2", "摩通", True, 24_000, 24_200, 10_000, 0.201, 0.15, 40),   # 同條款、發行商報正常溢價
        Cbbc("6xxx3", "瑞銀", True, 25_000, 25_200, 10_000, 0.095, 0.55, 30),   # 報告例子：折讓 50 點
        Cbbc("6xxx4", "滙豐", True, 25_600, 25_800, 10_000, 0.030, 0.70, 20),   # 貼近收回：折讓 100 點但距收回 0.8%
        Cbbc("6xxx5", "高盛", False, 27_000, 26_800, 10_000, 0.098, 0.60, 30),  # 熊證折讓 20 點
        Cbbc("6xxx6", "花旗", True, 23_000, 23_300, 20_000, 0.146, 0.90, 60),   # 比率 20,000：折讓 80 點但一格＝20 點
    ]
    print_rows(scan(sample, fut), fut)
    print("\n讀法：6xxx4 折讓最大卻不是候選（距收回價 0.8% < 日波幅，折讓是發行商對 gap 風險的合理定價）。")
    print("6xxx3／6xxx5 是遠離收回價、折讓大過一格差價的候選；6xxx1 折讓 10 點連一格（10 點）都不夠；")
    print("6xxx6 比率 20,000 → 一格＝20 點，80 點折讓仍有淨利；6xxx2 以期指計是 10 點溢價（正常），證明 6xxx1 的折讓不是條款造成而是街貨重。")


def _warrant_request_cls(ft):
    """futu-api 10.x 把 get_warrant 的篩選物件匯出成 WarrantRequest（舊版叫 WarrantDataFilter）。"""
    cls = getattr(ft, "WarrantRequest", None) or getattr(ft, "WarrantDataFilter", None)
    if cls is None:
        from futu.quote.quote_get_warrant import Request as cls  # type: ignore
    return cls


def scan_live(host: str, port: int, owner: str = "HK.800000", min_dist_pct: float = 3.0, min_street: float = 0.5,
              borrow_rate: float = 0.01, log=print) -> tuple[list[dict], dict]:
    """連 OpenD 掃描該相關資產全部牛熊證。回傳 (rows, meta)；rows 含 discount>0 與否全部（給前向測試存檔），candidate 欄標候選。"""
    try:
        import futu as ft  # type: ignore
        ft.OpenQuoteContext
    except (ImportError, AttributeError):
        sys.exit("需要 pip install futu-api 並在本機跑 Futu OpenD；不要在 repo 根目錄用互動模式跑（repo 的 futu/ 資料夾會蓋掉套件）")
    import datetime as dt
    import time
    ctx = ft.OpenQuoteContext(host=host, port=port)
    try:
        is_index = owner == "HK.800000"
        ref_code = "HK.HSImain" if is_index else owner
        ret, snap = ctx.get_market_snapshot([ref_code])
        if ret != ft.RET_OK:
            raise RuntimeError(f"{ref_code} 快照失敗：{snap}")
        fut = float(snap.loc[0, "last_price"])
        hedge_spread = 1.0 if is_index else 0.01 * fut
        curve = _futures_curve(ft, ctx, log) if is_index else None
        cbbcs: list[Cbbc] = []
        for wtype, bull in ((ft.WrtType.BULL, True), (ft.WrtType.BEAR, False)):
            begin = 0
            while True:
                req = _warrant_request_cls(ft)()
                req.type_list = [wtype]
                req.begin, req.num = begin, 200
                req.sort_field = ft.SortField.CODE
                ret, data = ctx.get_warrant(owner, req)
                if ret != ft.RET_OK:
                    raise RuntimeError(f"get_warrant 失敗：{data}")
                df, last_page, all_count = data
                for _, r in df.iterrows():
                    ask = float(r.get("ask_price") or 0)
                    if ask <= 0 or float(r.get("recovery_price") or 0) <= 0:
                        continue
                    mat = dt.date.fromisoformat(str(r["maturity_time"])[:10])
                    cbbcs.append(Cbbc(str(r["stock"]), str(r.get("issuer", "?")), bull,
                                      float(r["strike_price"]), float(r["recovery_price"]), float(r["conversion_ratio"]),
                                      ask, float(r.get("street_rate") or 0) / 100.0, (mat - dt.date.today()).days,
                                      maturity=mat.isoformat()))
                begin += len(df)
                if last_page or len(df) == 0 or begin >= all_count:
                    break
                time.sleep(3.1)
            time.sleep(3.1)
        log(f"{owner} 牛熊證（有賣價）{len(cbbcs)} 隻，參考價 {fut:,.2f}")
        rows = scan(cbbcs, fut, min_dist_pct, min_street, hedge_spread, 0.0 if is_index else borrow_rate, curve)
        return rows, {"owner": owner, "forward": fut, "n": len(rows), "futures_curve": curve or {}}
    finally:
        ctx.close()


def _futures_curve(ft, ctx, log=print) -> dict:
    """恒指期貨各合約月的即時價 {到期日: 中間價}。先用 get_referencestock_list(HK.800000, FUTURE)，
    拿不到就猜代號 HK.HSI<yymm>（近 12 個月 ＋ 之後 6 個 12 月）。任何一步失敗都只記 log、回空 dict。"""
    import datetime as dt
    codes: list[str] = []
    try:
        ret, df = ctx.get_referencestock_list("HK.800000", ft.SecurityReferenceType.FUTURE)
        if ret == ft.RET_OK and len(df):
            codes = [str(c) for c in df["code"].tolist() if str(c).startswith("HK.HSI")]
    except Exception as exc:  # noqa: BLE001
        log(f"期指合約清單取不到（{exc}），改猜代號")
    if not codes:
        today = dt.date.today()
        months = {(today.year + (today.month - 1 + i) // 12, (today.month - 1 + i) % 12 + 1) for i in range(12)}
        months |= {(today.year + i, 12) for i in range(1, 7)}
        codes = [f"HK.HSI{y % 100:02d}{m:02d}" for y, m in sorted(months)]
    curve: dict = {}
    try:
        ret, snap = ctx.get_market_snapshot(codes[:60])
        if ret != ft.RET_OK:
            log(f"期指快照失敗：{snap}")
            return {}
        for _, r in snap.iterrows():
            code = str(r["code"])
            tail = code[-4:]
            if not tail.isdigit():
                continue
            y, m = 2000 + int(tail[:2]), int(tail[2:])
            exp = (dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=2))   # 月底倒數第二日近似
            bid, ask, last = (float(r.get(k) or 0) for k in ("bid_price", "ask_price", "last_price"))
            px = (bid + ask) / 2 if bid > 0 and ask > 0 else last
            if px > 0:
                curve[exp.isoformat()] = px
    except Exception as exc:  # noqa: BLE001
        log(f"期指曲線失敗：{exc}")
        return {}
    log(f"期指曲線 {len(curve)} 個合約月：" + ", ".join(f"{k[:7]}={v:,.0f}" for k, v in sorted(curve.items())))
    return curve


def live(host: str, port: int, min_dist_pct: float, min_street: float, owner: str, borrow_rate: float) -> None:
    rows, meta = scan_live(host, port, owner, min_dist_pct, min_street, borrow_rate)
    print_rows([r for r in rows if r["discount"] > 0][:40], meta["forward"])
    n_c = sum(1 for r in rows if r["candidate"])
    print(f"\n{len(rows)} 隻；折讓 > 0 的 {sum(1 for r in rows if r['discount'] > 0)} 隻；候選（淨利 > 0、距收回價 ≥ {min_dist_pct}%、街貨 ≥ {min_street:.0%}）{n_c} 隻")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true", help="離線自我檢查與假想掃描")
    p.add_argument("--live", action="store_true", help="連 Futu OpenD 掃描恒指牛熊證")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11111)
    p.add_argument("--min-dist", type=float, default=3.0, help="距收回價最少 %%（預設 3）")
    p.add_argument("--min-street", type=float, default=0.5, help="街貨比例下限 0–1（預設 0.5）")
    p.add_argument("--owner", default="HK.800000", help="相關資產：HK.800000＝恒指（預設），或個股如 HK.00700")
    p.add_argument("--borrow", type=float, default=0.01, help="個股借貨費年率（預設 0.01＝1%%），恒指不用")
    a = p.parse_args()
    if a.live:
        live(a.host, a.port, a.min_dist, a.min_street, a.owner, a.borrow)
    else:
        demo()


if __name__ == "__main__":
    main()
