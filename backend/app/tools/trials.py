"""search_trials — backed by the repo-root trials agent.

The tool builds a top-level ``features`` override from the inputs the orchestrator
passes and runs the real agent (deterministic binary criteria -> one bounded LLM
call for free-text criteria -> per-trial verdict in code). Each per-trial finding
is mapped into the same issue/recommendation vocabulary the other tools use, with
the verdict and decisive criteria folded into the text — and the richer agent
fields (verdict, criteria_*, recruitment_status, live_question) kept alongside.

could_enter / possible_with_more_info items are NOT filtered out; a trial the
patient could enter that the room never discussed is exactly the gap we surface.
On ANY error it falls back to the canned trials.json table — logged loudly.
"""
from __future__ import annotations

import logging

from ._data import load

log = logging.getLogger(__name__)

SCHEMA = {
    "name": "search_trials",
    "description": (
        "Screen the patient against the trial list by cancer type, stage, and biomarkers. "
        "Returns a per-trial verdict (could_enter / possible_with_more_info / cannot_enter) "
        "naming the decisive criteria, plus recruitment status and site feasibility. Prefer "
        "trials that are OPEN and reachable; a molecularly-perfect but closed/far trial is not "
        "a useful match."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "biomarkers": {"type": "array", "items": {"type": "string"}},
            "cancer_type": {"type": "string"},
            "stage": {"type": "string"},
        },
        "required": ["biomarkers", "cancer_type"],
    },
}

# verdict -> the gap/addressed/uncertain vocabulary the other findings speak.
_STATUS_BY_VERDICT = {
    "could_enter": "gap",                 # an eligible trial the room may not have discussed
    "possible_with_more_info": "uncertain",
    "cannot_enter": "addressed",          # kept so the model sees *why* it isn't a match
}


def _features(cancer_type: str, biomarkers: list[str] | None, stage: str | None) -> dict:
    """Map the tool inputs to the matcher's top-level ``features`` override."""
    marks = list(biomarkers or [])
    features: dict = {
        "cancer": [cancer_type] if cancer_type else [],
        "biomarkers_present": marks,
        # Present-but-unvalued: trial criteria needing a specific status stay UNKNOWN
        # (honest) rather than being guessed at.
        "biomarker_status": {m.strip().lower(): "" for m in marks if str(m).strip()},
    }
    if stage:
        features["stage"] = [stage]
    return features


def _to_finding(t: dict) -> dict:
    """Fold one trial-agent verdict into the shared finding vocabulary."""
    verdict = t.get("verdict", "possible_with_more_info")
    tid = t.get("trial_id", "")
    title = t.get("title", tid or "trial")
    rec_status = t.get("recruitment_status", "unknown")
    met = t.get("criteria_met", [])
    blocking = t.get("criteria_blocking", [])
    missing = t.get("criteria_missing_info", [])

    if verdict == "could_enter":
        issue = f"Potentially eligible trial not confirmed as discussed: {title} ({tid})."
        recommendation = (
            f"Consider enrollment in {title} — patient meets: "
            f"{'; '.join(met) or 'the trial criteria'}."
        )
    elif verdict == "cannot_enter":
        issue = f"Trial screened out: {title} ({tid})."
        recommendation = (
            f"Not eligible for {title} — blocked by: "
            f"{'; '.join(blocking) or 'a disqualifying criterion'}."
        )
    else:  # possible_with_more_info
        issue = f"Trial eligibility undetermined pending data: {title} ({tid})."
        recommendation = (
            f"To assess eligibility for {title}, obtain: "
            f"{'; '.join(missing) or 'the missing information'}."
        )

    return {
        "issue": issue,
        "recommendation": recommendation,
        "evidence_ref": f"trial:{tid} (recruitment: {rec_status})",
        "recommendation_grade": None,  # trials carry a verdict, not a CoR/LoE grade
        "match_confidence": t.get("match_confidence"),
        "confidence_rationale": t.get("confidence_rationale"),
        "patient_facing_note": t.get("patient_facing_note"),
        "live_question": t.get("live_question"),
        "source_agent": t.get("source_agent", "trials_agent"),
        "status": _STATUS_BY_VERDICT.get(verdict, "uncertain"),
        # Richer agent fields kept intact so the orchestrator can reason over them.
        "verdict": verdict,
        "recruitment_status": rec_status,
        "criteria_met": met,
        "criteria_blocking": blocking,
        "criteria_missing_info": missing,
        "trial_id": tid,
        "title": title,
    }


def _canned(biomarkers: list[str], cancer_type: str, stage: str | None = None) -> dict:
    """The original canned-table behavior — the bail-out."""
    trials = load("trials.json")
    wanted = {b.strip().lower() for b in biomarkers}
    matches = []
    for t in trials:
        if cancer_type.lower() not in t["cancer_type"].lower():
            continue
        criteria = t["inclusion_criteria"]
        met = [c for c in criteria if c["biomarker"].lower() in wanted or c.get("always_met")]
        missing = [c for c in criteria if c not in met]
        matches.append(
            {
                "nct_id": t["nct_id"],
                "title": t["title"],
                "criteria_met": f"{len(met)}/{len(criteria)}",
                "missing_criteria": [c["label"] for c in missing],
                "recruitment_status": t["recruitment_status"],
                "site_distance_miles": t["site_distance_miles"],
                "reported_benefit": t.get("reported_benefit"),
            }
        )
    return {"matches": matches, "source": "trials.json (canned fallback)"}


def run(biomarkers: list[str], cancer_type: str, stage: str | None = None) -> dict:
    try:
        from agents.trials import search_trials

        patient = {"features": _features(cancer_type, biomarkers, stage)}
        # Deterministic binary-criteria pass (no free-text LLM call) for demo latency.
        findings = [_to_finding(t) for t in search_trials(patient, use_llm=False)]
        return {"findings": findings, "source": "trials_agent"}
    except Exception as exc:  # noqa: BLE001 — the demo must survive any agent failure
        log.warning(
            "trials agent unavailable (%s: %s); falling back to canned trials.json",
            type(exc).__name__,
            exc,
        )
        return _canned(biomarkers, cancer_type, stage)
