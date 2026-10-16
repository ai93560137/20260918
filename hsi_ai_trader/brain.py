"""Claude 決策：每 5 分鐘睇一次市，回傳結構化決定。出錯一律當 HOLD。"""
import hashlib
import json
import logging
from pathlib import Path

import anthropic

log = logging.getLogger("brain")

SYSTEM = """You are the decision engine of an automated intraday trading bot for Hang Seng Index
Mini Futures (MHI, front month, HK$10 per index point, 1-point tick) on HKFE, day and night sessions.

Every 5 minutes you receive market data, the current position and the risk budget. Decide ONE action:
- HOLD: do nothing.
- OPEN_LONG / OPEN_SHORT: open exactly 1 contract. Only allowed when flat. stop_price is REQUIRED.
- CLOSE: close the current position.
- UPDATE_STOP: move the stop (and optionally target) of the current position.

Hard rules enforced by code (you cannot override them; violating them just turns your action into HOLD):
- Max 1 contract. No pyramiding, no reversing in one step (CLOSE first, open on a later cycle).
- Stop distance is clamped to stop_points_min/max when given (null = no limit).
- If the stop risk exceeds the remaining daily loss budget the entry is rejected.
- No new entries in the last minutes of a session. Positions MAY be held overnight; an overnight gap
  is not protected by the daily loss limit, so weigh that before holding into a session close.
- Stops and targets are checked by code every few seconds between your decisions.

Guidance:
- HOLD is the default. Only trade when there is a clear edge; overtrading loses money to fees and slippage.
- Base stops on market structure and recent range (ATR of 5-min bars), not arbitrary numbers.
- Respect the trend on higher timeframes; be careful around the open and lunch break.
- Use recent_decisions and today's trades to stay consistent; do not flip-flop.
- Write `reason` in Traditional Chinese (Cantonese style is fine), max 2 sentences.
- The trader's LESSONS (below, if any) come from the human owner reviewing your past trades.
  They override the general guidance above, but never the hard rules.
Always answer by calling the `decide` tool."""

LESSONS_FILE = Path(__file__).resolve().parent / "LESSONS.md"


def load_lessons(path: Path = LESSONS_FILE):
    """使用者教落嘅嘢。每次決策重讀，VM 更新 repo 後唔使重啟。回傳 (內文, 短 hash)。"""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "", None
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def build_system(lessons: str) -> str:
    return SYSTEM + ("\n\n=== LESSONS FROM THE OWNER ===\n" + lessons if lessons else "")

TOOL = {
    "name": "decide",
    "description": "Return the trading decision for this cycle.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["HOLD", "OPEN_LONG", "OPEN_SHORT", "CLOSE", "UPDATE_STOP"]},
            "stop_price": {"type": ["number", "null"],
                           "description": "Absolute stop price. Required for OPEN_* and UPDATE_STOP."},
            "target_price": {"type": ["number", "null"],
                             "description": "Optional absolute take-profit price."},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["action", "confidence", "reason"],
    },
}


class ClaudeBrain:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                          timeout=90, max_retries=2)

    def decide(self, context: dict) -> dict:
        lessons, lessons_ver = load_lessons()
        try:
            msg = self.client.messages.create(
                model=self.cfg.model,
                max_tokens=1024,
                system=build_system(lessons),
                tools=[TOOL],
                tool_choice={"type": "tool", "name": "decide"},
                messages=[{"role": "user",
                           "content": "Market context (JSON):\n" +
                                      json.dumps(context, ensure_ascii=False, separators=(",", ":"))}],
            )
            for block in msg.content:
                if block.type == "tool_use" and block.name == "decide":
                    d = dict(block.input)
                    d["_usage"] = {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens}
                    d["_lessons"] = lessons_ver   # 記低用咗邊個版本嘅教學，方便事後對照
                    return d
            return {"action": "HOLD", "confidence": 0, "reason": "AI 冇回傳決定"}
        except Exception as e:  # noqa: BLE001
            log.exception("Claude 決策失敗")
            return {"action": "HOLD", "confidence": 0, "reason": f"AI 出錯：{e}", "_error": True}
