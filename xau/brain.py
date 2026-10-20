"""Claude 決策：每根 M1 收盤睇一次市，回傳結構化決定。出錯一律當 HOLD。
沿用龍飛陣 hsi_ai_trader/brain.py：strict tool `decide`、prompt caching、Haiku 預篩、拒答後備。"""
import hashlib
import json
import logging
import time

import anthropic

import config

log = logging.getLogger("brain")

SYSTEM = """You are the decision engine of an automated trading bot for {product_desc}
(fixed lot size set by code, long or short unless the input says long-only; stop distances in the risk block are in price units, pip size is given).
{hours}

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
- Risk ladder (risk.ladder): level B = no new entries, C = position halved, D = everything closed and the bot halted
  until the owner unlocks it. It is driven by the daily loss, drawdown from the equity high-water mark, the hard stop
  on cumulative loss and the broker margin level. You cannot change it.
- A position is force-closed by code after risk.max_hold_min minutes, and the stop/target are checked on every bar.

The legacy system's rules and gate (the REFERENCE section below) are reference only: they describe what the previous
rule-based system did and what was measured. Use them as context, not as conditions you must satisfy.

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

GATE_SYSTEM = """You are the pre-screen for an automated {symbol} trading bot ({product_desc}). The bot is FLAT.
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

STABLE_KEYS = ("product", "bars_m15_older")           # 一個鐘先變一次：放可快取前段（整點切，見 main.build_context）
STABLE2_KEYS = ("bars_m1_older",)                     # 上一個整點之前嘅 M1：第二個快取段
CACHE_TTL_DECIDE = "1h"                               # 決策模型唔係每根都問（篩選先），1 小時 TTL（寫 2×）
CACHE_TTL_SCREEN = "5m"                               # 篩選每分鐘都問，5 分鐘 TTL 夠（寫 1.25×）
FALLBACK_BETA = "server-side-fallback-2026-07-01"     # 拒答時由伺服器按類別轉後備模型（只限 Anthropic API）
FALLBACK_MODELS = ("claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5")


def _dump(d):
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _user_content(context, ask, ttl=CACHE_TTL_DECIDE):
    """三段：[產品＋整點前 M15]（快取）→ [整點前 M1]（快取）→ [本小時 K 線＋戶口＋持倉＋風控]（即時）。
    快取段每個鐘先變一次；system 另有一個快取段，合共 3 個 cache_control（上限 4）。"""
    stable = {k: context[k] for k in STABLE_KEYS if k in context}
    stable2 = {k: context[k] for k in STABLE2_KEYS if k in context}
    live = {k: v for k, v in context.items() if k not in STABLE_KEYS and k not in STABLE2_KEYS}
    cc = {"type": "ephemeral", "ttl": ttl}
    return [{"type": "text", "text": "Product and 15-minute bars before the current hour (change once an hour), JSON:\n" + _dump(stable), "cache_control": cc},
            {"type": "text", "text": "1-minute bars before the current hour (change once an hour), JSON:\n" + _dump(stable2), "cache_control": cc},
            {"type": "text", "text": f"Market context now: this hour's 1-minute and 15-minute bars, account, position, risk (JSON). {ask}\n" + _dump(live)}]


