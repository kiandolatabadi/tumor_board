"""Data contracts for the panel.

Two signals are kept deliberately SEPARATE and must never be collapsed into one
number (README §5):

- ``recommendation_grade`` — how strong is the evidence itself (Class of
  Recommendation I–IV / Level of Evidence A–C, e.g. "IIa/B").
- ``match_confidence`` — the panel's own certainty it applied that evidence to
  *this* patient (right biomarker, right staging, complete data), 0–1.

These models are self-contained — no FHIR, no legacy imports.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

OperabilityStatus = Literal["not_applicable", "cleared", "not_confirmed"]
RationaleStatus = Literal["stated", "not_stated"]


class TranscriptRef(BaseModel):
    """Links a finding to the moment — or the *absence* — in the board discussion."""
    speaker: Optional[str] = None
    quote: Optional[str] = Field(None, description="Verbatim line the finding relates to.")
    absent: bool = Field(
        False,
        description="True when the finding is an ABSENCE — the room never raised it.",
    )


class Finding(BaseModel):
    """One gap the room did not (adequately) address."""
    issue: str = Field(..., description="What the room missed or under-addressed.")
    recommendation: str = Field(..., description="What to do about it — never the clinical call itself.")
    recommendation_grade: Optional[str] = Field(
        None, description="Class-of-Recommendation / Level-of-Evidence, e.g. 'IIa/B'. Null if no graded guideline applies."
    )
    match_confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="The panel's certainty this evidence fits THIS patient. Orthogonal to the grade.",
    )
    evidence_ref: str = Field(
        ..., description="Which chart document or transcript quote backs this. No source, no finding.",
    )
    rationale_status: RationaleStatus = Field(
        "not_stated", description="Did the room give an explicit reason for the related choice?",
    )
    patient_facing_note: str = Field(
        ..., description="Plain-language translation, with real numbers, for the 'discuss with the patient' layer.",
    )
    live_question: str = Field(..., description="One directly-answerable question to surface live in the room.")
    source_specialist: str = Field(..., description="Which specialist produced this finding.")
    proposes_procedure: bool = Field(
        False,
        description="True ONLY if this finding proposes PERFORMING a surgical/invasive procedure "
        "(not merely mentioning one). Drives the operability gate.",
    )
    operability_status: OperabilityStatus = "not_applicable"
    transcript_ref: Optional[TranscriptRef] = None


class Claim(BaseModel):
    """A position a specialist takes that another specialist might contradict.

    Claims are what the reconciliation pass compares across specialists to detect
    contradictions — they are the debate surface, kept apart from findings."""
    about: str = Field(..., description="Short topic tag, e.g. 'ribociclib' or 'liver metastasectomy'.")
    stance: Literal["recommend", "caution", "oppose", "defer"] = Field(
        ..., description="This specialist's stance on the topic.",
    )
    statement: str = Field(..., description="One sentence stating the position.")


class SpecialistOpinion(BaseModel):
    """One specialist's contribution to the board."""
    specialist: str
    title: str = Field(..., description="Human label, e.g. 'Medical Oncology'.")
    summary: str = Field(..., description="Two–three sentences: what this specialist sees in this case.")
    findings: list[Finding] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    needs: list[str] = Field(
        default_factory=list,
        description="Open questions this specialist needs another specialist to answer.",
    )
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Overall confidence in this read.")


class Conflict(BaseModel):
    """A tension the reconciliation pass found between specialists."""
    kind: Literal["contradiction", "dependency"]
    topic: str = Field(..., description="What the tension is about.")
    description: str
    specialists: list[str] = Field(..., description="Specialists on the two sides of the tension.")
    resolved: bool = False
    resolution: Optional[str] = Field(None, description="How cross-examination settled it, if it did.")


class DeliberationEntry(BaseModel):
    """One brokered exchange in the cross-examination log — the auditable rationale trail."""
    round: int
    topic: str
    prompt_to: str = Field(..., description="Specialist asked to respond.")
    opposing_claim: str
    response: str


class ActionItem(BaseModel):
    """End-of-meeting ledger row — a human to-do, structurally distinct from a Finding."""
    action: str
    owner: str = Field(..., description="Role that owns it, e.g. 'ONCOLOGIST', 'NURSE_COORDINATOR'.")
    deadline: Optional[str] = None
    linked_finding: Optional[str] = Field(None, description="issue text of the related Finding, if any.")


class PanelResult(BaseModel):
    """The full board output."""
    case_id: str
    specialists_consulted: list[str]
    findings: list[Finding] = Field(default_factory=list)
    action_ledger: list[ActionItem] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    deliberation: list[DeliberationEntry] = Field(default_factory=list)
    rounds: int = Field(1, description="How many deliberation rounds ran (1 = parallel pass only).")
    opinions: list[SpecialistOpinion] = Field(
        default_factory=list, description="Raw per-specialist opinions, kept for transparency.",
    )
    truncated: bool = Field(False, description="True if any model output was cut off / unparseable.")
