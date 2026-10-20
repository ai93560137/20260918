"""Claude 決策：每根 M1 收盤睇一次市，回傳結構化決定。出錯一律當 HOLD。
沿用龍飛陣 hsi_ai_trader/brain.py：strict tool `decide`、prompt caching、Haiku 預篩、拒答後備。"""
import hashlib
import json
import logging
import time

import anthropic

import config

log = logging.getLogger("brain")

SYSTEM = """You are the decision engine of an automated trading bot for spot gold CFD {symbol} on MetaTrader 5
(1 lot = 100 oz, price in US$ per oz, fixed lot size set by code, long or short unless the input says long-only).
Trading hours: Sunday 18:00 to Friday 17:00 US Eastern with a daily break 17:00-18:00 ET.

Every minute, when a 1-minute bar closes, you receive market data, the account, the current position and the risk
limits. Decide ONE action:
- HOLD: do nothing.
- OPEN_LONG / OPEN_SHORT: open one position of the fixed size (`risk.lots`). Only allowed when flat and the gate is OPEN.
  stop_price (absolute US$) is REQUIRED. target_price is optional.
- CLOSE: close the current position.
- UPDATE_STOP: move the stop (and optionally the target) of the current position.

Hard rules enforced by code (you cannot override them; violating them just turns your action into HOLD):
- One position at a time. No pyramiding, no reversing in one step (CLOSE first, open on a later bar).
- Stop distance must be between risk.min_sl_usd and risk.max_sl_usd from the current price.
- Entries need confidence >= risk.min_confidence. Daily entry cap risk.max_trades_per_day (0 = none).
- The risk gate (six checks: session, volatility, exposure, daily loss, drawdown, pacing) must be OPEN to enter.
- A position is force-closed by code after risk.max_hold_min minutes, and the stop/target are checked on every bar.

Guidance:
- HOLD is the default. Only trade when there is a clear edge; overtrading loses money to spread and slippage.
- Base stops on market structure and recent range (ATR of 1-minute and 15-minute bars), not arbitrary numbers.
- Respect the higher-timeframe trend (15-minute bars); be careful around the New York open, the 17:00 ET break
  and scheduled US data releases (see news).
- Use recent_decisions and recent_trades to stay consistent; do not flip-flop bar to bar.
- Write `reason` in Traditional Chinese (Cantonese style is fine), max 2 sentences.
- The owner's LESSONS (below, if any) come from the human owner reviewing your past trades.
  They override the general guidance above, but never the hard rules.
Always answer by calling the `decide` tool exactly once."""

TOOL = {
    "name": "decide",
    "description": "Return the trading decision for this bar. Call this exactly once.",
    "strict": True,   # Opus／Sonnet 5.5 唔接受強制 tool_choice（400）：auto + strict 保證參數合 schema
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["HOLD", "OPEN_LONG", "OPEN_SHORT", "CLOSE", "UPDATE_STOP"]},
            "stop_price": {"anyOf": [{"type": "number"}, {"type": "null"}],
                           "description": "Absolute stop price in US$. Required for OPEN_* and UPDATE_STOP."},
            "target_price": {"anyOf": [{"type": "number"}, {"type": "null"}],
                             "description": "Optional absolute take-profit price in US$."},
            "confidence": {"type": "number", "description": "0 to 1."},
            "reason": {"type": "string"},
        },
        "required": ["action", "stop_price", "target_price", "confidence", "reason"],
        "additionalProperties": False,
    },
}

GATE_SYSTEM = """You are the pre-screen for an automated gold ({symbol}) trading bot. The bot is FLAT.
A stronger model makes the real decision, but every call costs money, so you only decide whether this 1-minute bar
deserves a full analysis. You do not trade.
Answer look=true when there is a plausible entry setup now: a breakout of a recent range, a pullback to a level
within a 15-minute trend, a sharp move or reversal, or price near an important session high/low. Also answer
look=true when unsure. Answer look=false only when the market is clearly quiet or choppy with no setup either way.
Write `reason` in Traditional Chinese (Cantonese style is fine), one short sentence.
The owner's LESSONS (below, if any) describe what the owner wants traded; follow them."""

