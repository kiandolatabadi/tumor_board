"""The tumor-board *panel* — an agentic, format-free rebuild of the analysis core.

Design (see docs/architecture.md):

    load clean markdown case (data/cases/, via cases.get_case — no FHIR)
        │
    Router (Claude) picks the relevant specialists for THIS case
        │  always-on: oncology, pharmacy, internal_medicine
        │  on-demand: radiology, pathology, genetics, fertility,
        │             radiation_oncology, surgery, palliative_goc, cardiology
        ▼
    Round 1 — PARALLEL fan-out: every chosen specialist consults at once,
              reasoning from native knowledge over the clean chart + transcript,
              each returning findings + claims (positions) + open needs.
        ▼
    Reconciliation (Claude): scan the opinions for CONTRADICTIONS and
              unmet DEPENDENCIES between specialists.
        ▼
    Round 2+ — TARGETED cross-examination (broker-mediated): the orchestrator
              carries one specialist's claim to another and asks it to concur or
              rebut. Only the involved specialists re-run. Bounded by a round cap.
        ▼
    Synthesis (Claude): merge into ranked findings + an action ledger.
        ▼
    HARD GATES in code (never prompt-mediated): operability + goals-of-care.

Everything here is self-contained: it imports only ``cases`` (the clean folder
loader) and ``config.get_client``. It does NOT touch stage2/, ingest/, or the
legacy orchestrator — those model a data format this project doesn't have.
"""
from __future__ import annotations

from .orchestrator import run_board
from .schema import (
    ActionItem,
    Claim,
    Conflict,
    Finding,
    PanelResult,
    SpecialistOpinion,
)

__all__ = [
    "run_board",
    "PanelResult",
    "SpecialistOpinion",
    "Finding",
    "Claim",
    "Conflict",
    "ActionItem",
]
