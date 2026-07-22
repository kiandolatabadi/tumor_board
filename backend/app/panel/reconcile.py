"""Reconciliation: find where specialists contradict or depend on each other.

After the parallel pass, one Claude call reads every specialist's claims and needs
and reports the tensions — a contradiction (two specialists take opposing stances
on the same topic) or a dependency (one specialist needs another's answer to
finish). These are what the orchestrator then routes into cross-examination.
"""
from __future__ import annotations

from .llm import call_json
from .schema import Conflict, SpecialistOpinion

_SYSTEM = (
    "You are the tumor-board coordinator reconciling the specialists' opinions. "
    "Read their claims and needs and identify the real tensions between them:\n"
    "- contradiction: two specialists take opposing stances on the SAME topic "
    "(e.g. oncology recommends a drug cardiology cautions against).\n"
    "- dependency: one specialist's finding is unresolved until another answers "
    "(e.g. surgery's option is not ready until internal medicine rules on operability).\n\n"
    "Only report genuine, decision-relevant tensions — not stylistic differences, "
    "and not two specialists simply covering different ground. If there are none, "
    "return an empty list.\n\n"
    "Return ONLY JSON: {\"conflicts\": [ {\"kind\":\"contradiction\"|\"dependency\","
    "\"topic\":\"...\",\"description\":\"...\",\"specialists\":[\"name\",\"name\"]} ]}"
)


def _digest(opinions: list[SpecialistOpinion]) -> str:
    parts = []
    for o in opinions:
        claims = "; ".join(f"[{c.stance} {c.about}] {c.statement}" for c in o.claims) or "(none)"
        needs = "; ".join(o.needs) or "(none)"
        parts.append(
            f"### {o.specialist} ({o.title}) — confidence {o.confidence:.2f}\n"
            f"summary: {o.summary}\nclaims: {claims}\nneeds: {needs}"
        )
    return "\n\n".join(parts)


def find_conflicts(opinions: list[SpecialistOpinion]) -> list[Conflict]:
    """Return the tensions between specialists (possibly empty)."""
    active = [o for o in opinions if o.confidence > 0]
    if len(active) < 2:
        return []
    try:
        data, _ = call_json(_SYSTEM, _digest(active))
    except Exception:
        return []  # reconciliation is best-effort; a failure just skips round 2
    conflicts: list[Conflict] = []
    for c in data.get("conflicts", []):
        try:
            conflicts.append(Conflict(**c))
        except Exception:
            continue
    return conflicts
