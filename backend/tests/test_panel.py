"""Panel regression test — runs the REAL loop against a MOCK Claude client.

No network, no API key, no cost. Locks in the behaviour we hardened by hand:
the loop terminates and stays bounded, every stage's JSON validates, cross-
examination survives an out-of-vocabulary stance (the 'qualify' bug), and the
operability gate fires in code.
"""
from __future__ import annotations

import json

import app.panel.llm as llm

_ROUND1 = {
    "summary": "Round-1 opinion.",
    "confidence": 0.7,
    "findings": [{
        "issue": "Fertility preservation deferred and never revisited",
        "recommendation": "Offer oncofertility referral before gonadotoxic therapy",
        "recommendation_grade": "I/A", "match_confidence": 0.82,
        "evidence_ref": "oncology/consult_2024-02-10_initial_diagnosis.md",
        "rationale_status": "not_stated",
        "patient_facing_note": "Preserving fertility keeps the option of children later.",
        "live_question": "Was fertility preservation offered before this therapy?",
        "proposes_procedure": False,
        "transcript_ref": {"speaker": None, "quote": None, "absent": True},
    }],
    "claims": [{"about": "ribociclib", "stance": "recommend", "statement": "Start ribociclib"}],
    "needs": [],
}
# The cross-examined reply uses 'qualify' — the value that used to crash the run.
_CROSSEXAM = {
    "summary": "On review, I qualify my position given the cardiac history.",
    "confidence": 0.6, "findings": [],
    "claims": [{"about": "ribociclib", "stance": "qualify", "statement": "Only with QT monitoring"}],
    "needs": [],
}
_RECONCILE = {"conflicts": [{
    "kind": "contradiction", "topic": "ribociclib",
    "description": "Oncology recommends ribociclib; cardiology cautions on QT.",
    "specialists": ["oncology", "cardiology"],
}]}
_SYNTHESIS = {
    "findings": [
        {**_ROUND1["findings"][0], "source_specialist": "fertility"},
        {  # procedure proposed, no operability clearance -> gate must flag it
            "issue": "Liver metastasectomy floated without an operability assessment",
            "recommendation": "Proceed with resection of the two hepatic lesions",
            "recommendation_grade": "IIb/C", "match_confidence": 0.5,
            "evidence_ref": "tumor_board_transcript.md (surgeon)",
            "rationale_status": "not_stated",
            "patient_facing_note": "Removing the liver spots may be an option if you are fit enough.",
            "live_question": "Has fitness for liver surgery been assessed?",
            "source_specialist": "surgery", "proposes_procedure": True,
            "operability_status": "not_applicable",
            "transcript_ref": {"speaker": "SURGEON", "quote": "we could resect those", "absent": False},
        },
    ],
    "action_ledger": [{"action": "Refer to oncofertility", "owner": "ONCOLOGIST",
                       "deadline": None, "linked_finding": "Fertility preservation deferred and never revisited"}],
}


def _mk(text: str):
    block = type("B", (), {"type": "text", "text": text})()
    return type("Msg", (), {"stop_reason": "end_turn", "content": [block]})()


class _FakeClient:
    class messages:
        @staticmethod
        def create(**kw):
            system = kw.get("system")
            sys_text = system[0]["text"] if isinstance(system, list) else str(system)
            user = kw["messages"][0]["content"]
            if "decide which specialists" in sys_text:
                return _mk(json.dumps({"specialists": ["cardiology", "fertility"], "reason": "t"}))
            if "reconciling the specialists" in sys_text:
                return _mk(json.dumps(_RECONCILE))
            if "writing up the panel's conclusions" in sys_text:
                return _mk(json.dumps(_SYNTHESIS))
            if "one voice on a tumor-board" in sys_text:
                return _mk(json.dumps(_CROSSEXAM if "SECOND-OPINION REQUEST" in user else _ROUND1))
            return _mk("{}")


def test_panel_runs_bounded_and_gates(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: _FakeClient())
    from app.panel.orchestrator import run_board

    r = run_board("hero_breast_escalation")

    # bounded + terminates
    assert r.rounds == 2
    assert llm.calls_made() <= llm.PANEL_MAX_CALLS

    # always-on floor honoured, router additions included
    assert {"oncology", "pharmacy", "internal_medicine"}.issubset(r.specialists_consulted)
    assert len(r.specialists_consulted) == 5

    # cross-examination happened and the conflict is marked handled
    assert r.deliberation
    assert any(c.resolved for c in r.conflicts)

    # the 'qualify' stance was coerced, not crashed — every stance is valid
    stances = [c.stance for o in r.opinions for c in o.claims]
    assert all(s in {"recommend", "caution", "oppose", "defer"} for s in stances)
    assert "caution" in stances

    # operability gate fired in code
    op = next(f for f in r.findings if "metastasectomy" in f.issue.lower())
    assert op.operability_status == "not_confirmed"
    assert "operability not yet confirmed" in op.recommendation
