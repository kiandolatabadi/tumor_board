"""Care-domain vocabulary — what a goals-of-care conversation ADDRESSED.

Dependency-free by design: both the Stage 2 contract (`app/stage2/`) and the
pre-split schema (`app/case_schema.py`) import from here, so neither layer has to
depend on the other and the vocabulary has exactly one definition.

Mechanical throughout. Stage 2 records which domains a document covers; deciding
whether a covered domain answers a given clinical question is Stage 3's join.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class CareDomain(str, Enum):
    """What a goals-of-care conversation ADDRESSED. A record is only informative
    about the domains it actually covered: a conversation about resuscitation says
    nothing about whether to pursue a clinical trial. Mechanical vocabulary — Stage
    2 records which domains a document covers; deciding whether a given domain
    answers a given clinical question is Stage 3's."""
    resuscitation = "resuscitation"                        # code status, DNR/DNI
    life_sustaining_treatment = "life_sustaining_treatment"  # ventilation, dialysis, artificial nutrition
    systemic_therapy = "systemic_therapy"                  # chemo, targeted, immunotherapy
    surgery = "surgery"                                    # operative / invasive intervention
    radiation = "radiation"
    clinical_trials = "clinical_trials"
    hospice_referral = "hospice_referral"
    symptom_management = "symptom_management"


class ScopeSource(str, Enum):
    """How `covers` was established. `absent` is meaningful: it says the source
    never recorded a scope, which is different from recording an empty one."""
    coded = "coded"                          # the source carried an explicit scope list
    derived_from_text = "derived_from_text"  # deterministic keyword scan of the record text
    absent = "absent"


# Deterministic text -> domain mapping. Keyword matching only: no judgment about
# whether the domain applies to a patient, just which topics the text mentions.
_DOMAIN_PATTERNS: dict[CareDomain, str] = {
    CareDomain.resuscitation: r"\b(dnr|dni|do not resuscitate|do not intubate|code status|resuscitat\w+|full code)\b",
    CareDomain.life_sustaining_treatment: r"\b(ventilat\w+|intubat\w+|dialysis|life[- ]sustaining|artificial (?:nutrition|hydration)|feeding tube|tracheostomy)\b",
    CareDomain.systemic_therapy: r"\b(chemo\w*|systemic therapy|immunotherap\w+|targeted therapy|infusion|cytotoxic)\b",
    CareDomain.surgery: r"\b(surg\w+|operat\w+|resect\w+|lobectom\w+|invasive procedure)\b",
    CareDomain.radiation: r"\b(radiat\w+|radiotherap\w+|rt\b|sbrt|brachytherap\w+)\b",
    CareDomain.clinical_trials: r"\b(clinical trial|trial enroll\w*|investigational|study drug)\b",
    CareDomain.hospice_referral: r"\b(hospice|end[- ]of[- ]life care)\b",
    CareDomain.symptom_management: r"\b(symptom\w*|palliat\w+|pain (?:control|management)|comfort measures)\b",
}


def derive_care_domains(*texts: Optional[str]) -> list[CareDomain]:
    """Which care domains the given text mentions. Deterministic and mechanical —
    used when a source records a goals-of-care conversation as prose rather than
    as a coded scope."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob.strip():
        return []
    return [d for d, pat in _DOMAIN_PATTERNS.items() if re.search(pat, blob, re.I)]
