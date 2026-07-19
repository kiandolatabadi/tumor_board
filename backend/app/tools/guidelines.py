"""check_guideline_coverage — backed by the repo-root guidelines agent.

The tool builds a top-level ``features`` override (the matcher's authoring/testing
hook, see agents/guidelines/matcher.py) from the inputs the orchestrator passes,
runs the real agent (deterministic triage -> shelf lookup -> bounded synthesis),
and returns its contract-(A) findings. On ANY error it falls back to the canned
guidelines.json table so the demo never breaks — the fallback is logged loudly.
"""
from __future__ import annotations

import logging

from ._data import load

log = logging.getLogger(__name__)

SCHEMA = {
    "name": "check_guideline_coverage",
    "description": (
        "Look up guideline-preferred options for the patient's cancer type/stage/biomarker "
        "(and, when known, age/sex/therapy class — these gate fertility- and germline-testing "
        "recommendations) and return each with its Class-of-Recommendation / Level-of-Evidence "
        "grade and whether the chart already addresses it. The orchestrator compares these "
        "against what the transcript actually discussed to find gaps."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cancer_type": {"type": "string"},
            "stage": {"type": "string"},
            "biomarkers": {"type": "array", "items": {"type": "string"}},
            "age": {"type": "integer", "description": "Patient age in years, if known."},
            "sex": {"type": "string", "description": "Patient sex, if known."},
            "therapy_class": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Planned or current therapy classes, if known — e.g. 'gonadotoxic', "
                    "'endocrine', 'chemotherapy'. Gates fertility-preservation coverage."
                ),
            },
        },
        "required": ["cancer_type"],
    },
}


def _features(
    cancer_type: str,
    stage: str | None,
    biomarkers: list[str] | None,
    age: int | None,
    sex: str | None,
    therapy_class: list[str] | None,
) -> dict:
    """Map the tool inputs to the matcher's top-level ``features`` override."""
    features: dict = {"cancer": [cancer_type] if cancer_type else []}
    if stage:
        features["stage"] = [stage]
    if biomarkers:
        features["biomarkers_present"] = list(biomarkers)
    if age is not None:
        features["age"] = age
    if sex:
        features["sex"] = sex
    if therapy_class:
        features["planned_therapy_class"] = list(therapy_class)
    return features


def _canned(cancer_type: str, stage: str | None = None, biomarkers: list[str] | None = None) -> dict:
    """The original canned-table behavior — honest factice data, the bail-out."""
    table = load("guidelines.json")
    options = [
        g
        for g in table
        if cancer_type.lower() in g["cancer_type"].lower()
        and (stage is None or stage.lower() in g.get("stage", "").lower() or not g.get("stage"))
    ]
    return {"guideline_options": options, "source": "guidelines.json (canned fallback)"}


def run(
    cancer_type: str,
    stage: str | None = None,
    biomarkers: list[str] | None = None,
    age: int | None = None,
    sex: str | None = None,
    therapy_class: list[str] | None = None,
) -> dict:
    try:
        from agents.guidelines import check_guideline_coverage

        patient = {"features": _features(cancer_type, stage, biomarkers, age, sex, therapy_class)}
        # Deterministic (no synthesis LLM call) for demo latency — findings, grades,
        # and evidence still come from the shelf; the orchestrator synthesizes narrative.
        findings = check_guideline_coverage(patient, use_llm=False)
        return {"findings": findings, "source": "guidelines_agent"}
    except Exception as exc:  # noqa: BLE001 — the demo must survive any agent failure
        log.warning(
            "guidelines agent unavailable (%s: %s); falling back to canned guidelines.json",
            type(exc).__name__,
            exc,
        )
        return _canned(cancer_type, stage, biomarkers)
