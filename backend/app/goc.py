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
from .case_schema import CareDomain, ScopeSource, TumorBoardCase
from .treatment_kinds import TreatmentKind

# ---------------------------------------------------------------------------
# BELONGS IN THE GUIDANCE PACK (clinical opinion, not mechanical fact).
# Per the Stage 2 / Stage 3 seam rule these are Stage 3's to own: the adapter
# emits dated events, guidance decides which ones invalidate a prior GOC record
# and how old is too old. They live here only until the pack exists.
# ---------------------------------------------------------------------------
MAX_GOC_AGE_DAYS = 180
# MUST cover every TreatmentKind value plus the derived kinds. A kind missing
# here silently stops invalidating goals of care — a safety regression in the
# permissive direction — so test_goc.py asserts full coverage rather than trusting
# this list to be maintained by hand.
INVALIDATING_EVENT_KINDS = {k.value for k in TreatmentKind} | {"progression", "diagnosis"}
# Which domains a record must speak to before it can suppress disease-directed
# guidance. A resuscitation-only conversation ("DNR") says nothing about whether
# to pursue a trial — the README's "doesn't cover this scenario" case.
DISEASE_DIRECTED_DOMAINS = {
    CareDomain.systemic_therapy, CareDomain.surgery,
    CareDomain.radiation, CareDomain.clinical_trials,
}

# Positive supportive-care intent. Deliberately narrow: this is the *authorizing*
# direction, so it must not fire on ambiguity.
_SUPPORTIVE = re.compile(
    r"\b(comfort[- ]focused|comfort care|supportive care only|supportive[- ]only|"
    r"hospice|palliative[- ]only|no further (?:active |disease[- ]directed )?treatment|"
    r"forgo(?:ing)? (?:further )?treatment|declines? further treatment)\b",
    re.I,
)
# A negation before the match flips the meaning ("not ready for hospice"). The
# window stops at clause boundaries (. ; ,) because a negation in a PRECEDING
# clause negates that clause, not this one: in "Declines further chemotherapy;
# comfort care only" the "declines" governs chemotherapy, and letting it reach
# across the semicolon would cancel the supportive-care statement that follows.
_NEGATED = re.compile(
    r"\b(not|no longer|never|declin\w+|against|rather than|instead of|isn'?t|aren'?t)\b[^.;,]{0,25}$",
    re.I,
)


class GocStatus(str, Enum):
    VALID_SUPPORTIVE_ONLY = "valid_supportive_only"          # the only skip-authorizing state
    VALID_ESCALATION_CONSISTENT = "valid_escalation_consistent"
    STALE_BY_AGE = "stale_by_age"
    INVALIDATED_BY_EVENT = "invalidated_by_event"             # recorded before a major event
    TIMELINE_INCOMPLETE = "timeline_incomplete"               # undated events — recency unprovable
    CONTRADICTED_BY_ROOM = "contradicted_by_room"             # live discussion supersedes the chart
    SCOPE_MISMATCH = "scope_mismatch"                         # recorded, but not about this question
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
    permitted_scope: CareScope = CareScope.all_options
    documented_date: Optional[str] = None
    age_days: Optional[int] = None
    reference_date: Optional[str] = Field(None, description="Date the age was measured against (board date).")
    invalidating_event: Optional[MajorEvent] = None
    room_signal_quote: Optional[str] = Field(None, description="Grounded transcript quote that superseded the chart.")
    summary: Optional[str] = None
    disclosure: str = Field(..., description="Human-readable statement of the decision. Always shown — a skip is never silent.")
    revisit_recommended: bool = False
    # Data-quality surface. Undated events are REPORTED, never dropped: an event we
    # cannot place in time is exactly the one that might invalidate this record.
    undated_events: list[MajorEvent] = Field(default_factory=list)
    timeline_complete: bool = True
    data_gap_note: Optional[str] = Field(None, description="Shown to providers when the timeline is partial.")
    # What the conversation actually covered. Stage 3 uses this to check a specific
    # rule's domain against the record; `scope_source == absent` means unknown, not empty.
    documented_scope: list[CareDomain] = Field(default_factory=list)
    scope_source: ScopeSource = ScopeSource.absent


