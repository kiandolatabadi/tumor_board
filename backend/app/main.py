"""FastAPI entrypoint.

The app lives in ``app.panel.api``; this re-exports it so both
``uvicorn app.main:app`` and ``uvicorn app.panel.api:app`` work.

Run (from the backend/ directory):  uvicorn app.main:app --reload
"""
from __future__ import annotations

from .panel.api import app

__all__ = ["app"]
