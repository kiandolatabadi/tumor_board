"""Goals-of-care precondition.

The asymmetry under test throughout: only a positive, recent, event-valid
supportive-care record authorizes skipping guidance. Every other state — absent,
stale, invalidated by a later treatment event, or superseded by live discussion —
must NOT authorize a skip. Absence of evidence is never a licence to act.
"""
from __future__ import annotations

from app.agents.schema import Enrichment, InferenceKind, InferredObservation, SourceRef
from app.case_schema import (CareDomain, Diagnosis, GoalsOfCare, PriorTreatment, ScopeSource,
                             TumorBoardCase, derive_care_domains)
from app.goc import (INVALIDATING_EVENT_KINDS, CareScope, GocStatus, covers_domain, evaluate_goc,
                     major_events)
from app.treatment_kinds import TreatmentKind, classify_treatment_kind


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


def test_major_events_are_mechanical_and_keep_undated_entries():
    """Events are derived mechanically, and undated ones are KEPT — see
    test_undated_invalidating_event_blocks_skip_and_is_reported for why."""
    case = _case(treatments=[
        PriorTreatment(name="lobectomy", kind="surgery", date="2026-06-20"),
        PriorTreatment(name="undated", kind="systemic", date=None),
    ])
    events = major_events(case)
    kinds = {e.kind for e in events}
    assert "surgery" in kinds and "diagnosis" in kinds
    assert {e.name for e in events} >= {"lobectomy", "undated"}
    assert [e.dated for e in events].count(False) == 1


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


# --- the skip narrows scope, it does not empty it ----------------------------

def test_supportive_only_narrows_scope_to_symptom_directed():
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."))
    ev = evaluate_goc(case)
    assert ev.permitted_scope is CareScope.symptom_directed_only
    assert "symptom-directed" in ev.disclosure.lower()


def test_non_skip_paths_keep_full_scope():
    for goc in (None, GoalsOfCare(documented_date="2026-06-02", summary="Pursue all treatment options.")):
        assert evaluate_goc(_case(goc)).permitted_scope is CareScope.all_options


def test_skip_result_still_flags_symptom_directed_review():
    from app.orchestrator import goc_skip_result
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."))
    result = goc_skip_result(evaluate_goc(case), None)
    assert any("symptom-directed" in a.action.lower() for a in result.action_ledger)


# --- undated events are surfaced, never silently dropped ---------------------

def test_undated_invalidating_event_blocks_skip_and_is_reported():
    """The dangerous case: an undated surgery might postdate the GOC record. We
    cannot prove recency, so we must not skip — and must say why."""
    case = _case(
        GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."),
        treatments=[PriorTreatment(name="lobectomy", kind="surgery", date=None)],
    )
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.TIMELINE_INCOMPLETE
    assert ev.authorizes_skip is False
    assert ev.timeline_complete is False
    assert ev.undated_events and ev.undated_events[0].name == "lobectomy"
    assert "lobectomy" in ev.data_gap_note


def test_undated_events_are_retained_by_major_events():
    """Regression: dropping undated events hid exactly the ones that matter."""
    case = _case(treatments=[PriorTreatment(name="undated surgery", kind="surgery", date=None)])
    names = {e.name for e in major_events(case)}
    assert "undated surgery" in names
    assert any(not e.dated for e in major_events(case))


def test_dated_events_still_report_a_complete_timeline():
    case = _case(
        GoalsOfCare(documented_date="2026-07-01", summary="Comfort-focused care only."),
        treatments=[PriorTreatment(name="lobectomy", kind="surgery", date="2026-06-20")],
    )
    ev = evaluate_goc(case)
    assert ev.timeline_complete is True
    assert ev.data_gap_note is None
    assert ev.authorizes_skip is True


def test_data_gap_is_surfaced_even_when_goc_is_absent():
    """A provider should learn the timeline is partial regardless of GOC state."""
    case = _case(None, treatments=[PriorTreatment(name="lobectomy", kind="surgery", date=None)])
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.ABSENT
    assert ev.timeline_complete is False and ev.data_gap_note


# --- GOC scope: "or doesn't cover this scenario" ------------------------------

def test_resuscitation_only_record_cannot_suppress_disease_directed_guidance():
    """The README's scope-mismatch case: a DNR conversation says nothing about
    whether to pursue a trial, so it must not withhold guidance."""
    case = _case(GoalsOfCare(
        documented_date="2026-06-02",
        summary="Code status discussed: DNR/DNI. Comfort-focused if arrest occurs.",
        covers=[CareDomain.resuscitation],
        scope_source=ScopeSource.derived_from_text,
    ))
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.SCOPE_MISMATCH
    assert ev.authorizes_skip is False
    assert "resuscitation" in ev.disclosure
    assert ev.revisit_recommended is True


