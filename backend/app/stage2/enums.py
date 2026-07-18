"""Closed enumerations for the PatientCaseBundle.

These MUST match `docs/stage-interface-contract.yaml` §6 exactly — a drift test
(test_stage2_bundle.py) loads the contract and asserts equality, so a rename here
or there fails loudly instead of silently diverging across the seam.
"""
from __future__ import annotations

from enum import Enum


class TriState(str, Enum):
    positive = "positive"
    negative = "negative"
    equivocal = "equivocal"
    unknown = "unknown"


class BiomarkerCategory(str, Enum):
    mutation = "mutation"
    fusion = "fusion"
    expression = "expression"
    amplification = "amplification"
    signature = "signature"
    other = "other"


class MedIntent(str, Enum):
    current = "current"
    proposed = "proposed"


class PerfScale(str, Enum):
    ECOG = "ECOG"
    Karnofsky = "Karnofsky"


class TreatmentKind(str, Enum):
    surgery = "surgery"
    systemic = "systemic"
    radiation = "radiation"
    ablation = "ablation"
    transplant = "transplant"
    other = "other"


class StageGroup(str, Enum):
    s0 = "0"
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"
    unknown = "unknown"


# Care-domain vocabulary lives in app/care_domains.py — a dependency-free module
# both the Stage 2 contract and the pre-split schema import, so neither layer
# depends on the other. Re-exported here so it reads as part of this contract.
from ..care_domains import CareDomain, ScopeSource, derive_care_domains  # noqa: E402,F401
