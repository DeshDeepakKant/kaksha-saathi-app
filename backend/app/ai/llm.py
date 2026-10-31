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


def _create(client, **kw):  # pragma: no cover - network
    """messages.create, with API errors (bad model id, rate limit, outage) surfaced as LLMUnavailable
    so every feature takes its deterministic fallback instead of a 500."""
    import anthropic
    try:
        return client.messages.create(**kw)
    except anthropic.APIError as e:
        raise LLMUnavailable(f"{type(e).__name__}: {e}"[:300]) from e


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
        # Sessions don't autoflush: flush now so a second call in the same request finds this row
        # instead of inserting a duplicate (school_id, day).
        session.flush()
    row.cost_inr += cost



def plain_dashes(obj):
    """The apps show no em dashes: swap any the model wrote for a comma (or a hyphen when it stands alone)."""
    if isinstance(obj, str):
        return obj.replace(" \u2014 ", ", ").replace("\u2014", "-")
    if isinstance(obj, list):
        return [plain_dashes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: plain_dashes(v) for k, v in obj.items()}
    return obj


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
        resp = _create(client, **kw)
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
    return LLMResult(plain_dashes(parsed), model, in_tok, out_tok, latency, cost)


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
    resp = _create(client, **kw)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    pin, pout = PRICING_INR[_model_tier(model)]
    cost = resp.usage.input_tokens / 1e6 * pin + resp.usage.output_tokens / 1e6 * pout
    session.add(AiCall(school_id=school_id, feature=feature, model=model, prompt_version=prompt_version,
                       input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                       latency_ms=int((time.monotonic() - started) * 1000), cost_inr=round(cost, 4)))
    if school_id is not None:
        _charge(session, school_id, cost)
    return plain_dashes(text)


# INR per web search request (server-side tool; assumption: ~$10 per 1,000 searches)
WEB_SEARCH_INR = 0.9
WEB_SEARCH_TOOL = "web_search_20260209"
MAX_CONTINUATIONS = 2


def _search_outcome(blocks) -> tuple[int, int]:
    """(successful, failed) web_search_tool_result blocks. A failure's content is an error object, not a list."""
    ok = failed = 0
    for b in blocks:
        if getattr(b, "type", None) != "web_search_tool_result":
            continue
        if isinstance(getattr(b, "content", None), list):
            ok += 1
        else:
            failed += 1
    return ok, failed


def web_research(session: Session, *, feature: str, prompt_version: str, model: str, system: str,
                 user: str, max_uses: int = 3, max_tokens: int = 1500,
                 school_id: int | None = None, time_budget_s: float | None = None) -> str:
    """Short research notes from Claude's server-side web search. Raises LLMUnavailable on any failure.

    Returns "" when no search succeeded (every result was an error object): notes must be web-backed or
    nothing, so a caller never labels model memory as "web". `pause_turn` is resumed by re-sending the
    conversation (no extra "continue" message), at most MAX_CONTINUATIONS times.
    `time_budget_s` caps the whole lookup: each request gets only the time left, with no SDK retries,
    so a slow search can't hold a teacher's request open for minutes.
    """
    if budget_remaining(session, school_id) <= 0:
        raise LLMUnavailable("daily budget exhausted")
    client = _client()
    started = time.monotonic()
    tools = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses}]
    first = {"role": "user", "content": user}
    assistant: list = []
    in_tok = out_tok = searches = 0
    error = None
    deadline = started + time_budget_s if time_budget_s else None
    try:
        for _ in range(1 + MAX_CONTINUATIONS):
            api = client
            if deadline is not None:
                left = deadline - time.monotonic()
                if left < 5:
                    break  # out of time: keep whatever the finished searches produced
                api = client.with_options(timeout=left, max_retries=0)
            messages = [first] + ([{"role": "assistant", "content": assistant}] if assistant else [])
            resp = _create(api, model=model, max_tokens=max_tokens, system=system,
                           messages=messages, tools=tools)
            in_tok += resp.usage.input_tokens
            out_tok += resp.usage.output_tokens
            stu = getattr(resp.usage, "server_tool_use", None)
            searches += int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
            assistant = assistant + list(resp.content)
            if resp.stop_reason != "pause_turn":
                break
    except LLMUnavailable as e:
        error = str(e)
        raise
    except Exception as e:  # unexpected SDK/response shape: the caller just gets no notes
        error = f"{type(e).__name__}: {e}"
        raise LLMUnavailable(error[:300]) from e
    finally:
        pin, pout = PRICING_INR[_model_tier(model)]
        cost = in_tok / 1e6 * pin + out_tok / 1e6 * pout + searches * WEB_SEARCH_INR
        ok, failed = _search_outcome(assistant)
        status = "error" if error else ("ok" if ok else "no_results")
        if not error and failed and not ok:
            error = f"{failed} web search error(s)"
        session.add(AiCall(school_id=school_id, feature=feature, model=model, prompt_version=prompt_version,
                           input_tokens=in_tok, output_tokens=out_tok,
                           latency_ms=int((time.monotonic() - started) * 1000), cost_inr=round(cost, 4),
                           validation_status=status, error=error[:300] if error else None))
        if school_id is not None and cost:
            _charge(session, school_id, cost)
    if not ok:
        return ""
    # citations split one answer into several text blocks, so join them back without separators
    text = "".join(b.text for b in assistant if getattr(b, "type", None) == "text")
    return text.strip()[:4000]