def covers_domain(ev: GocEvaluation, domain: CareDomain) -> Optional[bool]:
    """Does the documented conversation speak to `domain`? Returns None when the
    source recorded no scope — unknown is not False, and callers must not treat it
    as coverage. The deterministic primitive Stage 3 joins a rule's domain against."""
    if ev.scope_source is ScopeSource.absent or not ev.documented_scope:
        return None
    return domain in ev.documented_scope


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
    """Mechanical: every clinical event that could change a care decision, DATED OR
    NOT. No judgement about which ones matter — that is INVALIDATING_EVENT_KINDS'
    job.

    Undated events are deliberately retained. Dropping them would be a silent
    failure in the dangerous direction: an undated surgery that in fact postdates a
    goals-of-care record would vanish, and the record would look valid. Callers
    treat an undated invalidating event as *unprovable recency*, not as absence."""
    events: list[MajorEvent] = []
    if case.diagnosis and (case.diagnosis.diagnosis_date or case.diagnosis.primary_site):
        events.append(MajorEvent(kind="diagnosis", name=case.diagnosis.primary_site, date=case.diagnosis.diagnosis_date))
    for t in case.prior_treatments:
        kind = (t.kind or "procedure").lower()
        events.append(MajorEvent(kind=kind, name=t.name, date=t.date))
        # A recorded progression is itself an inflection point.
        if t.response and re.search(r"progress\w*|relapse\w*|recurr\w*", t.response, re.I):
            events.append(MajorEvent(kind="progression", name=f"{t.name}: {t.response}", date=t.date))
    return events


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

    # Undated events of an invalidating kind make recency UNPROVABLE. Surface them
    # to the provider rather than silently treating them as absent.
    undated = [e for e in events if not e.dated and e.kind in INVALIDATING_EVENT_KINDS]
    gap_note = None
    if undated:
        names = ", ".join(f"{e.kind}: {e.name}" for e in undated[:4])
        gap_note = (
            f"{len(undated)} clinical event(s) carry no usable date in the source record ({names}). "
            "Whether the documented goals of care predate them cannot be established from the data."
        )

    # --- absent -------------------------------------------------------------
    if not goc or not (goc.summary or goc.status):
        return GocEvaluation(
            status=GocStatus.ABSENT,
            authorizes_skip=False,
            reference_date=ref.isoformat() if ref else None,
            revisit_recommended=True,
            undated_events=undated, timeline_complete=not undated, data_gap_note=gap_note,
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
            documented_scope=goc.covers, scope_source=goc.scope_source,
            undated_events=undated, timeline_complete=not undated, data_gap_note=gap_note,
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
            documented_scope=goc.covers, scope_source=goc.scope_source,
            undated_events=undated, timeline_complete=not undated, data_gap_note=gap_note,
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
            documented_scope=goc.covers, scope_source=goc.scope_source,
            undated_events=undated, timeline_complete=not undated, data_gap_note=gap_note,
            disclosure=(
                f"Documented goals of care are undated or older than {max_age_days} days"
                + (f" ({age_days} days)" if age_days is not None else "")
                + " and were not relied on. Goals of care should be revisited."
            ),
        )

    # --- unprovable recency: undated events of an invalidating kind ----------
    # Reached only when the record is otherwise valid. We cannot show it postdates
    # these events, so it cannot authorize a skip — but the reason is a DATA GAP,
    # reported as such, not a clinical judgment about this patient.
    if undated:
        return GocEvaluation(
            status=GocStatus.TIMELINE_INCOMPLETE,
            authorizes_skip=False,
            documented_date=goc.documented_date, age_days=age_days,
            reference_date=ref.isoformat() if ref else None,
            summary=summary, revisit_recommended=True,
            documented_scope=goc.covers, scope_source=goc.scope_source,
            undated_events=undated, timeline_complete=False, data_gap_note=gap_note,
            disclosure=(
                f"Documented goals of care ({goc.documented_date}) could not be confirmed as current: "
                f"{gap_note} Guidance was not skipped. Confirm the source record's event dates."
            ),
        )

    # --- valid, and recent -> the one authorizing branch ---------------------
    if _is_supportive_only(summary):
        # Scope mismatch (rule: "or doesn't cover this scenario"). A record whose
        # recorded scope speaks only to, say, resuscitation cannot suppress
        # disease-directed guidance. Unknown scope is NOT a mismatch — it falls
        # through, because a bare "supportive care only" is a global statement.
        if goc.covers and not (set(goc.covers) & DISEASE_DIRECTED_DOMAINS):
            covered = ", ".join(d.value for d in goc.covers)
            return GocEvaluation(
                status=GocStatus.SCOPE_MISMATCH,
                authorizes_skip=False,
                documented_date=goc.documented_date, age_days=age_days,
                reference_date=ref.isoformat() if ref else None,
                summary=summary, revisit_recommended=True,
                documented_scope=goc.covers, scope_source=goc.scope_source,
                disclosure=(
                    f"Documented goals of care ({goc.documented_date}) address {covered} and do not "
                    "cover disease-directed treatment, so they were not used to withhold guidance. "
                    "Goals of care should be revisited for this decision."
                ),
            )
        return GocEvaluation(
            status=GocStatus.VALID_SUPPORTIVE_ONLY,
            authorizes_skip=True,
            permitted_scope=CareScope.symptom_directed_only,
            documented_date=goc.documented_date, age_days=age_days,
            reference_date=ref.isoformat() if ref else None,
            summary=summary, timeline_complete=True,
            documented_scope=goc.covers, scope_source=goc.scope_source,
            disclosure=(
                f"Disease-directed guidance and trial matching were NOT surfaced. Goals of care "
                f"documented {goc.documented_date} ({age_days} days ago, with no major treatment event "
                f"since) record supportive care only: \"{summary.strip()}\" "
                "Symptom-directed options (for example palliative radiotherapy for pain) remain in "
                "scope and are unaffected by this."
            ),
        )

    return GocEvaluation(
        status=GocStatus.VALID_ESCALATION_CONSISTENT,
        authorizes_skip=False,
        documented_scope=goc.covers, scope_source=goc.scope_source,
        documented_date=goc.documented_date, age_days=age_days,
        reference_date=ref.isoformat() if ref else None,
        summary=summary,
        disclosure=(
            f"Goals of care documented {goc.documented_date} ({age_days} days ago) are current and do "
            "not restrict disease-directed options; guidance proceeded normally."
        ),
    )
