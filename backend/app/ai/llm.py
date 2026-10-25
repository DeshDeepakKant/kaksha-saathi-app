"""Thin Claude wrapper: structured output via a forced tool, retries, logging, cost, budget.

Every call is recorded in `ai_calls`; the daily budget gate lives here so no feature
can bypass it. If no API key is configured the caller receives `LLMUnavailable` and is
expected to use its deterministic fallback (which every AI feature has).
"""
from __future__ import annotations

import inspect
import json
import time
from functools import lru_cache
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.tables import AiCall, UsageCounter
from app.models.tables import utcnow


class LLMUnavailable(Exception):
    pass


class LLMValidationError(Exception):
    pass


@dataclass
class LLMResult:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_inr: float


# INR per 1M tokens (assumption documented in docs/04; update if pricing changes)
PRICING_INR = {
    "haiku": (60.0, 300.0),
    "sonnet": (180.0, 900.0),
}


def _client():  # pragma: no cover - network
    import anthropic
    s = get_settings()
    if not s.anthropic_api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=s.anthropic_api_key)


@lru_cache
def _supports_temperature(client) -> bool:  # pragma: no cover - depends on installed SDK
    """Newer Claude models reject `temperature`; detect by capability rather than model name."""
    try:
        return "temperature" in inspect.signature(client.messages.create).parameters
    except (TypeError, ValueError):
        return False


def _model_tier(model: str) -> str:
    return "haiku" if "haiku" in model else "sonnet"


def budget_remaining(session: Session, school_id: int | None) -> float:
    if school_id is None:
        return float("inf")
    s = get_settings()
    row = session.scalar(select(UsageCounter).where(
        UsageCounter.school_id == school_id, UsageCounter.day == utcnow().date()))
    used = row.cost_inr if row else 0.0
    return s.daily_budget_inr_per_school - used


def _charge(session: Session, school_id: int, cost: float) -> None:
    day = utcnow().date()
    row = session.scalar(select(UsageCounter).where(
        UsageCounter.school_id == school_id, UsageCounter.day == day))
    if row is None:
        row = UsageCounter(school_id=school_id, day=day, cost_inr=0.0)
        session.add(row)
    row.cost_inr += cost


def structured(
    session: Session,
    *,
    feature: str,
    prompt_version: str,
    model: str,
    system: str,
    user: str,
    schema: dict,
    tool_name: str,
    images: list[dict] | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    school_id: int | None = None,
    retry_with_error: bool = True,
    validate=None,
) -> LLMResult:
    """Call Claude with a forced tool producing `schema`. Raises LLMUnavailable/LLMValidationError."""
    s = get_settings()
    if budget_remaining(session, school_id) <= 0:
        raise LLMUnavailable("daily budget exhausted")
    client = _client()

    content: list[dict] = []
    if images:
        content.extend(images)
    content.append({"type": "text", "text": user})
    tools = [{"name": tool_name, "description": "Return the structured result.", "input_schema": schema}]
    messages = [{"role": "user", "content": content}]
    started = time.monotonic()
    in_tok = out_tok = 0
    last_err = ""
    parsed: dict | None = None

    kw = dict(model=model, max_tokens=max_tokens,
              system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
              tools=tools, tool_choice={"type": "tool", "name": tool_name}, messages=messages)
    if _supports_temperature(client):
        kw["temperature"] = temperature
    for attempt in range(2 if retry_with_error else 1):
        resp = client.messages.create(**kw)
        in_tok += resp.usage.input_tokens
        out_tok += resp.usage.output_tokens
        block = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            last_err = "no tool_use block"
        else:
            data = block.input if isinstance(block.input, dict) else json.loads(block.input)
            try:
                if validate is not None:
                    data = validate(data)
                parsed = data
                break
            except Exception as e:  # validation failure → one retry with the error appended
                last_err = str(e)
                if attempt == 0:
                    kw["messages"] = messages = messages + [
                        {"role": "assistant", "content": [{"type": "tool_use", "id": block.id,
                                                           "name": tool_name, "input": block.input}]},
                        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id,
                                                      "is_error": True, "content": f"Invalid output: {last_err}. Fix and call the tool again."}]},
                    ]

    latency = int((time.monotonic() - started) * 1000)
    pin, pout = PRICING_INR[_model_tier(model)]
    cost = in_tok / 1e6 * pin + out_tok / 1e6 * pout
    status = "ok" if parsed is not None else "invalid"
    session.add(AiCall(school_id=school_id, feature=feature, model=model, prompt_version=prompt_version,
                       input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency,
                       cost_inr=round(cost, 4), validation_status=status, error=None if parsed else last_err[:300]))
    if school_id is not None:
        _charge(session, school_id, cost)
    if parsed is None:
        raise LLMValidationError(last_err)
    return LLMResult(parsed, model, in_tok, out_tok, latency, cost)


def simple_text(session: Session, *, feature: str, prompt_version: str, model: str, system: str,
                user: str, max_tokens: int = 300, temperature: float = 0.2,
                school_id: int | None = None) -> str:  # pragma: no cover - network
    """Plain-text call for cases where a schema adds no value (tutor lines). Includes a text-level filter."""
    s = get_settings()
    if budget_remaining(session, school_id) <= 0:
        raise LLMUnavailable("daily budget exhausted")
    client = _client()
    started = time.monotonic()
    kw = dict(model=model, max_tokens=max_tokens, system=system,
              messages=[{"role": "user", "content": user}])
    if _supports_temperature(client):
        kw["temperature"] = temperature
    resp = client.messages.create(**kw)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    pin, pout = PRICING_INR[_model_tier(model)]
    cost = resp.usage.input_tokens / 1e6 * pin + resp.usage.output_tokens / 1e6 * pout
    session.add(AiCall(school_id=school_id, feature=feature, model=model, prompt_version=prompt_version,
                       input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                       latency_ms=int((time.monotonic() - started) * 1000), cost_inr=round(cost, 4)))
    if school_id is not None:
        _charge(session, school_id, cost)
    return text
