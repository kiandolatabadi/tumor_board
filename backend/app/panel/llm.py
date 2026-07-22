"""Thin Claude helper: send a system + user prompt, get parsed JSON back.

One place owns the model choice, token caps, prompt caching of the (static)
system text, and the tolerant JSON extraction every stage relies on. Stages call
``call_json`` and validate the result into their own pydantic model.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from ..config import get_client

# Default to a current, capable model; override per deployment via env.
MODEL = os.getenv("PANEL_MODEL", "claude-sonnet-5")
# Specialist opinions / router / reconcile are small; keep this tight so a call
# can't run away. Synthesis passes a larger cap explicitly.
MAX_OUTPUT_TOKENS = int(os.getenv("PANEL_MAX_OUTPUT_TOKENS", "4000"))

# Hard safety net: a whole board run may make at most this many model calls.
# A runaway loop trips this instead of billing indefinitely. Reset per run.
PANEL_MAX_CALLS = int(os.getenv("PANEL_MAX_CALLS", "40"))

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)

_calls_made = 0


class OutputUnparseable(Exception):
    """The model's reply could not be read as the JSON we asked for."""


class CallBudgetExceeded(RuntimeError):
    """A single board run tried to make more model calls than PANEL_MAX_CALLS."""


def reset_call_budget() -> None:
    """Call once at the start of a board run so the budget is per-run."""
    global _calls_made
    _calls_made = 0


def calls_made() -> int:
    return _calls_made


def _extract_json(text: str) -> Any:
    """Read a JSON value out of a model reply, tolerating prose and ``` fences.

    Strategy: strip fences, try a straight parse, else scan for the first
    balanced {...} or [...] block. We never guess at truncated tails — a partial
    object raises rather than being half-read."""
    stripped = _FENCE.sub("", text.strip())
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = min(
        (i for i in (stripped.find("{"), stripped.find("[")) if i >= 0),
        default=-1,
    )
    if start < 0:
        raise OutputUnparseable(text[:300])
    opener = stripped[start]
    closer = "}" if opener == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(stripped)):
        c = stripped[i]
        if in_str:
            in_str = not (c == '"' and not esc)
            esc = c == "\\" and not esc
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start : i + 1])
                except json.JSONDecodeError as e:
                    raise OutputUnparseable(str(e)) from e
    raise OutputUnparseable("unbalanced JSON in model reply")


def call_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    cache_system: bool = True,
) -> Any:
    """Run one Claude call and return the parsed JSON body.

    ``cache_system`` marks the (static) system prompt for prompt caching, so the
    per-specialist role prompts are billed once and reused across a run."""
    global _calls_made
    _calls_made += 1
    if _calls_made > PANEL_MAX_CALLS:
        raise CallBudgetExceeded(
            f"board run exceeded PANEL_MAX_CALLS={PANEL_MAX_CALLS} model calls — aborting to avoid runaway cost"
        )
    client = get_client()
    system_block: Any = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if cache_system
        else system
    )
    resp = client.messages.create(
        model=model or MODEL,
        max_tokens=max_tokens or MAX_OUTPUT_TOKENS,
        system=system_block,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    value = _extract_json(text)
    truncated = resp.stop_reason == "max_tokens"
    return value, truncated
