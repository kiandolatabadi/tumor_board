"""Goals-of-care precondition — evaluated BEFORE guidance, not labelled after it.

Sibling of the operability gate, and the same shape: a permissive outcome requires
a positive, checkable result; absence of evidence forces the conservative path.

    operability gate:  absence of a `cleared` result  ->  cannot present surgery as ready
    GOC precondition:  absence of a valid supportive-care record  ->  cannot skip guidance

Two rules carry the clinical weight here (both from the clinician review):

1. RECENCY IS EVENT-RELATIVE, not just calendar age. A goals-of-care conversation
   recorded BEFORE a major treatment event is stale no matter how recent the
   calendar says it is — the event is exactly what would change the answer.

2. SUPPRESSION REQUIRES AFFIRMATIVE EVIDENCE. Guidance may be skipped only on a
   positive, recent, event-valid record documenting supportive care. Missing or
   stale GOC never authorizes skipping — it is the *least* informed state, not a
   licence to act.

And the asymmetry that keeps inference safe: a grounded room signal may INVALIDATE
a documented record (raise the bar) but may never AUTHORIZE skipping (lower it).
Model output triggers conservative behaviour, never permissive behaviour.
"""
from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .agents.schema import Enrichment, InferenceKind
from .case_schema import TumorBoardCase

# ---------------------------------------------------------------------------
# BELONGS IN THE GUIDANCE PACK (clinical opinion, not mechanical fact).
# Per the Stage 2 / Stage 3 seam rule these are Stage 3's to own: the adapter
# emits dated events, guidance decides which ones invalidate a prior GOC record
# and how old is too old. They live here only until the pack exists.
# ---------------------------------------------------------------------------
MAX_GOC_AGE_DAYS = 180
INVALIDATING_EVENT_KINDS = {
    "surgery", "systemic", "radiation", "procedure", "progression", "diagnosis",
}

# Positive supportive-care intent. Deliberately narrow: this is the *authorizing*
# direction, so it must not fire on ambiguity.
_SUPPORTIVE = re.compile(
    r"\b(comfort[- ]focused|comfort care|supportive care only|supportive[- ]only|"
    r"hospice|palliative[- ]only|no further (?:active |disease[- ]directed )?treatment|"
    r"forgo(?:ing)? (?:further )?treatment|declines? further treatment)\b",
    re.I,
)
# A negation before the match flips the meaning ("not ready for hospice").
_NEGATED = re.compile(
    r"\b(not|no longer|never|declin\w+|against|rather than|instead of|isn'?t|aren'?t)\b[^.]{0,40}$",
    re.I,
)


class GocStatus(str, Enum):
    VALID_SUPPORTIVE_ONLY = "valid_supportive_only"          # the only skip-authorizing state
    VALID_ESCALATION_CONSISTENT = "valid_escalation_consistent"
    STALE_BY_AGE = "stale_by_age"
    INVALIDATED_BY_EVENT = "invalidated_by_event"             # recorded before a major event
    TIMELINE_INCOMPLETE = "timeline_incomplete"               # undated events — recency unprovable
    CONTRADICTED_BY_ROOM = "contradicted_by_room"             # live discussion supersedes the chart
    ABSENT = "absent"


class CareScope(str, Enum):
    """What remains in scope after the precondition. A supportive-care record
    narrows the scope; it does not empty it — symptom-directed options (palliative
    radiotherapy for pain, and so on) stay appropriate."""
    all_options = "all_options"
    symptom_directed_only = "symptom_directed_only"


class MajorEvent(BaseModel):
    kind: str
    name: Optional[str] = None
    date: Optional[str] = Field(None, description="None when the source carried no usable date.")

    @property
    def dated(self) -> bool:
        return _parse_date(self.date) is not None


class GocEvaluation(BaseModel):
    """The precondition result. `authorizes_skip` is the only field the pipeline
    branches on, and it is True in exactly one status."""
    status: GocStatus
    authorizes_skip: bool = False
    documented_date: Optional[str] = None
    age_days: Optional[int] = None
    reference_date: Optional[str] = Field(None, description="Date the age was measured against (board date).")
    invalidating_event: Optional[MajorEvent] = None
    room_signal_quote: Optional[str] = Field(None, description="Grounded transcript quote that superseded the chart.")
    summary: Optional[str] = None
    disclosure: str = Field(..., description="Human-readable statement of the decision. Always shown — a skip is never silent.")
    revisit_recommended: bool = False


def _parse_date(s: Optional[str]) -> Optional[date]:
    """Tolerant ISO parse. Accepts 'YYYY-MM-DD', 'YYYY-MM', 'YYYY'."""
    if not s:
        return None
    text = str(s).strip()[:10]
    for fmt in (text, f"{text}-01", f"{text}-01-01"):
        try:
            return date.fromisoformat(fmt)
        except ValueError:
            continue
    return None


def major_events(case: TumorBoardCase) -> list[MajorEvent]:
    """Mechanical: every dated clinical event that could change a care decision.
    No judgement about which ones matter — that is INVALIDATING_EVENT_KINDS' job."""
    events: list[MajorEvent] = []
    if case.diagnosis and case.diagnosis.diagnosis_date:
        events.append(MajorEvent(kind="diagnosis", name=case.diagnosis.primary_site, date=case.diagnosis.diagnosis_date))
    for t in case.prior_treatments:
        if t.date:
            kind = (t.kind or "procedure").lower()
            events.append(MajorEvent(kind=kind, name=t.name, date=t.date))
            # A recorded progression is itself an inflection point.
            if t.response and re.search(r"progress\w*|relapse\w*|recurr\w*", t.response, re.I):
                events.append(MajorEvent(kind="progression", name=f"{t.name}: {t.response}", date=t.date))
    return [e for e in events if _parse_date(e.date)]


