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
- US ETFs and stocks only: portfolio limits across products. If risk.portfolio_long_blocked / portfolio_short_blocked is
  not null, opening in that direction is rejected (e.g. 2 of SPY/QQQ/DIA/IWM, or 2 of AAPL/MSFT/NVDA/GOOGL/AMZN/META/TSLA, already hold that
  direction, or all US products together hit the combined daily loss limit). Do not propose that entry; HOLD or wait instead.

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


LESSONS_DIR = Path(__file__).resolve().parent / "lessons"
EMPTY_MARK = "（未有）"


LESSONS_ALIAS = {"MHI": "HSI"}      # [R287] 小型恒指同大期同一個指數，用 HSI 教學簿（MHI 真倉跟 HSI 模擬學到嘅嘢）


def product_lessons(product, lessons_dir: Path = LESSONS_DIR) -> str:
    """[R228] 個別產品教學簿 lessons/<產品>.md：只取「## 教學」之後嘅內容；（未有）當冇。"""
    product = LESSONS_ALIAS.get(product, product)
    try:
        text = (lessons_dir / f"{product}.md").read_text(encoding="utf-8")
    except (FileNotFoundError, TypeError):
        return ""
    body = text.split("## 教學", 1)[1] if "## 教學" in text else ""
    body = body.strip()
    return "" if body in ("", EMPTY_MARK) else body


def load_lessons(path: Path = LESSONS_FILE, product=None, lessons_dir: Path = LESSONS_DIR):
    """使用者教落嘅嘢。每次決策重讀，VM 更新 repo 後唔使重啟。回傳 (內文, 短 hash)。
    [R228] 使用者 10-18：共用教學簿（LESSONS.md）＋ 該產品自己嘅教學簿（lessons/<產品>.md），覆盤後各自更新。"""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        text = ""
    own = product_lessons(product, lessons_dir) if product else ""
    if own:
        text += f"\n\n=== LESSONS FOR {product} ONLY (override the shared ones above for {product}) ===\n{own}"
    text = text.strip()
    if not text:
        return "", None
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def product_line(cfg) -> str:
    from markets import spec_for
    sp = spec_for(cfg.product)
    if sp.kind == "stock":
        kind = "ETF" if "ETF" in sp.name or sp.product in ("GLD", "USO") else "single stock (earnings gaps possible)"
        return (f"{sp.name} ({sp.product}, US-listed {kind}, about US${sp.notional_usd:,.0f} per position, share count "
                f"set by code, tick {sp.tick:g}, long or short), US extended hours 04:00-20:00 ET (pre-market, "
                f"regular 09:30-16:00, after-hours; thinner liquidity and wider spreads outside regular hours)"
                + ("" if sp.ext_hours else "; NEW ENTRIES ONLY in regular hours 09:30-16:00 ET (spreads too wide "
                   "outside), existing positions are still managed"))
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
    "strict": True,   # Sonnet／Opus 5.5 唔接受強制 tool_choice（400），用 auto + strict 保證參數合 schema
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
            "watch_above": {"anyOf": [{"type": "number"}, {"type": "null"}],
                            "description": "Only for HOLD while flat: the price above which you would want to re-evaluate "
                                           "(e.g. the breakout level you are waiting for). While price stays strictly between "
                                           "watch_below and watch_above, the bot may reuse this HOLD for up to 30 minutes without "
                                           "asking you again. null otherwise, or if any move could matter."},
            "watch_below": {"anyOf": [{"type": "number"}, {"type": "null"}],
                            "description": "Only for HOLD while flat: the price below which you would want to re-evaluate. "
                                           "null otherwise."},
        },
        "required": ["action", "stop_price", "target_price", "confidence", "reason", "watch_above", "watch_below"],
        "additionalProperties": False,
    },
}


GATE_SYSTEM = """You are the pre-screen for an automated intraday trading bot for {product_line}.
The bot is FLAT. A stronger model makes the real decision, but every call to it costs money, so you only decide
whether this 5-minute bar deserves a full analysis. You do not trade.

Answer look=true when there is a plausible entry setup now: a breakout or breakdown of a recent range, a pullback to
a level within a trend, a sharp move or reversal, a volume spike, or price near an important daily high/low.
Also answer look=true when you are unsure. Answer look=false only when the market is clearly quiet or choppy with no
setup in either direction. Missing a good trade costs far more than one extra call.
Write `reason` in Traditional Chinese (Cantonese style is fine), one short sentence.
The owner's LESSONS (below, if any) describe what the owner wants traded; follow them."""