GATE_FORMAT = {"type": "json_schema", "schema": {
    "type": "object", "properties": {"look": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["look", "reason"], "additionalProperties": False}}

STABLE_KEYS = ("product", "bars_m15_older")           # 每 15 分鐘至 1 小時先變：放可快取前段
FALLBACK_BETA = "server-side-fallback-2026-07-01"     # 拒答時由伺服器按類別轉後備模型（只限 Anthropic API）
FALLBACK_MODELS = ("claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5")


def _dump(d):
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _user_content(context, ask):
    stable = {k: context[k] for k in STABLE_KEYS if k in context}
    live = {k: v for k, v in context.items() if k not in STABLE_KEYS}
    return [{"type": "text", "text": "Product and older 15-minute bars (change slowly), JSON:\n" + _dump(stable),
             "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": f"Market context now (JSON). {ask}\n" + _dump(live)}]


def _usage(msg, model):
    u = msg.usage
    return {"in": u.input_tokens, "out": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "model": getattr(msg, "model", None) or model}


def cost_usd(usage):
    """按 config.PRICES 估算（美元）。未知模型回 None。"""
    if not usage:
        return None
    price = config.PRICES.get(str(usage.get("model") or "").split("@")[0])
    if not price:
        for key, val in config.PRICES.items():
            if str(usage.get("model") or "").startswith(key):
                price = val
                break
    if not price:
        return None
    pin, pout, pcache = price
    return round((usage.get("in", 0) * pin + usage.get("out", 0) * pout + usage.get("cache_read", 0) * pcache
                  + usage.get("cache_write", 0) * pin * 1.25) / 1e6, 5)


def build_system(lessons, symbol=None):
    text = SYSTEM.replace("{symbol}", symbol or config.SYMBOL)
    return text + ("\n\n=== LESSONS FROM THE OWNER ===\n" + lessons if lessons else "")


def make_client():
    if config.PROVIDER == "vertex":
        from anthropic import AnthropicVertex
        kwargs = {"region": config.VERTEX_REGION, "timeout": config.API_TIMEOUT_SEC, "max_retries": 1}
        if config.VERTEX_PROJECT:
            kwargs["project_id"] = config.VERTEX_PROJECT
        return AnthropicVertex(**kwargs)
    return anthropic.Anthropic(timeout=config.API_TIMEOUT_SEC, max_retries=1)   # ANTHROPIC_API_KEY 由環境變數讀


class ClaudeBrain:
    def __init__(self, client=None, lessons_loader=None):
        self._client = client
        self.lessons_loader = lessons_loader or (lambda: "")
        self._fallbacks = config.PROVIDER != "vertex" and config.MODEL in FALLBACK_MODELS

    @property
    def client(self):
        if self._client is None:
            self._client = make_client()
        return self._client

    def _lessons(self):
        text = (self.lessons_loader() or "").strip()
        return text, (hashlib.sha256(text.encode("utf-8")).hexdigest()[:8] if text else None)

    def _create(self, **kwargs):
        if self._fallbacks:
            try:
                return self.client.messages.create(extra_headers={"anthropic-beta": FALLBACK_BETA},
                                                   extra_body={"fallbacks": "default"}, **kwargs)
            except anthropic.BadRequestError as exc:
                log.warning("拒答後備功能唔用得，改普通請求：%s", exc.message)
                self._fallbacks = False
        return self.client.messages.create(**kwargs)

    def screen(self, context):
        """冇倉時用平價模型篩一次。出錯一律當「要睇」。"""
        lessons, _ = self._lessons()
        text = GATE_SYSTEM.replace("{symbol}", config.SYMBOL) + ("\n\n=== LESSONS FROM THE OWNER ===\n" + lessons if lessons else "")
        started = time.time()
        try:
            msg = self.client.messages.create(
                model=config.GATE_MODEL, max_tokens=4000,
                system=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                output_config={"effort": config.GATE_EFFORT, "format": GATE_FORMAT},
                messages=[{"role": "user", "content": _user_content(context, "Screen this bar.")}])
            usage = _usage(msg, config.GATE_MODEL)
            ms = int((time.time() - started) * 1000)
            if msg.stop_reason == "refusal":
                return {"look": True, "reason": "篩選拒答，照問決策模型", "_usage": usage, "_ms": ms, "_error": True}
            out = json.loads(next(b.text for b in msg.content if b.type == "text"))
            return {"look": bool(out.get("look")), "reason": str(out.get("reason") or "")[:200], "_usage": usage, "_ms": ms}
        except Exception as exc:  # noqa: BLE001
            log.warning("篩選失敗，照問決策模型：%s", exc.__class__.__name__)
            return {"look": True, "reason": f"篩選出錯：{exc.__class__.__name__}", "_error": True,
                    "_ms": int((time.time() - started) * 1000)}

    def decide(self, context):
        lessons, ver = self._lessons()
        system = [{"type": "text", "text": build_system(lessons), "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        started = time.time()
        try:
            msg = self._create(
                model=config.MODEL, max_tokens=config.MAX_TOKENS, system=system, tools=[TOOL],
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                output_config={"effort": config.EFFORT},
                messages=[{"role": "user", "content": _user_content(context, "Call the `decide` tool.")}])
            usage = _usage(msg, config.MODEL)
            ms = int((time.time() - started) * 1000)
            base = {"_usage": usage, "_lessons": ver, "_ms": ms}
            if msg.stop_reason == "refusal":
                return {"action": "HOLD", "confidence": 0, "reason": "AI 拒絕回應", "_error": True, **base}
            if msg.stop_reason == "max_tokens":
                return {"action": "HOLD", "confidence": 0, "reason": "AI 回應被截斷（max_tokens）", "_error": True, **base}
            for block in msg.content:
                if block.type == "tool_use" and block.name == "decide":
                    return {**dict(block.input), **base}
            return {"action": "HOLD", "confidence": 0, "reason": "AI 冇回傳決定", **base}
        except Exception as exc:  # noqa: BLE001
            log.exception("Claude 決策失敗")
            return {"action": "HOLD", "confidence": 0, "reason": f"AI 出錯：{exc.__class__.__name__}: {str(exc)[:120]}",
                    "_error": True, "_ms": int((time.time() - started) * 1000)}