def test_record_covering_a_disease_directed_domain_still_authorizes_skip():
    case = _case(GoalsOfCare(
        documented_date="2026-06-02",
        summary="Declines further chemotherapy; comfort care only.",
        covers=[CareDomain.systemic_therapy, CareDomain.symptom_management],
        scope_source=ScopeSource.derived_from_text,
    ))
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.VALID_SUPPORTIVE_ONLY
    assert ev.authorizes_skip is True


def test_unknown_scope_falls_through_rather_than_blocking():
    """Unrecorded scope is not a mismatch: a bare 'supportive care only' is a
    global statement. Preserves behaviour for sources that carry no scope."""
    case = _case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."))
    ev = evaluate_goc(case)
    assert ev.scope_source is ScopeSource.absent
    assert ev.authorizes_skip is True


def test_scope_is_carried_on_every_branch_for_stage_3():
    for goc in (
        GoalsOfCare(documented_date="2026-06-02", summary="Pursue all options.",
                    covers=[CareDomain.systemic_therapy], scope_source=ScopeSource.coded),
        GoalsOfCare(documented_date="2025-02-01", summary="Comfort care only.",
                    covers=[CareDomain.hospice_referral], scope_source=ScopeSource.coded),
    ):
        ev = evaluate_goc(_case(goc))
        assert ev.documented_scope == goc.covers
        assert ev.scope_source is ScopeSource.coded


def test_covers_domain_distinguishes_unknown_from_false():
    known = evaluate_goc(_case(GoalsOfCare(
        documented_date="2026-06-02", summary="Declines further chemotherapy; comfort care only.",
        covers=[CareDomain.systemic_therapy], scope_source=ScopeSource.coded)))
    assert covers_domain(known, CareDomain.systemic_therapy) is True
    assert covers_domain(known, CareDomain.surgery) is False

    unknown = evaluate_goc(_case(GoalsOfCare(documented_date="2026-06-02", summary="Comfort care only.")))
    assert covers_domain(unknown, CareDomain.surgery) is None  # unknown is not False


def test_derive_care_domains_is_deterministic_and_mechanical():
    assert derive_care_domains("Code status: DNR/DNI") == [CareDomain.resuscitation]
    assert set(derive_care_domains("declines further chemotherapy, wants hospice")) == {
        CareDomain.systemic_therapy, CareDomain.hospice_referral}
    assert derive_care_domains(None, "") == []


def test_negation_does_not_cross_a_clause_boundary():
    """"Declines further chemotherapy" negates chemotherapy, not the comfort-care
    statement in the next clause. Regression: the guard used to reach across ';'."""
    case = _case(GoalsOfCare(documented_date="2026-06-02",
                             summary="Declines further chemotherapy; comfort care only."))
    assert evaluate_goc(case).authorizes_skip is True
    # ...but a negation in the SAME clause still applies.
    same = _case(GoalsOfCare(documented_date="2026-06-02", summary="Not ready for comfort care."))
    assert evaluate_goc(same).authorizes_skip is False


def test_every_treatment_kind_invalidates_goals_of_care():
    """Drift guard. Closing PriorTreatment.kind into TreatmentKind removed the old
    catch-all "procedure"; a kind missing from INVALIDATING_EVENT_KINDS would
    silently stop invalidating a GOC record — a regression toward permissiveness."""
    missing = {k.value for k in TreatmentKind} - INVALIDATING_EVENT_KINDS
    assert not missing, f"TreatmentKind values not covered: {missing}"


def test_an_unclassifiable_treatment_still_invalidates():
    """A procedure whose name matches no keyword classifies as `other` — still a
    real clinical event, so it must still invalidate."""
    case = _case(
        GoalsOfCare(documented_date="2026-06-02", summary="Comfort-focused care only."),
        treatments=[PriorTreatment(name="unlisted intervention", kind=TreatmentKind.other, date="2026-06-20")],
    )
    ev = evaluate_goc(case)
    assert ev.status is GocStatus.INVALIDATED_BY_EVENT
    assert ev.authorizes_skip is False


def test_procedures_classify_instead_of_defaulting():
    assert classify_treatment_kind("Left upper lobectomy") is TreatmentKind.surgery
    assert classify_treatment_kind("carboplatin infusion") is TreatmentKind.systemic
    assert classify_treatment_kind("stereotactic radiotherapy") is TreatmentKind.radiation
    assert classify_treatment_kind("mystery intervention") is TreatmentKind.other