def _usage(msg, model, ttl=CACHE_TTL_DECIDE):
    u = msg.usage
    return {"in": u.input_tokens, "out": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_ttl": ttl, "model": getattr(msg, "model", None) or model}


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
    write_mult = 2.0 if str(usage.get("cache_ttl") or "1h") == "1h" else 1.25     # 快取寫入：1h TTL 2×，5m TTL 1.25×
    return round((usage.get("in", 0) * pin + usage.get("out", 0) * pout + usage.get("cache_read", 0) * pcache
                  + usage.get("cache_write", 0) * pin * write_mult) / 1e6, 5)


REFERENCE_FILE = __file__.rsplit("/", 1)[0] + "/reference/legacy_rules.md"


def load_reference():
    """舊規則／電閘摘要（使用者 10-20：刪減做硬閘、留做參考）。讀唔到就冇。"""
    try:
        with open(REFERENCE_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def build_system(lessons, symbol=None, reference=None):
    hours = ("Trading hours: Sunday 17:00 to Friday 17:00 US Eastern, 24 hours on weekdays (liquidity peaks in the London and New York sessions)."
             if config.PRODUCT_KIND == "fx" else "Trading hours: Sunday 18:00 to Friday 17:00 US Eastern with a daily break 17:00-18:00 ET.")
    text = SYSTEM.replace("{product_desc}", config.PRODUCT_DESC).replace("{hours}", hours).replace("{symbol}", symbol or config.SYMBOL)
    reference = load_reference() if reference is None else reference
    if reference:
        text += "\n\n=== REFERENCE: LEGACY RULES AND GATE (not binding) ===\n" + reference
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
        text = GATE_SYSTEM.replace("{product_desc}", config.PRODUCT_DESC).replace("{symbol}", config.SYMBOL) + ("\n\n=== LESSONS FROM THE OWNER ===\n" + lessons if lessons else "")
        started = time.time()
        try:
            msg = self.client.messages.create(
                model=config.GATE_MODEL, max_tokens=4000,
                system=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral", "ttl": CACHE_TTL_SCREEN}}],
                output_config={"effort": config.GATE_EFFORT, "format": GATE_FORMAT},
                messages=[{"role": "user", "content": _user_content(context, "Screen this bar.", CACHE_TTL_SCREEN)}])
            usage = _usage(msg, config.GATE_MODEL, CACHE_TTL_SCREEN)
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


# ---------------------------------------------------------------------------
# [R290] Telegram 頻道訊號解析（只解析，唔決定）：自由格式 → 固定 JSON
# ---------------------------------------------------------------------------
SIGNAL_SYSTEM = """You parse messages from Telegram trading-signal channels. Messages are free-form, often mixed Chinese/English with emoji.
Only parse and flag risks; never invent numbers that are not in the message (use null). Write `analysis` in Traditional Chinese
(Cantonese style is fine), 2-4 sentences: what the signal says, risk/reward, anything suspicious or missing."""

SIGNAL_FORMAT = {"type": "json_schema", "schema": {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["new_signal", "update", "other"],
                 "description": "new_signal = a new entry; update = managing an existing trade (move SL, close, TP hit); other = anything else"},
        "symbol": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "side": {"anyOf": [{"type": "string", "enum": ["BUY", "SELL"]}, {"type": "null"}]},
        "order_type": {"anyOf": [{"type": "string", "enum": ["market", "limit", "stop"]}, {"type": "null"}]},
        "entry_low": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "entry_high": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "sl": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "tp": {"type": "array", "items": {"type": "number"}},
        "update_action": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "confidence": {"type": "number"},
        "analysis": {"type": "string"},
    },
    "required": ["kind", "symbol", "side", "order_type", "entry_low", "entry_high", "sl", "tp", "update_action", "confidence", "analysis"],
    "additionalProperties": False}}


def analyze_signal(client, text, reply_text=None, channel=None, model=None):
    """回傳 (dict, None) 或 (None, 原因)。"""
    context = f"\n(This message replies to an earlier message:\n{reply_text[:1500]}\n)" if reply_text else ""
    user = f"Channel: {channel or 'unknown'}{context}\nMessage:\n{text}"
    try:
        msg = client.messages.create(
            model=model or config.MODEL, max_tokens=4000,
            system=[{"type": "text", "text": SIGNAL_SYSTEM, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            output_config={"effort": "low", "format": SIGNAL_FORMAT},
            messages=[{"role": "user", "content": user}])
        if msg.stop_reason == "refusal":
            return None, "AI 拒答"
        data = json.loads(next(b.text for b in msg.content if b.type == "text"))
    except Exception as exc:  # noqa: BLE001
        return None, f"AI 呼叫失敗：{type(exc).__name__}: {str(exc)[:120]}"
    return (data if isinstance(data, dict) else None), (None if isinstance(data, dict) else "AI 回覆唔係 JSON")
