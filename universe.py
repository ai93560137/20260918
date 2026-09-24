"""指數成分股（point-in-time 宇宙）統一介面——港股/美股/日股的研究工具都經過這裡。

「市場」（數據放哪、代碼格式，見 marketdata.py）跟「指數」（誰在什麼時候是成分股、
基準用哪隻 ETF）分開：同一檔美股可以同時是 S&P 500、Nasdaq-100、道指成分股，
數據只存一份。

兩種成分股來源格式：
- snapshots：逐年快照目錄（恒指：scripts/pointintime/hsi_<year>.txt，快照日 6/30），
  最後一份快照滿一年之後改用現行名單 live 檔（paper_trade.py 每天更新）
- intervals：universes/<index>/membership.csv（ticker,start,end；end 空白 = 至今），
  精確到日（S&P 500 來自 fja05680/sp500 逐日名單）

防代碼重用（港股 0013、美股 AAL 1996 年是 AMR 別家公司）：成分股的價格歷史必須
在「入選日」之前就已存在（容許 GRACE_DAYS），否則那份價格屬於後來拿到代碼的公司。
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GRACE_DAYS = 7

INDICES = {
    "hsi": {"market": "hk", "name": "恒生指數", "benchmark": "2800.HK", "kind": "snapshots",
            "dir": "scripts/pointintime", "pattern": "hsi_*.txt", "live": "scripts/universe_hsi_live.txt",
            "official_sectors": "scripts/pointintime/hsi_sectors.json",
            "names": "data/equities/hk/_names.json", "style_k": 10},
    "sp500": {"market": "us", "name": "S&P 500", "benchmark": "SPY", "kind": "intervals",
              "file": "universes/sp500/membership.csv", "names": "data/equities/us/_names.json", "style_k": 50},
    "ndx": {"market": "us", "name": "Nasdaq-100", "benchmark": "QQQ", "kind": "intervals",
            "file": "universes/ndx/membership.csv", "names": "data/equities/us/_names.json", "style_k": 10},
    "djia": {"market": "us", "name": "道瓊工業平均", "benchmark": "DIA", "kind": "intervals",
             "file": "universes/djia/membership.csv", "names": "data/equities/us/_names.json", "style_k": 5},
    "n225": {"market": "jp", "name": "日經225", "benchmark": "1321.T", "kind": "intervals",
             "file": "universes/n225/membership.csv", "names": "data/equities/jp/_names.json", "style_k": 25},
}


class Universe:
    def __init__(self, index: str):
        if index not in INDICES:
            raise SystemExit(f"未知指數 {index}，可選：{', '.join(INDICES)}")
        self.key = index
        self.cfg = INDICES[index]
        self.benchmark = self.cfg["benchmark"]
        self.snapshots: list[tuple[date, set[str]]] = []
        self.intervals: list[tuple[str, date, date | None]] = []
        self.live: set[str] = set()
        self.blocked: list[tuple[str, date, date | None]] = []   # 代碼重用黑名單擋掉的區間（當洞處理）
        if self.cfg["kind"] == "snapshots":
            for p in sorted((ROOT / self.cfg["dir"]).glob(self.cfg["pattern"])):
                y = p.stem.split("_")[-1]
                if y.isdigit():
                    self.snapshots.append((date(int(y), 6, 30), _read_list(p)))
            live = ROOT / self.cfg.get("live", "")
            if self.cfg.get("live") and live.exists():
                self.live = _read_list(live)
        else:
            renames = load_renames(self.cfg["market"])
            blocked = load_blocklist(self.cfg["market"])
            with open(ROOT / self.cfg["file"], newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    t = renames.get(r["ticker"], r["ticker"])
                    a = date.fromisoformat(r["start"])
                    b = date.fromisoformat(r["end"]) if r["end"] else None
                    if (t, a) in blocked:
                        self.blocked.append((t, a, b))
                        continue
                    self.intervals.append((t, a, b))

    def all_tickers(self, since: date | None = None) -> list[str]:
        """曾經是成分股的全部代碼（since：只要該日之後還在的）。"""
        if self.snapshots:
            s = set().union(*(m for d, m in self.snapshots if not since or d >= since - timedelta(days=366)))
            return sorted(s | self.live)
        return sorted({t for t, a, b in self.intervals if not since or b is None or b >= since})

    def listed_at(self, d: date) -> int:
        """d 當天名單上的成分股總數（含被黑名單擋掉的；算倖存者偏差洞用）。"""
        return len(self.members_at(d)) + sum(1 for _, a, b in self.blocked if a <= d and (b is None or d < b))

    def members_at(self, d: date) -> dict[str, date]:
        """d 當天的成分股 -> 入選日（給防代碼重用的價格起始檢查）。"""
        if self.snapshots:
            snap = None
            for sd, mem in self.snapshots:
                if sd <= d:
                    snap = (sd, mem)
            if snap is None:
                return {}
            sd, mem = snap
            if self.live and d >= self.snapshots[-1][0] + timedelta(days=365):
                return {t: d for t in self.live}
            return {t: sd for t in mem}
        return {t: a for t, a, b in self.intervals if a <= d and (b is None or d < b)}

    def first_date(self) -> date:
        if self.snapshots:
            return self.snapshots[0][0]
        return min(a for _, a, _ in self.intervals)

    def eligible_at(self, d: date, first_price: dict[str, date]) -> set[str]:
        """成分股且價格歷史通過防代碼重用檢查。"""
        return {t for t, entry in self.members_at(d).items()
                if t in first_price and first_price[t] <= entry + timedelta(days=GRACE_DAYS)}

    def sectors(self) -> tuple[dict[str, str], dict[str, str]]:
        """(ticker -> yfinance sector, ticker -> 來源)。手動補缺檔 universes/<market>/sectors_manual.json。"""
        sec, src = {}, {}
        manual = ROOT / "universes" / self.cfg["market"] / "sectors_manual.json"
        if self.cfg["market"] == "hk":
            manual = ROOT / "scripts" / "pointintime" / "sectors_manual.json"
        if manual.exists():
            for t, s in json.loads(manual.read_text(encoding="utf-8")).items():
                if not t.startswith("_"):
                    sec[t], src[t] = s, "manual"
        names = ROOT / self.cfg["names"]
        if names.exists():
            for t, rec in json.loads(names.read_text(encoding="utf-8")).items():
                if rec.get("sector"):
                    sec[t], src[t] = rec["sector"], "yf"
        return sec, src

    def official_sectors(self) -> dict[str, dict[str, str]]:
        """指數公司自己的分類（當年快照）；只有恒指有。{ticker: {year: sector}}"""
        p = self.cfg.get("official_sectors")
        return json.loads((ROOT / p).read_text(encoding="utf-8")) if p else {}


def load_renames(market: str) -> dict[str, str]:
    """universes/<market>/renames.csv（old,new,note）：改代碼的公司，Yahoo 只用新代碼保存整段
    歷史——成分股檔裡的舊代碼載入時改掛新代碼。對應錯了也不會混進別家價格：新代碼的價格
    仍要通過防代碼重用檢查（起點不晚於入選日）。"""
    p = ROOT / "universes" / market / "renames.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {r["old"]: r["new"] for r in csv.DictReader(f)}


def load_blocklist(market: str) -> set[tuple[str, date]]:
    """universes/<market>/reuse_blocklist.csv（ticker,start,end,reason）：Yahoo 上同代碼的價格其實是
    後來拿到代碼的別家公司、而且那家歷史更長（防代碼重用的起點檢查擋不住），人工查證後列入。
    以（代碼、入選日）比對，套在改代碼對照之後。"""
    p = ROOT / "universes" / market / "reuse_blocklist.csv"
    if not p.exists():
        return set()
    with open(p, newline="", encoding="utf-8") as f:
        return {(r["ticker"], date.fromisoformat(r["start"])) for r in csv.DictReader(f)}


def _read_list(p: Path) -> set[str]:
    return {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
