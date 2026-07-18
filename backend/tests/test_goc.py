"""Goals-of-care precondition.

The asymmetry under test throughout: only a positive, recent, event-valid
supportive-care record authorizes skipping guidance. Every other state — absent,
stale, invalidated by a later treatment event, or superseded by live discussion —
must NOT authorize a skip. Absence of evidence is never a licence to act.
"""
from __future__ import annotations

from app.agents.schema import Enrichment, InferenceKind, InferredObservation, SourceRef
from app.case_schema import Diagnosis, GoalsOfCare, PriorTreatment, TumorBoardCase
from app.goc import GocStatus, evaluate_goc, major_events


def _case(goc: GoalsOfCare | None = None, treatments: list[PriorTreatment] | None = None,
          board_date: str = "2026-07-18") -> TumorBoardCase:
    return TumorBoardCase(
        board_date=board_date,
        diagnosis=Diagnosis(primary_site="lung", diagnosis_date="2025-01-10"),
        prior_treatments=treatments or [],
        goals_of_care=goc,
    )


def _goc_inference(quote: str, grounded: bool = True) -> Enrichment:
    return Enrichment(inferred=[
        InferredObservation(
            kind=InferenceKind.goals_of_care,
            summary="family raised goals of care",
            confidence=0.8,
            rationale="explicit statement in the room",
            source=SourceRef(location="transcript", quote=quote, grounded=grounded),
        )
    ])


# --- the one authorizing path ------------------------------------------------

def test_recent_supportive_only_authorizes_skip():
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care; hospice referral discussed."))
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.VALID_SUPPORTIVE_ONLY
    assert ev.authorizes_skip is True
    assert "not surfaced" in ev.disclosure.lower() or "not" in ev.disclosure.lower()
    assert ev.documented_date == "2026-06-02"


def test_skip_disclosure_names_the_record_and_age():
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="supportive care only"))
    ev = evaluate_goc(case)
    assert "2026-06-02" in ev.disclosure
    assert str(ev.age_days) in ev.disclosure  # a skip is never silent about its basis


# --- rule 1: recency is EVENT-relative --------------------------------------

def test_supportive_goc_before_a_later_treatment_event_does_not_authorize_skip():
    """Calendar-recent, but recorded BEFORE a major treatment event -> invalid."""
    case = _case(
        GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."),
        treatments=[PriorTreatment(name="lobectomy", kind="surgery", date="2026-06-20")],
    )
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.INVALIDATED_BY_EVENT
    assert ev.authorizes_skip is False
    assert ev.invalidating_event.kind == "surgery"
    assert ev.revisit_recommended is True


def test_supportive_goc_after_the_event_still_authorizes_skip():
    case = _case(
        GoalsOfCare(documented_date="2026-07-01", summary="Comfort-focused care only."),
        treatments=[PriorTreatment(name="lobectomy", kind="surgery", date="2026-06-20")],
    )
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.VALID_SUPPORTIVE_ONLY
    assert ev.authorizes_skip is True


def test_progression_response_is_itself_an_invalidating_event():
    case = _case(
        GoalsOfCare(documented_date="2026-06-02", summary="comfort care"),
        treatments=[PriorTreatment(name="carboplatin", kind="systemic", date="2026-06-15",
                                   response="progression on therapy")],
    )
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.INVALIDATED_BY_EVENT
    assert ev.authorizes_skip is False


def test_major_events_are_mechanical_and_dated():
    case = _case(treatments=[
        PriorTreatment(name="lobectomy", kind="surgery", date="2026-06-20"),
        PriorTreatment(name="undated", kind="systemic", date=None),
    ])
    kinds = {e.kind for e in major_events(case)}
    assert "surgery" in kinds and "diagnosis" in kinds
    assert all(e.date for e in major_events(case))  # undated events are dropped


# --- rule 2: suppression requires AFFIRMATIVE evidence -----------------------

def test_absent_goc_does_not_authorize_skip():
    ev = evaluate_goc(_case(None))
    assert ev.status is GocStatus.ABSENT
    assert ev.authorizes_skip is False
    assert ev.revisit_recommended is True


def test_stale_supportive_goc_does_not_authorize_skip():
    """Dated after the diagnosis (so not event-invalidated) but far past the age
    threshold — staleness alone must still block the skip."""
    case = _case(GoalsOfCare(documented_date="2025-02-01", summary="Comfort-focused care only."))
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.STALE_BY_AGE
    assert ev.authorizes_skip is False


def test_event_invalidation_takes_precedence_over_age():
    """A GOC recorded before the diagnosis is invalidated BY THE EVENT — the more
    specific and more actionable answer than 'stale by age'."""
    case = _case(GoalsOfCare(documented_date="2024-01-01", summary="Comfort-focused care only."))
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.INVALIDATED_BY_EVENT
    assert ev.invalidating_event.kind == "diagnosis"
    assert ev.authorizes_skip is False


def test_undated_supportive_goc_does_not_authorize_skip():
    case = _case(GoalsOfCare(documented_date=None, summary="Comfort-focused care only."))
    ev = evaluate_goc(case)
    assert ev.authorizes_skip is False


def test_recent_escalation_consistent_goc_proceeds_normally():
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Wishes to pursue all available treatment options."))
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.VALID_ESCALATION_CONSISTENT
    assert ev.authorizes_skip is False
    assert ev.revisit_recommended is False


def test_negated_supportive_language_does_not_authorize_skip():
    """'not ready for hospice' must not read as 'hospice'."""
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Patient is not ready for hospice at this time."))
    ev = evaluate_goc(case)
    assert ev.authorizes_skip is False


# --- the inference asymmetry -------------------------------------------------

def test_room_signal_invalidates_an_otherwise_valid_supportive_record():
    """An inference may RAISE the bar: live discussion supersedes the chart."""
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."))
    ev = evaluate_goc(case, _goc_inference("she's changed her mind about treatment"))
    assert ev.status is GocStatus.CONTRADICTED_BY_ROOM
    assert ev.authorizes_skip is False
    assert ev.room_signal_quote


def test_room_signal_alone_never_authorizes_skip():
    """An inference may never LOWER the bar: no coded record, room says comfort
    care -> still no skip. Model output triggers conservative behaviour only."""
    ev = evaluate_goc(_case(None), _goc_inference("she just wants to be comfortable now"))
    assert ev.authorizes_skip is False


def test_ungrounded_room_signal_is_ignored():
    """Only a VERIFIED quote counts as a room signal."""
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."))
    ev = evaluate_goc(case, _goc_inference("hearsay", grounded=False))
    assert ev.status is GocStatus.VALID_SUPPORTIVE_ONLY


# --- the skip path surfaces itself -------------------------------------------

def test_skip_result_surfaces_the_skip_and_carries_no_grade():
    from app.orchestrator import goc_skip_result
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."))
    ev = evaluate_goc(case)
    result = goc_skip_result(ev, None)
    assert len(result.findings) == 1
    assert result.findings[0].recommendation_grade is None  # no rule matched — nothing to copy
    assert result.findings[0].source_agent == "goals_of_care_precondition"
    assert result.goc.status is GocStatus.VALID_SUPPORTIVE_ONLY
    assert result.action_ledger  # confirming the record stays a human to-do
