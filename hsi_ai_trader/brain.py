"""Claude 決策：每 5 分鐘睇一次市，回傳結構化決定。出錯一律當 HOLD。"""
import hashlib
import json
import logging
from pathlib import Path

import anthropic

log = logging.getLogger("brain")

SYSTEM = """You are the decision engine of an automated intraday trading bot for {product_line}.
The product, market, tick and point value (converted to HKD) are also given in the input.

Every 5 minutes you receive market data, the current position and the risk budget. Decide ONE action:
- HOLD: do nothing.
- OPEN_LONG / OPEN_SHORT: open one position of the fixed size set by code (`risk.order_qty`). Only allowed when flat.
  stop_price is REQUIRED.
- CLOSE: close the current position.
- UPDATE_STOP: move the stop (and optionally target) of the current position.

Hard rules enforced by code (you cannot override them; violating them just turns your action into HOLD):
- One position at a time. No pyramiding, no reversing in one step (CLOSE first, open on a later cycle).
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


def product_line(cfg) -> str:
    from markets import spec_for
    sp = spec_for(cfg.product)
    if sp.kind == "stock":
        return (f"{sp.name} ({sp.product}, US-listed ETF, about US${sp.notional_usd:,.0f} per position, share count "
                f"set by code, tick {sp.tick:g}, long or short), US extended hours 04:00-20:00 ET (pre-market, "
                f"regular 09:30-16:00, after-hours; thinner liquidity and wider spreads outside regular hours)")
    sess = ("HKFE day and night sessions (HKT)" if sp.market == "HK"
            else "CME Globex nearly 24h, Sunday 18:00 to Friday 17:00 US Eastern, daily break 17:00-18:00 ET")
    return (f"{sp.name} ({sp.product}, front month, {sp.currency} {sp.point_value:g} per index point, "
            f"tick {sp.tick:g}), {sess}")


def build_system(lessons: str, cfg=None) -> str:
    """固定前綴（每個產品程式各自一份，可快取）：產品描述＋硬性規則＋使用者教學。"""
    text = SYSTEM.replace("{product_line}", product_line(cfg) if cfg is not None else "an index futures contract")
    return text + ("\n\n=== LESSONS FROM THE OWNER ===\n" + lessons if lessons else "")

TOOL = {
    "name": "decide",
    "description": "Return the trading decision for this cycle. Call this exactly once.",
    "strict": True,   # Sonnet 5.5 唔接受強制 tool_choice（400），用 auto + strict 保證參數合 schema
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["HOLD", "OPEN_LONG", "OPEN_SHORT", "CLOSE", "UPDATE_STOP"]},
            "stop_price": {"anyOf": [{"type": "number"}, {"type": "null"}],
                           "description": "Absolute stop price. Required for OPEN_* and UPDATE_STOP."},
            "target_price": {"anyOf": [{"type": "number"}, {"type": "null"}],
                             "description": "Optional absolute take-profit price."},
            "confidence": {"type": "number", "description": "0 to 1."},
            "reason": {"type": "string"},
        },
        "required": ["action", "stop_price", "target_price", "confidence", "reason"],
        "additionalProperties": False,
    },
}


class ClaudeBrain:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                          timeout=90, max_retries=2)

    def decide(self, context: dict) -> dict:
        lessons, lessons_ver = load_lessons()
        # prompt caching：tools → system 係固定前綴（硬性規則＋LESSONS），每 5 分鐘先 call 一次，
        # 用 1 小時 TTL；所有會變嘅嘢（時間、K 線、倉位、額度）只放喺 user 訊息。
        system = [{"type": "text", "text": build_system(lessons, self.cfg),
                   "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        try:
            kwargs = {}
            if self.cfg.effort:
                kwargs["output_config"] = {"effort": self.cfg.effort}
            msg = self.client.messages.create(
                model=self.cfg.model,
                max_tokens=16000,          # 思考 token 都計入，太細會截斷
                system=system,
                tools=[TOOL],
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                messages=[{"role": "user",
                           "content": "Market context (JSON). Call the `decide` tool.\n" +
                                      json.dumps(context, ensure_ascii=False, sort_keys=True,
                                                 separators=(",", ":"))}],
                **kwargs,
            )
            u = msg.usage
            usage = {"in": u.input_tokens, "out": u.output_tokens,
                     "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                     "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0}
            if msg.stop_reason == "refusal":
                return {"action": "HOLD", "confidence": 0, "reason": "AI 拒絕回應", "_usage": usage,
                        "_lessons": lessons_ver, "_error": True}
            for block in msg.content:
                if block.type == "tool_use" and block.name == "decide":
                    d = dict(block.input)
                    d["_usage"] = usage
                    d["_lessons"] = lessons_ver   # 記低用咗邊個版本嘅教學，方便事後對照
                    return d
            return {"action": "HOLD", "confidence": 0, "reason": "AI 冇回傳決定", "_usage": usage,
                    "_lessons": lessons_ver}
        except Exception as e:  # noqa: BLE001
            log.exception("Claude 決策失敗")
            return {"action": "HOLD", "confidence": 0, "reason": f"AI 出錯：{e}", "_error": True}