GATE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"look": {"type": "boolean"}, "reason": {"type": "string"}},
        "required": ["look", "reason"],
        "additionalProperties": False,
    },
}

# 日內唔變嘅部分（日線、合約）放喺可快取嘅前段；其餘每 5 分鐘都變，放後面（方案 C）
STABLE_KEYS = ("product", "market", "contract", "bars_daily")
# 拒答時由伺服器按類別轉去後備模型再答（Opus 5.5／Fable 5.1／Sonnet 5.5 先支援）
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5")


def _user_content(context: dict, ask: str):
    """[R218] 方案 C：日線同合約放第一段並標記快取（1 小時），同 system 一齊成為固定前綴；即時數據放第二段。"""
    dump = lambda d: json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))  # noqa: E731
    stable = {k: context[k] for k in STABLE_KEYS if k in context}
    live = {k: v for k, v in context.items() if k not in STABLE_KEYS}
    return [{"type": "text", "text": "Daily bars and contract (unchanged during the trading day), JSON:\n" + dump(stable),
             "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": f"Market context now (JSON). {ask}\n" + dump(live)}]


def _usage(msg, model=None):
    u = msg.usage
    return {"in": u.input_tokens, "out": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "model": getattr(msg, "model", None) or model}     # 有後備模型接手時係實際答嘅模型


class ClaudeBrain:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None,
                                          timeout=90, max_retries=2)
        self._fallbacks = cfg.model in FALLBACK_MODELS

    def _create(self, **kwargs):
        if self._fallbacks:
            try:
                return self.client.messages.create(extra_headers={"anthropic-beta": FALLBACK_BETA},
                                                   extra_body={"fallbacks": "default"}, **kwargs)
            except anthropic.BadRequestError as e:
                # 後備功能唔受落（例如 beta 收咗）：之後唔再用，照普通方式問，唔好令每次決策都出錯
                log.warning("拒答後備功能唔用得，改普通請求：%s", e.message)
                self._fallbacks = False
        return self.client.messages.create(**kwargs)

    def screen(self, context: dict) -> dict:
        """[R218] 方案 A：Haiku 篩選。出錯一律當「要睇」（寧可多問一次，唔好漏機會）。"""
        cfg = self.cfg
        lessons, _ = load_lessons(product=cfg.product)
        text = GATE_SYSTEM.replace("{product_line}", product_line(cfg))
        text += "\n\n=== LESSONS FROM THE OWNER ===\n" + lessons if lessons else ""
        try:
            msg = self.client.messages.create(
                model=cfg.gate_model,
                max_tokens=4000,           # Haiku 5.5 預設會思考，思考 token 計入；太細會截斷
                system=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                output_config={"effort": cfg.gate_effort or "low", "format": GATE_FORMAT},
                messages=[{"role": "user", "content": _user_content(context, "Screen this bar.")}],
            )
            usage = _usage(msg, cfg.gate_model)
            if msg.stop_reason == "refusal":
                return {"look": True, "reason": "篩選拒答，照問決策模型", "_usage": usage, "_error": True}
            out = json.loads(next(b.text for b in msg.content if b.type == "text"))
            return {"look": bool(out.get("look")), "reason": str(out.get("reason") or "")[:200], "_usage": usage}
        except Exception as e:  # noqa: BLE001
            log.warning("Haiku 篩選失敗，照問決策模型：%s", e.__class__.__name__)
            return {"look": True, "reason": f"篩選出錯：{e.__class__.__name__}", "_error": True}

    def decide(self, context: dict) -> dict:
        lessons, lessons_ver = load_lessons(product=self.cfg.product)
        # prompt caching：tools → system（硬性規則＋LESSONS）→ 日線，係固定前綴，用 1 小時 TTL；
        # 所有會變嘅嘢（時間、5 分鐘 K 線、倉位、額度）放喺 user 訊息第二段。
        system = [{"type": "text", "text": build_system(lessons, self.cfg),
                   "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        try:
            kwargs = {}
            if self.cfg.effort:
                kwargs["output_config"] = {"effort": self.cfg.effort}
            msg = self._create(
                model=self.cfg.model,
                max_tokens=16000,          # 思考 token 都計入，太細會截斷
                system=system,
                tools=[TOOL],
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                messages=[{"role": "user", "content": _user_content(context, "Call the `decide` tool.")}],
                **kwargs,
            )
            usage = _usage(msg, self.cfg.model)
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