def _reference_date(case: TumorBoardCase, events: list[MajorEvent]) -> Optional[date]:
    """Measure age against the board date. Falls back to the latest known date in
    the case — never the wall clock, so evaluation stays deterministic."""
    board = _parse_date(case.board_date)
    if board:
        return board
    candidates = [d for d in (_parse_date(e.date) for e in events) if d]
    goc = _parse_date(case.goals_of_care.documented_date) if case.goals_of_care else None
    if goc:
        candidates.append(goc)
    return max(candidates) if candidates else None


def _is_supportive_only(text: str) -> bool:
    """Positive supportive-care intent, with a negation guard. Conservative by
    construction: this is what licenses suppression."""
    for m in _SUPPORTIVE.finditer(text or ""):
        if not _NEGATED.search(text[: m.start()]):
            return True
    return False


def _room_goc_signal(enrichment: Optional[Enrichment]) -> Optional[str]:
    """A GROUNDED goals-of-care inference means the room is discussing goals now,
    so the chart is under live revision and cannot be relied on to skip guidance.
    Returns the supporting quote. Never authorizes — only invalidates."""
    if not enrichment:
        return None
    for obs in enrichment.inferred:
        if obs.kind == InferenceKind.goals_of_care and obs.source.grounded:
            return obs.source.quote
    return None


def evaluate_goc(
    case: TumorBoardCase,
    enrichment: Optional[Enrichment] = None,
    max_age_days: int = MAX_GOC_AGE_DAYS,
) -> GocEvaluation:
    """Evaluate the goals-of-care precondition. Called BEFORE the guidance join."""
    events = major_events(case)
    ref = _reference_date(case, events)
    goc = case.goals_of_care
    goc_date = _parse_date(goc.documented_date) if goc else None
    summary = " ".join(filter(None, [(goc.summary if goc else None), (goc.status if goc else None)]))

    # --- absent -------------------------------------------------------------
    if not goc or not (goc.summary or goc.status):
        return GocEvaluation(
            status=GocStatus.ABSENT,
            authorizes_skip=False,
            reference_date=ref.isoformat() if ref else None,
            revisit_recommended=True,
            disclosure=(
                "No goals-of-care conversation is documented. Guidance was NOT skipped — "
                "absent goals of care is the least-informed state, not a reason to withhold options."
            ),
        )

    age_days = (ref - goc_date).days if (ref and goc_date) else None

    # --- superseded by the room (asymmetric: invalidates, never authorizes) ---
    quote = _room_goc_signal(enrichment)
    if quote:
        return GocEvaluation(
            status=GocStatus.CONTRADICTED_BY_ROOM,
            authorizes_skip=False,
            documented_date=goc.documented_date, age_days=age_days,
            reference_date=ref.isoformat() if ref else None,
            room_signal_quote=quote, summary=summary, revisit_recommended=True,
            disclosure=(
                "Goals of care are being discussed in this meeting, so the documented record is "
                f"under live revision and was not relied on. Room signal: \"{quote}\""
            ),
        )

    # --- event-relative recency (rule 1) -------------------------------------
    invalidating = None
    if goc_date:
        for e in events:
            ed = _parse_date(e.date)
            if ed and ed > goc_date and e.kind in INVALIDATING_EVENT_KINDS:
                if invalidating is None or ed > _parse_date(invalidating.date):
                    invalidating = e
    if invalidating:
        return GocEvaluation(
            status=GocStatus.INVALIDATED_BY_EVENT,
            authorizes_skip=False,
            documented_date=goc.documented_date, age_days=age_days,
            reference_date=ref.isoformat() if ref else None,
            invalidating_event=invalidating, summary=summary, revisit_recommended=True,
            disclosure=(
                f"Documented goals of care ({goc.documented_date}) predate a major treatment event "
                f"({invalidating.kind}: {invalidating.name}, {invalidating.date}) and were not relied on. "
                "Goals of care should be revisited before treatment decisions."
            ),
        )

    # --- calendar recency ----------------------------------------------------
    if goc_date is None or age_days is None or age_days > max_age_days:
        return GocEvaluation(
            status=GocStatus.STALE_BY_AGE,
            authorizes_skip=False,
            documented_date=goc.documented_date, age_days=age_days,
            reference_date=ref.isoformat() if ref else None,
            summary=summary, revisit_recommended=True,
            disclosure=(
                f"Documented goals of care are undated or older than {max_age_days} days"
                + (f" ({age_days} days)" if age_days is not None else "")
                + " and were not relied on. Goals of care should be revisited."
            ),
        )

    # --- valid, and recent -> the one authorizing branch ---------------------
    if _is_supportive_only(summary):
        return GocEvaluation(
            status=GocStatus.VALID_SUPPORTIVE_ONLY,
            authorizes_skip=True,
            documented_date=goc.documented_date, age_days=age_days,
            reference_date=ref.isoformat() if ref else None,
            summary=summary,
            disclosure=(
                f"Guidance and trial matching were NOT surfaced. Goals of care documented "
                f"{goc.documented_date} ({age_days} days ago, with no major treatment event since) "
                f"record supportive care only: \"{summary.strip()}\""
            ),
        )

    return GocEvaluation(
        status=GocStatus.VALID_ESCALATION_CONSISTENT,
        authorizes_skip=False,
        documented_date=goc.documented_date, age_days=age_days,
        reference_date=ref.isoformat() if ref else None,
        summary=summary,
        disclosure=(
            f"Goals of care documented {goc.documented_date} ({age_days} days ago) are current and do "
            "not restrict disease-directed options; guidance proceeded normally."
        ),
    )
