"""啟動：python bot.py
停機：建立 STOP 檔案（即平倉並唔再開倉）；暫停開倉：建立 PAUSE 檔案。"""
import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler

from config import CFG
from markets import spec_for
from push import push
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

    if CFG.instance_real and CFG.trd_env != "REAL":
        # 真倉程式但產品唔喺 LONGFEI_REAL_PRODUCTS：唔好用真倉資料夾跑模擬，等 update.sh 停呢個服務
        log.error("真倉程式但 %s 唔喺 LONGFEI_REAL_PRODUCTS：唔交易，等待停機", CFG.product)
        while True:
            time.sleep(3600)
    if not CFG.instance_real and os.getenv("TRD_ENV", "").upper() == "REAL":
        log.warning("模擬程式永遠 SIMULATE（R209）：真倉由 zhuge-longfei-real@<產品> 跑，TRD_ENV=REAL 已忽略")
    sp = spec_for(CFG.product)
    size = f"每次約 US${sp.notional_usd:,.0f}（按價計股數）" if sp.kind == "stock" else f"上限={CFG.max_qty}張"
    log.info("啟動龍飛陣 AI 交易：產品=%s env=%s %s 日蝕上限=HK$%.0f 模型=%s 資料=%s",
             CFG.product, CFG.trd_env, size, CFG.daily_loss_limit, CFG.model, CFG.log_dir.parent)
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
                push(CFG, trader.state)          # 成績上載 GCS（冇設定就跳過，失敗唔影響交易）
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
