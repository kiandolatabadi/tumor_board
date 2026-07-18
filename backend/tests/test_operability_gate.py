"""The hard rule is enforced in code, so it must be testable without the API."""
import json

import pytest
from app.orchestrator import (OutputUnparseable, _parse, _unparseable_result,
                              gate_operability)
from app.schema import Finding, OperabilityStatus


def _finding(**over) -> Finding:
    base = dict(
        issue="x",
        evidence_ref="guidelines.json",
        recommendation="do the thing",
        match_confidence=0.5,
        patient_facing_note="note",
        live_question="q?",
        source_agent="check_guideline_coverage",
    )
    base.update(over)
    return Finding(**base)


def test_surgical_finding_without_operability_is_relabeled():
    f = _finding(issue="Lobectomy not offered", recommendation="Offer lobectomy")
    (gated,) = gate_operability([f])
    assert gated.operability_status == OperabilityStatus.not_confirmed
    assert "operability not yet confirmed" in gated.recommendation


def test_cleared_finding_stands_only_with_a_cleared_result():
    f = _finding(
        issue="Consider resection",
        recommendation="Proceed to surgery",
        operability_status=OperabilityStatus.cleared,
    )
    (gated,) = gate_operability([f], operability_results=[{"cleared": True}])
    assert gated.operability_status == OperabilityStatus.cleared
    assert "not yet confirmed" not in gated.recommendation


def test_declared_cleared_without_any_result_is_downgraded():
    """A model claiming 'cleared' with no backing operability result is not trusted."""
    f = _finding(issue="Consider resection", recommendation="Proceed to surgery",
                 operability_status=OperabilityStatus.cleared)
    (gated,) = gate_operability([f], operability_results=[])
    assert gated.operability_status == OperabilityStatus.not_confirmed


def test_blocking_result_overrides_declared_cleared():
    f = _finding(issue="Consider resection", recommendation="Proceed to surgery",
                 operability_status=OperabilityStatus.cleared)
    (gated,) = gate_operability([f], operability_results=[{"cleared": False}])
    assert gated.operability_status == OperabilityStatus.not_confirmed
    assert "operability not yet confirmed" in gated.recommendation


def test_non_surgical_finding_is_untouched():
    f = _finding(issue="EGFR trial not discussed", recommendation="Consider trial NCT04030000")
    (gated,) = gate_operability([f])
    assert gated.operability_status == OperabilityStatus.not_applicable


def test_finding_that_only_mentions_surgery_is_not_gated():
    """Regression: a documentation finding that mentions surgery/resection but
    does NOT propose a procedure must not be relabeled (the earlier false positive)."""
    f = _finding(
        issue="Radiotherapy chosen over surgery with no rationale stated",
        recommendation="Document explicit rationale for radiotherapy over resection",
    )
    (gated,) = gate_operability([f])
    assert gated.operability_status == OperabilityStatus.not_applicable
    assert "operability not yet confirmed" not in gated.recommendation


def test_declared_proposes_procedure_is_gated_even_without_keywords():
    """Primary path: the model's declared intent gates it regardless of wording."""
    f = _finding(issue="Definitive local therapy", recommendation="Take patient to the OR", proposes_procedure=True)
    (gated,) = gate_operability([f])
    assert gated.operability_status == OperabilityStatus.not_confirmed


# --- truncation: a partial run must never read as a complete one --------------

class _Blk:
    type = "text"
    def __init__(self, text): self.text = text


class _Resp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Blk(text)]
        self.stop_reason = stop_reason


def _finding_json(n: int) -> str:
    return json.dumps({
        "issue": f"issue {n}", "evidence_ref": f"ref{n}", "recommendation": f"rec {n}",
        "match_confidence": 0.5, "patient_facing_note": "note", "live_question": "q?",
        "source_agent": "check_guideline_coverage",
    })


def test_truncated_output_salvages_complete_findings():
    """Cut off mid-array: the three complete findings survive, the partial one is
    discarded, and the result is flagged truncated."""
    text = '{"findings": [' + ", ".join(_finding_json(i) for i in range(3)) + ', {"issue": "partial'
    result = _parse(_Resp(text))
    assert len(result.findings) == 3
    assert result.truncated is True
    assert [f.issue for f in result.findings] == ["issue 0", "issue 1", "issue 2"]


def test_wellformed_output_is_not_flagged_truncated():
    text = json.dumps({"findings": [json.loads(_finding_json(0))], "action_ledger": []})
    result = _parse(_Resp(text))
    assert result.truncated is False and len(result.findings) == 1


def test_unsalvageable_output_reports_failure_rather_than_empty():
    """The worst failure mode is a blank panel that reads as 'no gaps found'."""
    with pytest.raises(OutputUnparseable):
        _parse(_Resp("this is not json at all"))
    degraded = _unparseable_result("boom", "max_tokens")
    assert degraded.truncated is True
    assert "did not complete" in degraded.findings[0].issue
    assert "NOT the same as" in degraded.findings[0].recommendation