"""Core data contracts.

The finding schema deliberately keeps its signals SEPARATE — never collapse
``recommendation_grade`` (how strong is the evidence) and ``match_confidence``
(did we apply it to the right patient) into a single score. See README §5.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .agents.schema import Enrichment
from .goc import GocEvaluation


class RationaleStatus(str, Enum):
    stated = "stated"
    not_stated = "not_stated"


class OperabilityStatus(str, Enum):
    # Surgical / invasive options must carry one of these. ``not_applicable``
    # is for non-procedural findings; ``cleared`` / ``not_confirmed`` come from
    # the check_operability tool. A surgical finding may NEVER be ``not_applicable``.
    not_applicable = "not_applicable"
    cleared = "cleared"
    not_confirmed = "not_confirmed"


class TranscriptRef(BaseModel):
    """Links a finding back to the moment (or absence) in the transcript."""
    line: Optional[int] = Field(None, description="0-based transcript line index, or null if the gap is an *absence*.")
    timestamp: Optional[str] = Field(None, description="e.g. '00:14:32' if available.")
    speaker: Optional[str] = None
    quote: Optional[str] = None


class Finding(BaseModel):
    issue: str = Field(..., description="What the room missed or under-addressed.")
    evidence_ref: str = Field(..., description="Which lookup/source backs this — e.g. a trial NCT id or interaction-table row. No source, no finding.")
    recommendation: str
    # Real dual-axis clinical grade: Class of Recommendation (I–IV) / Level of Evidence (A–C), e.g. "IIa/B".
    recommendation_grade: Optional[str] = Field(None, description="Class-of-Recommendation / Level-of-Evidence pair, e.g. 'IIa/B'.")
    # The agent's OWN certainty it matched the right evidence to THIS patient. Orthogonal to the grade.
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    rationale_status: RationaleStatus = RationaleStatus.not_stated
    patient_facing_note: str = Field(..., description="Plain language, WITH real numbers, for the 'to be addressed with the patient' layer.")
    live_question: str = Field(..., description="One directly-answerable question to surface live.")
    source_agent: str = Field(..., description="Which sub-check produced this (tool name).")
    proposes_procedure: bool = Field(
        False,
        description="True only if this finding PROPOSES performing a surgical/invasive procedure "
        "(not merely mentioning one). Drives the operability gate.",
    )
    operability_status: OperabilityStatus = OperabilityStatus.not_applicable
    transcript_ref: Optional[TranscriptRef] = None


class ActionItem(BaseModel):
    """End-of-meeting ledger row — a human to-do, structurally distinct from a Finding."""
    action: str
    owner: str
    deadline: Optional[str] = None
    linked_finding: Optional[str] = Field(None, description="issue text of the related Finding, if any.")


class AnalysisResult(BaseModel):
    findings: list[Finding]
    action_ledger: list[ActionItem]
    # Distinct section — inferred, source-cited nuance, kept separate from the
    # grounded findings above. Empty (with a skipped_reason) if the agent didn't run.
    enrichment: Enrichment = Field(default_factory=Enrichment)
    # Tools an inference deterministically triggered (raises_check), with results —
    # these gate the findings above. See orchestrator.run_triggered_checks.
    triggered_checks: list[dict] = Field(default_factory=list)
    # The goals-of-care precondition, evaluated BEFORE guidance. Always populated —
    # when it authorized a skip, `goc.disclosure` is the reason, and a skip is never
    # silent. See goc.evaluate_goc.
    goc: Optional[GocEvaluation] = None
    # True when the model's output was cut off and only complete findings were
    # recovered. Surfaced so a partial run never reads as a complete one.
    truncated: bool = False


class AnalyzeRequest(BaseModel):
    """A full source record (FHIR-envelope shape). If omitted, the API falls
    back to the bundled synthetic case."""
    record: Optional[dict] = None
