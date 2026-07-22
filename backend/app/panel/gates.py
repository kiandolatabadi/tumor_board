"""Hard safety gates — enforced in code, never left to a prompt.

Two rules the architecture guarantees regardless of what any model said:

1. OPERABILITY: a finding that proposes performing a surgical/invasive procedure
   may only stand as ``cleared`` if a specialist actually cleared operability.
   Otherwise it is forced to ``not_confirmed`` and relabeled. A judge poking at
   edge cases is exactly how a prompt-only version of this rule quietly breaks —
   so it lives here (README §5, "hard architectural rule").

2. These are backstops on top of the model's own judgment, not replacements for
   it: the synthesis step is still asked to set the fields correctly; this makes
   sure it cannot be wrong in the unsafe direction.
"""
from __future__ import annotations

import re

from .schema import Finding, SpecialistOpinion

# A recommendation that PROPOSES a procedure: a procedure noun AND a proposing verb.
# Mention alone ("document rationale for surgery vs radiotherapy") is not a proposal.
_PROC_NOUN = re.compile(
    r"\b(surg\w*|resect\w+|lobectom\w+|pneumonectom\w+|metastasectom\w+|biops\w+|"
    r"ablat\w+|invasive procedure|operat\w+)\b",
    re.I,
)
_PROPOSE_VERB = re.compile(
    r"\b(offer\w*|proceed\w*|perform\w*|schedul\w*|pursu\w*|undergo\w*|opt for|"
    r"recommend\w*|resect\w*)\b",
    re.I,
)


def _proposes_procedure(f: Finding) -> bool:
    if f.proposes_procedure:
        return True
    return bool(_PROC_NOUN.search(f.recommendation) and _PROPOSE_VERB.search(f.recommendation))


def _operability_cleared(opinions: list[SpecialistOpinion]) -> bool:
    """Did any specialist explicitly clear operability? Internal medicine (or
    cardiology/surgery) 'recommend'/'defer' claims about operability count as a
    clearance signal only when the stance affirmatively clears — a 'caution' or
    'oppose' never does."""
    for o in opinions:
        for c in o.claims:
            if "operab" in c.about.lower() or "operab" in c.statement.lower() or "fitness" in c.about.lower():
                if c.stance == "recommend":
                    return True
    return False


def apply_operability_gate(
    findings: list[Finding],
    opinions: list[SpecialistOpinion],
) -> list[Finding]:
    """Relabel any procedure-proposing finding that isn't backed by a clearance."""
    cleared = _operability_cleared(opinions)
    for f in findings:
        if not _proposes_procedure(f):
            continue
        f.proposes_procedure = True
        if cleared and f.operability_status != "not_confirmed":
            f.operability_status = "cleared"
        else:
            if f.operability_status != "not_confirmed":
                f.operability_status = "not_confirmed"
            marker = "[guideline-preferred — operability not yet confirmed]"
            if marker not in f.recommendation:
                f.recommendation = f"{f.recommendation}  {marker}"
    return findings
