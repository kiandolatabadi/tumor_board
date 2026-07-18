"""Runtime configuration, loaded from the environment (see .env.example)."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

# Default to a fast Sonnet model for the tool-use loop. Override via env.
MODEL = os.getenv("TUMOR_BOARD_MODEL", "claude-sonnet-4-6")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
MAX_TOOL_TURNS = int(os.getenv("TUMOR_BOARD_MAX_TURNS", "12"))
# Findings are verbose (patient_facing_note + live_question per finding), so a
# full board case can exceed a small cap. Truncation used to yield ZERO findings;
# _parse now salvages, but headroom is the cheaper half of the fix.
MAX_OUTPUT_TOKENS = int(os.getenv("TUMOR_BOARD_MAX_OUTPUT_TOKENS", "16000"))


@lru_cache
def get_client():
    """Lazily build the Anthropic client so imports don't require a key."""
    from anthropic import Anthropic

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy backend/.env.example to "
            "backend/.env and add your key."
        )
    return Anthropic(api_key=key)
