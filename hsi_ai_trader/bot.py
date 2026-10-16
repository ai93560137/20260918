"""啟動：python bot.py
停機：建立 STOP 檔案（即平倉並唔再開倉）；暫停開倉：建立 PAUSE 檔案。"""
import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

from config import CFG
from rules import now_hkt


def setup_logging():
    CFG.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = RotatingFileHandler(CFG.log_dir / "bot.log", maxBytes=5_000_000, backupCount=5,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)


def main():
    setup_logging()
    log = logging.getLogger("bot")
    if not CFG.anthropic_api_key:
        log.error("未設定 ANTHROPIC_API_KEY")
        sys.exit(1)

    from broker import FutuBroker
    from brain import ClaudeBrain
    from trader import Trader

    log.info("啟動龍飛陣 AI 交易：env=%s 上限=%d張 日蝕上限=HK$%.0f 模型=%s",
             CFG.trd_env, CFG.max_qty, CFG.daily_loss_limit, CFG.model)
    broker = FutuBroker(CFG)
    trader = Trader(CFG, broker, ClaudeBrain(CFG), now_hkt)

    running = {"on": True}

    def _stop(*_):
        running["on"] = False
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    last_eq_snap = 0.0
    try:
        while running["on"]:
            trader.tick()
            if time.time() - last_eq_snap >= 300:
                trader.snapshot_equity()
                last_eq_snap = time.time()
            time.sleep(CFG.risk_loop_sec)
    finally:
        pos = trader.state.get("pos")
        if pos:
            log.warning("程式停止時仍有倉位 %s，止蝕 %s 唔會再被監控！", pos.get("code"), pos.get("stop"))
        broker.close()
        log.info("已停止")


if __name__ == "__main__":
    main()
